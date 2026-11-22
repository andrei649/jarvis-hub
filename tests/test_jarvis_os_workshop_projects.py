"""Saved workshop scenes use only guarded, indexed vault Markdown."""

import json
import threading
import urllib.parse
import urllib.request
from http.server import HTTPServer
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core.routers import jarvis_os


def robot():
    return {"version": 1, "view": "robot", "camera": {"position": [2, 1, 8], "target": [0, 0, 0]},
            "state": {"housingColor": "#AABBCC", "ringColor": "#112233", "shellColor": "#445566",
                      "metalness": 0.7, "roughness": 0.3, "explode": 0.2}}


def house():
    return {"version": 1, "view": "house", "camera": {"position": [-11, 18.5, 21.5], "target": [0, 0, 0]},
            "state": {"mode": "miniature", "centeredDoorNoStairs": True, "garageCars": True,
                      "livingRoomExtraMeters": 2, "kitchenExtraMeters": 1.5,
                      "poolBackPalmsAndFlowers": True, "poolLoungeChairs": False,
                      "showRoof": True, "roofVisibilityOverride": False,
                      "showRoomLabels": True, "explodedLayers": False}}


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "Vault"
    (root / "Journal" / "Inbox").mkdir(parents=True)
    monkeypatch.setenv("JARVIS_OS_VAULT_PATH", str(root))
    monkeypatch.setenv("JARVIS_OS_VAULT_INCLUDE", "Journal/Inbox")
    monkeypatch.setenv("JARVIS_OS_VAULT_INBOX", "Journal/Inbox")
    monkeypatch.setenv("JARVIS_OS_REPOSITORY_DOCS", "0")
    jarvis_os._engine().invalidate_brain_cache()
    return root


def test_roundtrip_versions_search_and_human_readable_note(vault):
    client = TestClient(web.app)
    title = "Garden Shed (roșu)"
    first = client.post("/api/os/workshop/projects", json={"title": title, "project": robot()})
    assert first.status_code == 200, first.text
    saved1 = first.json()
    assert set(saved1) == {"ok", "path", "title", "view"}
    assert saved1["path"].startswith("Journal/Inbox/")
    second = client.post("/api/os/workshop/projects", json={"title": title, "project": house()})
    assert second.status_code == 200, second.text
    saved2 = second.json()
    assert saved1["path"] != saved2["path"]
    assert "(2).md" in saved2["path"]
    assert sorted(client.get("/api/os/workshop/projects").json()["projects"], key=lambda x: x["path"]) == [
        {"path": saved2["path"], "title": saved2["title"], "view": "house"},
        {"path": saved1["path"], "title": saved1["title"], "view": "robot"},
    ]
    for saved, scene in ((saved1, robot()), (saved2, house())):
        loaded = client.get("/api/os/workshop/project", params={"path": saved["path"]})
        assert loaded.status_code == 200, loaded.text
        assert loaded.json()["project"] == scene
        assert loaded.json()["summary"]
        note = (vault / saved["path"]).read_text(encoding="utf-8")
        assert note.count("```nerva-workshop") == 1
        assert loaded.json()["summary"] in note
        assert note.count("# ") == 1
    results = client.get("/api/os/brain/retrieve", params={"q": "Garden Shed"}).json()["attachments"]
    assert any(item["name"] == saved1["path"] and "Robot scene" in item["text"] for item in results)


def test_rejects_hostile_input_without_writing(vault):
    client = TestClient(web.app)
    bad_color = robot()
    bad_color["state"]["housingColor"] = "javascript:alert(1)"
    bad_camera = robot()
    bad_camera["camera"]["position"] = [float("inf"), 1, 8]
    bad_extra = robot()
    bad_extra["extra"] = "ignore"
    for title, scene in (("bad\n```", robot()), ("Bad", bad_color), ("Bad", bad_camera),
                         ("Bad", bad_extra), ("", robot())):
        response = client.post("/api/os/workshop/projects", content=json.dumps({"title": title, "project": scene}),
                               headers={"Content-Type": "application/json"})
        assert response.status_code in (422, 400)
    assert not list(vault.rglob("*.md"))


def test_scope_repo_and_corrupt_note_boundaries(vault, monkeypatch):
    client = TestClient(web.app)
    path = client.post("/api/os/workshop/projects", json={"title": "Safe", "project": robot()}).json()["path"]
    outside = vault / "Other.md"
    outside.write_text((vault / path).read_text(encoding="utf-8"), encoding="utf-8")
    assert client.get("/api/os/workshop/project", params={"path": "Other.md"}).status_code == 404
    assert client.get("/api/os/workshop/project", params={"path": "../Other.md"}).status_code == 404
    assert client.get("/api/os/workshop/project", params={"path": str(outside)}).status_code == 404
    assert client.get("/api/os/workshop/projects").json()["projects"] == [
        {"path": path, "title": "Safe", "view": "robot"}]
    note = vault / path
    note.write_text(note.read_text(encoding="utf-8").replace('"version":1', '"version":99'), encoding="utf-8")
    assert client.get("/api/os/workshop/project", params={"path": path}).status_code == 422
    assert client.get("/api/os/workshop/projects").json()["projects"] == []
    monkeypatch.setenv("JARVIS_OS_VAULT_EXCLUDE", "Journal")
    assert client.get("/api/os/workshop/project", params={"path": path}).status_code == 404


def test_repeated_indexed_get_reopens_without_traversal(vault, monkeypatch):
    client = TestClient(web.app)
    path = client.post("/api/os/workshop/projects", json={"title": "Fast", "project": robot()}).json()["path"]
    engine = jarvis_os._engine()
    def no_walk(_cfg):
        raise AssertionError("indexed GET traversed the vault")
    monkeypatch.setattr(engine, "build_real_brain_graph", no_walk)
    for _ in range(2):
        assert client.get("/api/os/workshop/project", params={"path": path}).json()["project"] == robot()
    note = vault / path
    note.write_text(note.read_text(encoding="utf-8").replace('status: "inbox"', 'privacy: private'),
                    encoding="utf-8")
    assert client.get("/api/os/workshop/project", params={"path": path}).status_code == 404


def test_list_discovers_external_eligible_note(vault):
    client = TestClient(web.app)
    path = client.post("/api/os/workshop/projects", json={"title": "Seed", "project": robot()}).json()["path"]
    external = vault / "Journal" / "Inbox" / "External.md"
    external.write_text((vault / path).read_text(encoding="utf-8").replace(
        "Robot scene:", "Long Obsidian annotation: " + "a" * 4000 + "\n\nRobot scene:"), encoding="utf-8")
    engine = jarvis_os._engine()
    cfg = jarvis_os._config(engine)
    assert engine.read_indexed_note(cfg, "Journal/Inbox/External.md")[2]
    assert engine.workshop_projects.parse(engine.read_indexed_note(cfg, "Journal/Inbox/External.md")[2]) == robot()
    paths = {item["path"] for item in client.get("/api/os/workshop/projects").json()["projects"]}
    assert paths == {path, "Journal/Inbox/External.md"}
    external_node = next(node for node in engine.build_real_brain_graph(cfg)["nodes"]
                         if node.get("relPath") == "Journal/Inbox/External.md")
    assert external_node["workshopProject"] is True
    assert "```nerva-workshop" not in external_node["body"]


def test_list_does_not_silently_drop_versions_after_one_hundred():
    engine = jarvis_os._engine()
    paths = [f"Journal/Inbox/Version {number}.md" for number in range(101)]
    body = engine.workshop_projects.note_content(robot())
    fake = SimpleNamespace(
        SOURCE_VAULT="vault", _BRAIN_LOCK=threading.Lock(),
        _BRAIN_CACHE={"key": "fixed", "files": {path: ("vault", "root", ()) for path in paths}},
        _cache_key=lambda _cfg: "fixed",
        build_real_brain_graph=lambda _cfg: {"ok": True, "nodes": [{"relPath": path, "workshopProject": True} for path in paths]},
        read_indexed_note=lambda _cfg, path: (path, [], body, []),
    )
    assert len(engine.workshop_projects.list_projects(fake, {})) == 101


def test_deleted_note_is_not_listed_or_opened(vault):
    client = TestClient(web.app)
    path = client.post("/api/os/workshop/projects", json={"title": "Temporary", "project": robot()}).json()["path"]
    (vault / path).unlink()
    assert client.get("/api/os/workshop/projects").json()["projects"] == []
    assert client.get("/api/os/workshop/project", params={"path": path}).status_code == 404


def test_successful_create_with_failed_index_is_reported(vault, monkeypatch):
    engine = jarvis_os._engine()
    monkeypatch.setattr(engine, "build_real_brain_graph", lambda _cfg: {"ok": False})
    response = TestClient(web.app).post("/api/os/workshop/projects", json={"title": "Needs index", "project": robot()})
    assert response.status_code == 500
    assert response.json()["error"] == "project saved but could not be reopened"
    assert response.json()["path"] == "Journal/Inbox/Needs index.md"
    assert (vault / response.json()["path"]).is_file()


def test_missing_vault_does_not_create_store(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    monkeypatch.setenv("JARVIS_OS_VAULT_PATH", str(missing))
    response = TestClient(web.app).post("/api/os/workshop/projects", json={"title": "Safe", "project": robot()})
    assert response.status_code == 409
    assert not missing.exists()


def test_standalone_api_uses_same_scene_contract(vault, monkeypatch):
    engine = jarvis_os._engine()
    cfg = {"vaultPath": str(vault), "vaultMode": "andrei_os", "vaultInclude": "Journal/Inbox",
           "vaultInbox": "Journal/Inbox", "vaultExclude": ""}
    monkeypatch.setattr(engine, "load_config", lambda: cfg)
    server = HTTPServer(("127.0.0.1", 0), engine.JarvisRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/api/workshop/projects",
                                     data=json.dumps({"title": "Standalone", "project": robot()}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            saved = json.load(response)
        assert set(saved) == {"ok", "path", "title", "view"}
        with urllib.request.urlopen(base + "/api/workshop/projects", timeout=5) as response:
            assert json.load(response)["projects"] == [{"path": saved["path"], "title": "Standalone", "view": "robot"}]
        query = urllib.parse.urlencode({"path": saved["path"]})
        with urllib.request.urlopen(base + "/api/workshop/project?" + query, timeout=5) as response:
            loaded = json.load(response)
        assert loaded["project"] == robot()
        assert "housing #AABBCC" in loaded["summary"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
