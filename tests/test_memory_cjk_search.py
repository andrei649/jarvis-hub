"""H574 — CJK-aware FTS5 index for structured memory search and CJK-aware session terms.

The index is ``unicode61`` over pre-segmented text (CJK unigrams + bigrams), so 1- and
2-character CJK queries are answered by ``MATCH`` instead of a ``LIKE '%…%'`` scan, and
a reindex migration builds it for rows written before it existed.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from agents.core.memory import cjk_fts
from agents.core.memory.session_search import search_sessions
from agents.core.memory.store import MemoryStore


def _run(coro):
    return asyncio.run(coro)


def _traced(store):
    """Record every SQL statement the store runs (each call opens its own connection)."""
    seen: list[str] = []
    original = store._conn

    def conn():
        c = original()
        c.set_trace_callback(seen.append)
        return c

    store._conn = conn
    return seen


def _values(rows):
    return sorted(r["value"] for r in rows)


# ── the segmenter ───────────────────────────────────────────────────────────

def test_index_text_emits_unigrams_and_bigrams_per_cjk_run():
    assert cjk_fts.index_text("明天去看牙医").split() == [
        "明", "天", "去", "看", "牙", "医", "明天", "天去", "去看", "看牙", "牙医"]
    # non-CJK text passes through (lower-cased); punctuation ends a run
    assert cjk_fts.index_text("Call 牙医、预约 now").split() == [
        "call", "牙", "医", "牙医", "、", "预", "约", "预约", "now"]
    assert cjk_fts.cjk_runs("ｶﾀｶﾅ・テスト") == ["カタカナ", "テスト"]   # NFKC; ・ separates


def test_match_expression_quotes_grams_and_ignores_non_cjk():
    assert cjk_fts.match_expression("牙") == '"牙"'
    assert cjk_fts.match_expression("牙医") == '"牙医"'
    assert cjk_fts.match_expression("看牙医") == '"看牙" AND "牙医"'
    assert cjk_fts.match_expression('dentist "OR* 牙') == '"牙"'
    assert cjk_fts.match_expression("dentist") is None
    assert cjk_fts.split_script_boundaries("明天dentist") == ["明天", "dentist"]


# ── MemoryStore: CJK queries go through the FTS5 index ─────────────────────

@pytest.fixture
def store(tmp_path):
    s = MemoryStore(db_path=tmp_path / "memory.db")
    _run(s.upsert("fact", "appointment", "明天去看牙医"))
    _run(s.upsert("fact", "food", "我喜欢寿司和拉面"))
    _run(s.upsert("preference", "jp", "カタカナのテスト"))
    _run(s.upsert("preference", "ko", "한국어 회의 내일"))
    _run(s.upsert("fact", "drink", "coffee with milk"))
    return s


@pytest.mark.parametrize("query, expected", [
    ("牙", ["明天去看牙医"]),               # one character
    ("牙医", ["明天去看牙医"]),             # two characters
    ("去看牙医", ["明天去看牙医"]),
    ("寿司", ["我喜欢寿司和拉面"]),
    ("ｶﾀｶﾅ", ["カタカナのテスト"]),           # half-width query meets full-width text
    ("회의", ["한국어 회의 내일"]),
])
def test_short_cjk_queries_use_match_not_like(store, query, expected):
    seen = _traced(store)
    rows = _run(store.search(query))
    assert _values(rows) == expected
    statements = " ".join(seen)
    assert "MATCH" in statements
    assert "LIKE" not in statements


def test_index_candidates_are_rechecked_for_exact_substring(store):
    _run(store.upsert("fact", "split", "看牙 医生"))         # 看牙 and 医 sit in separate runs
    assert _values(_run(store.search("牙医"))) == ["明天去看牙医"]
    assert _run(store.search("医牙")) == []
    _run(store.upsert("fact", "both", "看牙。牙医"))          # both bigrams of 看牙医, not the substring
    assert _values(_run(store.search("看牙医"))) == ["明天去看牙医"]


def test_key_is_searchable_too(store):
    _run(store.upsert("fact", "牙医电话", "+40 700 000 000"))
    assert _values(_run(store.search("电话"))) == ["+40 700 000 000"]


def test_non_cjk_queries_keep_like_substring_semantics(store):
    seen = _traced(store)
    assert _values(_run(store.search("ffe"))) == ["coffee with milk"]
    assert "LIKE" in " ".join(seen)


def test_mixed_query_keeps_whole_substring_semantics(store):
    _run(store.upsert("fact", "mixed", "call 牙医 tomorrow"))
    assert _values(_run(store.search("call 牙医"))) == ["call 牙医 tomorrow"]
    assert _run(store.search("phone 牙医")) == []


def test_upsert_overwrite_and_delete_keep_index_in_step(store):
    _run(store.upsert("fact", "appointment", "下周去医院"))
    assert _run(store.search("牙医")) == []
    assert _values(_run(store.search("医院"))) == ["下周去医院"]
    assert _run(store.delete("fact", "appointment")) is True
    assert _run(store.search("医院")) == []
    with sqlite3.connect(store._path) as conn:
        (indexed,) = conn.execute("SELECT count(*) FROM memory_fts").fetchone()
        (rows,) = conn.execute("SELECT count(*) FROM memory").fetchone()
    assert indexed == rows


def test_limit_and_recency_order(tmp_path):
    s = MemoryStore(db_path=tmp_path / "m.db")
    for i in range(5):
        _run(s.upsert("fact", f"k{i}", f"会议 {i}"))
    with sqlite3.connect(s._path) as conn:
        for i in range(5):
            conn.execute("UPDATE memory SET updated_at=? WHERE key=?", (f"2026-01-0{i + 1}", f"k{i}"))
    rows = _run(s.search("会议", limit=2))
    assert [r["key"] for r in rows] == ["k4", "k3"]


# ── the reindex migration ───────────────────────────────────────────────────

def _legacy_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, key TEXT NOT NULL,
            value TEXT NOT NULL, metadata TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(category, key))""")
        conn.execute("INSERT INTO memory (category, key, value) VALUES ('fact','a','明天去看牙医')")
        conn.execute("INSERT INTO memory (category, key, value) VALUES ('fact','b','寿司')")


def test_rows_written_before_the_index_are_backfilled_on_open(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_db(path)
    s = MemoryStore(db_path=path)
    seen = _traced(s)
    assert _values(_run(s.search("牙"))) == ["明天去看牙医"]
    assert _values(_run(s.search("寿司"))) == ["寿司"]
    assert "LIKE" not in " ".join(seen)


def test_rows_removed_behind_the_store_leave_the_index_on_open(tmp_path):
    path = tmp_path / "m.db"
    s = MemoryStore(db_path=path)
    _run(s.upsert("fact", "a", "牙医"))
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM memory")
    MemoryStore(db_path=path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM memory_fts").fetchone()[0] == 0


def test_segmenter_version_change_rebuilds_the_index(tmp_path):
    path = tmp_path / "m.db"
    s = MemoryStore(db_path=path)
    _run(s.upsert("fact", "a", "明天去看牙医"))
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM memory_fts")
        conn.execute("INSERT INTO memory_fts(rowid, seg) VALUES (999, 'stale 牙 医 牙医')")
        conn.execute("UPDATE memory_fts_meta SET value='old-version' WHERE name='segmenter'")
    reopened = MemoryStore(db_path=path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM memory_fts_meta WHERE name='segmenter'"
                            ).fetchone()[0] == cjk_fts.SEGMENTER_VERSION
        assert [r[0] for r in conn.execute("SELECT rowid FROM memory_fts")] == [1]
    assert _values(_run(reopened.search("牙医"))) == ["明天去看牙医"]


def test_without_fts5_cjk_search_falls_back_to_like(store):
    store._fts = False
    seen = _traced(store)
    assert _values(_run(store.search("牙医"))) == ["明天去看牙医"]
    assert "LIKE" in " ".join(seen)


# ── session search: CJK-aware keyword split ─────────────────────────────────

def _session(tmp_path, sid, turns):
    (tmp_path / f"{sid}.json").write_text(json.dumps({"session_id": sid, "turns": turns}),
                                          encoding="utf-8")


def test_session_search_splits_cjk_from_latin_and_finds_short_cjk_terms(tmp_path):
    _session(tmp_path, "s-cjk", [
        {"role": "user", "content": "明天下午三点去看牙医, dentist booked"},
        {"role": "assistant", "content": "好的，我记住了"},
    ])
    found = search_sessions("牙医dentist", directory=tmp_path)
    assert found["ok"] and found["terms"] == ["牙医", "dentist"]
    assert [h["turn"] for h in found["hits"]] == [0]
    assert [h["turn"] for h in search_sessions("牙", directory=tmp_path)["hits"]] == [0]
    assert [h["turn"] for h in search_sessions("记住", directory=tmp_path)["hits"]] == [1]
    # half-width / full-width forms meet each other, as in the memory index
    assert [h["turn"] for h in search_sessions("ｄｅｎｔｉｓｔ牙医", directory=tmp_path)["hits"]] == [0]
    assert search_sessions("dentist记住", directory=tmp_path)["hits"] == []
