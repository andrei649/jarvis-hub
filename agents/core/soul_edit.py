"""H156 — one path that makes an edited persona live.

The prompt editor (H10.22) versioned SOUL text in the SoulVersionStore, and nothing wrote
it where the model reads it: a commit or a rollback changed a JSON history while the
agent kept its old persona. :func:`apply_soul` is the one way an edit lands, the
HUD's Apply and a rollback alike:

1. **Refused when the guard would drop it.** The body is scanned exactly as
   ``Agent._load_soul`` scans it (H387); a persona the guard would block is refused, and a
   line it would only quarantine is applied and named in the verdict.
2. **What was live is kept.** The first edit of an agent seeds the version history with
   the live file as v1, and a file changed on disk since the last version (a hand edit)
   is recorded before it is replaced, so any persona that was in force can be rolled
   back to.
3. **Written where the model reads it.** The owner's overlay — ``souls/<id>/SOUL.local.md``
   in the data home, else the repo-local ``SOUL.local.md`` — never the shipped template,
   atomically (temporary file, fsync, replace). A failed write changes nothing.
4. **Versioned, then live.** The text becomes the next version (the same text twice is one
   version), and the agent re-reads its persona, so its next turn uses it.
5. **Audited without the text.** A SETTINGS_CHANGE row names the agent, the version and its
   hash; so does a version saved to the history alone (``record_version``).

Safe mode refuses an edit: overlays are not read there (H275), so it could not be live.
The front-matter's ``description`` is the agent's one-line description for the owner's
lists (``description_of``); it is typed persona config, never part of the prompt.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.soul_edit")

AGENT_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
MAX_SOUL_BYTES = 256 * 1024
DESCRIPTION_CHARS = 400
OVERLAY_NAME = "SOUL.local.md"
SEED_MESSAGE = "on disk before the first edit"
DRIFT_MESSAGE = "on disk, changed outside the editor"

_LOCK = threading.Lock()


class SoulEditError(Exception):
    """A refusal the route answers with *status* and ``{"error": code, **extra}``."""

    def __init__(self, code: str, status: int, **extra: Any) -> None:
        super().__init__(code)
        self.code, self.status, self.extra = code, status, extra

    def body(self) -> dict:
        return {"error": self.code, **self.extra}


def guard_verdict(content: str, filename: str = OVERLAY_NAME) -> dict:
    """What ``Agent._load_soul`` would do to *content*: flags, blocked, truncated."""
    from .agent import _body_line_offset, _cap_soul_body, _scan_soul_body, _soul_max_chars

    try:
        from .cognition.frontmatter import parse_frontmatter

        _meta, body = parse_frontmatter(content)
    except Exception:
        body = content
    body, flags, blocked = _scan_soul_body(body, filename, _body_line_offset(content, body))
    truncated = False
    if not blocked:
        _capped, truncated = _cap_soul_body(body, filename, _soul_max_chars())
    return {"flags": flags, "blocked": blocked, "truncated": truncated}


def _description(meta: Any) -> str:
    text = meta.get("description") if isinstance(meta, dict) else None
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())[:DESCRIPTION_CHARS]


def description_of(agent: Any) -> str:
    """The agent's front-matter ``description`` as one line of at most DESCRIPTION_CHARS."""
    return _description((getattr(agent, "soul", None) or {}).get("meta"))


def description_in(content: str) -> str:
    """The ``description`` in a SOUL file's front-matter, as :func:`description_of`."""
    try:
        from .cognition.frontmatter import parse_frontmatter

        meta, _body = parse_frontmatter(content)
    except Exception:
        return ""
    return _description(meta)


def agent_folder(agent_id: str) -> str | None:
    """*agent_id* when it names a folder under the app's ``agents/`` — the enumerated name,
    so no request value reaches a path."""
    from .paths import app_root

    ident = str(agent_id or "").strip().lower()
    if not AGENT_ID_RE.match(ident):
        return None
    base = app_root() / "agents"
    try:
        return next((d.name for d in base.iterdir() if d.is_dir() and d.name == ident), None)
    except OSError:
        return None


def overlay_path(agent_id: str) -> tuple[Path, str]:
    """Where the owner's persona for *agent_id* is written (``soul_path_for``'s first
    candidate), and which of the two places that is."""
    from .paths import app_root, user_souls_dir

    souls = user_souls_dir()
    if souls is not None:
        return souls / agent_id / OVERLAY_NAME, "data home"
    return app_root() / "agents" / agent_id / OVERLAY_NAME, "repo overlay"


def _write_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                logger.debug("could not remove %s", tmp, exc_info=True)


def _live_text(agent_id: str) -> str | None:
    from .agent import soul_path_for

    try:
        return soul_path_for(agent_id).read_text(encoding="utf-8")
    except OSError:
        return None


def apply_soul(orch: Any, agent_id: str, content: Any, *, message: str = "", author: str = "owner",
               action: str = "apply") -> dict:
    """Make *content* the live persona of *agent_id*; see the module docstring.

    Raises :class:`SoulEditError` for a refusal (404 unknown agent, 409 safe mode, 413 too
    large, 422 not text or blocked, 500 write failed). Returns the version entry (None
    without a version store), the guard verdict, where it was written and whether the
    running agent picked it up. Blocking I/O: call it off the event loop.
    """
    from . import safe_mode

    ident = agent_folder(agent_id)
    agents = getattr(orch, "agents", None) or {}
    if ident is None or ident not in agents:
        raise SoulEditError("unknown_agent", 404, agent=str(agent_id)[:64])
    if not isinstance(content, str):
        raise SoulEditError("content_not_text", 422)
    if len(content.encode("utf-8")) > MAX_SOUL_BYTES:
        raise SoulEditError("too_large", 413, max_bytes=MAX_SOUL_BYTES)
    if safe_mode.enabled():
        raise SoulEditError("safe_mode", 409, detail="persona overlays are not read in safe mode")
    verdict = guard_verdict(content)
    if verdict["blocked"]:
        raise SoulEditError("soul_blocked", 422, guard=verdict)
    store = getattr(orch, "soul_versions", None)
    target, where = overlay_path(ident)
    with _LOCK:
        if store is not None:
            # What is live is never lost: the first edit keeps it as v1, and a persona
            # changed on disk since the last version (a hand edit) is kept before it is
            # replaced. An agent with no persona file has nothing to keep.
            before = _live_text(ident)
            head = store.current(ident)
            if before is not None and (head is None or head["content"] != before):
                store.commit(ident, before, message=SEED_MESSAGE if head is None else DRIFT_MESSAGE,
                             author="hub")
        try:
            _write_atomically(target, content)
        except OSError as exc:
            logger.warning("persona for %s could not be written: %s", ident, exc)
            raise SoulEditError("write_failed", 500) from exc
        entry = None
        if store is not None:
            entry = store.commit(ident, content, message=message or "edited in the HUD", author=author)
        agent = agents[ident]
        agent._load_soul()
        live = (agent.soul or {}).get("path") == target
    _audit(orch, ident, entry, content, action)
    return {"agent_id": ident, "version": entry, "guard": verdict, "live": live, "written_to": where}


def _audit(orch: Any, agent_id: str, entry: dict | None, content: str, action: str) -> None:
    import hashlib

    audit = getattr(orch, "audit", None)
    if audit is None:
        return
    from .security.types import SecurityEvent, SecurityEventType

    digest = entry["hash"] if entry else hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    version = f"v{entry['version']}" if entry else "unversioned"
    try:
        audit.log(SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE,
            timestamp=time.time(),
            content_preview=f"persona {agent_id} {action}: {version} sha256:{digest} ({len(content)} chars)",
            action_taken=f"soul_{action}",
        ))
    except Exception:
        logger.warning("the persona change for %s could not be audited", agent_id, exc_info=True)


def record_version(orch: Any, agent_id: str, entry: dict | None, action: str) -> None:
    """Audit a version written to the history without touching the live persona (a plain
    commit, the history-only rollback of a key that is no loaded agent): the version and
    its hash, never the text."""
    if entry:
        _audit(orch, str(agent_id)[:64], entry, str(entry.get("content", "")), action)


DRAFT_SYSTEM = ("You write the one-line description an owner sees in their list of assistants. "
                "Read the persona below and answer with one paragraph of at most 50 words saying "
                "what this assistant does. No preamble, no quotes, no markdown.")
DRAFT_MAX_TOKENS = 160


async def draft_description(orch: Any, agent_id: str) -> str:
    """A description proposed by the local model from the live persona; nothing is saved.

    Strict-local (the persona is the owner's text): no local model is a refusal, never a
    cloud call. Raises :class:`SoulEditError`.
    """
    import asyncio

    from .llm.model_config import DEFAULT_LOCAL_MODEL

    ident = agent_folder(agent_id)
    agent = (getattr(orch, "agents", None) or {}).get(ident) if ident else None
    if agent is None:
        raise SoulEditError("unknown_agent", 404, agent=str(agent_id)[:64])
    persona = str((agent.soul or {}).get("content") or "")[:8000]
    router = getattr(orch, "llm_router", None)
    try:
        backend = router.local_backend
    except Exception as exc:
        raise SoulEditError("no_local_model", 503) from exc
    if backend is None:
        raise SoulEditError("no_local_model", 503)
    model = getattr(router, "active_model", None) or DEFAULT_LOCAL_MODEL
    prompt = f"Persona:\n{persona}"
    if "qwen3" in model.lower():
        prompt = f"{prompt}\n/no_think"
    try:
        raw = await asyncio.wait_for(
            backend.generate(model=model, prompt=prompt, system=DRAFT_SYSTEM,
                             max_tokens=DRAFT_MAX_TOKENS, temperature=0.3),
            timeout=60)
    except Exception as exc:
        logger.warning("description draft for %s failed: %s", ident, type(exc).__name__)
        raise SoulEditError("no_local_model", 503) from exc
    first = next((p for p in str(raw or "").strip().split("\n\n") if p.strip()), "")
    text = " ".join(first.split())[:DESCRIPTION_CHARS]
    if not text:
        raise SoulEditError("empty_draft", 503)
    return text


__all__ = [
    "DESCRIPTION_CHARS", "MAX_SOUL_BYTES", "SoulEditError", "agent_folder", "apply_soul",
    "description_in", "description_of", "draft_description", "guard_verdict", "overlay_path",
    "record_version",
]
