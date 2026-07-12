"""H28.4 — optional accessibility-first Windows desktop host driver."""

from __future__ import annotations

import base64
import threading

import pytest

import agents.core.desktop_host as desktop_host
from agents.core.desktop_host import DesktopHostDisabled, WindowsDesktopDriver


class FakeBackend:
    def __init__(self, elements=None, *, error: Exception | None = None):
        self.elements = list(elements or [])
        self.error = error
        self.snapshot_calls = 0
        self.mutations = []
        self.closed = False

    async def accessibility_elements(self):
        self.snapshot_calls += 1
        if self.error is not None:
            raise self.error
        return self.elements

    async def click(self, element):
        self.mutations.append(("click", element))

    async def type(self, element, text):
        self.mutations.append(("type", element, text))

    async def close(self):
        self.closed = True


class LocalLocator:
    is_local = True

    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"label": "Save", "x": 12, "y": 24}

    async def __call__(self, *, query, screenshot):
        self.calls.append({"query": query, "screenshot": screenshot})
        return self.result


@pytest.fixture
def backend():
    return FakeBackend(
        [
            {"name": "Save", "role": "Button", "text": "Save file", "enabled": True},
            {"name": "Title", "role": "Edit", "value": "Draft"},
        ]
    )


@pytest.fixture
def local_vlm():
    return LocalLocator()


@pytest.fixture
def driver(backend, local_vlm):
    return WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: backend,
        screenshotter=lambda: b"png-bytes",
        local_vlm_locator=local_vlm,
        app_launchers={"browser": ("browser.exe", "--private")},
    )


def test_from_env_requires_host_and_isolated_flags(monkeypatch):
    monkeypatch.delenv("JARVIS_DESKTOP_HOST", raising=False)
    monkeypatch.delenv("JARVIS_DESKTOP_ISOLATED", raising=False)
    with pytest.raises(DesktopHostDisabled):
        WindowsDesktopDriver.from_env()

    monkeypatch.setenv("JARVIS_DESKTOP_HOST", "1")
    with pytest.raises(DesktopHostDisabled):
        WindowsDesktopDriver.from_env()

    monkeypatch.setenv("JARVIS_DESKTOP_ISOLATED", "1")
    enabled = WindowsDesktopDriver.from_env(backend_factory=lambda: FakeBackend())
    assert enabled.host_enabled is True
    assert enabled.isolated is True
    assert enabled.requires_kernel is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host_enabled", "0"),
        ("host_enabled", "false"),
        ("host_enabled", 0),
        ("host_enabled", 1),
        ("isolated", "0"),
        ("isolated", "false"),
        ("isolated", 0),
        ("isolated", 1),
    ],
)
def test_direct_constructor_requires_literal_boolean_gates(field, value):
    kwargs = {"host_enabled": True, "isolated": True}
    kwargs[field] = value

    with pytest.raises(TypeError, match=field):
        WindowsDesktopDriver(**kwargs)


@pytest.mark.asyncio
async def test_direct_driver_still_refuses_actuation_without_both_gates():
    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=False,
        backend_factory=lambda: FakeBackend(),
    )
    with pytest.raises(DesktopHostDisabled):
        await driver.perform("observe", {})


@pytest.mark.asyncio
async def test_locate_uses_accessibility_before_local_vlm(driver, local_vlm):
    result = await driver.perform("locate", {"query": "Save"})

    assert result["ok"] is True
    assert result["source"] == "accessibility"
    assert result["element"]["name"] == "Save"
    assert local_vlm.calls == []


@pytest.mark.asyncio
async def test_locate_uses_proven_local_vlm_only_after_accessibility_miss(local_vlm):
    backend = FakeBackend([{"name": "Cancel", "role": "Button"}])
    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: backend,
        screenshotter=lambda: b"screen",
        local_vlm_locator=local_vlm,
    )

    result = await driver.perform("locate", {"query": "Save"})

    assert backend.snapshot_calls == 1
    assert local_vlm.calls == [{"query": "Save", "screenshot": b"screen"}]
    assert result == {
        "ok": True,
        "source": "local_vlm",
        "provenance": "local",
        "element": {"label": "Save", "x": 12, "y": 24},
    }


@pytest.mark.asyncio
async def test_unmarked_vlm_is_rejected_without_calling_it():
    calls = []

    async def unmarked_locator(**kwargs):
        calls.append(kwargs)

    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: FakeBackend(),
        screenshotter=lambda: b"screen",
        local_vlm_locator=unmarked_locator,
    )

    result = await driver.perform("locate", {"query": "Save"})

    assert result == {"ok": False, "reason": "local_vlm_not_proven_local"}
    assert calls == []


@pytest.mark.asyncio
async def test_local_vlm_result_drops_unbounded_and_non_finite_numbers():
    locator = LocalLocator(
        {
            "x": 42,
            "confidence": 0.75,
            "huge": 10**1_000,
            "nan": float("nan"),
            "positive_inf": float("inf"),
            "negative_inf": float("-inf"),
        }
    )
    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: FakeBackend(),
        screenshotter=lambda: b"screen",
        local_vlm_locator=locator,
    )

    result = await driver.perform("locate", {"query": "Save"})

    assert result["element"] == {"x": 42, "confidence": 0.75}


@pytest.mark.asyncio
async def test_local_vlm_result_that_normalizes_empty_fails_closed():
    locator = LocalLocator({"nested": {"x": 12}})
    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: FakeBackend(),
        screenshotter=lambda: b"screen",
        local_vlm_locator=locator,
    )

    result = await driver.perform("locate", {"query": "Save"})

    assert result == {"ok": False, "reason": "local_vlm_result_invalid"}


@pytest.mark.asyncio
async def test_observe_normalizes_and_caps_accessibility_elements():
    backend = FakeBackend(
        [
            {"name": "abcdefgh", "role": "button", "text": "123456", "secret": "drop"},
            {"name": "second", "role": "text"},
            {"name": "third", "role": "text"},
        ]
    )
    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: backend,
        max_elements=2,
        max_text_chars=5,
    )

    result = await driver.perform("observe", {})

    assert result["ok"] is True
    assert result["source"] == "accessibility"
    assert result["truncated"] is True
    assert result["elements"] == [
        {"id": "element-0", "name": "abcde", "role": "butto", "text": "12345"},
        {"id": "element-1", "name": "secon", "role": "text"},
    ]


@pytest.mark.asyncio
async def test_read_returns_bounded_accessible_text(driver):
    result = await driver.perform("read", {"query": "Title"})

    assert result == {
        "ok": True,
        "source": "accessibility",
        "text": "Draft",
        "element": {
            "id": "element-1",
            "name": "Title",
            "role": "Edit",
            "value": "Draft",
        },
    }


@pytest.mark.asyncio
async def test_click_and_type_require_named_accessibility_elements(backend, driver):
    coordinate_only = await driver.perform("click", {"x": 10, "y": 20})
    missing = await driver.perform("click", {"name": "Not there"})
    clicked = await driver.perform("click", {"name": "Save"})
    typed = await driver.perform("type", {"name": "Title", "text": "Ready"})

    assert coordinate_only == {"ok": False, "reason": "named_element_required"}
    assert missing == {"ok": False, "reason": "element_not_found"}
    assert clicked == {"ok": True, "action": "click", "element": "Save"}
    assert typed == {"ok": True, "action": "type", "element": "Title"}
    assert backend.mutations == [
        ("click", backend.elements[0]),
        ("type", backend.elements[1], "Ready"),
    ]


@pytest.mark.asyncio
async def test_mutation_rejects_oversized_name_instead_of_actuating_truncated_prefix():
    backend = FakeBackend(
        [
            {"name": "abcde-first", "role": "Button"},
            {"name": "abcde-second", "role": "Button"},
        ]
    )
    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: backend,
        max_text_chars=5,
    )

    prefix_result = await driver.perform("click", {"name": "abcde"})
    oversized_result = await driver.perform("click", {"name": "abcde-second"})

    assert prefix_result == {"ok": False, "reason": "element_not_found"}
    assert oversized_result == {"ok": False, "reason": "element_name_too_large"}
    assert backend.mutations == []


@pytest.mark.asyncio
async def test_type_requires_bounded_text(driver):
    assert await driver.perform("type", {"name": "Title"}) == {
        "ok": False,
        "reason": "text_required",
    }
    assert await driver.perform("type", {"name": "Title", "text": "x" * 21_000}) == {
        "ok": False,
        "reason": "text_too_large",
    }


@pytest.mark.asyncio
async def test_screenshot_caps_bytes_before_base64_encoding(monkeypatch):
    encoded = []

    def forbidden_encode(value):
        encoded.append(value)
        raise AssertionError("oversized bytes must not be encoded")

    monkeypatch.setattr(desktop_host.base64, "b64encode", forbidden_encode)
    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: FakeBackend(),
        screenshotter=lambda: b"12345",
        max_screenshot_bytes=4,
    )

    result = await driver.perform("screenshot", {})

    assert result == {"ok": False, "reason": "screenshot_too_large"}
    assert encoded == []


@pytest.mark.asyncio
async def test_screenshot_returns_bounded_base64_without_starting_accessibility_backend():
    factories = []

    def backend_factory():
        factories.append(True)
        return FakeBackend()

    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=backend_factory,
        screenshotter=lambda: b"png",
    )

    result = await driver.perform("screenshot", {})

    assert result == {
        "ok": True,
        "source": "screenshot",
        "mime": "image/png",
        "bytes": 3,
        "image_base64": base64.b64encode(b"png").decode("ascii"),
    }
    assert factories == []


@pytest.mark.asyncio
async def test_synchronous_host_operations_run_off_the_event_loop(monkeypatch):
    event_loop_thread = threading.get_ident()
    call_threads = []

    class SyncBackend:
        def accessibility_elements(self):
            call_threads.append(("accessibility", threading.get_ident()))
            yield {"name": "Save", "role": "Button"}

        def click(self, element):
            call_threads.append(("click", threading.get_ident()))

        def type(self, element, text):
            call_threads.append(("type", threading.get_ident()))

    backend = SyncBackend()

    def backend_factory():
        call_threads.append(("factory", threading.get_ident()))
        return backend

    def screenshotter():
        call_threads.append(("screenshot", threading.get_ident()))
        return b"png"

    def popen(argv, **kwargs):
        call_threads.append(("popen", threading.get_ident()))
        return object()

    monkeypatch.setattr(desktop_host.subprocess, "Popen", popen)
    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=backend_factory,
        screenshotter=screenshotter,
        app_launchers={"browser": ("browser.exe",)},
    )

    await driver.perform("observe", {})
    await driver.perform("click", {"name": "Save"})
    await driver.perform("type", {"name": "Save", "text": "Ready"})
    await driver.perform("screenshot", {})
    await driver.perform("launch", {"app": "browser"})

    assert {name for name, _thread in call_threads} == {
        "factory",
        "accessibility",
        "click",
        "type",
        "screenshot",
        "popen",
    }
    assert all(thread != event_loop_thread for _name, thread in call_threads)


@pytest.mark.asyncio
async def test_launch_uses_only_canonical_key_and_argv_without_shell(monkeypatch):
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return object()

    monkeypatch.setattr(desktop_host.subprocess, "Popen", fake_popen)
    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: FakeBackend(),
        app_launchers={
            "browser": ("browser.exe", "--private"),
            "browser; calc": ("calc.exe",),
        },
    )

    hostile = await driver.perform("launch", {"app": "browser; calc"})
    unknown = await driver.perform("launch", {"app": "C:\\Windows\\cmd.exe"})
    launched = await driver.perform("launch", {"app": "BROWSER"})

    assert hostile == {"ok": False, "reason": "invalid_app_key"}
    assert unknown == {"ok": False, "reason": "invalid_app_key"}
    assert launched == {"ok": True, "action": "launch", "app": "browser"}
    assert calls == [(["browser.exe", "--private"], {"shell": False})]


@pytest.mark.asyncio
async def test_unknown_action_and_non_mapping_args_are_refused(driver):
    assert await driver.perform("delete", {}) == {
        "ok": False,
        "reason": "unsupported_action",
    }
    assert await driver.perform("observe", []) == {
        "ok": False,
        "reason": "invalid_args",
    }


@pytest.mark.asyncio
async def test_raw_backend_and_screenshot_errors_are_redacted():
    secret = "C:\\Users\\owner\\private.txt token=secret"
    backend_driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: FakeBackend(error=RuntimeError(secret)),
    )
    screenshot_driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: FakeBackend(),
        screenshotter=lambda: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    backend_result = await backend_driver.perform("observe", {})
    screenshot_result = await screenshot_driver.perform("screenshot", {})

    assert backend_result == {"ok": False, "reason": "desktop_host_failed"}
    assert screenshot_result == {"ok": False, "reason": "desktop_host_failed"}
    assert secret not in repr((backend_result, screenshot_result))


@pytest.mark.asyncio
async def test_close_releases_started_backend(backend):
    driver = WindowsDesktopDriver(
        host_enabled=True,
        isolated=True,
        backend_factory=lambda: backend,
    )
    await driver.perform("observe", {})

    await driver.close()

    assert backend.closed is True
