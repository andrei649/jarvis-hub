"""H427 — a fail-closed checkpoint before compaction discards a transcript.

When the context compressor summarises the middle of a conversation, the turns it evicts
leave the prompt for good; the conversation store keeps only the last ``memory.max_turns``.
Hermes lets memory providers mine those turns first (``on_pre_compress``) and, under
``compression.checkpoint_required``, refuses to compress unless one of them durably landed
them. Nerva does the same:

- **The hook.** :func:`run_checkpoint` is awaited by ``ContextCompressor.compress`` with
  exactly the turns about to be summarised away (``messages``) and the whole transcript
  (``evidence_messages``), before the summary is built. The contract is versioned: a provider
  declares ``checkpoint_api_version``, and only one at :data:`CHECKPOINT_API_VERSION` or above
  counts as a checkpoint. The optional keyword arguments are passed only when the provider's
  signature accepts them, so an older provider keeps working. A synchronous provider runs off
  the event loop and must return only once its write is durable.
- **The shipped provider.** :class:`TranscriptArchive` appends each evicted turn once (by its
  content hash) to a per-session JSONL file under the data folder, flushed and fsynced before
  it returns, so what a summary replaced can always be read back.
- **Fail closed.** With ``memory.compression_checkpoint_required`` on, a checkpoint provider
  that raises, or no checkpoint provider succeeding, aborts the compaction
  (:class:`CheckpointAborted`): the compressor keeps the uncompressed transcript, and a turn
  whose uncompressed prompt would not fit the model's window is refused instead of sent.
  With it off (the default), a failing provider is logged and compaction proceeds.
- **Audited.** Every checkpoint writes ``memory.precompress_checkpoint`` and every abort
  ``memory.precompress_abort`` to the signed intent log (turn counts, provider names and the
  reason — never the turns themselves).
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.memory.precompress")

CHECKPOINT_API_VERSION = 2
SETTING_REQUIRED = "memory.compression_checkpoint_required"
AUDIT_CHECKPOINT = "memory.precompress_checkpoint"
AUDIT_ABORT = "memory.precompress_abort"
_OPTIONAL_KWARGS = ("evidence_messages", "require_checkpoint", "checkpoint_api_version", "session_id")


class CheckpointAborted(RuntimeError):
    """A required pre-compression checkpoint did not land: keep the transcript uncompressed."""


def provider_name(provider: Any) -> str:
    return str(getattr(provider, "name", "") or type(provider).__name__)


def is_checkpoint_provider(provider: Any) -> bool:
    """Whether ``provider`` implements the current checkpoint contract."""
    version = getattr(provider, "checkpoint_api_version", 1)
    return isinstance(version, int) and version >= CHECKPOINT_API_VERSION   # True is 1: too old


def _accepted_kwargs(fn: Any, offered: dict) -> dict:
    """The subset of ``offered`` that ``fn``'s signature takes (all of it for ``**kwargs``)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(offered)
    return {k: v for k, v in offered.items() if k in params}


async def _call(provider: Any, messages: list, offered: dict) -> Any:
    hook = getattr(provider, "on_pre_compress", None)
    if not callable(hook):
        raise TypeError(f"{provider_name(provider)} has no on_pre_compress")
    kwargs = _accepted_kwargs(hook, offered)
    if inspect.iscoroutinefunction(hook):
        return await hook(messages, **kwargs)
    return await asyncio.to_thread(hook, messages, **kwargs)


def _audit(audit: Any, event: str, fields: dict) -> None:
    log = getattr(audit, "log", None)
    if not callable(log):
        return
    try:
        log(event, fields)
    except Exception:
        logger.warning("pre-compress checkpoint: the audit row could not be written", exc_info=True)


async def run_checkpoint(providers, messages: list, evidence_messages: list, *, required: bool,
                         session_id: str = "", audit: Any = None) -> dict:
    """Hand the turns about to be summarised away to every provider; raise
    :class:`CheckpointAborted` when ``required`` and no checkpoint landed."""
    messages = [dict(m) for m in (messages or [])]
    if not messages:
        return {"evicted": 0, "providers": [], "failed": []}
    offered = {
        "evidence_messages": [dict(m) for m in (evidence_messages or [])],
        "require_checkpoint": bool(required),
        "checkpoint_api_version": CHECKPOINT_API_VERSION,
        "session_id": session_id,
    }
    landed: list[str] = []
    failed: list[str] = []
    for provider in list(providers or []):
        name = provider_name(provider)
        counts = is_checkpoint_provider(provider)
        try:
            await _call(provider, messages, offered)
        except Exception as exc:
            failed.append(name)
            if required and counts:
                reason = f"{name} failed the pre-compress checkpoint: {type(exc).__name__}"
                _audit(audit, AUDIT_ABORT, {"session": session_id, "evicted": len(messages),
                                            "provider": name, "reason": reason, "required": True})
                logger.error("pre-compress checkpoint: %s; the transcript stays uncompressed", reason)
                raise CheckpointAborted(reason) from exc
            logger.warning("pre-compress checkpoint: %s failed (%s)", name, type(exc).__name__)
            continue
        if counts:
            landed.append(name)
    if required and not landed:
        reason = f"No active memory provider completed pre-compress checkpoint API v{CHECKPOINT_API_VERSION}"
        _audit(audit, AUDIT_ABORT, {"session": session_id, "evicted": len(messages),
                                    "provider": "", "reason": reason, "required": True})
        logger.error("pre-compress checkpoint: %s; the transcript stays uncompressed", reason)
        raise CheckpointAborted(reason)
    _audit(audit, AUDIT_CHECKPOINT, {"session": session_id, "evicted": len(messages),
                                     "providers": landed, "failed": failed, "required": bool(required)})
    return {"evicted": len(messages), "providers": landed, "failed": failed}


# ── the shipped provider ─────────────────────────────────────────────────────────

def turn_id(turn: dict) -> str:
    """A stable identity for one turn: its speaker, time and content."""
    content = turn.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, sort_keys=True, default=str)
    raw = json.dumps([str(turn.get("role") or ""), str(turn.get("agent_id") or ""),
                      str(turn.get("timestamp") or ""), content], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _archived_content(content: Any) -> str:
    if isinstance(content, str):
        return "[image]" if content.startswith("data:image/") else content
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(content)


class TranscriptArchive:
    """Append each evicted turn once to ``<root>/<session hash>.jsonl``, fsynced before returning."""

    name = "transcript_archive"
    checkpoint_api_version = CHECKPOINT_API_VERSION

    def __init__(self, root: str | Path | None = None) -> None:
        if root is None:
            from agents.core.paths import data_path
            root = data_path("compaction_archive")
        self.root = Path(root)
        self._seen: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    def path_for(self, session_id: str) -> Path:
        digest = hashlib.sha256(str(session_id or "default").encode()).hexdigest()[:32]
        return self.root / f"{digest}.jsonl"

    def _known(self, path: Path) -> set[str]:
        key = str(path)
        if key not in self._seen:
            seen: set[str] = set()
            if path.exists():
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            seen.add(str(json.loads(line)["id"]))
                        except (ValueError, KeyError, TypeError):
                            continue
            self._seen[key] = seen
        return self._seen[key]

    def on_pre_compress(self, messages: list, *, session_id: str = "", **_kwargs: Any) -> dict:
        path = self.path_for(session_id)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            seen = self._known(path)
            fresh = []
            for turn in messages or []:
                tid = turn_id(turn)
                if tid in seen or any(tid == r["id"] for r in fresh):
                    continue
                fresh.append({
                    "id": tid,
                    "session": str(session_id or ""),
                    "role": str(turn.get("role") or ""),
                    "agent_id": str(turn.get("agent_id") or ""),
                    "timestamp": turn.get("timestamp"),
                    "content": _archived_content(turn.get("content", "")),
                    "archived_at": time.time(),
                })
            if fresh:
                with path.open("a", encoding="utf-8") as handle:
                    for record in fresh:
                        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                seen.update(r["id"] for r in fresh)
        return {"archived": len(fresh), "known": len(seen)}

    def read(self, session_id: str) -> list[dict]:
        """The archived turns of a session, oldest first."""
        path = self.path_for(session_id)
        if not path.exists():
            return []
        out = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    out.append(record)
        return out


_default: list[Any] | None = None
_default_lock = threading.Lock()


def default_providers() -> list[Any]:
    """The providers a hub runs when none were registered: the transcript archive."""
    global _default
    with _default_lock:
        if _default is None:
            _default = [TranscriptArchive()]
        return list(_default)


def set_default_providers(providers: list[Any] | None) -> None:
    """Swap the default providers (tests; ``None`` rebuilds them on next use)."""
    global _default
    with _default_lock:
        _default = None if providers is None else list(providers)


__all__ = [
    "AUDIT_ABORT", "AUDIT_CHECKPOINT", "CHECKPOINT_API_VERSION", "CheckpointAborted", "SETTING_REQUIRED",
    "TranscriptArchive", "default_providers", "is_checkpoint_provider", "run_checkpoint",
    "set_default_providers", "turn_id",
]
