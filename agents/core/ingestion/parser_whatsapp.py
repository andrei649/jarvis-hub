"""
parser_whatsapp.py — Parses WhatsApp exported .txt files.

WhatsApp export format (per chat):
  [12.05.2026, 14:32:21] Andrei: Salut, ce faci?
  [12.05.2026, 14:33:05] Alexandra: Bine, tu?

Date format varies by locale:
  - RO: [dd.mm.yyyy, hh:mm:ss]
  - EN: [m/d/yy, h:mm:ss AM/PM]
  - 24h: [dd.mm.yyyy, hh:mm:ss]
  - System messages: "... joined using this group's invite link"
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from agents.core.security import taint

from .normalizer import NormalizedMessage

logger = logging.getLogger("jarvis.ingestion.whatsapp")

# Common WhatsApp line patterns
WA_PATTERNS = [
    # [dd.mm.yyyy, hh:mm:ss] Sender: message  (RO/24h)
    re.compile(r"\[(\d{2})\.(\d{2})\.(\d{4}),\s*(\d{2}):(\d{2})(?::(\d{2}))?\]\s+([^:]+?):\s*(.+)"),
    # [m/d/yy, h:mm:ss AM/PM] Sender: message  (EN/12h)
    re.compile(r"\[(\d{1,2})/(\d{1,2})/(\d{2,4}),\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?\]\s+([^:]+?):\s*(.+)"),
    # [dd.mm.yyyy, hh:mm:ss] Sender: message (with seconds)
    re.compile(r"\[(\d{2})\.(\d{2})\.(\d{4}),\s*(\d{2}):(\d{2}):(\d{2})\]\s+([^:]+?):\s*(.+)"),
]

SYSTEM_MESSAGE_PATTERNS = [
    "joined using this group",
    "left using this group",
    "changed the group",
    "changed this group",
    "removed",
    "added",
    "Messages and calls are end-to-end encrypted",
    "security code changed",
    "created group",
]


def _is_system_message(text: str) -> bool:
    return any(p in text.lower() for p in SYSTEM_MESSAGE_PATTERNS)


def _parse_timestamp(pattern, match) -> Optional[float]:
    try:
        if pattern == 0:  # RO/24h: [dd.mm.yyyy, hh:mm:ss]
            dt = datetime(
                int(match.group(3)), int(match.group(2)), int(match.group(1)),
                int(match.group(4)), int(match.group(5)), int(match.group(6) or 0),
            )
        elif pattern == 1:  # EN/12h: [m/d/yy, h:mm:ss AM/PM]
            hour = int(match.group(4))
            minute = int(match.group(5))
            second = int(match.group(6) or 0)
            ampm = match.group(7)
            if ampm:
                if ampm.upper() == "PM" and hour < 12:
                    hour += 12
                elif ampm.upper() == "AM" and hour == 12:
                    hour = 0
            year_str = match.group(3)
            year = int(year_str) if len(year_str) == 4 else 2000 + int(year_str)
            dt = datetime(year, int(match.group(1)), int(match.group(2)), hour, minute, second)
        else:  # [dd.mm.yyyy, hh:mm:ss] with seconds
            dt = datetime(
                int(match.group(3)), int(match.group(2)), int(match.group(1)),
                int(match.group(4)), int(match.group(5)), int(match.group(6)),
            )
        return dt.timestamp()
    except (ValueError, IndexError):
        return None


class WhatsAppParser:
    def __init__(self, my_name: str = "Andrei"):
        self.my_name = my_name
        self._name_variants = [my_name.lower()]
        self._name_variants.append(my_name.lower().replace(" ", ""))

    def _is_me(self, sender: str) -> bool:
        return sender.lower().strip() in self._name_variants

    def parse_file(self, path: Path) -> list[NormalizedMessage]:
        messages = []
        if not path.exists():
            logger.warning(f"WA file not found: {path}")
            return messages

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read {path}: {e}")
            return messages

        conversation_id = path.stem

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            matched = False
            for i, pattern in enumerate(WA_PATTERNS):
                m = pattern.match(line)
                if m:
                    matched = True
                    break

            if not matched:
                continue

            if i == 0:
                sender = m.group(7)
                msg_text = m.group(8)
                ts = _parse_timestamp(0, m)
            elif i == 1:
                sender = m.group(8)
                msg_text = m.group(9)
                ts = _parse_timestamp(1, m)
            else:
                sender = m.group(7)
                msg_text = m.group(8)
                ts = _parse_timestamp(2, m)

            if ts is None:
                continue
            if _is_system_message(msg_text):
                continue

            is_me = self._is_me(sender)
            # TASK-3/H23.6: another person's message from an external chat export —
            # mark it so any action later built from it escalates through the
            # kernel instead of auto-executing. The owner's own messages stay
            # untainted.
            metadata = taint.mark({}, source="whatsapp") if not is_me else {}
            messages.append(
                NormalizedMessage(
                    source="whatsapp",
                    conversation_id=conversation_id,
                    sender=sender,
                    is_me=is_me,
                    text=msg_text,
                    timestamp=ts,
                    metadata=metadata,
                )
            )

        logger.info(f"WA: {len(messages)} messages from '{conversation_id}'")
        return messages

    def parse_directory(self, directory: Path) -> Generator[NormalizedMessage, None, None]:
        if not directory.exists():
            logger.warning(f"WA directory not found: {directory}")
            return

        for f in sorted(directory.glob("*.txt")):
            yield from self.parse_file(f)
