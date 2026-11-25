import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core.routers import jarvis_os


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    root = tmp_path / "Sample Vault"
    destination = root / "Journal" / "Inbox"
    destination.mkdir(parents=True)
    monkeypatch.setenv("JARVIS_OS_VAULT_PATH", str(root))
    monkeypatch.setenv("JARVIS_OS_VAULT_INCLUDE", "Journal/Inbox")
    monkeypatch.setenv("JARVIS_OS_VAULT_INBOX", "Journal/Inbox")
    return root, destination


def test_capture_and_retrieve_inside_existing_scoped_inbox(inbox):
    root, destination = inbox
    client = TestClient(web.app)
    status = client.get("/api/os/status").json()
    assert status["inboxFolder"] == "Journal/Inbox"
    for number in (1, 2):
        res = client.post("/api/os/brain/capture", json={"title": "Workshop", "content": "Remember the teal desk."})
        assert res.status_code == 200, res.text[:300]
        note = destination / ("Workshop.md" if number == 1 else "Workshop (2).md")
        assert Path(res.json()["path"]) == note
        assert res.json()["node"]["relPath"] == note.relative_to(root).as_posix()
        assert "[[Acasa]]" not in note.read_text(encoding="utf-8")
    retrieved = client.get("/api/os/brain/retrieve", params={"q": "workshop"}).json()["attachments"]
    assert any(n["name"] == "Journal/Inbox/Workshop.md" and "teal desk" in n["text"] for n in retrieved)
    graph_node = next(n for n in client.get("/api/os/brain").json()["nodes"] if n.get("relPath") == "Journal/Inbox/Workshop.md")
    assert graph_node["obsidianSource"] == {
        "vault": root.name, "file": "Journal/Inbox/Workshop.md", "readable": True,
    }
    sources = client.get("/api/os/brain").json()["discoveredSources"]
    assert sources[0]["path"] == str(root)
    assert "2 Markdown" in sources[0]["detail"]
    assert not any("backup" in s["name"].lower() for s in sources)


@pytest.mark.parametrize("folder", ["Journal/Missing", "../external", "Journal/Inbox/Absent", "C:/outside", ".obsidian"])
def test_scoped_capture_refuses_invalid_excluded_or_absent_destination(inbox, monkeypatch, folder):
    root, _ = inbox
    monkeypatch.setenv("JARVIS_OS_VAULT_INBOX", folder)
    res = TestClient(web.app).post("/api/os/brain/capture", json={"title": "Example", "content": "Example"})
    assert res.status_code == 409
    assert not list(root.rglob("*.md"))
    assert not (root / "Journal/Inbox/Absent").exists()


def test_explicit_project_register_is_grounding_without_opening_project_files(inbox, monkeypatch):
    root, _ = inbox
    index = "Projects/index.json"
    file = root / index
    file.parent.mkdir(parents=True)
    record = {"id": "PRJ-111", "n": "Woodshop.md", "pas": "Order birch plywood"}
    def save():
        file.write_text(json.dumps({"schema": "project-index/v1", "items": [record]}), encoding="utf-8")
    save()
    monkeypatch.setenv("JARVIS_OS_PROJECT_INDEX", "1")
    monkeypatch.setenv("JARVIS_OS_VAULT_INCLUDE", "Journal/Inbox;" + index)
    client = TestClient(web.app)
    result = client.get("/api/os/brain/retrieve", params={"q": "woodshop"}).json()["attachments"]
    assert len(result) == 1
    assert result[0]["name"] == index + "#PRJ-111"
    assert "Order birch plywood" in result[0]["text"]
    graph_node = next(n for n in client.get("/api/os/brain").json()["nodes"] if n.get("projectId") == "PRJ-111")
    assert "obsidianSource" not in graph_node
    register_note = root / "Projects" / "Register" / "Woodshop.md"
    register_note.parent.mkdir(parents=True)
    register_note.write_text("# Woodshop\n\nvisible project note", encoding="utf-8")
    engine = jarvis_os._engine()
    engine.invalidate_brain_cache()
    graph_node = next(n for n in client.get("/api/os/brain").json()["nodes"] if n.get("projectId") == "PRJ-111")
    assert graph_node["obsidianSource"] == {
        "vault": root.name, "file": "Projects/Register/Woodshop.md", "readable": False,
    }
    assert "noteFile" not in graph_node
    assert client.get("/api/os/brain/retrieve", params={"q": "woodshop"}).json()["sources"] == {
        index + "#PRJ-111": graph_node["obsidianSource"],
    }
    monkeypatch.setenv("JARVIS_OS_VAULT_INCLUDE", "Journal/Inbox;" + index + ";Projects/Register")
    engine.invalidate_brain_cache()
    graph_node = next(n for n in client.get("/api/os/brain").json()["nodes"] if n.get("projectId") == "PRJ-111")
    assert graph_node["obsidianSource"]["readable"] is True
    register_note.write_text("---\nprivacy: restricted\n---\n\nprivate project body", encoding="utf-8")
    engine.invalidate_brain_cache()
    graph_node = next(n for n in client.get("/api/os/brain").json()["nodes"] if n.get("projectId") == "PRJ-111")
    assert graph_node["obsidianSource"]["readable"] is False
    assert "private project body" not in str(graph_node)
    monkeypatch.setenv("JARVIS_OS_VAULT_EXCLUDE", "Projects/Register")
    engine.invalidate_brain_cache()
    graph_node = next(n for n in client.get("/api/os/brain").json()["nodes"] if n.get("projectId") == "PRJ-111")
    assert "obsidianSource" not in graph_node
    record["pas"] = "Fit hinges"
    save()
    assert "Fit hinges" in client.get("/api/os/brain/retrieve", params={"q": "woodshop"}).json()["attachments"][0]["text"]
    monkeypatch.setenv("JARVIS_OS_VAULT_EXCLUDE", "Projects")
    assert not client.get("/api/os/brain/retrieve", params={"q": "woodshop"}).json()["attachments"]


def test_private_project_index_settings_select_only_the_configured_relative_files(inbox, monkeypatch):
    root, _ = inbox
    index = root / "Archive" / "summary.json"
    note = root / "Archive" / "Notes" / "Garden.md"
    note.parent.mkdir(parents=True)
    index.write_text(json.dumps({"schema": "custom-projects/v1", "items": [
        {"id": "PRJ-123", "n": "Garden.md", "pas": "Plant seeds"}]}), encoding="utf-8")
    note.write_text("# Garden\n\nA synthetic note", encoding="utf-8")
    monkeypatch.setenv("JARVIS_OS_PROJECT_INDEX", "1")
    monkeypatch.setenv("JARVIS_OS_PROJECT_INDEX_PATH", "Archive/summary.json")
    monkeypatch.setenv("JARVIS_OS_PROJECT_REGISTER_DIR", "Archive/Notes")
    monkeypatch.setenv("JARVIS_OS_PROJECT_INDEX_SCHEMA", "custom-projects/v1")
    monkeypatch.setenv("JARVIS_OS_VAULT_INCLUDE", "Journal/Inbox;Archive/summary.json")
    graph = TestClient(web.app).get("/api/os/brain").json()
    row = next(node for node in graph["nodes"] if node.get("projectId") == "PRJ-123")
    assert row["relPath"] == "Archive/summary.json#PRJ-123"
    assert row["obsidianSource"] == {"vault": root.name, "file": "Archive/Notes/Garden.md", "readable": False}


def test_ambiguous_register_filename_has_no_native_source(inbox, monkeypatch):
    root, _ = inbox
    index = root / "Projects" / "index.json"
    target = root / "Projects" / "Register" / "Project#draft.md"
    index.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    target.write_text("# Project", encoding="utf-8")
    index.write_text(json.dumps({"schema": "project-index/v1", "items": [
        {"id": "PRJ-111", "n": target.name}]}), encoding="utf-8")
    monkeypatch.setenv("JARVIS_OS_PROJECT_INDEX", "1")
    monkeypatch.setenv("JARVIS_OS_VAULT_INCLUDE", "Journal/Inbox;Projects/index.json")
    graph = TestClient(web.app).get("/api/os/brain").json()
    node = next(n for n in graph["nodes"] if n.get("projectId") == "PRJ-111")
    assert "obsidianSource" not in node


def test_duplicate_truncated_attachment_names_have_no_native_source(inbox, monkeypatch):
    root, _ = inbox
    same_prefix = "n" * 200
    nodes = [{"title": "Alpha", "relPath": same_prefix + suffix, "body": "alpha",
              "obsidianSource": {"vault": root.name, "file": suffix + ".md", "readable": True}}
             for suffix in ("-one", "-two")]
    monkeypatch.setattr(jarvis_os._engine(), "retrieve_vault_context", lambda *_args: ("", nodes))
    result = TestClient(web.app).get("/api/os/brain/retrieve", params={"q": "alpha"}).json()
    assert [item["name"] for item in result["attachments"]] == [same_prefix, same_prefix]
    assert result["sources"] == {}


def test_register_readability_matches_exact_nfd_target(inbox, monkeypatch):
    root, _ = inbox
    name = "Cafe\u0301.md"
    index = root / "Projects" / "index.json"
    target = root / "Projects" / "Register" / name
    index.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    target.write_text("# Project\n\nprivate-but-allowed-synthetic-body", encoding="utf-8")
    index.write_text(json.dumps({"schema": "project-index/v1", "items": [
        {"id": "PRJ-111", "n": name}]}), encoding="utf-8")
    monkeypatch.setenv("JARVIS_OS_PROJECT_INDEX", "1")
    monkeypatch.setenv("JARVIS_OS_VAULT_INCLUDE", "Journal/Inbox;Projects/index.json;Projects/Register")
    node = next(n for n in TestClient(web.app).get("/api/os/brain").json()["nodes"] if n.get("projectId") == "PRJ-111")
    assert node["obsidianSource"] == {
        "vault": root.name, "file": "Projects/Register/" + name, "readable": True,
    }
    nfc_target = target.with_name("Café.md")
    if not nfc_target.exists():
        nfc_target.write_text("# Other project", encoding="utf-8")
        jarvis_os._engine().invalidate_brain_cache()
        node = next(n for n in TestClient(web.app).get("/api/os/brain").json()["nodes"] if n.get("projectId") == "PRJ-111")
        assert node["obsidianSource"]["readable"] is False


@pytest.mark.parametrize("name", [".Hidden.md", " Lead.md", "Trail.md ", "Trailing.",
                                  "Bad^caret.md", "Bad#hash.md", "Bad%escape.md", "Bad?query.md",
                                  "Bad<angle.md", "Bad\ncontrol.md", "bad\\slash.md"])
def test_native_source_rejects_unsafe_components(name):
    assert jarvis_os._engine()._native_note_source("Sample Vault", ("Notes", name), True) is None
