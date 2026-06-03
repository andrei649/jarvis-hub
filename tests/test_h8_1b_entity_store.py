"""Tests for H8.1b — Entity Memory Store."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.memory.entity import EntityStore, extract_entities


# ── heuristic extraction ────────────────────────────────────────────────────

def test_extract_proper_nouns():
    found = dict(extract_entities("I met Alexandra at Raiffeisen Bank in Bucharest."))
    assert "Alexandra" in found
    assert "Raiffeisen Bank" in found
    assert found["Raiffeisen Bank"] == "organization"   # 'bank' hint
    assert "Bucharest" in found


def test_extract_skips_sentence_initial_stopwords():
    found = dict(extract_entities("The meeting was good. When can we talk?"))
    # 'The', 'When' are stopwords → not entities
    assert "The" not in found
    assert "When" not in found


def test_extract_empty():
    assert extract_entities("") == []
    assert extract_entities("just some lowercase words") == []


# ── store ───────────────────────────────────────────────────────────────────

def test_record_increments_mentions(tmp_path):
    store = EntityStore(path=tmp_path / "e.json")
    store.record("Max", "person", source="conversation", context="Max is my son")
    store.record("Max", "person", source="telegram")
    ent = store.get("Max")
    assert ent["mentions"] == 2
    assert set(ent["sources"]) == {"conversation", "telegram"}
    assert ent["first_seen"] <= ent["last_seen"]


def test_type_upgrade_from_unknown(tmp_path):
    store = EntityStore(path=tmp_path / "e.json")
    store.record("Cosmina", "unknown")
    store.record("Cosmina", "place")
    assert store.get("Cosmina")["type"] == "place"


def test_search_and_filter(tmp_path):
    store = EntityStore(path=tmp_path / "e.json")
    store.record("Jarvis", "project")
    store.record("Jarvis", "project")        # 2 mentions
    store.record("Frigga", "person")
    # most-mentioned first
    assert store.search()[0]["name"] == "Jarvis"
    # substring
    assert [e["name"] for e in store.search("frig")] == ["Frigga"]
    # type filter
    assert [e["name"] for e in store.search(entity_type="person")] == ["Frigga"]


def test_ingest_text_and_stats(tmp_path):
    store = EntityStore(path=tmp_path / "e.json")
    n = store.ingest_text("Andrei drives a BMW E93 built at Cosmina de Sus.", source="chat")
    assert n >= 2
    stats = store.stats()
    assert stats["entities"] == n
    assert stats["mentions_total"] >= n


def test_persistence_and_delete(tmp_path):
    p = tmp_path / "e.json"
    store = EntityStore(path=p)
    store.record("Pepper", "person")
    # reload from disk
    assert EntityStore(path=p).get("Pepper") is not None
    assert store.delete("Pepper") is True
    assert EntityStore(path=p).get("Pepper") is None


# ── endpoint ────────────────────────────────────────────────────────────────

def test_entities_endpoint():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "entities", None) is not None:
            web.orch.entities.record("Veronica", "person")
        resp = c.get("/api/memory/entities")
        assert resp.status_code == 200
        body = resp.json()
        assert "entities" in body and "stats" in body
        assert isinstance(body["entities"], list)
