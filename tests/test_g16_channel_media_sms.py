"""G16 — channel media out (H070) and voice notes (H528).

Owner-side behaviour, attacker-side refusals:

* a reply of the owner's running Telegram turn attaches the files it names with
  ``MEDIA:`` lines — only files under an approved output folder, never through ``..``,
  a link, a hidden folder, a secret-like name or past the size cap, and never to a
  non-owner or from a notice outside the turn; a file already delivered to the chat is
  not sent twice (G15's delivery ledger);
* audio goes out as a native voice note: Ogg/Opus, MP3 and M4A as they are, anything
  else converted to Opus by ffmpeg, and without ffmpeg as an audio file with a note.

Hermetic: a recording fake for Telegram, temporary data roots, no network.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from agents.core.channels import audio_container, delivery_ledger, media_delivery
from agents.core.channels import telegram as telegram_module
from agents.core.channels.spoken_reply import Audio
from agents.core.channels.telegram import TelegramChannel

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415478"
    "9c6360f8cf000000030101001898c3ef0000000049454e44ae426082")


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(root))
    monkeypatch.delenv(media_delivery.DIRS_ENV, raising=False)
    monkeypatch.delenv(media_delivery.MAX_BYTES_ENV, raising=False)
    store = delivery_ledger.ReliabilityStore(root / "rel.db")
    delivery_ledger.set_store(store)
    yield root
    delivery_ledger.set_store(None)
    store.close()


@pytest.fixture
def outputs(data_root):
    out = data_root / "outputs"
    out.mkdir()
    return out


# ── H070: the delivery-path allowlist ────────────────────────────────────────


def test_a_file_in_an_output_folder_is_deliverable(outputs):
    (outputs / "chart.png").write_bytes(PNG)
    item = media_delivery.resolve(str(outputs / "chart.png"))
    assert isinstance(item, media_delivery.DeliverableFile)
    assert (item.name, item.mime, item.kind) == ("chart.png", "image/png", "image")
    assert item.sha256 == hashlib.sha256(PNG).hexdigest()


def test_traversal_is_refused_before_anything_is_resolved(outputs, data_root):
    (data_root / "settings.json").write_text("{}")
    refusal = media_delivery.resolve(str(outputs / ".." / "settings.json"))
    assert refusal == media_delivery.Refusal(media_delivery.REASON_TRAVERSAL)


def test_a_relative_path_is_refused(outputs):
    assert media_delivery.resolve("outputs/chart.png").reason == media_delivery.REASON_NOT_ABSOLUTE


def test_a_file_outside_every_approved_folder_is_refused(outputs, tmp_path):
    elsewhere = tmp_path / "elsewhere.png"
    elsewhere.write_bytes(PNG)
    assert media_delivery.resolve(str(elsewhere)).reason == media_delivery.REASON_OUTSIDE


def test_a_link_inside_an_approved_folder_that_points_out_is_refused(outputs, tmp_path):
    secret = tmp_path / "id_material.txt"
    secret.write_text("private")
    (outputs / "innocent.png").symlink_to(secret)
    assert media_delivery.resolve(str(outputs / "innocent.png")).reason == media_delivery.REASON_OUTSIDE


def test_a_link_to_a_file_inside_the_folder_is_still_refused(outputs):
    (outputs / "real.png").write_bytes(PNG)
    (outputs / "alias.png").symlink_to(outputs / "real.png")
    assert media_delivery.resolve(str(outputs / "alias.png")).reason == media_delivery.REASON_SYMLINK


def test_a_linked_directory_that_escapes_is_refused(outputs, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.png").write_bytes(PNG)
    (outputs / "door").symlink_to(outside, target_is_directory=True)
    assert media_delivery.resolve(str(outputs / "door" / "x.png")).reason == media_delivery.REASON_OUTSIDE


@pytest.mark.parametrize("name", ["id_rsa", "server.pem", "api.key", "secrets.txt", ".env",
                                  "credentials.json", "hub.db", "github_token.txt", "store.enc"])
def test_secret_like_names_are_refused_even_in_an_approved_folder(outputs, name):
    (outputs / name).write_bytes(b"material")
    assert media_delivery.resolve(str(outputs / name)).reason in (
        media_delivery.REASON_SECRET_NAME, media_delivery.REASON_PROTECTED)


def test_a_hidden_folder_inside_an_approved_folder_is_refused(outputs):
    (outputs / ".ssh").mkdir()
    (outputs / ".ssh" / "chart.png").write_bytes(PNG)
    assert media_delivery.resolve(str(outputs / ".ssh" / "chart.png")).reason == media_delivery.REASON_PROTECTED


def test_the_size_cap_and_empty_files(outputs, monkeypatch):
    monkeypatch.setenv(media_delivery.MAX_BYTES_ENV, "100")
    (outputs / "big.bin").write_bytes(b"x" * 101)
    (outputs / "empty.bin").write_bytes(b"")
    assert media_delivery.resolve(str(outputs / "big.bin")).reason == media_delivery.REASON_TOO_LARGE
    assert media_delivery.resolve(str(outputs / "empty.bin")).reason == media_delivery.REASON_EMPTY
    monkeypatch.setenv(media_delivery.MAX_BYTES_ENV, str(10 ** 12))
    assert media_delivery.max_bytes() == media_delivery.MAX_BYTES_CEILING


def test_an_owner_listed_folder_widens_the_set_but_never_to_a_protected_place(
        data_root, tmp_path, monkeypatch):
    extra = tmp_path / "renders"
    extra.mkdir()
    (extra / "a.png").write_bytes(PNG)
    listed = os.pathsep.join([str(extra), str(data_root), "/", str(data_root / "security"), "relative/dir"])
    (data_root / "security").mkdir()
    monkeypatch.setenv(media_delivery.DIRS_ENV, listed)
    roots = media_delivery.allowed_roots()
    assert roots == [extra.resolve()], "the data root, / and the security folder never become roots"
    assert isinstance(media_delivery.resolve(str(extra / "a.png")), media_delivery.DeliverableFile)
    (data_root / "security" / "keys.png").write_bytes(PNG)
    assert media_delivery.resolve(str(data_root / "security" / "keys.png")).reason == media_delivery.REASON_OUTSIDE


def test_directives_are_taken_out_of_the_words():
    text = "Here it is.\nMEDIA: /a/b.png\n  MEDIA:`/a/c.ogg`\nMEDIA: /a/b.png\nThanks."
    cleaned, paths = media_delivery.extract_directives(text)
    assert paths == ["/a/b.png", "/a/c.ogg"]
    assert "MEDIA" not in cleaned and cleaned.startswith("Here it is.") and cleaned.endswith("Thanks.")
    assert media_delivery.extract_directives("no media here") == ("no media here", [])
    # only a line of its own is a directive
    assert media_delivery.extract_directives("say MEDIA: /x mid-sentence")[1] == []


# ── H070 on Telegram: who gets a file, and once ──────────────────────────────


class _Response:
    def __init__(self, status=200):
        self.status_code = status
        self.is_success = status < 400

    def json(self):
        return {"ok": self.is_success, "result": {"message_id": 7}} if self.is_success else {"ok": False}

    def raise_for_status(self):
        if not self.is_success:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, statuses=None):
        self.calls: list[tuple[str, dict]] = []
        self.statuses = dict(statuses or {})
        self.is_closed = False

    async def post(self, url, json=None, data=None, files=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, {"json": json, "data": data, "files": files}))
        queue = self.statuses.get(method)
        return _Response(queue.pop(0) if queue else 200)

    def methods(self):
        return [m for m, _ in self.calls]

    def texts(self):
        return [(c["json"] or {}).get("text", "") for m, c in self.calls if m == "sendMessage"]


def _telegram():
    ch = TelegramChannel(token="t")
    ch.client = _Client()
    return ch


class _Turn:
    """Run code as the chat's running turn, spoken by *admin* or a guest."""

    def __init__(self, ch, chat=42, admin=True):
        self.ch, self.chat, self.admin = ch, chat, admin

    def __enter__(self):
        from agents.core.commands import Principal
        from agents.core.orchestrator import bind_turn_principal

        self.scope = telegram_module._TurnScope(self.ch, self.chat)
        self.t1 = telegram_module._RUNNING_TURN.set(self.scope)
        self.t2 = bind_turn_principal(Principal(channel="telegram", sender=str(self.chat),
                                                admin=self.admin, chat=str(self.chat)))
        return self

    def __exit__(self, *exc):
        from agents.core.orchestrator import reset_turn_principal

        reset_turn_principal(self.t2)
        telegram_module._RUNNING_TURN.reset(self.t1)


async def test_the_owners_turn_attaches_an_allowed_file_after_the_words(outputs):
    (outputs / "chart.png").write_bytes(PNG)
    ch = _telegram()
    with _Turn(ch):
        ok = await ch.send(f"Your chart:\nMEDIA: {outputs / 'chart.png'}", chat_id=42)
    assert ok
    assert ch.client.methods() == ["sendMessage", "sendPhoto"]
    assert "MEDIA" not in ch.client.texts()[0]
    name, data, mime = ch.client.calls[1][1]["files"]["photo"]
    assert (name, data, mime) == ("chart.png", PNG, "image/png")


async def test_a_refused_file_is_named_by_reason_never_by_path(outputs, tmp_path):
    secret = tmp_path / "notes.txt"
    secret.write_text("private")
    ch = _telegram()
    with _Turn(ch):
        await ch.send(f"Done.\nMEDIA: {secret}\nMEDIA: {outputs}/../x", chat_id=42)
    assert ch.client.methods() == ["sendMessage", "sendMessage"]
    notice = ch.client.texts()[1]
    assert "Attachment 1 was not sent" in notice and "Attachment 2 was not sent" in notice
    assert str(tmp_path) not in notice and "notes.txt" not in notice


async def test_a_guest_never_receives_a_file(outputs):
    (outputs / "chart.png").write_bytes(PNG)
    ch = _telegram()
    with _Turn(ch, admin=False):
        await ch.send(f"MEDIA: {outputs / 'chart.png'}", chat_id=42)
    assert ch.client.methods() == ["sendMessage"]
    assert "only to the owner" in ch.client.texts()[0]


async def test_outside_the_turn_a_media_line_is_just_text(outputs):
    (outputs / "chart.png").write_bytes(PNG)
    ch = _telegram()
    await ch.send(f"MEDIA: {outputs / 'chart.png'}", chat_id=42)          # a digest, a notice
    with _Turn(ch):
        await ch.send(f"MEDIA: {outputs / 'chart.png'}", chat_id=42, plain=True)  # an outside notice
    assert ch.client.methods() == ["sendMessage", "sendMessage"]
    assert all("MEDIA:" in t for t in ch.client.texts())


async def test_the_same_file_is_delivered_to_a_chat_once(outputs):
    (outputs / "chart.png").write_bytes(PNG)
    ch = _telegram()
    with _Turn(ch):
        await ch.send(f"one\nMEDIA: {outputs / 'chart.png'}", chat_id=42)
        await ch.send(f"two\nMEDIA: {outputs / 'chart.png'}", chat_id=42)
    assert ch.client.methods().count("sendPhoto") == 1


async def test_the_kernel_decides_when_it_is_on(outputs, monkeypatch):
    from agents.core.kernel import Decision, Verdict

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    (outputs / "chart.png").write_bytes(PNG)
    seen = []
    ch = _telegram()
    ch.media_kernel = lambda action: seen.append(action) or Decision(Verdict.QUEUE, reason="ask")
    with _Turn(ch):
        await ch.send(f"MEDIA: {outputs / 'chart.png'}", chat_id=42)
    assert seen and seen[0].kind == "channel.reply"
    assert seen[0].payload["attachment"]["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert "sendPhoto" not in ch.client.methods()
    assert "approval" in ch.client.texts()[-1]
    ch2 = _telegram()   # kernel on, nothing bound: refused, never sent unmediated
    with _Turn(ch2):
        await ch2.send(f"MEDIA: {outputs / 'chart.png'}", chat_id=42)
    assert "sendPhoto" not in ch2.client.methods()


# ── H528: native voice notes ─────────────────────────────────────────────────


def _wav(seconds=0.2, rate=8000) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


OGG_OPUS = b"OggS\x00\x02" + b"\x00" * 22 + b"OpusHead" + b"\x00" * 20


def test_the_container_is_sniffed_from_the_bytes():
    assert audio_container.sniff(OGG_OPUS) == "ogg_opus"
    assert audio_container.sniff(_wav()) == "wav"
    assert audio_container.sniff(b"ID3\x04clip") == "mp3"
    assert audio_container.sniff(b"fLaC" + b"\x00" * 20) == "flac"
    assert audio_container.sniff(b"garbage bytes here") == "unknown"


def test_voice_ready_audio_goes_as_it_is():
    clip = audio_container.prepare_voice(OGG_OPUS, ffmpeg=False)
    assert (clip.mode, clip.mime, clip.filename, clip.converted) == ("voice", "audio/ogg", "reply.ogg", False)
    assert audio_container.prepare_voice(b"ID3\x04clip", ffmpeg=False).mode == "voice"


def test_without_ffmpeg_a_wav_is_sent_as_audio_with_a_note():
    clip = audio_container.prepare_voice(_wav(), declared_mime="audio/wav", ffmpeg=False)
    assert (clip.mode, clip.mime, clip.note) == ("audio", "audio/wav", audio_container.NOTE_NO_FFMPEG)


def test_with_ffmpeg_a_wav_becomes_an_opus_voice_note():
    converted = audio_container.prepare_voice(_wav(), ffmpeg="/bin/ffmpeg",
                                              convert=lambda data, binary, container: OGG_OPUS)
    assert (converted.mode, converted.mime, converted.converted) == ("voice", "audio/ogg", True)
    failed = audio_container.prepare_voice(_wav(), ffmpeg="/bin/ffmpeg", convert=lambda d, b, c: None)
    assert (failed.mode, failed.note) == ("audio", audio_container.NOTE_CONVERT_FAILED)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_the_real_ffmpeg_conversion_produces_ogg_opus():
    try:
        clip = audio_container.prepare_voice(_wav())
    except subprocess.SubprocessError:  # pragma: no cover
        pytest.skip("ffmpeg could not run here")
    if clip.mode != "voice":   # an ffmpeg built without libopus
        pytest.skip("this ffmpeg has no Opus encoder")
    assert audio_container.sniff(clip.data) == "ogg_opus"


async def test_telegram_sends_a_wav_without_ffmpeg_as_audio_with_the_note(monkeypatch):
    monkeypatch.setattr(audio_container, "ffmpeg_path", lambda: None)
    ch = _telegram()
    assert await ch._send_voice(42, Audio(ok=True, data=_wav(), mime="audio/wav"))
    assert ch.client.methods() == ["sendAudio"]
    assert ch.client.calls[0][1]["data"]["caption"] == audio_container.NOTE_NO_FFMPEG


async def test_an_audio_file_named_in_a_reply_arrives_as_a_voice_note(outputs):
    (outputs / "answer.ogg").write_bytes(OGG_OPUS)
    ch = _telegram()
    with _Turn(ch):
        await ch.send(f"MEDIA: {outputs / 'answer.ogg'}", chat_id=42)
    assert ch.client.methods() == ["sendVoice"]
    assert ch.client.calls[0][1]["files"]["voice"][2] == "audio/ogg"


# ── G16 security review: regressions (R1–R4 Major, M1–M4 Minor, nits) ────────


async def test_review_r2_the_owner_in_a_group_gets_the_refusal_not_the_file(outputs):
    from agents.core.commands import Principal
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal

    group = -1001234567890
    (outputs / "q3.png").write_bytes(PNG)
    ch = _telegram()
    t1 = telegram_module._RUNNING_TURN.set(telegram_module._TurnScope(ch, group))
    t2 = bind_turn_principal(Principal(channel="telegram", sender="42", admin=True,
                                       chat=str(group), scope="group"))
    try:
        await ch.send(f"Here:\nMEDIA: {outputs / 'q3.png'}", chat_id=group)
    finally:
        reset_turn_principal(t2)
        telegram_module._RUNNING_TURN.reset(t1)
    assert "sendPhoto" not in ch.client.methods()
    assert "private chat" in ch.client.texts()[-1]


def test_review_r3_a_fifo_is_refused_without_opening_it(outputs):
    os.mkfifo(outputs / "report.txt")
    assert media_delivery.resolve(str(outputs / "report.txt")).reason == media_delivery.REASON_NOT_FILE


def test_review_r4_a_non_audio_body_never_reaches_ffmpeg():
    calls = []
    mpd = b'<?xml version="1.0"?><MPD><BaseURL>http://127.0.0.1:9/beacon</BaseURL></MPD>'
    clip = audio_container.prepare_voice(mpd, declared_mime="audio/flac", ffmpeg="/bin/ffmpeg",
                                         convert=lambda *a: calls.append(a))
    assert calls == [] and clip.mode == "document" and clip.mime == "application/octet-stream"


def test_review_r4_ffmpeg_gets_a_forced_demuxer_and_the_pipe_only(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return SimpleNamespace(returncode=1, stdout=b"")

    monkeypatch.setattr(audio_container.subprocess, "run", fake_run)
    audio_container.prepare_voice(_wav(), ffmpeg="/bin/ffmpeg")
    argv = seen["argv"]
    assert argv[argv.index("-protocol_whitelist") + 1] == "pipe" and "-nostdin" in argv
    assert argv[argv.index("-i") - 2:argv.index("-i")] == ["-f", "wav"]


async def test_review_r4_a_fake_audio_file_goes_out_as_a_document(outputs):
    (outputs / "podcast.flac").write_bytes(b"<MPD>not audio at all</MPD>")
    ch = _telegram()
    with _Turn(ch):
        await ch.send(f"MEDIA: {outputs / 'podcast.flac'}", chat_id=42)
    assert ch.client.methods() == ["sendDocument"]


def test_review_m1_a_hard_link_is_refused(outputs, data_root):
    (data_root / "security").mkdir()
    (data_root / "security" / "audit.log").write_text("secret")
    os.link(data_root / "security" / "audit.log", outputs / "summary.txt")
    assert media_delivery.resolve(str(outputs / "summary.txt")).reason == media_delivery.REASON_HARDLINK


def test_review_m2_a_folder_swapped_for_a_link_mid_check_is_refused(outputs, data_root, monkeypatch):
    (data_root / "security").mkdir()
    (data_root / "security" / "audit.log").write_text("secret")
    (outputs / "run").mkdir()
    (outputs / "run" / "audit.log").write_text("harmless")
    real_fn, state = media_delivery._real, {"n": 0}

    def racing(path):
        result = real_fn(path)
        if not state["n"] and str(path).endswith("audit.log"):
            state["n"] = 1
            os.rename(outputs / "run", outputs / "run.old")
            os.symlink(data_root / "security", outputs / "run")
        return result

    monkeypatch.setattr(media_delivery, "_real", racing)
    got = media_delivery.resolve(str(outputs / "run" / "audit.log"), roots=[outputs])
    assert isinstance(got, media_delivery.Refusal)


async def test_review_m3_a_streamed_reply_never_shows_the_path(outputs):
    (outputs / "chart.png").write_bytes(PNG)
    ch = _telegram()
    with _Turn(ch):
        draft = telegram_module.TelegramDraft(ch, 42, interval=0)
        await draft.push("Here you go\nMEDI")
        await draft.push(f"A: {outputs / 'chart.png'}\nand more")
        await draft.finish()
    shown = " ".join(str(c.get("json") or c.get("data") or "") for _, c in ch.client.calls)
    assert str(outputs) not in shown and "MEDIA" not in shown
    assert "sendPhoto" in ch.client.methods()


async def test_review_m4_asking_again_in_a_new_turn_sends_again(outputs):
    (outputs / "chart.png").write_bytes(PNG)
    ch = _telegram()
    with _Turn(ch):
        await ch.send(f"one\nMEDIA: {outputs / 'chart.png'}", chat_id=42)
        await ch.send(f"again\nMEDIA: {outputs / 'chart.png'}", chat_id=42)   # same turn: once
    with _Turn(ch):
        await ch.send(f"later\nMEDIA: {outputs / 'chart.png'}", chat_id=42)   # a new request
    assert ch.client.methods().count("sendPhoto") == 2


def test_review_nits_fenced_examples_and_private_home_folders(tmp_path, monkeypatch, data_root):
    text = "Use it like this:\n```\nMEDIA: /tmp/example.png\n```\n> MEDIA: /tmp/q.png\nDone."
    assert media_delivery.extract_directives(text) == (text, [])
    home = tmp_path / "home"
    (home / ".ssh" / "keys").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(media_delivery.DIRS_ENV, str(home / ".ssh" / "keys"))
    assert media_delivery.allowed_roots() == []
