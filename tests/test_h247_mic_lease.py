"""H247 — one microphone per device, armed only by a surface the owner allowed.

Nothing recorded which surface held the microphone: the hub's own wake-word pipeline and
a HUD hands-free loop in a browser on the same machine could both open it, no call said
who held it, nothing checked the owner's consent before arming, and nothing was audited;
the host pipeline started at boot with no check at all. ``agents/core/voice/mic.py`` is
the lease table: a surface (``host:hub``, ``hud:<tab>``, ``mobile:<device>``) arms,
pauses, resumes and stops the microphone of one device; a second surface on a device
already held is refused and named (409), or takes it over explicitly; a kind the owner
has not allowed (``voice.mic_surfaces``) is refused (403); a browser or phone lease
lapses unless renewed; every arm, take-over, stop and refusal is audited.
"""

from __future__ import annotations

import pytest

from agents.core.voice import mic


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def board():
    clock = Clock()
    rows = []
    allowed = {"kinds": ["hud", "mobile"]}
    arb = mic.MicArbiter(clock=clock, allowed=lambda: list(allowed["kinds"]),
                         audit=lambda action, preview: rows.append((action, preview)))
    arb.clock, arb.rows, arb.allowed_kinds = clock, rows, allowed
    return arb


def _refused(fn, code):
    with pytest.raises(mic.MicRefused) as err:
        fn()
    assert err.value.code == code
    return err.value


# ── consent ─────────────────────────────────────────────────────────────────────

def test_the_host_pipeline_needs_the_owners_consent(board):
    err = _refused(lambda: board.arm("host", "hub", device="host"), "not_consented")
    assert "voice.mic_surfaces" in err.message
    assert board.rows[-1][0] == "mic_refused" and "host:hub" in board.rows[-1][1]
    board.allowed_kinds["kinds"].append("host")
    lease = board.arm("host", "hub", device="host")
    assert lease["surface"] == "host:hub" and lease["state"] == "armed"
    assert board.rows[-1] == ("mic_arm", "host:hub armed the microphone of host")


def test_a_satellite_or_an_unknown_kind_cannot_arm_here(board):
    board.allowed_kinds["kinds"].extend(["satellite", "robot"])
    with pytest.raises(ValueError):
        board.arm("satellite", "kitchen", device="satellite:kitchen")
    with pytest.raises(ValueError):
        board.arm("robot", "x", device="x")


@pytest.mark.parametrize("client", ["", "a b", "x" * 65, "tab\n1", None])
def test_a_client_id_must_be_short_and_printable(board, client):
    with pytest.raises(ValueError):
        board.arm("hud", client, device="host")


def test_a_long_client_id_arms_its_own_device_and_a_device_name_is_checked(board):
    long_id = "t" * mic.MAX_CLIENT_LEN
    assert board.arm("hud", long_id, device=f"remote:hud:{long_id}")["device"] == f"remote:hud:{long_id}"
    with pytest.raises(ValueError):
        board.arm("hud", "tab1", device="remote hud")


def test_consent_withdrawn_ends_the_lease_at_its_next_renewal(board):
    board.arm("hud", "tab1", device="remote:tab1")
    board.allowed_kinds["kinds"].remove("hud")
    _refused(lambda: board.arm("hud", "tab1", device="remote:tab1"), "not_consented")
    assert board.holder("remote:tab1") is None


# ── one microphone per device ───────────────────────────────────────────────────

def test_a_second_surface_on_the_same_device_is_refused_and_named(board):
    board.allowed_kinds["kinds"].append("host")
    board.arm("host", "hub", device="host")
    err = _refused(lambda: board.arm("hud", "tab1", device="host"), "mic_busy")
    assert err.holder["surface"] == "host:hub"
    assert board.holder("host")["surface"] == "host:hub"
    assert board.arm("hud", "tab2", device="remote:tab2")["state"] == "armed"   # another device is free


def test_a_take_over_pauses_the_holder_and_tells_it(board):
    board.allowed_kinds["kinds"].append("host")
    told = []
    board.arm("host", "hub", device="host")
    board.on_change("host:hub", lambda state: told.append(state))
    lease = board.arm("hud", "tab1", device="host", take_over=True)
    assert lease["surface"] == "hud:tab1" and board.holder("host")["surface"] == "hud:tab1"
    paused = board.lease("host:hub")
    assert paused["state"] == "paused" and paused["paused_by"] == "hud:tab1"
    assert told == ["paused"]
    assert ("mic_take_over", "hud:tab1 took the microphone of host from host:hub") in board.rows


def test_renewing_is_not_a_conflict(board):
    first = board.arm("hud", "tab1", device="host")
    board.clock.now += 30
    again = board.arm("hud", "tab1", device="host")
    assert again["since"] == first["since"] and again["renewed"] == board.clock.now
    assert [r[0] for r in board.rows].count("mic_arm") == 1                  # a renewal is not re-audited


def test_a_browser_lease_lapses_unless_renewed_and_the_hosts_does_not(board):
    board.allowed_kinds["kinds"].append("host")
    board.arm("hud", "tab1", device="remote:tab1")
    board.arm("host", "hub", device="host")
    board.clock.now += mic.LEASE_SECONDS + 1
    assert board.holder("remote:tab1") is None
    assert board.holder("host")["surface"] == "host:hub"
    assert [d["device"] for d in board.status()["devices"]] == ["host"]


def test_pause_frees_the_device_and_resume_asks_again(board):
    board.allowed_kinds["kinds"].append("host")
    told = []
    board.arm("host", "hub", device="host")
    board.on_change("host:hub", told.append)
    assert board.pause("host:hub")["state"] == "paused"
    assert board.holder("host") is None
    board.arm("hud", "tab1", device="host")
    _refused(lambda: board.resume("host:hub"), "mic_busy")
    assert board.resume("host:hub", take_over=True)["state"] == "armed"
    assert board.lease("hud:tab1")["state"] == "paused" and told == ["paused", "armed"]


def test_stop_releases_and_says_so(board):
    board.arm("hud", "tab1", device="host")
    assert board.stop("hud:tab1") is True and board.holder("host") is None
    assert board.stop("hud:tab1") is False
    assert board.rows[-1] == ("mic_stop", "hud:tab1 released the microphone of host")


def test_the_table_is_bounded(board):
    for n in range(mic.MAX_LEASES):
        board.arm("hud", f"t{n}", device=f"remote:t{n}")
    _refused(lambda: board.arm("hud", "one-more", device="remote:x"), "too_many")


def test_status_names_every_holder_and_what_is_allowed(board):
    board.allowed_kinds["kinds"].append("host")
    board.arm("host", "hub", device="host")
    board.arm("mobile", "pixel", device="mobile:pixel")
    st = board.status()
    assert st["allowed"] == ["hud", "mobile", "host"]
    assert {(d["device"], d["holder"]["surface"]) for d in st["devices"]} == {("host", "host:hub"), ("mobile:pixel", "mobile:pixel")}
    assert all({"kind", "client", "state", "since"} <= set(d["holder"]) for d in st["devices"])


def test_the_numbers(board):
    assert mic.LEASE_SECONDS == 45 and mic.MAX_LEASES == 32 and mic.DEFAULT_ALLOWED == ["hud", "mobile"]
    board.arm("hud", "tab1", device="remote:tab1")
    board.clock.now += 44
    assert board.holder("remote:tab1") is not None
    board.clock.now += 2
    assert board.holder("remote:tab1") is None


def test_a_lease_keeps_when_it_began_across_a_pause(board):
    first = board.arm("hud", "tab1", device="host")
    board.pause("hud:tab1")
    board.clock.now += 10
    assert board.resume("hud:tab1")["since"] == first["since"]


def test_the_consent_is_read_from_the_setting_and_only_arming_kinds_count(monkeypatch):
    from agents.core import settings_db

    monkeypatch.setattr(settings_db, "get_value", lambda cat, key, default=None: ["hud", "robot", 3, "host"])
    assert mic.allowed_kinds() == ["hud", "host"]
    monkeypatch.setattr(settings_db, "get_value", lambda cat, key, default=None: "hud")
    assert mic.allowed_kinds() == ["hud", "mobile"]                  # not a list: the default

    def broken(*a, **k):
        raise RuntimeError("no store")

    monkeypatch.setattr(settings_db, "get_value", broken)
    assert mic.allowed_kinds() == ["hud", "mobile"]


# ── the setting ─────────────────────────────────────────────────────────────────

def test_the_consent_setting_is_declared_off_for_the_host(tmp_path, monkeypatch):
    from agents.core import settings_db

    spec = settings_db._SPEC[("voice", "mic_surfaces")]
    assert spec["value"] == ["hud", "mobile"] and spec["kind"] == "tags"
    assert settings_db.validate_category("voice", {"mic_surfaces": ["hud", "host"]}) == []
    assert settings_db.validate_category("voice", {"mic_surfaces": ["hud", "robot"]})


# ── the host pipeline asks at boot ──────────────────────────────────────────────

def test_the_voice_channel_starts_the_host_pipeline_only_with_a_lease(monkeypatch):
    import asyncio

    from agents.core.channels import voice as channel

    started, stopped = [], []

    class FakePipeline:
        def __init__(self, on_transcription=None):
            self.tts = None

        async def start(self):
            started.append(1)

        def stop(self):
            stopped.append(1)

    board = mic.MicArbiter(allowed=lambda: ["hud"], audit=lambda *a: None)
    monkeypatch.setattr(channel, "VoicePipeline", FakePipeline)
    monkeypatch.setattr(mic, "ARBITER", board)
    ch = channel.VoiceChannel()
    asyncio.run(ch.start())
    assert started == [] and board.holder("host") is None           # not consented: the mic stays shut
    board._allowed = lambda: ["hud", "host"]
    asyncio.run(ch.start())
    assert started == [1] and board.holder("host")["surface"] == "host:hub"
    board.arm("hud", "tab1", device="host", take_over=True)
    assert stopped == [1]                                            # taken over: the pipeline let go
    asyncio.run(ch.stop())
    assert board.lease("host:hub") is None


# ── the routes ──────────────────────────────────────────────────────────────────

TOKEN = {"X-User-Token": "u-h247"}


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "USER_TOKEN", "u-h247", raising=False)
    monkeypatch.setenv("JARVIS_USER_TOKEN", "u-h247")
    rows = []
    board = mic.MicArbiter(allowed=lambda: ["hud", "mobile", "host"],
                           audit=lambda action, preview: rows.append((action, preview)))
    monkeypatch.setattr(mic, "ARBITER", board)
    local = TestClient(web.app, client=("127.0.0.1", 50000))
    remote = TestClient(web.app, client=("192.168.1.20", 50000))
    return local, remote, board, rows


def test_a_browser_on_the_hubs_own_machine_shares_the_hosts_microphone(client):
    local, remote, board, rows = client
    board.arm("host", "hub", device="host")
    busy = local.post("/api/voice/mic/arm", json={"surface": "hud", "client": "tab1"}, headers=TOKEN)
    assert busy.status_code == 409 and busy.json()["holder"]["surface"] == "host:hub"
    far = remote.post("/api/voice/mic/arm", json={"surface": "hud", "client": "tab2"}, headers=TOKEN)
    assert far.status_code == 200 and far.json()["lease"]["device"] == "remote:hud:tab2"
    took = local.post("/api/voice/mic/arm", json={"surface": "hud", "client": "tab1", "take_over": True}, headers=TOKEN)
    assert took.status_code == 200 and took.json()["lease"]["device"] == "host"
    assert board.lease("host:hub")["state"] == "paused"


def test_the_routes_refuse_what_the_owner_did_not_allow_and_answer_who_holds_the_mic(client, monkeypatch):
    local, _remote, board, _rows = client
    board._allowed = lambda: ["mobile"]
    got = local.post("/api/voice/mic/arm", json={"surface": "hud", "client": "tab1"}, headers=TOKEN)
    assert got.status_code == 403 and got.json()["error"] == "not_consented"
    board._allowed = lambda: ["hud"]
    assert local.post("/api/voice/mic/arm", json={"surface": "hud", "client": "tab1"}, headers=TOKEN).status_code == 200
    st = local.get("/api/voice/mic", headers=TOKEN)
    assert st.status_code == 200 and st.json()["devices"][0]["holder"]["surface"] == "hud:tab1"
    assert "no-store" in st.headers.get("cache-control", "")
    assert local.post("/api/voice/mic/pause", json={"surface": "hud:tab1"}, headers=TOKEN).json()["lease"]["state"] == "paused"
    assert local.post("/api/voice/mic/resume", json={"surface": "hud:tab1"}, headers=TOKEN).json()["lease"]["state"] == "armed"
    assert local.post("/api/voice/mic/stop", json={"surface": "hud:tab1"}, headers=TOKEN).json() == {"ok": True, "stopped": True}
    assert local.post("/api/voice/mic/pause", json={"surface": "hud:tab1"}, headers=TOKEN).status_code == 404


def test_a_phone_has_its_own_microphone_even_on_loopback(client):
    local, _remote, board, _rows = client
    board.arm("host", "hub", device="host")
    got = local.post("/api/voice/mic/arm", json={"surface": "mobile", "client": "pixel"}, headers=TOKEN)
    assert got.status_code == 200 and got.json()["lease"]["device"] == "mobile:pixel"


def test_the_routes_refuse_a_host_arm_and_a_bad_body(client):
    local, _remote, _board, _rows = client
    assert local.post("/api/voice/mic/arm", json={"surface": "host", "client": "hub"}, headers=TOKEN).status_code == 422
    assert local.post("/api/voice/mic/arm", json={"surface": "hud", "client": "a b"}, headers=TOKEN).status_code == 422


def test_every_mic_route_is_user_guarded():
    from agents import web
    from tests._route_introspect import iter_effective_routes

    mine = [r for r in iter_effective_routes(web.app)
            if getattr(r, "path", "").startswith("/api/voice/mic") and hasattr(r, "dependant")]
    assert {(next(iter(r.methods)), r.path) for r in mine} == {
        ("GET", "/api/voice/mic"), ("POST", "/api/voice/mic/arm"), ("POST", "/api/voice/mic/pause"),
        ("POST", "/api/voice/mic/resume"), ("POST", "/api/voice/mic/stop")}
    for r in mine:
        assert "user_guard" in {getattr(d.call, "__name__", "") for d in r.dependant.dependencies}, r.path
