"""The ANDREI OS interface on the hub: the `/os` page and the `/api/os/*` vault routes.

The page is the standalone app from `apps/jarvis-os/public`; served by the hub it must
run under the hub's CSP (no third-party hosts), call the hub instead of its own backend,
and reach personal vault notes only through guarded routes that cannot leave the vault.
"""
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web  # noqa: E402
from agents.core.routers import jarvis_os  # noqa: E402

PUBLIC = repo_root / "apps" / "jarvis-os" / "public"


@pytest.fixture
def client():
    return TestClient(web.app)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """A small vault the hub is pointed at, plus a file beside it that must stay out."""
    root = tmp_path / "Vault"
    (root / "02 Proiecte").mkdir(parents=True)
    (root / "02 Proiecte" / "Atelier iPod.md").write_text(
        "---\ntitle: \"Atelier iPod\"\ntags: [hobby]\n---\n\nRestaurare iPod Classic cu [[Acasa]].\n",
        encoding="utf-8")
    (root / "00 Acasa").mkdir()
    (root / "00 Acasa" / "Acasa.md").write_text("# Acasa\n\nIndexul principal.\n", encoding="utf-8")
    (tmp_path / "outside.md").write_text("not part of the vault", encoding="utf-8")
    monkeypatch.setenv(jarvis_os.VAULT_ENV, str(root))
    engine = jarvis_os._engine()
    engine.invalidate_brain_cache()
    yield root
    engine.invalidate_brain_cache()


# ── page shell + assets ──────────────────────────────────────────

def test_os_redirects_to_the_trailing_slash(client):
    response = client.get("/os", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/os/"


def test_shell_is_marked_for_the_hub_and_has_no_third_party_hosts(client):
    response = client.get("/os/")
    assert response.status_code == 200
    assert '<meta name="jarvis-os-hub" content="" />' in response.text
    # The hub's CSP allows only same-origin scripts, styles and fonts.
    head = response.text.split("</head>", 1)[0]
    assert "https://" not in head
    assert '"three": "./vendor/three/three.module.js"' in head


def test_every_local_asset_the_shell_names_is_served(client):
    page = client.get("/os/").text
    names = set(re.findall(r'(?:src|href)="((?:css|js|assets|vendor)/[^"]+)"', page))
    names |= {"vendor/three/three.module.js", "vendor/three/addons/controls/OrbitControls.js",
              "vendor/three/addons/environments/RoomEnvironment.js", "js/api.js"}
    assert {"css/styles.css", "js/main.js"} <= names
    for name in sorted(names):
        response = client.get(f"/os/{name}")
        assert response.status_code == 200, name
    assert client.get("/os/js/main.js").headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("path", [
    "/os/../server.py", "/os/%2e%2e/server.py", "/os/..%2fserver.py",
    "/os/%2e%2e%2f%2e%2e%2fREADME.md", "/os/js/../../config.example.json",
])
def test_assets_cannot_leave_the_public_folder(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert "ThreadingHTTPServer" not in response.text


def test_the_page_calls_no_backend_except_through_the_api_module():
    for script in (PUBLIC / "js").glob("*.js"):
        if script.name != "api.js":
            assert "fetch(" not in script.read_text(encoding="utf-8"), script.name


# ── vault routes ─────────────────────────────────────────────────

def test_status_names_the_hub_and_this_checkout(client, vault):
    body = client.get("/api/os/status").json()
    assert body["ok"] is True and body["backend"] == "hub"
    assert body["vaultAvailable"] is True and Path(body["vaultPath"]) == vault
    assert Path(body["nervaPath"]) == repo_root


def test_brain_without_a_vault_answers_demo_mode(client, tmp_path, monkeypatch):
    monkeypatch.setenv(jarvis_os.VAULT_ENV, str(tmp_path / "missing"))
    body = client.get("/api/os/brain").json()
    assert body["ok"] is True and body["mode"] == "demo_550" and "nodes" not in body
    assert client.get("/api/os/status").json()["vaultMode"] == "demo_550"


def test_brain_graph_holds_the_vault_notes_and_their_links(client, vault):
    body = client.get("/api/os/brain?reindex=1").json()
    by_title = {node["title"]: node for node in body["nodes"]}
    assert {"Atelier iPod", "Acasa"} <= set(by_title)
    linked = {tuple(edge) for edge in body["edges"]}
    a, b = sorted((by_title["Atelier iPod"]["index"], by_title["Acasa"]["index"]))
    assert (a, b) in linked
    assert any(node.get("sourceVault") == "Nerva Jarvis Hub" for node in body["nodes"])


def test_note_reads_a_vault_file_and_a_repo_doc(client, vault):
    note = client.get("/api/os/brain/note", params={"relPath": "02 Proiecte/Atelier iPod.md"}).json()
    assert note["ok"] is True and note["title"] == "Atelier iPod" and "Acasa" in note["wikilinks"]
    doc = client.get("/api/os/brain/note", params={"relPath": "Nerva/jarvis-hub/NERVA.md"})
    assert doc.status_code == 200 and doc.json()["ok"] is True


@pytest.mark.parametrize("rel", [
    "../outside.md", "02 Proiecte/../../outside.md", "Nerva/jarvis-hub/../outside.md",
    "Nerva/jarvis-hub/.env.example", "Nerva/jarvis-hub/agents/web.py", "", "02 Proiecte",
])
def test_note_refuses_paths_outside_the_indexed_sources(client, vault, rel):
    response = client.get("/api/os/brain/note", params={"relPath": rel})
    assert response.status_code == 404
    assert response.json() == {"ok": False, "error": "note not found"}


def test_retrieve_returns_chat_attachments_and_a_focus_title(client, vault):
    body = client.get("/api/os/brain/retrieve", params={"q": "ce stii despre atelier ipod"}).json()
    assert body["focus"] == "Atelier iPod"
    first = body["attachments"][0]
    assert set(first) == {"name", "text"} and "Restaurare iPod" in first["text"]
    # The shape /chat accepts: at most 8 attachments, bounded name and text.
    assert len(body["attachments"]) <= 8
    for item in body["attachments"]:
        web.ChatAttachment(**item)


def test_retrieve_with_no_question_or_no_vault_is_empty(client, vault, tmp_path, monkeypatch):
    assert client.get("/api/os/brain/retrieve").json() == {"ok": True, "attachments": [], "focus": None}
    monkeypatch.setenv(jarvis_os.VAULT_ENV, str(tmp_path / "missing"))
    body = client.get("/api/os/brain/retrieve", params={"q": "ipod"}).json()
    assert body == {"ok": True, "attachments": [], "focus": None}


def test_capture_writes_into_the_inbox_only(client, vault):
    response = client.post("/api/os/brain/capture",
                           json={"title": "../../Idee: noua?", "content": "De verificat."})
    body = response.json()
    assert response.status_code == 200 and body["ok"] is True
    written = Path(body["path"])
    assert written.parent == vault / "08 Inbox" and written.is_file()
    assert "De verificat." in written.read_text(encoding="utf-8")
    assert [p.name for p in vault.parent.iterdir()].count("outside.md") == 1
    assert not list(vault.parent.glob("*Idee*"))


def test_capture_needs_content_and_a_vault(client, vault, tmp_path, monkeypatch):
    assert client.post("/api/os/brain/capture", json={"title": " ", "content": ""}).status_code == 422
    monkeypatch.setenv(jarvis_os.VAULT_ENV, str(tmp_path / "missing"))
    response = client.post("/api/os/brain/capture", json={"title": "x", "content": "y"})
    assert response.status_code == 409
    assert not (tmp_path / "missing").exists()


def test_vault_routes_are_refused_from_the_network(vault, monkeypatch):
    # conftest replaces the user guard for the whole suite; this test wants the real one.
    from agents.core.routers._deps import user_guard
    monkeypatch.delitem(web.app.dependency_overrides, user_guard, raising=False)
    monkeypatch.delenv("JARVIS_USER_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    remote = TestClient(web.app, client=("203.0.113.9", 50000))
    for path in ("/api/os/status", "/api/os/brain", "/api/os/brain/retrieve?q=ipod",
                 "/api/os/brain/note?relPath=00%20Acasa/Acasa.md"):
        assert remote.get(path).status_code in (401, 403), path
    assert remote.post("/api/os/brain/capture", json={"title": "x", "content": "y"}).status_code in (401, 403)
    assert not (vault / "08 Inbox").exists()
