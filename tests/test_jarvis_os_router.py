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


def test_fenced_passages_are_searchable_without_creating_note_links(client, vault):
    text = ("[[Plans]]\n\n````text\n[[Literal]] and [label](example.md)\n"
            "```\n[[Still literal]]\n````\n  ~~~\n[[Example]]\n  ~~~\n[Report](report.md)\n")
    (vault / "02 Proiecte" / "Handoff.md").write_text(text, encoding="utf-8")
    note = client.get("/api/os/brain/note", params={"relPath": "02 Proiecte/Handoff.md"}).json()
    assert note["wikilinks"] == ["Plans", "report"]
    assert "[[Still literal]]" in note["body"]


def test_note_reads_a_vault_file_and_a_repo_doc(client, vault):
    note = client.get("/api/os/brain/note", params={"relPath": "02 Proiecte/Atelier iPod.md"}).json()
    assert note["ok"] is True and note["title"] == "Atelier iPod" and "Acasa" in note["wikilinks"]
    doc = client.get("/api/os/brain/note", params={"relPath": "Nerva/jarvis-hub/NERVA.md"})
    assert doc.status_code == 200 and doc.json()["ok"] is True


def test_note_reader_opens_at_the_late_match_and_preserves_the_default_view(client, vault):
    prefix = "Ordinary studio notes.\n\n" * 410
    lesson = "Spectroscope calibration uses the indigo reference."
    text = prefix + lesson + "\n\n" + "Studio log. " * 620
    (vault / "02 Proiecte" / "Log.md").write_bytes(text.encode("utf-8"))
    url = "/api/os/brain/note"
    params = {"relPath": "02 Proiecte/Log.md"}
    first = client.get(url, params=params).json()
    assert first["body"] == text[:6000] and "start" not in first
    match = client.get(url, params={**params, "q": "spectroscope calibration"}).json()
    assert match["start"] > 6000 and lesson in match["body"]
    assert match["body"] == text[match["start"]:match["start"] + 6000]
    unrelated = client.get(url, params={**params, "q": "nohitsanywhere"}).json()
    assert unrelated["body"] == first["body"]


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
    engine = jarvis_os._engine()
    monkeypatch.setattr(engine, "build_real_brain_graph", lambda *args, **kwargs: pytest.fail("unexpected vault walk"))
    assert client.get("/api/os/brain/retrieve", params={"q": "ce este"}).json()["attachments"] == []
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


def test_capture_never_overwrites_an_existing_note(client, vault):
    first = client.post("/api/os/brain/capture", json={"title": "Idee", "content": "prima"}).json()
    second = client.post("/api/os/brain/capture", json={"title": "Idee", "content": "a doua"}).json()
    one, two = Path(first["path"]), Path(second["path"])
    assert one != two and two.name == "Idee (2).md"
    assert "prima" in one.read_text(encoding="utf-8")
    assert "a doua" in two.read_text(encoding="utf-8")
    assert second["node"]["title"] == "Idee (2)"


# ── the standalone server (apps/jarvis-os/server.py) ─────────────

@pytest.fixture
def standalone(vault, monkeypatch):
    """The real standalone server on a free loopback port, pointed at the temp vault."""
    import http.client
    import threading

    engine = jarvis_os._engine()
    cfg = {"vaultMode": "andrei_os", "vaultPath": str(vault), "nervaPath": str(repo_root)}
    monkeypatch.setattr(engine, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(engine, "save_config", lambda updates: pytest.fail("config was written"))
    server = engine.ReusableThreadingHTTPServer(("127.0.0.1", 0), engine.JarvisRequestHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def call(method, path, *, origin=None, host=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{port}"}
        if origin:
            headers["Origin"] = origin
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        payload = response.read().decode("utf-8", "replace")
        conn.close()
        return response, payload

    call.port = port
    yield call
    server.shutdown()
    server.server_close()


def test_standalone_access_log_omits_note_query(standalone, capsys):
    standalone("GET", "/api/brain/note?relPath=synthetic-private-note")
    output = capsys.readouterr().out
    assert "GET /api/brain/note HTTP" in output
    assert "synthetic-private-note" not in output


def test_standalone_serves_its_own_page_and_api(standalone):
    response, body = standalone("GET", "/api/brain/note?relPath=00%20Acasa/Acasa.md",
                                origin=f"http://localhost:{standalone.port}",
                                host=f"localhost:{standalone.port}")
    assert response.status == 200 and "Indexul principal" in body
    assert response.getheader("Access-Control-Allow-Origin") is None
    assert standalone("GET", "/api/brain")[0].status == 200          # no Origin: a script or curl
    assert standalone("GET", "/")[0].status == 200
    script, _body = standalone("GET", "/js/main.js")
    assert script.status == 200 and script.getheader("Content-Type").startswith("text/javascript")


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/brain", None),
    ("GET", "/api/brain/note?relPath=00%20Acasa/Acasa.md", None),
    ("GET", "/api/status", None),
    ("POST", "/api/config", '{"vaultPath": "/"}'),
    ("POST", "/api/brain/capture", '{"title": "x", "content": "y"}'),
    ("OPTIONS", "/api/config", None),
])
def test_standalone_refuses_another_sites_requests(standalone, vault, method, path, body):
    response, payload = standalone(method, path, origin="https://evil.example", body=body)
    assert response.status == 403
    assert response.getheader("Access-Control-Allow-Origin") is None
    assert "Indexul principal" not in payload
    assert not (vault / "08 Inbox").exists()


def test_standalone_refuses_a_rebound_hostname(standalone):
    response, payload = standalone("GET", "/api/brain/note?relPath=00%20Acasa/Acasa.md",
                                   host=f"evil.example:{standalone.port}")
    assert response.status == 403 and "Indexul principal" not in payload


def test_standalone_note_cannot_read_a_sibling_folder(standalone, vault):
    sibling = vault.parent / (vault.name + "-private")
    sibling.mkdir()
    (sibling / "secret.txt").write_text("do not read", encoding="utf-8")
    for rel in (f"../{sibling.name}/secret.txt", "../outside.md"):
        response, payload = standalone("GET", "/api/brain/note?relPath=" + rel.replace(" ", "%20"))
        assert response.status == 404, rel
        assert "do not read" not in payload and "not part of the vault" not in payload


def test_hub_posts_carry_the_session_csrf_token():
    """The page's one API module reads the owner session and echoes its CSRF token."""
    source = (PUBLIC / "js" / "api.js").read_text(encoding="utf-8")
    assert "/api/auth/session" in source and '"X-CSRF-Token"' in source
    assert 'credentials: "same-origin"' in source


def test_loading_the_standalone_app_leaves_the_hubs_mime_types_alone(client):
    """The hub imports apps/jarvis-os/server.py; that must not re-register `.js` for the
    whole process, or the hub's own bundles change content type."""
    import importlib.util
    import mimetypes

    names = ("bundle.js", "module.mjs", "style.css", "icon.svg", "data.json")
    before = [mimetypes.guess_type(name) for name in names]
    source = repo_root / "apps" / "jarvis-os" / "server.py"
    spec = importlib.util.spec_from_file_location("jarvis_os_fresh_load", source)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert [mimetypes.guess_type(name) for name in names] == before
    handler = jarvis_os._engine().JarvisRequestHandler
    assert handler.extensions_map[".js"] == "text/javascript"
    assert client.get("/os/js/main.js").headers["content-type"].startswith("text/javascript")
