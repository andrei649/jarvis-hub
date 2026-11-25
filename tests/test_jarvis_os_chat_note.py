"""Explicit Chat -> Obsidian saves use the configured, pinned inbox."""

import concurrent.futures
import hashlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core.routers import jarvis_os


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    root = tmp_path / "Sample Vault"
    folder = root / "Journal" / "Inbox"
    folder.mkdir(parents=True)
    monkeypatch.setenv("JARVIS_OS_VAULT_PATH", str(root))
    monkeypatch.setenv("JARVIS_OS_VAULT_INCLUDE", "Journal/Inbox")
    monkeypatch.setenv("JARVIS_OS_VAULT_INBOX", "Journal/Inbox")
    return root, folder, TestClient(web.app)


def body(client, *, request_id=None, title="Reviewed note", content="Line one\n\nLine two\n"):
    target = client.get("/api/os/status").json()["captureTarget"]
    assert target and target["inbox"] == "Journal/Inbox"
    return {"targetId": target["id"], "requestId": request_id or str(uuid.uuid4()),
            "title": title, "content": content}


def test_exact_bytes_receipt_and_retry(inbox):
    root, folder, client = inbox
    request = body(client, content="\n  edited body\n\n")
    first = client.post("/api/os/brain/chat-note", json=request)
    assert first.status_code == 200, first.text
    saved = first.json()
    assert saved == {"ok": True, "relPath": "Journal/Inbox/Reviewed note.md",
                     "source": {"vault": root.name, "file": saved["relPath"], "readable": True}}
    assert "no-store" in first.headers["cache-control"]
    assert (folder / saved["relPath"].split("/")[-1]).read_bytes() == request["content"].encode()
    assert client.post("/api/os/brain/chat-note", json=request).json() == saved
    assert client.post("/api/os/brain/chat-note", json={**request,
        "requestId": request["requestId"].upper()}).json() == saved
    assert len(list(folder.glob("*.md"))) == 1


def test_reopen_saved_note_reads_current_public_body_at_original_destination(inbox, tmp_path, monkeypatch):
    root, folder, client = inbox
    request = body(client)
    saved = client.post("/api/os/brain/chat-note", json=request).json()
    params = {"targetId": request["targetId"], "relPath": saved["relPath"]}
    live = "Subiect\n" + "o" * 6_100 + "\nUltima linie."
    path = folder / "Reviewed note.md"
    path.write_bytes(live.encode())
    opened = client.get("/api/os/brain/note", params=params)
    assert opened.status_code == 200 and opened.json() == {"ok": True, **params, "body": live}
    assert "no-store" in opened.headers["cache-control"]
    preview = client.get("/api/os/brain/note", params={"relPath": saved["relPath"]})
    assert preview.json()["body"] == live[:6000]
    path.write_bytes(b"a" * 100_001)
    assert client.get("/api/os/brain/note", params=params).status_code == 413
    path.write_bytes(b"---\nprivacy: private\n---\nprivate edit")
    assert client.get("/api/os/brain/note", params=params).status_code == 404
    other = tmp_path / "replacement" / root.name
    (other / "Journal" / "Inbox").mkdir(parents=True)
    (other / saved["relPath"]).write_bytes(b"Different vault with the same name")
    monkeypatch.setenv("JARVIS_OS_VAULT_PATH", str(other))
    switched = client.get("/api/os/brain/note", params=params)
    assert switched.status_code in (404, 409) and "Different vault" not in switched.text


def test_reopen_scopes_the_read_to_the_pinned_inbox(inbox, monkeypatch):
    root, folder, client = inbox
    monkeypatch.setenv("JARVIS_OS_VAULT_INCLUDE", "")
    target = body(client)["targetId"]
    (root / "Outside.md").write_text("elsewhere", encoding="utf-8")
    for rel in ("Outside.md", "Nerva/jarvis-hub/README.md", "Journal/Inbox/../../Outside.md"):
        assert client.get("/api/os/brain/note", params={"targetId": target, "relPath": rel}).status_code == 404
    (folder / "Note.md").write_text("old", encoding="utf-8")
    folder.rename(root / "Journal" / "Former inbox")
    folder.mkdir()
    (folder / "Note.md").write_text("new", encoding="utf-8")
    changed = client.get("/api/os/brain/note", params={"targetId": target, "relPath": "Journal/Inbox/Note.md"})
    assert changed.status_code in (404, 409) and "new" not in changed.text


def test_conflicting_reuse_or_user_edit_never_clobbers(inbox):
    _root, folder, client = inbox
    request = body(client)
    response = client.post("/api/os/brain/chat-note", json=request)
    assert response.status_code == 200
    file = folder / response.json()["relPath"].split("/")[-1]
    changed = {**request, "content": "another intent"}
    assert client.post("/api/os/brain/chat-note", json=changed).status_code == 409
    changed = {**request, "title": "Other title"}
    assert client.post("/api/os/brain/chat-note", json=changed).status_code == 409
    file.write_text("owner edit", encoding="utf-8")
    edited = client.post("/api/os/brain/chat-note", json=request)
    assert edited.status_code == 409 and edited.json()["code"] == "note_changed"
    assert file.read_text(encoding="utf-8") == "owner edit"
    assert len(list(folder.glob("*.md"))) == 1


def test_independent_title_collision_never_overwrites(inbox):
    _root, folder, client = inbox
    first = body(client, title="Shared title", content="first")
    second = body(client, title="Shared title", content="second")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda request: client.post("/api/os/brain/chat-note", json=request),
                                  (first, second)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["code"] == "title_conflict"
    assert (folder / "Shared title.md").read_bytes() in (b"first", b"second")
    assert len(list(folder.glob("*.md"))) == 1
    # A second intent with identical reviewed bytes can acknowledge the existing note.
    same = body(client, title="Shared title", content=(folder / "Shared title.md").read_text())
    assert client.post("/api/os/brain/chat-note", json=same).status_code == 200
    assert len(list(folder.glob("*.md"))) == 1


def test_concurrent_publication_reserves_title_before_temporary_link_is_removed(inbox):
    _root, folder, client = inbox
    temporary = folder / ".in-flight.tmp"
    temporary.write_bytes(b"winner")
    final = folder / "Shared.md"
    final.hardlink_to(temporary)
    request = body(client, title="Shared", content="second")
    response = client.post("/api/os/brain/chat-note", json=request)
    assert response.status_code == 409 and response.json().get("code") == "title_conflict"
    temporary.unlink()
    assert final.read_bytes() == b"winner"
    retry = body(client, title="Shared", content="winner")
    assert client.post("/api/os/brain/chat-note", json=retry).status_code == 200


@pytest.mark.parametrize("title, expected", [
    ("CON", "CON-Note.md"),
    ("AUX.txt", "AUX-Note.txt.md"),
    ("Meeting.md", "Meeting.md"),
    ("Unsafe #/% title", "Unsafe --- title.md"),
])
def test_native_safe_readable_basename(inbox, title, expected):
    _root, folder, client = inbox
    result = client.post("/api/os/brain/chat-note", json=body(client, title=title, content="body"))
    assert result.status_code == 200, result.text
    assert result.json()["relPath"].endswith("/" + expected)
    assert (folder / expected).read_bytes() == b"body"


def test_unicode_title_stays_in_component_limit(inbox):
    _root, folder, client = inbox
    title = "📚" * 120
    result = client.post("/api/os/brain/chat-note", json=body(client, title=title, content="body"))
    assert result.status_code == 200, result.text
    name = result.json()["relPath"].split("/")[-1]
    assert name.startswith("📚") and name.endswith(".md") and "- " not in name
    assert len(name.encode("utf-8")) <= 255
    assert len(name.encode("utf-16-le")) // 2 <= 255
    assert (folder / name).read_bytes() == b"body"


def test_legacy_uuid_filename_replay(inbox):
    _root, folder, client = inbox
    request = body(client, title="Old title", content="old body\n")
    name = f"Old title - {request['requestId']}.md"
    (folder / name).write_bytes(request["content"].encode())
    receipt = {"title": request["title"], "sha256": hashlib.sha256(request["content"].encode()).hexdigest()}
    (folder / f".chat-note-{request['requestId']}.json").write_text(
        json.dumps(receipt, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    response = client.post("/api/os/brain/chat-note", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["relPath"] == f"Journal/Inbox/{name}"
    assert not (folder / "Old title.md").exists()


def test_stale_target_root_and_inbox_switch_and_invalid_scope(inbox, tmp_path, monkeypatch):
    root, folder, client = inbox
    request = body(client)
    other = tmp_path / "Other Vault"
    (other / "Journal" / "Inbox").mkdir(parents=True)
    monkeypatch.setenv("JARVIS_OS_VAULT_PATH", str(other))
    assert client.post("/api/os/brain/chat-note", json=request).status_code == 409
    monkeypatch.setenv("JARVIS_OS_VAULT_PATH", str(root))
    monkeypatch.setenv("JARVIS_OS_VAULT_INBOX", "Journal/Missing")
    assert client.get("/api/os/status").json()["captureTarget"] is None
    assert client.post("/api/os/brain/chat-note", json=request).status_code == 409
    monkeypatch.setenv("JARVIS_OS_VAULT_INBOX", "Journal/Inbox")
    folder.rename(root / "Journal" / "Old Inbox")
    (root / "Journal" / "Inbox").mkdir()
    assert client.post("/api/os/brain/chat-note", json=request).status_code == 409


def test_status_does_not_create_missing_inbox(inbox, monkeypatch):
    root, _folder, client = inbox
    monkeypatch.setenv("JARVIS_OS_VAULT_INBOX", "Journal/New Inbox")
    response = client.get("/api/os/status").json()
    assert response["captureTarget"] is None
    assert "existing allowed vault inbox" in response["captureUnavailableReason"]
    assert not (root / "Journal" / "New Inbox").exists()


def test_default_inbox_first_save_creates_only_on_post(inbox, monkeypatch):
    root, _folder, client = inbox
    monkeypatch.delenv("JARVIS_OS_VAULT_INBOX")
    monkeypatch.delenv("JARVIS_OS_VAULT_INCLUDE")
    status = client.get("/api/os/status").json()
    assert status["captureTarget"]["inbox"] == "08 Inbox"
    assert not (root / "08 Inbox").exists()
    request = {"targetId": status["captureTarget"]["id"], "requestId": str(uuid.uuid4()),
               "title": "First note", "content": "exact\n"}
    first = client.post("/api/os/brain/chat-note", json=request)
    assert first.status_code == 200, first.text
    assert (root / "08 Inbox" / first.json()["relPath"].split("/")[-1]).read_bytes() == b"exact\n"
    assert client.get("/api/os/status").json()["captureTarget"]["id"] == request["targetId"]
    assert client.post("/api/os/brain/chat-note", json=request).json() == first.json()


def test_default_inbox_denied_by_policy_stays_absent(inbox, monkeypatch):
    root, _folder, client = inbox
    monkeypatch.delenv("JARVIS_OS_VAULT_INBOX")
    status = client.get("/api/os/status").json()
    assert status["captureTarget"] is None
    response = client.post("/api/os/brain/chat-note", json={
        "targetId": "v1-" + "0" * 64, "requestId": str(uuid.uuid4()), "title": "No", "content": "body"})
    assert response.status_code == 409
    assert not (root / "08 Inbox").exists()


def test_concurrent_same_request_and_unsafe_native_source(inbox, monkeypatch):
    root, folder, client = inbox
    request = body(client, title="📚" * 120, content="concurrent\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post("/api/os/brain/chat-note", json=request), range(4)))
    assert all(response.status_code == 200 for response in responses), [r.text for r in responses]
    assert all(response.json() == responses[0].json() for response in responses)
    assert len(list(folder.glob("*.md"))) == 1
    assert len(next(folder.glob("*.md")).name.encode("utf-8")) <= 255
    unsafe = root.parent / "Unsafe # Vault"
    unsafe.mkdir()
    (unsafe / "Journal" / "Inbox").mkdir(parents=True)
    monkeypatch.setenv("JARVIS_OS_VAULT_PATH", str(unsafe))
    result = client.post("/api/os/brain/chat-note", json=body(client, title="unsafe # title"))
    assert result.status_code == 200
    assert result.json()["source"] is None


def test_partial_write_is_never_published(inbox, monkeypatch):
    _root, folder, client = inbox
    request = body(client)
    api = jarvis_os._engine().vault_fs._platform_api()
    original = api.write

    def fail_after_prefix(handle, data):
        original(handle, data[:3])
        raise OSError("interrupted write")

    monkeypatch.setattr(jarvis_os._engine().vault_fs, "_platform_api", lambda: api)
    monkeypatch.setattr(api, "write", fail_after_prefix)
    response = client.post("/api/os/brain/chat-note", json=request)
    assert response.status_code == 500
    assert not list(folder.iterdir())


def test_retry_finishes_after_marker_only_crash(inbox, monkeypatch):
    _root, folder, client = inbox
    request = body(client)
    fs_type = jarvis_os._engine().vault_fs.VaultFs
    original = fs_type.publish_in

    def fail_note_once(self, directory, name, data):
        if name.endswith(".md"):
            raise OSError("interrupted before note publish")
        return original(self, directory, name, data)

    with monkeypatch.context() as patch:
        patch.setattr(fs_type, "publish_in", fail_note_once)
        assert client.post("/api/os/brain/chat-note", json=request).status_code == 500
    assert not list(folder.glob("*.md"))
    result = client.post("/api/os/brain/chat-note", json=request)
    assert result.status_code == 200, result.text
    assert len(list(folder.glob("*.md"))) == 1


def test_structured_body_and_user_guard(inbox, monkeypatch):
    _root, _folder, client = inbox
    request = body(client)
    for bad in ({**request, "requestId": "not-uuid"}, {**request, "extra": "x"},
                {**request, "targetId": "wrong"}, {**request, "title": " "},
                {**request, "content": "\n "}, {**request, "content": "x" * 100_001}):
        assert client.post("/api/os/brain/chat-note", json=bad).status_code == 422
    for bad in ({**request, "content": "\ud800"}, {**request, "title": "\ud800"}):
        assert client.post("/api/os/brain/chat-note", content=json.dumps(bad)).status_code == 422
    operation = client.get("/openapi.json").json()["paths"]["/api/os/brain/chat-note"]["post"]
    assert "ChatNoteReceipt" in str(operation["responses"]["200"])
    from agents.core.routers._deps import user_guard
    monkeypatch.delitem(web.app.dependency_overrides, user_guard, raising=False)
    monkeypatch.delenv("JARVIS_USER_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    remote = TestClient(web.app, client=("8.8.8.8", 12345))
    assert remote.post("/api/os/brain/chat-note", json=request).status_code in (401, 403)
