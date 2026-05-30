"""
parser_facebook.py — Parses Facebook Messenger JSON exports.

Expects directory structure:
  data/facebook/messages/inbox/<conversation>/message_1.json

JSON structure per Facebook DYI export:
  {
    "participants": [{"name": "..."}],
    "messages": [
      {
        "sender_name": "...",
        "timestamp_ms": 1234567890000,
        "content": "...",
        "type": "Generic",
        ...
      }
    ],
    "title": "Conversation title",
    ...
  }
"""

import json
import logging
from pathlib import Path
from typing import Generator

from .normalizer import NormalizedMessage

logger = logging.getLogger("jarvis.ingestion.facebook")


class FacebookParser:
    def __init__(self, my_name: str = "Andrei Tarcomnicu"):
        self.my_name = my_name
        self._name_variants: list[str] = []
        self._detect_name_variants()

    def _detect_name_variants(self):
        parts = self.my_name.lower().split()
        self._name_variants = [self.my_name.lower()]
        if len(parts) >= 2:
            self._name_variants.append(parts[0])
        if len(parts) >= 1:
            self._name_variants.append(parts[-1])

    def _is_me(self, sender_name: str) -> bool:
        return sender_name.lower().strip() in self._name_variants

    def parse_file(self, path: Path) -> list[NormalizedMessage]:
        messages = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError, PermissionError) as e:
            logger.warning(f"Failed to parse {path}: {e}")
            return messages

        inbox_name = path.parent.name if path.parent.name != "inbox" else path.parent.parent.name
        conversation_id = data.get("title", inbox_name)

        for msg in data.get("messages", []):
            text = msg.get("content", "").strip()
            if not text:
                continue
            if msg.get("type", "Generic") != "Generic":
                continue

            sender = msg.get("sender_name", "Unknown")
            messages.append(
                NormalizedMessage(
                    source="facebook",
                    conversation_id=conversation_id,
                    sender=sender,
                    is_me=self._is_me(sender),
                    text=text,
                    timestamp=msg.get("timestamp_ms", 0) / 1000.0,
                    metadata={
                        "type": msg.get("type", "Generic"),
                        "photos": len(msg.get("photos", [])),
                        "sticker": msg.get("sticker", None) is not None,
                    },
                )
            )

        logger.info(f"FB: {len(messages)} messages from '{conversation_id}'")
        return messages

    def parse_directory(self, inbox_dir: Path) -> Generator[NormalizedMessage, None, None]:
        if not inbox_dir.exists():
            logger.warning(f"FB inbox directory not found: {inbox_dir}")
            return

        for conv_dir in sorted(inbox_dir.iterdir()):
            if not conv_dir.is_dir():
                continue
            msg_file = conv_dir / "message_1.json"
            if not msg_file.exists():
                alt_files = list(conv_dir.glob("message_*.json"))
                if alt_files:
                    msg_file = alt_files[0]
                else:
                    continue
            yield from self.parse_file(msg_file)
