"""H10.26: Data Spaces — per-agent data scope (least-privilege reads).

Unassigned agents are unrestricted (backward-compatible); an assigned agent only
sees the source categories in its granted spaces. Enforced at /api/memory/profile
via ?agent=<id>.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.data_spaces import DataSpaces  # noqa: E402
import agents.web as web  # noqa: E402


def _ds(tmp_path):
    return DataSpaces(path=str(tmp_path / "ds.json"))


# ── policy ────────────────────────────────────────────────────────

def test_unassigned_agent_is_unrestricted(tmp_path):
    ds = _ds(tmp_path)
    assert ds.allowed_sources("frigga") is None
    assert ds.can_access("frigga", "anything") is True
    cats = {"fact": [1], "secret": [2]}
    assert ds.filter_categories(cats, "frigga") == cats     # unchanged


def test_scoped_agent_sees_only_its_spaces(tmp_path):
    ds = _ds(tmp_path)
    ds.define_space("family", ["fact", "preference"])
    ds.define_space("ops", ["task"])
    ds.assign("frigga", "family")
    assert ds.allowed_sources("frigga") == {"fact", "preference"}
    assert ds.can_access("frigga", "fact") and not ds.can_access("frigga", "secret")
    cats = {"fact": [1], "preference": [2], "secret": [3], "task": [4]}
    assert set(ds.filter_categories(cats, "frigga")) == {"fact", "preference"}
    # a second space unions in
    ds.assign("frigga", "ops")
    assert ds.allowed_sources("frigga") == {"fact", "preference", "task"}


def test_unassign_restores_unrestricted(tmp_path):
    ds = _ds(tmp_path)
    ds.define_space("s", ["fact"])
    ds.assign("frigga", "s")
    assert ds.allowed_sources("frigga") == {"fact"}
    ds.unassign("frigga", "s")
    assert ds.allowed_sources("frigga") is None             # back to open


def test_delete_space_cascades_to_assignments(tmp_path):
    ds = _ds(tmp_path)
    ds.define_space("s", ["fact"])
    ds.assign("frigga", "s")
    assert ds.delete_space("s") is True
    assert ds.allowed_sources("frigga") is None             # assignment dropped
    assert ds.list_assignments() == {}


def test_assign_unknown_space_raises(tmp_path):
    with pytest.raises(ValueError):
        _ds(tmp_path).assign("frigga", "nope")


def test_persists_across_reload(tmp_path):
    p = str(tmp_path / "ds.json")
    a = DataSpaces(path=p)
    a.define_space("s", ["fact"])
    a.assign("frigga", "s")
    assert DataSpaces(path=p).allowed_sources("frigga") == {"fact"}


# ── endpoints ─────────────────────────────────────────────────────


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "_data_spaces", DataSpaces(path=str(tmp_path / "ds.json")))
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm")
    return TestClient(web.app), {"X-Admin-Token": "adm"}


def test_space_management_endpoints(monkeypatch, tmp_path):
    client, hdr = _client(monkeypatch, tmp_path)
    assert client.get("/api/memory/spaces").status_code == 401          # admin-guarded
    assert client.post("/api/memory/spaces", json={"name": "family", "sources": ["fact"]}, headers=hdr).status_code == 200
    assert client.post("/api/memory/spaces/assign", json={"agent": "frigga", "space": "family"}, headers=hdr).status_code == 200
    data = client.get("/api/memory/spaces", headers=hdr).json()
    assert data["spaces"][0]["space"] == "family"
    assert data["assignments"]["frigga"] == ["family"]
    # assigning an unknown space → 400
    assert client.post("/api/memory/spaces/assign", json={"agent": "x", "space": "ghost"}, headers=hdr).status_code == 400


def test_profile_is_scoped_by_agent(monkeypatch, tmp_path):
    client, hdr = _client(monkeypatch, tmp_path)
    # scope 'ghost' to a space whose source category won't exist → profile empties out
    web._data_spaces.define_space("void", ["__no_such_category__"])
    web._data_spaces.assign("ghost", "void")
    scoped = client.get("/api/memory/profile?agent=ghost")
    assert scoped.status_code == 200 and scoped.json() == {}
    # no agent → unrestricted (returns the store map, whatever it holds)
    assert client.get("/api/memory/profile").status_code == 200
