"""Tests for H10.22 — Prompt Version Control."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.soul_versioning import SoulVersionStore


# ── commit / history ─────────────────────────────────────────────────────────

def test_commit_increments_and_dedupes(tmp_path):
    s = SoulVersionStore(path=tmp_path / "sv.json")
    v1 = s.commit("jarvis", "v1 content", message="init")
    assert v1["version"] == 1 and v1["parent"] is None
    v2 = s.commit("jarvis", "v2 content", message="tweak")
    assert v2["version"] == 2 and v2["parent"] == 1
    # identical content → no new version
    again = s.commit("jarvis", "v2 content")
    assert again["version"] == 2


def test_history_marks_current(tmp_path):
    s = SoulVersionStore(path=tmp_path / "sv.json")
    s.commit("a", "one")
    s.commit("a", "two")
    hist = s.history("a")
    assert [h["version"] for h in hist] == [2, 1]    # newest first
    assert hist[0]["is_current"] is True
    assert "content" not in hist[0]                  # metadata only


def test_diff(tmp_path):
    s = SoulVersionStore(path=tmp_path / "sv.json")
    s.commit("a", "line1\nline2")
    s.commit("a", "line1\nCHANGED")
    d = s.diff("a", 1, 2)
    assert "-line2" in d and "+CHANGED" in d
    assert s.diff("a", 1, 99) is None


def test_rollback_is_nondestructive(tmp_path):
    s = SoulVersionStore(path=tmp_path / "sv.json")
    s.commit("a", "original")
    s.commit("a", "broken")
    rb = s.rollback("a", 1)
    assert rb["version"] == 3                         # new version
    assert rb["content"] == "original"
    assert "rollback to v1" in rb["message"]
    assert s.current("a")["content"] == "original"


# ── A/B ──────────────────────────────────────────────────────────────────────

def test_ab_experiment_pick_and_summary(tmp_path):
    s = SoulVersionStore(path=tmp_path / "sv.json")
    s.commit("a", "A")
    s.commit("a", "B")
    s.set_experiment("a", 1, 2, split=0.5)
    # deterministic pick via roll
    assert s.pick("a", roll=0.1) == 2                 # roll < split → B
    assert s.pick("a", roll=0.9) == 1                 # else A

    s.record_result("a", 1, 0.4)
    s.record_result("a", 2, 0.8)
    s.record_result("a", 2, 0.9)
    summ = s.ab_summary("a")
    assert summ["means"]["1"] == 0.4
    assert summ["means"]["2"] == pytest.approx(0.85)
    assert summ["winner"] == 2


def test_ab_requires_existing_versions(tmp_path):
    s = SoulVersionStore(path=tmp_path / "sv.json")
    s.commit("a", "only one")
    with pytest.raises(KeyError):
        s.set_experiment("a", 1, 5)
    assert s.ab_summary("a") is None                  # no experiment yet


def test_persistence(tmp_path):
    p = tmp_path / "sv.json"
    s = SoulVersionStore(path=p)
    s.commit("a", "persist me", message="m")
    assert SoulVersionStore(path=p).current("a")["content"] == "persist me"


# ── endpoints (admin-guarded) ────────────────────────────────────────────────

def test_prompt_vc_endpoints():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    hdr = {"X-Admin-Token": "test-secret"}
    try:
        with TestClient(web.app) as c:
            if getattr(web.orch, "soul_versions", None) is None:
                return
            # auth required
            assert c.get("/api/admin/prompts/jarvis/history").status_code == 401

            # commit two versions
            assert c.post("/api/admin/prompts/jarvis/commit",
                          json={"content": "first", "message": "init"}, headers=hdr).status_code == 200
            assert c.post("/api/admin/prompts/jarvis/commit",
                          json={"content": "second"}, headers=hdr).status_code == 200
            # missing content → 400
            assert c.post("/api/admin/prompts/jarvis/commit", json={}, headers=hdr).status_code == 400

            # history
            hist = c.get("/api/admin/prompts/jarvis/history", headers=hdr).json()["history"]
            assert len(hist) >= 2

            # diff + rollback
            assert "diff" in c.get("/api/admin/prompts/jarvis/diff",
                                   params={"a": 1, "b": 2}, headers=hdr).json()
            rb = c.post("/api/admin/prompts/jarvis/rollback", json={"version": 1}, headers=hdr)
            assert rb.status_code == 200

            # A/B
            ab = c.post("/api/admin/prompts/jarvis/ab", json={"a": 1, "b": 2}, headers=hdr)
            assert ab.status_code == 200
            assert "ab" in c.get("/api/admin/prompts/jarvis/ab", headers=hdr).json()
    finally:
        web.ADMIN_TOKEN = old
