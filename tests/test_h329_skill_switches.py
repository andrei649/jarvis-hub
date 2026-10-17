"""H329 — switch a skill off without uninstalling it, everywhere or on one channel.

An owner who distrusted a skill could only uninstall it, losing its usage history, its
signature and its approval. Now ``skills.disabled`` and ``skills.channel_disabled``
(settings) switch it off at once: it is left out of the model's catalog and of
``skills_list`` / ``skill_view``, a command naming it is refused with the reason, and
nothing about it is deleted. The security monitor cannot be switched off. The admin
route records every switch in the intent log, and switching back on is refused when it
cannot be recorded. ``nerva skills list|off|on`` and the Skill Switches panel drive it.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import settings_db  # noqa: E402
from agents.core.skills import loader as loader_mod  # noqa: E402
from agents.core.skills import switches  # noqa: E402
from agents.core.skills.loader import Skill, SkillLoader  # noqa: E402

REPO = repo_root
_TOKEN = "h329-token"


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    # The shipped skills tree: an essential skill is the shipped copy (review-H329 F2).
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tmp_path / "skills")
    yield


def _skill(tmp_path, folder, name, *, command=None, category=None, calls=None, shipped=False):
    path = tmp_path / "skills" / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    (path / "SKILL.sig").write_text("signature", encoding="utf-8")
    manifest = {"name": name, "description": f"{name} does things",
                "commands": [{"command": command or folder, "description": "run it"}]}
    if category:
        manifest["hermes"] = {"category": category}
    skill = Skill(name, path, manifest)
    skill.trusted = True
    skill.external = not shipped
    skill.view_files = {"SKILL.md": f"# {name}\n".encode()}
    record = calls if calls is not None else []

    async def _run(args, context=None):
        record.append((folder, args))
        return f"{folder} ran {args}"

    skill.register_command(command or folder, _run)
    return skill


def _store(**values):
    updated, skipped = settings_db.put_category("skills", values)
    assert skipped == []


# ── the rows ─────────────────────────────────────────────────────────────────────

def test_the_two_rows_are_declared_settings_and_validated():
    rows = {(r["category"], r["key"]): r for r in settings_db.DEFAULTS}
    assert rows[("skills", "disabled")]["kind"] == "tags" and rows[("skills", "disabled")]["value"] == []
    assert rows[("skills", "channel_disabled")]["kind"] == "json" and rows[("skills", "channel_disabled")]["value"] == {}
    assert settings_db.validate_category("skills", {"channel_disabled": {"telegram": ["Spotify"]}}) == []
    for bad in ([], {"Tele gram": ["x"]}, {"telegram": "Spotify"}, {"telegram": [3]},
                {f"c{i}": ["x"] for i in range(switches.MAX_CHANNELS + 1)}):
        assert settings_db.validate_category("skills", {"channel_disabled": bad}), bad
    assert settings_db.validate_category("skills", {"disabled": "Spotify"})     # tags: a list


def test_names_and_channels_are_cleaned():
    assert switches.clean_names([" Spotify ", "spotify", "", 3, "x" * 200, "tab\there", "Brief"]) == ["Spotify", "Brief"]
    assert switches.clean_names("Spotify") == []
    assert len(switches.clean_names([f"n{i}" for i in range(switches.MAX_NAMES + 5)])) == switches.MAX_NAMES
    assert switches.clean_channel(" Telegram ") == "telegram"
    assert switches.clean_channel("tele gram") == "" and switches.clean_channel("") == "" and switches.clean_channel("-x") == ""
    assert switches.clean_channel("x" * 32) == "x" * 32 and switches.clean_channel("x" * 33) == ""
    assert switches.clean_channel_map({"Telegram": ["a"], "bad key": ["b"], "voice": [], "web": "c"}) == {"telegram": ["a"]}
    assert switches.clean_channel_map(["x"]) == {}
    many = {f"c{i}": ["a"] for i in range(switches.MAX_CHANNELS + 3)}
    assert len(switches.clean_channel_map(many)) == switches.MAX_CHANNELS


# ── whether a skill is off ───────────────────────────────────────────────────────

def test_off_everywhere_by_name_ignoring_case(tmp_path):
    weather = _skill(tmp_path, "weather", "Weather Intel")
    assert switches.off_reason(weather, "web") == ""
    _store(disabled=["weather intel"])
    assert switches.off_reason(weather, "web") == "everywhere"
    assert switches.off_reason(weather, None) == "everywhere"
    _store(disabled=["weather"])             # a folder is resolved by the route, never stored
    assert switches.off_reason(weather, "web") == ""
    assert switches.identities(weather) == {"weather intel", "weather"}


def test_off_on_one_channel_only(tmp_path):
    from agents.core.commands import Principal
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal

    spotify = _skill(tmp_path, "spotify", "Spotify")
    _store(channel_disabled={"telegram": ["Spotify"]})
    assert switches.off_reason(spotify, "telegram") == "on telegram"
    assert switches.off_reason(spotify, "Telegram") == "on telegram"
    assert switches.off_reason(spotify, "voice") == ""
    assert switches.off_reason(spotify, None) == ""                        # no turn bound
    token = bind_turn_principal(Principal(channel="telegram"))
    try:
        assert switches.current_channel() == "telegram"
        assert switches.off_reason(spotify, None) == "on telegram"         # the turn's channel
        assert switches.off_reason(spotify, "web") == ""                   # an explicit channel wins
        assert switches.off_reason(spotify, "") == "on telegram"           # no channel: the turn's
        assert switches.off_reason(spotify, "not a channel") == "on telegram"
    finally:
        reset_turn_principal(token)


def test_an_essential_skill_is_never_off(tmp_path):
    monitor = _skill(tmp_path, "security_monitor", "Security Monitor", shipped=True)
    assert switches.is_essential(monitor)
    assert not switches.is_essential(_skill(tmp_path, "weather", "Weather Intel"))
    _store(disabled=["Security Monitor"], channel_disabled={"telegram": ["security_monitor"]})
    assert switches.off_reason(monitor, "telegram") == ""


def test_an_unreadable_store_refuses_nonessential_skill(tmp_path, monkeypatch):
    weather = _skill(tmp_path, "weather", "Weather Intel")
    monkeypatch.setattr(switches, "state", MagicMock(side_effect=RuntimeError("locked")))
    assert switches.off_reason(weather, "web") == "switches unavailable"


# ── what a switched-off skill does ───────────────────────────────────────────────

def test_a_command_of_a_switched_off_skill_is_refused_and_not_counted(tmp_path):
    calls, uses = [], []
    weather = _skill(tmp_path, "weather", "Weather Intel", calls=calls)
    weather.usage_hook = lambda name, kind: uses.append((name, kind))
    assert asyncio.run(weather.execute("weather", "cluj", {"channel": "web"})) == "weather ran cluj"
    _store(disabled=["Weather Intel"])
    reply = asyncio.run(weather.execute("weather", "cluj", {"channel": "web"}))
    assert reply == ("[skill:Weather Intel] is switched off everywhere; "
                     "the owner can switch it back on in Console → Trust → Skill Switches")
    assert calls == [("weather", "cluj")] and uses == [("Weather Intel", "use")]


def test_a_channel_switch_refuses_there_only(tmp_path):
    calls = []
    spotify = _skill(tmp_path, "spotify", "Spotify", calls=calls)
    _store(channel_disabled={"telegram": ["SPOTIFY"]})
    assert "switched off on telegram" in asyncio.run(spotify.execute("spotify", "play", {"channel": "telegram"}))
    assert asyncio.run(spotify.execute("spotify", "play", {"channel": "voice"})) == "spotify ran play"
    assert calls == [("spotify", "play")]


def _loader(*skills):
    loader = SkillLoader.__new__(SkillLoader)
    loader.skills = {s.name: s for s in skills}
    return loader


def test_the_catalog_leaves_a_switched_off_skill_out(tmp_path, monkeypatch):
    loader = _loader(_skill(tmp_path, "weather", "Weather Intel"), _skill(tmp_path, "spotify", "Spotify"))
    reads = []
    real = switches.state
    monkeypatch.setattr(switches, "state", lambda: reads.append(1) or real())
    assert {r["skill"] for r in loader.prompt_catalog()} == {"Weather Intel", "Spotify"}
    _store(disabled=["Spotify"])
    reads.clear()
    assert {r["skill"] for r in loader.prompt_catalog()} == {"Weather Intel"}
    assert reads == [1]                                      # read once for the whole catalog
    assert SkillLoader.catalog_gate(loader.skills["Spotify"]) == "disabled"
    assert SkillLoader.catalog_gate(loader.skills["Weather Intel"]) == ""


def test_the_catalog_leaves_it_out_on_its_channel_only(tmp_path):
    from agents.core.commands import Principal
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal

    loader = _loader(_skill(tmp_path, "spotify", "Spotify"))
    _store(channel_disabled={"telegram": ["Spotify"]})
    assert [r["skill"] for r in loader.prompt_catalog()] == ["Spotify"]
    token = bind_turn_principal(Principal(channel="telegram"))
    try:
        assert loader.prompt_catalog() == []
    finally:
        reset_turn_principal(token)


def test_an_unreadable_store_hides_the_catalog(tmp_path, monkeypatch):
    loader = _loader(_skill(tmp_path, "spotify", "Spotify"), _skill(tmp_path, "weather", "Weather Intel"))
    unreadable = MagicMock(side_effect=RuntimeError("locked"))
    monkeypatch.setattr(switches, "state", unreadable)
    assert loader.prompt_catalog() == []
    assert unreadable.call_count == 1                        # not retried per skill


def test_skills_list_and_skill_view_leave_it_out(tmp_path):
    from agents.core.skills.tools import register_skill_tools
    from agents.core.tool_rpc import ToolRPCServer

    loader = _loader(_skill(tmp_path, "weather", "Weather Intel"), _skill(tmp_path, "spotify", "Spotify"))
    server = ToolRPCServer()
    register_skill_tools(server, loader=lambda: loader, proposals=lambda: None, approvals=lambda: None,
                         session_id=lambda: "s", posture=lambda: "operator/owner")

    def call(tool, args):
        return asyncio.run(server.handle({"tool": tool, "args": args}, actor="jarvis"))["result"]

    _store(disabled=["spotify"])
    assert [s["name"] for s in call("skills_list", {})["skills"]] == ["Weather Intel"]
    assert call("skill_view", {"name": "Spotify"})["ok"] is False
    assert call("skill_view", {"name": "Weather Intel"})["ok"] is True


# ── the switch itself ────────────────────────────────────────────────────────────

def test_apply_switches_off_and_on_everywhere(tmp_path):
    weather, spotify = _skill(tmp_path, "weather", "Weather Intel"), _skill(tmp_path, "spotify", "Spotify")
    out = switches.apply([weather, spotify], enabled=False)
    assert out["changed"] == ["Weather Intel", "Spotify"] and out["unchanged"] == []
    assert out["state"] == {"disabled": ["Weather Intel", "Spotify"], "channel_disabled": {}}
    assert out["before"] == {"disabled": [], "channel_disabled": {}}
    again = switches.apply([weather], enabled=False)
    assert again["changed"] == [] and again["unchanged"] == ["Weather Intel"]
    with pytest.raises(PermissionError):
        switches.apply([weather], enabled=True)
    on = switches.plan([weather], enabled=True, channel="", now=switches.state())
    assert on["changed"] == ["Weather Intel"] and on["state"]["disabled"] == ["Spotify"]
    assert switches.off_reason(weather) == "everywhere"  # planning never writes
    assert switches.plan([weather], enabled=True, channel="", now=on["state"])["unchanged"] == ["Weather Intel"]


def test_apply_on_everywhere_clears_every_entry_and_on_a_channel_only_that_one(tmp_path):
    spotify = _skill(tmp_path, "spotify", "Spotify")
    _store(disabled=["SPOTIFY"], channel_disabled={"telegram": ["spotify"], "voice": ["Spotify", "Brief"]})
    one = switches.plan([spotify], enabled=True, channel="telegram", now=switches.state())
    assert one["changed"] == ["Spotify"]
    assert one["state"] == {"disabled": ["SPOTIFY"], "channel_disabled": {"voice": ["Spotify", "Brief"]}}
    assert switches.off_reason(spotify, "telegram") == "everywhere"     # still off everywhere
    assert settings_db.get_value("skills", "channel_disabled")["telegram"] == ["spotify"]  # no write yet
    every = switches.plan([spotify], enabled=True, channel="", now=one["state"])
    assert every["state"] == {"disabled": [], "channel_disabled": {"voice": ["Brief"]}}
    assert switches.off_reason(spotify) == "everywhere"


def test_apply_off_on_a_channel(tmp_path):
    spotify = _skill(tmp_path, "spotify", "Spotify")
    out = switches.apply([spotify], enabled=False, channel="telegram")
    assert out["state"] == {"disabled": [], "channel_disabled": {"telegram": ["Spotify"]}}
    assert switches.apply([spotify], enabled=False, channel="telegram")["unchanged"] == ["Spotify"]


def test_apply_never_switches_an_essential_skill_off(tmp_path):
    monitor = _skill(tmp_path, "security_monitor", "Security Monitor", shipped=True)
    out = switches.apply([monitor], enabled=False, channel="telegram")
    assert out["essential"] == ["Security Monitor"] and out["changed"] == []
    assert out["state"] == {"disabled": [], "channel_disabled": {}}


def test_apply_says_when_the_store_refuses(tmp_path, monkeypatch):
    weather = _skill(tmp_path, "weather", "Weather Intel")
    from agents.core.skills import switch_approval

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(switch_approval, "_write_state", fail)
    with pytest.raises(OSError):
        switches.apply([weather], enabled=False)
    assert switches.state() == {"disabled": [], "channel_disabled": {}}


def test_restore_cannot_widen_without_approval(tmp_path):
    weather = _skill(tmp_path, "weather", "Weather Intel")
    _store(disabled=["Weather Intel"])
    with pytest.raises(PermissionError):
        switches.restore({"disabled": [], "channel_disabled": {}}, switches.state())
    assert switches.off_reason(weather) == "everywhere"


# ── the route ────────────────────────────────────────────────────────────────────

class _Log:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    def record(self, **row):
        if self.fail:
            raise OSError("intent log unwritable")
        self.rows.append(row)


def _client(monkeypatch, tmp_path, *, log=None):
    from fastapi.testclient import TestClient

    from agents import web

    skills = [_skill(tmp_path, "weather", "Weather Intel", category="info"),
              _skill(tmp_path, "news", "News", category="Info"),
              _skill(tmp_path, "spotify", "Spotify"),
              _skill(tmp_path, "security_monitor", "Security Monitor", category="info", shipped=True)]
    orch = MagicMock()
    orch.skills = SimpleNamespace(skills={s.name: s for s in skills})
    orch.permission_ledger = None
    orch.autonomy = None
    orch.skill_usage = None
    orch.intent_log = log if log is not None else _Log()
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    return TestClient(web.app), orch



def _ready_approval(monkeypatch, tmp_path, orch):
    from agents.core.permission_ledger import PermissionLedger
    from agents.core.skills import signing, switch_approval

    monkeypatch.setattr(switch_approval, "kernel_enabled", lambda: True)
    monkeypatch.setattr("agents.core.permission_ledger._kernel_on", lambda: True)
    queued = []
    def enqueue(**kwargs):
        queued.append(kwargs)
        return len(queued)
    orch.permission_ledger = PermissionLedger(tmp_path / "permissions.db", enabled=True,
                                               authorizer=lambda action: SimpleNamespace(verdict="queue"))
    orch.autonomy = SimpleNamespace(govern_enqueue=enqueue)
    for skill in orch.skills.skills.values():
        skill.source_fingerprint = signing.source_snapshot(skill.path).fingerprint
    orch._queued_switches = queued


def _approve(orch, task_id=1):
    from agents.core.skills import switch_approval

    queued = orch._queued_switches[task_id - 1]
    task = SimpleNamespace(id=task_id, kind="permission.grant", payload=queued["payload"],
                           title=queued["title"], agent="jarvis",
                           decision="accept", decided_by="alice", human_decision={"action": "accept", "by": "alice"})
    return asyncio.run(switch_approval.apply_approved(task, ledger=orch.permission_ledger,
                                                       loader=orch.skills,
                                                       usage=getattr(orch, "skill_usage", None),
                                                       intent_log=orch.intent_log))

def _post(client, body):
    return client.post("/api/skills/switch", json=body, headers={"X-Admin-Token": _TOKEN})


def test_the_route_switches_off_and_records_it(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    resp = _post(client, {"skill": "weather", "enabled": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["changed"] == ["Weather Intel"] and body["audited"] is True and body["channel"] is None
    assert body["switches"] == {"disabled": ["Weather Intel"], "channel_disabled": {}}
    row = orch.intent_log.rows[0]
    assert row["actor"] == "owner" and row["action"] == "skill.disable" and row["cause"] == "skills.switch"
    assert row["metadata"] == {"skills": ["Weather Intel"], "channel": None, "category": None}
    assert "off everywhere" in row["why"]
    assert _post(client, {"skill": "Weather Intel", "enabled": False}).json()["unchanged"] == ["Weather Intel"]
    assert len(orch.intent_log.rows) == 1                     # nothing changed, nothing recorded


def test_the_route_switches_on_one_channel(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    _ready_approval(monkeypatch, tmp_path, orch)
    assert _post(client, {"skill": "spotify", "enabled": False, "channel": "Telegram"}).json()["channel"] == "telegram"
    response = _post(client, {"skill": "spotify", "enabled": True, "channel": "telegram"})
    assert response.status_code == 202 and response.json()["status"] == "pending"
    assert switches.state()["channel_disabled"] == {"telegram": ["Spotify"]}
    assert _approve(orch, response.json()["task_id"])["status"] == "ok"
    assert switches.state()["channel_disabled"] == {}



def test_the_route_switches_a_category_but_not_its_essential_skill(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    body = _post(client, {"category": "INFO", "enabled": False}).json()
    assert sorted(body["changed"]) == ["News", "Weather Intel"] and body["essential"] == ["Security Monitor"]
    assert orch.intent_log.rows[0]["metadata"]["category"] == "INFO"


@pytest.mark.parametrize("payload,status,reason", [
    ({"enabled": False}, 422, "bad_target"),
    ({"skill": "weather", "category": "info", "enabled": False}, 422, "bad_target"),
    ({"skill": "weather", "enabled": False, "channel": "tele gram"}, 422, "bad_channel"),
    ({"skill": "ghost", "enabled": False}, 404, "not_found"),
    ({"category": "ghost", "enabled": False}, 404, "not_found"),
    ({"skill": "security_monitor", "enabled": False}, 409, "essential"),
])
def test_the_route_refuses(monkeypatch, tmp_path, payload, status, reason):
    client, orch = _client(monkeypatch, tmp_path)
    resp = _post(client, payload)
    assert resp.status_code == status and resp.json()["reason"] == reason
    assert switches.state() == {"disabled": [], "channel_disabled": {}} and orch.intent_log.rows == []


def test_the_route_is_admin_only(monkeypatch, tmp_path):
    client, _orch = _client(monkeypatch, tmp_path)
    assert client.post("/api/skills/switch", json={"skill": "weather", "enabled": False}).status_code in (401, 403)
    assert switches.state()["disabled"] == []


def test_a_manifest_name_wins_over_a_folder_of_the_same_spelling(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    other = _skill(tmp_path, "weather2", "weather")
    orch.skills.skills = {"Weather Intel": orch.skills.skills["Weather Intel"], "weather": other}
    assert _post(client, {"skill": "WEATHER", "enabled": False}).json()["changed"] == ["weather"]
    assert switches.off_reason(orch.skills.skills["Weather Intel"], "web") == ""   # not the other one
    assert _post(client, {"skill": "Weather Intel", "enabled": False}).json()["changed"] == ["Weather Intel"]
    assert switches.state()["disabled"] == ["weather", "Weather Intel"]


@pytest.mark.parametrize("log", [None, object()])
def test_switching_on_needs_approval_intake_not_intent_log(monkeypatch, tmp_path, log):
    client, orch = _client(monkeypatch, tmp_path)
    _store(disabled=["Weather Intel"])
    orch.intent_log = log
    response = _post(client, {"skill": "weather", "enabled": True})
    assert response.status_code == 503 and response.json()["reason"] == "approval_unavailable"
    assert _post(client, {"skill": "spotify", "enabled": False}).json()["audited"] is False



def test_switching_on_needs_the_approval_intake(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    _store(disabled=["Weather Intel"])
    orch.intent_log = None
    resp = _post(client, {"skill": "weather", "enabled": True})
    assert resp.status_code == 503 and resp.json()["reason"] == "approval_unavailable"
    assert switches.state()["disabled"] == ["Weather Intel"]
    off = _post(client, {"skill": "spotify", "enabled": False}).json()
    assert off["changed"] == ["Spotify"] and off["audited"] is False



def test_optional_intent_log_failure_does_not_erase_canonical_approval(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path, log=_Log(fail=True))
    _ready_approval(monkeypatch, tmp_path, orch)
    _store(disabled=["Weather Intel"])
    resp = _post(client, {"skill": "weather", "enabled": True})
    assert resp.status_code == 202 and switches.state()["disabled"] == ["Weather Intel"]
    assert _approve(orch, resp.json()["task_id"])["status"] == "ok"
    assert switches.state()["disabled"] == []
    conn = settings_db.get_conn()
    try:
        row = conn.execute("SELECT approver,task_id FROM skill_switch_events WHERE action='enable'").fetchone()
        assert row["approver"] == "alice" and row["task_id"] == resp.json()["task_id"]
    finally:
        conn.close()



def test_a_later_disable_defeats_the_earlier_approval(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    _ready_approval(monkeypatch, tmp_path, orch)
    _store(disabled=["Weather Intel"])
    pending = _post(client, {"skill": "weather", "enabled": True})
    assert pending.status_code == 202
    assert _post(client, {"skill": "weather", "enabled": False}).status_code == 200
    assert _approve(orch, pending.json()["task_id"])["reason"] == "stale_switch_request"
    assert switches.state()["disabled"] == ["Weather Intel"]



def test_a_store_that_refuses_the_write_is_a_503(monkeypatch, tmp_path):
    from agents.core.skills import switch_approval

    client, orch = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(switch_approval, "_write_state", MagicMock(side_effect=RuntimeError("disk full")))
    resp = _post(client, {"skill": "weather", "enabled": False})
    assert resp.status_code == 503 and resp.json()["reason"] == "write_failed"
    assert orch.intent_log.rows == [] and switches.state()["disabled"] == []



def test_the_skills_list_says_where_each_is_off(monkeypatch, tmp_path):
    client, _orch = _client(monkeypatch, tmp_path)
    _store(disabled=["weather intel", "weather", "Security Monitor"],
           channel_disabled={"telegram": ["Spotify", "Security Monitor"], "voice": ["spotify"]})
    body = client.get("/skills").json()
    rows = body["skills"]
    assert rows["Weather Intel"]["disabled"] is True and rows["Weather Intel"]["category"] == "info"
    assert rows["Spotify"]["disabled"] is False and rows["Spotify"]["disabled_channels"] == ["telegram", "voice"]
    assert rows["Spotify"]["category"] == ""
    monitor = rows["Security Monitor"]
    assert monitor["essential"] is True and monitor["disabled"] is False and monitor["disabled_channels"] == []
    assert body["switches"]["channel_disabled"]["voice"] == ["spotify"]


def _tree(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob("*")) if p.is_file()}


def test_nothing_about_the_skill_is_touched_by_a_cycle(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    _ready_approval(monkeypatch, tmp_path, orch)
    weather = orch.skills.skills["Weather Intel"]
    before = _tree(weather.path)
    manifest = dict(weather.manifest)
    assert _post(client, {"skill": "weather", "enabled": False}).status_code == 200
    pending = _post(client, {"skill": "weather", "enabled": True})
    assert pending.status_code == 202 and _tree(weather.path) == before
    assert _approve(orch, pending.json()["task_id"])["status"] == "ok"
    assert _post(client, {"skill": "weather", "enabled": True}).json()["status"] == "unchanged"
    assert _tree(weather.path) == before and weather.manifest == manifest and weather.trusted is True



# ── the CLI ──────────────────────────────────────────────────────────────────────

def _cli(argv, routes):
    from agents.cli.nerva import Context, main

    calls = []

    class _Hub:
        base_url = "http://127.0.0.1:8080"

        def get(self, path):
            calls.append(("GET", path, None))
            return routes[f"GET {path}"]

        def post(self, path, body=None):
            calls.append(("POST", path, body))
            answer = routes[f"POST {path}"]
            return answer(body) if callable(answer) else answer

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: _Hub())
    return main(argv, context=ctx), out.getvalue(), err.getvalue(), calls


def test_nerva_skills_off_on_and_list():
    reply = {"ok": True, "changed": ["Spotify"], "unchanged": [], "essential": [], "audited": True}
    code, out, _err, calls = _cli(["skills", "off", "spotify", "--channel", "telegram"],
                                  {"POST /api/skills/switch": reply})
    assert code == 0 and calls == [("POST", "/api/skills/switch", {"enabled": False, "skill": "spotify", "channel": "telegram"})]
    assert out.strip() == "switched off on telegram: Spotify"
    code, out, _err, calls = _cli(["skills", "on", "--category", "info"],
                                  {"POST /api/skills/switch": {"changed": [], "unchanged": ["News"], "essential": [], "audited": False}})
    assert calls[0][2] == {"enabled": True, "category": "info"} and out.strip() == "News: already on everywhere"
    code, out, _err, _calls = _cli(["skills", "on", "--category", "info", "--channel", "telegram"],
                                   {"POST /api/skills/switch": {"changed": [], "unchanged": [], "essential": [],
                                                                "off_everywhere": ["Spotify"]}})
    assert out.strip() == "Spotify: still off everywhere (switch it on without --channel)"   # review-H329 F3
    code, out, _err, _calls = _cli(["skills", "off", "--category", "info"],
                                   {"POST /api/skills/switch": {"changed": [], "unchanged": [], "essential": ["Security Monitor"],
                                                                "unstorable": ["Notes\xa0Pro"]}})
    assert out.splitlines() == ["Notes\xa0Pro: not switched off; the switch could not be stored",
                                "Security Monitor: essential, stays on"]
    code, out, _err, _calls = _cli(["skills", "off", "spotify"],
                                   {"POST /api/skills/switch": {"changed": ["Spotify"], "audited": False}})
    assert "could not record" in out
    listing = {"skills": {"Spotify": {"disabled": False, "disabled_channels": ["telegram"]},
                          "Weather Intel": {"disabled": True, "disabled_channels": []},
                          "Security Monitor": {"essential": True, "disabled": False, "disabled_channels": []},
                          "brief": {"disabled": False, "disabled_channels": []}}}
    code, out, _err, _calls = _cli(["skills", "list"], {"GET /skills": listing})
    assert code == 0 and out.splitlines() == ["brief: on", "Security Monitor: on (essential)",
                                              "Spotify: off on telegram", "Weather Intel: off everywhere"]


def test_nerva_skills_needs_one_target_and_a_real_listing():
    code, _out, err, calls = _cli(["skills", "off"], {})
    assert code == 2 and "name one skill" in err and calls == []
    code, _out, err, calls = _cli(["skills", "off", "x", "--category", "y"], {})
    assert code == 2 and calls == []
    code, _out, err, _calls = _cli(["skills", "list"], {"GET /skills": {"error": "x"}})
    assert code == 1 and "no skills" in err


def test_a_refused_essential_switch_off_is_an_error_at_the_cli():
    """review-H329 F10: the route answers 409 for one essential skill, never a 200."""
    from agents.cli.client import HubError

    def refuse(body):
        raise HubError(409, "Security Monitor is essential and cannot be switched off")

    code, out, err, _calls = _cli(["skills", "off", "security_monitor"], {"POST /api/skills/switch": refuse})
    assert code == 1 and out == ""
    assert err.strip() == "HTTP 409: Security Monitor is essential and cannot be switched off"


# ── review round ─────────────────────────────────────────────────────────────────

def _admin_write(client, method, path, body=None):
    return client.request(method, path, json=body if body is not None else {},
                          headers={"X-Admin-Token": _TOKEN})


def test_the_settings_routes_never_write_a_switch(monkeypatch, tmp_path):
    """review-H329 F1: only the switch route writes the two rows, so a switch-on is never
    made without its intent-log record: a settings write, an import and a reset refuse or
    leave them."""
    client, orch = _client(monkeypatch, tmp_path)
    orch.intent_log = None
    _store(disabled=["Weather Intel"], channel_disabled={"telegram": ["Spotify"]})
    stored = switches.state()
    resp = _admin_write(client, "PUT", "/api/admin/settings/skills", {"values": {"disabled": []}})
    assert resp.status_code == 422 and "Skill Switches" in " ".join(resp.json()["details"])
    resp = _admin_write(client, "PUT", "/api/admin/settings/skills",
                        {"values": {"channel_disabled": {}, "auto_generate": False}})
    assert resp.status_code == 422 and settings_db.get_value("skills", "auto_generate") is True
    assert _admin_write(client, "PUT", "/api/admin/settings/skills",
                        {"values": {"auto_generate": False}}).status_code == 200
    resp = _admin_write(client, "POST", "/api/admin/settings/import", {"settings": {"skills": {"disabled": []}}})
    assert resp.status_code == 422 and "skills.disabled" in " ".join(resp.json()["details"])
    same = {"settings": {"skills": {"disabled": ["Weather Intel"]}}}         # an older export, unchanged
    assert _admin_write(client, "POST", "/api/admin/settings/import", same).status_code == 200
    assert _admin_write(client, "POST", "/api/admin/settings/skills/reset").status_code == 200
    assert _admin_write(client, "POST", "/api/admin/settings/reseed").status_code == 200
    assert switches.state() == stored
    doc = settings_db.export_settings()
    assert {"disabled", "channel_disabled"}.isdisjoint(doc["settings"]["skills"])
    assert {"skills.disabled", "skills.channel_disabled"} <= {e["setting"] for e in doc["excluded"]}
    rows = {r["key"]: r for r in settings_db.get_category("skills")}
    assert "Skill Switches" in rows["disabled"]["written_by"] and "written_by" not in rows["auto_generate"]


def test_nerva_config_set_never_writes_a_switch():
    """review-H329 F1: `nerva config set` names the command that does."""
    from agents.cli.nerva import Context, main

    _store(disabled=["Weather Intel"])
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: None)
    assert main(["config", "set", "skills.disabled", ""], context=ctx) == 1
    assert "nerva skills on" in err.getvalue() and switches.state()["disabled"] == ["Weather Intel"]


def test_only_the_shipped_security_monitor_is_essential(monkeypatch, tmp_path):
    """review-H329 F2: an imported skill that takes the monitor's folder or name has a switch."""
    assert not switches.is_essential(_skill(tmp_path, "other", "security_monitor", shipped=True))
    assert not switches.is_essential(_skill(tmp_path, "security_monitor", "Totally Safe Helper"))     # external
    assert not switches.is_essential(_skill(tmp_path / "mine", "security_monitor", "Security Monitor", shipped=True))
    client, orch = _client(monkeypatch, tmp_path)
    helper = _skill(tmp_path / "mine", "security_monitor", "Totally Safe Helper")
    orch.skills.skills = {"Totally Safe Helper": helper}
    resp = _post(client, {"skill": "security_monitor", "enabled": False})
    assert resp.status_code == 200 and resp.json()["changed"] == ["Totally Safe Helper"]
    assert switches.off_reason(helper, "web") == "everywhere"


def test_switching_on_one_channel_a_skill_off_everywhere_says_so(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    spotify = orch.skills.skills["Spotify"]
    assert _post(client, {"skill": "spotify", "enabled": False}).status_code == 200
    resp = _post(client, {"skill": "spotify", "enabled": True, "channel": "telegram"})
    assert resp.status_code == 409 and resp.json()["reason"] == "off_everywhere"
    assert switches.off_reason(spotify, "telegram") == "everywhere"
    out = switches.plan([spotify], enabled=True, channel="telegram", now=switches.state())
    assert out["changed"] == [] and out["off_everywhere"] == ["Spotify"]
    _store(disabled=["Spotify"], channel_disabled={"telegram": ["Spotify"]})
    both = switches.plan([spotify], enabled=True, channel="telegram", now=switches.state())
    assert both["changed"] == ["Spotify"] and both["off_everywhere"] == ["Spotify"]



def test_a_turn_with_no_principal_hides_a_skill_off_on_its_channel(tmp_path):
    """review-H329 F4: an mcp, webhook or workflow turn binds no principal; the catalog
    reads the channel handle_input was given, the one a command is refused on."""
    from agents.core.orchestrator import Orchestrator

    loader = _loader(_skill(tmp_path, "spotify", "Spotify"))
    _store(channel_disabled={"mcp": ["Spotify"]})
    seen = []

    async def turn(*args, **kwargs):
        seen.append([r["skill"] for r in loader.prompt_catalog()])
        return "ok"

    asyncio.run(Orchestrator.handle_input(SimpleNamespace(_handle_input=turn), "t", channel="mcp"))
    asyncio.run(Orchestrator.handle_input(SimpleNamespace(_handle_input=turn), "t", channel="voice"))
    asyncio.run(Orchestrator.handle_input_stream(SimpleNamespace(_handle_input_stream=turn), "t", channel="mcp"))
    assert seen == [[], ["Spotify"], []]
    assert switches.current_channel() == ""                                 # the turn's binding is reset


def test_a_cycle_keeps_the_usage_count_the_approval_and_the_signature(monkeypatch, tmp_path):
    """review-H329 F5: GOV-263's claim on a real loader, usage store and approval store."""
    from agents.core.skills import signing
    from agents.core.skills.approval import SkillApprovalStore
    from agents.core.skills.usage import ORIGIN_AGENT, SkillUsageStore

    client, orch = _client(monkeypatch, tmp_path)
    mine = tmp_path / "mine"
    folder = mine / "notes_pro"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# Notes Pro\n\n> Keeps notes.\n", encoding="utf-8")
    (folder / "main.py").write_text("def register(skill):\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tmp_path / "shipped")
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: mine)
    approvals = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    approvals.approve(folder)
    signing.sign_skill(folder)
    usage = SkillUsageStore(path=tmp_path / "usage.json")
    usage.note_created("Notes Pro", ORIGIN_AGENT)
    usage.bump("Notes Pro", "use")
    loader = SkillLoader(approval_store=approvals)
    loader.attach_usage(usage)
    loader.discover()
    orch.skills = loader
    _ready_approval(monkeypatch, tmp_path, orch)

    def standing():
        skill = loader.skills["Notes Pro"]
        return (usage.get("Notes Pro")["use_count"], usage.get("Notes Pro")["state"], approvals.is_approved(folder),
                signing.verify_skill(folder), skill.trusted, skill.owner_vouched, _tree(folder))

    before = standing()
    assert before[0] == 1 and before[2] is True
    assert _post(client, {"skill": "notes_pro", "enabled": False}).json()["changed"] == ["Notes Pro"]
    assert "switched off" in asyncio.run(loader.skills["Notes Pro"].execute("x", "", {"channel": "web"}))
    assert standing() == before
    pending = _post(client, {"skill": "notes_pro", "enabled": True})
    assert pending.status_code == 202 and _approve(orch, pending.json()["task_id"])["status"] == "ok"
    loader.discover()
    assert standing() == before


def test_a_switch_off_the_store_cannot_hold_is_refused_and_not_recorded(monkeypatch, tmp_path):
    """review-H329 F6: a name the read would drop, or one past the caps, is never reported
    switched off (nor recorded) while the skill stays on."""
    client, orch = _client(monkeypatch, tmp_path)
    odd = _skill(tmp_path, "notes_pro", "Notes\xa0Pro", category="info")
    orch.skills.skills["Notes\xa0Pro"] = odd
    resp = _post(client, {"skill": "notes_pro", "enabled": False})
    assert resp.status_code == 409 and resp.json()["reason"] == "unstorable"
    assert orch.intent_log.rows == [] and switches.state() == {"disabled": [], "channel_disabled": {}}
    body = _post(client, {"category": "info", "enabled": False}).json()
    assert body["unstorable"] == ["Notes\xa0Pro"] and "Notes\xa0Pro" not in body["changed"]
    assert orch.intent_log.rows[0]["metadata"]["skills"] == body["changed"]
    weather = orch.skills.skills["Weather Intel"]
    _store(disabled=[f"n{i}" for i in range(switches.MAX_NAMES)], channel_disabled={})
    out = switches.apply([weather], enabled=False)
    assert out["unstorable"] == ["Weather Intel"] and out["changed"] == []
    _store(disabled=[], channel_disabled={f"c{i}": ["x"] for i in range(switches.MAX_CHANNELS)})
    assert switches.apply([weather], enabled=False, channel="telegram")["unstorable"] == ["Weather Intel"]
    assert switches.apply([weather], enabled=False, channel="c0")["changed"] == ["Weather Intel"]
    assert switches.off_reason(weather, "c0") == "on c0"


def test_a_switch_on_an_unreadable_store_writes_nothing(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    _store(disabled=["Evil", "Other"], channel_disabled={"telegram": ["Spotify"]})
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value='{}' WHERE category='skills' AND key='disabled'")
        conn.commit()
    finally:
        conn.close()
    resp = _post(client, {"skill": "news", "enabled": False})
    assert resp.status_code == 503 and resp.json()["reason"] == "switches_unavailable"
    assert client.get("/skills").status_code == 503



def test_unreadable_switch_store_refuses_execution_and_hides_catalog(monkeypatch, tmp_path):
    skill = _skill(tmp_path, "weather", "Weather Intel")
    loader = _loader(skill)
    _store(disabled=["Weather Intel"])
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value='{}' WHERE category='skills' AND key='disabled'")
        conn.commit()
    finally:
        conn.close()
    assert switches.off_reason(skill, "web") == "switches unavailable"
    assert loader.prompt_catalog() == []
    assert "switches unavailable" in asyncio.run(skill.execute("weather", "", {"channel": "web"}))



def test_intent_log_projection_failure_does_not_revert_canonical_enable(monkeypatch, tmp_path):
    from agents.core.security.anchor import IntentLog
    from agents.core.skills import switch_approval

    log = IntentLog(tmp_path / "intent_log.json", secret_key="h329")
    client, orch = _client(monkeypatch, tmp_path, log=log)
    _ready_approval(monkeypatch, tmp_path, orch)
    _store(disabled=["Weather Intel"])
    monkeypatch.setattr(log, "record", MagicMock(side_effect=OSError("disk full")))
    response = _post(client, {"skill": "weather", "enabled": True})
    assert response.status_code == 202
    assert _approve(orch, response.json()["task_id"])["status"] == "ok"
    assert switches.state()["disabled"] == []
    conn = settings_db.get_conn()
    try:
        assert conn.execute("SELECT count(*) FROM skill_switch_receipts").fetchone()[0] == 1
    finally:
        conn.close()



def test_the_curator_never_archives_a_skill_switched_off_everywhere(tmp_path):
    """review-H329 F9: a switched-off skill cannot record use, so its idle clock is the
    owner's switch, not neglect; archiving it would cost its approval at the next start."""
    from datetime import UTC, datetime, timedelta

    from agents.core.skills.curator import SkillCurator
    from agents.core.skills.usage import ORIGIN_AGENT, SkillUsageStore

    kept, idle, local = (_skill(tmp_path, "kept_helper", "Kept Helper"), _skill(tmp_path, "idle_helper", "Idle Helper"),
                         _skill(tmp_path, "local_helper", "Local Helper"))
    loader = SimpleNamespace(skills={s.name: s for s in (kept, idle, local)})
    usage = SkillUsageStore(path=tmp_path / "usage.json")
    for skill in (kept, idle, local):
        usage.note_created(skill.name, ORIGIN_AGENT)
    _store(disabled=["kept helper"], channel_disabled={"telegram": ["Local Helper"]})
    curator = SkillCurator(loader, usage, archive_dir=tmp_path / "archive",
                           now=lambda: datetime.now(UTC) + timedelta(days=100))
    out = asyncio.run(curator.run())
    assert sorted(out["lifecycle"]["archived"]) == ["Idle Helper", "Local Helper"]
    assert "Kept Helper" in loader.skills and kept.path.exists()


def test_the_skill_list_is_not_open_to_the_network(monkeypatch, tmp_path):
    """review-H329 F11: GET /skills carries the owner's switches and channel names."""
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import _deps

    _client(monkeypatch, tmp_path)
    monkeypatch.delitem(web.app.dependency_overrides, _deps.user_guard)    # the suite's no-op guard
    _store(channel_disabled={"telegram": ["Spotify"]})
    lan = TestClient(web.app, client=("192.168.1.77", 5555), base_url="http://192.168.1.10:8000")
    assert lan.get("/skills").status_code in (401, 403)
    monkeypatch.setattr(web, "USER_TOKEN", "h329-user")
    assert lan.get("/skills", headers={"X-User-Token": "h329-user"}).status_code == 200


def test_a_skill_switched_back_on_is_not_archived_for_its_time_off(monkeypatch, tmp_path):
    from datetime import UTC, datetime, timedelta

    from agents.core.skills.curator import SkillCurator
    from agents.core.skills.usage import ORIGIN_AGENT, SkillUsageStore, latest_activity_at

    client, orch = _client(monkeypatch, tmp_path)
    _ready_approval(monkeypatch, tmp_path, orch)
    usage = SkillUsageStore(path=tmp_path / "usage.json")
    orch.skill_usage = usage
    usage.note_created("Weather Intel", ORIGIN_AGENT)
    usage._items["Weather Intel"]["last_used_at"] = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    _store(disabled=["Weather Intel"])
    pending = _post(client, {"skill": "weather", "enabled": True})
    assert pending.status_code == 202 and latest_activity_at(usage.get("Weather Intel")) is not None
    assert _approve(orch, pending.json()["task_id"])["status"] == "ok"
    anchor = latest_activity_at(usage.get("Weather Intel"))
    assert anchor is not None and datetime.now(UTC) - anchor < timedelta(minutes=1)
    rec = usage.get("Weather Intel")
    assert rec.get("switch_on_count") == 1 and not rec.get("use_count")
    curator = SkillCurator(SimpleNamespace(skills=orch.skills.skills), usage, archive_dir=tmp_path / "archive",
                           now=lambda: datetime.now(UTC) + timedelta(days=10))
    out = asyncio.run(curator.run())
    assert "Weather Intel" not in out["lifecycle"]["archived"]



def test_a_switch_off_or_a_failed_switch_on_does_not_restart_the_clock(monkeypatch, tmp_path):
    from agents.core.skills.usage import ORIGIN_AGENT, SkillUsageStore, latest_activity_at

    client, orch = _client(monkeypatch, tmp_path, log=_Log(fail=True))
    usage = SkillUsageStore(path=tmp_path / "usage.json")
    orch.skill_usage = usage
    usage.note_created("Weather Intel", ORIGIN_AGENT)
    _store(disabled=["Weather Intel"])
    assert _post(client, {"skill": "weather", "enabled": True}).status_code == 503     # not recorded, not kept
    assert latest_activity_at(usage.get("Weather Intel")) is None
    client, orch = _client(monkeypatch, tmp_path)
    orch.skill_usage = usage
    _post(client, {"skill": "spotify", "enabled": False})
    assert latest_activity_at(usage.get("Spotify") or {}) is None


def test_a_reset_names_the_switch_rows_it_keeps():
    from agents.core import settings_db

    kept = settings_db.reset_kept("skills")
    assert "disabled" in kept and "channel_disabled" in kept
    assert {"skills.disabled", "skills.channel_disabled"} <= set(settings_db.reset_kept_all())
