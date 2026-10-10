"""Bounded, read-only Claude Code/Codex JSONL extraction on the CLI host."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

SOURCES = {"claude": (".claude", "projects"), "codex": (".codex", "sessions")}
MAX_BYTES = 2 * 1024 * 1024
MAX_LINES = 2000
MAX_TURNS = 100


class ForeignSourceError(ValueError):
    pass


def _text(value) -> tuple[str, list[str]]:
    if isinstance(value, str):
        return value, []
    if not isinstance(value, list):
        return "", []
    text, tools = [], []
    for item in value:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"text", "input_text", "output_text"} and isinstance(item.get("text"), str):
            text.append(item["text"])
        elif item.get("type") in {"tool_use", "function_call"} and isinstance(item.get("name"), str):
            tools.append(item["name"][:64])
    return "\n".join(text), tools[:20]


def _row(source: str, value: dict) -> tuple[str, str, list[str], str | None] | None:
    if source == "claude":
        role = value.get("type")
        if role not in {"user", "assistant"}:
            return None
        message = value.get("message")
        if not isinstance(message, dict) or message.get("role") != role:
            return None
        content, tools = _text(message.get("content"))
        stamp = value.get("timestamp")
    else:
        if value.get("type") == "event_msg" and isinstance(value.get("payload"), dict):
            payload = value["payload"]
            role = {"user_message": "user", "agent_message": "assistant"}.get(payload.get("type"))
            content, tools = _text(payload.get("message"))
        elif value.get("type") == "response_item" and isinstance(value.get("payload"), dict):
            payload = value["payload"]
            if payload.get("type") == "message" and payload.get("role") in {"user", "assistant"}:
                role = payload["role"]
                content, tools = _text(payload.get("content"))
            elif payload.get("type") in {"function_call", "custom_tool_call"}:
                name = payload.get("name")
                if not isinstance(name, str) or not 0 < len(name) <= 64:
                    return None
                role, content, tools = "assistant", "", [name]
            else:
                return None
        else:
            return None
        stamp = value.get("timestamp")
    if role == "assistant" and not content.strip() and tools:
        content = "[tool calls: " + ", ".join(tools) + "]"
    if not role or not isinstance(content, str) or not content.strip() or len(content) > 32768:
        return None
    if not isinstance(stamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError:
        return None
    return role, content, tools, parsed.astimezone(UTC).isoformat()


def read_file(source: str, path: str | Path) -> dict:
    if source not in SOURCES:
        raise ForeignSourceError("unknown foreign source")
    candidate = Path(path).expanduser().absolute()
    if candidate.suffix != ".jsonl":
        raise ForeignSourceError("foreign source must be JSONL")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        if os.name == "posix":
            directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
            try:
                for part in candidate.parts[1:-1]:
                    opened = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    os.close(directory)
                    directory = opened
                fd = os.open(candidate.name, flags, dir_fd=directory)
            finally:
                os.close(directory)
        else:
            if any(part.is_symlink() for part in (candidate, *candidate.parents)):
                raise ForeignSourceError("symlinked foreign source")
            fd = os.open(candidate, flags)
    except OSError as exc:
        raise ForeignSourceError("foreign source unreadable") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise ForeignSourceError("foreign source exceeds bounds")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(fd)
        if (len(raw) > MAX_BYTES or len(raw) != before.st_size
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
            raise ForeignSourceError("foreign source changed")
    finally:
        os.close(fd)
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise ForeignSourceError("foreign source is not UTF-8") from exc
    if len(lines) > MAX_LINES:
        raise ForeignSourceError("foreign source exceeds bounds")
    turns = []
    external_id = candidate.stem[:128]
    previous = None
    for line in lines:
        if len(line) > 65536:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        if source == "claude" and isinstance(value.get("sessionId"), str):
            external_id = value["sessionId"][:128]
        if source == "codex" and value.get("type") == "session_meta":
            payload = value.get("payload")
            if isinstance(payload, dict) and isinstance(payload.get("id"), str):
                external_id = payload["id"][:128]
        parsed = _row(source, value)
        if parsed is None:
            continue
        role, content, tools, timestamp = parsed
        kind = value.get("type")
        if previous and previous[:2] == (role, content) and previous[2] != kind:
            # Codex rollout files mirror one utterance in event_msg and response_item.
            previous = role, content, kind
            continue
        row = {"role": role, "content": content, "timestamp": timestamp}
        if tools:
            row["tools"] = tools
        turns.append(row)
        previous = role, content, kind
        if len(turns) > MAX_TURNS:
            raise ForeignSourceError("foreign source exceeds turn bound")
    if not turns or not external_id:
        raise ForeignSourceError("no importable conversation turns")
    return {"source": source, "external_id": external_id, "turns": turns,
            "source_sha256": hashlib.sha256(raw).hexdigest()}


def discover(source: str, external_id: str | None = None, *, home: Path | None = None) -> Path:
    if source not in SOURCES or (external_id is not None and (not external_id or len(external_id) > 128)):
        raise ForeignSourceError("invalid foreign selector")
    root = (home or Path.home()).joinpath(*SOURCES[source])
    if not root.exists():
        raise ForeignSourceError("no foreign conversations found")
    files = sorted(root.rglob("*.jsonl"))
    if len(files) > MAX_LINES:
        raise ForeignSourceError("too many foreign conversations")
    if external_id is not None:
        found = []
        # Codex rollout filenames are only hints; session_meta.id is authoritative.
        # Claude filenames normally carry the ID, but the internal sessionId must
        # still agree before an explicit selector imports that file.
        candidates = files if source == "codex" else [path for path in files if path.stem == external_id]
        for path in candidates:
            try:
                if read_file(source, path)["external_id"] == external_id:
                    found.append(path)
            except ForeignSourceError:
                continue
    else:
        found = files
    if not found:
        raise ForeignSourceError("foreign conversation not found")
    if len(found) != 1:
        raise ForeignSourceError("foreign conversation ambiguous; use sessions import --from SOURCE PATH")
    return found[0]
