"""The Kanban dispatcher runs a claimed turn under its own identities."""

import asyncio
from contextlib import contextmanager

import pytest

from agents.core.action_origin import bind_action_origin, current_action_origin, reset_action_origin
from agents.core.autonomy_coordinator import _APPROVED_TASK
from agents.core.commands import Principal
from agents.core.kanban.context import KanbanContext, current_context, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.llm.job_selection import (
    SelectionError,
    _selection,
    apply_selection,
    current_selection,
)
from agents.core.llm.request_context import (
    RequestOverrides,
    _reasoning,
    current_overrides,
    current_session,
    reasoning_scope,
    request_overrides_scope,
    selected_reasoning,
    session_scope,
)
from agents.core.orchestrator import (
    Orchestrator,
    _active_session,
    _session_is_shared,
    bind_turn_principal,
    current_principal,
    reset_turn_principal,
)
from agents.core.turn_approvals import _turn_approvals


def runner():
    from agents.core.kanban.worker_runner import WorkerTurnRefused, run_worker_turn

    return run_worker_turn, WorkerTurnRefused


def claimed_scope(
    tmp_path, *, profile="builder", session_id="worker-session", board="default", **task_options
):
    with (
        kanban_scope(KanbanContext(tmp_path, profile, board=board, can_mutate=True)),
        kb.connect_closing(board=board) as conn,
    ):
        task_id = kb.create_task(conn, title="synthetic turn", assignee=profile, **task_options)
        claimed = kb.claim_task(conn, task_id)
    assert claimed is not None
    return KanbanContext(
        tmp_path,
        profile,
        board=board,
        task_id=task_id,
        run_id=claimed.current_run_id,
        session_id=session_id,
        can_mutate=True,
    )


def real_orchestrator(reply="worker answer"):
    orch = Orchestrator.__new__(Orchestrator)
    orch.agents = {"builder": object(), "jarvis": object()}
    orch._session_id_default = "owner-session"
    seen = []

    async def call_agents(agent_ids, prompt, *_):
        seen.append(
            (
                agent_ids,
                prompt,
                orch.session_id,
                orch.on_shared_session(),
                current_session(),
                current_principal(),
                current_action_origin(),
                current_context(),
                current_selection(),
                current_overrides(),
                _APPROVED_TASK.get(),
                _turn_approvals.get(),
            )
        )
        return {agent_ids[0]: reply}

    orch._call_agents_parallel = call_agents
    return orch, seen


@contextmanager
def parent_tokens():
    principal = Principal(channel="web", sender="owner", admin=True)
    principal_token = bind_turn_principal(principal)
    origin_token = bind_action_origin("inbound")
    session_token = _active_session.set("parent-session")
    shared_token = _session_is_shared.set(True)
    approved = object()
    approval_token = _APPROVED_TASK.set(approved)
    approval_sink = [91]
    approvals_token = _turn_approvals.set(approval_sink)
    selection = object()
    selection_token = _selection.set(selection)
    overrides = RequestOverrides(max_tokens=7)
    try:
        with (
            session_scope("provider-parent"),
            request_overrides_scope(overrides),
            reasoning_scope("high"),
        ):
            yield principal, approved, approval_sink, selection, overrides
            assert current_principal() is principal
            assert current_action_origin() == "inbound"
            assert _active_session.get() == "parent-session"
            assert _session_is_shared.get() is True
            assert current_session() == "provider-parent"
            assert _APPROVED_TASK.get() is approved
            assert _turn_approvals.get() is approval_sink
            assert _selection.get() is selection
            assert current_overrides() is overrides
            assert selected_reasoning("medium") == "high"
    finally:
        _selection.reset(selection_token)
        _turn_approvals.reset(approvals_token)
        _APPROVED_TASK.reset(approval_token)
        _session_is_shared.reset(shared_token)
        _active_session.reset(session_token)
        reset_action_origin(origin_token)
        reset_turn_principal(principal_token)


@pytest.mark.asyncio
async def test_worker_binds_real_orchestrator_identity_and_restores_parent(tmp_path, monkeypatch):
    run, _ = runner()
    monkeypatch.setattr("agents.core.power.hold_for_turn", lambda orch: False)
    context = claimed_scope(tmp_path)
    orch, seen = real_orchestrator()
    with kanban_scope(context), parent_tokens() as parent:
        assert (
            await run(
                orch, prompt="do synthetic work", agent_id="builder", session_id="worker-session"
            )
            == "worker answer"
        )
        assert orch.session_id == "parent-session"
        assert current_context() is context
    assert len(seen) == 1
    (
        agents,
        prompt,
        sid,
        shared,
        provider_sid,
        principal,
        origin,
        observed,
        selection,
        overrides,
        approved,
        sink,
    ) = seen[0]
    assert (agents, prompt, sid, shared, provider_sid) == (
        ["builder"],
        "do synthetic work",
        "worker-session",
        False,
        "worker-session",
    )
    assert principal == Principal(channel="internal")
    assert origin == "generated"
    assert observed is context
    assert selection is None and overrides is None and approved is None and sink is None
    assert parent[0].admin is True


@pytest.mark.asyncio
async def test_two_overlapping_worker_sessions_keep_their_identities(tmp_path, monkeypatch):
    run, _ = runner()
    monkeypatch.setattr("agents.core.power.hold_for_turn", lambda orch: False)
    first = claimed_scope(tmp_path, session_id="worker-one")
    second = claimed_scope(tmp_path, session_id="worker-two")
    orch, _ = real_orchestrator()
    arrived = asyncio.Event()
    release = asyncio.Event()
    seen = []

    async def process(prompt, agent_ids, *_):
        seen.append((prompt, orch.session_id, current_session(), current_context().task_id))
        if prompt == "first":
            arrived.set()
            await release.wait()
            seen.append(
                ("first-after-wait", orch.session_id, current_session(), current_context().task_id)
            )
        return {agent_ids[0]: prompt}

    # Keep Orchestrator.process_detailed and its real session properties in use.
    async def call_agents(agent_ids, prompt, *_):
        return await process(prompt, agent_ids)

    orch._call_agents_parallel = call_agents
    with kanban_scope(first):
        pending = asyncio.create_task(
            run(orch, prompt="first", agent_id="builder", session_id="worker-one")
        )
        await arrived.wait()
        with kanban_scope(second):
            assert (
                await run(orch, prompt="second", agent_id="builder", session_id="worker-two")
                == "second"
            )
        release.set()
        assert await pending == "first"
    assert seen == [
        ("first", "worker-one", "worker-one", first.task_id),
        ("second", "worker-two", "worker-two", second.task_id),
        ("first-after-wait", "worker-one", "worker-one", first.task_id),
    ]


@pytest.mark.asyncio
async def test_unknown_agent_and_wrong_scope_refused_without_model_call(tmp_path):
    run, refused = runner()
    context = claimed_scope(tmp_path)
    orch, seen = real_orchestrator()
    with kanban_scope(context):
        with pytest.raises(refused):
            await run(orch, prompt="test", agent_id="missing", session_id=context.session_id)
        with pytest.raises(refused):
            await run(orch, prompt="test", agent_id="builder", session_id="other-session")
    with pytest.raises(refused):
        await run(orch, prompt="test", agent_id="builder", session_id=context.session_id)
    assert seen == []


@pytest.mark.asyncio
async def test_closed_and_successor_run_refused(tmp_path):
    run, refused = runner()
    context = claimed_scope(tmp_path)
    orch, seen = real_orchestrator()
    with kanban_scope(context), kb.connect_closing() as conn:
        assert kb.complete_task(
            conn, context.task_id, summary="done", expected_run_id=context.run_id
        )
    with kanban_scope(context), pytest.raises(refused):
        await run(orch, prompt="test", agent_id="builder", session_id=context.session_id)
    assert seen == []

    successor = claimed_scope(tmp_path, session_id="successor-session")
    with kanban_scope(successor), kb.connect_closing() as conn:
        conn.execute(
            "UPDATE tasks SET current_run_id = ? WHERE id = ?",
            (successor.run_id + 1, successor.task_id),
        )
        conn.commit()
    with kanban_scope(successor), pytest.raises(refused):
        await run(orch, prompt="test", agent_id="builder", session_id=successor.session_id)
    assert seen == []


@pytest.mark.asyncio
async def test_ownership_rechecked_after_session_lease_wait(tmp_path, monkeypatch):
    run, refused = runner()
    context = claimed_scope(tmp_path)
    orch, seen = real_orchestrator()
    held = asyncio.Event()
    release = asyncio.Event()
    checked = asyncio.Event()
    from agents.core.kanban import worker_runner

    original_check = worker_runner._check_ownership

    def signal_first_check(scope):
        original_check(scope)
        checked.set()

    monkeypatch.setattr(worker_runner, "_check_ownership", signal_first_check)

    async def hold_lease():
        async with orch.turn_lease(context.session_id) as acquired:
            assert acquired
            held.set()
            await release.wait()

    blocker = asyncio.create_task(hold_lease())
    await held.wait()
    with kanban_scope(context):
        pending = asyncio.create_task(
            run(orch, prompt="test", agent_id="builder", session_id=context.session_id)
        )
        await checked.wait()
        with kb.connect_closing() as conn:
            conn.execute(
                "UPDATE tasks SET current_run_id = ? WHERE id = ?",
                (context.run_id + 1, context.task_id),
            )
            conn.commit()
        release.set()
        await blocker
        with pytest.raises(refused):
            await pending
    assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        "",
        "[builder error: unavailable]",
        "No language model is loaded yet. Start LM Studio (or Ollama) and load a model, then try again — or enable DEMO mode in the HUD to preview the interface.",
    ],
)
async def test_empty_error_and_degraded_reply_refused_with_restoration(
    tmp_path, monkeypatch, reply
):
    run, refused = runner()
    monkeypatch.setattr("agents.core.power.hold_for_turn", lambda orch: False)
    context = claimed_scope(tmp_path)
    orch, seen = real_orchestrator(reply)
    with kanban_scope(context), parent_tokens(), pytest.raises(refused):
        await run(orch, prompt="test", agent_id="builder", session_id=context.session_id)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_cancelled_worker_restores_parent_and_releases_lease(tmp_path, monkeypatch):
    run, _ = runner()
    monkeypatch.setattr("agents.core.power.hold_for_turn", lambda orch: False)
    context = claimed_scope(tmp_path)
    orch, _ = real_orchestrator()

    async def wait_forever(agent_ids, prompt, *_):
        asyncio.current_task().cancel()
        await asyncio.sleep(0)

    orch._call_agents_parallel = wait_forever
    with kanban_scope(context), parent_tokens():
        with pytest.raises(asyncio.CancelledError):
            await run(orch, prompt="test", agent_id="builder", session_id=context.session_id)
        assert not orch._turn_leases[context.session_id].locked()


@pytest.mark.asyncio
async def test_task_owned_model_provider_and_reasoning_reach_real_process_scope(
    tmp_path, monkeypatch
):
    run, _ = runner()
    monkeypatch.setattr("agents.core.power.hold_for_turn", lambda orch: False)
    context = claimed_scope(
        tmp_path,
        model_override="local-model",
        provider_override="lm-studio",
        reasoning_effort="low",
    )
    orch, _ = real_orchestrator()
    observed = []

    class LocalBackend:
        def context_window(self, model):
            return 8192

    class GovernedLocalRouter:
        _backend_name = "lm-studio"
        _local_available = True
        _ollama_backend = None

        def __init__(self):
            self._backend = LocalBackend()
            self._local_model = "local-model"

        def select_backend(self, agent_id, prompt):
            observed.append(
                (
                    "preflight",
                    agent_id,
                    prompt,
                    current_selection().model,
                    current_selection().provider,
                    selected_reasoning("medium"),
                )
            )
            return apply_selection(self, agent_id, self._backend, self._local_model, "local")

    orch.llm_router = GovernedLocalRouter()

    async def call_agents(agent_ids, prompt, *_):
        observed.append(
            (
                "process",
                agent_ids[0],
                prompt,
                current_selection().model,
                current_selection().provider,
                selected_reasoning("medium"),
            )
        )
        return {agent_ids[0]: "pinned answer"}

    orch._call_agents_parallel = call_agents
    with kanban_scope(context), parent_tokens():
        assert (
            await run(orch, prompt="pinned work", agent_id="builder", session_id=context.session_id)
            == "pinned answer"
        )
    assert observed == [
        ("preflight", "builder", "pinned work", "local-model", "lm-studio", "low"),
        ("process", "builder", "pinned work", "local-model", "lm-studio", "low"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("router_kind", ["missing", "wrong"])
async def test_pinned_task_refuses_missing_or_wrong_governed_router_before_process(
    tmp_path,
    router_kind,
):
    run, refused = runner()
    context = claimed_scope(tmp_path, model_override="local-model", provider_override="lm-studio")
    orch, seen = real_orchestrator()
    if router_kind == "wrong":

        class WrongRouter:
            def select_backend(self, agent_id, prompt):
                raise SelectionError("requested provider is unavailable")

        orch.llm_router = WrongRouter()
    with kanban_scope(context), parent_tokens(), pytest.raises(refused):
        await run(orch, prompt="pinned work", agent_id="builder", session_id=context.session_id)
    assert seen == []


@pytest.mark.asyncio
async def test_task_owned_pins_do_not_leak_into_next_unpinned_turn(tmp_path, monkeypatch):
    run, _ = runner()
    monkeypatch.setattr("agents.core.power.hold_for_turn", lambda orch: False)
    pinned = claimed_scope(
        tmp_path, session_id="pinned-session", model_override="local-model", reasoning_effort="none"
    )
    ordinary = claimed_scope(tmp_path, session_id="ordinary-session")
    orch, _ = real_orchestrator()
    observed = []

    class LocalBackend:
        def context_window(self, model):
            return 8192

    class GovernedLocalRouter:
        _backend_name = "lm-studio"
        _local_available = True
        _ollama_backend = None

        def __init__(self):
            self._backend = LocalBackend()
            self._local_model = "local-model"

        def select_backend(self, agent_id, prompt):
            return apply_selection(self, agent_id, self._backend, self._local_model, "local")

    orch.llm_router = GovernedLocalRouter()

    async def call_agents(agent_ids, prompt, *_):
        selection = current_selection()
        observed.append(
            (
                prompt,
                selection.model if selection else None,
                selected_reasoning("medium"),
                _reasoning.get() is None,
            )
        )
        return {agent_ids[0]: "answer"}

    orch._call_agents_parallel = call_agents
    with parent_tokens():
        with kanban_scope(pinned):
            assert (
                await run(orch, prompt="pinned", agent_id="builder", session_id=pinned.session_id)
                == "answer"
            )
        with kanban_scope(ordinary):
            assert (
                await run(
                    orch, prompt="ordinary", agent_id="builder", session_id=ordinary.session_id
                )
                == "answer"
            )
    assert observed == [
        ("pinned", "local-model", "none", False),
        ("ordinary", None, "medium", True),
    ]
