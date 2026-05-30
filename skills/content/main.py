"""
content/main.py — Veronica's content drafting skill (H2.10).

Loader-pattern skill. Saves platform drafts (LinkedIn, blog, …) as local JSON
under memory_logs/content_drafts/, and lists them back. Pure-local, no network.

Commands (see get_commands):
  draft <platform>|<title>|<body>   — save a draft, returns its id
  list_drafts <platform>            — list saved drafts for a platform
"""

import json
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger("jarvis.skills.content")

DRAFTS_DIR = Path("memory_logs") / "content_drafts"


def get_commands() -> list[str]:
    return ["draft", "list_drafts"]


def _platform_file(platform: str) -> Path:
    safe = "".join(c for c in platform.lower() if c.isalnum() or c in "-_") or "general"
    return DRAFTS_DIR / f"{safe}.json"


def _load(platform: str) -> list[dict]:
    fp = _platform_file(platform)
    if not fp.exists():
        return []
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(platform: str, drafts: list[dict]) -> None:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    _platform_file(platform).write_text(
        json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def draft(args: str, context: dict = None) -> str:
    """`draft <platform>|<title>|<body>` — save a draft."""
    parts = [p.strip() for p in (args or "").split("|")]
    if len(parts) < 3 or not parts[0]:
        return "Folosire: draft <platformă>|<titlu>|<text>"
    platform, title, body = parts[0], parts[1], "|".join(parts[2:])
    drafts = _load(platform)
    draft_id = uuid.uuid4().hex[:8]
    drafts.append({
        "draft_id": draft_id, "title": title, "body": body, "ts": time.time(),
    })
    _save(platform, drafts)
    return f"Draft salvat pentru {platform} (id {draft_id}): „{title}”."


async def list_drafts(args: str, context: dict = None) -> str:
    """`list_drafts <platform>` — list saved drafts."""
    platform = (args or "").strip().split(" ")[0]
    if not platform:
        return "Folosire: list_drafts <platformă>"
    drafts = _load(platform)
    if not drafts:
        return f"Niciun draft pentru {platform}."
    lines = [f"- [{d['draft_id']}] {d['title']}" for d in drafts[-10:]]
    return f"Drafturi {platform} ({len(drafts)}):\n" + "\n".join(lines)


# Programmatic API (used by tests / other modules without text parsing).
def save_draft(platform: str, title: str, body: str) -> dict:
    drafts = _load(platform)
    entry = {"draft_id": uuid.uuid4().hex[:8], "title": title, "body": body, "ts": time.time()}
    drafts.append(entry)
    _save(platform, drafts)
    return {"status": "success", "draft_id": entry["draft_id"]}


def get_drafts(platform: str) -> list[dict]:
    return [{"draft_id": d["draft_id"], "title": d["title"], "body": d["body"]}
            for d in _load(platform)]


async def handle(cmd: str, args: str, context: dict = None) -> str:
    dispatch = {"draft": draft, "list_drafts": list_drafts}
    fn = dispatch.get(cmd)
    if fn:
        return await fn(args, context)
    return f"[content] comandă necunoscută: {cmd}"
