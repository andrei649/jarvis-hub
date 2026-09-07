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


# Virtual keycodes (Carbon `Events.h`). Only the keys ``keys.ALLOWED_KEYS`` can
# name are here; a key that parses but is missing from this table is refused
# rather than approximated, because pressing a different key than the card said
# is worse than pressing none at all.
_MAC_KEYCODES: dict[str, int] = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26,
    "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38,
    "k": 40, "n": 45, "m": 46,
    "return": 36, "enter": 36, "tab": 48, "space": 49, "backspace": 51,
    "escape": 53, "delete": 117,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
    "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}

# CGEventFlags. Named rather than imported so the table can be read (and tested)
# without Quartz present.
_MAC_MODIFIER_FLAGS: dict[str, int] = {
    "cmd": 1 << 20, "shift": 1 << 17, "alt": 1 << 19, "ctrl": 1 << 18,
}

# (vertical, horizontal) wheel deltas. Positive vertical scrolls the content up,
# which moves the view DOWN — the direction names describe what the reader sees
# moving, not the sign of the delta.
_SCROLL_VECTORS: dict[str, tuple[int, int]] = {
    "down": (-1, 0), "up": (1, 0), "right": (0, -1), "left": (0, 1),
}


def _split(chord: str) -> tuple[tuple[str, ...], str]:
    """Canonical modifiers and base key. The chord is already allowlisted."""
    from agents.core.desktop_drivers.keys import parse_chord

    return parse_chord(chord)


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

    def _focus(self, handle: Any) -> None:
        """Set AXFocused rather than clicking to focus.

        A click to focus is a click: on a control that also acts on press, it
        does the thing as well as focusing it. Setting the attribute focuses and
        nothing else, which is what "focus this field, then type" means.
        """
        services = self._bridge()
        try:
            error = services.AXUIElementSetAttributeValue(handle, "AXFocused", True)
        except Exception as exc:
            raise DriverError("focus_failed") from exc
        if error != 0:
            raise DriverError("focus_failed")

    def _key(self, chord: str) -> None:
        """Press one allowlisted chord through CGEvent.

        This is the one action with no element handle, so unlike every other
        mutation it cannot re-verify its target — the chord allowlist in
        ``keys.py`` is the whole of the check, and it runs before this is called.
        """
        try:
            import Quartz  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - host-only
            raise DriverUnavailable("desktop_dependency_unavailable") from exc

        mods, base = _split(chord)
        keycode = _MAC_KEYCODES.get(base)
        if keycode is None:
            # A key that parsed but has no macOS code is refused rather than
            # approximated: pressing a different key than the card named is worse
            # than pressing none.
            raise DriverError("key_not_mapped")
        flags = 0
        for mod in mods:
            flags |= _MAC_MODIFIER_FLAGS.get(mod, 0)
        try:
            for down in (True, False):
                event = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
                if event is None:
                    raise DriverError("key_failed")
                if flags:
                    Quartz.CGEventSetFlags(event, flags)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        except DriverError:
            raise
        except Exception as exc:
            raise DriverError("key_failed") from exc

    def _scroll(self, handle: Any, direction: str, notches: int) -> None:
        """Scroll the frontmost window by a bounded number of notches.

        The handle is accepted and deliberately unused: AX has no scroll action,
        so this is a wheel event on whatever is under the pointer. Saying that
        here matters — a caller reading the signature would otherwise assume the
        named element is what scrolls, and act on a stale assumption when it does
        not.
        """
        try:
            import Quartz  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - host-only
            raise DriverUnavailable("desktop_dependency_unavailable") from exc

        vertical, horizontal = _SCROLL_VECTORS.get(direction, (0, 0))
        try:
            for _ in range(int(notches)):
                event = Quartz.CGEventCreateScrollWheelEvent(
                    None, Quartz.kCGScrollEventUnitLine, 2, vertical, horizontal
                )
                if event is None:
                    raise DriverError("scroll_failed")
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        except DriverError:
            raise
        except Exception as exc:
            raise DriverError("scroll_failed") from exc

    def _screenshot(self) -> bytes:
        if self._capture is not None:
            return self._capture()
        return capture("macos")


__all__ = ["AX_ATTRIBUTES", "MacDesktopDriver", "accessibility_trusted"]
