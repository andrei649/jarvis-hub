"""H28.4 — governed, default-off desktop host execution route."""

import pytest
from fastapi.testclient import TestClient

from agents.core.desktop_host import WindowsDesktopDriver
from agents.core.kernel import Decision, Verdict
from agents.core.routers import multimodal


class _Driver:
    requires_kernel = True

    def __init__(self, result=None):
        self.calls = []
        self.result = {"ok": True, "source": "accessibility", "elements": []}
        if result is not None:
            self.result = result

    async def perform(self, action, args):
        self.calls.append((action, args))
        return self.result


@pytest.fixture
def client():
    from agents import web

    with TestClient(web.app) as test_client:
        yield test_client


def _enable_host(monkeypatch):
    monkeypatch.setenv("JARVIS_DESKTOP_HOST", "1")
    monkeypatch.setenv("JARVIS_DESKTOP_ISOLATED", "1")


def _wire_driver(monkeypatch, driver, *, verdict=Verdict.GRANT, reason="allowed"):
    orch = object()
    seen = []

    monkeypatch.setattr(
        WindowsDesktopDriver,
        "from_env",
        classmethod(lambda cls: driver),
    )

    def bind(live_orch):
        seen.append(live_orch)

        def authorize(_action, capability=None):
            return Decision(verdict, reason=reason, tier=2)

        return authorize

    monkeypatch.setattr("agents.core.kernel.binding.make_action_kernel", bind)
    monkeypatch.setattr(multimodal, "get_orch", lambda: orch)
    return orch, seen


def test_desktop_run_is_user_guarded_and_default_off(client, monkeypatch):
    monkeypatch.delenv("JARVIS_DESKTOP_HOST", raising=False)
    monkeypatch.delenv("JARVIS_DESKTOP_ISOLATED", raising=False)
    built = []
    monkeypatch.setattr(
        multimodal,
        "build_desktop_runtime",
        lambda _orch: built.append(True),
        raising=False,
    )

    response = client.post("/api/desktop/run", json={"steps": []})

    assert response.status_code == 200
    assert response.json() == {"ok": False, "reason": "desktop_host_disabled"}
    assert built == []

    from tests.test_route_auth_matrix import _runtime_guards

    assert _runtime_guards()["POST /api/desktop/run"] == "user"


def test_desktop_run_uses_live_orchestrator_kernel_binding(client, monkeypatch):
    _enable_host(monkeypatch)
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    driver = _Driver()
    orch, seen = _wire_driver(monkeypatch, driver)

    payload = client.post(
        "/api/desktop/run",
        json={"steps": [{"action": "observe", "args": {}}]},
    ).json()

    assert seen == [orch]
    assert driver.calls == [("observe", {})]
    assert payload == {
        "ok": True,
        "ran": [
            {
                "action": "observe",
                "status": "ran",
                "result": {"ok": True, "source": "accessibility", "elements": []},
            }
        ],
    }


@pytest.mark.parametrize(
    ("unified", "kernel", "reason"),
    [
        (False, True, "unified_action_api_disabled"),
        (True, False, "action_kernel_disabled"),
    ],
)
def test_desktop_run_reports_disabled_facade_without_host_execution(
    client,
    monkeypatch,
    unified,
    kernel,
    reason,
):
    _enable_host(monkeypatch)
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1" if unified else "0")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1" if kernel else "0")
    driver = _Driver()
    _wire_driver(monkeypatch, driver)

    payload = client.post(
        "/api/desktop/run",
        json={"steps": [{"action": "observe", "args": {}}]},
    ).json()

    assert payload["ok"] is False
    assert payload["ran"] == [
        {"action": "observe", "status": "blocked", "reason": reason}
    ]
    assert driver.calls == []


def test_desktop_run_preserves_queued_kernel_outcome(client, monkeypatch):
    _enable_host(monkeypatch)
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    driver = _Driver()
    _wire_driver(
        monkeypatch,
        driver,
        verdict=Verdict.QUEUE,
        reason="approval_required",
    )

    payload = client.post(
        "/api/desktop/run",
        json={"steps": [{"action": "observe", "args": {}}]},
    ).json()

    assert payload["ok"] is False
    assert payload["ran"] == [
        {"action": "observe", "status": "queued", "reason": "approval_required"}
    ]
    assert driver.calls == []


def test_desktop_run_never_reports_nested_driver_refusal_as_success(client, monkeypatch):
    _enable_host(monkeypatch)
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    driver = _Driver({"ok": False, "reason": "not_found"})
    _wire_driver(monkeypatch, driver)

    payload = client.post(
        "/api/desktop/run",
        json={"steps": [{"action": "observe", "args": {}}]},
    ).json()

    assert payload["ok"] is False
    assert payload["ran"] == [
        {"action": "observe", "status": "failed", "reason": "not_found"}
    ]


def test_desktop_run_rejects_non_string_action_without_500(client, monkeypatch):
    _enable_host(monkeypatch)
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    driver = _Driver()
    _wire_driver(monkeypatch, driver)

    response = client.post(
        "/api/desktop/run",
        json={"steps": [{"action": 1, "args": {}}]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "ran": [{"action": 1, "status": "failed", "reason": "invalid_action"}],
    }
    assert driver.calls == []
