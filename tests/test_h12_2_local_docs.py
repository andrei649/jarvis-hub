"""Tests for H12.2 — Onboarding drop-folder.

Indexing logic uses an injected `remember` so it runs fully offline; the
endpoint is exercised against the real app over a temp folder.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.local_docs import LocalDocsIndexer, chunk_text, extract_text


# ── helpers ─────────────────────────────────────────────────────────────────

def test_chunk_text_windows():
    words = " ".join(str(i) for i in range(1000))
    chunks = chunk_text(words, chunk_words=400, overlap=40)
    assert len(chunks) >= 2
    assert all(len(c.split()) <= 400 for c in chunks)
    # short text → single chunk
    assert chunk_text("just a few words") == ["just a few words"]
    assert chunk_text("") == []


def test_extract_text_native_and_skip(tmp_path):
    md = tmp_path / "a.md"
    md.write_text("# Title\nhello world", encoding="utf-8")
    assert "hello world" in extract_text(md)
    # missing-parser format → None (graceful skip), never raises
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF-1.4 not really a pdf")
    assert extract_text(pdf) is None


# ── indexing ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_index_folder_remembers_chunks(tmp_path):
    (tmp_path / "one.md").write_text("alpha beta gamma", encoding="utf-8")
    (tmp_path / "two.txt").write_text("delta epsilon", encoding="utf-8")
    (tmp_path / "ignore.bin").write_bytes(b"\x00\x01")
    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "three.md").write_text("zeta eta", encoding="utf-8")

    remembered = []

    async def remember(text, metadata):
        remembered.append((text, metadata))
        return "id"

    summary = await LocalDocsIndexer(remember).index(tmp_path)
    assert summary["files_indexed"] == 3      # two top-level + one nested
    assert summary["chunks"] == 3
    # metadata carries source + relative file path
    files = {m["file"] for _, m in remembered}
    assert "one.md" in files
    assert str(Path("nested") / "three.md") in files


@pytest.mark.asyncio
async def test_index_missing_folder(tmp_path):
    async def remember(text, metadata):
        return "id"
    out = await LocalDocsIndexer(remember).index(tmp_path / "nope")
    assert "error" in out


# ── endpoint ────────────────────────────────────────────────────────────────

def test_local_docs_endpoint(tmp_path):
    (tmp_path / "doc.md").write_text("hello from a local document", encoding="utf-8")
    from agents import web
    with TestClient(web.app) as c:
        resp = c.post("/api/local-docs/index", json={"path": str(tmp_path)})
        assert resp.status_code == 200
        assert resp.json()["files_indexed"] == 1
        # status reflects the last run
        status = c.get("/api/local-docs").json()
        assert status["files_indexed"] == 1
        # bad path → 400
        bad = c.post("/api/local-docs/index", json={"path": str(tmp_path / "ghost")})
        assert bad.status_code == 400
