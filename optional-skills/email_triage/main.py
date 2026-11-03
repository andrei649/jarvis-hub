"""
email_triage/main.py — Pepper's email triage skill (H2.2).

Loader-pattern skill that reads recent unread Gmail messages, prioritizes
them by VIP sender / urgency keywords / recency, and returns a formatted
Romanian-language summary with action suggestions.

Commands (see get_commands):
  triage [query]   — returns prioritized inbox summary
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("jarvis.skills.email_triage")

_gmail = None

VIP_SENDERS = [
    "family", "mama", "tata", "sora", "frate",
    "boss", "director", "ceo", "manager",
]
URGENT_KEYWORDS = [
    "urgent", "deadline", "asap", "critical", "important",
    "today", "azi", "mâine", "maine",
    "action required", "needs attention",
]


def _get_gmail():
    global _gmail
    if _gmail is None:
        try:
            from agents.core.plugins.gmail_plugin import GmailPlugin
        except ImportError:
            try:
                from core.plugins.gmail_plugin import GmailPlugin
            except ImportError:
                logger.warning("Gmail plugin not available")
                return None
        _gmail = GmailPlugin()
    return _gmail


def get_commands() -> list[str]:
    return ["triage"]


def _priority_score(msg: dict) -> int:
    """Compute priority score for a message. Higher = more important."""
    score = 0
    sender = (msg.get("from", "") or "").lower()
    subject = (msg.get("subject", "") or "").lower()
    snippet = (msg.get("snippet", "") or "").lower()
    combined = f"{subject} {snippet}"

    for vip in VIP_SENDERS:
        if vip in sender or vip in combined:
            score += 30
            break

    for kw in URGENT_KEYWORDS:
        if kw in combined:
            score += 20
            break

    date_str = msg.get("date", "") or ""
    try:
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%d %b %Y %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S%z",
        ):
            try:
                msg_date = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        else:
            msg_date = None
        if msg_date:
            age = datetime.now(timezone.utc) - msg_date
            if age < timedelta(hours=1):
                score += 15
            elif age < timedelta(hours=6):
                score += 10
            elif age < timedelta(hours=24):
                score += 5
    except Exception:
        pass

    return score


async def triage(args: str = "", context: dict = None) -> str:
    """Return prioritized inbox summary. Degrades gracefully if Gmail unavailable."""
    args = (args or "").strip()
    gmail = _get_gmail()

    if gmail is None:
        return ("📧 Triage email — Gmail indisponibil.\n"
                "Verifică token-ul OAuth sau conexiunea la internet.")

    try:
        query = f"is:unread {args}".strip()
        messages = await gmail.list_messages(max_results=20, query=query)
    except Exception as e:
        logger.warning(f"Triage Gmail error: {e}")
        return ("📧 Triage email — eroare la interogarea Gmail.\n"
                f"Detalii: {e}")

    if not messages:
        return "📧 Triage email — inbox-ul este gol. Nimic de prioritizat."

    if len(messages) == 1 and "error" in messages[0]:
        return f"📧 Triage email — eroare Gmail: {messages[0]['error']}"

    scored = []
    for msg in messages:
        score = _priority_score(msg)
        scored.append((score, msg))
    scored.sort(key=lambda x: x[0], reverse=True)

    lines = ["📧 Triage email — inbox priorizat:"]
    lines.append("")

    for i, (score, msg) in enumerate(scored):
        sender = msg.get("from", "necunoscut")
        subject = msg.get("subject", "(fără subiect)")
        snippet = (msg.get("snippet", "") or "")[:100]

        if score >= 50:
            prefix = "🔴"
            action = "necesită atenție imediată"
        elif score >= 30:
            prefix = "🟡"
            action = "de revăzut azi"
        elif score >= 15:
            prefix = "🟢"
            action = "poate aștepta"
        else:
            prefix = "⚪"
            action = "prioritate scăzută"

        lines.append(f"{prefix} [{score}] {subject}")
        lines.append(f"   De la: {sender}")
        if snippet:
            lines.append(f"   Preview: {snippet}")
        lines.append(f"   Acțiune: {action}")
        lines.append("")

    lines.append(f"Total: {len(scored)} mesaje necitite.")
    return "\n".join(lines)


async def handle(cmd: str, args: str, context: dict = None) -> str:
    if cmd == "triage":
        return await triage(args, context)
    return f"[email_triage] comandă necunoscută: {cmd}"
