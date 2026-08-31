"""desktop_control.py — 0.25 Desktop Control Pack (app-launch + OS-action allowlist core).

`GovernedDesktop` (H15.3, `desktop_operator.py`) already gates *how* a desktop step runs —
read-only inline, mutating held for approval, hostile-UI injection aborts. What it does not
answer is *what may be launched or controlled at all*. This pack is that missing front door:
a strict, pure **allowlist** that turns a high-level request ("open the browser", "mute",
"start recording") into a governed desktop **step** — and refuses anything not explicitly on
the list, honestly, with a reason.

Security-critical design:

* **Allowlist, not passthrough.** Apps are named by a **canonical key** (``browser``,
  ``terminal``, ``editor`` …), never a binary path or shell string. The host owns the
  key→launcher map (an OS/deployment seam); the pack can therefore never be turned into an
  arbitrary-execution vector — a caller-supplied path or ``rm -rf`` simply isn't an allowlist
  key and is refused. As defense-in-depth the key is also rejected if it carries a path
  separator or shell metacharacter.
* **Validated OS actions.** Volume/brightness take a clamped 0–100 level; unknown actions or
  out-of-range values are refused, not coerced into something surprising.
* **Recording is consent-flagged.** Screen recording captures everything visible, so it is
  always mutating + approval-gated and carries an explicit privacy note; it is never started
  implicitly.
* **Plans, never actions.** Every entry point returns a plan (or a refusal). Execution goes
  through the injected `GovernedDesktop` (approval + injection guard); the pack itself performs
  no desktop I/O. Pure, deterministic, offline-testable.
"""

from __future__ import annotations

import re

from agents.core.desktop_operator import GovernedDesktop

# Canonical launchable apps → display metadata only. The host resolves the key to a vetted
# launcher; the pack never stores or emits a binary path (that is the arbitrary-exec seam).
APPS: dict[str, dict] = {
    "browser":  {"label": "Web browser"},
    "terminal": {"label": "Terminal"},
    "editor":   {"label": "Code editor"},
    "files":    {"label": "File manager"},
    "music":    {"label": "Music player"},
    "mail":     {"label": "Mail client"},
    "calendar": {"label": "Calendar"},
    "notes":    {"label": "Notes"},
    "settings": {"label": "System settings"},
}

# OS control actions. `arg` names the single validated parameter (None = no parameter);
# `level` params clamp to 0–100. `screenshot` is the only read-only one (runs inline).
_PCT = "pct"
OS_ACTIONS: dict[str, dict] = {
    "volume_set":     {"arg": "level", "validate": _PCT, "mutating": True},
    "volume_mute":    {"arg": "on", "validate": "bool", "mutating": True},
    "brightness_set": {"arg": "level", "validate": _PCT, "mutating": True},
    "media_playpause": {"arg": None, "validate": None, "mutating": True},
    "media_next":     {"arg": None, "validate": None, "mutating": True},
    "media_prev":     {"arg": None, "validate": None, "mutating": True},
    "lock_screen":    {"arg": None, "validate": None, "mutating": True},
    "sleep_display":  {"arg": None, "validate": None, "mutating": True},
    "screenshot":     {"arg": None, "validate": None, "mutating": False},
}

RECORDING_OPS: tuple[str, ...] = ("start", "stop")

_APP_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")   # keys only — no paths, no shell


def _refuse(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def _step(action: str, args: dict, *, mutating: bool, label: str, **extra) -> dict:
    return {"ok": True, "step": {"action": action, "args": args},
            "mutating": mutating, "requires_approval": mutating, "label": label, **extra}


def plan_launch(app: str) -> dict:
    """Plan a governed app launch, or refuse if the app is not allowlisted."""
    key = str(app or "").strip().lower()
    if not _APP_KEY_RE.match(key):
        return _refuse(f"not an app key: {app!r}")          # a path/shell string never matches
    if key not in APPS:
        return _refuse(f"app not on allowlist: {key}")
    return _step("launch", {"app": key, "target": "desktop"},
                 mutating=True, label=f"Launch {APPS[key]['label']}")


def _validate_arg(spec: dict, value) -> tuple[bool, object]:
    kind = spec["validate"]
    if kind is None:
        return True, None
    if kind == _PCT:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return False, None
        if not 0 <= n <= 100:
            return False, None
        return True, n
    if kind == "bool":
        if not isinstance(value, bool):
            return False, None
        return True, value
    return False, None


def plan_os_action(action: str, value=None) -> dict:
    """Plan a validated OS-control action, or refuse (unknown action / bad parameter)."""
    key = str(action or "").strip().lower()
    spec = OS_ACTIONS.get(key)
    if spec is None:
        return _refuse(f"os action not on allowlist: {key}")
    args: dict = {"target": "desktop"}
    if spec["arg"] is not None:
        ok, coerced = _validate_arg(spec, value)
        if not ok:
            return _refuse(f"invalid value for {key}: {value!r}")
        args[spec["arg"]] = coerced
    return _step(key, args, mutating=spec["mutating"], label=key.replace("_", " "))


def plan_recording(op: str) -> dict:
    """Plan a screen-recording start/stop — always consent-flagged + approval-gated."""
    key = str(op or "").strip().lower()
    if key not in RECORDING_OPS:
        return _refuse(f"unknown recording op: {op!r} (expected start/stop)")
    return _step("record", {"op": key, "target": "desktop"}, mutating=True,
                 label=f"{key.capitalize()} screen recording",
                 privacy="screen recording captures everything visible — held for explicit "
                         "approval, never started automatically")


def allowlist() -> dict:
    """The full inspectable surface — what this pack will and won't plan."""
    return {
        "apps": sorted(APPS),
        "os_actions": sorted(OS_ACTIONS),
        "read_only": sorted(a for a, s in OS_ACTIONS.items() if not s["mutating"]),
        "recording": list(RECORDING_OPS),
    }


def plan(kind: str, **kwargs) -> dict:
    """Dispatch one high-level request to the right planner (DRA-43).

    One dispatcher so the HTTP surface and the ToolRPC tool cannot disagree
    about what is allowlisted.

    Execution note: an admitted plan runs through ``DesktopControl.run`` →
    ``GovernedDesktop.run``, which is the composition this pack documents and
    ships. It is NOT interchangeable with POSTing the step to
    ``/api/desktop/run``: that route validates through
    ``desktop_operator.validate_desktop_run_args``, whose per-action rules allow
    no argument beyond the ones they name, so the ``target: "desktop"`` every
    step here carries is refused as ``unexpected_action_args`` — and the
    volume/brightness/media/lock/sleep and ``record`` actions have no rule at
    all. ``tests/test_desktop_control.py`` pins that gap so it stays visible.
    """
    key = str(kind or "").strip().lower()
    if key == "launch":
        return plan_launch(kwargs.get("app"))
    if key == "os_action":
        return plan_os_action(kwargs.get("action"), kwargs.get("value"))
    if key == "recording":
        return plan_recording(kwargs.get("op"))
    return _refuse(f"unknown plan kind: {key!r} (expected launch/os_action/recording)")


class DesktopControl:
    """Allowlist planner composed with the H15.3 governed executor.

    ``run`` forwards the planned steps to `GovernedDesktop` (approval + injection guard);
    refused plans are dropped before they reach the desktop. Offline by default
    (`NullDesktopDriver`); a real VM/desktop driver is the host seam.
    """

    def __init__(self, governed: GovernedDesktop | None = None) -> None:
        self._gov = governed or GovernedDesktop()

    @staticmethod
    def allowlist() -> dict:
        return allowlist()

    async def run(self, plans: list[dict], *, approver=None, screenshot_text: str = "") -> dict:
        """Execute the *admitted* plans through the governed desktop. Returns the governed
        result plus the plans that were refused at the allowlist (never silently dropped)."""
        steps = [p["step"] for p in (plans or []) if p.get("ok")]
        refused = [{"reason": p.get("reason")} for p in (plans or []) if not p.get("ok")]
        result = await self._gov.run(steps, screenshot_text=screenshot_text, approver=approver)
        result["refused"] = refused
        return result
