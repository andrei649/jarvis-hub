"""linux.py — the Linux accessibility driver, X11 and Wayland.

A thin adapter over :class:`AccessibilityDriver`, plus the one thing that is
genuinely harder on Linux than anywhere else: **input under Wayland**.

Wayland deliberately has no global synthetic-input API. The routes that exist are:

* the **RemoteDesktop portal** (``org.freedesktop.portal.RemoteDesktop``) — the
  supported one, consent-based, version 2+ for the input methods this needs;
* **libei** — the newer emulated-input protocol, also consent-based;
* ``uinput`` / ``ydotool`` — which need root or a group membership that grants
  every process on the box the ability to synthesise input to any window.

The third route is **refused by policy**, not merely unsupported. It works, and
that is the problem: it bypasses the compositor's consent model entirely, so
"Nerva can type" would silently become "anything running as the owner can type,
including into a password prompt". `wayland_input_unavailable` is the honest
answer when the portal is absent, and the probe's hint tells the owner what to
install rather than how to work around the consent model.

X11 has no such distinction — any client can synthesise input to any window — so
the X11 path uses AT-SPI actions directly and says so.

AT-SPI itself is the observation route on both. Its absence is `atspi_unavailable`.
Everything imports lazily; on a headless runner every seam refuses cleanly.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from agents.core.desktop_drivers.base import AccessibilityDriver, DriverError, DriverUnavailable
from agents.core.desktop_drivers.capture import capture
from agents.core.host_probe import portal_remote_desktop_version

logger = logging.getLogger("jarvis.desktop_drivers")

# The portal version that carries the input methods this driver needs. Below it,
# a portal exists but cannot do what a click requires.
MIN_PORTAL_VERSION = 2

# Input routes, in the order they are tried. `uinput`/`ydotool` are absent on
# purpose — see the module docstring; they are refused by policy, not missing.
WAYLAND_INPUT_ROUTES = ("portal", "libei")

# AT-SPI states that make an element unusable. Read as names rather than enum
# values so a version difference cannot silently invert the meaning.
_DISABLED_STATES = ("STATE_DEFUNCT", "STATE_INSENSITIVE")


def _atspi():
    """Import AT-SPI through PyGObject, or refuse by name."""
    try:
        import gi  # type: ignore[import-not-found]

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi  # type: ignore[import-not-found]
    except (ImportError, ValueError) as exc:
        raise DriverUnavailable("atspi_unavailable") from exc
    return Atspi


def wayland_input_route(
    *, version_reader: Any = None
) -> str:
    """Which consent-based input route Wayland offers here, or "".

    Never returns a uinput/ydotool route: those are refused by policy even when
    present, because they bypass the compositor's consent model.
    """
    read = version_reader or portal_remote_desktop_version
    try:
        version = read()
    except Exception:
        logger.debug("portal version probe failed", exc_info=True)
        version = None
    if isinstance(version, int) and version >= MIN_PORTAL_VERSION:
        return "portal"
    try:
        import libei  # type: ignore[import-not-found]  # noqa: F401

        return "libei"
    except ImportError:
        return ""


# X11 keysyms for every key ``keys.ALLOWED_KEYS`` can name. Letters and digits
# are their ASCII codepoints; the named keys come from ``keysymdef.h``.
_X_KEYSYMS: dict[str, int] = {
    **{c: ord(c) for c in "abcdefghijklmnopqrstuvwxyz"},
    **{d: ord(d) for d in "0123456789"},
    "return": 0xFF0D, "enter": 0xFF0D, "tab": 0xFF09, "escape": 0xFF1B,
    "space": 0x0020, "backspace": 0xFF08, "delete": 0xFFFF,
    "left": 0xFF51, "up": 0xFF52, "right": 0xFF53, "down": 0xFF54,
    "home": 0xFF50, "end": 0xFF57, "pageup": 0xFF55, "pagedown": 0xFF56,
    "f1": 0xFFBE, "f2": 0xFFBF, "f3": 0xFFC0, "f4": 0xFFC1, "f5": 0xFFC2,
    "f6": 0xFFC3, "f7": 0xFFC4, "f8": 0xFFC5, "f9": 0xFFC6, "f10": 0xFFC7,
    "f11": 0xFFC8, "f12": 0xFFC9,
}

# The canonical modifiers, as keysyms to hold down. ``cmd`` is Super on Linux —
# the same physical key the canonicaliser folds cmd/meta/super/win onto.
_X_MODIFIER_KEYSYMS: dict[str, int] = {
    "ctrl": 0xFFE3, "shift": 0xFFE1, "alt": 0xFFE9, "cmd": 0xFFEB,
}

# AT-SPI ScrollType names, resolved late so the table is readable without pyatspi.
_ATSPI_SCROLL: dict[str, str] = {
    "up": "SCROLL_TOP_EDGE", "down": "SCROLL_BOTTOM_EDGE",
    "left": "SCROLL_LEFT_EDGE", "right": "SCROLL_RIGHT_EDGE",
}


def _component_iface(handle: Any) -> Any:
    """The Component interface, or None. Spelling varies by AT-SPI version, and
    the wrong spelling is an absent method rather than an error."""
    for name in ("queryComponent", "get_component_iface"):
        getter = getattr(handle, name, None)
        if callable(getter):
            try:
                return getter()
            except Exception:  # nosec B112 - the wrong spelling for this AT-SPI version is an absent method, not an error
                continue
    return None


class LinuxDesktopDriver(AccessibilityDriver):
    """Drives Linux through AT-SPI. Kernel-mediated by inheritance.

    ``platform`` is the detected session (``linux-x11`` or ``linux-wayland``) and
    decides the input and capture routes — not a preference, a hard constraint.
    """

    def __init__(
        self,
        *,
        platform: str = "linux-x11",
        locator: Any = None,
        atspi: Any = None,
        roots: Any = None,
        capture_fn: Any = None,
        input_route: str | None = None,
    ) -> None:
        super().__init__(locator=locator)
        if platform not in {"linux-x11", "linux-wayland"}:
            raise DriverUnavailable("desktop_platform_unsupported")
        self.platform = platform
        self._atspi_mod = atspi
        self._roots = roots
        self._capture = capture_fn
        self._input_route = input_route

    def _bridge(self) -> Any:
        if self._atspi_mod is None:
            self._atspi_mod = _atspi()
        return self._atspi_mod

    def input_route(self) -> str:
        """The route a mutation will take. X11 needs no portal; Wayland does."""
        if self._input_route is not None:
            return self._input_route
        if self.platform == "linux-x11":
            return "atspi"
        self._input_route = wayland_input_route()
        return self._input_route

    # ── seams ────────────────────────────────────────────────────────────

    def _elements(self) -> list[tuple[dict, Any]]:
        """The active application's AT-SPI children, one level deep.

        Shallow for the same reason as macOS: a full recursive walk of a modern
        toolkit is enormous, and a driver nobody waits for is a driver nobody uses.
        """
        atspi = self._bridge()
        if self._roots is not None:
            roots = list(self._roots())
        else:
            desktop = atspi.get_desktop(0)
            roots = [
                desktop.get_child_at_index(i)
                for i in range(min(int(desktop.get_child_count()), 16))
            ]
        rows: list[tuple[dict, Any]] = []
        for app in roots:
            for index in range(min(int(_count(app)), 32)):
                child = _child(app, index)
                if child is None:
                    continue
                rows.append((self._describe(child), child))
        return rows

    def _describe(self, node: Any) -> dict[str, Any]:
        states = _state_names(node)
        return {
            "name": _text(node, "get_name"),
            "role": _text(node, "get_role_name"),
            "value": _text(node, "get_description"),
            "text": _text(node, "get_description"),
            "enabled": not any(state in states for state in _DISABLED_STATES),
        }

    def _click(self, handle: Any) -> None:
        """AT-SPI's own ``click`` action — the element acts on itself.

        Under Wayland this still needs a consent-based input route to exist,
        because a toolkit may implement the action by synthesising input; the
        check is up front so the refusal is `wayland_input_unavailable` rather
        than a mysterious no-op.
        """
        self._require_input_route()
        action = _action_iface(handle)
        if action is None:
            raise DriverError("element_not_actionable")
        try:
            if not bool(action.do_action(0)):
                raise DriverError("press_failed")
        except DriverError:
            raise
        except Exception as exc:
            raise DriverError("press_failed") from exc

    def _type(self, handle: Any, text: str) -> None:
        """Set the element's text through the EditableText interface.

        Setting the value beats synthesising keystrokes for the same reason as on
        macOS: keys go to whatever is focused now, which may not be the element
        that was matched a moment ago.
        """
        self._require_input_route()
        editable = _editable_iface(handle)
        if editable is None:
            raise DriverError("element_not_editable")
        try:
            if not bool(editable.set_text_contents(text)):
                raise DriverError("type_failed")
        except DriverError:
            raise
        except Exception as exc:
            raise DriverError("type_failed") from exc

    def _focus(self, handle: Any) -> None:
        """Grab focus through AT-SPI's Component interface.

        Focusing is not clicking: on a control that acts on press, a click to
        focus also does the thing. This changes only where the next keystroke
        lands, which is what "focus this field, then type" actually means.
        """
        self._require_input_route()
        component = _component_iface(handle)
        if component is None:
            raise DriverError("element_not_focusable")
        try:
            if not bool(component.grab_focus()):
                raise DriverError("focus_failed")
        except DriverError:
            raise
        except Exception as exc:
            raise DriverError("focus_failed") from exc

    def _key(self, chord: str) -> None:
        """Press one allowlisted chord through AT-SPI's own key synthesis.

        Deliberately AT-SPI and not uinput/ydotool: those work, and that is the
        problem — they bypass the compositor's consent model, which is the same
        reason they are refused as an input route. Under Wayland this still
        requires a consent-based route to exist, so a chord cannot become the one
        way to sidestep the check every other mutation passes.

        This is the only mutation with no element to re-verify against, so the
        allowlist in ``keys.py`` is the whole check — and it has already run.
        """
        self._require_input_route()
        try:
            import pyatspi  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - host-only
            raise DriverUnavailable("desktop_dependency_unavailable") from exc

        from agents.core.desktop_drivers.keys import parse_chord

        mods, base = parse_chord(chord)
        keysym = _X_KEYSYMS.get(base)
        if keysym is None:
            # Parsed but unmapped: refused rather than approximated, because
            # pressing a different key than the card named is worse than none.
            raise DriverError("key_not_mapped")
        sequence = [_X_MODIFIER_KEYSYMS[m] for m in mods if m in _X_MODIFIER_KEYSYMS]
        try:
            for sym in sequence:
                pyatspi.Registry.generateKeyboardEvent(sym, None, pyatspi.KEY_PRESS)
            pyatspi.Registry.generateKeyboardEvent(keysym, None, pyatspi.KEY_PRESSRELEASE)
            for sym in reversed(sequence):
                # Released in reverse, and in a finally-shaped order, because a
                # modifier left down outlives this step and changes every key the
                # owner presses afterwards.
                pyatspi.Registry.generateKeyboardEvent(sym, None, pyatspi.KEY_RELEASE)
        except Exception as exc:
            for sym in reversed(sequence):
                # Best-effort release: the original failure is the one worth
                # reporting, but a modifier left down would change every key the
                # owner presses after this step.
                with contextlib.suppress(Exception):
                    pyatspi.Registry.generateKeyboardEvent(sym, None, pyatspi.KEY_RELEASE)
            raise DriverError("key_failed") from exc

    def _scroll(self, handle: Any, direction: str, notches: int) -> None:
        """Scroll a named element through AT-SPI, one bounded step at a time."""
        self._require_input_route()
        component = _component_iface(handle)
        if component is None:
            raise DriverError("element_not_scrollable")
        scroll_type = _ATSPI_SCROLL.get(direction)
        if scroll_type is None:
            raise DriverError("scroll_direction_unsupported")
        try:
            import pyatspi  # type: ignore[import-not-found]

            target = getattr(pyatspi, scroll_type, None)
            if target is None:
                raise DriverError("scroll_unsupported_by_atspi")
            for _ in range(int(notches)):
                component.scrollTo(target)
        except DriverError:
            raise
        except ImportError as exc:  # pragma: no cover - host-only
            raise DriverUnavailable("desktop_dependency_unavailable") from exc
        except Exception as exc:
            raise DriverError("scroll_failed") from exc

    def _require_input_route(self) -> None:
        route = self.input_route()
        if not route:
            # Wayland with no portal and no libei. uinput/ydotool would work here
            # and are refused: they bypass the compositor's consent model.
            raise DriverUnavailable("wayland_input_unavailable")

    def _screenshot(self) -> bytes:
        if self._capture is not None:
            return self._capture()
        return capture(self.platform)


# ── small AT-SPI helpers, each tolerant of a missing method ─────────────────

def _text(node: Any, method: str) -> str:
    try:
        value = getattr(node, method)()
    except Exception:
        return ""
    return str(value) if isinstance(value, (str, int, float)) else ""


def _count(node: Any) -> int:
    try:
        return int(node.get_child_count())
    except Exception:
        return 0


def _child(node: Any, index: int) -> Any:
    try:
        return node.get_child_at_index(index)
    except Exception:
        return None


def _state_names(node: Any) -> set[str]:
    try:
        states = node.get_state_set()
        return {str(name) for name in states.get_states()}
    except Exception:
        return set()


def _action_iface(node: Any) -> Any:
    """AT-SPI renamed this accessor between versions; try both spellings."""
    for name in ("get_action_iface", "get_action"):
        try:
            iface = getattr(node, name)()
        except Exception:  # nosec B112 - the wrong spelling for this AT-SPI version is an absent method, not an error
            continue
        if iface is not None:
            return iface
    return None


def _editable_iface(node: Any) -> Any:
    """Same version split as :func:`_action_iface`."""
    for name in ("get_editable_text_iface", "get_editable_text"):
        try:
            iface = getattr(node, name)()
        except Exception:  # nosec B112 - the wrong spelling for this AT-SPI version is an absent method, not an error
            continue
        if iface is not None:
            return iface
    return None


__all__ = [
    "MIN_PORTAL_VERSION",
    "WAYLAND_INPUT_ROUTES",
    "LinuxDesktopDriver",
    "wayland_input_route",
]
