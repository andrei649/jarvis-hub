"""
data_spaces.py — H10.26 Data Spaces / per-agent data scope.

Organise data sources (memory categories, plugin outputs, knowledge tags) into
named "spaces", and grant each agent only the spaces it needs — least-privilege
for what an agent can READ, complementing LOCAL_ONLY_AGENTS (which governs where
an agent's compute/data may go).

Backward-compatible by design: an agent with **no** space assignment is
*unrestricted* (sees everything), so existing behaviour is unchanged until you
deliberately scope an agent. File-backed JSON, pure-Python, offline-testable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .persistence import JsonStore

DEFAULT_PATH = Path("memory_logs/data_spaces.json")


class DataSpaces(JsonStore):
    """Named source-sets ("spaces") + per-agent assignments, with a default-open
    policy (unassigned agent = unrestricted)."""

    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return {"spaces": self._spaces, "assignments": self._assignments}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._spaces = raw.get("spaces", {})            # {space_name: [sources...]}
        self._assignments = raw.get("assignments", {})  # {agent_id: [space_names...]}

    # ── spaces ───────────────────────────────────────────────────────────────

    def define_space(self, name: str, sources) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("space name is required")
        self._spaces[name] = sorted({str(s).strip() for s in (sources or []) if str(s).strip()})
        with self._lock:
            self._save()
        return {"space": name, "sources": self._spaces[name]}

    def delete_space(self, name: str) -> bool:
        existed = name in self._spaces
        self._spaces.pop(name, None)
        # cascade: drop the space from every assignment that referenced it
        for spaces in self._assignments.values():
            if name in spaces:
                spaces.remove(name)
        self._assignments = {a: s for a, s in self._assignments.items() if s}
        if existed:
            with self._lock:
                self._save()
        return existed

    def list_spaces(self) -> list[dict]:
        return [{"space": k, "sources": v} for k, v in sorted(self._spaces.items())]

    # ── assignments ──────────────────────────────────────────────────────────

    def assign(self, agent_id: str, space_name: str) -> dict:
        agent_id = (agent_id or "").strip().lower()
        if not agent_id:
            raise ValueError("agent_id is required")
        if space_name not in self._spaces:
            raise ValueError(f"unknown space: {space_name}")
        cur = set(self._assignments.get(agent_id, []))
        cur.add(space_name)
        self._assignments[agent_id] = sorted(cur)
        with self._lock:
            self._save()
        return {"agent": agent_id, "spaces": self._assignments[agent_id]}

    def unassign(self, agent_id: str, space_name: str) -> dict:
        agent_id = (agent_id or "").strip().lower()
        cur = set(self._assignments.get(agent_id, []))
        cur.discard(space_name)
        if cur:
            self._assignments[agent_id] = sorted(cur)
        else:
            self._assignments.pop(agent_id, None)       # back to unrestricted
        with self._lock:
            self._save()
        return {"agent": agent_id, "spaces": sorted(cur)}

    def list_assignments(self) -> dict:
        return {a: s for a, s in sorted(self._assignments.items())}

    # ── enforcement ──────────────────────────────────────────────────────────

    def allowed_sources(self, agent_id: str) -> Optional[set]:
        """Sources *agent_id* may read. ``None`` means unrestricted (no scope)."""
        agent_id = (agent_id or "").strip().lower()
        spaces = self._assignments.get(agent_id)
        if not spaces:
            return None
        allowed: set = set()
        for s in spaces:
            allowed.update(self._spaces.get(s, []))
        return allowed

    def can_access(self, agent_id: str, source: str) -> bool:
        allowed = self.allowed_sources(agent_id)
        return allowed is None or source in allowed

    def filter_categories(self, category_map: dict, agent_id: str) -> dict:
        """Return *category_map* with categories the agent isn't scoped to dropped.
        An unrestricted agent gets the map unchanged."""
        allowed = self.allowed_sources(agent_id)
        if allowed is None:
            return dict(category_map)
        return {k: v for k, v in category_map.items() if k in allowed}
