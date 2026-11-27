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

import contextlib
import re
from collections.abc import Callable
from typing import Any

from agents.core.desktop_operator import GovernedDesktop
from agents.core.kernel import (
    Action,
    Budget,
    Capability,
    Decision,
    Verdict,
    authorize,
    kernel_enabled,
)

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


def _emit_audit_event(audit: Any, event: str, payload: dict[str, Any], *, actor: str = "jarvis") -> None:
    """Best-effort structured audit emission supporting both AuditLogger.log and IntentLog.record."""
    if audit is None:
        return
    with contextlib.suppress(Exception):
        if callable(getattr(audit, "log", None)):
            audit.log(event, payload)
        elif callable(getattr(audit, "record", None)):
            audit.record(actor, event, str(payload.get("status") or event), payload)


class DesktopControl:
    """Allowlist planner composed with the H15.3 governed executor and Action Kernel.

    ``run`` rechecks each admitted plan against the bound ``ActionKernel`` (when provided
    or when ``JARVIS_ACTION_KERNEL`` is enabled), forwards permitted steps to
    ``GovernedDesktop`` (approval + injection guard), and emits structured audit entries
    for refused, kernel-denied, blocked, and executed steps; refused plans are dropped
    before they reach the desktop. Offline by default (``NullDesktopDriver``).
    """

    def __init__(
        self,
        governed: GovernedDesktop | None = None,
        *,
        kernel: Callable[[Action], Decision] | None = None,
        audit: Any = None,
        agent: str = "jarvis",
    ) -> None:
        self._gov = governed or GovernedDesktop()
        self._kernel = kernel
        self._audit = audit
        self._agent = agent

    @staticmethod
    def allowlist() -> dict:
        return allowlist()

    def _authorize_plan(self, planned: dict) -> Decision | None:
        if self._kernel is not None:
            step = planned["step"]
            act = Action(
                kind="desktop.control",
                agent=self._agent,
                title=str(planned.get("label") or step["action"]),
                payload={
                    "action": step["action"],
                    "args": dict(step.get("args") or {}),
                    "mutating": bool(planned.get("mutating", True)),
                },
            )
            return self._kernel(act)
        if kernel_enabled():
            step = planned["step"]
            act = Action(
                kind="desktop.control",
                agent=self._agent,
                title=str(planned.get("label") or step["action"]),
                payload={
                    "action": step["action"],
                    "args": dict(step.get("args") or {}),
                    "mutating": bool(planned.get("mutating", True)),
                },
            )
            return authorize(act, Capability(), Budget(), audit=self._audit)
        return None

    async def run(self, plans: list[dict], *, approver=None, screenshot_text: str = "") -> dict:
        """Execute the *admitted* plans through the Action Kernel and governed desktop.

        Returns the governed result plus the plans that were refused at the allowlist
        or denied by the Action Kernel (never silently dropped).
        """
        refused = [{"reason": p.get("reason")} for p in (plans or []) if not p.get("ok")]
        for item in refused:
            _emit_audit_event(
                self._audit,
                "desktop.control.refused",
                {"status": "refused", "reason": item["reason"]},
                actor=self._agent,
            )

        permitted_steps: list[dict] = []
        denied_entries: list[dict] = []
        queue_forced_actions: set[int] = set()

        for p in plans or []:
            if not p.get("ok"):
                continue
            step = p["step"]
            try:
                decision = self._authorize_plan(p)
            except Exception:
                decision = Decision(Verdict.DENY, reason="kernel_error")
            if decision is not None and decision.verdict is Verdict.DENY:
                reason = decision.reason or "kernel_denied"
                entry = {"action": step["action"], "status": "denied", "reason": reason}
                denied_entries.append(entry)
                _emit_audit_event(
                    self._audit,
                    "desktop.control.denied",
                    {
                        "status": "denied",
                        "action": step["action"],
                        "args": dict(step.get("args") or {}),
                        "reason": reason,
                    },
                    actor=self._agent,
                )
                continue
            idx = len(permitted_steps)
            permitted_steps.append(step)
            if decision is not None and decision.verdict is Verdict.QUEUE:
                queue_forced_actions.add(idx)

        step_index = 0

        def _effective_approver(action_name: str, action_args: dict) -> bool:
            if approver is None:
                return False
            return bool(approver(action_name, action_args))

        # If the kernel returned QUEUE on a read-only step, require explicit approver consent too.
        blocked_by_queue: list[dict] = []
        final_steps: list[dict] = []
        for idx, step in enumerate(permitted_steps):
            is_read_only = step["action"] in allowlist()["read_only"]
            if idx in queue_forced_actions and is_read_only and not _effective_approver(step["action"], dict(step.get("args") or {})):
                entry = {"action": step["action"], "status": "blocked", "reason": "kernel_queue_requires_approval"}
                blocked_by_queue.append(entry)
                _emit_audit_event(
                    self._audit,
                    "desktop.control.step",
                    {"status": "blocked", "action": step["action"], "args": dict(step.get("args") or {})},
                    actor=self._agent,
                )
            else:
                step_index += 1
                final_steps.append(step)

        if final_steps or not (denied_entries or blocked_by_queue):
            result = await self._gov.run(final_steps, screenshot_text=screenshot_text, approver=approver)
        else:
            result = {"ok": True, "ran": [], "stopped_early": False}

        for row in result.get("ran") or []:
            _emit_audit_event(
                self._audit,
                "desktop.control.step",
                {
                    "status": row.get("status", "unknown"),
                    "action": row.get("action"),
                },
                actor=self._agent,
            )

        if denied_entries or blocked_by_queue:
            result["ran"] = [*denied_entries, *blocked_by_queue, *(result.get("ran") or [])]
        if denied_entries:
            result["denied"] = denied_entries
        result["refused"] = refused
        return result
