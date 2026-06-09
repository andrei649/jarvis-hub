"""
skill_drift.py — H20.5 Skill self-improvement + drift manifest.

Two pieces:

  * a **content-hash manifest** so a `hermes update`-style sync can detect when a
    locally-held skill has drifted from its recorded version (and vice-versa);
  * a **refinement proposal** path that improves an *existing* skill (not just
    `generate_skill`, which only creates) — the refinement itself comes from an
    injectable refiner (deferred LLM); the proposal is gated/reversible.

Pure and offline-testable; the LLM refiner is injected.
"""

from __future__ import annotations

import hashlib
from typing import Awaitable, Callable, Optional


def manifest_hash(content: str) -> str:
    """Stable content hash for a skill body (whitespace-normalized)."""
    norm = "\n".join(line.rstrip() for line in (content or "").strip().splitlines())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


class SkillDriftManifest:
    """Records skill content-hashes and detects drift on sync."""

    def __init__(self) -> None:
        self._hashes: dict[str, str] = {}

    def record(self, skill_id: str, content: str) -> str:
        h = manifest_hash(content)
        self._hashes[skill_id] = h
        return h

    def has_drifted(self, skill_id: str, content: str) -> bool:
        known = self._hashes.get(skill_id)
        return known is not None and known != manifest_hash(content)

    def drift_report(self, skills: dict) -> dict:
        """`skills` = {skill_id: content}. Classify each as new / drifted / unchanged."""
        new, drifted, unchanged = [], [], []
        for sid, content in (skills or {}).items():
            if sid not in self._hashes:
                new.append(sid)
            elif self.has_drifted(sid, content):
                drifted.append(sid)
            else:
                unchanged.append(sid)
        return {"new": new, "drifted": drifted, "unchanged": unchanged}

    def known(self) -> "list[str]":
        return sorted(self._hashes.keys())


async def refine_proposal(skill_id: str, content: str,
                          refiner: Optional[Callable[[str], Awaitable[str]]] = None) -> dict:
    """Propose a refinement of an existing skill (gated; refiner is deferred LLM)."""
    original_hash = manifest_hash(content)
    proposed = ""
    if refiner is not None:
        try:
            proposed = await refiner(content)
        except Exception:
            proposed = ""
    changed = bool(proposed) and manifest_hash(proposed) != original_hash
    return {"skill_id": skill_id, "original_hash": original_hash,
            "proposed": proposed, "changed": changed,
            "requires_approval": True, "reversible": True}
