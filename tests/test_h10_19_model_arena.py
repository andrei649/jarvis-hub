"""Tests for H10.19 — Model Arena / Blind Comparison."""
import random
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.arena import Arena


# ── blind creation ───────────────────────────────────────────────────────────

def test_create_match_is_blind(tmp_path):
    a = Arena(path=tmp_path / "a.json")
    m = a.create_match("2+2?", {"gpt-4o": "four", "qwen": "4"},
                       rng=random.Random(1))
    # entries expose only label + response, never the model
    assert {e["label"] for e in m["entries"]} == {"A", "B"}
    for e in m["entries"]:
        assert "model" not in e
    assert "mapping" not in m                      # hidden before vote
    assert m["voted"] is False


def test_create_requires_two(tmp_path):
    a = Arena(path=tmp_path / "a.json")
    with pytest.raises(ValueError):
        a.create_match("q", {"only": "one"})


# ── vote → ELO + reveal ──────────────────────────────────────────────────────

def test_vote_updates_elo_and_reveals(tmp_path):
    a = Arena(path=tmp_path / "a.json")
    m = a.create_match("q", {"strong": "great answer", "weak": "meh"},
                       rng=random.Random(0))
    winner_label = next(e["label"] for e in m["entries"])  # vote for whoever is 'A'
    voted = a.vote(m["id"], winner_label)
    assert voted["voted"] is True
    assert "mapping" in voted                      # revealed after vote
    winner_model = voted["winner_model"]
    board = {r["model"]: r for r in a.leaderboard()}
    assert board[winner_model]["elo"] > 1500       # winner gained
    assert board[winner_model]["wins"] == 1
    loser = [mdl for mdl in board if mdl != winner_model][0]
    assert board[loser]["elo"] < 1500              # loser dropped


def test_double_vote_and_bad_label_rejected(tmp_path):
    a = Arena(path=tmp_path / "a.json")
    m = a.create_match("q", {"x": "ax", "y": "by"}, rng=random.Random(2))
    a.vote(m["id"], m["entries"][0]["label"])
    with pytest.raises(ValueError):
        a.vote(m["id"], m["entries"][0]["label"])  # already voted
    with pytest.raises(KeyError):
        a.vote("nonexistent", "A")


def test_leaderboard_and_persistence(tmp_path):
    p = tmp_path / "a.json"
    a = Arena(path=p)
    m = a.create_match("q", {"m1": "r1", "m2": "r2"}, rng=random.Random(3))
    a.vote(m["id"], m["entries"][0]["label"])
    # reload preserves ratings
    board = {r["model"]: r for r in Arena(path=p).leaderboard()}
    assert sum(r["games"] for r in board.values()) == 2   # one win + one loss


# ── endpoints ────────────────────────────────────────────────────────────────

def test_arena_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "arena", None) is None:
            return
        web.orch.arena.clear()
        assert c.post("/api/arena/run", json={"query": "q"}).status_code == 400  # no candidates
        run = c.post("/api/arena/run", json={
            "query": "best greeting?",
            "candidates": {"alpha": "hello", "beta": "hi there"}})
        assert run.status_code == 200
        match = run.json()["match"]
        assert "mapping" not in match              # blind
        vote = c.post("/api/arena/vote",
                      json={"match_id": match["id"], "winner": match["entries"][0]["label"]})
        assert vote.status_code == 200 and vote.json()["match"]["voted"] is True
        lb = c.get("/api/arena/leaderboard")
        assert lb.status_code == 200 and len(lb.json()["leaderboard"]) == 2
