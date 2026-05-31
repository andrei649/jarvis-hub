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


def build_decision_card(task) -> dict:
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
    if payload.get("rationale"):
        lines.append(f"_De ce:_ {_md(str(payload['rationale']))}")
    if payload.get("expected"):
        lines.append(f"_Rezultat așteptat:_ {_md(str(payload['expected']))}")
    if payload.get("amount"):
        lines.append(f"_Sumă:_ {payload['amount']}")

    keyboard = [[
        {"text": label, "callback_data": f"{CALLBACK_PREFIX}:{t['id']}:{action}"}
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
