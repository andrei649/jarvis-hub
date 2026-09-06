"""macos.py — the macOS accessibility driver.

A thin adapter over :class:`AccessibilityDriver`: the observe/act policy, the
bounds and the kernel requirement all live in the base, so this file is only the
three platform seams plus the one macOS-specific rule that matters.

That rule is **Nerva never asks macOS for a permission**. `AXIsProcessTrusted`
with the prompt option ON puts a system dialog on the owner's screen, from a
background process, at a moment they did not choose. The host probe already reads
the grant with the prompt OFF, and this driver refuses
(`accessibility_permission_missing`) when it is absent. Granting is the owner's
deliberate act in System Settings, and `docs/OWNER_TASKS.md` says how.

Everything imports lazily: on a Linux CI runner this module is importable and
every seam refuses cleanly.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.core.desktop_drivers.base import AccessibilityDriver, DriverError, DriverUnavailable
from agents.core.desktop_drivers.capture import capture

logger = logging.getLogger("jarvis.desktop_drivers")

# The AX attributes read per element. A fixed list keeps the snapshot bounded and
# predictable — and keeps the driver from hoovering up an entire window tree of
# text it has no reason to read.
AX_ATTRIBUTES = ("AXTitle", "AXRole", "AXValue", "AXDescription", "AXEnabled")


def _application_services():
    """Import the AX bridge, or refuse by name. Never prompts."""
    try:
        import ApplicationServices  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DriverUnavailable("desktop_dependency_unavailable") from exc
    return ApplicationServices


def accessibility_trusted() -> bool:
    """Read the grant with the prompt option OFF — a check, never a request."""
    services = _application_services()
    try:
        return bool(
            services.AXIsProcessTrustedWithOptions(
                {services.kAXTrustedCheckOptionPrompt: False}
            )
        )
    except Exception:
        logger.debug("macOS AX trust check failed", exc_info=True)
        return False


def _attribute(services: Any, element: Any, name: str) -> Any:
    """One AX attribute, or None. A missing attribute is normal, not an error."""
    try:
        error, value = services.AXUIElementCopyAttributeValue(element, name, None)
    except Exception:
        return None
    return value if error == 0 else None


class MacDesktopDriver(AccessibilityDriver):
    """Drives macOS through the accessibility API. Kernel-mediated by inheritance."""

    platform = "macos"

    def __init__(self, *, locator: Any = None, services: Any = None,
                 app_elements: Any = None, capture_fn: Any = None) -> None:
        super().__init__(locator=locator)
        # Injectable seams keep the tests hermetic on a Linux runner: production
        # passes none of them and everything resolves lazily below.
        self._services = services
        self._app_elements = app_elements
        self._capture = capture_fn

    def _bridge(self) -> Any:
        if self._services is None:
            self._services = _application_services()
            if not accessibility_trusted():
                raise DriverUnavailable("accessibility_permission_missing")
        return self._services

    # ── seams ────────────────────────────────────────────────────────────

    def _elements(self) -> list[tuple[dict, Any]]:
        """The focused application's accessibility children, flattened one level.

        One level on purpose: a full recursive walk of an Electron window can run
        to tens of thousands of nodes, and a driver that spends ten seconds
        enumerating before every click is not usable. The visual fallback exists
        for what a shallow walk cannot see.
        """
        services = self._bridge()
        if self._app_elements is not None:
            return list(self._app_elements())

        system = services.AXUIElementCreateSystemWide()
        focused = _attribute(services, system, "AXFocusedApplication")
        if focused is None:
            raise DriverError("no_focused_application")
        windows = _attribute(services, focused, "AXWindows") or []
        rows: list[tuple[dict, Any]] = []
        for window in list(windows)[:8]:
            for child in list(_attribute(services, window, "AXChildren") or []):
                rows.append((self._describe(services, child), child))
        return rows

    def _describe(self, services: Any, element: Any) -> dict[str, Any]:
        values = {name: _attribute(services, element, name) for name in AX_ATTRIBUTES}
        return {
            "name": values.get("AXTitle") or values.get("AXDescription") or "",
            "role": values.get("AXRole") or "",
            "value": values.get("AXValue") or "",
            "text": values.get("AXDescription") or "",
            "enabled": values.get("AXEnabled") is not False,
        }

    def _click(self, handle: Any) -> None:
        """AXPress — the element's own action, not a synthetic click at a point.

        Pressing the control is safer than moving the cursor and clicking: it
        cannot land on whatever moved under the pointer between the snapshot and
        the click, and it works with the window unfocused.
        """
        services = self._bridge()
        try:
            error = services.AXUIElementPerformAction(handle, "AXPress")
        except Exception as exc:
            raise DriverError("press_failed") from exc
        if error != 0:
            raise DriverError("press_failed")

    def _type(self, handle: Any, text: str) -> None:
        """Set AXValue rather than synthesising keystrokes.

        Synthetic keys go to whatever is focused *now*, which may not be the
        element that was matched; setting the value targets the control itself.
        """
        services = self._bridge()
        try:
            error = services.AXUIElementSetAttributeValue(handle, "AXValue", text)
        except Exception as exc:
            raise DriverError("type_failed") from exc
        if error != 0:
            raise DriverError("type_failed")

    def _screenshot(self) -> bytes:
        if self._capture is not None:
            return self._capture()
        return capture("macos")


__all__ = ["AX_ATTRIBUTES", "MacDesktopDriver", "accessibility_trusted"]
