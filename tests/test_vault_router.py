"""T-0.20 — the HTTP surface over agents/core/vault.py (list/put/get/delete).

The vault core (crypto, atomic commits, quotas) already had full coverage in
tests/test_vault.py with zero live callers; these tests cover the route layer:
wiring, the HTTP-specific size cap, base64 handling, user-tier auth, and that
content never appears in a listing (only on an explicit per-item GET).
"""

import asyncio
import base64
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.routers import vault as vault_router  # noqa: E402
from core.vault import Vault  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_vault(tmp_path, monkeypatch):
    """Every test gets its own on-disk vault instead of the real default root."""
    v = Vault(tmp_path / "v", key="router-test-passphrase")
    monkeypatch.setattr(vault_router, "_VAULT_SINGLETON", v)
    yield v


def test_get_vault_returns_the_patched_singleton(_isolated_vault):
    assert vault_router._get_vault() is _isolated_vault


def test_list_endpoint_returns_items_and_stats():
    body = asyncio.run(vault_router.vault_list())
    import json
    payload = json.loads(body.body)
    assert payload["items"] == []
    assert payload["stats"]["items"] == 0


def test_put_then_list_never_leaks_content_only_get_does(_isolated_vault):
    text = b"a family document nobody else should read"
    put_body = vault_router.VaultPutBody(
        name="doc.txt", kind="document",
        data_base64=base64.b64encode(text).decode("ascii"),
    )
    put_resp = asyncio.run(vault_router.vault_put(put_body))
    import json
    put_payload = json.loads(put_resp.body)
    assert put_payload["ok"] is True
    vid = put_payload["entry"]["id"]
    assert "data_base64" not in put_payload["entry"]

    list_resp = asyncio.run(vault_router.vault_list())
    list_payload = json.loads(list_resp.body)
    assert len(list_payload["items"]) == 1
    assert "data_base64" not in list_payload["items"][0]
    blob = json.dumps(list_payload).encode()
    assert text not in blob  # the listing never carries plaintext

    get_resp = asyncio.run(vault_router.vault_get(vid))
    get_payload = json.loads(get_resp.body)
    assert base64.b64decode(get_payload["data_base64"]) == text
    assert get_payload["name"] == "doc.txt"


def test_put_rejects_invalid_base64():
    bad = vault_router.VaultPutBody(name="x", data_base64="not-valid-base64!!!")
    resp = asyncio.run(vault_router.vault_put(bad))
    assert resp.status_code == 400


def test_put_rejects_over_the_http_size_cap(monkeypatch):
    monkeypatch.setattr(vault_router, "_MAX_HTTP_ITEM_BYTES", 10)
    body = vault_router.VaultPutBody(
        name="big", data_base64=base64.b64encode(b"x" * 100).decode("ascii"),
    )
    resp = asyncio.run(vault_router.vault_put(body))
    assert resp.status_code == 413


def test_get_missing_item_is_a_clean_404():
    resp = asyncio.run(vault_router.vault_get("nonexistent12345"))
    assert resp.status_code == 404


def test_delete_removes_and_reports_honestly(_isolated_vault):
    put_body = vault_router.VaultPutBody(
        name="n", data_base64=base64.b64encode(b"bye").decode("ascii"),
    )
    put_resp = asyncio.run(vault_router.vault_put(put_body))
    import json
    vid = json.loads(put_resp.body)["entry"]["id"]

    del_resp = asyncio.run(vault_router.vault_delete(vid))
    assert json.loads(del_resp.body) == {"ok": True, "removed": True}

    del_again = asyncio.run(vault_router.vault_delete(vid))
    assert json.loads(del_again.body) == {"ok": True, "removed": False}


def test_routes_registered_and_user_guarded():
    routes = {r.path: r for r in vault_router.router.routes}
    for path in ("/api/vault", "/api/vault/{vault_id}"):
        assert path in routes
    for route in vault_router.router.routes:
        names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "user_guard" in names, f"{route.path} must be user-guarded"


def test_http_roundtrip_through_the_real_app(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from agents import web

    v = Vault(tmp_path / "http-v", key="http-test-passphrase")
    monkeypatch.setattr(vault_router, "_VAULT_SINGLETON", v)
    client = TestClient(web.app)

    r = client.post("/api/vault", json={
        "name": "n", "data_base64": base64.b64encode(b"hi").decode("ascii"),
    })
    assert r.status_code == 200
    vid = r.json()["entry"]["id"]

    r = client.get("/api/vault")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1

    r = client.get(f"/api/vault/{vid}")
    assert r.status_code == 200
    assert base64.b64decode(r.json()["data_base64"]) == b"hi"

    r = client.delete(f"/api/vault/{vid}")
    assert r.status_code == 200
    assert r.json()["removed"] is True
