"""T-0.58 — the typed Pack Manager surface.

0.58's remaining scope read "model/domain/content pack types are separate". It
turned out the *content/domain* type already had a full implementation —
`knowledge_packs.py` (manifest / verify / install-plan over the drop-folder
indexer) — with **zero callers**: no route, no HUD, only its own unit test, the
same built-but-unwired shape `signal_routing.py` and `vault.py` had. So this
closes the row by giving pack types one real typed surface, not by inventing an
empty taxonomy on top of `skill`.

`model` packs are deliberately declared UNSUPPORTED rather than stubbed: Nerva
does not distribute model weights (models come from LM Studio / Ollama), so a
`model` pack type would be a label with nothing behind it — exactly the
"looks done, isn't wired" failure the V2 readiness ladder exists to catch.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

# Import via the `agents.` path — the same module object agents/web.py mounts.
from agents.core.knowledge_packs import build_manifest, write_manifest  # noqa: E402
from agents.core.routers import packs as packs_router  # noqa: E402


def _pack_folder(tmp_path, name="demo", version="1.0.0", body="hello world"):
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "doc.md").write_text(body, encoding="utf-8")
    write_manifest(folder, build_manifest(folder, name=name, version=version))
    return folder


def _orch(folders=None, skills=None):
    return SimpleNamespace(
        get_setting=lambda k, d=None: (folders or {}) if k == "local_docs.folders" else d,
        marketplace=SimpleNamespace(list_skills=lambda: list(skills or [])),
    )


def _body(resp):
    return json.loads(resp.body)


# ── the typed inventory ───────────────────────────────────────────────────────

def test_pack_types_are_declared_with_honest_capabilities(monkeypatch):
    monkeypatch.setattr(packs_router, "get_orch", lambda: _orch())
    body = _body(asyncio.run(packs_router.packs_list()))

    types = {t["type"]: t for t in body["types"]}
    assert set(types) == {"skill", "knowledge", "model"}
    assert types["skill"]["supported"] is True
    assert types["knowledge"]["supported"] is True
    # The load-bearing honesty: model packs are NOT stubbed as available.
    assert types["model"]["supported"] is False
    assert types["model"]["reason"]


def test_inventory_lists_skill_packs_with_their_type(monkeypatch):
    monkeypatch.setattr(packs_router, "get_orch", lambda: _orch(
        skills=[{"name": "weather", "version": "2.1.0", "description": "d", "author": "a"}],
    ))
    body = _body(asyncio.run(packs_router.packs_list()))

    skill_packs = [p for p in body["packs"] if p["pack_type"] == "skill"]
    assert len(skill_packs) == 1
    assert skill_packs[0]["name"] == "weather"
    assert skill_packs[0]["version"] == "2.1.0"


def test_inventory_lists_configured_knowledge_packs(tmp_path, monkeypatch):
    folder = _pack_folder(tmp_path, name="ro-law", version="3.0.0")
    monkeypatch.setattr(packs_router, "get_orch",
                        lambda: _orch(folders={"law": str(folder)}))
    body = _body(asyncio.run(packs_router.packs_list()))

    kp = [p for p in body["packs"] if p["pack_type"] == "knowledge"]
    assert len(kp) == 1
    assert kp[0]["name"] == "ro-law" and kp[0]["version"] == "3.0.0"
    assert kp[0]["key"] == "law"
    assert kp[0]["files"] == 1


def test_a_configured_folder_without_a_manifest_is_not_a_pack(tmp_path, monkeypatch):
    """A bare drop-folder is not a pack — it has no manifest to verify against.
    It must be reported as such, not silently promoted to a pack."""
    plain = tmp_path / "loose"
    plain.mkdir()
    (plain / "note.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(packs_router, "get_orch",
                        lambda: _orch(folders={"loose": str(plain)}))
    body = _body(asyncio.run(packs_router.packs_list()))

    assert [p for p in body["packs"] if p["pack_type"] == "knowledge"] == []
    assert "loose" in body["unmanifested"]


def test_inventory_degrades_honestly_without_an_orchestrator(monkeypatch):
    monkeypatch.setattr(packs_router, "get_orch", lambda: None)
    body = _body(asyncio.run(packs_router.packs_list()))
    assert body["packs"] == []
    assert body["available"] is False


# ── verification ──────────────────────────────────────────────────────────────

def test_verify_reports_ok_for_an_intact_pack(tmp_path, monkeypatch):
    folder = _pack_folder(tmp_path)
    monkeypatch.setattr(packs_router, "get_orch",
                        lambda: _orch(folders={"demo": str(folder)}))
    body = _body(asyncio.run(packs_router.packs_verify("demo")))
    assert body["ok"] is True and body["verify"]["checked"] == 1


def test_verify_names_every_discrepancy_on_a_tampered_pack(tmp_path, monkeypatch):
    folder = _pack_folder(tmp_path)
    (folder / "doc.md").write_text("TAMPERED", encoding="utf-8")
    (folder / "extra.md").write_text("smuggled in", encoding="utf-8")
    monkeypatch.setattr(packs_router, "get_orch",
                        lambda: _orch(folders={"demo": str(folder)}))
    body = _body(asyncio.run(packs_router.packs_verify("demo")))

    assert body["ok"] is False
    assert "doc.md" in body["verify"]["modified"]
    assert "extra.md" in body["verify"]["unexpected"]


def test_verify_rejects_an_unknown_key_without_touching_disk(monkeypatch):
    monkeypatch.setattr(packs_router, "get_orch", lambda: _orch(folders={}))
    resp = asyncio.run(packs_router.packs_verify("nope"))
    assert resp.status_code == 404


def test_verify_refuses_a_folder_with_no_manifest(tmp_path, monkeypatch):
    plain = tmp_path / "loose"
    plain.mkdir()
    (plain / "n.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(packs_router, "get_orch",
                        lambda: _orch(folders={"loose": str(plain)}))
    body = _body(asyncio.run(packs_router.packs_verify("loose")))
    assert body["ok"] is False and body["reason"] == "no_manifest"


# ── wiring ────────────────────────────────────────────────────────────────────

def test_routes_registered_and_user_guarded():
    paths = {r.path for r in packs_router.router.routes}
    assert paths == {"/api/packs", "/api/packs/{key}/verify"}
    for route in packs_router.router.routes:
        names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "user_guard" in names, f"{route.path} must be user-guarded"


def test_http_roundtrip():
    from fastapi.testclient import TestClient

    from agents import web

    r = TestClient(web.app).get("/api/packs")
    assert r.status_code == 200
    assert "types" in r.json()
