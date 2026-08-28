"""packs.py router — T-0.58 Pack Manager: one typed surface over every pack kind.

0.58's remaining scope was "model/domain/content pack types are separate". The
content/domain type turned out to be already implemented — `knowledge_packs.py`
(manifest / verify / install-plan over the H12.2 drop-folder indexer) — but with
**no caller at all**: no route, no HUD, only its own unit test. So the gap was
never a missing taxonomy, it was two pack implementations that never met.

This unifies them behind one read surface:

* ``skill``     — the `SkillMarketplace` registry (publish/install/rollback/history
                  already live at `/api/skills/marketplace/*`; listed here for the
                  unified inventory).
* ``knowledge`` — configured `local_docs.folders` that carry a `pack.json`
                  manifest. A folder *without* one is reported under
                  ``unmanifested`` rather than promoted to a pack: a bare
                  drop-folder has nothing to verify against, and calling it a
                  pack would imply an integrity guarantee that doesn't exist.
* ``model``     — declared **unsupported**, with a reason. Nerva does not
                  distribute model weights (models come from LM Studio / Ollama),
                  so a `model` pack type would be a label with nothing behind it.
                  Naming it honestly beats shipping a stub that reads as done.

Read-only and user-guarded. Installing a knowledge pack stays on the existing
governed path (`POST /api/local-docs/index`) — this router deliberately adds no
second way to write into memory.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi import Path as PathParam

from agents.core.app_state import get_orch
from agents.core.knowledge_packs import load_manifest, verify_pack
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.packs")

router = APIRouter(tags=["packs"])

PACK_TYPES = [
    {"type": "skill", "supported": True,
     "manages": "publish / install / uninstall / rollback / history",
     "surface": "/api/skills/marketplace/*"},
    {"type": "knowledge", "supported": True,
     "manages": "manifest / verify / index into memory",
     "surface": "/api/packs/{key}/verify · /api/local-docs/index"},
    {"type": "model", "supported": False,
     "reason": "Nerva does not distribute model weights — models are provided by "
               "LM Studio / Ollama on the host, so there is nothing for a pack to carry.",
     "surface": None},
]


def _configured_folders(orch) -> dict:
    try:
        folders = orch.get_setting("local_docs.folders", {}) if orch else {}
    except Exception:
        logger.debug("local_docs.folders read failed", exc_info=True)
        return {}
    return folders if isinstance(folders, dict) else {}


def _knowledge_packs(orch) -> tuple[list[dict], list[str]]:
    """Configured folders split into (manifested packs, unmanifested keys)."""
    packs: list[dict] = []
    unmanifested: list[str] = []
    for key, folder in sorted(_configured_folders(orch).items()):
        try:
            manifest = load_manifest(folder)
        except Exception:
            logger.debug("manifest read failed for %s", key, exc_info=True)
            manifest = None
        if not manifest:
            unmanifested.append(str(key))
            continue
        files = manifest.get("files")
        packs.append({
            "pack_type": "knowledge",
            "key": str(key),
            "name": str(manifest.get("name") or key),
            "version": str(manifest.get("version") or ""),
            "files": len(files) if isinstance(files, list) else 0,
            "path": str(Path(folder)),
        })
    return packs, unmanifested


def _skill_packs(orch) -> list[dict]:
    try:
        rows = orch.marketplace.list_skills() if orch else []
    except Exception:
        logger.debug("marketplace listing failed", exc_info=True)
        return []
    out: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append({
            "pack_type": "skill",
            "name": str(row.get("name") or ""),
            "version": str(row.get("version") or ""),
            "description": str(row.get("description") or "")[:200],
            "author": str(row.get("author") or ""),
        })
    return out


@router.get("/api/packs", dependencies=[Depends(user_guard)])
async def packs_list():
    """Typed inventory across every supported pack kind."""
    orch = get_orch()
    if orch is None:
        return nocache_json({
            "available": False, "types": PACK_TYPES,
            "packs": [], "unmanifested": [], "counts": {},
        })
    knowledge, unmanifested = _knowledge_packs(orch)
    skills = _skill_packs(orch)
    packs = skills + knowledge
    return nocache_json({
        "available": True,
        "types": PACK_TYPES,
        "packs": packs,
        "unmanifested": unmanifested,
        "counts": {"skill": len(skills), "knowledge": len(knowledge), "total": len(packs)},
    })


@router.get("/api/packs/{key}/verify", dependencies=[Depends(user_guard)])
async def packs_verify(key: str = PathParam(..., min_length=1, max_length=128)):
    """Tamper/completeness check for one configured knowledge pack.

    Every discrepancy is named (`missing` / `modified` / `unexpected`) — the
    underlying `verify_pack` never silently passes a partial pack, and neither
    does this. A folder with no manifest is refused rather than reported clean.
    """
    orch = get_orch()
    folder = _configured_folders(orch).get(key)
    if not folder:
        return nocache_json(
            {"ok": False, "reason": "unknown_key", "key": key,
             "available": sorted(_configured_folders(orch))},
            status_code=404,
        )
    manifest = load_manifest(folder)
    if not manifest:
        return nocache_json({
            "ok": False, "reason": "no_manifest", "key": key,
            "hint": "a folder without pack.json is a drop-folder, not a pack — "
                    "index it via /api/local-docs/index instead",
        })
    check = verify_pack(folder, manifest)
    return nocache_json({
        "ok": bool(check.get("ok")),
        "key": key,
        "name": str(manifest.get("name") or key),
        "version": str(manifest.get("version") or ""),
        "verify": check,
    })
