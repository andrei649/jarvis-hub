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
