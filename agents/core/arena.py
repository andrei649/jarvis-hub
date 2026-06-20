"""
arena.py — H10.19 Model Arena / Blind Comparison.

Send the same query to 2+ models/agents, show the answers **blind** (anonymized
A/B labels), let the user vote, and aggregate a quality leaderboard (win-rate +
ELO). The match hides which label maps to which model until a vote is cast, so
the comparison is unbiased.

Pure/offline: the caller supplies candidate responses (a real multi-agent run in
prod, fixtures in tests); the arena handles anonymization, voting, ELO, and the
leaderboard. Persistence is a single JSON file (atomic writes).
"""

from __future__ import annotations

import json
import random
import time
import uuid
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from .persistence import JsonStore

DEFAULT_PATH = data_path("arena.json")
_K = 32           # ELO K-factor
_BASE = 1500.0    # ELO starting rating
_LABELS = "ABCDEFGH"


def _expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


class Arena(JsonStore):
    _matches: dict[str, dict]
    _ratings: dict[str, dict]   # model -> {elo, wins, losses, games}

    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return {"matches": self._matches, "ratings": self._ratings}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._matches = raw.get("matches", {})
        self._ratings = raw.get("ratings", {})

    def _rating(self, model: str) -> dict:
        return self._ratings.setdefault(
            model, {"elo": _BASE, "wins": 0, "losses": 0, "games": 0})

    # ── create (blind) ───────────────────────────────────────────────────────

    def create_match(self, query: str, candidates: dict[str, str],
                     rng: Optional[random.Random] = None) -> dict:
        """Create a blind match. *candidates* = {model: response}. Labels are
        shuffled so the displayed A/B order doesn't reveal the model."""
        if len(candidates) < 2:
            raise ValueError("need at least 2 candidates")
        rng = rng or random.Random()
        models = list(candidates.keys())
        rng.shuffle(models)
        entries, mapping = [], {}
        for i, model in enumerate(models):
            label = _LABELS[i]
            mapping[label] = model
            entries.append({"label": label, "response": candidates[model]})
        match_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._matches[match_id] = {
                "id": match_id, "query": query, "entries": entries,
                "_mapping": mapping, "voted": False, "winner_label": None,
                "winner_model": None, "created_at": time.time(),
            }
            self._save()
        return self.get_match(match_id)

    def get_match(self, match_id: str) -> Optional[dict]:
        """Return a match. The label→model mapping is hidden until a vote."""
        with self._lock:
            m = self._matches.get(match_id)
            if not m:
                return None
            out = {k: v for k, v in m.items() if k != "_mapping"}
            out = json.loads(json.dumps(out))           # deep copy
            if m["voted"]:
                out["mapping"] = dict(m["_mapping"])     # revealed after vote
        return out

    # ── vote → ELO ───────────────────────────────────────────────────────────

    def vote(self, match_id: str, winner_label: str) -> dict:
        """Record a vote for *winner_label*; reveal mapping; update ELO/win-rate."""
        with self._lock:
            m = self._matches.get(match_id)
            if not m:
                raise KeyError("unknown match")
            if m["voted"]:
                raise ValueError("match already voted")
            mapping = m["_mapping"]
            if winner_label not in mapping:
                raise ValueError("unknown label")
            winner = mapping[winner_label]
            losers = [mdl for lbl, mdl in mapping.items() if lbl != winner_label]

            wr = self._rating(winner)
            for loser in losers:
                lr = self._rating(loser)
                exp_w = _expected(wr["elo"], lr["elo"])
                wr["elo"] = round(wr["elo"] + _K * (1 - exp_w), 1)
                lr["elo"] = round(lr["elo"] + _K * (0 - (1 - exp_w)), 1)
                wr["wins"] += 1
                lr["losses"] += 1
                wr["games"] += 1
                lr["games"] += 1

            m["voted"] = True
            m["winner_label"] = winner_label
            m["winner_model"] = winner
            self._save()
        return self.get_match(match_id)

    # ── leaderboard ──────────────────────────────────────────────────────────

    def leaderboard(self) -> list[dict]:
        with self._lock:
            rows = []
            for model, r in self._ratings.items():
                games = r["games"]
                rows.append({
                    "model": model, "elo": r["elo"], "wins": r["wins"],
                    "losses": r["losses"], "games": games,
                    "win_rate": round(r["wins"] / games, 3) if games else None,
                })
        rows.sort(key=lambda x: x["elo"], reverse=True)
        return rows

    def clear(self) -> None:
        with self._lock:
            self._matches.clear()
            self._ratings.clear()
            self._save()
