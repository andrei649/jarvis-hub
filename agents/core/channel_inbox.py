"""Bounded inbox store for live channel messages.

Safe Comms v0 deliberately scopes persistence to interactive channels whose
reply path is already real (web + telegram). Other channels can be added once
their send path is proven.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from agents.core.paths import data_path

from .persistence import JsonStore

DEFAULT_PATH = data_path("channel_inbox.json")
SUPPORTED_INBOX_CHANNELS = frozenset({"telegram", "web", "email"})
_MAX_TEXT = 4_000
_PREVIEW = 240
_REPLY_KEYS = {
    "telegram": ("chat_id",),
    "web": ("client_id",),
    # EmailChannel.send() kwargs; `to` is aliased from the inbound `from_addr`
    # in _reply_metadata (the reply target IS the inbound sender).
    "email": ("to", "subject"),
}


class ChannelInboxStore(JsonStore):
    def __init__(self, path: str | Path | None = DEFAULT_PATH, *,
                 max_messages: int = 500) -> None:
        self.max_messages = max(1, int(max_messages))
        super().__init__(path)

    def _serialize(self):
        return {"messages": self._messages}

    def _deserialize(self, raw) -> None:
        if isinstance(raw, dict):
            messages = raw.get("messages", [])
        elif isinstance(raw, list):
            messages = raw
        else:
            messages = []
        self._messages = [
            self._public(m) for m in messages if isinstance(m, dict)
        ][-self.max_messages:]

    def record_inbound(self, channel: str, text: str, *, sender: str = "",
                       metadata: dict | None = None, now: float | None = None) -> dict | None:
        channel = (channel or "").strip().lower()
        if channel not in SUPPORTED_INBOX_CHANNELS:
            return None
        return self._record(
            channel,
            text,
            direction="in",
            sender=sender,
            metadata=metadata,
            now=now,
        )

    def record_outbound(self, channel: str, text: str, *, thread_id: str,
                        reply_to: str = "", metadata: dict | None = None,
                        now: float | None = None) -> dict | None:
        channel = (channel or "").strip().lower()
        if channel not in SUPPORTED_INBOX_CHANNELS:
            return None
        return self._record(
            channel,
            text,
            direction="out",
            sender="jarvis",
            metadata=metadata,
            now=now,
            thread_id=thread_id,
            reply_to=reply_to,
        )

    def get_message(self, message_id: str) -> dict | None:
        with self._lock:
            for message in self._messages:
                if message.get("id") == message_id:
                    return dict(message)
        return None

    def messages(self, thread_id: str, *, limit: int = 50) -> list[dict]:
        n = max(1, int(limit or 50))
        with self._lock:
            items = [dict(m) for m in self._messages if m.get("thread_id") == thread_id]
        return items[-n:]

    def threads(self, *, limit: int = 50) -> list[dict]:
        n = max(1, int(limit or 50))
        grouped: dict[str, dict] = {}
        with self._lock:
            for message in self._messages:
                tid = message["thread_id"]
                row = grouped.setdefault(tid, {
                    "id": tid,
                    "thread_id": tid,
                    "channel": message["channel"],
                    "sender": message.get("sender", ""),
                    "from": message.get("sender", "") or message["channel"],
                    "subj": f"{message['channel']} thread",
                    "preview": "",
                    "ts": 0.0,
                    "count": 0,
                    "unread": False,
                    "reply": {},
                    "last_message_id": "",
                })
                row["count"] += 1
                if message["ts"] >= row["ts"]:
                    row.update({
                        "preview": message.get("preview", ""),
                        "ts": message["ts"],
                        "unread": message.get("direction") == "in",
                        "reply": dict(message.get("reply") or row.get("reply") or {}),
                        "last_message_id": message.get("id", ""),
                    })
        rows = sorted(grouped.values(), key=lambda r: r["ts"], reverse=True)
        return rows[:n]

    def thread(self, thread_id: str) -> dict | None:
        return next((t for t in self.threads(limit=self.max_messages)
                     if t["thread_id"] == thread_id), None)

    def stats(self) -> dict:
        """Inbox roll-up. `channels` is the supported VOCABULARY; `active_channels` and
        `by_channel` are what is actually stored.

        Those used to be one field: `channels` returned sorted(SUPPORTED_INBOX_CHANNELS), a
        module constant identical on every install. It looked like an answer to "which
        channels have traffic" and was not one — a box where email flows and a box where it
        was never configured rendered the same three words. The vocabulary is still worth
        publishing, so it keeps its key; the measurement is a separate field, and a
        supported-but-silent channel is ABSENT from it rather than reported as a zero.
        """
        threads = self.threads(limit=self.max_messages)
        by_channel: dict[str, int] = {}
        for m in self._messages:
            ch = str(m.get("channel") or "")
            if ch:
                by_channel[ch] = by_channel.get(ch, 0) + 1
        return {
            "enabled": True,
            "channels": sorted(SUPPORTED_INBOX_CHANNELS),
            "active_channels": sorted(by_channel),
            "by_channel": dict(sorted(by_channel.items())),
            "threads": len(threads),
            "messages": len(self._messages),
            "max_messages": self.max_messages,
        }

    def _record(self, channel: str, text: str, *, direction: str, sender: str = "",
                metadata: dict | None = None, now: float | None = None,
                thread_id: str = "", reply_to: str = "") -> dict:
        ts = time.time() if now is None else float(now)
        clean_text = str(text or "")[:_MAX_TEXT]
        reply = _reply_metadata(channel, metadata or {})
        sender = str(sender or _sender_from_metadata(channel, metadata or ""))
        thread_id = thread_id or _thread_id(channel, sender, reply)
        message_id = _message_id(channel, thread_id, direction, clean_text, ts)
        taint_fields = _taint_metadata(metadata or {})
        rec = self._public({
            "id": message_id,
            "thread_id": thread_id,
            "channel": channel,
            "direction": direction,
            "sender": sender,
            "text": clean_text,
            "preview": clean_text[:_PREVIEW],
            "reply": reply,
            "reply_to": reply_to,
            "ts": ts,
            **taint_fields,
        })
        with self._lock:
            self._messages.append(rec)
            self._messages = self._messages[-self.max_messages:]
            self._save()
        return dict(rec)

    @staticmethod
    def _public(message: dict) -> dict:
        out = {
            "id": str(message.get("id", "")),
            "thread_id": str(message.get("thread_id", "")),
            "channel": str(message.get("channel", "")),
            "direction": str(message.get("direction", "")),
            "sender": str(message.get("sender", "")),
            "text": str(message.get("text", ""))[:_MAX_TEXT],
            "preview": str(message.get("preview", ""))[:_PREVIEW],
            "reply": dict(message.get("reply") or {}),
            "reply_to": str(message.get("reply_to", "")),
            "ts": float(message.get("ts") or 0.0),
            "tainted": bool(message.get("tainted")),
            "taint_source": str(message.get("taint_source", "")),
            "injection_flags": _injection_flags(message.get("injection_flags")),
        }
        return out


def _reply_metadata(channel: str, metadata: dict[str, Any]) -> dict:
    out = {}
    meta = dict(metadata)
    if channel == "email" and not meta.get("to") and meta.get("from_addr"):
        meta["to"] = meta["from_addr"]
    for key in _REPLY_KEYS.get(channel, ()):
        value = meta.get(key)
        if isinstance(value, (str, int)) and str(value):
            out[key] = value
    return out


def _sender_from_metadata(channel: str, metadata: dict | str) -> str:
    if not isinstance(metadata, dict):
        return ""
    for key in ("sender", "sender_id", "user_id", "client_id", "chat_id", "from_addr"):
        value = metadata.get(key)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    return channel


def _taint_metadata(metadata: dict) -> dict:
    if not isinstance(metadata, dict):
        return {"tainted": False, "taint_source": "", "injection_flags": []}
    return {
        "tainted": bool(metadata.get("tainted")),
        "taint_source": str(metadata.get("taint_source", "")),
        "injection_flags": _injection_flags(metadata.get("injection_flags")),
    }


def _injection_flags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)][:20]


def _thread_id(channel: str, sender: str, reply: dict) -> str:
    stable = sender or reply.get("chat_id") or reply.get("client_id") or "unknown"
    digest = hashlib.sha256(f"{channel}:{stable}".encode()).hexdigest()[:12]
    return f"{channel}:{digest}"


def _message_id(channel: str, thread_id: str, direction: str, text: str, ts: float) -> str:
    digest = hashlib.sha256(
        f"{channel}:{thread_id}:{direction}:{ts}:{text}".encode(),
    ).hexdigest()
    return digest[:16]
