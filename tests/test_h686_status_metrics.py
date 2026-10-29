"""Frozen H686 status metrics from one accepted, physical request."""

import httpx
import pytest

from agents.core.llm.tool_protocol import TokenUsage
from agents.core.turn_usage import (
    model_usage_scope,
    record_dispatch,
    record_usage,
    turn_usage_scope,
)


def _request(model="actual"):
    return httpx.Request("POST", "https://example.test/v1/chat/completions", json={"model": model})


def test_complete_single_request_uses_disjoint_prompt_and_physical_interval(monkeypatch):
    from agents.core import turn_usage

    ticks = iter((10.0, 12.0))
    monkeypatch.setattr(turn_usage.time, "monotonic", lambda: next(ticks))
    with turn_usage_scope() as collector:
        with model_usage_scope(model="actual", route="cloud", context_window=1000):
            record_dispatch("test-provider", _request())
            record_usage(TokenUsage(input_tokens=100, cache_read=300, cache_write=100,
                                    output_tokens=80, counts_complete=True,
                                    prompt_counts_complete=True))
        status = collector.status_snapshot()
        accounting = collector.snapshot()
    assert status == {"model": "actual", "context_detail": {"prompt_tokens": 500, "window_tokens": 1000},
                      "context_pct": 50, "tps": 40.0}
    assert accounting["input_tokens"] == 500  # H220 keeps its aggregate accounting.


def test_missing_prompt_certification_or_window_hides_context_but_not_exact_tps(monkeypatch):
    from agents.core import turn_usage

    ticks = iter((1.0, 2.0))
    monkeypatch.setattr(turn_usage.time, "monotonic", lambda: next(ticks))
    with turn_usage_scope() as collector:
        with model_usage_scope(model="actual", route="cloud"):
            record_dispatch("test-provider", _request())
            record_usage(TokenUsage(input_tokens=100, output_tokens=20, counts_complete=True))
        assert collector.status_snapshot() == {"model": "actual", "tps": 20.0}


def test_multiple_requests_do_not_select_latest_primary_request(monkeypatch):
    from agents.core import turn_usage

    ticks = iter((1.0, 2.0, 3.0, 4.0))
    monkeypatch.setattr(turn_usage.time, "monotonic", lambda: next(ticks))
    with turn_usage_scope() as collector:
        with model_usage_scope(model="actual", route="cloud", context_window=1000):
            for _ in range(2):
                record_dispatch("test-provider", _request())
                record_usage(TokenUsage(input_tokens=100, output_tokens=20, counts_complete=True,
                                        prompt_counts_complete=True))
        assert collector.status_snapshot() == {}


def test_outcome_duration_settles_before_cleanup_and_prompt_elapsed_needs_visible_chunk(monkeypatch):
    from agents.core import turn_outcome

    ticks = iter((1.025, 1.050, 1.100))
    monkeypatch.setattr(turn_outcome.time, "perf_counter", lambda: next(ticks))
    collector, token = turn_outcome.open_turn_outcome()
    try:
        assert collector.claim()
        collector.begin(1.0)
        assert collector.visible_output("hello")
        assert collector.settle("answered")
        assert collector.publish(100)
        final = collector.close()
        assert final["latency_ms"] == 100
        assert final["duration_ms"] == 50
        assert final["prompt_elapsed_ms"] == 25
    finally:
        turn_outcome.reset_turn_outcome(token)


def test_selection_keeps_h396_diagnostics_when_latency_is_unselected():
    from agents import web

    class FakeOrch:
        def get_setting(self, *_args):
            return ["model", "duration", "total_tokens", "cache_hit"]

    measured = {"latency_ms": 100, "duration_ms": 80, "model": "actual",
                "completion": {"kind": "answered"}, "cache_hit": 60.0}
    usage = {"usage_basis": "provider_complete", "input_tokens": 100,
             "output_tokens": 20}
    assert web._selected_turn_outcome(FakeOrch(), measured, usage=usage) == {
        "model": "actual", "duration_ms": 80, "total_tokens": 120,
        "cache_hit": 60.0, "completion": {"kind": "answered"},
    }


def test_broken_optional_status_preference_retains_core_outcome_without_detail(caplog):
    from agents import web

    class BrokenOrch:
        def get_setting(self, *_args):
            raise RuntimeError('private status setting')

    measured = {'completion': {'kind': 'answered'}, 'tools': {'called': 1},
                'output': {'visible': True}, 'file_mutations': 1,
                'file_mutation_attribution': 'confirmed', 'latency_ms': 20}
    assert web._selected_turn_outcome(BrokenOrch(), measured) == {
        key: measured[key] for key in ('completion', 'tools', 'output',
                                      'file_mutations', 'file_mutation_attribution')}
    assert 'optional turn status selection unavailable' in caplog.text
    assert 'private status setting' not in caplog.text


def test_cache_epoch_is_scoped_and_zero_reads_hide():
    from agents.core.status_cache_epoch import CacheEpochs

    epochs = CacheEpochs(max_scopes=2)
    left = ("owner", "session-a", "instance-a", "jarvis", "local", "ollama", "model-a")
    right = ("owner", "session-b", "instance-b", "jarvis", "local", "ollama", "model-a")
    assert epochs.observe(left, 100, 0, 0) is None
    assert epochs.observe(left, 100, 300, 100) == 50.0
    assert epochs.observe(right, 100, 300, 100) == 60.0
    assert epochs.value(left) == 50.0
    epochs.invalidate_conversation(("owner", "session-a", "instance-a"))
    assert epochs.value(left) is None
    assert epochs.value(right) == 60.0
    assert epochs.observe(left, 100, 300, 100) == 60.0
    epochs.contaminate(left)
    assert epochs.value(left) is None
    epochs.invalidate_selection()
    assert epochs.value(left) is None
    assert epochs.value(right) is None


def test_physical_model_transition_clears_prior_prefix_for_same_agent():
    from agents.core.status_cache_epoch import CacheEpochs

    epochs = CacheEpochs()
    first = ("owner", "session", "instance", "jarvis", "cloud", "provider", "first")
    other = first[:-1] + ("other",)
    assert epochs.observe(first, 100, 300, 100) == 60.0
    assert epochs.observe(other, 100, 0, 0) is None
    assert epochs.value(first) is None
    assert epochs.observe(first, 100, 100, 0) == 50.0


def test_unknown_model_poison_survives_until_conversation_invalidation():
    from agents.core.status_cache_epoch import CacheEpochs

    epochs = CacheEpochs()
    conversation = ("owner", "session", "instance")
    key = conversation + ("jarvis", "cloud", "provider", "model")
    epochs.contaminate_conversation(conversation)
    assert epochs.observe(key, 100, 300, 100) is None
    epochs.invalidate_conversation(conversation)
    assert epochs.observe(key, 100, 300, 100) == 60.0


def test_bounded_cache_eviction_fails_closed_until_selection_invalidation():
    from agents.core.status_cache_epoch import CacheEpochs

    epochs = CacheEpochs(max_scopes=1)
    first = ("owner", "session-a", "instance-a", "jarvis", "cloud", "provider", "model")
    second = ("owner", "session-b", "instance-b", "jarvis", "cloud", "provider", "model")
    assert epochs.observe(first, 100, 300, 100) == 60.0
    assert epochs.observe(second, 100, 300, 100) is None
    assert epochs.observe(first, 100, 300, 100) is None
    epochs.invalidate_selection()
    assert epochs.observe(first, 100, 300, 100) == 60.0


def test_accepted_compaction_invalidates_same_instance_across_principals_only():
    from agents.core.status_cache_epoch import CacheEpochs

    epochs = CacheEpochs()
    owner = ("owner", "session", "instance", "jarvis", "cloud", "provider", "model")
    user = ("user", "session", "instance", "jarvis", "cloud", "provider", "model")
    other = ("owner", "session", "new-instance", "jarvis", "cloud", "provider", "model")
    for key in (owner, user, other):
        epochs.observe(key, 100, 300, 100)
    epochs.invalidate_instance("session", "instance")
    assert epochs.value(owner) is None and epochs.value(user) is None
    assert epochs.value(other) == 60.0


def test_cache_epoch_isolates_principal_conversation_and_agent():
    from agents.core.status_cache_epoch import CacheEpochs

    epochs = CacheEpochs()
    base = ("owner", "session-a", "instance-a", "jarvis", "cloud", "provider", "model")
    other_principal = ("user",) + base[1:]
    other_chat = (base[0], "session-b", "instance-b") + base[3:]
    other_agent = base[:3] + ("frigga",) + base[4:]
    for key, read in ((base, 300), (other_principal, 100),
                      (other_chat, 200), (other_agent, 400)):
        epochs.observe(key, 100, read, 0)
    assert epochs.value(base) == 75.0
    assert epochs.value(other_principal) == 50.0
    assert epochs.value(other_chat) == 100 * 200 / 300
    assert epochs.value(other_agent) == 80.0
    epochs.contaminate(base)
    assert epochs.value(base) is None
    assert epochs.value(other_principal) == 50.0
    assert epochs.value(other_chat) == 100 * 200 / 300
    assert epochs.value(other_agent) == 80.0


def test_accepted_compaction_counts_once_and_late_count_is_inert():
    from agents.core.turn_outcome import TurnOutcomeCollector

    sink = TurnOutcomeCollector()
    assert sink.accepted_compression() is True
    assert sink.accepted_compression() is True
    assert sink.claim() and sink.publish(50)
    assert sink.close()["compressions"] == 2
    assert sink.accepted_compression() is False
    assert sink.close()["compressions"] == 2


def test_accepted_compaction_invalidates_current_and_cross_principal_instance():
    from agents.core.status_cache_epoch import EPOCHS
    from agents.core.turn_outcome import (
        open_turn_outcome,
        record_accepted_compression,
        reset_turn_outcome,
    )

    EPOCHS.invalidate_selection()
    owner = ("owner", "session", "instance", "jarvis", "cloud", "provider", "model")
    user = ("user", "session", "instance", "jarvis", "cloud", "provider", "model")
    unrelated = ("owner", "other", "instance", "jarvis", "cloud", "provider", "model")
    for key in (owner, user, unrelated):
        EPOCHS.observe(key, 100, 300, 100)
    sink, token = open_turn_outcome()
    try:
        with turn_usage_scope() as collector:
            assert collector.bind_status_scope(("owner", "session", "instance"))
            assert record_accepted_compression("session", "instance") is True
            assert sink.claim() and sink.publish(10)
            assert sink.close()["compressions"] == 1
        assert EPOCHS.value(owner) is None and EPOCHS.value(user) is None
        assert EPOCHS.value(unrelated) == 60.0
    finally:
        reset_turn_outcome(token)
        EPOCHS.invalidate_selection()


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_main_compaction_hook_counts_only_accepted_clock_commit(tmp_path, monkeypatch, accepted):
    from agents.core.context_compressor import ContextCompressor
    from agents.core.conversation_clock import CompactionClockRefused
    from agents.core.orchestrator import Orchestrator
    from agents.core.status_cache_epoch import EPOCHS
    from agents.core.turn_outcome import open_turn_outcome, reset_turn_outcome
    from tests.test_compaction_clock import history_stub, store

    manager = store(tmp_path)
    clock = manager.clock_snapshot("a")
    key = ("owner", "a", clock.instance_id, "jarvis", "cloud", "provider", "model")
    EPOCHS.invalidate_selection()
    EPOCHS.observe(key, 100, 300, 100)
    if not accepted:
        monkeypatch.setattr(manager, "commit_clock", lambda *_args, **_kwargs: None)

    async def compact(*_args, **_kwargs):
        return {"compressed": True, "summary": "digest", "covered": 1,
                "kept": [], "kept_first": []}

    monkeypatch.setattr(ContextCompressor, "compact", compact)
    sink, token = open_turn_outcome()
    try:
        with turn_usage_scope() as collector:
            assert collector.bind_status_scope(("owner", "a", clock.instance_id))
            if accepted:
                await Orchestrator._history_for_prompt(history_stub(manager), 10)
            else:
                with pytest.raises(CompactionClockRefused):
                    await Orchestrator._history_for_prompt(history_stub(manager), 10)
            assert sink.progress() == ({"compressions": 1} if accepted else None)
            assert EPOCHS.value(key) == (None if accepted else 60.0)
    finally:
        reset_turn_outcome(token)
        EPOCHS.invalidate_selection()


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_tool_loop_commit_counts_and_resets_only_after_publication(tmp_path, monkeypatch, accepted):
    from agents.core import agent_runtime
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.conversation_clock import clock_scope, render_snapshot
    from agents.core.status_cache_epoch import EPOCHS
    from agents.core.turn_outcome import open_turn_outcome, reset_turn_outcome
    from tests.test_compaction_clock import store

    manager = store(tmp_path)
    clock = manager.clock_snapshot("a")
    key = ("owner", "a", clock.instance_id, "jarvis", "cloud", "provider", "model")
    EPOCHS.invalidate_selection()
    assert EPOCHS.observe(key, 100, 300, 100) == 60.0
    runtime = AgentToolRuntime(object(), enabled=lambda: True)
    monkeypatch.setattr(runtime, "_context_budget", lambda *_args: 100)
    monkeypatch.setattr(agent_runtime, "estimate_messages", lambda rows:
                        101 if len(rows[-1]["content"]) > 1000 else 90)
    if not accepted:
        monkeypatch.setattr(manager, "commit_clock", lambda *_args, **_kwargs: None)
    rows = [{"role": "system", "content": render_snapshot("soul", clock)},
            {"role": "tool", "content": "x" * 5000}]
    sink, token = open_turn_outcome()
    try:
        with turn_usage_scope() as usage, clock_scope(manager, clock):
            assert usage.bind_status_scope(("owner", "a", clock.instance_id))
            result = await runtime._compact_context(rows, set(), model="m", max_tokens=10,
                                                    agent_id="jarvis", event_sink=None)
            assert result is accepted
            assert sink.progress() == ({"compressions": 1} if accepted else None)
            assert EPOCHS.value(key) == (None if accepted else 60.0)
    finally:
        reset_turn_outcome(token)
        EPOCHS.invalidate_selection()
        manager.close()
        manager.close()


@pytest.mark.asyncio
async def test_micro_view_hook_counts_only_durable_publication(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agents.core.checkpoint import CheckpointManager
    from agents.core.memory import persistence
    from agents.core.orchestrator import Orchestrator
    from agents.core.status_cache_epoch import EPOCHS
    from agents.core.turn_outcome import open_turn_outcome, reset_turn_outcome
    from tests.test_h391_micro_lifecycle import _receipt, _turns

    monkeypatch.setattr(persistence, "_memory_dir", lambda: tmp_path / "memory")
    manager = CheckpointManager(str(tmp_path / "clock.db"))
    manager.initialize()
    manager.create_session_record("s")
    clock = manager.clock_snapshot("s")
    rows = _turns(2)
    persistence.save_memory("s", rows, instance_id=clock.instance_id,
                            revision=4, checkpoint_mgr=manager)
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.checkpoints = manager
    orch.memory = SimpleNamespace(conversation=SimpleNamespace(persist=True))
    orch.get_setting = lambda key, default=None: {
        "memory.context_compression": True,
        "memory.compression_micro_compact": True,
    }.get(key, default)
    key = ("owner", "s", clock.instance_id, "jarvis", "cloud", "provider", "model")
    EPOCHS.invalidate_selection()
    EPOCHS.observe(key, 100, 300, 100)
    sink, token = open_turn_outcome()
    try:
        with turn_usage_scope() as collector:
            assert collector.bind_status_scope(("owner", "s", clock.instance_id))
            receipt = _receipt(rows, clock, 4)
            assert await orch._maybe_micro_compact("answer 1", append_receipt=receipt)
            assert sink.progress() == {"compressions": 1}
            assert EPOCHS.value(key) is None
            assert not await orch._maybe_micro_compact("answer 1", append_receipt=receipt)
            assert sink.progress() == {"compressions": 1}
    finally:
        reset_turn_outcome(token)
        EPOCHS.invalidate_selection()
        manager.close()


def test_cache_epoch_follows_two_turns_of_one_authenticated_instance(monkeypatch):
    from agents.core import turn_usage
    from agents.core.status_cache_epoch import EPOCHS

    EPOCHS.invalidate_selection()
    ticks = iter((1.0, 2.0, 3.0, 4.0))
    monkeypatch.setattr(turn_usage.time, "monotonic", lambda: next(ticks))
    scope = ("web:owner", "session-a", "instance-a")
    for index, expected in enumerate((60.0, 50.0)):
        with turn_usage_scope() as collector:
            assert collector.bind_status_scope(scope)
            with model_usage_scope(model="actual", route="cloud", agent_id="jarvis"):
                record_dispatch("test-provider", _request())
                record_usage(TokenUsage(input_tokens=100, cache_read=300 if index == 0 else 0,
                                        cache_write=100 if index == 0 else 0,
                                        output_tokens=20, counts_complete=True,
                                        prompt_counts_complete=True))
            assert collector.status_snapshot()["cache_hit"] == expected
    EPOCHS.invalidate_selection()


def test_deferred_or_failed_model_setting_apply_preserves_cache_epoch(tmp_path, monkeypatch):
    from agents.core import settings_db
    from agents.core.status_cache_epoch import EPOCHS

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    EPOCHS.invalidate_selection()
    key = ("owner", "session", "instance", "jarvis", "cloud", "provider", "model")
    assert EPOCHS.observe(key, 100, 300, 100) == 60.0
    original = settings_db.get_value("llm", "default_model")
    settings_db.put_category("llm", {"default_model": original})
    settings_db.put_category("display", {"status_bar_fields": ["latency", "cache_hit"]})
    assert EPOCHS.value(key) == 60.0
    settings_db.put_category("llm", {"default_model": "synthetic-model"})
    assert EPOCHS.value(key) == 60.0
    def failed_apply(_category, _values):
        raise RuntimeError("synthetic listener failure")
    monkeypatch.setattr(settings_db, "_change_listeners", [failed_apply])
    settings_db.put_category("llm", {"default_model": "another-model"})
    assert EPOCHS.value(key) == 60.0
    # A trusted physical identity transition is the verified reset boundary.
    EPOCHS.observe(("owner", "session", "instance", "jarvis", "cloud", "provider", "new-model"),
                   100, 0, 0)
    assert EPOCHS.value(key) is None


def test_signed_selection_resets_cache_only_when_effective_route_changes(tmp_path, monkeypatch):
    from dataclasses import replace

    from agents.core import settings_db
    from agents.core.llm import provider_selection
    from agents.core.status_cache_epoch import EPOCHS
    from tests.test_h361_provider_selection_fence import _binding

    store = tmp_path / "settings.db"
    monkeypatch.setattr(settings_db, "DB_PATH", store)
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    key = ("owner", "session", "instance", "jarvis", "cloud", "provider", "model")
    first = provider_selection.compare_and_swap(store, _binding(store), expected_revision=2)
    assert EPOCHS.observe(key, 100, 300, 100) == 60.0
    rotated = replace(first.binding, credential_generation=2)
    second = provider_selection.compare_and_swap(store, rotated, expected_revision=first.revision)
    assert EPOCHS.value(key) == 60.0
    changed = replace(second.binding, model="other-model")
    provider_selection.compare_and_swap(store, changed, expected_revision=second.revision)
    assert EPOCHS.value(key) is None


def test_custom_choice_reset_ignores_same_effective_endpoint(tmp_path, monkeypatch):
    from agents.core import settings_db
    from agents.core.llm import custom_endpoints
    from agents.core.status_cache_epoch import EPOCHS

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    endpoint = custom_endpoints.create_endpoint("one", "One", "http://127.0.0.1:1234/v1",
                                                "model", "none", "local")
    first = custom_endpoints.activate_endpoint(endpoint.key, expected_revision=endpoint.revision,
                                               expected_choice_epoch=custom_endpoints.read_choice().epoch,
                                               proof="0" * 64)
    key = ("owner", "session", "instance", "jarvis", "local", "custom:one", "model")
    assert EPOCHS.observe(key, 100, 300, 100) == 60.0
    second = custom_endpoints.activate_endpoint(endpoint.key, expected_revision=endpoint.revision,
                                                expected_choice_epoch=first.epoch, proof="1" * 64)
    assert EPOCHS.value(key) == 60.0
    custom_endpoints.clear_endpoint_choice(expected_choice_epoch=second.epoch)
    assert EPOCHS.value(key) is None


def test_authoritative_request_window_refuses_guess_and_mismatch():
    from types import SimpleNamespace

    from agents.core.llm.effective_window import authoritative_context_window

    actual = SimpleNamespace(context_window=lambda model: 4096 if model == "actual" else None)
    assert authoritative_context_window(actual, "actual", resolved=4096) == 4096
    assert authoritative_context_window(actual, "actual", resolved=8192) is None
    assert authoritative_context_window(actual, "unknown", resolved=8192) is None
    assert authoritative_context_window(SimpleNamespace(), "actual", resolved=4096) is None
    huge = SimpleNamespace(context_window=lambda _model: 1_000_000_000_001)
    assert authoritative_context_window(huge, "actual") is None


def test_nonfinite_request_rate_hides_tps(monkeypatch):
    from agents.core import turn_usage

    ticks = iter((1.0, 1.0 + 1e-12))
    monkeypatch.setattr(turn_usage.time, "monotonic", lambda: next(ticks))
    with turn_usage_scope() as collector:
        with model_usage_scope(model="actual", route="cloud"):
            record_dispatch("test-provider", _request())
            record_usage(TokenUsage(input_tokens=1, output_tokens=999_999_999_999,
                                    counts_complete=True))
        assert collector.status_snapshot() == {"model": "actual"}


def test_replayed_usage_does_not_double_count_cache_and_unknown_poison_hides(monkeypatch):
    from agents.core import turn_usage
    from agents.core.status_cache_epoch import EPOCHS

    EPOCHS.invalidate_selection()
    ticks = iter((1.0, 2.0, 3.0, 4.0))
    monkeypatch.setattr(turn_usage.time, "monotonic", lambda: next(ticks))
    scope = ("owner", "session", "instance")
    with turn_usage_scope() as collector:
        assert collector.bind_status_scope(scope)
        with model_usage_scope(model="actual", route="cloud", agent_id="jarvis"):
            record_dispatch("test-provider", _request())
            usage = TokenUsage(input_tokens=100, cache_read=300, cache_write=100,
                               output_tokens=20, counts_complete=True,
                               prompt_counts_complete=True)
            record_usage(usage)
            record_usage(usage)
        assert collector.status_snapshot()["cache_hit"] == 60.0
    with turn_usage_scope() as collector:
        assert collector.bind_status_scope(scope)
        with model_usage_scope(model="actual", route="cloud", agent_id="jarvis"):
            record_dispatch("test-provider", _request())
            record_usage(TokenUsage(input_tokens=100, output_tokens=20, counts_complete=True,
                                    prompt_counts_complete=False))
        assert "cache_hit" not in collector.status_snapshot()
    EPOCHS.invalidate_selection()


def test_http_and_stream_progress_project_same_selected_physical_metrics(monkeypatch):
    import json
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import turn_usage
    from agents.core.turn_outcome import record_turn_latency
    from tests.test_turn_status_readout import _orch

    fake = _orch(monkeypatch, fields=("model", "context_detail", "context_pct", "tps"))
    ticks = iter((1.0, 3.0, 5.0, 7.0))
    monkeypatch.setattr(turn_usage, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    async def work(*_args, on_token=None, **_kwargs):
        with model_usage_scope(model="actual", route="cloud", context_window=1000):
            record_dispatch("test-provider", _request())
            record_usage(TokenUsage(input_tokens=100, cache_read=300, cache_write=100,
                                    output_tokens=80, counts_complete=True,
                                    prompt_counts_complete=True))
        if on_token is not None:
            await on_token("answer")
        record_turn_latency(137)
        return "answer"

    fake.handle_input = work
    fake.handle_input_stream = work
    monkeypatch.setattr(web, "orch", fake)
    client = TestClient(web.app)
    direct = client.post("/chat", json={"message": "hello"}).json()["outcome"]
    events = [json.loads(part[6:]) for part in client.post(
        "/chat/stream", json={"message": "hello"}).text.split("\n\n") if part.startswith("data: ")]
    progress = next(event["outcome"] for event in events if event["type"] == "outcome_progress"
                    and event["outcome"] and "model" in event["outcome"])
    final = events[-1]["outcome"]
    expected = {"model": "actual", "context_detail": {"prompt_tokens": 500, "window_tokens": 1000},
                "context_pct": 50.0, "tps": 40.0}
    for outcome in (direct, progress, final):
        assert {key: outcome[key] for key in expected} == expected
        assert "latency_ms" not in outcome


def test_unapplied_local_adoption_write_does_not_reset_cache(tmp_path, monkeypatch):
    from agents.core import settings_db
    from agents.core.status_cache_epoch import EPOCHS

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    key = ("owner", "session", "instance", "jarvis", "local", "ollama", "model")
    EPOCHS.invalidate_selection()
    EPOCHS.observe(key, 100, 300, 100)
    with settings_db.defer_model_epoch_invalidation():
        settings_db.put_category("llm", {"default_model": "synthetic-pending"})
    assert EPOCHS.value(key) == 60.0


@pytest.mark.asyncio
@pytest.mark.parametrize("adopted", [False, True])
async def test_local_provider_switch_resets_only_after_live_adoption(monkeypatch, adopted):
    from types import SimpleNamespace

    from agents.core.routers import models_llm
    from agents.core.status_cache_epoch import EPOCHS

    key = ("owner", "session", "instance", "jarvis", "local", "ollama", "old")
    EPOCHS.invalidate_selection()
    EPOCHS.observe(key, 100, 300, 100)

    async def catalog():
        return {"models": [{"id": "new", "provider": "lm-studio", "available": True}]}

    async def adopt(*_args, **_kwargs):
        return {"adopted": adopted, "rollback_complete": True}

    monkeypatch.setattr(models_llm, "_web", lambda: SimpleNamespace(_list_local_models=catalog))
    monkeypatch.setattr(models_llm, "_local_provider_name", lambda _router: "ollama")
    monkeypatch.setattr(models_llm, "_adopt_local_provider", adopt)
    response = await models_llm._switch_local_model_locked(SimpleNamespace(active_model="old"),
                                                            "new", provider="lm-studio")
    assert response.status_code == (200 if adopted else 409)
    assert EPOCHS.value(key) == (None if adopted else 60.0)
    EPOCHS.invalidate_selection()


@pytest.mark.asyncio
async def test_public_latency_includes_cleanup_after_accepted_duration(monkeypatch):
    from agents.core import turn_outcome

    ticks = iter((1.0, 1.1, 1.2))
    monkeypatch.setattr(turn_outcome.time, "perf_counter", lambda: next(ticks))
    sink, token = turn_outcome.open_turn_outcome()
    try:
        @turn_outcome.measure_turn_latency
        async def work():
            assert turn_outcome.record_turn_completion("answered")
            return "done"  # wrapper observes final cleanup after settlement

        assert await work() == "done"
        result = sink.close()
        assert result["duration_ms"] == 100
        assert result["latency_ms"] == 200
    finally:
        turn_outcome.reset_turn_outcome(token)


def test_all_twenty_selections_self_hide_without_unrelated_sources():
    from types import SimpleNamespace

    from agents import web
    from agents.core.settings_db import _STATUS_FIELDS

    class FakeOrch:
        checkpoints = SimpleNamespace(session_title=lambda session: {
            "title": "Current session" if session == "current" else "Other session"})

        def get_setting(self, key, _default=None):
            return list(_STATUS_FIELDS) if key == "display.status_bar_fields" else True

    result = web._selected_turn_outcome(FakeOrch(), {"latency_ms": 25},
                                        usage={"usage_basis": "unknown"}, session_id="current")
    assert result == {"latency_ms": 25, "title": "Current session", "battery": True}
    assert len(_STATUS_FIELDS) == 20 and "total_tokens" in _STATUS_FIELDS
