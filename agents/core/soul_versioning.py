"""
soul_versioning.py — H10.22 Prompt Version Control.

Git-like version history for agent SOUL.md / system prompts: every commit is an
immutable, numbered version (with hash, message, author, parent), so you can
diff any two versions, roll back non-destructively (rollback = a new commit that
restores old content), and run A/B experiments between two versions with scored
results to pick a winner.

Storage is a single JSON file (atomic writes), fully offline-testable.
"""

from __future__ import annotations

import difflib
import hashlib
import random
import time
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from .persistence import JsonStore

DEFAULT_PATH = data_path("soul_versions.json")


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


class SoulVersionStore(JsonStore):
    # base default _serialize/_deserialize operate on self._data:
    # {agent_id: {"versions": [..], "ab": {...}}}
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)


    def _agent(self, agent_id: str) -> dict:
        return self._data.setdefault(agent_id, {"versions": [], "ab": None})

    # ── commit / history ─────────────────────────────────────────────────────

    def commit(self, agent_id: str, content: str, message: str = "", author: str = "") -> dict:
        """Append a new version. No-op (returns current) if content is unchanged."""
        with self._lock:
            agent = self._agent(agent_id)
            versions = agent["versions"]
            head = versions[-1] if versions else None
            if head is not None and head["content"] == content:
                return dict(head)          # identical → no new version
            entry = {
                "version": (head["version"] + 1) if head else 1,
                "content": content,
                "hash": _hash(content),
                "ts": time.time(),
                "message": message,
                "author": author,
                "parent": head["version"] if head else None,
            }
            versions.append(entry)
            self._save()
            return dict(entry)

    def history(self, agent_id: str) -> list[dict]:
        """Version metadata (no content), newest first."""
        with self._lock:
            versions = list(self._agent(agent_id)["versions"])
        head = versions[-1]["version"] if versions else None
        out = []
        for v in reversed(versions):
            meta = {k: v[k] for k in ("version", "hash", "ts", "message", "author", "parent")}
            meta["is_current"] = v["version"] == head
            out.append(meta)
        return out

    def get(self, agent_id: str, version: int) -> Optional[dict]:
        with self._lock:
            for v in self._agent(agent_id)["versions"]:
                if v["version"] == version:
                    return dict(v)
        return None

    def current(self, agent_id: str) -> Optional[dict]:
        with self._lock:
            versions = self._agent(agent_id)["versions"]
            return dict(versions[-1]) if versions else None

    # ── diff / rollback ──────────────────────────────────────────────────────

    def diff(self, agent_id: str, a: int, b: int) -> Optional[str]:
        """Unified diff between version *a* and version *b*."""
        va, vb = self.get(agent_id, a), self.get(agent_id, b)
        if va is None or vb is None:
            return None
        lines = difflib.unified_diff(
            va["content"].splitlines(),
            vb["content"].splitlines(),
            fromfile=f"v{a}", tofile=f"v{b}", lineterm="",
        )
        return "\n".join(lines)

    def rollback(self, agent_id: str, version: int, author: str = "") -> Optional[dict]:
        """Non-destructive: commit a NEW version restoring *version*'s content."""
        target = self.get(agent_id, version)
        if target is None:
            return None
        return self.commit(
            agent_id, target["content"],
            message=f"rollback to v{version}", author=author,
        )

    # ── A/B experiments ──────────────────────────────────────────────────────

    def set_experiment(self, agent_id: str, a: int, b: int, split: float = 0.5) -> dict:
        """Start an A/B test between two existing versions (split = P(B))."""
        if self.get(agent_id, a) is None or self.get(agent_id, b) is None:
            raise KeyError("both versions must exist")
        split = min(max(float(split), 0.0), 1.0)
        with self._lock:
            ab = {
                "a": a, "b": b, "split": split,
                "results": {str(a): {"n": 0, "score_sum": 0.0},
                            str(b): {"n": 0, "score_sum": 0.0}},
                "started_at": time.time(),
            }
            self._agent(agent_id)["ab"] = ab
            self._save()
            return dict(ab)

    def pick(self, agent_id: str, roll: Optional[float] = None) -> Optional[int]:
        """Pick a version for this run per the experiment split (B if roll < split)."""
        with self._lock:
            ab = self._agent(agent_id)["ab"]
        if not ab:
            cur = self.current(agent_id)
            return cur["version"] if cur else None
        roll = random.random() if roll is None else roll
        return ab["b"] if roll < ab["split"] else ab["a"]

    def record_result(self, agent_id: str, version: int, score: float) -> bool:
        """Record a scored outcome for a version under the active experiment."""
        with self._lock:
            ab = self._agent(agent_id)["ab"]
            if not ab or str(version) not in ab["results"]:
                return False
            r = ab["results"][str(version)]
            r["n"] += 1
            r["score_sum"] = round(r["score_sum"] + float(score), 6)
            self._save()
            return True

    def ab_summary(self, agent_id: str) -> Optional[dict]:
        """Per-version mean score + the current leader (or None if no experiment)."""
        with self._lock:
            ab = self._agent(agent_id)["ab"]
            ab = dict(ab) if ab else None
        if not ab:
            return None
        means = {}
        for ver, r in ab["results"].items():
            means[ver] = round(r["score_sum"] / r["n"], 6) if r["n"] else None
        scored = {v: m for v, m in means.items() if m is not None}
        winner = max(scored, key=scored.get) if scored else None
        return {
            "a": ab["a"], "b": ab["b"], "split": ab["split"],
            "results": ab["results"], "means": means,
            "winner": int(winner) if winner is not None else None,
        }
