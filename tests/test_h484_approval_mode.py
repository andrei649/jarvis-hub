"""H484 — one dial that sets how much Nerva may do without asking, on every surface.

The dial is ``autonomy.mode`` (auto | ask | off). These tests pin what the row still
lacked: the ``/approvals`` chat command, the ``nerva approvals mode`` verb, the effective
mode on every approval card, the audited write, and the fail-closed reading of a stored
value the dial does not know (Hermes: an unknown value warns and falls back to asking; a
YAML 1.1 boolean spelling is normalized, never taken for the loosest position).

No position silences approvals: every word the dial accepts only adds asking.

Hermetic: bare orchestrator doubles, the settings write monkeypatched, no model.
"""

from __future__ import annotations

import io
import logging
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.cli.nerva import EXIT_OK, EXIT_USAGE, Context, main
from agents.core.autonomy import mode as mode_module
from agents.core.autonomy.policy import ACT, ASK, AutonomyPolicy, RiskTier
from agents.core.commands import ADMIN, Principal, build_default_registry
from agents.core.routers import autonomy as routes
from agents.core.routers._deps import admin_guard
from agents.core.security.types import SecurityEventType

OWNER = Principal(channel="telegram", sender="42", admin=True)
GUEST = Principal(channel="telegram", sender="7", admin=False)


class _Audit:
    def __init__(self, fail=False):
        self.events, self.fail = [], fail

    def log(self, event):
        if self.fail:
            raise OSError("audit store is read-only")
        self.events.append(event)


_stores: list[dict] = []     # the settings each double reads; the `writes` fixture fills them


def _orch(mode="auto", agent_modes=None, audit=None, pending=()):
    store = {"autonomy.mode": mode, "autonomy.agent_modes": dict(agent_modes or {})}
    _stores.append(store)
    policy = AutonomyPolicy(mode=mode, agent_modes=dict(agent_modes or {}))
    orch = SimpleNamespace(
        commands=build_default_registry(),
        autonomy=SimpleNamespace(policy=policy),
        autonomy_queue=SimpleNamespace(pending_decisions=lambda: list(pending)),
        audit=audit if audit is not None else _Audit(),
        get_setting=lambda key, default=None: store.get(key, default),
        reloads=0,
    )

    def reload():
        orch.reloads += 1

    orch.load_runtime_settings = reload
    orch.store = store
    return orch


@pytest.fixture
def writes(monkeypatch):
    """The settings store double: records every category write."""
    seen = []
    _stores.clear()

    def put_category(category, values):
        seen.append((category, dict(values)))
        for store in _stores:            # what a reload then reads back
            store.update({f"{category}.{key}": value for key, value in values.items()})
        return len(values), []

    monkeypatch.setattr(mode_module, "_put_category", put_category)
    return seen


# ── reading a stored value ───────────────────────────────────────────────────


@pytest.mark.parametrize("stored,expected,known", [
    ("auto", "auto", True), ("ASK", "ask", True), (" Off ", "off", True),
    (None, "auto", True), ("", "auto", True),
    # YAML 1.1 reads a bare `off` as False: it is the dial's off, never the loosest position.
    (False, "off", True),
    # Anything else is not a position: fall back to asking, and say so.
    (True, "ask", False), ("yolo", "ask", False), (3, "ask", False), ("   ", "ask", False),
    # Hermes' words mean the same stored as typed.
    ("smart", "auto", True), ("manual", "ask", True),
    ({"mode": "auto"}, "ask", False),
])
def test_a_stored_mode_is_normalized_and_an_unknown_one_falls_back_to_asking(stored, expected, known):
    assert mode_module.normalize_mode(stored) == (expected, known)


def test_the_policy_never_runs_an_unknown_mode_as_auto(caplog):
    action = {"kind": "note.write", "risk_tier": int(RiskTier.REVERSIBLE), "agent": "friday"}
    assert AutonomyPolicy(mode="auto").decide(action).outcome == ACT
    mode_module._warned.clear()
    with caplog.at_level(logging.WARNING):
        decision = AutonomyPolicy(mode="yolo").decide(action)
    assert decision.outcome == ASK
    assert any("yolo" in record.getMessage() for record in caplog.records)
    # A per-agent override the dial does not know asks too; a boolean False is off.
    assert AutonomyPolicy(mode="auto", agent_modes={"friday": "none"}).decide(action).outcome == ASK
    assert AutonomyPolicy(mode=False).effective_mode() == "off"
    assert AutonomyPolicy(mode=False).decide(
        {"kind": "x", "risk_tier": int(RiskTier.READ_ONLY)}).outcome == ASK


_ASKS = {ACT: 0, "notify": 1, ASK: 2}


def test_no_position_of_the_dial_asks_less_than_auto():
    """Every word the dial accepts (and every unknown one) asks at least as much as
    ``auto`` for every kind of action — and ``auto`` itself is pinned for what it is: a
    payment inside the owner's per-action and daily caps runs without asking; over the
    cap, or any other irreversible action, asks."""
    inside = {"kind": "payment.send", "amount": 49, "agent": "friday"}
    over = {"kind": "payment.send", "amount": 51, "agent": "friday"}
    irreversible = {"kind": "x", "risk_tier": int(RiskTier.IRREVERSIBLE_OR_MONEY)}
    actions = [inside, over, irreversible,
               *({"kind": "x", "risk_tier": int(tier)} for tier in RiskTier)]

    def decide(mode, action):
        return AutonomyPolicy(mode=mode, cap_per_action=50, daily_ceiling=200).decide(action)

    assert set(mode_module.MODES) == {"auto", "ask", "off"}
    assert decide("auto", inside).outcome == ACT           # the truth about `auto`
    assert decide("auto", inside).tier == RiskTier.IRREVERSIBLE_OR_MONEY
    assert decide("auto", over).outcome == ASK and decide("auto", irreversible).outcome == ASK
    for mode in ("ask", "off", "manual", "yolo", "none", False, True, 3, "   "):
        assert decide(mode, inside).outcome == ASK, mode
    for mode in (*mode_module.MODES, "smart", "manual", "yolo", "none", False, True):
        for action in actions:
            assert _ASKS[decide(mode, action).outcome] >= _ASKS[decide("auto", action).outcome], (mode, action)


# ── the one write path ───────────────────────────────────────────────────────


def test_set_global_mode_persists_applies_live_reloads_and_audits(writes):
    orch = _orch("auto")
    result = mode_module.set_global_mode(orch, "ask", actor="owner", surface="chat")
    assert result == {"mode": "ask", "was": "auto", "changed": True, "audited": True,
                      "effective": True, "live": "ask"}
    assert writes == [("autonomy", {"mode": "ask"})]
    assert orch.autonomy.policy.mode == "ask"
    assert orch.reloads == 1          # the coordinator's next tick reads the new value
    (event,) = orch.audit.events
    assert event.event_type == SecurityEventType.SETTINGS_CHANGE
    assert event.action_taken == "settings_update"
    assert "autonomy.mode" in event.content_preview
    assert "auto → ask" in event.content_preview and "chat" in event.content_preview


def test_set_global_mode_refuses_a_word_that_is_not_a_position(writes):
    orch = _orch("ask")
    for word in ("yolo", "none", "", "disabled", "smart", "manual"):
        with pytest.raises(ValueError):
            mode_module.set_global_mode(orch, word, actor="owner", surface="chat")
    assert writes == [] and orch.autonomy.policy.mode == "ask" and orch.audit.events == []


def test_a_write_the_audit_log_could_not_record_says_so(writes):
    orch = _orch("auto", audit=_Audit(fail=True))
    result = mode_module.set_global_mode(orch, "off", actor="owner", surface="cli")
    assert result["mode"] == "off" and result["audited"] is False
    assert orch.autonomy.policy.mode == "off"


def test_a_skipped_settings_write_changes_nothing(monkeypatch):
    monkeypatch.setattr(mode_module, "_put_category", lambda category, values: (0, ["mode"]))
    orch = _orch("ask")
    with pytest.raises(mode_module.ModeNotSaved):
        mode_module.set_global_mode(orch, "auto", actor="owner", surface="chat")
    assert orch.autonomy.policy.mode == "ask"
    # The failed attempt is on the record.
    assert [event.action_taken for event in orch.audit.events] == ["settings_update_failed"]


def test_describe_names_the_effective_mode_and_where_it_comes_from():
    orch = _orch("auto", agent_modes={"friday": "ask"})
    assert mode_module.describe(orch, "friday") == {"effective": "ask", "source": "agent", "global": "auto"}
    assert mode_module.describe(orch, "jarvis") == {"effective": "auto", "source": "global", "global": "auto"}
    assert mode_module.describe(orch, None) == {"effective": "auto", "source": "global", "global": "auto"}


# ── /approvals in chat ───────────────────────────────────────────────────────


async def _say(orch, text, principal=OWNER):
    return await orch.commands.dispatch(text, orch=orch, principal=principal)


@pytest.mark.asyncio
async def test_approvals_is_an_owner_command_in_the_registry():
    command = build_default_registry().get("approvals")
    assert command is not None and command.tier == ADMIN
    assert command.usage == "[auto|ask|off]"


@pytest.mark.asyncio
async def test_bare_approvals_shows_the_mode_and_changes_nothing(writes):
    orch = _orch("ask", agent_modes={"friday": "off"})
    outcome = await _say(orch, "/approvals")
    assert outcome.status == "answered"
    assert "Approval mode: ask" in outcome.reply
    assert "friday: off" in outcome.reply
    assert "/approvals [auto|ask|off]" in outcome.reply
    assert writes == [] and orch.audit.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("word,mode", [
    ("ask", "ask"), ("OFF", "off"), ("auto", "auto"),
    # Hermes' words for the same two positions.
    ("manual", "ask"), ("smart", "auto"),
])
async def test_the_owner_sets_the_mode_from_chat(writes, word, mode):
    start = "ask" if mode != "ask" else "auto"
    orch = _orch(start)
    outcome = await _say(orch, f"/approvals {word}")
    assert outcome.status == "answered"
    assert f"Approval mode: {mode}" in outcome.reply
    assert writes == [("autonomy", {"mode": mode})]
    assert orch.autonomy.policy.mode == mode
    assert len(orch.audit.events) == 1 and "chat" in orch.audit.events[0].content_preview


@pytest.mark.asyncio
async def test_off_is_the_strictest_position_and_the_reply_says_so(writes):
    orch = _orch("auto")
    outcome = await _say(orch, "/approvals off")
    assert orch.autonomy.policy.mode == "off"
    assert "every action waits for your approval" in outcome.reply
    assert "no position that turns approvals off" in outcome.reply


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/approvals yolo", "/approvals none", "/approvals auto now", "/approvals on"])
async def test_an_unknown_word_changes_nothing(writes, text):
    orch = _orch("ask")
    outcome = await _say(orch, text)
    assert "Usage: /approvals [auto|ask|off]" in outcome.reply
    assert "Approval mode remains ask" in outcome.reply
    assert writes == [] and orch.autonomy.policy.mode == "ask" and orch.audit.events == []


@pytest.mark.asyncio
async def test_a_non_owner_cannot_see_or_set_the_mode(writes):
    orch = _orch("ask")
    for text in ("/approvals", "/approvals auto"):
        outcome = await _say(orch, text, GUEST)
        assert outcome.status == "refused"
        assert "Approval mode" not in outcome.reply      # the mode is not disclosed either
    assert writes == [] and orch.autonomy.policy.mode == "ask"
    # The only audit rows are the access gate's denials (H058); no settings change.
    assert [event.action_taken for event in orch.audit.events] == ["slash_command_denied"] * 2


@pytest.mark.asyncio
async def test_the_handler_rechecks_the_owner_at_the_write(writes):
    """Defence in depth (Hermes re-checks admin at the side-effect boundary): the handler
    itself refuses a non-owner even if a caller reached it past the registry's tier gate."""
    from agents.core.commands import CommandContext

    orch = _orch("ask")
    command = orch.commands.get("approvals")
    reply = await command.handler(CommandContext(orch=orch, principal=GUEST, name="approvals", args="auto"))
    assert "Only the owner can change the approval mode" in reply
    assert writes == [] and orch.autonomy.policy.mode == "ask"


@pytest.mark.asyncio
async def test_a_write_that_did_not_take_effect_is_reported_as_such(monkeypatch):
    monkeypatch.setattr(mode_module, "_put_category", lambda category, values: (0, ["mode"]))
    orch = _orch("ask")
    outcome = await _say(orch, "/approvals auto")
    assert "Approval mode remains ask" in outcome.reply
    assert orch.autonomy.policy.mode == "ask"


# ── the approval card and the routes ─────────────────────────────────────────


def _task(task_id, agent, tier):
    data = {"id": task_id, "agent": agent, "kind": "note.write", "title": f"task {task_id}",
            "risk_tier": int(tier), "status": "blocked"}
    return SimpleNamespace(**data, to_dict=lambda: dict(data))


def _app(orch, monkeypatch):
    monkeypatch.setattr(routes, "get_orch", lambda: orch)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[admin_guard] = lambda: None
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_every_approval_card_carries_the_effective_mode(monkeypatch):
    orch = _orch("auto", agent_modes={"friday": "ask"}, pending=[
        _task(1, "friday", RiskTier.REVERSIBLE), _task(2, "jarvis", RiskTier.IRREVERSIBLE_OR_MONEY)])
    async with _app(orch, monkeypatch) as client:
        body = (await client.get("/autonomy/approvals")).json()
    assert body["mode"] == "auto"
    cards = {card["id"]: card for card in body["pending"]}
    assert cards[1]["approval_mode"] == {"effective": "ask", "source": "agent", "global": "auto"}
    assert cards[2]["approval_mode"] == {"effective": "auto", "source": "global", "global": "auto"}
    # The buckets carry the same cards.
    assert body["reversible"][0]["approval_mode"]["effective"] == "ask"
    assert body["irreversible"][0]["approval_mode"]["effective"] == "auto"


@pytest.mark.asyncio
async def test_the_mode_route_writes_through_the_audited_path(monkeypatch, writes):
    orch = _orch("auto")
    async with _app(orch, monkeypatch) as client:
        response = await client.post("/autonomy/mode", json={"mode": "ASK"})
        assert response.status_code == 200
        assert response.json() == {"mode": "ask", "ok": True, "was": "auto", "audited": True,
                                   "effective": True, "looser": {}}
        assert (await client.get("/autonomy/mode")).json() == {"mode": "ask"}
        refused = await client.post("/autonomy/mode", json={"mode": "yolo"})
        assert refused.status_code == 422
    assert writes == [("autonomy", {"mode": "ask"})]
    assert len(orch.audit.events) == 1 and "api" in orch.audit.events[0].content_preview


@pytest.mark.asyncio
async def test_the_mode_route_reads_an_unknown_stored_value_as_ask(monkeypatch):
    orch = _orch("yolo")
    async with _app(orch, monkeypatch) as client:
        assert (await client.get("/autonomy/mode")).json() == {"mode": "ask"}


# ── nerva approvals mode ─────────────────────────────────────────────────────


class _Hub:
    base_url = "http://127.0.0.1:8080"

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def get(self, path):
        self.calls.append(("GET", path, None))
        return self.replies[("GET", path)]

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        return self.replies[("POST", path)]


def _run(args, replies):
    hub = _Hub(replies)
    out, err = io.StringIO(), io.StringIO()
    code = main(args, context=Context(environ={}, out=out, err=err, client_factory=lambda _: hub))
    return code, out.getvalue(), err.getvalue(), hub.calls


def test_the_cli_shows_the_mode():
    code, out, _err, calls = _run(["approvals", "mode"], {
        ("GET", "/autonomy/policy"): {"global": "ask", "agents": {"friday": "off"}}})
    assert code == EXIT_OK
    assert calls == [("GET", "/autonomy/policy", None)]
    assert "approval mode: ask" in out and "friday: off" in out


@pytest.mark.parametrize("word,mode", [("off", "off"), ("manual", "ask"), ("smart", "auto"), ("AUTO", "auto")])
def test_the_cli_sets_the_mode_through_the_admin_route(word, mode):
    code, out, _err, calls = _run(["approvals", "mode", word], {
        ("POST", "/autonomy/mode"): {"mode": mode, "ok": True, "was": "ask", "audited": True}})
    assert code == EXIT_OK
    assert calls == [("POST", "/autonomy/mode", {"mode": mode})]
    assert f"approval mode: {mode}" in out


def test_the_cli_refuses_an_unknown_word_without_calling_the_hub():
    code, _out, err, calls = _run(["approvals", "mode", "yolo"], {})
    assert code == EXIT_USAGE and calls == []
    assert "auto|ask|off" in err


def test_the_cli_reports_a_mode_the_hub_did_not_confirm():
    from agents.cli.nerva import EXIT_FAILED

    code, _out, err, _calls = _run(["approvals", "mode", "ask"], {
        ("POST", "/autonomy/mode"): {"mode": "auto", "ok": True}})
    assert code == EXIT_FAILED and "did not become effective" in err


def test_the_cli_list_shows_the_mode_on_each_card():
    code, out, _err, _calls = _run(["approvals", "list"], {("GET", "/autonomy/approvals"): {
        "mode": "auto",
        "pending": [{"id": 4, "risk_tier": 1, "reversible": True, "kind": "note.write", "title": "t",
                     "approval_mode": {"effective": "ask", "source": "agent", "global": "auto"}}]}})
    assert code == EXIT_OK
    assert "mode now ask (agent override; global auto)" in out


def test_the_cli_list_prefers_the_mode_a_card_was_asked_under():
    code, out, _err, _calls = _run(["approvals", "list"], {("GET", "/autonomy/approvals"): {
        "mode": "auto",
        "pending": [{"id": 4, "risk_tier": 1, "reversible": True, "kind": "note.write", "title": "t",
                     "approval_mode": {"effective": "auto", "source": "global", "global": "auto"},
                     "asked_under": {"mode": "ask", "source": "global", "global": "ask", "by_mode": True}}]}})
    assert code == EXIT_OK
    assert "asked under mode ask (global; the mode is why it waits)" in out
