"""H391: bounded turn compaction decisions, independent of live providers."""

from agents.core.agent import Agent
from agents.core.llm.effective_window import EffectiveWindow
from agents.core.turn_compaction import (
    CompressionAttempts,
    TurnCompaction,
    compaction_scope,
    idle_should_compact,
    material_progress,
    preflight_worth_estimating,
    reanchor_current_user,
    restore_actionable_user,
)


def test_two_huge_rows_trigger_preflight_estimate():
    rows = [{"role": "system", "content": "s"},
            {"role": "user", "content": "x" * 12000}]
    assert preflight_worth_estimating(rows, threshold_tokens=2000,
                                      protect_first=1, protect_last=1)


def test_idle_is_opt_in_and_has_floor_and_cooldown():
    assert not idle_should_compact(enabled=True, after_seconds=0, gap_seconds=300,
                                   tokens=1500, floor_tokens=1000, cooldown=False)
    assert not idle_should_compact(enabled=True, after_seconds=60, gap_seconds=59,
                                   tokens=1500, floor_tokens=1000, cooldown=False)
    assert not idle_should_compact(enabled=True, after_seconds=60, gap_seconds=60,
                                   tokens=1000, floor_tokens=1000, cooldown=False)
    assert not idle_should_compact(enabled=True, after_seconds=60, gap_seconds=60,
                                   tokens=1500, floor_tokens=1000, cooldown=True)
    assert idle_should_compact(enabled=True, after_seconds=60, gap_seconds=60,
                               tokens=1500, floor_tokens=1000, cooldown=False)


def test_material_token_cut_and_removed_row_count_as_progress():
    assert material_progress(10, 9, 1000, 1000)
    assert material_progress(10, 10, 1000, 949)
    assert not material_progress(10, 10, 1000, 950)
    assert not material_progress(10, 10, 1000, 980)


def test_attempts_rearm_only_on_valid_successful_provider_prompt_usage():
    state = CompressionAttempts(max_attempts=2)
    assert state.take()
    assert state.take()
    assert not state.take()
    assert not state.rearm(prompt_tokens=200, threshold_tokens=500,
                           counts_complete=False, provider_succeeded=True)
    assert not state.rearm(prompt_tokens=0, threshold_tokens=500,
                           counts_complete=True, provider_succeeded=True)
    assert not state.rearm(prompt_tokens=200, threshold_tokens=500,
                           counts_complete=True, provider_succeeded=False)
    state.mark_completed()
    assert state.rearm(prompt_tokens=200, threshold_tokens=500,
                       counts_complete=True, provider_succeeded=True)
    assert state.take()


def test_completed_fold_cools_down_until_valid_provider_relief():
    state = CompressionAttempts(max_attempts=3)
    assert state.take()
    state.mark_completed()
    assert not state.take()
    assert not state.rearm(prompt_tokens=200, threshold_tokens=500,
                           counts_complete=False, provider_succeeded=True)
    assert not state.take()
    assert state.rearm(prompt_tokens=200, threshold_tokens=500,
                        counts_complete=True, provider_succeeded=True)
    assert state.take()


def test_blocked_warning_is_visible_once_and_rearms_after_valid_provider_relief():
    from agents.core.llm.tool_protocol import TokenUsage
    from agents.core.turn_notices import open_turn_notices, reset_turn_notices

    notices, token = open_turn_notices()
    try:
        state = TurnCompaction(session_id="s", enabled=True, max_attempts=2,
                               threshold_tokens=3000)
        assert state.attempts.take()
        state.attempts.mark_completed()
        assert state.warn_blocked("no_progress", tokens=5000, threshold=3000)
        assert not state.warn_blocked("no_progress", tokens=5100, threshold=3000)
        assert len(notices) == 1
        assert notices[0]["code"] == "context_overflow_blocked"
        assert "no_progress" in notices[0]["text"]
        state.pressure_below_threshold()
        assert not state.warn_blocked("no_progress", tokens=5000, threshold=3000)
        assert state.observe_usage(TokenUsage(input_tokens=200, prompt_counts_complete=True),
                                   provider_succeeded=True)
        assert state.warn_blocked("no_progress", tokens=5000, threshold=3000)
    finally:
        reset_turn_notices(token)


def test_blocked_warning_without_turn_notice_collector_reaches_status_log(caplog):
    state = TurnCompaction(session_id="s", enabled=True, max_attempts=1)
    assert state.warn_blocked("attempt_limit", tokens=5000, threshold=3000)
    assert not state.warn_blocked("attempt_limit", tokens=5000, threshold=3000)
    assert caplog.text.count("attempt_limit") == 1
    assert "x" * 100 not in caplog.text


def test_current_user_reanchors_after_fold_and_handoff_cannot_drive_model():
    current = {"role": "user", "content": "actual ask", "turn_id": "u-2"}
    rows = [{"role": "system", "content": "s"},
            {"role": "user", "content": "old ask", "turn_id": "u-1"},
            {"role": "user", "content": "[history pointer]", "synthetic_handoff": True},
            dict(current)]
    assert reanchor_current_user(rows, turn_id="u-2") == 3
    rows.pop()
    restored = restore_actionable_user(rows, current)
    assert restored[-1] == current
    assert reanchor_current_user(restored, turn_id="u-2") == 3
    assert restore_actionable_user(rows, None) is None


async def test_idle_force_compacts_below_normal_threshold_to_floor():
    from agents.core.context_compressor import CompactionPolicy, ContextCompressor

    rows = [{"role": "user", "content": f"question {i} " + "x" * 400}
            for i in range(6)]
    compressor = ContextCompressor(max_tokens=2000)
    result = await compressor.compact(rows, model="local",
                                      policy=CompactionPolicy(protect_head=0, protect_last_n=2),
                                      force_target_tokens=300)
    assert result["compressed"] is True
    assert result["evicted"] == 4


def test_rolling_micro_summary_defrag_rebuilds_from_original_covered_turns():
    from agents.core.context_compressor import ContextCompressor

    turns = [{"role": "user", "content": "first ask"},
             {"role": "assistant", "content": "first answer"},
             {"role": "user", "content": "new ask"},
             {"role": "assistant", "content": "new answer"}]
    compressor = ContextCompressor()
    summary = compressor.micro_summary(turns, prior="stale " * 1000,
                                       new_turns=turns[-2:], defrag_threshold_tokens=100)
    assert "stale stale" not in summary
    assert "new ask" in summary
    assert "new answer" in summary


async def test_history_preflight_attempts_even_with_only_two_huge_rows():
    from agents.core.orchestrator import Orchestrator

    class Memory:
        async def get_history(self, sid, last_n=None):
            return [{"role": "assistant", "content": "x" * 12000},
                    {"role": "user", "content": "hi"}]

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.memory = Memory()
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_max_tokens": 2000,
    }.get(key, default)
    state = TurnCompaction(session_id="s", enabled=True, max_attempts=2)
    with compaction_scope(state):
        await orch._history_for_prompt(6)
    assert state.attempts.used == 1
    assert state.threshold_tokens == 2000


async def test_preflight_timeout_refuses_without_clock_commit_or_model_send(monkeypatch):
    import asyncio

    import pytest

    from agents.core.context_compressor import ContextCompressor
    from agents.core.conversation_clock import CompactionClockRefused
    from agents.core.orchestrator import Orchestrator

    cancelled = asyncio.Event()

    async def stalled(self, turns, **kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(ContextCompressor, "compact", stalled)

    class Memory:
        async def get_history(self, sid, last_n=None):
            return [{"role": "assistant", "content": "x" * 12000},
                    {"role": "user", "content": "ask"}]

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.memory = Memory()
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_max_tokens": 2000,
        "memory.compression_preflight_timeout_seconds": 0.01,
    }.get(key, default)
    with compaction_scope(TurnCompaction(session_id="s", enabled=True, max_attempts=2)), pytest.raises(CompactionClockRefused):
        await orch._history_for_prompt(6)
    await asyncio.wait_for(cancelled.wait(), 1)


async def test_history_idle_gate_folds_below_pressure_threshold():
    from datetime import UTC, datetime, timedelta

    from agents.core.orchestrator import Orchestrator

    now = datetime.now(UTC)
    rows = [{"role": "user" if i % 2 == 0 else "assistant",
             "content": f"row {i} " + "x" * 400,
             "timestamp": (now - timedelta(seconds=120)).isoformat()}
            for i in range(7)]
    rows[-1]["role"] = "user"
    rows[-1]["timestamp"] = now.isoformat()

    class Memory:
        async def get_history(self, sid, last_n=None):
            return list(rows)

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.memory = Memory()
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_max_tokens": 1000,
        "memory.compression_idle_after_seconds": 60,
    }.get(key, default)
    state = TurnCompaction(session_id="s", enabled=True, max_attempts=2)
    with compaction_scope(state):
        rendered = await orch._history_for_prompt(6)
    assert "summary of earlier conversation" in rendered
    assert state.attempts.used == 1


async def test_compacted_history_reanchors_and_restores_current_real_user(monkeypatch):
    from agents.core.context_compressor import ContextCompressor
    from agents.core.orchestrator import Orchestrator

    class Memory:
        async def get_history(self, sid, last_n=None):
            return [{"role": "user", "content": "old", "timestamp": "t1"},
                    {"role": "assistant", "content": "answer", "timestamp": "t2"},
                    {"role": "user", "content": "actual current ask", "timestamp": "t3"}]

    async def broken_fold(self, turns, **kwargs):
        return {"compressed": False, "summary": "", "kept_first": [],
                "kept": [{"role": "user", "content": "[pointer]",
                          "synthetic_handoff": True}], "tokens": 10}

    monkeypatch.setattr(ContextCompressor, "compact", broken_fold)
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.memory = Memory()
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_max_tokens": 2000,
    }.get(key, default)
    state = TurnCompaction(session_id="s", enabled=True, max_attempts=2)
    with compaction_scope(state):
        rendered = await orch._history_for_prompt(6)
    assert rendered.endswith("[user]: actual current ask")
    assert state.current_user_index == 1


async def test_plain_request_over_exact_window_refuses_before_physical_send():
    agent = Agent("jarvis", {})
    sent = []

    class Backend:
        async def generate(self, **kwargs):
            sent.append(kwargs)
            return "unexpected"

    state = TurnCompaction(session_id="s", enabled=True, max_attempts=2)
    with compaction_scope(state):
        import pytest

        from agents.core.conversation_clock import CompactionClockRefused

        with pytest.raises(CompactionClockRefused):
            await agent.generate_response(Backend(), "local", "x" * 20000, "system",
                                          512, 0, session_id="s",
                                          effective_window=EffectiveWindow(4096))
    assert sent == []


async def test_unicode_prompt_uses_token_estimate_before_physical_send():
    import pytest

    from agents.core.conversation_clock import CompactionClockRefused

    agent = Agent("jarvis", {})
    sent = []

    class Backend:
        async def generate(self, **kwargs):
            sent.append(kwargs)
            return "unexpected"

    with compaction_scope(TurnCompaction(session_id="s", enabled=True, max_attempts=1)), pytest.raises(CompactionClockRefused):
        await agent.generate_response(Backend(), "local", "𠜎" * 3000, "system",
                                      512, 0, session_id="s",
                                      effective_window=EffectiveWindow(4096))
    assert sent == []


async def test_known_hard_window_disabled_compaction_warns_and_refuses_zero_send():
    import pytest

    from agents.core.conversation_clock import CompactionClockRefused
    from agents.core.turn_notices import open_turn_notices, reset_turn_notices

    agent = Agent("jarvis", {})
    sent = []

    class Backend:
        async def generate(self, **kwargs):
            sent.append(kwargs)
            return "unexpected"

    notices, token = open_turn_notices()
    try:
        with compaction_scope(TurnCompaction(session_id="s", enabled=False, max_attempts=1)), pytest.raises(CompactionClockRefused):
            await agent.generate_response(Backend(), "local", "x" * 20000,
                                          "system", 512, 0, session_id="s",
                                          effective_window=EffectiveWindow(4096))
        assert sent == []
        assert len(notices) == 1
        assert "disabled" in notices[0]["text"]
    finally:
        reset_turn_notices(token)


async def test_plain_provider_usage_rearms_only_after_successful_response():
    from agents.core.llm.tool_protocol import TokenUsage
    from agents.core.llm.usage_context import report_text_usage

    agent = Agent("jarvis", {})
    state = TurnCompaction(session_id="s", enabled=True, max_attempts=1,
                           threshold_tokens=500)
    state.attempts.take()
    state.attempts.mark_completed()

    class Backend:
        async def generate(self, **kwargs):
            report_text_usage(TokenUsage(input_tokens=200, prompt_counts_complete=True))
            return "ok"

    with compaction_scope(state):
        assert await agent.generate_response(Backend(), "local", "hi", "system", 10, 0,
                                             session_id="s") == "ok"
        assert state.attempts.take()


async def test_plain_and_stream_turns_bind_session_scoped_compaction_state():
    from agents.core.orchestrator import Orchestrator
    from agents.core.turn_compaction import active_compaction

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_max_attempts": 3,
    }.get(key, default)
    seen = []

    async def plain(*args):
        seen.append((active_compaction().session_id, active_compaction().max_attempts))
        return "ok"

    async def stream(*args):
        seen.append((active_compaction().session_id, active_compaction().max_attempts))
        return "ok"

    orch._handle_input = plain
    orch._handle_input_stream = stream
    assert await orch.handle_input("hello", session_id="s") == "ok"
    assert await orch.handle_input_stream("hello", session_id="s") == "ok"
    assert seen == [("s", 3), ("s", 3)]
    assert active_compaction() is None


async def test_plain_and_stream_turns_surface_bounded_blocked_notices():
    from agents.core.orchestrator import Orchestrator
    from agents.core.turn_compaction import active_compaction
    from agents.core.turn_notices import open_turn_notices, reset_turn_notices

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "plain"
    orch.get_setting = lambda key, default=None: (
        True if key == "memory.context_compression" else default)

    async def blocked(*args):
        state = active_compaction()
        state.warn_blocked("attempt_limit", tokens=5000, threshold=3000)
        state.warn_blocked("attempt_limit", tokens=5000, threshold=3000)
        return "context_refused"

    orch._handle_input = blocked
    orch._handle_input_stream = blocked
    notices, token = open_turn_notices()
    try:
        assert await orch.handle_input("ask", session_id="plain") == "context_refused"
        assert len(notices) == 1
        assert notices[0]["code"] == "context_overflow_blocked"
    finally:
        reset_turn_notices(token)
    notices, token = open_turn_notices()
    try:
        assert await orch.handle_input_stream("ask", session_id="stream") == "context_refused"
        assert len(notices) == 1
        assert notices[0]["code"] == "context_overflow_blocked"
    finally:
        reset_turn_notices(token)


async def test_next_turn_resets_attempt_budget_but_keeps_warning_per_session():
    from agents.core.orchestrator import Orchestrator
    from agents.core.turn_compaction import active_compaction

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.get_setting = lambda key, default=None: (
        True if key == "memory.context_compression" else default)
    seen = []

    async def turn(*args):
        state = active_compaction()
        seen.append((state.session_id, state.attempts.used, state._warned))
        if state.session_id == "s" and state.attempts.used == 0:
            state.attempts.take()
            state.attempts.mark_completed()
            state._warned = True
        return "ok"

    orch._handle_input = turn
    await orch.handle_input("one", session_id="s")
    await orch.handle_input("two", session_id="s")
    await orch.handle_input("other", session_id="other")
    assert seen == [("s", 0, False), ("s", 0, True), ("other", 0, False)]


def test_model_window_or_instance_change_resets_session_pressure_only():
    state = TurnCompaction(session_id="s", enabled=True, max_attempts=2)
    state.bind_route("instance-1", "model-a", 4096, 2000)
    state.attempts.take()
    state._warned = True
    state.bind_route("instance-1", "model-a", 4096, 2000)
    assert state.attempts.used == 1 and state._warned
    state.bind_route("instance-1", "model-b", 4096, 2000)
    assert state.attempts.used == 0 and not state._warned
    state.attempts.take()
    state.bind_route("instance-2", "model-b", 4096, 2000)
    assert state.attempts.used == 0


def test_real_tool_provider_usage_rearms_pending_fold_but_partial_does_not():
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.tool_protocol import TokenUsage, ToolTurn

    state = TurnCompaction(session_id="s", enabled=True, max_attempts=1)
    state.threshold_tokens = 500
    assert state.attempts.take()
    state.attempts.mark_completed()
    with compaction_scope(state):
        AgentToolRuntime._report_usage(None, ToolTurn(usage=TokenUsage(
            input_tokens=200, prompt_counts_complete=False)))
        assert not state.attempts.take()
        AgentToolRuntime._report_usage(None, ToolTurn(content="ok", usage=TokenUsage(
            input_tokens=200, prompt_counts_complete=True)))
        assert state.attempts.take()
