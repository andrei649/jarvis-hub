"""H427 — a fail-closed checkpoint before compaction discards a transcript.

The compressor summarised the middle of a conversation and the evicted turns left the prompt,
with nothing checking that they had landed anywhere (the conversation store keeps only the
last ``memory.max_turns``). Now every provider sees exactly the turns about to be summarised
away first — the transcript archive writes them, fsynced — and with
``memory.compression_checkpoint_required`` a checkpoint that did not land keeps the transcript
uncompressed, or refuses a turn that would not fit. Every checkpoint and abort is audited.
"""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.context_compressor import CompactionPolicy, ContextCompressor
from agents.core.memory import precompress as pc
from agents.core.memory.precompress import CheckpointAborted, TranscriptArchive


class _Audit:
    def __init__(self):
        self.rows = []

    def log(self, event, fields):
        self.rows.append((event, fields))


class _Provider:
    checkpoint_api_version = 2

    def __init__(self, name="p", error=None):
        self.name, self.error, self.calls = name, error, []

    async def on_pre_compress(self, messages, *, evidence_messages=None, require_checkpoint=False,
                              checkpoint_api_version=0, session_id=""):
        self.calls.append({"messages": messages, "evidence": evidence_messages, "required": require_checkpoint,
                           "version": checkpoint_api_version, "session": session_id})
        if self.error:
            raise self.error
        return {"ok": True}


TURNS = [{"role": "user", "content": f"turn {i}", "timestamp": i} for i in range(4)]


# ── the contract ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("version,counts", [(2, True), (3, True), (1, False), (None, False),
                                            ("2", False), (True, False), (1.5, False)])
def test_only_a_provider_on_the_current_contract_counts_as_a_checkpoint(version, counts):
    provider = SimpleNamespace() if version is None else SimpleNamespace(checkpoint_api_version=version)
    assert pc.is_checkpoint_provider(provider) is counts
    assert pc.CHECKPOINT_API_VERSION == 2


def test_a_provider_is_named_by_its_name_or_its_class():
    assert pc.provider_name(_Provider("archive")) == "archive"
    assert pc.provider_name(SimpleNamespace()) == "SimpleNamespace"


def test_new_keyword_arguments_are_passed_only_to_a_provider_that_takes_them():
    offered = {"evidence_messages": [1], "require_checkpoint": True, "checkpoint_api_version": 2, "session_id": "s"}

    def old(messages):
        return None

    def some(messages, *, session_id=""):
        return None

    def everything(messages, **kwargs):
        return None

    assert pc._accepted_kwargs(old, offered) == {}
    assert pc._accepted_kwargs(some, offered) == {"session_id": "s"}
    assert pc._accepted_kwargs(everything, offered) == offered
    assert pc._accepted_kwargs(object(), offered) == {}          # not inspectable: nothing extra
    assert pc._accepted_kwargs(max, offered) == {}               # a builtin without a signature


async def test_every_provider_sees_exactly_the_evicted_turns_and_the_whole_transcript():
    audit, first, second = _Audit(), _Provider("a"), _Provider("b")
    got = await pc.run_checkpoint([first, second], TURNS[1:3], TURNS, required=False, session_id="s1", audit=audit)
    assert got == {"evicted": 2, "providers": ["a", "b"], "failed": []}
    call = first.calls[0]
    assert call["messages"] == TURNS[1:3] and call["evidence"] == TURNS
    assert (call["required"], call["version"], call["session"]) == (False, 2, "s1")
    assert audit.rows == [(pc.AUDIT_CHECKPOINT, {"session": "s1", "evicted": 2, "providers": ["a", "b"],
                                                 "failed": [], "required": False})]


async def test_a_provider_gets_copies_it_cannot_change_the_transcript_through():
    class _Mutating(_Provider):
        async def on_pre_compress(self, messages, **kwargs):
            messages[0]["content"] = "changed"
            kwargs["evidence_messages"].clear()

    turns = [dict(t) for t in TURNS]
    await pc.run_checkpoint([_Mutating()], turns[:1], turns, required=True)
    assert turns == TURNS


async def test_a_synchronous_provider_runs_off_the_event_loop():
    seen = {}

    class _Sync:
        checkpoint_api_version = 2

        def on_pre_compress(self, messages, session_id=""):
            seen["thread"] = threading.get_ident()
            seen["session"] = session_id

    await pc.run_checkpoint([_Sync()], TURNS[:1], TURNS, required=True, session_id="s")
    assert seen["thread"] != threading.get_ident() and seen["session"] == "s"


async def test_nothing_to_evict_calls_nothing_and_audits_nothing():
    audit, provider = _Audit(), _Provider()
    assert await pc.run_checkpoint([provider], [], TURNS, required=True, audit=audit) == {
        "evicted": 0, "providers": [], "failed": []}
    assert provider.calls == [] and audit.rows == []


async def test_when_not_required_a_failing_provider_is_noted_and_compaction_goes_on(caplog):
    audit, bad, good = _Audit(), _Provider("bad", RuntimeError("disk")), _Provider("good")
    got = await pc.run_checkpoint([bad, good], TURNS[:2], TURNS, required=False, audit=audit)
    assert got == {"evicted": 2, "providers": ["good"], "failed": ["bad"]}
    assert good.calls and audit.rows[0][1]["failed"] == ["bad"]
    assert any("bad failed" in r.getMessage() for r in caplog.records)


async def test_when_not_required_nothing_landing_is_not_an_abort():
    audit = _Audit()
    got = await pc.run_checkpoint([], TURNS[:1], TURNS, required=False, audit=audit)
    assert got["providers"] == [] and audit.rows[0][0] == pc.AUDIT_CHECKPOINT


async def test_when_required_a_failing_checkpoint_aborts_at_once(caplog):
    audit, bad, later = _Audit(), _Provider("archive", OSError("disk full")), _Provider("later")
    with pytest.raises(CheckpointAborted) as err:
        await pc.run_checkpoint([bad, later], TURNS[:2], TURNS, required=True, session_id="s", audit=audit)
    assert str(err.value) == "archive failed the pre-compress checkpoint: OSError"
    assert isinstance(err.value.__cause__, OSError)
    assert later.calls == []
    assert audit.rows == [(pc.AUDIT_ABORT, {"session": "s", "evicted": 2, "provider": "archive",
                                            "reason": str(err.value), "required": True})]
    assert any("stays uncompressed" in r.getMessage() for r in caplog.records)


async def test_when_required_an_old_provider_failing_is_tolerated_but_does_not_count():
    old = _Provider("old", RuntimeError("x"))
    old.checkpoint_api_version = 1
    good = _Provider("good")
    got = await pc.run_checkpoint([old, good], TURNS[:1], TURNS, required=True)
    assert got["providers"] == ["good"] and got["failed"] == ["old"]


async def test_when_required_no_checkpoint_landing_aborts():
    audit, old = _Audit(), _Provider("old")
    old.checkpoint_api_version = 1
    for providers in ([], [old]):
        with pytest.raises(CheckpointAborted) as err:
            await pc.run_checkpoint(providers, TURNS[:1], TURNS, required=True, session_id="s", audit=audit)
        assert str(err.value) == "No active memory provider completed pre-compress checkpoint API v2"
    assert [row[0] for row in audit.rows] == [pc.AUDIT_ABORT, pc.AUDIT_ABORT]
    assert audit.rows[0][1] == {"session": "s", "evicted": 1, "provider": "", "required": True,
                                "reason": "No active memory provider completed pre-compress checkpoint API v2"}


async def test_the_requirement_is_passed_to_the_provider():
    provider = _Provider()
    await pc.run_checkpoint([provider], TURNS[:1], TURNS, required=True)
    assert provider.calls[0]["required"] is True


async def test_a_hook_that_is_not_callable_is_a_failure():
    got = await pc.run_checkpoint([SimpleNamespace(checkpoint_api_version=2, name="x", on_pre_compress="no")],
                                  TURNS[:1], TURNS, required=False)
    assert got["failed"] == ["x"]


async def test_a_provider_without_the_hook_is_a_failure():
    with pytest.raises(CheckpointAborted):
        await pc.run_checkpoint([SimpleNamespace(checkpoint_api_version=2)], TURNS[:1], TURNS, required=True)
    got = await pc.run_checkpoint([SimpleNamespace(checkpoint_api_version=2, name="x")], TURNS[:1], TURNS,
                                  required=False)
    assert got["failed"] == ["x"]


async def test_the_audit_never_breaks_a_checkpoint(caplog):
    class _Broken:
        def log(self, *a):
            raise RuntimeError("intent log down")

    got = await pc.run_checkpoint([_Provider()], TURNS[:1], TURNS, required=True, audit=_Broken())
    assert got["providers"] == ["p"]
    assert any("audit row could not be written" in r.getMessage() for r in caplog.records)
    assert (await pc.run_checkpoint([_Provider()], TURNS[:1], TURNS, required=True, audit=object()))["providers"]


# ── the transcript archive ───────────────────────────────────────────────────────

def test_the_archive_writes_each_evicted_turn_once_and_fsyncs(tmp_path, monkeypatch):
    import os

    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd)))
    archive = TranscriptArchive(tmp_path / "arch")
    assert archive.on_pre_compress(TURNS[:2], session_id="s1") == {"archived": 2, "known": 2}
    assert len(synced) == 1
    assert archive.on_pre_compress(TURNS[:3] + TURNS[2:3], session_id="s1") == {"archived": 1, "known": 3}
    assert archive.on_pre_compress(TURNS[:3], session_id="s1") == {"archived": 0, "known": 3}
    assert len(synced) == 2                         # nothing new, nothing written
    rows = archive.read("s1")
    assert [r["content"] for r in rows] == ["turn 0", "turn 1", "turn 2"]
    assert rows[0]["role"] == "user" and rows[0]["session"] == "s1" and rows[0]["timestamp"] == 0
    assert rows[0]["id"] == pc.turn_id(TURNS[0]) and rows[0]["archived_at"] > 0


def test_a_restarted_archive_remembers_what_it_already_holds(tmp_path):
    TranscriptArchive(tmp_path).on_pre_compress(TURNS[:2], session_id="s")
    again = TranscriptArchive(tmp_path)
    assert again.on_pre_compress(TURNS[:3], session_id="s") == {"archived": 1, "known": 3}
    assert len(again.read("s")) == 3


def test_a_damaged_line_is_skipped_not_fatal(tmp_path):
    archive = TranscriptArchive(tmp_path)
    archive.on_pre_compress(TURNS[:1], session_id="s")
    with archive.path_for("s").open("a", encoding="utf-8") as handle:
        handle.write("not json\n[1]\n{}\n")
    again = TranscriptArchive(tmp_path)
    assert again.on_pre_compress(TURNS[:2], session_id="s") == {"archived": 1, "known": 2}
    assert [r.get("content") for r in again.read("s")] == ["turn 0", None, "turn 1"]


def test_each_session_has_its_own_file_named_by_a_hash(tmp_path):
    archive = TranscriptArchive(tmp_path)
    archive.on_pre_compress(TURNS[:1], session_id="../../etc/passwd")
    archive.on_pre_compress(TURNS[:1], session_id="other")
    files = sorted(p.name for p in tmp_path.iterdir())
    assert len(files) == 2 and all(len(n) == len("0" * 32 + ".jsonl") for n in files)
    assert archive.path_for("../../etc/passwd").parent == tmp_path
    assert archive.path_for("") == archive.path_for("default")
    assert archive.read("never") == []


def test_images_are_not_copied_and_structured_content_is_kept_as_json(tmp_path):
    archive = TranscriptArchive(tmp_path)
    archive.on_pre_compress([{"role": "user", "content": "data:image/png;base64,AAAA"},
                             {"role": "tool", "content": {"b": 1, "a": [2]}}], session_id="s")
    assert [r["content"] for r in archive.read("s")] == ["[image]", '{"a": [2], "b": 1}']


def test_a_turn_is_identified_by_speaker_time_and_content():
    base = {"role": "user", "agent_id": "", "timestamp": 1, "content": "x"}
    assert pc.turn_id(base) == pc.turn_id(dict(base))
    for change in ({"role": "assistant"}, {"agent_id": "jarvis"}, {"timestamp": 2}, {"content": "y"}):
        assert pc.turn_id({**base, **change}) != pc.turn_id(base)
    assert pc.turn_id({"content": {"a": 1, "b": 2}}) == pc.turn_id({"content": {"b": 2, "a": 1}})


def test_the_archive_declares_the_current_contract():
    assert pc.is_checkpoint_provider(TranscriptArchive("/tmp/x")) and TranscriptArchive.name == "transcript_archive"


def test_the_default_archive_lives_in_the_data_folder(tmp_path, monkeypatch):
    import agents.core.paths as paths

    monkeypatch.setattr(paths, "data_path", lambda name: tmp_path / name)
    pc.set_default_providers(None)
    try:
        providers = pc.default_providers()
        assert len(providers) == 1 and providers[0].root == tmp_path / "compaction_archive"
        assert pc.default_providers()[0] is providers[0]
        pc.set_default_providers([])
        assert pc.default_providers() == []
    finally:
        pc.set_default_providers(None)


# ── the compressor ───────────────────────────────────────────────────────────────

LONG = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"{i} " + "x" * 800} for i in range(10)]


async def test_the_checkpoint_sees_exactly_the_turns_the_summary_replaces_before_it_is_built():
    order, seen = [], {}

    async def checkpoint(evicted, transcript):
        order.append("checkpoint")
        seen["evicted"], seen["transcript"] = evicted, transcript

    async def summarize(text):
        order.append("summary")
        return "short summary"

    comp = ContextCompressor(summarizer=summarize, max_tokens=500, keep_recent=3, keep_first=2, checkpoint=checkpoint)
    out = await comp.compress(LONG)
    assert order == ["checkpoint", "summary"] and out["compressed"] is True
    assert seen["evicted"] == LONG[2:-3] and seen["transcript"] == LONG
    assert out["evicted"] == len(seen["evicted"])


async def test_with_a_prior_summary_the_checkpoint_still_sees_every_evicted_turn():
    seen = {}

    async def checkpoint(evicted, transcript):
        seen["evicted"] = evicted

    comp = ContextCompressor(max_tokens=500, keep_recent=2, checkpoint=checkpoint)
    await comp.compress(LONG, prior={"summary": "earlier", "covered": 3})
    assert seen["evicted"] == LONG[:-2]


async def test_an_aborted_checkpoint_keeps_the_transcript_and_builds_no_summary():
    called = []

    async def checkpoint(evicted, transcript):
        raise CheckpointAborted("archive failed")

    async def summarize(text):
        called.append(text)
        return "s"

    comp = ContextCompressor(summarizer=summarize, max_tokens=500, keep_recent=2, checkpoint=checkpoint)
    out = await comp.compress(LONG)
    assert out["compressed"] is False and out["kept"] == LONG and out["summary"] == ""
    assert out["evicted"] == 0 and out["checkpoint_aborted"] == "archive failed" and called == []
    assert out["tokens"] == sum(comp._turn_tokens(t) for t in LONG)


async def test_nothing_over_budget_calls_no_checkpoint():
    called = []

    async def checkpoint(evicted, transcript):
        called.append(evicted)

    out = await ContextCompressor(max_tokens=100_000, checkpoint=checkpoint).compress(LONG)
    assert out["compressed"] is False and called == []


async def test_compact_fails_closed_with_the_transcript_untouched():
    sink = []
    rows = LONG[:6] + [{"role": "user", "content": "data:image/png;base64,AAAA"}] + LONG[6:]

    async def checkpoint(evicted, transcript):
        raise CheckpointAborted("no archive")

    comp = ContextCompressor(max_tokens=500, checkpoint=checkpoint)
    policy = CompactionPolicy(protect_head=1, protect_last_n=2, per_model={"m": 4000})
    out = await comp.compact(rows, model="m", policy=policy, session_id="s", sink=sink.append)
    assert out["kept"] == rows and out["kept_first"] == [] and out["compressed"] is False
    assert (out["tier"], out["images_dropped"], out["lineage"], out["evicted"]) == ("none", 0, None, 0)
    assert out["checkpoint_aborted"] == "no archive" and out["window"] == 4000
    assert out["tokens"] == comp._used(rows, None)
    assert sink == []                              # no lineage row for a compaction that did not happen
    assert (comp.keep_first, comp.keep_recent, comp.max_tokens) == (0, 4, 500)


# ── the orchestrator ─────────────────────────────────────────────────────────────

def _store(tmp_path):
    from agents.core.checkpoint import CheckpointManager

    manager = CheckpointManager(str(tmp_path / "clock.db"))
    manager.initialize()
    manager.create_session_record("a")
    return manager


def _stub(manager, *, required=False, providers=None, window=100_000, audit=None):
    settings = {"memory.context_compression": True, "memory.compression_max_tokens": 500,
                pc.SETTING_REQUIRED: required}

    async def history(*args):
        return [dict(t) for t in LONG]

    stub = SimpleNamespace(
        session_id="a", checkpoints=manager, get_setting=lambda key, default=None: settings.get(key, default),
        memory=SimpleNamespace(get_history=history), _compaction_model=lambda: "local",
        _compaction_policy=lambda: CompactionPolicy(per_model={"local": window}), _usage_anchor=lambda n: None,
        action_audit=audit if audit is not None else _Audit())
    if providers is not None:
        stub.precompress_providers = providers
    return stub


async def test_a_compaction_archives_the_evicted_turns_and_is_audited(tmp_path):
    from agents.core.orchestrator import Orchestrator

    manager, archive, audit = _store(tmp_path), TranscriptArchive(tmp_path / "arch"), _Audit()
    out = await Orchestrator._history_for_prompt(_stub(manager, providers=[archive], audit=audit), 10)
    assert "[summary of earlier conversation]" in out
    archived = archive.read("a")
    assert archived and all(r["session"] == "a" for r in archived)
    assert [r["content"] for r in archived] == [t["content"] for t in LONG[2:-6]]
    assert audit.rows[-1][0] == pc.AUDIT_CHECKPOINT and audit.rows[-1][1]["providers"] == ["transcript_archive"]
    assert manager.clock_snapshot("a").revision == 1
    manager.close()


async def test_a_required_checkpoint_that_fails_keeps_the_transcript(tmp_path):
    from agents.core.orchestrator import Orchestrator

    manager, audit = _store(tmp_path), _Audit()
    stub = _stub(manager, required=True, providers=[_Provider("archive", OSError("disk full"))], audit=audit)
    out = await Orchestrator._history_for_prompt(stub, 10)
    assert "[summary" not in out and all(t["content"] in out for t in LONG)
    assert manager.clock_snapshot("a").revision == 0        # nothing committed
    assert audit.rows == [(pc.AUDIT_ABORT, {"session": "a", "evicted": 2, "provider": "archive", "required": True,
                                            "reason": "archive failed the pre-compress checkpoint: OSError"})]
    manager.close()


async def test_without_the_requirement_a_failing_provider_does_not_stop_compaction(tmp_path):
    from agents.core.orchestrator import Orchestrator

    manager = _store(tmp_path)
    stub = _stub(manager, required=False, providers=[_Provider("archive", OSError("disk full"))])
    out = await Orchestrator._history_for_prompt(stub, 10)
    assert "[summary of earlier conversation]" in out and manager.clock_snapshot("a").revision == 1
    manager.close()


async def test_a_required_checkpoint_with_no_provider_keeps_the_transcript(tmp_path):
    from agents.core.orchestrator import Orchestrator

    manager = _store(tmp_path)
    out = await Orchestrator._history_for_prompt(_stub(manager, required=True, providers=[]), 10)
    assert "[summary" not in out
    manager.close()


async def test_a_prompt_that_cannot_fit_uncompressed_is_refused(tmp_path):
    from agents.core.conversation_clock import CompactionClockRefused
    from agents.core.orchestrator import Orchestrator

    manager = _store(tmp_path)
    used = sum(ContextCompressor.estimate_tokens(t["content"]) for t in LONG)
    stub = _stub(manager, required=True, providers=[], window=used)
    with pytest.raises(CompactionClockRefused):
        await Orchestrator._history_for_prompt(stub, 10)
    fits = _stub(manager, required=True, providers=[], window=used + 1)
    assert "[summary" not in await Orchestrator._history_for_prompt(fits, 10)
    manager.close()


async def test_only_a_literal_true_requires_the_checkpoint(tmp_path):
    from agents.core.orchestrator import Orchestrator

    manager = _store(tmp_path)
    for value in ("true", 1, None):
        stub = _stub(manager, required=value, providers=[_Provider("archive", OSError("x"))])
        assert "[summary of earlier conversation]" in await Orchestrator._history_for_prompt(stub, 10)
    manager.close()


async def test_a_hub_without_registered_providers_uses_the_archive(tmp_path, monkeypatch):
    from agents.core.orchestrator import _precompress_checkpoint

    archive = TranscriptArchive(tmp_path)
    pc.set_default_providers([archive])
    try:
        stub = _stub(None)
        await _precompress_checkpoint(stub, "a")(TURNS[:1], TURNS)
        assert len(archive.read("a")) == 1
    finally:
        pc.set_default_providers(None)


def test_the_owner_switch_is_a_memory_toggle_off_by_default():
    (row,) = [d for d in settings_db.DEFAULTS if f"{d['category']}.{d['key']}" == pc.SETTING_REQUIRED]
    assert row["value"] is False and row["kind"] == "toggle"


def test_the_audit_rows_carry_no_turn_text():
    audit = _Audit()
    asyncio.run(pc.run_checkpoint([_Provider()], [{"role": "user", "content": "my secret plan"}], TURNS,
                                  required=False, audit=audit))
    assert "my secret plan" not in json.dumps(audit.rows)
