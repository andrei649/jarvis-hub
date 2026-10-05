"""Real signed queue and pinned board claims, without a live model/provider."""

import asyncio
import hashlib
import hmac
from types import SimpleNamespace

import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.commands import Principal
from agents.core.kanban.context import KanbanContext, current_context, kanban_scope
from agents.core.kanban.dispatcher import KanbanDispatcher
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kernel import Decision, Verdict

OWNER = Principal(channel="web", admin=True)


def fixture_runtime(tmp_path, monkeypatch, verdict=Verdict.QUEUE):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    signer = DetachedHMACSigner(
        lambda b: hmac.new(b"synthetic-kanban-test-key-20261004", b, hashlib.sha256).hexdigest()
    )
    head = [None]

    def cas(old, new):
        if head[0] != old:
            return False
        head[0] = new
        return True

    queue = TaskQueue(
        str(tmp_path / "queue.db"),
        mediation_mode="enforce",
        mediation_signer=signer,
        mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
        mediation_scope="global",
    ).initialize()
    calls = []

    def kernel(action):
        calls.append(action)
        return Decision(verdict, tier=2, reason="synthetic board test")

    worker = AutonomyWorker(
        queue, policy=AutonomyPolicy(mode="auto"), kernel=kernel, mediation_signer=signer
    )
    # Production binds the one-shot intake bridge through the coordinator.
    worker.bind_mediation(kernel, signer)
    settings = {"llm.kanban": True, "llm.kanban_dispatch": True, "llm.tool_loop_enabled": True}
    orch = SimpleNamespace(
        autonomy=worker,
        autonomy_queue=queue,
        agents={"jarvis": object(), "reviewer": object()},
        get_setting=lambda key, default=None: settings.get(key, default),
    )
    seen = []

    async def runner(orch, *, prompt, agent_id, session_id):
        ctx = current_context()
        seen.append((ctx, prompt, agent_id, session_id))
        with kb.connect_closing() as conn:
            assert kb.complete_task(
                conn, ctx.task_id, result="actual synthetic result", expected_run_id=ctx.run_id
            )
        return "actual synthetic result"

    controller = KanbanDispatcher(orch, home=tmp_path / "board", runner=runner)
    executor = TaskExecutor(execution_guard=worker.execution_allowed)
    executor.register(controller.KIND, controller.execute)
    worker.executor = executor.execute
    return controller, orch, settings, seen, calls


def create(controller, **kwargs):
    with (
        kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)),
        kb.connect_closing() as conn,
    ):
        return kb.create_task(
            conn,
            title=kwargs.pop("title", "work"),
            assignee=kwargs.pop("assignee", "jarvis"),
            **kwargs,
        )


def read(controller, tid):
    with (
        kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)),
        kb.connect_closing() as conn,
    ):
        return kb.get_task(conn, tid)


@pytest.mark.asyncio
async def test_signed_request_deduplicates_and_waits_for_approval(tmp_path, monkeypatch):
    c, orch, _, seen, calls = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c)
    first = await c.request(OWNER)
    again = await c.request(OWNER)
    assert first["queued"][0]["task_id"] == tid
    assert again["queued"][0]["queue_id"] == first["queued"][0]["queue_id"]
    assert len(orch.autonomy_queue.list()) == len(calls) == 1
    assert orch.autonomy_queue.list()[0].status == "blocked"
    pending = orch.autonomy_queue.list()[0]
    assert "work" in pending.payload["prompt"]
    assert pending.payload["prompt_sha256"]
    assert read(c, tid).status == "ready"
    assert (await orch.autonomy.tick())["ran"] == 0
    assert seen == []


@pytest.mark.asyncio
async def test_approved_real_worker_tick_claims_exact_board_run(tmp_path, monkeypatch):
    c, orch, _, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c)
    queued = (await c.request(OWNER))["queued"][0]
    orch.autonomy_queue.transition(
        queued["queue_id"], TaskStatus.APPROVED, decided_by="owner", decision="approve"
    )
    result = await orch.autonomy.tick()
    assert result["done"] == 1
    assert len(seen) == 1 and seen[0][0].task_id == tid and seen[0][0].run_id is not None
    assert seen[0][2] == "jarvis" and seen[0][3].startswith("kanban::")
    assert seen[0][1] == orch.autonomy_queue.get(queued["queue_id"]).payload["prompt"]
    assert read(c, tid).status == "done"
    assert current_context() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["body", "comment", "dependency"])
async def test_changed_board_input_cannot_borrow_pending_approval(tmp_path, monkeypatch, mutation):
    c, orch, _, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c)
    qid = (await c.request(OWNER))["queued"][0]["queue_id"]
    with (
        kanban_scope(KanbanContext(c.home, "dispatcher", can_mutate=True)),
        kb.connect_closing() as conn,
    ):
        if mutation == "body":
            with kb.write_txn(conn):
                conn.execute("UPDATE tasks SET body=? WHERE id=?", ("changed instructions", tid))
        elif mutation == "comment":
            kb.add_comment(conn, tid, author="jarvis", body="changed instructions")
        else:
            parent = kb.create_task(conn, title="new dependency", assignee="jarvis")
            kb.link_tasks(conn, parent, tid)
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    assert (await orch.autonomy.tick())["failed"] == 1
    assert seen == [] and read(c, tid).current_run_id is None


@pytest.mark.asyncio
async def test_refused_kernel_never_claims_or_calls_agent(tmp_path, monkeypatch):
    c, orch, _, seen, calls = fixture_runtime(tmp_path, monkeypatch, Verdict.DENY)
    tid = create(c)
    answer = await c.request(OWNER)
    assert answer["queued"] == [] and calls
    assert orch.autonomy_queue.list() == [] and seen == []
    assert read(c, tid).status == "ready"


@pytest.mark.asyncio
async def test_disabled_and_guest_request_touch_no_storage(tmp_path, monkeypatch):
    c, _, settings, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    settings["llm.kanban_dispatch"] = False
    assert (await c.request(OWNER))["ok"] is False
    settings["llm.kanban_dispatch"] = True
    assert (await c.request(Principal(channel="web")))["ok"] is False
    assert not c.home.exists() and seen == []


@pytest.mark.asyncio
async def test_controller_restart_recovers_queue_binding_without_duplicate(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c)
    first = (await c.request(OWNER))["queued"][0]
    with (
        kanban_scope(KanbanContext(c.home, "dispatcher", can_mutate=True)),
        kb.connect_closing() as conn,
        kb.write_txn(conn),
    ):
        conn.execute(
            "UPDATE nerva_dispatches SET queue_id=NULL, state='prepared' WHERE task_id=?",
            (tid,),
        )
    restarted = KanbanDispatcher(orch, home=c.home, runner=c.runner)
    after = (await restarted.request(OWNER))["queued"][0]
    assert after["queue_id"] == first["queue_id"] and len(orch.autonomy_queue.list()) == 1


@pytest.mark.asyncio
async def test_direct_handler_has_no_executor_permit(tmp_path, monkeypatch):
    c, orch, _, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c)
    qid = (await c.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    claimed = orch.autonomy_queue.claim_mediated(
        qid, execution_id="00000000-0000-4000-8000-000000000001"
    )
    assert (await c.execute(claimed))["status"] == "refused"
    assert seen == [] and read(c, tid).status == "ready"


@pytest.mark.asyncio
async def test_prose_without_board_terminal_action_is_failure(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c)

    async def incomplete(*args, **kwargs):
        return "I will finish later"

    c.runner = incomplete
    qid = (await c.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    assert (await orch.autonomy.tick())["failed"] == 1
    assert read(c, tid).status != "done"


@pytest.mark.asyncio
async def test_review_reservation_and_profile_caps(tmp_path, monkeypatch):
    c, _, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    ready = create(c, title="highest ready", priority=100)
    review = create(c, title="review", assignee="reviewer")
    with (
        kanban_scope(KanbanContext(c.home, "dispatcher", can_mutate=True)),
        kb.connect_closing() as conn,
    ):
        kb.request_review(conn, review, summary="review evidence", reviewer="reviewer")
    answer = await c.request(OWNER, limit=1)
    assert answer["queued"][0]["task_id"] == review
    assert read(c, ready).status == "ready"


@pytest.mark.asyncio
async def test_overlapping_requests_have_one_durable_submission(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    create(c)
    other = KanbanDispatcher(orch, home=c.home, runner=c.runner)
    a, b = await asyncio.gather(c.request(OWNER), other.request(OWNER))
    assert a["queued"][0]["queue_id"] == b["queued"][0]["queue_id"]
    assert len(orch.autonomy_queue.list()) == 1


@pytest.mark.asyncio
async def test_pending_work_counts_against_each_agent_capacity(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    first = create(c, title="first")
    create(c, title="second")
    reviewer = create(c, assignee="reviewer")
    queued = (await c.request(OWNER))["queued"]
    assert {item["task_id"] for item in queued} == {first, reviewer}
    assert len(orch.autonomy_queue.list()) == 2


@pytest.mark.asyncio
async def test_changed_pending_input_does_not_create_a_second_live_submission(
    tmp_path, monkeypatch
):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c)
    old = (await c.request(OWNER))["queued"][0]
    with (
        kanban_scope(KanbanContext(c.home, "dispatcher", can_mutate=True)),
        kb.connect_closing() as conn,
        kb.write_txn(conn),
    ):
        conn.execute("UPDATE tasks SET body=? WHERE id=?", ("new instruction", tid))
    assert (await c.request(OWNER))["queued"] == []
    assert len(orch.autonomy_queue.list()) == 1
    orch.autonomy_queue.transition(
        old["queue_id"], TaskStatus.APPROVED, decided_by="owner", decision="approve"
    )
    assert (await orch.autonomy.tick())["failed"] == 1
    new = (await c.request(OWNER))["queued"][0]
    assert new["queue_id"] != old["queue_id"]


@pytest.mark.asyncio
async def test_unavailable_dispatch_lock_refuses_before_queue_intake(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    create(c)
    original = type(c.home).open

    def unavailable(path, *args, **kwargs):
        if path.name.endswith(".dispatch.lock"):
            raise PermissionError("synthetic unavailable lock")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(type(c.home), "open", unavailable)
    answer = await c.request(OWNER)
    assert answer["queued"] == [] and orch.autonomy_queue.list() == []


@pytest.mark.asyncio
async def test_long_worker_emits_heartbeat_for_its_exact_run(tmp_path, monkeypatch):
    from agents.core.kanban.upstream import kanban_db_dispatch as kbd

    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    create(c)
    pulse = asyncio.Event()
    actual = kbd.heartbeat_worker

    def heartbeat(conn, task_id, **kwargs):
        assert kwargs["expected_run_id"] == current_context().run_id
        result = actual(conn, task_id, **kwargs)
        pulse.set()
        return result

    monkeypatch.setattr(kbd, "heartbeat_worker", heartbeat)
    monkeypatch.setattr(c, "_HEARTBEAT_SECONDS", 0.001, raising=False)
    normal = c.runner

    async def delayed(*args, **kwargs):
        await asyncio.wait_for(pulse.wait(), timeout=1)
        return await normal(*args, **kwargs)

    c.runner = delayed
    qid = (await c.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    assert (await orch.autonomy.tick())["done"] == 1
    assert pulse.is_set() and current_context() is None


@pytest.mark.asyncio
async def test_late_provider_error_preserves_completed_board_run(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c)
    normal = c.runner

    async def late_error(*args, **kwargs):
        await normal(*args, **kwargs)
        raise RuntimeError("synthetic response transport error after board completion")

    c.runner = late_error
    qid = (await c.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    assert (await orch.autonomy.tick())["failed"] == 1
    assert read(c, tid).status == "done"


@pytest.mark.asyncio
async def test_timeout_releases_only_own_board_claim(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c, max_runtime_seconds=1)

    async def never_returns(*args, **kwargs):
        await asyncio.Event().wait()

    c.runner = never_returns
    qid = (await c.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    assert (await orch.autonomy.tick())["failed"] == 1
    task = read(c, tid)
    assert task.status != "done" and task.claim_lock is None
    assert task.consecutive_failures == 1


@pytest.mark.asyncio
async def test_cancelled_model_turn_releases_board_scope(tmp_path, monkeypatch):
    c, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c)
    entered = asyncio.Event()

    async def cancelled(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    c.runner = cancelled
    qid = (await c.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    tick = asyncio.create_task(orch.autonomy.tick())
    await asyncio.wait_for(entered.wait(), timeout=1)
    tick.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tick
    assert read(c, tid).claim_lock is None and current_context() is None


@pytest.mark.asyncio
async def test_restart_recovers_pending_capacity_before_proposing_more_work(tmp_path, monkeypatch):
    c, orch, settings, _, _ = fixture_runtime(tmp_path, monkeypatch)
    settings["llm.kanban_max_workers"] = 1
    tid = create(c)
    (await c.request(OWNER))["queued"][0]
    with (
        kanban_scope(KanbanContext(c.home, "dispatcher", can_mutate=True)),
        kb.connect_closing() as conn,
        kb.write_txn(conn),
    ):
        conn.execute(
            "UPDATE nerva_dispatches SET queue_id=NULL, state='prepared' WHERE task_id=?", (tid,)
        )
    create(c, title="higher priority", priority=100, assignee="reviewer")
    restarted = KanbanDispatcher(orch, home=c.home, runner=c.runner)
    answer = await restarted.request(OWNER)
    assert {q["task_id"] for q in answer["queued"]} == {tid}
    assert len(orch.autonomy_queue.list()) == 1


@pytest.mark.asyncio
async def test_host_capacity_includes_pending_work_on_other_boards(tmp_path, monkeypatch):
    c, orch, settings, _, _ = fixture_runtime(tmp_path, monkeypatch)
    settings["llm.kanban_max_workers"] = 1
    create(c)
    await c.request(OWNER)
    with (
        kanban_scope(KanbanContext(c.home, "dispatcher", board="other", can_mutate=True)),
        kb.connect_closing(board="other") as conn,
    ):
        kb.create_task(conn, title="other board work", assignee="reviewer")
    assert (await c.request(OWNER, board="other"))["queued"] == []
    assert len(orch.autonomy_queue.list()) == 1


@pytest.mark.asyncio
async def test_disabling_dispatch_after_approval_cannot_count_as_completion(tmp_path, monkeypatch):
    c, orch, settings, seen, _ = fixture_runtime(tmp_path, monkeypatch)
    tid = create(c)
    qid = (await c.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED, decided_by="owner", decision="approve")
    settings["llm.kanban_dispatch"] = False
    outcome = await orch.autonomy.tick()
    assert outcome["done"] == 0 and outcome["failed"] == 1
    assert seen == [] and read(c, tid).status == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", ["llm.kanban_max_workers", "llm.kanban_max_workers_per_agent"])
async def test_zero_worker_budget_does_not_enqueue(tmp_path, monkeypatch, budget):
    c, orch, settings, _, _ = fixture_runtime(tmp_path, monkeypatch)
    create(c)
    settings[budget] = 0
    assert (await c.request(OWNER))["queued"] == []
    assert orch.autonomy_queue.list() == []
