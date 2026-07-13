"""H32.1 — durable, explicit, encrypted capability-request plane."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from agents.core.acquisition.models import RequestStatus
from agents.core.acquisition.runtime import AcquisitionRuntime
from agents.core.acquisition.store import CapabilityRequestStore, CapabilityStoreError
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.observability import capability_registry
from agents.core.tool_rpc import ToolRPCServer


def test_explicit_miss_is_redacted_encrypted_deduped_and_restart_safe(tmp_path):
    root = tmp_path / "runtime" / "acquisition"
    store = CapabilityRequestStore(root=root, clock=lambda: 100.0)
    goal = "Build a weather adapter password=hunter22 for alice@example.com"

    first = store.capture(goal, agent_id="jarvis", reason="no_registered_capability")
    second = store.capture(goal, agent_id="jarvis", reason="no_registered_capability")

    assert first.request_id == second.request_id
    assert second.occurrences == 2
    assert "hunter22" not in second.goal
    assert "alice@example.com" not in second.goal
    assert second.fingerprint and len(second.fingerprint) == 64
    disk = (root / "requests.enc").read_bytes()
    assert b"hunter22" not in disk and b"weather adapter" not in disk

    restarted = CapabilityRequestStore(root=root, clock=lambda: 101.0)
    loaded = restarted.get(first.request_id)
    assert loaded is not None
    assert loaded.goal == second.goal
    assert loaded.occurrences == 2


@pytest.mark.parametrize("reason", ["unanswered_chat", "model_uncertain", "", "unknown"])
def test_non_capability_failures_do_not_create_requests(tmp_path, reason):
    store = CapabilityRequestStore(root=tmp_path)
    with pytest.raises(ValueError, match="explicit capability miss"):
        store.capture("just answer normally", agent_id="jarvis", reason=reason)
    assert store.list() == []


def test_master_flag_is_default_off_and_does_not_create_runtime_files(tmp_path):
    root = tmp_path / "acquisition"
    runtime = AcquisitionRuntime(root=root)
    assert runtime.capture_gap(
        {
            "goal": "need a new tool",
            "agent_id": "jarvis",
            "reason": "no_registered_capability",
        }
    ) is None
    assert runtime.request_store is None
    assert not root.exists()


def test_goal_and_identity_are_bounded(tmp_path):
    store = CapabilityRequestStore(root=tmp_path)
    with pytest.raises(ValueError, match="goal"):
        store.capture("", agent_id="jarvis", reason="tool_not_allowed")
    with pytest.raises(ValueError, match="goal"):
        store.capture("x" * 4097, agent_id="jarvis", reason="tool_not_allowed")
    with pytest.raises(ValueError, match="agent"):
        store.capture("need a bounded tool", agent_id="x" * 129, reason="tool_not_allowed")


def test_lifecycle_is_append_only_and_invalid_transitions_fail(tmp_path):
    store = CapabilityRequestStore(root=tmp_path, clock=lambda: 10.0)
    request = store.capture("need a csv normalizer", agent_id="jarvis", reason="tool_not_allowed")
    researching = store.transition(request.request_id, RequestStatus.RESEARCHING, actor="resolver")
    assert researching.status is RequestStatus.RESEARCHING
    assert [event.status for event in researching.history] == [
        RequestStatus.MISSING,
        RequestStatus.RESEARCHING,
    ]
    with pytest.raises(ValueError, match="transition"):
        store.transition(request.request_id, RequestStatus.INSTALLED, actor="resolver")


def test_concurrent_duplicate_capture_is_single_record(tmp_path):
    store = CapabilityRequestStore(root=tmp_path)

    def capture(_index):
        return store.capture(
            "need a deterministic json flattener",
            agent_id="jarvis",
            reason="no_registered_capability",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(capture, range(32)))
    assert len({row.request_id for row in rows}) == 1
    assert store.list()[0].occurrences == 32


def test_corruption_fails_closed_and_capacity_never_evicts_open_work(tmp_path):
    store = CapabilityRequestStore(root=tmp_path, max_requests=1)
    store.capture("need capability one", agent_id="jarvis", reason="tool_not_allowed")
    with pytest.raises(CapabilityStoreError, match="capacity"):
        store.capture("need capability two", agent_id="jarvis", reason="tool_not_allowed")

    (tmp_path / "requests.enc").write_bytes(b"not-ciphertext")
    with pytest.raises(CapabilityStoreError, match="decrypt"):
        CapabilityRequestStore(root=tmp_path).list()


def test_retention_purges_goal_but_keeps_hash_only_tombstone(tmp_path):
    now = 31 * 86_400.0
    store = CapabilityRequestStore(root=tmp_path, clock=lambda: 0.0, retention_days=30)
    request = store.capture("need an old adapter", agent_id="jarvis", reason="tool_not_allowed")
    store.transition(request.request_id, RequestStatus.ABANDONED, actor="owner")

    result = store.purge(now=now)
    assert result == {"purged": 1, "tombstones": 1}
    assert store.list() == []
    tombstone = json.loads((tmp_path / "tombstones.jsonl").read_text(encoding="utf-8"))
    assert tombstone["request_hash"]
    assert "adapter" not in json.dumps(tombstone)


@pytest.mark.asyncio
async def test_agent_runtime_emits_gap_only_after_registry_refusal():
    events: list[dict] = []
    runtime = AgentToolRuntime(
        ToolRPCServer(),
        enabled=lambda: True,
        registry_enabled=lambda: True,
        capability_snapshot=lambda: {"capabilities": []},
        gap_callback=events.append,
    )
    backend = SimpleNamespace(supports_tools=True)

    reply = await runtime.run(
        agent_id="jarvis",
        backend=backend,
        model="local",
        prompt="Use a tool to normalize this CSV",
    )

    assert "no live registered capability" in reply
    assert events == [
        {
            "agent_id": "jarvis",
            "goal": "Use a tool to normalize this CSV",
            "reason": "no_registered_capability",
        }
    ]

    await runtime.run(
        agent_id="jarvis",
        backend=backend,
        model="local",
        prompt="Tell me a short joke",
    )
    assert len(events) == 1


def test_missing_requests_project_as_registry_state_without_promotion(tmp_path):
    store = CapabilityRequestStore(root=tmp_path)
    request = store.capture("need a csv normalizer", agent_id="jarvis", reason="tool_not_allowed")
    orch = SimpleNamespace(
        acquisition=SimpleNamespace(request_store=store),
        components=SimpleNamespace(status={}),
        tool_rpc=SimpleNamespace(tools=lambda: []),
        skills=SimpleNamespace(skills={}),
        autonomy_queue=None,
    )

    records = {record.id: record for record in capability_registry.build_records(orch)}
    record = records[f"missing:{request.fingerprint[:24]}"]
    assert record.state == capability_registry.MISSING
    assert record.confidence == 0.0
    assert record.detail["request_id"] == request.request_id
    assert request.goal not in json.dumps(record.detail)
