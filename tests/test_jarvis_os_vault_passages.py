"""A matched vault passage can be found beyond the public graph preview."""

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core.routers import jarvis_os


@pytest.fixture
def long_note(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    note = vault / "Long.md"
    note.write_text("# Long\n\n" + "ordinary filler.\n" * 500 + "\nThe cobalt narwhal keeps the key.\n",
                    encoding="utf-8")
    monkeypatch.setenv("JARVIS_OS_VAULT_PATH", str(vault))
    monkeypatch.setenv("JARVIS_OS_REPOSITORY_DOCS", "0")
    engine = jarvis_os._engine()
    engine.invalidate_brain_cache()
    yield note, engine
    engine.invalidate_brain_cache()


def test_deep_passage_reaches_chat_but_not_the_public_graph_or_note_preview(long_note):
    _note, engine = long_note
    client = TestClient(web.app)

    graph = client.get("/api/os/brain").json()
    public = next(node for node in graph["nodes"] if node.get("relPath") == "Long.md")
    assert len(public["body"]) <= 3800
    assert "cobalt narwhal" not in public["body"]
    preview = client.get("/api/os/brain/note", params={"relPath": "Long.md"}).json()
    assert len(preview["body"]) == 6000
    assert "cobalt narwhal" not in preview["body"]

    result = client.get("/api/os/brain/retrieve", params={"q": "cobalt narwhal"}).json()
    assert len(result["attachments"]) == 1
    attachment = result["attachments"][0]
    assert attachment["name"] == "Long.md"
    assert "The cobalt narwhal keeps the key." in attachment["text"]
    assert len(attachment["text"]) <= 1500
    context, nodes = engine.retrieve_vault_context("cobalt narwhal", jarvis_os._config(engine))
    assert "The cobalt narwhal keeps the key." in context
    assert "The cobalt narwhal keeps the key." in nodes[0]["excerpt"]
    assert "cobalt narwhal" in engine._synthesize_grounded_fallback("cobalt narwhal", nodes)["reply"]


def test_changed_tail_does_not_leak_after_graph_walk(long_note, monkeypatch):
    note, engine = long_note
    original = engine._read_indexed_note_found

    def change_before_read(cfg, found, *, target_id=None):
        note.write_text("# Long\n\nCurrent public text.\n", encoding="utf-8")
        return original(cfg, found, target_id=target_id)

    monkeypatch.setattr(engine, "_read_indexed_note_found", change_before_read)
    result = TestClient(web.app).get("/api/os/brain/retrieve", params={"q": "cobalt narwhal"}).json()
    assert result["attachments"] == []


def test_retrieve_continues_to_next_ranked_note_when_first_disappears(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    first = vault / "A.md"
    first.write_text("# A\n\ncobalt narwhal first", encoding="utf-8")
    (vault / "B.md").write_text("# B\n\ncobalt narwhal second", encoding="utf-8")
    monkeypatch.setenv("JARVIS_OS_VAULT_PATH", str(vault))
    monkeypatch.setenv("JARVIS_OS_REPOSITORY_DOCS", "0")
    engine = jarvis_os._engine()
    original = engine._read_indexed_note_found

    def remove_first(cfg, found, *, target_id=None):
        if found[2] == ("A.md",):
            first.unlink()
        return original(cfg, found, target_id=target_id)

    monkeypatch.setattr(engine, "_read_indexed_note_found", remove_first)
    try:
        _context, nodes = engine.retrieve_vault_context("cobalt narwhal", jarvis_os._config(engine), top_k=1)
        assert [node["relPath"] for node in nodes] == ["B.md"]
    finally:
        engine.invalidate_brain_cache()


def test_repo_document_keeps_its_index_label_on_fresh_read(tmp_path):
    vault = tmp_path / "Vault"
    vault.mkdir()
    repo = tmp_path / "Repo"
    document = repo / "agents" / "alpha" / "Notes.md"
    document.parent.mkdir(parents=True)
    document.write_text("# Current heading\n\nFacts without the label word.", encoding="utf-8")
    engine = jarvis_os._engine()
    cfg = {"vaultMode": "andrei_plus_nerva", "vaultPath": str(vault), "nervaPath": str(repo)}
    try:
        _context, nodes = engine.retrieve_vault_context("alpha", cfg, top_k=1)
        assert nodes[0]["title"] == "Agent · alpha (Notes)"
        assert "Facts without the label word." in nodes[0]["excerpt"]
    finally:
        engine.invalidate_brain_cache()
