"""platform.py — pick the right desktop driver for this host, or say why not.

One function does the choosing, and it makes exactly one decision: which adapter
matches the session the host probe already detected. It does not install
anything, does not prompt for a permission, and does not fall back to a weaker
route when the right one is unavailable — a silent downgrade from "drive the real
desktop" to "pretend" is precisely the class of surprise this product refuses.

Choosing is driven by :func:`agents.core.host_probe.probe_host`, so the factory
and the Host Readiness panel can never disagree about what this machine can do:
they read the same probe and speak the same closed refusal vocabulary.

The two ways to get nothing back, and the difference between them:

* **Refused** — the platform is known but something blocks it (no Accessibility
  grant, a Wayland session with no portal, a missing library). ``reason`` names
  it from the probe's vocabulary, and ``hint`` is the probe's own sentence about
  what the owner can do.
* **Unsupported** — the session is not one a driver exists for at all (headless
  CI, for example). ``desktop_platform_unsupported``.

Neither is an exception. A host that cannot drive a desktop is an ordinary fact,
and the caller renders it; raising would push every caller into a try/except that
mostly exists to swallow it again.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agents.core.host_probe import (
    REFUSAL_HINTS,
    HostProbe,
    desktop_operator_available,
    probe_host,
)

logger = logging.getLogger("jarvis.desktop_drivers")

# Which adapter serves which detected session. `headless` is deliberately absent:
# there is no driver for a host with no display, and inventing one that "works"
# would be the silent downgrade this module exists to prevent.
DRIVER_PLATFORMS = ("windows", "macos", "linux-x11", "linux-wayland")


@dataclass(frozen=True)
class DriverChoice:
    """What the factory decided, and why. ``driver`` is None unless ``ok``."""

    ok: bool
    platform: str
    driver: Any = None
    reason: str = ""
    hint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "platform": self.platform,
            "driver": type(self.driver).__name__ if self.driver is not None else None,
            "reason": self.reason,
            "hint": self.hint,
        }


def _blocking_refusal(probe: HostProbe) -> str:
    """The first refusal that actually stops a driver, in severity order.

    ``local_vlm_not_proven_local`` is excluded: it disables the *visual fallback*,
    not the accessibility route, and refusing the whole driver for it would mean a
    perfectly good a11y-driven session is unavailable because a vision model is
    not configured. ``target_elevated`` is per-window, not per-host, and surfaces
    at the step that hits it.
    """
    ordered = (
        "desktop_platform_unsupported",
        "atspi_unavailable",
        "accessibility_permission_missing",
        "wayland_input_unavailable",
        "wayland_capture_unavailable",
        "screen_recording_permission_missing",
        "desktop_dependency_unavailable",
    )
    present = set(probe.refusals)
    for reason in ordered:
        if reason in present:
            return reason
    return ""


def driver_for_host(
    probe: HostProbe | None = None,
    *,
    locator: Any = None,
    factories: dict[str, Any] | None = None,
) -> DriverChoice:
    """Build the driver this host can actually run, or explain the refusal.

    ``factories`` maps a platform to a zero-argument callable and exists for
    tests; production resolves the adapters lazily below so importing this module
    never imports pywinauto, pyobjc or PyGObject.
    """
    p = probe if probe is not None else probe_host()
    platform = p.platform

    if platform not in DRIVER_PLATFORMS:
        return DriverChoice(
            False, platform,
            reason="desktop_platform_unsupported",
            hint=REFUSAL_HINTS["desktop_platform_unsupported"],
        )

    blocking = _blocking_refusal(p)
    if blocking:
        return DriverChoice(False, platform, reason=blocking,
                            hint=REFUSAL_HINTS.get(blocking, ""))
    # A probe with no blocking refusal but which the probe's own verdict rejects
    # is a disagreement, and the safe reading of a disagreement is "no".
    if not desktop_operator_available(p):
        reason = next(iter(sorted(p.refusals)), "desktop_dependency_unavailable")
        return DriverChoice(False, platform, reason=reason,
                            hint=REFUSAL_HINTS.get(reason, ""))

    build = (factories or {}).get(platform) or _adapter(platform)
    if build is None:
        return DriverChoice(
            False, platform,
            reason="desktop_dependency_unavailable",
            hint=REFUSAL_HINTS["desktop_dependency_unavailable"],
        )
    try:
        driver = build(locator=locator) if factories is None else build()
    except Exception as exc:
        from agents.core.desktop_drivers.base import DriverUnavailable

        reason = exc.reason if isinstance(exc, DriverUnavailable) else "desktop_dependency_unavailable"
        logger.info("desktop driver unavailable on %s: %s", platform, reason)
        return DriverChoice(False, platform, reason=reason,
                            hint=REFUSAL_HINTS.get(reason, ""))
    return DriverChoice(True, platform, driver=driver)


def _adapter(platform: str):
    """Resolve the adapter constructor lazily — importing costs nothing here."""
    if platform == "windows":
        def _windows(*, locator=None):
            from agents.core.desktop_host import WindowsDesktopDriver

            return WindowsDesktopDriver.from_env(local_locator=locator)

        return _windows
    if platform == "macos":
        def _macos(*, locator=None):
            from agents.core.desktop_drivers.macos import MacDesktopDriver

            return MacDesktopDriver(locator=locator)

        return _macos
    if platform in {"linux-x11", "linux-wayland"}:
        def _linux(*, locator=None):
            from agents.core.desktop_drivers.linux import LinuxDesktopDriver

            return LinuxDesktopDriver(platform=platform, locator=locator)

        return _linux
    return None


def describe_host(probe: HostProbe | None = None) -> dict[str, Any]:
    """What a caller needs to render "can this box be driven, and why not"."""
    p = probe if probe is not None else probe_host()
    choice = driver_for_host(p)
    return {
        "platform": p.platform,
        "driver_available": choice.ok,
        "reason": choice.reason,
        "hint": choice.hint,
        "refusals": list(p.refusals),
        "warnings": list(p.warnings),
        # The visual fallback is reported separately because it is genuinely
        # separate: an a11y-driven session works without it.
        "visual_fallback": "local_vlm_not_proven_local" not in set(p.refusals),
    }


__all__ = ["DRIVER_PLATFORMS", "DriverChoice", "describe_host", "driver_for_host"]
