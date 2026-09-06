"""Host capability probe — the honest-refusal vocabulary of the computer operator.

Until this module existed the only thing the desktop seam could say about *why*
it cannot drive this machine was ``DesktopDependencyUnavailable`` when pywinauto
failed to import.  It could not say "Accessibility is not granted to this
process", "this is a Wayland session and the RemoteDesktop portal is older than
v2", "no AT-SPI bridge", or "the target window is elevated".  ``probe_host``
turns those into first-class, testable reasons that the driver factory,
``operator_router`` availability callbacks and the HUD can render verbatim.

Contract (MOONSHOT §5 — honesty, local-first, never noisy):

* **Observe-only.**  The probe never actuates, never spawns a GUI, and never
  calls a permission-*requesting* API.  On macOS it asks
  ``AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: False})`` and
  ``CGPreflightScreenCaptureAccess()`` — the silent preflight variants — and the
  ``CGRequestScreenCaptureAccess`` / ``prompt=True`` forms are deliberately
  absent from this file.  Requesting a permission is an owner decision that
  belongs to the permission ledger, not to a probe.
* **No new hard dependencies.**  Every OS library is looked up with
  ``importlib.util.find_spec`` and imported lazily inside the default call that
  needs it; a missing module is a *fact* in ``deps``, never an exception.
* **Injectable.**  ``env``, ``importer``, ``calls`` and ``sys_platform`` are
  parameters so the whole platform matrix is testable offline, on any CI box,
  without OS permissions or subprocesses.
* **Reads flags only to report them.**  ``JARVIS_DESKTOP_HOST``,
  ``JARVIS_DESKTOP_ISOLATED``, ``JARVIS_PLAYWRIGHT_HOST`` and
  ``JARVIS_TERMINAL_LOCAL_HOST`` appear in ``flags`` so the HUD can show *why*
  a surface is off; the probe itself is default-on because it changes nothing.

The refusal vocabulary is a closed set (``REFUSAL_REASONS``).  Drivers and the
factory pin their own reason strings to it so a refusal in a log, a route
payload and the HUD is always the same word.  ``target_elevated`` is part of
the vocabulary but is a *per-step* fact only a driver can establish; the probe
never emits it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess  # nosec B404 — argv lists only, never shell=True
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from agents.core.env_config import truthy

PLATFORMS: tuple[str, ...] = ("windows", "macos", "linux-x11", "linux-wayland", "headless")

# Fixed key order → stable canonical JSON → stable fingerprints.
DEP_NAMES: tuple[str, ...] = (
    "pywinauto",
    "uiautomation",
    "pyobjc",
    "gi_atspi",
    "libei",
    "playwright",
    "mss",
)

# Probe key → importable module name.  ``pyobjc`` is the distribution; the
# framework wrapper the macOS driver actually imports is ``ApplicationServices``.
# ``gi_atspi`` checks for PyGObject only: resolving the AT-SPI typelib would mean
# importing ``gi.repository`` (which loads GObject), and a probe must not do that.
DEP_MODULES: Mapping[str, str] = {
    "pywinauto": "pywinauto",
    "uiautomation": "uiautomation",
    "pyobjc": "ApplicationServices",
    "gi_atspi": "gi",
    "libei": "libei",
    "playwright": "playwright",
    "mss": "mss",
}

# Command-line tools some routes lean on (argv only, never shell).  Reported,
# never executed by the probe — except the D-Bus property read below, which is
# a read-only query with a hard timeout.
BINARY_NAMES: tuple[str, ...] = ("xdotool", "grim", "gdbus", "busctl")

REPORTED_FLAGS: tuple[str, ...] = (
    "JARVIS_DESKTOP_HOST",
    "JARVIS_DESKTOP_ISOLATED",
    "JARVIS_PLAYWRIGHT_HOST",
    "JARVIS_TERMINAL_LOCAL_HOST",
)

REFUSAL_REASONS: frozenset[str] = frozenset(
    {
        "desktop_platform_unsupported",
        "accessibility_permission_missing",
        "screen_recording_permission_missing",
        "wayland_input_unavailable",
        "wayland_capture_unavailable",
        "atspi_unavailable",
        "target_elevated",
        "desktop_dependency_unavailable",
        "local_vlm_not_proven_local",
    }
)

# What the owner can do about each reason.  Plain sentences, no paths, no
# secrets — safe to render verbatim in the HUD.
REFUSAL_HINTS: Mapping[str, str] = {
    "desktop_platform_unsupported": "No graphical session was detected (no display); the desktop operator needs a logged-in desktop.",
    "accessibility_permission_missing": "Grant Accessibility to the Nerva Python process in System Settings → Privacy & Security; Nerva never requests it on its own.",
    "screen_recording_permission_missing": "Grant Screen Recording to the Nerva Python process in System Settings → Privacy & Security; Nerva never requests it on its own.",
    "wayland_input_unavailable": "Wayland input needs python-libei and an org.freedesktop.portal.RemoteDesktop portal of version 2 or newer; uinput/ydotool are refused by policy (root, bypasses consent).",
    "wayland_capture_unavailable": "Wayland capture needs the ScreenCast portal or the grim tool; X11-only grabbers (mss, ImageGrab) do not work here.",
    "atspi_unavailable": "The accessibility-first route needs PyGObject with the AT-SPI typelib (gi.repository.Atspi).",
    "target_elevated": "The target window runs at a higher integrity level than Nerva; UIPI blocks it and Nerva refuses rather than escalate.",
    "desktop_dependency_unavailable": "An optional desktop library is not installed in the Nerva environment (pywinauto or uiautomation on Windows, pyobjc on macOS).",
    "local_vlm_not_proven_local": "A vision model is configured but does not resolve to a loopback base; screen bytes never leave the host, so the visual route stays off.",
}

_WAYLAND_INPUT_MIN_PORTAL_VERSION = 2
_PORTAL_PROBE_TIMEOUT_S = 3.0
_PORTAL_VERSION_RE = re.compile(r"(?:uint32\s+|^\s*u\s+)(\d+)")
_LIMITED_PORTAL_TEXT = 4096


class HostProbeError(RuntimeError):
    """Raised only for contract violations inside this module (never for host facts)."""


@dataclass(frozen=True)
class HostProbe:
    """One observe-only snapshot of what this host can honestly offer the operator.

    ``permissions`` values are tri-state: ``True`` / ``False`` are established
    facts, ``None`` means "could not be established without prompting or without
    a dependency that is absent" — never a guess.
    """

    platform: str
    deps: Mapping[str, bool]
    permissions: Mapping[str, Any]
    refusals: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    binaries: Mapping[str, bool] = field(default_factory=dict)
    flags: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise HostProbeError(f"unknown platform: {self.platform!r}")
        if tuple(self.deps.keys()) != DEP_NAMES:
            raise HostProbeError("deps must carry exactly DEP_NAMES in order")
        if any(type(v) is not bool for v in self.deps.values()):
            raise HostProbeError("deps values must be bool")
        unknown = set(self.refusals) - REFUSAL_REASONS
        if unknown:
            raise HostProbeError(f"refusal outside the vocabulary: {sorted(unknown)}")
        if len(set(self.refusals)) != len(self.refusals):
            raise HostProbeError("refusals must be unique")
        if any(not isinstance(w, str) or not w for w in self.warnings):
            raise HostProbeError("warnings must be non-empty strings")
        object.__setattr__(self, "deps", dict(self.deps))
        object.__setattr__(self, "permissions", dict(self.permissions))
        object.__setattr__(self, "binaries", dict(self.binaries))
        object.__setattr__(self, "flags", dict(self.flags))

    @property
    def ok(self) -> bool:
        """True when nothing in the closed vocabulary stands in the operator's way."""
        return not self.refusals

    def refuses(self, reason: str) -> bool:
        if reason not in REFUSAL_REASONS:
            raise HostProbeError(f"refusal outside the vocabulary: {reason!r}")
        return reason in self.refusals

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "deps": dict(self.deps),
            "permissions": dict(self.permissions),
            "refusals": list(self.refusals),
            "warnings": list(self.warnings),
            "binaries": dict(self.binaries),
            "flags": dict(self.flags),
            "ok": self.ok,
            "hints": {r: REFUSAL_HINTS.get(r, "") for r in self.refusals},
            "fingerprint": self.fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        """SHA-256 of the canonical JSON of the facts (not of hints or timestamps)."""
        facts = {
            "platform": self.platform,
            "deps": dict(self.deps),
            "permissions": dict(self.permissions),
            "refusals": list(self.refusals),
            "warnings": list(self.warnings),
            "binaries": dict(self.binaries),
            "flags": dict(self.flags),
        }
        canonical = json.dumps(facts, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── platform detection ──────────────────────────────────────────────────────


def detect_desktop_platform(
    env: Mapping[str, str] | None = None, sys_platform: str | None = None
) -> str:
    """Classify the session: windows | macos | linux-x11 | linux-wayland | headless.

    Wayland wins over X11 when both are visible (Xwayland exports ``DISPLAY``
    inside a Wayland session), so the input route is judged against the
    compositor that actually owns the seat.  Anything without a display server
    on a non-Windows, non-macOS box is ``headless`` — including this CI runner.
    """
    environ = os.environ if env is None else env
    plat = (sys_platform if sys_platform is not None else sys.platform).lower()
    if plat.startswith("win") or plat == "cygwin":
        return "windows"
    if plat == "darwin":
        return "macos"
    session = str(environ.get("XDG_SESSION_TYPE", "")).strip().lower()
    if session == "wayland" or environ.get("WAYLAND_DISPLAY"):
        return "linux-wayland"
    if session == "x11" or environ.get("DISPLAY"):
        return "linux-x11"
    return "headless"


# ── default OS calls (each lazy, each guarded, none prompting) ──────────────


def _ax_is_process_trusted() -> bool | None:
    """macOS: ``AXIsProcessTrustedWithOptions`` with the prompt option OFF."""
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
    except ImportError:
        return None
    try:
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: False}))
    except Exception:
        return None


def _cg_preflight_screen_capture() -> bool | None:
    """macOS: ``CGPreflightScreenCaptureAccess`` — the non-requesting check."""
    try:
        from Quartz import CGPreflightScreenCaptureAccess  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return bool(CGPreflightScreenCaptureAccess())
    except Exception:
        return None


def parse_portal_version(text: str) -> int | None:
    """Extract the ``version`` property from ``gdbus`` (``(<uint32 2>,)``) or ``busctl`` (``u 2``)."""
    if not isinstance(text, str):
        return None
    match = _PORTAL_VERSION_RE.search(text[:_LIMITED_PORTAL_TEXT])
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _portal_version_argv(tool: str) -> list[str]:
    if tool == "gdbus":
        return [
            "gdbus", "call", "--session",
            "--dest", "org.freedesktop.portal.Desktop",
            "--object-path", "/org/freedesktop/portal/desktop",
            "--method", "org.freedesktop.DBus.Properties.Get",
            "org.freedesktop.portal.RemoteDesktop", "version",
        ]
    return [
        "busctl", "--user", "get-property",
        "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.RemoteDesktop", "version",
    ]


def portal_remote_desktop_version(
    *,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., Any] = subprocess.run,
) -> int | None:
    """Read ``org.freedesktop.portal.RemoteDesktop.version`` over the session bus.

    A read-only property query, argv only, hard timeout, no shell.  ``None`` when
    there is no session bus, no D-Bus client tool, or the portal is absent — the
    caller treats ``None`` as "unknown", which for Wayland input means refuse.
    """
    environ = os.environ if env is None else env
    if not environ.get("DBUS_SESSION_BUS_ADDRESS") and not environ.get("XDG_RUNTIME_DIR"):
        return None
    for tool in ("gdbus", "busctl"):
        if not which(tool):
            continue
        try:
            proc = runner(
                _portal_version_argv(tool),
                capture_output=True,
                text=True,
                timeout=_PORTAL_PROBE_TIMEOUT_S,
                check=False,
            )
        except Exception:
            continue
        if getattr(proc, "returncode", 1) != 0:
            continue
        version = parse_portal_version(getattr(proc, "stdout", "") or "")
        if version is not None:
            return version
    return None


def _process_elevated() -> bool | None:
    """Is *this* process elevated (admin / root)?  Reported; never acted on."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        geteuid = getattr(os, "geteuid", None)
        return None if geteuid is None else geteuid() == 0
    except Exception:
        return None


def _uinput_writable() -> bool | None:
    """Linux: ``/dev/uinput`` writability — reported so the HUD can say it is *refused* by policy."""
    try:
        if not os.path.exists("/dev/uinput"):
            return False
        return os.access("/dev/uinput", os.W_OK)
    except Exception:
        return None


def _vlm_proven_local(env: Mapping[str, str] | None = None) -> bool | None:
    """``True``/``False`` for a configured VLM, ``None`` when none is configured."""
    try:
        from agents.core.llm.vlm import VLMNotConfigured, resolve_vlm_config
    except Exception:
        return None
    try:
        return resolve_vlm_config(env).is_local is True
    except VLMNotConfigured:
        return None
    except Exception:
        return None


def default_calls() -> dict[str, Callable[..., Any]]:
    """The OS-touching seams ``probe_host`` uses when nothing is injected."""
    return {
        "ax_is_process_trusted": _ax_is_process_trusted,
        "cg_preflight_screen_capture": _cg_preflight_screen_capture,
        "portal_remote_desktop_version": portal_remote_desktop_version,
        "process_elevated": _process_elevated,
        "uinput_writable": _uinput_writable,
        "vlm_proven_local": _vlm_proven_local,
        "which": shutil.which,
    }


# ── the probe ───────────────────────────────────────────────────────────────


def _dep_present(importer: Callable[[str], Any], module: str) -> bool:
    try:
        return importer(module) is not None
    except Exception:
        # find_spec raises for a broken parent package; that is "not usable".
        return False


def _safe_call(calls: Mapping[str, Callable[..., Any]], name: str, **kwargs) -> Any:
    fn = calls.get(name)
    if fn is None:
        return None
    try:
        return fn(**kwargs) if kwargs else fn()
    except Exception:
        return None


def _tri(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def probe_host(
    env: Mapping[str, str] | None = None,
    importer: Callable[[str], Any] | None = None,
    calls: Mapping[str, Callable[..., Any]] | None = None,
    *,
    sys_platform: str | None = None,
) -> HostProbe:
    """Build a :class:`HostProbe` for this (or an injected) host.

    ``env`` defaults to ``os.environ``; ``importer`` to ``importlib.util.find_spec``;
    ``calls`` to :func:`default_calls` (an injected mapping *replaces* it wholesale,
    so a test that passes ``calls={}`` sees every permission as unknown and no OS
    call at all).  Only the calls relevant to the detected platform are invoked.
    """
    environ = os.environ if env is None else env
    find = importlib.util.find_spec if importer is None else importer
    ops = default_calls() if calls is None else calls
    platform = detect_desktop_platform(environ, sys_platform)

    deps = {name: _dep_present(find, DEP_MODULES[name]) for name in DEP_NAMES}
    which = ops.get("which")
    binaries = {}
    for tool in BINARY_NAMES:
        try:
            binaries[tool] = bool(which(tool)) if callable(which) else False
        except Exception:
            binaries[tool] = False
    flags = {name: truthy(environ.get(name), False) for name in REPORTED_FLAGS}

    permissions: dict[str, Any] = {
        "accessibility_trusted": None,
        "screen_capture": None,
        "portal_remote_desktop_version": None,
        "xdg_session_type": str(environ.get("XDG_SESSION_TYPE", "")).strip().lower(),
        "process_elevated": None,
        "uinput_writable": None,
        "vlm_proven_local": None,
    }
    refusals: list[str] = []
    warnings: list[str] = []

    def refuse(reason: str) -> None:
        if reason not in refusals:
            refusals.append(reason)

    if platform == "headless":
        refuse("desktop_platform_unsupported")

    elif platform == "windows":
        if not (deps["pywinauto"] or deps["uiautomation"]):
            refuse("desktop_dependency_unavailable")
        permissions["process_elevated"] = _tri(_safe_call(ops, "process_elevated"))
        if permissions["process_elevated"] is True:
            warnings.append("process_elevated:nerva_runs_elevated")
        # Screen capture on Windows needs no permission; the grabber is a dep fact.
        if not deps["mss"]:
            warnings.append("capture_fallback:pil_imagegrab")

    elif platform == "macos":
        if not deps["pyobjc"]:
            refuse("desktop_dependency_unavailable")
        permissions["accessibility_trusted"] = _tri(_safe_call(ops, "ax_is_process_trusted"))
        permissions["screen_capture"] = _tri(_safe_call(ops, "cg_preflight_screen_capture"))
        if permissions["accessibility_trusted"] is False:
            refuse("accessibility_permission_missing")
        if permissions["screen_capture"] is False:
            refuse("screen_recording_permission_missing")
        if permissions["accessibility_trusted"] is None:
            warnings.append("accessibility_trusted:unknown")
        if permissions["screen_capture"] is None:
            warnings.append("screen_capture:unknown")

    else:  # linux-x11 / linux-wayland
        if not deps["gi_atspi"]:
            refuse("atspi_unavailable")
        permissions["process_elevated"] = _tri(_safe_call(ops, "process_elevated"))
        permissions["uinput_writable"] = _tri(_safe_call(ops, "uinput_writable"))
        if permissions["uinput_writable"] is True:
            warnings.append("uinput_writable:refused_by_policy")
        if platform == "linux-wayland":
            version = _safe_call(ops, "portal_remote_desktop_version", env=environ)
            try:
                version = None if version is None else int(version)
            except (TypeError, ValueError):
                version = None
            permissions["portal_remote_desktop_version"] = version
            if not deps["libei"] or version is None or version < _WAYLAND_INPUT_MIN_PORTAL_VERSION:
                refuse("wayland_input_unavailable")
            if version is None and not binaries["grim"]:
                refuse("wayland_capture_unavailable")
            if deps["mss"]:
                warnings.append("mss_present:x11_only_grabber")
        else:
            if not binaries["xdotool"]:
                warnings.append("x11_input_tool_missing:xdotool")
            if not deps["mss"]:
                warnings.append("capture_fallback:pil_imagegrab")

    if platform != "headless":
        permissions["vlm_proven_local"] = _tri(_safe_call(ops, "vlm_proven_local", env=environ))
        if permissions["vlm_proven_local"] is False:
            refuse("local_vlm_not_proven_local")

    return HostProbe(
        platform=platform,
        deps=deps,
        permissions=permissions,
        refusals=tuple(refusals),
        warnings=tuple(warnings),
        binaries=binaries,
        flags=flags,
    )


def desktop_operator_available(probe: HostProbe | None = None) -> bool:
    """One-word verdict for availability callbacks: can a desktop driver run here?

    ``local_vlm_not_proven_local`` alone does not veto the desktop route — it
    vetoes only the visual fallback — so it is excluded here.
    """
    p = probe if probe is not None else probe_host()
    blocking = set(p.refusals) - {"local_vlm_not_proven_local", "target_elevated"}
    return not blocking


__all__ = [
    "BINARY_NAMES",
    "DEP_MODULES",
    "DEP_NAMES",
    "HostProbe",
    "HostProbeError",
    "PLATFORMS",
    "REFUSAL_HINTS",
    "REFUSAL_REASONS",
    "REPORTED_FLAGS",
    "default_calls",
    "desktop_operator_available",
    "detect_desktop_platform",
    "parse_portal_version",
    "portal_remote_desktop_version",
    "probe_host",
]
