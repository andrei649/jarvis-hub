"""H484 — the defects an adversarial review found in the approval dial, one test each.

These run against the real settings store (a private ``settings_db`` file), a real
``TaskQueue`` + ``AutonomyWorker``, the real ``AutonomyCoordinator.loop`` and, for the boot
window, a real ``Orchestrator`` — the places the defects lived — not patched doubles.
"""

from __future__ import annotations

import asyncio
import io
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.cli.nerva import EXIT_OK, Context, main
from agents.core import settings_db
from agents.core.autonomy import mode as mode_module
from agents.core.autonomy.policy import ACT, ASK, AutonomyPolicy, RiskTier
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget
from agents.core.commands import CommandContext, Principal, _status, build_default_registry
from agents.core.routers import autonomy as routes
from agents.core.routers._deps import admin_guard

OWNER = Principal(channel="telegram", sender="42", admin=True)


class _Audit:
    def __init__(self):
        self.events = []

    def log(self, event):
        self.events.append(event)


@pytest.fixture
def store(monkeypatch, tmp_path):
    """A real settings store of this test's own."""
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "h484-settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    return settings_db


def _hub(store, tmp_path, *, executor=None, reload_works=True, correctable=True):
    """An orchestrator-shaped object over the real store, queue and worker. Its
    ``get_setting`` reads a cache that ``load_runtime_settings`` fills from the store —
    as ``Orchestrator`` does — and that reload can be made to fail quietly."""
    queue = TaskQueue(db_path=str(tmp_path / "tasks.db")).initialize()
    policy = AutonomyPolicy(mode=store.get_value("autonomy", "mode", "auto"),
                            agent_modes=dict(store.get_value("autonomy", "agent_modes", {}) or {}))
    worker = AutonomyWorker(queue, policy=policy,
                            executor=executor, budget=InterruptBudget(per_day=4))
    cache: dict = {}
    hub = SimpleNamespace(commands=build_default_registry(), autonomy=worker, autonomy_queue=queue,
                          audit=_Audit(), agents={}, llm_router=None, reload_works=reload_works)

    def load():
        if not hub.reload_works:
            return                       # Orchestrator.load_runtime_settings swallows its own errors
        cache.clear()
        for category, items in store.get_all().items():
            for item in items:
                cache[f"{category}.{item['key']}"] = item["value"]

    hub.reload_works = True
    load()
    hub.reload_works = reload_works
    hub.load_runtime_settings = load
    hub.get_setting = lambda key, default=None: cache.get(key, default)
    if correctable:
        hub._runtime_settings = cache
    hub.cache = cache
    return hub


async def _say(hub, text, principal=OWNER):
    return await hub.commands.dispatch(text, orch=hub, principal=principal)


def _client(hub, monkeypatch):
    monkeypatch.setattr(routes, "get_orch", lambda: hub)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[admin_guard] = lambda: None
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ── BLOCKER-1: the stored mode governs from the first decision after a restart ──


@pytest.mark.parametrize("stored", ["off", "ask"])
async def test_a_restarted_hub_runs_the_stored_mode_from_its_first_decision(store, tmp_path, monkeypatch, stored):
    from agents.core.config import JarvisConfig
    from agents.core.orchestrator import Orchestrator

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_TESTING", "1")
    store.put_category("autonomy", {"mode": stored, "agent_modes": {"friday": "ask"}})
    orch = Orchestrator(JarvisConfig())
    try:
        # No coordinator tick has run: this is the boot window.
        assert orch.autonomy.policy.mode == stored
        assert orch.autonomy.policy.agent_modes == {"friday": "ask"}
        assert mode_module.global_mode(orch) == stored
        assert mode_module.describe(orch, "jarvis")["effective"] == stored
        orch.autonomy_queue.initialize()     # what Orchestrator.initialize() does first
        task = await orch.autonomy.submit("jarvis", "draft_email", "the first task after a restart")
        assert task.status == "blocked" and task.decided_by == "policy"
        reply = (await orch.commands.dispatch("/approvals", orch=orch, principal=OWNER)).reply
        assert f"Approval mode: {stored}" in reply
    finally:
        await orch.aclose()


async def test_the_coordinator_syncs_the_stored_mode_while_the_estop_is_engaged(store, tmp_path, monkeypatch):
    from agents.core import autonomy_coordinator, estop

    hub = _hub(store, tmp_path)
    assert hub.autonomy.policy.mode == "auto"
    store.put_category("autonomy", {"mode": "off"})      # e.g. the generic settings write
    hub.load_runtime_settings()
    monkeypatch.setattr(autonomy_coordinator, "autonomy_tick_seconds", lambda orch: 0.01)
    monkeypatch.setattr(estop, "check_paused", lambda *a, **k: True)
    loop = asyncio.create_task(autonomy_coordinator.AutonomyCoordinator(hub).loop())
    try:
        for _ in range(200):
            if hub.autonomy.policy.mode == "off":
                break
            await asyncio.sleep(0.01)
        assert hub.autonomy.policy.mode == "off"
    finally:
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)
        hub.autonomy_queue.close()


# ── MAJOR-2a: `off` does not execute work the policy approved on its own ──


async def test_off_returns_policy_approved_work_to_waiting_and_still_runs_what_the_owner_approved(store, tmp_path):
    ran = []

    async def executor(task):
        ran.append(task.title)
        return {"ok": True}

    hub = _hub(store, tmp_path, executor=executor)
    worker, queue = hub.autonomy, hub.autonomy_queue
    try:
        by_policy = await worker.submit("friday", "draft_email", "approved by the policy")
        assert (by_policy.status, by_policy.decided_by) == ("approved", "policy")
        worker.policy.mode = "ask"
        held = await worker.submit("friday", "draft_email", "approved by the owner")
        assert held.status == "blocked"
        owner = await worker.apply_decision(held.id, "accept", decided_by="admin")
        assert (owner.status, owner.decided_by) == ("approved", "admin")

        mode_module.set_global_mode(hub, "off", actor="owner", surface="test")
        summary = await worker.tick()
        assert ran == ["approved by the owner"]
        back = queue.get(by_policy.id)
        assert (back.status, back.decided_by, back.decision) == ("blocked", "policy", "needs-approval")
        assert summary["held"] >= 1
        assert by_policy.id in {task.id for task in queue.pending_decisions()}

        # The owner approves the returned task: now it runs, still in `off`.
        await worker.apply_decision(by_policy.id, "accept", decided_by="admin")
        await worker.tick()
        assert ran == ["approved by the owner", "approved by the policy"]
    finally:
        queue.close()


async def test_auto_and_ask_still_run_policy_approved_work(store, tmp_path):
    ran = []

    async def executor(task):
        ran.append(task.title)
        return {"ok": True}

    hub = _hub(store, tmp_path, executor=executor)
    try:
        await hub.autonomy.submit("friday", "draft_email", "queued in auto")
        hub.autonomy.policy.mode = "ask"         # ask gates new work; it recalls nothing
        await hub.autonomy.tick()
        assert ran == ["queued in auto"]
    finally:
        hub.autonomy_queue.close()


# ── MAJOR-2b: global `off` is a floor; a looser override under `ask` is named ──


def test_no_per_agent_override_loosens_a_global_off():
    reversible = {"kind": "note.write", "risk_tier": int(RiskTier.REVERSIBLE), "agent": "friday"}
    policy = AutonomyPolicy(mode="off", agent_modes={"friday": "auto"})
    assert policy.effective_mode("friday") == "off"
    assert policy.decide(reversible).outcome == ASK
    assert policy.decide({**reversible, "risk_tier": int(RiskTier.READ_ONLY)}).outcome == ASK
    # Under `ask` the override keeps deciding (an existing graduated-autonomy feature).
    assert AutonomyPolicy(mode="ask", agent_modes={"friday": "auto"}).decide(reversible).outcome == ACT


async def test_the_card_and_the_replies_say_what_an_override_really_does(store, tmp_path, monkeypatch):
    store.put_category("autonomy", {"mode": "auto", "agent_modes": {"friday": "auto", "vision": "off"}})
    hub = _hub(store, tmp_path)
    try:
        reply = (await _say(hub, "/approvals ask")).reply
        assert "Approval mode: ask" in reply
        looser = next((line for line in reply.splitlines() if "still asks less" in line), "")
        assert "friday" in looser and "vision" not in looser
        shown = (await _say(hub, "/approvals")).reply
        assert "friday: auto" in shown and "asks less than the global mode" in shown

        reply = (await _say(hub, "/approvals off")).reply
        assert "no per-agent override loosens" in reply
        assert mode_module.describe(hub, "friday") == {"effective": "off", "source": "global", "global": "off"}
        assert mode_module.looser_overrides(hub) == {}
    finally:
        hub.autonomy_queue.close()


def test_the_cli_names_the_agents_whose_override_stays_looser():
    class Hub:
        base_url = "http://127.0.0.1:8080"

        def get(self, path):
            return {"global": "ask", "agents": {"friday": "auto", "vision": "off"}, "looser": {"friday": "auto"}}

        def post(self, path, body):
            return {"mode": "ask", "ok": True, "was": "auto", "audited": True, "effective": True,
                    "looser": {"friday": "auto"}}

    for args in (["approvals", "mode"], ["approvals", "mode", "ask"]):
        out, err = io.StringIO(), io.StringIO()
        code = main(args, context=Context(environ={}, out=out, err=err, client_factory=lambda _: Hub()))
        assert code == EXIT_OK
        assert "friday" in out.getvalue() and "asks less than the global mode" in out.getvalue()


# ── MAJOR-2c: the override write is audited, through the same path ──


async def test_the_override_route_persists_applies_and_audits(store, tmp_path, monkeypatch):
    hub = _hub(store, tmp_path)
    try:
        async with _client(hub, monkeypatch) as client:
            response = await client.post("/autonomy/policy", json={"agent": "friday", "mode": "ASK"})
            assert response.status_code == 200
            assert response.json()["agents"] == {"friday": "ask"} and response.json()["audited"] is True
            assert store.get_value("autonomy", "agent_modes") == {"friday": "ask"}
            assert hub.autonomy.policy.agent_modes == {"friday": "ask"}
            (event,) = hub.audit.events
            assert event.action_taken == "settings_update"
            assert "agent_modes[friday]" in event.content_preview
            assert "default → ask" in event.content_preview and "via api, by admin" in event.content_preview
            cleared = await client.post("/autonomy/policy", json={"agent": "friday", "mode": "default"})
            assert cleared.json()["agents"] == {} and len(hub.audit.events) == 2
            assert (await client.post("/autonomy/policy", json={"agent": "friday", "mode": "yolo"})).status_code == 422
    finally:
        hub.autonomy_queue.close()


# ── MAJOR-3: what `auto` really does with the irreversible tier ──


def test_auto_runs_a_payment_inside_the_caps_and_the_texts_say_so():
    payment = {"kind": "payment.send", "amount": 49, "agent": "friday"}
    decision = AutonomyPolicy(mode="auto", cap_per_action=50, daily_ceiling=200).decide(payment)
    assert (decision.outcome, decision.tier) == (ACT, RiskTier.IRREVERSIBLE_OR_MONEY)
    assert AutonomyPolicy(mode="auto", cap_per_action=50).decide({**payment, "amount": 51}).outcome == ASK
    for stricter in ("ask", "off"):
        assert AutonomyPolicy(mode=stricter, cap_per_action=50).decide(payment).outcome == ASK
    text = mode_module.meaning("auto")
    assert "always ask" not in text and "money caps" in text


async def test_no_reply_claims_the_irreversible_tier_always_asks(store, tmp_path):
    hub = _hub(store, tmp_path)
    try:
        for text in ("/approvals", "/approvals auto", "/approvals ask", "/approvals off"):
            reply = (await _say(hub, text)).reply
            assert "always ask" not in reply, reply
        assert "money caps" in (await _say(hub, "/approvals auto")).reply
    finally:
        hub.autonomy_queue.close()


# ── MAJOR-4: a failed settings refresh never reverts a tightening, and is reported ──


async def test_a_tightening_survives_a_reload_that_quietly_failed(store, tmp_path):
    hub = _hub(store, tmp_path, reload_works=False, correctable=False)
    try:
        reply = (await _say(hub, "/approvals off")).reply
        assert store.get_value("autonomy", "mode") == "off"
        assert hub.get_setting("autonomy.mode") == "auto"            # the stale cache
        assert hub.autonomy.policy.mode == "off"
        assert "running settings still read" in reply
        for _ in range(3):                                           # the coordinator's ticks
            assert mode_module.sync_policy(hub) == "off"
        assert hub.autonomy.policy.mode == "off"
        external = {"kind": "email.send", "risk_tier": int(RiskTier.EXTERNAL), "agent": "friday"}
        assert hub.autonomy.policy.decide(external).outcome == ASK
        # Once the settings catch up, the pending value is spent and the store decides.
        hub.reload_works = True
        hub.load_runtime_settings()
        assert mode_module.sync_policy(hub) == "off"
        store.put_category("autonomy", {"mode": "ask"})
        hub.load_runtime_settings()
        assert mode_module.sync_policy(hub) == "ask"
    finally:
        hub.autonomy_queue.close()


async def test_a_loosening_that_did_not_take_effect_is_reported_as_such(store, tmp_path, monkeypatch):
    store.put_category("autonomy", {"mode": "off"})
    hub = _hub(store, tmp_path, reload_works=False, correctable=False)
    try:
        result = mode_module.set_global_mode(hub, "auto", actor="owner", surface="test")
        assert result["effective"] is False and result["live"] == "off"
        assert hub.autonomy.policy.mode == "off" and mode_module.sync_policy(hub) == "off"
        reply = (await _say(hub, "/approvals auto")).reply
        assert "Approval mode remains off" in reply and "did not become effective" in reply
        async with _client(hub, monkeypatch) as client:
            response = await client.post("/autonomy/mode", json={"mode": "auto"})
            assert response.status_code == 503
            assert response.json()["error"] == "mode_not_effective" and response.json()["live"] == "off"
    finally:
        hub.autonomy_queue.close()


async def test_a_failed_reload_is_corrected_in_the_cache_the_coordinator_reads(store, tmp_path):
    hub = _hub(store, tmp_path, reload_works=False, correctable=True)
    try:
        result = mode_module.set_global_mode(hub, "off", actor="owner", surface="test")
        assert result["effective"] is True
        assert hub.get_setting("autonomy.mode") == "off" and mode_module.sync_policy(hub) == "off"
    finally:
        hub.autonomy_queue.close()


# ── MINOR-5: two writers ──


def test_two_concurrent_writers_leave_the_store_the_policy_and_the_audit_agreeing(store, tmp_path, monkeypatch):
    hub = _hub(store, tmp_path)
    real_put = mode_module._put_category

    def slow_put(category, values):
        if values.get("mode") == "off":
            time.sleep(0.05)
        result = real_put(category, values)
        if values.get("mode") == "auto":
            time.sleep(0.15)
        return result

    monkeypatch.setattr(mode_module, "_put_category", slow_put)
    try:
        hub.autonomy.policy.mode = "ask"
        writers = [threading.Thread(target=mode_module.set_global_mode, args=(hub, word),
                                    kwargs={"actor": word, "surface": "test"}) for word in ("auto", "off")]
        for writer in writers:
            writer.start()
            time.sleep(0.01)
        for writer in writers:
            writer.join()
        stored = store.get_value("autonomy", "mode")
        assert hub.autonomy.policy.mode == stored == hub.get_setting("autonomy.mode")
        assert f"→ {stored} " in hub.audit.events[-1].content_preview
    finally:
        hub.autonomy_queue.close()


# ── MINOR-6: a store that refuses the write ──


async def test_a_refused_write_is_a_structured_503_and_is_audited(store, tmp_path, monkeypatch):
    hub = _hub(store, tmp_path)

    def locked(category, values):
        raise OSError("database is locked")

    monkeypatch.setattr(mode_module, "_put_category", locked)
    try:
        async with _client(hub, monkeypatch) as client:
            response = await client.post("/autonomy/mode", json={"mode": "off"})
            assert response.status_code == 503 and response.json()["error"] == "mode_not_saved"
            override = await client.post("/autonomy/policy", json={"agent": "friday", "mode": "ask"})
            assert override.status_code == 503 and override.json()["error"] == "mode_not_saved"
        assert hub.autonomy.policy.mode == "auto" and hub.autonomy.policy.agent_modes == {}
        assert [event.action_taken for event in hub.audit.events] == ["settings_update_failed"] * 2
        assert "NOT SAVED" in hub.audit.events[0].content_preview
        reply = (await _say(hub, "/approvals off")).reply
        assert "Approval mode remains auto" in reply and len(hub.audit.events) == 3
    finally:
        hub.autonomy_queue.close()


# ── MINOR-7: what is displayed is what the policy runs ──


@pytest.mark.parametrize("stored,runs", [(False, "off"), ("yolo", "ask"), ("manual", "ask"), ("smart", "auto")])
async def test_every_reader_shows_the_mode_the_policy_runs(store, tmp_path, monkeypatch, stored, runs):
    from agents.core.routers import swarm

    hub = _hub(store, tmp_path)
    hub.cache["autonomy.mode"] = stored
    hub.autonomy.policy.mode = stored
    hub.autonomy.policy.agent_modes = {"friday": "none", "vision": False, "blank": "   "}
    try:
        assert hub.autonomy.policy.effective_mode() == runs
        status = _status(CommandContext(hub, OWNER, "status", ""))
        assert f"autonomy mode: {runs}" in status
        async with _client(hub, monkeypatch) as client:
            policy = (await client.get("/autonomy/policy")).json()
        assert policy["global"] == runs
        assert policy["agents"] == {"friday": "ask", "vision": "off"}
        assert swarm.autonomy_mode(hub) == runs
        # `nerva approvals mode` can read it.
        out = io.StringIO()
        hub_client = SimpleNamespace(base_url="http://x", get=lambda path: policy)
        assert main(["approvals", "mode"], context=Context(
            environ={}, out=out, err=io.StringIO(), client_factory=lambda _: hub_client)) == EXIT_OK
        assert f"approval mode: {runs}" in out.getvalue()
    finally:
        hub.autonomy_queue.close()


@pytest.mark.parametrize("stored,runs", [(False, "off"), ("yolo", "ask"), (None, "auto")])
def test_nerva_explain_reads_the_stored_mode_as_the_policy_does(store, stored, runs):
    from agents.cli.nerva import explain_action

    store.put_category("autonomy", {"mode": "auto"})
    conn = store.get_conn()
    conn.execute("UPDATE settings SET value=? WHERE category='autonomy' AND key='mode'",
                 (__import__("json").dumps(stored),))
    conn.commit()
    conn.close()
    assert explain_action("note.write", title="x")["autonomy_mode"] == runs


# ── MINOR-8: the card shows the mode the task was asked under ──


async def test_the_card_shows_the_mode_recorded_when_the_task_was_held(store, tmp_path, monkeypatch):
    store.put_category("autonomy", {"mode": "ask"})
    hub = _hub(store, tmp_path)
    try:
        held = await hub.autonomy.submit("friday", "draft_email", "held only because the mode was ask")
        assert held.status == "blocked"
        mode_module.set_global_mode(hub, "auto", actor="owner", surface="test")
        tiered = await hub.autonomy.submit("friday", "payment.send", "pay", payload={"amount": 500})
        assert tiered.status == "blocked"
        async with _client(hub, monkeypatch) as client:
            cards = {card["id"]: card for card in (await client.get("/autonomy/approvals")).json()["pending"]}
        assert cards[held.id]["approval_mode"]["effective"] == "auto"          # today's mode
        assert cards[held.id]["asked_under"] == {"mode": "ask", "source": "global", "global": "ask",
                                                 "by_mode": True}
        assert cards[tiered.id]["asked_under"] == {"mode": "auto", "source": "global", "global": "auto",
                                                   "by_mode": False}
    finally:
        hub.autonomy_queue.close()


async def test_a_task_returned_by_off_records_that(store, tmp_path):
    hub = _hub(store, tmp_path)
    try:
        task = await hub.autonomy.submit("friday", "draft_email", "approved, then recalled")
        hub.autonomy.policy.mode = "off"
        await hub.autonomy.tick()
        assert hub.autonomy_queue.ask_context(task.id) == {
            "mode": "off", "source": "global", "global": "off", "by_mode": True}
    finally:
        hub.autonomy_queue.close()


# ── MINOR-9 and the NITs ──


def test_a_blank_override_is_no_override_and_a_blank_mode_is_not_auto():
    reversible = {"kind": "note.write", "risk_tier": int(RiskTier.REVERSIBLE), "agent": "friday"}
    for blank in ("   ", "\t", ""):
        policy = AutonomyPolicy(mode="ask", agent_modes={"friday": blank})
        assert policy.effective_mode("friday") == "ask" and policy.decide(reversible).outcome == ASK
    assert mode_module.normalize_mode("   ") == ("ask", False)
    assert mode_module.normalize_mode("") == ("auto", True)


def test_hermes_words_mean_the_same_stored_or_typed():
    for word, mode in (("manual", "ask"), ("smart", "auto"), (" Manual ", "ask")):
        assert mode_module.parse_requested(word) == mode
        assert mode_module.normalize_mode(word) == (mode, True)
        assert AutonomyPolicy(mode=word).effective_mode() == mode


async def test_a_generic_settings_write_reaches_the_live_policy_at_once(store, tmp_path, monkeypatch):
    from agents.core.routers import admin

    hub = _hub(store, tmp_path)
    monkeypatch.setattr(admin, "get_orch", lambda: hub)
    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin_guard] = lambda: None
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put("/api/admin/settings/autonomy",
                                        json={"values": {"mode": "off", "agent_modes": {"friday": "ask"}}})
        assert response.status_code == 200, response.text
        assert hub.autonomy.policy.mode == "off" and hub.get_setting("autonomy.mode") == "off"
        assert hub.autonomy.policy.agent_modes == {"friday": "ask"}
    finally:
        hub.autonomy_queue.close()


# ── the per-agent overrides are a real setting now, and safe mode still drops them ──


def test_overrides_persist_in_the_store_and_safe_mode_serves_none(store, monkeypatch):
    from agents.core import safe_mode

    _updated, skipped = store.put_category("autonomy", {"agent_modes": {"friday": "auto"}})
    assert skipped == [] and store.get_value("autonomy", "agent_modes") == {"friday": "auto"}
    assert safe_mode.get_value("autonomy", "agent_modes", {}) == {"friday": "auto"}
    monkeypatch.setenv(safe_mode.ENV_NAME, "1")
    try:
        assert safe_mode.get_value("autonomy", "agent_modes", {}) == {}        # the boot read
        served = safe_mode.override_settings({"autonomy.agent_modes": {"friday": "auto"}})
        assert "autonomy.agent_modes" not in served                            # the runtime read
    finally:
        safe_mode.reset()
