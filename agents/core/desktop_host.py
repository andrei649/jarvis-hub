"""Optional, isolated Windows host driver for governed desktop actions.

The module owns no approval policy.  It is an actuation seam for
``GovernedDesktop`` and therefore requires the Action Kernel
(``requires_kernel = True``).  Optional Windows dependencies are imported only when
the corresponding host operation is first used, keeping normal CI dependency-free.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import io
import itertools
import math
import re
import subprocess  # nosec B404
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from agents.core.env_config import env_flag

_APP_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_OBSERVE_ACTIONS = frozenset({"observe", "read", "locate", "screenshot"})
_MUTATE_ACTIONS = frozenset({"click", "type", "launch"})
_LOCAL_PROVENANCE = frozenset({"local", "local-only", "local_only", "strict-local", "strict_local"})
_MAX_LOCAL_NUMERIC_MAGNITUDE = 1_000_000_000


class DesktopHostError(RuntimeError):
    """Base class for bounded desktop-host failures."""


class DesktopHostDisabled(DesktopHostError):
    """Desktop host actuation was not explicitly enabled and isolated."""


class DesktopDependencyUnavailable(DesktopHostError):
    """An optional host dependency is unavailable."""


class _ScreenshotTooLarge(DesktopHostError):
    """Screenshot bytes exceeded the configured budget before encoding."""


async def _resolve(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _call_host(callable_: Callable[..., Any], /, *args, **kwargs) -> Any:
    is_async = inspect.iscoroutinefunction(callable_) or inspect.iscoroutinefunction(
        callable_.__call__
    )
    if is_async:
        return await callable_(*args, **kwargs)
    return await _resolve(await asyncio.to_thread(callable_, *args, **kwargs))


class _PywinautoBackend:
    """Small dependency-lazy adapter over pywinauto's UIA backend."""

    def __init__(self) -> None:
        try:
            from pywinauto import Desktop
        except ImportError:
            raise DesktopDependencyUnavailable("Windows accessibility backend is unavailable") from None
        self._desktop = Desktop(backend="uia")

    def accessibility_elements(self):
        for window in self._desktop.windows():
            controls = [window]
            with contextlib.suppress(Exception):
                controls.extend(window.descendants())
            for control in controls:
                with contextlib.suppress(Exception):
                    info = control.element_info
                    yield {
                        "name": getattr(info, "name", ""),
                        "role": getattr(info, "control_type", ""),
                        "automation_id": getattr(info, "automation_id", ""),
                        "enabled": bool(control.is_enabled()),
                        "_control": control,
                    }

    @staticmethod
    def click(element) -> None:
        control = element.get("_control") if isinstance(element, Mapping) else element
        control.invoke()

    @staticmethod
    def type(element, text: str) -> None:
        control = element.get("_control") if isinstance(element, Mapping) else element
        control.set_edit_text(text)

    def close(self) -> None:
        self._desktop = None


def _default_screenshotter() -> bytes:
    try:
        from PIL import ImageGrab
    except ImportError:
        raise DesktopDependencyUnavailable("Windows screenshot backend is unavailable") from None
    image = ImageGrab.grab()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class WindowsDesktopDriver:
    """Bounded accessibility-first host driver for an isolated Windows desktop."""

    requires_kernel = True

    def __init__(
        self,
        *,
        host_enabled: bool = False,
        isolated: bool = False,
        backend_factory: Callable[[], Any] | None = None,
        screenshotter: Callable[[], Any] | None = None,
        local_vlm_locator: Callable[..., Any] | None = None,
        app_launchers: Mapping[str, Sequence[str]] | None = None,
        max_elements: int = 200,
        max_text_chars: int = 512,
        max_type_chars: int = 20_000,
        max_screenshot_bytes: int = 5_000_000,
    ) -> None:
        for label, value in (("host_enabled", host_enabled), ("isolated", isolated)):
            if type(value) is not bool:
                raise TypeError(f"{label} must be a literal bool")
        for label, value in (
            ("max_elements", max_elements),
            ("max_text_chars", max_text_chars),
            ("max_type_chars", max_type_chars),
            ("max_screenshot_bytes", max_screenshot_bytes),
        ):
            if int(value) <= 0:
                raise ValueError(f"{label} must be positive")

        self.host_enabled = host_enabled
        self.isolated = isolated
        self.max_elements = int(max_elements)
        self.max_text_chars = int(max_text_chars)
        self.max_type_chars = int(max_type_chars)
        self.max_screenshot_bytes = int(max_screenshot_bytes)
        self._backend_factory = backend_factory or _PywinautoBackend
        self._screenshotter = screenshotter or _default_screenshotter
        self._local_vlm_locator = local_vlm_locator
        self._app_launchers = self._normalize_launchers(app_launchers or {})
        self._backend = None

    @classmethod
    def from_env(cls, **kwargs) -> WindowsDesktopDriver:
        """Construct only after both explicit host and isolation opt-ins are enabled."""
        if not env_flag("JARVIS_DESKTOP_HOST") or not env_flag("JARVIS_DESKTOP_ISOLATED"):
            raise DesktopHostDisabled("isolated desktop host actuation is disabled")
        kwargs.setdefault("host_enabled", True)
        kwargs.setdefault("isolated", True)
        return cls(**kwargs)

    async def __aenter__(self) -> WindowsDesktopDriver:
        self._ensure_enabled()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def perform(self, action: str, args: dict) -> dict:
        """Perform one already-governed action with bounded, redacted results."""
        self._ensure_enabled()
        if not isinstance(args, Mapping):
            return {"ok": False, "reason": "invalid_args"}
        action = str(action or "").strip().lower()
        try:
            if action in _OBSERVE_ACTIONS:
                return await self._observe(action, dict(args))
            if action in _MUTATE_ACTIONS:
                return await self._mutate(action, dict(args))
            return {"ok": False, "reason": "unsupported_action"}
        except _ScreenshotTooLarge:
            return {"ok": False, "reason": "screenshot_too_large"}
        except DesktopDependencyUnavailable:
            return {"ok": False, "reason": "desktop_dependency_unavailable"}
        except Exception:
            # Never carry host exception text, paths, titles, or dependency details upward.
            return {"ok": False, "reason": "desktop_host_failed"}

    async def close(self) -> None:
        """Idempotently release an accessibility backend if one was started."""
        backend, self._backend = self._backend, None
        if backend is None:
            return
        close = getattr(backend, "close", None)
        if close is None:
            return
        try:
            await _call_host(close)
        except Exception:
            # Cleanup failure is intentionally redacted and cannot turn into raw audit text.
            return

    def _ensure_enabled(self) -> None:
        if not self.host_enabled or not self.isolated:
            raise DesktopHostDisabled("isolated desktop host actuation is disabled")

    async def _ensure_backend(self):
        if self._backend is None:
            self._backend = await _call_host(self._backend_factory)
        return self._backend

    async def _observe(self, action: str, args: dict) -> dict:
        if action == "screenshot":
            image = await self._screenshot_bytes()
            return {
                "ok": True,
                "source": "screenshot",
                "mime": "image/png",
                "bytes": len(image),
                "image_base64": base64.b64encode(image).decode("ascii"),
            }

        snapshot, truncated = await self._accessibility_snapshot()
        if action == "observe":
            return {
                "ok": True,
                "source": "accessibility",
                "elements": [normalized for normalized, _raw in snapshot],
                "truncated": truncated,
            }

        query = self._bounded_arg(args.get("query"))
        if not query:
            return {"ok": False, "reason": "query_required"}
        match = self._find(snapshot, query, exact_name=False)
        if match is not None:
            normalized, _raw = match
            if action == "read":
                text = normalized.get("value") or normalized.get("text") or normalized.get("name", "")
                return {
                    "ok": True,
                    "source": "accessibility",
                    "text": text,
                    "element": normalized,
                }
            return {"ok": True, "source": "accessibility", "element": normalized}

        if action == "read":
            return {"ok": False, "reason": "not_found"}
        return await self._locate_with_local_vlm(query)

    async def _mutate(self, action: str, args: dict) -> dict:
        if action == "launch":
            return await self._launch(args)

        raw_name = args.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            return {"ok": False, "reason": "named_element_required"}
        name = raw_name.strip()
        if len(name) > self.max_text_chars:
            return {"ok": False, "reason": "element_name_too_large"}
        if action == "type":
            text = args.get("text")
            if not isinstance(text, str):
                return {"ok": False, "reason": "text_required"}
            if len(text) > self.max_type_chars:
                return {"ok": False, "reason": "text_too_large"}

        snapshot, _truncated = await self._accessibility_snapshot()
        match = self._find(snapshot, name, exact_name=True)
        if match is None:
            return {"ok": False, "reason": "element_not_found"}
        normalized, raw = match
        backend = await self._ensure_backend()
        if action == "click":
            await _call_host(backend.click, raw)
        else:
            await _call_host(backend.type, raw, text)
        return {"ok": True, "action": action, "element": normalized.get("name", "")}

    async def _launch(self, args: dict) -> dict:
        raw_key = args.get("app")
        if not isinstance(raw_key, str):
            return {"ok": False, "reason": "invalid_app_key"}
        key = raw_key.strip().lower()
        if not _APP_KEY_RE.fullmatch(key):
            return {"ok": False, "reason": "invalid_app_key"}
        argv = self._app_launchers.get(key)
        if argv is None:
            return {"ok": False, "reason": "app_not_allowlisted"}
        # argv comes from the owner configuration; request-provided arguments never enter it.
        await _call_host(subprocess.Popen, list(argv), shell=False)
        return {"ok": True, "action": "launch", "app": key}

    async def _accessibility_snapshot(self) -> tuple[list[tuple[dict, Any]], bool]:
        backend = await self._ensure_backend()
        raw_elements = await _call_host(backend.accessibility_elements)
        bounded = await asyncio.to_thread(
            lambda: list(itertools.islice(iter(raw_elements or ()), self.max_elements + 1))
        )
        truncated = len(bounded) > self.max_elements
        snapshot = [
            (self._normalize_element(raw, index), raw)
            for index, raw in enumerate(bounded[: self.max_elements])
        ]
        return snapshot, truncated

    def _normalize_element(self, raw: Any, index: int) -> dict:
        normalized: dict[str, Any] = {"id": f"element-{index}"}
        for field in ("name", "role", "text", "value", "automation_id"):
            value = self._element_value(raw, field)
            if value not in (None, ""):
                normalized[field] = str(value)[: self.max_text_chars]
        enabled = self._element_value(raw, "enabled")
        if isinstance(enabled, bool):
            normalized["enabled"] = enabled
        return normalized

    @staticmethod
    def _element_value(raw: Any, field: str) -> Any:
        if isinstance(raw, Mapping):
            return raw.get(field)
        return getattr(raw, field, None)

    def _bounded_arg(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()[: self.max_text_chars]

    @staticmethod
    def _find(snapshot: list[tuple[dict, Any]], query: str, *, exact_name: bool):
        wanted = query.casefold()
        if exact_name:
            for normalized, raw in snapshot:
                raw_name = WindowsDesktopDriver._element_value(raw, "name")
                if str(raw_name or "").casefold() == wanted:
                    return normalized, raw
            return None
        for normalized, raw in snapshot:
            name = str(normalized.get("name", "")).casefold()
            if name == wanted:
                return normalized, raw
        for normalized, raw in snapshot:
            for field in ("name", "text", "value", "role", "automation_id"):
                if wanted in str(normalized.get(field, "")).casefold():
                    return normalized, raw
        return None

    async def _locate_with_local_vlm(self, query: str) -> dict:
        locator = self._local_vlm_locator
        if locator is None:
            return {"ok": False, "reason": "not_found"}
        if not self._is_proven_local(locator):
            return {"ok": False, "reason": "local_vlm_not_proven_local"}
        image = await self._screenshot_bytes()
        result = await _call_host(locator, query=query, screenshot=image)
        if not isinstance(result, Mapping) or not result:
            return {"ok": False, "reason": "not_found"}
        normalized = self._normalize_local_result(result)
        if not normalized:
            return {"ok": False, "reason": "local_vlm_result_invalid"}
        return {
            "ok": True,
            "source": "local_vlm",
            "provenance": "local",
            "element": normalized,
        }

    @staticmethod
    def _is_proven_local(locator: Any) -> bool:
        if getattr(locator, "is_local", False) is True:
            return True
        if getattr(locator, "local_only", False) is True:
            return True
        provenance = str(getattr(locator, "provenance", "")).strip().lower()
        return provenance in _LOCAL_PROVENANCE

    def _normalize_local_result(self, result: Mapping) -> dict:
        normalized = {}
        for key, value in itertools.islice(result.items(), 16):
            safe_key = str(key)[:64]
            if isinstance(value, str):
                normalized[safe_key] = value[: self.max_text_chars]
            elif (
                value is None
                or isinstance(value, bool)
                or (isinstance(value, int) and abs(value) <= _MAX_LOCAL_NUMERIC_MAGNITUDE)
                or (
                    isinstance(value, float)
                    and math.isfinite(value)
                    and abs(value) <= _MAX_LOCAL_NUMERIC_MAGNITUDE
                )
            ):
                normalized[safe_key] = value
        return normalized

    async def _screenshot_bytes(self) -> bytes:
        image = await _call_host(self._screenshotter)
        if not isinstance(image, (bytes, bytearray, memoryview)):
            raise DesktopHostError("desktop screenshot failed")
        value = bytes(image)
        if len(value) > self.max_screenshot_bytes:
            raise _ScreenshotTooLarge("screenshot exceeds configured byte budget")
        return value

    @staticmethod
    def _normalize_launchers(values: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, ...]]:
        normalized: dict[str, tuple[str, ...]] = {}
        for raw_key, raw_argv in values.items():
            if not isinstance(raw_key, str):
                continue
            key = raw_key.strip().lower()
            if not _APP_KEY_RE.fullmatch(key):
                continue
            if isinstance(raw_argv, (str, bytes)):
                continue
            argv = tuple(raw_argv)
            if not argv or len(argv) > 16:
                continue
            if not all(isinstance(part, str) and 0 < len(part) <= 2_048 for part in argv):
                continue
            normalized[key] = argv
        return normalized


__all__ = [
    "DesktopDependencyUnavailable",
    "DesktopHostDisabled",
    "DesktopHostError",
    "WindowsDesktopDriver",
]
