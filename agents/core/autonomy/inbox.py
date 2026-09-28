"""
inbox.py — Decision Inbox helpers (H6.2).

Pure, network-free helpers for the Telegram decision inbox: build the inline
keyboard card for a blocked task, and parse the callback_data when the user
taps a button. The TelegramChannel uses these; keeping them pure makes the
decision UX testable without a live bot.

Four responses map onto the ambient-agent canon (accept / edit / respond /
ignore) surfaced as Aprob / Editez / Resping / Amân.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Tuple

# callback_data prefix; Telegram limits callback_data to 64 bytes.
CALLBACK_PREFIX = "aut"

# action → (button label, mapped status verb)
DECISION_ACTIONS = {
    "accept": "✅ Aprob",
    "edit": "✏️ Editez",
    "reject": "❌ Resping",
    "defer": "🕓 Amân",
}

_TIER_LABELS = {0: "read-only", 1: "reversibil", 2: "extern", 3: "ireversibil/bani"}


@dataclass(frozen=True)
class OwnerTaskRegistrationContext:
    """Internal admin-route provenance, outside every task/receipt/execution byte."""

    request_json: str

    @classmethod
    def from_request(cls, request: dict) -> OwnerTaskRegistrationContext | None:
        # Share the conservative JSON/authority-claim rules with action registrations.
        from .approval_grouping import _valid_json

        try:
            if not isinstance(request, dict) or not _valid_json(request):
                return None
            authority_keys = {'kernel_mediation', 'mediation_receipt', 'mediation_scope',
                              'mediation_policy_revision', 'mediation_enqueue_id', 'mediation_execution_id',
                              'kernel_intake_id', 'kernel_intake_evidence', 'approval_context', 'authorization'}

            def contains_authority(value):
                if isinstance(value, dict):
                    return any(key in authority_keys or contains_authority(child) for key, child in value.items())
                if isinstance(value, list):
                    return any(contains_authority(child) for child in value)
                return False

            if contains_authority(request):
                return None
            encoded = json.dumps(request, sort_keys=True, ensure_ascii=False,
                                 separators=(',', ':'), allow_nan=False)
            return cls(encoded) if len(encoded.encode('utf-8')) <= 65_536 else None
        except (TypeError, ValueError, RecursionError, UnicodeError):
            return None


def is_decision_notification_leader(queue, task) -> bool:
    """Suppress a pending follower before any delivery/budget/push bookkeeping."""
    task_id = task.get('id') if isinstance(task, dict) else task.id
    group = queue.pending_group(task_id)
    return group is None or group['leader_id'] == task_id


def build_decision_card(task, *, group: dict | None = None) -> dict:
    """Return a Telegram sendMessage body (text + inline keyboard) for a task.

    `task` is a queue.Task (or any object/dict with id/title/agent/kind/
    risk_tier/payload).
    """
    t = _as_dict(task)
    payload = t.get("payload") or {}
    tier = int(t.get("risk_tier", 3))
    lines = [
        f"🤖 *Decizie necesară* — `#{t['id']}`",
        f"*{_md(t.get('title', '(fără titlu)'))}*",
        f"Agent: `{_md(t.get('agent', '?'))}` · Acțiune: `{_md(t.get('kind', '?'))}`",
        f"Risc: *{_TIER_LABELS.get(tier, tier)}*",
    ]
    grouped_leader = (isinstance(group, dict) and group.get('leader_id') == t['id']
                      and type(group.get('count')) is int and group['count'] >= 2)
    if grouped_leader:
        lines.append(f"{group['count']} cereri identice; aprobarea se aplică doar acestei sarcini.")
    if payload.get("rationale"):
        lines.append(f"_De ce:_ {_md(str(payload['rationale']))}")
    if payload.get("expected"):
        lines.append(f"_Rezultat așteptat:_ {_md(str(payload['expected']))}")
    if payload.get("amount"):
        lines.append(f"_Sumă:_ {payload['amount']}")
    # Surface injection taint from untrusted-source tasks (e.g. transcripts) so the
    # human approving sees it — the gate stays human, but now it's informed.
    flags = payload.get("injection_flags") or []
    if flags:
        lines.append(f"⚠️ *Conținut suspect* (injection): {len(flags)} tipar(e) — verifică sursa înainte de aprobare.")
    elif payload.get("untrusted_source"):
        lines.append("_Sursă externă (neîncredere): conținut tratat ca date, nu instrucțiuni._")
    # H12.5: dry-run preview — show what the action would do before approval.
    try:
        from .dry_run import preview_task
        lines.append(f"_Preview:_ {_md(preview_task(t)['summary'])}")
    except Exception:
        pass

    keyboard = [[
        {"text": '✅ Aprob o dată' if grouped_leader and action == 'accept' else label,
         "callback_data": f"{CALLBACK_PREFIX}:{t['id']}:{action}"}
        for action, label in DECISION_ACTIONS.items()
    ]]
    return {
        "text": "\n".join(lines),
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": keyboard},
    }


def parse_callback_data(data: str) -> Optional[Tuple[int, str]]:
    """Parse `aut:<task_id>:<action>` → (task_id, action), or None if invalid."""
    if not data or not data.startswith(CALLBACK_PREFIX + ":"):
        return None
    parts = data.split(":")
    if len(parts) != 3:
        return None
    _, raw_id, action = parts
    if action not in DECISION_ACTIONS:
        return None
    try:
        return int(raw_id), action
    except ValueError:
        return None


# ── helpers ───────────────────────────────────────────────────────
def _as_dict(task) -> dict:
    if isinstance(task, dict):
        return task
    if hasattr(task, "to_dict"):
        return task.to_dict()
    return dict(getattr(task, "__dict__", {}))


def _md(text: str) -> str:
    """Escape the few Markdown chars that would break a Telegram message."""
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text
