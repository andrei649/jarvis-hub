"""H484 — the second adversarial review of the approval dial, one test per finding.

Real ``Orchestrator`` + real settings store + the real routers for the write paths, a real
``TaskQueue`` + ``AutonomyWorker`` for the recall, the real ToolRPC + kernel for the
owner-approved terminal card.

The invariant behind M1–M3: the settings store is the truth; after any interleaving of
writers and of the coordinator's sync, the live policy holds what the store holds.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.cli import nerva
from agents.cli.client import HubError
from agents.cli.nerva import EXIT_FAILED, EXIT_OK, Context, main
from agents.core import safe_mode, settings_db
from agents.core.autonomy import mode as mode_module
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget
from agents.core.commands import Principal
from agents.core.routers import admin as admin_routes
from agents.core.routers import autonomy as routes
from agents.core.routers._deps import admin_guard
from tests.test_h277_smart_terminal_integration import propose, runtime, use_real_kernel  # noqa: F401

OWNER = Principal(channel="telegram", sender="42", admin=True)
SAME_ORIGIN = {"origin": "http://test", "content-type": "application/json"}


class _Audit:
    def __init__(self):
        self.events = []

    def log(self, event):
        self.events.append(event)

    @property
    def rows(self):
        return [(event.action_taken, event.content_preview) for event in self.events]


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "h484-settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_TESTING", "1")
    monkeypatch.delenv(safe_mode.ENV_NAME, raising=False)
    yield settings_db
    safe_mode.reset()


@pytest.fixture
async def boot(store, monkeypatch):
    """Boot a real orchestrator over the store; ``boot(mode=, agent_modes=, safe=)``."""
    from agents.core.config import JarvisConfig
    from agents.core.orchestrator import Orchestrator

    made = []

    def _boot(mode="auto", agent_modes=None, safe=False):
        store.put_category("autonomy", {"mode": mode, "agent_modes": agent_modes or {}})
        if safe:
            monkeypatch.setenv(safe_mode.ENV_NAME, "1")
        orch = Orchestrator(JarvisConfig())
        orch.load_runtime_settings()
        orch.autonomy_queue.initialize()
        orch.audit = _Audit()
        made.append(orch)
        return orch

    yield _boot
    for orch in made:
        await orch.aclose()


def _client(orch, monkeypatch):
    monkeypatch.setattr(routes, "get_orch", lambda: orch)
    monkeypatch.setattr(admin_routes, "get_orch", lambda: orch)
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(admin_routes.router)
    app.dependency_overrides[admin_guard] = lambda: None
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _live(orch, *agents):
    policy = orch.autonomy.policy
    return {"global": policy.mode, **{agent: policy.effective_mode(agent) for agent in agents}}


async def _say(orch, text):
    return (await orch.commands.dispatch(text, orch=orch, principal=OWNER)).reply


# ── M1: the coordinator's sync never interleaves with a writer ───────────────


async def test_a_sync_racing_a_tightening_leaves_the_policy_at_the_stored_off(boot, store, monkeypatch):
    orch = boot("auto")
    armed, writers = {"on": True}, []

    def race():
        """The owner's `/approvals off` arrives right after the sync read its value."""
        if armed["on"]:
            armed["on"] = False
            writer = threading.Thread(target=mode_module.set_global_mode, args=(orch, "off"),
                                      kwargs={"actor": "telegram:42", "surface": "chat"})
            writer.start()
            writer.join(timeout=0.5)        # an unlocked sync lets it finish here
            writers.append(writer)

    real_get = orch.get_setting

    def get_setting(key, default=None):                 # the read the first fix made
        value = real_get(key, default)
        if key == "autonomy.mode":
            race()
        return value

    orch.get_setting = get_setting
    real_read = getattr(mode_module, "_read_store", None)
    if real_read is not None:                           # the read this fix makes

        def read_store(key, default):
            value = real_read(key, default)
            if key == "mode":
                race()
            return value

        monkeypatch.setattr(mode_module, "_read_store", read_store)

    orch._autonomy._sync_approval_mode()
    for writer in writers:
        writer.join(timeout=5)
    assert writers and not writers[0].is_alive()
    assert store.get_value("autonomy", "mode") == "off"
    assert orch.autonomy.policy.mode == "off"           # the owner was told off holds
    task = await orch.autonomy.submit("jarvis", "draft_email", "after the race")
    assert task.status == "blocked"


# ── M2: live policy == store after any interleaving of writers ───────────────


async def test_a_settings_page_write_between_persist_and_apply_wins_as_the_store_has_it(boot, store, monkeypatch):
    orch = boot("ask")
    real_put = mode_module._put_category

    def racing(category, values):
        out = real_put(category, values)                              # A persists auto …
        store.put_category("autonomy", {"mode": "off"})               # … B saves off …
        mode_module.sync_policy(orch)                                 # … and applies it
        return out

    monkeypatch.setattr(mode_module, "_put_category", racing)
    result = mode_module.set_global_mode(orch, "auto", actor="telegram:42", surface="chat")
    assert store.get_value("autonomy", "mode") == "off"
    assert orch.autonomy.policy.mode == "off"                         # never looser than the store
    assert result["effective"] is False and result["live"] == "off"
    assert orch._autonomy._sync_approval_mode() == "off"
    assert (await orch.autonomy.submit("jarvis", "draft_email", "the last write was off")).status == "blocked"


async def test_concurrent_writers_on_every_path_leave_the_policy_at_the_store(boot, store, monkeypatch):
    orch = boot("ask")
    async with _client(orch, monkeypatch) as client:
        async def page(mode):
            return await client.put("/api/admin/settings/autonomy", json={"values": {"mode": mode}})

        async def chat(mode):
            return await asyncio.to_thread(
                mode_module.set_global_mode, orch, mode, actor="telegram:42", surface="chat")

        async def tick():
            return await asyncio.to_thread(orch._autonomy._sync_approval_mode)

        for _round in range(6):
            await asyncio.gather(page("off"), chat("auto"), tick(), page("ask"), chat("off"), tick(),
                                 chat("auto"), page("auto"))
            assert orch.autonomy.policy.mode == store.get_value("autonomy", "mode")


async def test_the_generic_settings_write_applies_under_the_lock(boot, store, monkeypatch):
    """The generic route holds the same lock around put + apply: a dedicated writer that
    is mid-write cannot be overtaken between its persist and its apply."""
    orch = boot("auto")
    entered, release = threading.Event(), threading.Event()
    real_put = mode_module._put_category

    def slow_put(category, values):
        out = real_put(category, values)
        entered.set()
        release.wait(timeout=5)
        return out

    monkeypatch.setattr(mode_module, "_put_category", slow_put)
    async with _client(orch, monkeypatch) as client:
        writer = asyncio.create_task(asyncio.to_thread(
            mode_module.set_global_mode, orch, "off", actor="telegram:42", surface="chat"))
        await asyncio.to_thread(entered.wait, 5)
        page = asyncio.create_task(client.put("/api/admin/settings/autonomy", json={"values": {"mode": "auto"}}))
        await asyncio.sleep(0.2)
        assert not page.done()                         # it waits for the writer's lock
        release.set()
        await writer
        assert (await page).status_code == 200
    assert orch.autonomy.policy.mode == store.get_value("autonomy", "mode") == "auto"


# ── M3: an override write never loses another agent's override ───────────────


async def test_an_override_write_in_safe_mode_keeps_every_stored_override(boot, store, monkeypatch):
    orch = boot("auto", {"friday": "off", "trader": "ask", "scout": "auto"}, safe=True)
    orch.agents = {name: object() for name in ("friday", "trader", "scout", "vision")}
    async with _client(orch, monkeypatch) as client:
        response = await client.post("/autonomy/policy", json={"agent": "vision", "mode": "ask"})
    assert response.status_code == 200, response.text
    assert store.get_value("autonomy", "agent_modes") == {
        "friday": "off", "trader": "ask", "scout": "auto", "vision": "ask"}
    action, preview = orch.audit.rows[-1]
    assert action == "settings_update"
    assert "friday: off" in preview and "scout: auto" in preview and "vision: ask" in preview
    assert "→" in preview and "via api, by admin" in preview


async def test_an_override_write_over_a_stale_cache_keeps_what_another_process_stored(boot, store, monkeypatch):
    orch = boot("auto")
    orch.agents = {name: object() for name in ("friday", "trader", "scout")}
    store.put_category("autonomy", {"agent_modes": {"friday": "off", "trader": "ask"}})   # nerva config set
    async with _client(orch, monkeypatch) as client:
        response = await client.post("/autonomy/policy", json={"agent": "scout", "mode": "auto"})
    assert response.status_code == 200
    assert store.get_value("autonomy", "agent_modes") == {"friday": "off", "trader": "ask", "scout": "auto"}
    assert _live(orch, "friday", "trader", "scout") == {
        "global": "auto", "friday": "off", "trader": "ask", "scout": "auto"}


# ── M4: safe mode never asks less than normal mode ───────────────────────────


@pytest.mark.parametrize("safe", [False, True])
async def test_safe_mode_keeps_the_overrides_that_ask_more(boot, safe):
    orch = boot("auto", {"friday": "off", "trader": "ask", "scout": "auto", "odd": "yolo"}, safe=safe)
    live = _live(orch, "friday", "trader", "scout", "odd")
    assert live["friday"] == "off" and live["trader"] == "ask" and live["odd"] == "ask"
    assert live["scout"] == "auto"                     # the global mode in safe mode, its override otherwise
    if safe:
        assert "scout" not in orch.autonomy.policy.agent_modes
        assert "scout" not in (orch.get_setting("autonomy.agent_modes", {}) or {})
    assert (await orch.autonomy.submit("friday", "draft_email", "friday is off")).status == "blocked"
    orch._autonomy._sync_approval_mode()
    assert _live(orch, "friday", "trader") == {"global": "auto", "friday": "off", "trader": "ask"}


async def test_a_looser_override_written_in_safe_mode_is_stored_and_reported_not_in_force(boot, store, monkeypatch):
    orch = boot("ask", {"friday": "off"}, safe=True)
    orch.agents = {"friday": object(), "scout": object()}
    async with _client(orch, monkeypatch) as client:
        response = await client.post("/autonomy/policy", json={"agent": "scout", "mode": "auto"})
    assert response.status_code == 503 and response.json()["error"] == "mode_not_effective"
    assert store.get_value("autonomy", "agent_modes") == {"friday": "off", "scout": "auto"}
    assert orch.autonomy.policy.effective_mode("scout") == "ask"


# ── M5: an owner-approved kernel-receipt task under ask/off ──────────────────


@pytest.mark.parametrize("mode", ["auto", "ask", "off"])
async def test_an_owner_approved_terminal_card_is_never_shown_done_when_nothing_ran(runtime, mode):  # noqa: F811
    queue, worker, orch, sandbox, _seen = runtime
    use_real_kernel(runtime)
    worker.policy.mode = mode
    answer = await propose(orch)
    await worker.apply_decision(answer["task_id"], "accept", "admin")
    summary = await worker.tick()
    final = queue.get(answer["task_id"])
    if mode == "auto":
        assert final.status == "done" and sandbox.commands == ["printf hello"]
        return
    # The kernel honours an approval receipt only in auto (an owner decision, unchanged).
    assert sandbox.commands == []
    assert final.status == "failed" and summary["failed"] == 1 and summary["done"] == 0
    assert final.result["reason"] == "kernel_queued"
    assert f"approval mode is {mode}" in final.result["error"] and "auto" in final.result["error"]


async def test_no_text_promises_that_every_owner_approval_runs(boot):
    orch = boot("auto")
    for word in ("ask", "off"):
        reply = await _say(orch, f"/approvals {word}")
        assert "only in auto" in reply, reply
        assert "what you approved yourself still runs." not in reply
    assert "only in auto" in mode_module.meaning("ask") and "only in auto" in mode_module.meaning("off")


# ── m1: under off only a human's approval runs ───────────────────────────────


def _worker(tmp_path, executor, mode="auto"):
    queue = TaskQueue(db_path=str(tmp_path / "tasks.db")).initialize()
    return queue, AutonomyWorker(queue, policy=AutonomyPolicy(mode=mode), executor=executor,
                                 budget=InterruptBudget(per_day=4))


async def test_under_off_every_machine_decided_approval_is_recalled(tmp_path):
    ran = []

    async def executor(task):
        ran.append(task.title)
        return {"ok": True}

    queue, worker = _worker(tmp_path, executor)
    try:
        machine = ("policy", "smart_approval", "consent", "system", "scheduler", "worker", "kernel",
                   "auto", "", None, "Policy", "policy ", "aux_llm", "runtime", "something-new")
        human = (("admin", "accept"), ("telegram", "accept"), ("user", "edit"))
        ids = {}
        for by in machine:
            task = await worker.submit("friday", "draft_email", f"machine {by!r}")
            queue._conn.execute("UPDATE tasks SET decided_by=? WHERE id=?", (by, task.id))
            queue._conn.commit()
            ids[task.id] = by
        for by, decision in human:
            task = await worker.submit("friday", "draft_email", f"human {by}")
            queue._conn.execute("UPDATE tasks SET decided_by=?, decision=? WHERE id=?", (by, decision, task.id))
            queue._conn.commit()
        worker.policy.mode = "off"
        await worker.tick(limit=50)
        assert sorted(ran) == ["human admin", "human telegram", "human user"]
        for task_id, by in ids.items():
            assert queue.get(task_id).status in ("blocked", "approved"), by
            assert queue.get(task_id).status != "done", by
    finally:
        queue.close()


async def test_a_refused_recall_holds_the_task_without_a_traceback_every_tick(tmp_path, caplog):
    ran = []

    async def executor(task):
        ran.append(task.title)
        return {"ok": True}

    queue, worker = _worker(tmp_path, executor)
    try:
        task = await worker.submit("friday", "draft_email", "cannot go back")
        worker.policy.mode = "off"
        real = queue.transition

        def refuse(task_id, new_status, **kwargs):
            if new_status == TaskStatus.BLOCKED:
                raise TaskQueueError("consent transition requires private queue authority")
            return real(task_id, new_status, **kwargs)

        queue.transition = refuse
        with caplog.at_level(logging.DEBUG):
            for _ in range(3):
                await worker.tick(limit=50)
        assert ran == [] and queue.get(task.id).status == "approved"
        noisy = [record for record in caplog.records
                 if record.levelno >= logging.WARNING and "held, not run" in record.getMessage()]
        assert len(noisy) <= 1 and all(record.exc_info is None for record in noisy)
    finally:
        queue.close()


# ── m4: what `off` recalled stays visible, and the replies say so ────────────


async def test_recalled_tasks_wait_in_the_inbox_and_the_replies_count_them(boot):
    orch = boot("auto")

    async def executor(task):
        return {"ok": True}

    orch.autonomy.executor = executor
    quiet = await orch.autonomy.submit("jarvis", "draft_email", "quiet one", attention_mode="digest")
    loud = await orch.autonomy.submit("jarvis", "draft_email", "loud one")
    assert quiet.status == loud.status == "approved"
    reply = await _say(orch, "/approvals off")
    assert "returns to your inbox" in reply
    await orch.autonomy.tick()
    waiting = {task.id for task in orch.autonomy_queue.pending_decisions()}
    assert {quiet.id, loud.id} <= waiting                       # whatever its attention mode
    assert "2 tasks recalled by off are waiting in your inbox" in await _say(orch, "/approvals")
    reply = await _say(orch, "/approvals auto")
    assert "2 tasks recalled by off are still waiting in your inbox" in reply
    assert "do not resume by themselves" in reply
    await orch.autonomy.tick()
    assert orch.autonomy_queue.get(loud.id).status == "blocked"  # safe: they wait for the owner


# ── m2 / m3: the generic settings paths validate, audit and apply at once ────


async def test_generic_writes_of_the_overrides_are_validated_and_audited(boot, store, monkeypatch):
    orch = boot("ask")
    async with _client(orch, monkeypatch) as client:
        for bad in ("friday=auto", ["x"], {"friday": {"a": 1}}, {"a" * 5000: "auto"}, {"friday": "yolo"},
                    {"fri\nday": "ask"}, {"__proto__": "auto"}, {str(n): "ask" for n in range(200)}, 7, None):
            response = await client.put("/api/admin/settings/autonomy", json={"values": {"agent_modes": bad}})
            assert response.status_code == 422, (bad, response.text)
        assert store.get_value("autonomy", "agent_modes") == {}
        ok = await client.put("/api/admin/settings/autonomy", json={"values": {"agent_modes": {"friday": "auto"}}})
        assert ok.status_code == 200
        assert orch.autonomy.policy.agent_modes == {"friday": "auto"}
        assert any("agent_modes" in preview and "friday: auto" in preview for _action, preview in orch.audit.rows)
        refused = await client.post("/api/admin/settings/import", headers=SAME_ORIGIN,
                                    json={"settings": {"autonomy": {"agent_modes": {"friday": "yolo"}}}})
        assert refused.status_code == 422


async def test_import_reset_and_undo_reach_the_live_policy_at_once(boot, store, monkeypatch):
    orch = boot("auto")
    async with _client(orch, monkeypatch) as client:
        imported = await client.post("/api/admin/settings/import", headers=SAME_ORIGIN, json={
            "settings": {"autonomy": {"mode": "off", "agent_modes": {"friday": "ask"}}}})
        assert imported.status_code == 200, imported.text
        assert orch.autonomy.policy.mode == "off" and orch.autonomy.policy.agent_modes == {"friday": "ask"}
        assert any("friday: ask" in preview for _action, preview in orch.audit.rows)
        reset = await client.post("/api/admin/settings/autonomy/reset", headers=SAME_ORIGIN, json={})
        assert reset.status_code == 200, reset.text
        assert orch.autonomy.policy.mode == store.get_value("autonomy", "mode") == "auto"
        assert orch.autonomy.policy.agent_modes == {}
        undone = await client.post("/api/admin/settings/undo", headers=SAME_ORIGIN, json={})
        assert undone.status_code == 200, undone.text
        assert orch.autonomy.policy.mode == store.get_value("autonomy", "mode") == "off"
        assert orch.autonomy.policy.agent_modes == {"friday": "ask"}


# ── m5: the override route validates the agent and answers honestly ──────────


async def test_the_override_route_takes_only_agents_of_this_hub(boot, store, monkeypatch):
    orch = boot("ask")
    orch.agents = {"friday": object(), "jarvis": object()}
    async with _client(orch, monkeypatch) as client:
        for agent in ("no-such-agent", "fri\nday\x00", "__proto__", "x" * 100000, "  ", "a b"):
            response = await client.post("/autonomy/policy", json={"agent": agent, "mode": "auto"})
            assert response.status_code == 422, agent
        assert store.get_value("autonomy", "agent_modes") == {}
        assert all("\n" not in preview and "\x00" not in preview for _action, preview in orch.audit.rows)
        for agent in ("friday", "owner"):                      # the roster, and a documented special id
            assert (await client.post("/autonomy/policy", json={"agent": agent, "mode": "off"})).status_code == 200
        # An override of an agent that is gone can still be cleared.
        store.put_category("autonomy", {"agent_modes": {"retired": "auto", "friday": "off"}})
        cleared = await client.post("/autonomy/policy", json={"agent": "retired", "mode": "default"})
        assert cleared.status_code == 200 and store.get_value("autonomy", "agent_modes") == {"friday": "off"}


async def test_a_write_of_what_is_already_stored_is_audited_as_a_no_op(boot, monkeypatch):
    orch = boot("auto")
    async with _client(orch, monkeypatch) as client:
        await client.post("/autonomy/mode", json={"mode": "off"})
        await client.post("/autonomy/mode", json={"mode": "off"})
    actions = [action for action, _preview in orch.audit.rows]
    assert actions == ["settings_update", "settings_noop"]
    assert "unchanged" in orch.audit.rows[-1][1]


# ── m6 / m7: the CLI says what is in force, and audits its own store write ───


def test_the_cli_reports_the_mode_in_force_when_a_write_did_not_take_effect():
    class Hub:
        base_url = "http://127.0.0.1:8080"

        def post(self, path, body):
            raise HubError(503, "Service Unavailable")

        def get(self, path):
            return {"global": "off", "agents": {}, "looser": {}}

    out, err = io.StringIO(), io.StringIO()
    code = main(["approvals", "mode", "auto"],
                context=Context(environ={}, out=out, err=err, client_factory=lambda _: Hub()))
    assert code == EXIT_FAILED
    assert "approval mode in force: off" in err.getvalue()
    assert "auto did not take effect" in err.getvalue()
    # A tightening that holds although the settings did not confirm it is said to hold.
    out, err = io.StringIO(), io.StringIO()
    code = main(["approvals", "mode", "off"],
                context=Context(environ={}, out=out, err=err, client_factory=lambda _: Hub()))
    assert code == EXIT_FAILED and "approval mode in force: off" in err.getvalue()
    assert "did not take effect" not in err.getvalue()


def test_nerva_config_set_validates_and_audits_the_overrides(store, monkeypatch):
    audit = _Audit()
    monkeypatch.setattr(nerva, "_audit_log", lambda: audit)

    def run(*args):
        out, err = io.StringIO(), io.StringIO()
        code = main(["config", "set", *args], context=Context(environ={}, out=out, err=err))
        return code, out.getvalue() + err.getvalue()

    code, said = run("autonomy.agent_modes", '{"friday": "yolo"}')
    assert code != EXIT_OK and store.get_value("autonomy", "agent_modes", {}) == {}
    code, said = run("autonomy.agent_modes", '{"friday": "ask"}')
    assert code == EXIT_OK, said
    assert store.get_value("autonomy", "agent_modes") == {"friday": "ask"}
    code, said = run("autonomy.mode", "off")
    assert code == EXIT_OK, said
    previews = [preview for action, preview in audit.rows if action == "settings_update"]
    assert any("agent_modes" in preview and "friday: ask" in preview and "via cli" in preview for preview in previews)
    assert any("autonomy.mode: auto → off" in preview and "via cli" in preview for preview in previews)


# ── the empty string, and the coordinator when the sync fails ────────────────


async def test_an_explicitly_stored_empty_mode_asks(boot, store):
    assert mode_module.normalize_mode("") == ("ask", False)
    assert mode_module.normalize_mode(None) == ("auto", True)
    orch = boot("auto")
    conn = store.get_conn()
    conn.execute("UPDATE settings SET value='\"\"' WHERE category='autonomy' AND key='mode'")
    conn.commit()
    conn.close()
    assert orch._autonomy._sync_approval_mode() == "ask"
    assert orch.autonomy.policy.mode == "ask"
    # A reset still lands on the declared default.
    assert store.plan_reset("autonomy")["autonomy"]["mode"] == "auto"


async def test_a_failed_sync_runs_nothing_proactive(store, tmp_path, monkeypatch):
    from agents.core import autonomy_coordinator, estop

    observed, ticked = [], []

    class Observer:
        async def observe(self):
            observed.append(1)

    queue = TaskQueue(db_path=str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(mode="auto"), budget=InterruptBudget(per_day=4))
    real_tick = worker.tick

    async def tick(*args, **kwargs):
        ticked.append(kwargs)
        return await real_tick(*args, **kwargs)

    worker.tick = tick
    dispatched = []
    orch = SimpleNamespace(
        autonomy=worker, autonomy_queue=queue, observer=Observer(), event_watcher=Observer(),
        reflector=None, curator=None, cognition=None, ingestion_watcher=None,
        get_setting=lambda key, default=None: {
            "llm.kanban": True, "llm.kanban_dispatch": True, "llm.tool_loop_enabled": True,
            "system.error_backlog_sync_enabled": False}.get(key, default))

    def broken(_orch):
        raise OSError("settings store unreadable")

    monkeypatch.setattr(mode_module, "sync_policy", broken)
    monkeypatch.setattr(autonomy_coordinator, "autonomy_tick_seconds", lambda orch: 0.01)
    monkeypatch.setattr(estop, "check_paused", lambda *a, **k: False)
    coordinator = autonomy_coordinator.AutonomyCoordinator(orch)
    coordinator.kanban_dispatcher = lambda: dispatched.append(1) or (_ for _ in ()).throw(AssertionError("dispatch"))
    loop = asyncio.create_task(coordinator.loop())
    try:
        for _ in range(200):
            if len(ticked) >= 2:
                break
            await asyncio.sleep(0.01)
    finally:
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)
        queue.close()
    assert len(ticked) >= 2 and observed == [] and dispatched == []
    assert worker.policy.mode == "auto"            # left exactly as it was
