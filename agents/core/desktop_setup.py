"""Turn the host probe's facts into the ordered path from install to first click.

The desktop operator is built — governed drivers for Windows, macOS and X11 /
Wayland, a visual-grounding fallback, an injection classifier — and
``host_probe.py`` already establishes, honestly and tri-state, what this machine
can offer it. What has never existed is the part a *person* uses: the inventory
row for this capability (H044) says it plainly — "Nerva builds its own governed
drivers rather than shelling to a third-party binary, but there is no
permission-grant UX". A refusal vocabulary the owner cannot read, in an order
they cannot act on, is not a setup path.

This module is that path, and nothing else:

- **Ordered, because the order is the information.** Dependencies come before
  the permissions those dependencies are needed to even *ask* about; a display
  comes before both. Reporting them as an unordered bag invites the owner to
  fight step four while step one is what is actually blocking them.
- **It reports; it never grants.** No operating system lets a process award
  itself Accessibility or Screen Recording, and a module that pretended
  otherwise would be lying in the one place the product sells honesty.
  :func:`open_settings` opens the OS pane where the human does it, then the
  caller re-probes: the new facts are the proof, never this module's say-so.
- **The openers are a closed table.** ``_OPENERS`` is a module constant of
  fixed argv; nothing from the probe, a caller, a setting or a model is ever
  interpolated into one, and :func:`open_settings` refuses any ``Opener`` that
  is not identically one of its own values. That keeps "put the owner in front
  of the right pane" from quietly becoming a launch-anything seam.
- **Pure.** :func:`plan` touches no OS, so the whole path is offline-testable
  against a synthetic :class:`~agents.core.host_probe.HostProbe`.

An unknown is never rendered as a yes. A step whose fact the probe could not
establish reports ``unknown`` with the reason it could not, because "we could
not tell" and "you are ready" are different answers to the owner's question.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .host_probe import REFUSAL_HINTS, HostProbe

READY = "ready"
BLOCKED = "blocked"
UNKNOWN = "unknown"
NOT_APPLICABLE = "not_applicable"
STATES = frozenset({READY, BLOCKED, UNKNOWN, NOT_APPLICABLE})

# Which optional libraries each platform's driver actually needs. A platform
# absent here has no dependency step rather than a vacuously satisfied one.
PLATFORM_DEPS: Mapping[str, tuple[str, ...]] = {
    "windows": ("pywinauto", "uiautomation"),
    "macos": ("pyobjc",),
    "linux-x11": ("gi_atspi",),
    "linux-wayland": ("gi_atspi", "libei"),
}

DRIVER_PLATFORMS = frozenset(PLATFORM_DEPS)


@dataclass(frozen=True)
class Opener:
    """A fixed way to put the owner in front of one OS pane. Never built at runtime."""

    argv: tuple[str, ...]
    label: str


# The closed table. Adding a row is a code change that a reviewer sees; there is
# deliberately no path that composes one from a string a caller supplies.
_OPENERS: Mapping[str, Opener] = {
    "macos.accessibility": Opener(
        argv=(
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ),
        label="System Settings → Privacy & Security → Accessibility",
    ),
    "macos.screen_recording": Opener(
        argv=(
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        ),
        label="System Settings → Privacy & Security → Screen Recording",
    ),
}


@dataclass(frozen=True)
class Step:
    """One thing that must be true before the operator can run, and its state."""

    key: str
    title: str
    state: str
    detail: str
    hint: str = ""
    opener: Opener | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.title:
            raise ValueError("a step needs a key and a title")
        if self.state not in STATES:
            raise ValueError(f"state must be one of {sorted(STATES)}")

    @property
    def blocking(self) -> bool:
        return self.state == BLOCKED

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "state": self.state,
            "detail": self.detail,
            "hint": self.hint,
            "opener": self.opener.label if self.opener is not None else "",
        }


@dataclass(frozen=True)
class SetupPlan:
    """The ordered path for this host. ``ready`` only when nothing is unresolved."""

    platform: str
    steps: tuple[Step, ...]

    @property
    def ready(self) -> bool:
        """True only when every step is settled in the owner's favour.

        An ``unknown`` step keeps this False on purpose: the probe could not
        establish the fact, and reporting readiness on a fact nobody
        established is exactly the silent downgrade the operator refuses.
        """
        return all(step.state in (READY, NOT_APPLICABLE) for step in self.steps)

    @property
    def blocking(self) -> Step | None:
        """The first step the owner should act on, or ``None``."""
        for step in self.steps:
            if step.state in (BLOCKED, UNKNOWN):
                return step
        return None

    @property
    def unresolved(self) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.state in (BLOCKED, UNKNOWN))

    def step(self, key: str) -> Step | None:
        for candidate in self.steps:
            if candidate.key == key:
                return candidate
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "ready": self.ready,
            "steps": [s.to_dict() for s in self.steps],
            "blocking": self.blocking.key if self.blocking else "",
        }


def _tri_step(
    key: str,
    title: str,
    value: Any,
    *,
    reason: str,
    blocked_detail: str,
    ready_detail: str,
    unknown_detail: str,
    opener: Opener | None = None,
) -> Step:
    """Map one tri-state probe fact onto a step, never collapsing None into False."""
    if value is True:
        return Step(key, title, READY, ready_detail)
    if value is False:
        return Step(key, title, BLOCKED, blocked_detail,
                    hint=REFUSAL_HINTS.get(reason, ""), opener=opener)
    return Step(key, title, UNKNOWN, unknown_detail,
                hint=REFUSAL_HINTS.get(reason, ""), opener=opener)


def plan(probe: HostProbe) -> SetupPlan:
    """Build the ordered setup path for the host this probe describes."""
    if not isinstance(probe, HostProbe):
        raise TypeError("plan() needs a HostProbe")
    platform = probe.platform
    deps = dict(probe.deps)
    perms = dict(probe.permissions)
    steps: list[Step] = []

    # 1. A graphical session. Nothing below it is worth reporting without one.
    if platform in DRIVER_PLATFORMS:
        steps.append(Step(
            "display", "A graphical session", READY,
            f"detected: {platform}",
        ))
    else:
        return SetupPlan(platform, (Step(
            "display", "A graphical session", BLOCKED,
            f"no usable desktop session detected ({platform})",
            hint=REFUSAL_HINTS["desktop_platform_unsupported"],
        ),))

    # 2. The driver libraries for this platform. Windows takes either adapter.
    required = PLATFORM_DEPS[platform]
    present = [name for name in required if deps.get(name)]
    satisfied = bool(present) if platform == "windows" else all(
        deps.get(name) for name in required
    )
    steps.append(Step(
        "dependencies", "The driver libraries", READY if satisfied else BLOCKED,
        ("installed: " + ", ".join(present)) if satisfied
        else "missing: " + ", ".join(n for n in required if not deps.get(n)),
        hint="" if satisfied else REFUSAL_HINTS["desktop_dependency_unavailable"],
    ))

    # 3–4. The OS grants. Only macOS has a permission a human must award; the
    # others have a capability that is either present or not, which is a
    # different question and is reported as one.
    if platform == "macos":
        steps.append(_tri_step(
            "accessibility", "Accessibility permission",
            perms.get("accessibility_trusted"),
            reason="accessibility_permission_missing",
            ready_detail="granted to this process",
            blocked_detail="not granted to this process",
            unknown_detail="could not be established without prompting",
            opener=_OPENERS["macos.accessibility"],
        ))
        steps.append(_tri_step(
            "screen_recording", "Screen Recording permission",
            perms.get("screen_capture"),
            reason="screen_recording_permission_missing",
            ready_detail="granted to this process",
            blocked_detail="not granted to this process",
            unknown_detail="could not be established without prompting",
            opener=_OPENERS["macos.screen_recording"],
        ))
    elif platform == "linux-wayland":
        # The probe already established both of these against the portal and the
        # host's binaries; re-deriving them here would be a second, weaker copy
        # of that logic. (It would also be wrong in a way worth naming: mss is an
        # X11-only grabber, so "mss is installed" is not a Wayland capture route.)
        refusals = set(probe.refusals)
        version = perms.get("portal_remote_desktop_version")
        input_ok = "wayland_input_unavailable" not in refusals
        steps.append(Step(
            "wayland_input", "Wayland input portal",
            READY if input_ok else BLOCKED,
            f"RemoteDesktop portal version {version}" if isinstance(version, int)
            else "no usable RemoteDesktop portal",
            hint="" if input_ok else REFUSAL_HINTS["wayland_input_unavailable"],
        ))
        capture_ok = "wayland_capture_unavailable" not in refusals
        steps.append(Step(
            "wayland_capture", "Wayland screen capture",
            READY if capture_ok else BLOCKED,
            "a portal or grim capture route is available" if capture_ok
            else "neither the ScreenCast portal nor grim was found",
            hint="" if capture_ok else REFUSAL_HINTS["wayland_capture_unavailable"],
        ))
    else:
        steps.append(Step(
            "os_permission", "An OS permission grant", NOT_APPLICABLE,
            "this platform has no grant for the owner to award",
        ))

    # 5. Elevation. Nerva refuses to escalate, so a raised target is the owner's
    #    to lower, not the product's to work around.
    elevated = perms.get("process_elevated")
    if elevated is True:
        steps.append(Step(
            "elevation", "No elevation mismatch", BLOCKED,
            "running elevated; Nerva refuses rather than escalate around UIPI",
            hint=REFUSAL_HINTS["target_elevated"],
        ))
    elif elevated is False:
        steps.append(Step("elevation", "No elevation mismatch", READY, "running unelevated"))
    else:
        steps.append(Step(
            "elevation", "No elevation mismatch", UNKNOWN,
            "could not be established", hint=REFUSAL_HINTS["target_elevated"],
        ))

    return SetupPlan(platform, tuple(steps))


def open_settings(step: Step, *, spawn) -> dict[str, Any]:
    """Open the OS pane for ``step``; the owner grants, this never does.

    ``spawn`` is injected (``subprocess.run``-shaped) so the whole path stays
    testable without launching anything. The refusal below is the load-bearing
    line: only an ``Opener`` that is identically one of ``_OPENERS``' own values
    is ever executed, so a forged or caller-built one cannot ride this seam into
    a process launch.
    """
    if not isinstance(step, Step):
        raise TypeError("open_settings() needs a Step")
    opener = step.opener
    if opener is None:
        return {"ok": False, "reason": "no_opener_for_step", "step": step.key}
    if not any(opener is known for known in _OPENERS.values()):
        return {"ok": False, "reason": "opener_not_in_table", "step": step.key}
    try:
        spawn(list(opener.argv))
    except FileNotFoundError:
        return {"ok": False, "reason": "opener_not_found", "step": step.key}
    except OSError:
        return {"ok": False, "reason": "opener_failed", "step": step.key}
    # Deliberately not "granted": opening a pane proves nothing about the grant.
    return {"ok": True, "opened": opener.label, "step": step.key,
            "note": "re-run the probe; the new facts are the proof, not this call"}


def render(report: SetupPlan) -> str:
    """One screen a person can act on: the state, then the first thing to do."""
    if not isinstance(report, SetupPlan):
        raise TypeError("render() needs a SetupPlan")
    marks = {READY: " ok ", BLOCKED: "STOP", UNKNOWN: "  ? ", NOT_APPLICABLE: " -- "}
    lines = [f"desktop operator on {report.platform}: "
             + ("ready" if report.ready else "not ready")]
    lines.append("")
    label_width = max((len(s.title) for s in report.steps), default=0)
    for step in report.steps:
        lines.append(f"  {marks[step.state]}  {step.title.ljust(label_width)}  {step.detail}")
    blocking = report.blocking
    if blocking is not None:
        lines.append("")
        lines.append(f"next: {blocking.title}")
        if blocking.hint:
            lines.append(f"  {blocking.hint}")
        if blocking.opener is not None:
            lines.append(f"  open it with: nerva desktop grant {blocking.key}")
            lines.append(f"  or by hand:   {blocking.opener.label}")
    return "\n".join(lines) + "\n"


def openers_for(keys: Sequence[str] = ()) -> dict[str, Opener]:
    """The closed opener table, or the named subset of it. Read-only view."""
    if not keys:
        return dict(_OPENERS)
    return {k: v for k, v in _OPENERS.items() if k in set(keys)}


__all__ = [
    "BLOCKED",
    "DRIVER_PLATFORMS",
    "NOT_APPLICABLE",
    "Opener",
    "PLATFORM_DEPS",
    "READY",
    "STATES",
    "SetupPlan",
    "Step",
    "UNKNOWN",
    "open_settings",
    "openers_for",
    "plan",
    "render",
]
