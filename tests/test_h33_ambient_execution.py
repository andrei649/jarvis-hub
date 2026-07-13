from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.ambient.contracts import MonitorDefinition, MonitorPredicate
from agents.core.ambient.execution import (
    AmbientTaskExecutor,
    SilentActionBinding,
    register_ambient_handlers,
    register_ambient_refusal_handlers,
)
from agents.core.ambient.registry import MonitorRegistry
from agents.core.ambient.store import AmbientStore
from agents.core.autonomy.executor import TaskExecutor


def _definition(version=1):
    return MonitorDefinition(
        monitor_id="monitor.safe.light",
        version=version,
        source="house",
        schema="house.event.v1",
        predicates=(MonitorPredicate("attributes.current_state", "eq", "on"),),
        alert_rung="act_silently",
    )


def _task(definition, **payload_overrides):
    payload = {
        "ambient_generation": 3,
        "consent_generation": 2,
        "event_fingerprint": "e" * 64,
        "monitor_hash": definition.definition_hash,
        "monitor_id": definition.monitor_id,
        "monitor_version": definition.version,
        "rung": "act_silently",
        "source": "house",
    }
    payload.update(payload_overrides)
    return SimpleNamespace(id=7, kind="ambient.action", payload=payload)


def _executor(tmp_path, *, enabled=lambda: True, generation=lambda: 3, action_api=None, rollback=None):
    store = AmbientStore(tmp_path / "ambient.db")
    registry = MonitorRegistry(store, enabled=True)
    definition = _definition()
    registry.create(definition, actor="owner")

    async def default_action(_binding, _task):
        return {"status": "ok", "verified": True}

    async def default_rollback(_binding, _task, _result):
        return {"status": "restored", "verified": True}

    executor = AmbientTaskExecutor(
        enabled_provider=enabled,
        generation_provider=generation,
        registry=registry,
        ownership_provider=lambda source: source == "house",
        kill_switch=lambda: False,
        binding_resolver=lambda monitor_id: SilentActionBinding(
            monitor_id=monitor_id,
            capability_id="house.light.set",
            rollbackable=True,
            postcondition_bound=True,
        ),
        action_api=action_api or default_action,
        rollback=rollback or default_rollback,
    )
    return executor, definition, store


@pytest.mark.parametrize(
    ("enabled", "generation", "overrides", "reason"),
    [
        (lambda: False, lambda: 3, {}, "ambient_disabled"),
        (lambda: True, lambda: 4, {}, "ambient_generation_revoked"),
        (lambda: True, lambda: 3, {"monitor_hash": "f" * 64}, "monitor_version_revoked"),
        (lambda: True, lambda: 3, {"source": "camera"}, "source_ownership_revoked"),
    ],
)
def test_executor_revalidates_every_immutable_ambient_binding(
    tmp_path, enabled, generation, overrides, reason
):
    called = []

    async def action_api(_binding, _task):
        called.append(True)
        return {"status": "ok", "verified": True}

    executor, definition, store = _executor(
        tmp_path, enabled=enabled, generation=generation, action_api=action_api
    )
    result = asyncio.run(executor.execute(_task(definition, **overrides)))

    assert result == {"status": "revoked", "reason": reason}
    assert called == []
    store.close()


def test_executor_rechecks_immediately_before_action_api(tmp_path):
    checks = []

    def enabled():
        checks.append(True)
        return len(checks) < 2

    executor, definition, store = _executor(tmp_path, enabled=enabled)
    result = asyncio.run(executor.execute(_task(definition)))

    assert result == {"status": "revoked", "reason": "ambient_disabled"}
    assert len(checks) == 2
    store.close()


def test_verified_silent_action_uses_registered_task_executor_handler(tmp_path):
    calls = []

    async def action_api(binding, task):
        calls.append((binding.capability_id, task.id))
        return {"status": "ok", "verified": True, "result": "changed"}

    ambient, definition, store = _executor(tmp_path, action_api=action_api)
    registry = TaskExecutor()
    register_ambient_handlers(registry, ambient)
    result = asyncio.run(registry.execute(_task(definition)))

    assert result["verified"] is True
    assert calls == [("house.light.set", 7)]
    store.close()


def test_partial_failure_compensates_even_when_ambient_becomes_disabled(tmp_path):
    state = {"enabled": True}
    rollbacks = []

    async def action_api(_binding, _task):
        state["enabled"] = False
        return {"status": "failed", "verified": False, "partial": True}

    async def rollback(binding, task, result):
        rollbacks.append((binding.capability_id, task.id, result["partial"]))
        return {"status": "restored", "verified": True}

    executor, definition, store = _executor(
        tmp_path,
        enabled=lambda: state["enabled"],
        action_api=action_api,
        rollback=rollback,
    )
    result = asyncio.run(executor.execute(_task(definition)))

    assert result == {
        "status": "failed",
        "reason": "postcondition_failed",
        "compensation": "verified",
    }
    assert rollbacks == [("house.light.set", 7, True)]
    store.close()


def test_failed_compensation_requires_manual_recovery(tmp_path):
    async def action_api(_binding, _task):
        return {"status": "failed", "verified": False}

    async def rollback(_binding, _task, _result):
        return {"status": "failed", "verified": False}

    executor, definition, store = _executor(
        tmp_path, action_api=action_api, rollback=rollback
    )

    assert asyncio.run(executor.execute(_task(definition))) == {
        "status": "failed",
        "reason": "postcondition_failed",
        "compensation": "manual_recovery_required",
    }
    store.close()


def test_unbound_production_ambient_tasks_never_fall_through_to_llm():
    fallback_calls = []

    async def fallback(task):
        fallback_calls.append(task.kind)
        return {"status": "ok"}

    registry = register_ambient_refusal_handlers(TaskExecutor(fallback=fallback))

    assert asyncio.run(
        registry.execute(SimpleNamespace(id=1, kind="ambient.action"))
    ) == {"status": "revoked", "reason": "silent_binding_unavailable"}
    assert asyncio.run(
        registry.execute(SimpleNamespace(id=2, kind="ambient.decision"))
    ) == {"status": "noop", "reason": "ambient_decision_acknowledged"}
    assert fallback_calls == []
