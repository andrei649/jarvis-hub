"""H12.7: passive multi-surface capture — strict opt-in, local, redacted, inspectable.

Nothing is captured unless the master switch AND the specific surface are on;
secrets are redacted before storage; every capture is listable and forgettable.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.passive_capture import PassiveCapture, capture_enabled, SURFACES  # noqa: E402
import agents.web as web  # noqa: E402


class _FakeScanner:
    def redact(self, text):
        return text.replace("SECRET", "[REDACTED]")


class _FakeKG:
    def __init__(self):
        self.seen = []

    def ingest(self, text, source=""):
        self.seen.append((text, source))
        return 2          # pretend 2 triples extracted


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSIVE_CAPTURE", "1")


@pytest.fixture
def cap(tmp_path):
    return PassiveCapture(path=str(tmp_path / "c.json"),
                          scanner=_FakeScanner(), kg_updater=_FakeKG())


# ── opt-in gate ───────────────────────────────────────────────────

def test_master_off_disables_everything(cap, monkeypatch):
    monkeypatch.delenv("JARVIS_PASSIVE_CAPTURE", raising=False)
    cap.set_surfaces({"clipboard": True})
    assert cap.surface_enabled("clipboard") is False
    assert cap.ingest("clipboard", "hello") == {"captured": False, "reason": "disabled"}


def test_master_on_but_surface_off(cap, on):
    assert cap.ingest("clipboard", "hello")["captured"] is False    # surface not enabled


def test_enabled_surface_captures(cap, on):
    cap.set_surfaces({"clipboard": True})
    out = cap.ingest("clipboard", "remember this", source="copy")
    assert out["captured"] is True and out["triples"] == 2
    assert len(cap.list()) == 1 and cap.list()[0]["surface"] == "clipboard"


# ── redaction + KG ────────────────────────────────────────────────

def test_secrets_redacted_before_storage(cap, on):
    cap.set_surfaces({"clipboard": True})
    out = cap.ingest("clipboard", "my key is SECRET-123")
    assert out["redacted"] is True
    rec = cap.list()[0]
    assert "SECRET" not in rec["preview"] and "[REDACTED]" in rec["preview"]


def test_kg_receives_redacted_text(cap, on):
    cap.set_surfaces({"browser": True})
    cap.ingest("browser", "token SECRET on page", source="https://x")
    text, source = cap._kg.seen[0]
    assert "SECRET" not in text and source == "capture:browser"


# ── validation ────────────────────────────────────────────────────

def test_unknown_surface_raises(cap, on):
    with pytest.raises(ValueError):
        cap.ingest("microphone", "x")


def test_empty_content_not_captured(cap, on):
    cap.set_surfaces({"files": True})
    assert cap.ingest("files", "   ")["captured"] is False


# ── inspect / forget ──────────────────────────────────────────────

def test_inspect_forget_clear(cap, on):
    cap.set_surfaces({"clipboard": True, "files": True})
    a = cap.ingest("clipboard", "one")["id"]
    cap.ingest("files", "two")
    assert len(cap.list()) == 2 and len(cap.list("files")) == 1
    assert cap.forget(a) is True and len(cap.list()) == 1
    assert cap.forget(a) is False
    assert cap.clear() == 1 and cap.list() == []


def test_status_and_persistence(tmp_path, on):
    p = str(tmp_path / "c.json")
    c1 = PassiveCapture(path=p, scanner=_FakeScanner())
    c1.set_surfaces({"clipboard": True})
    st = c1.status()
    assert st["enabled"] is True and st["surfaces"]["clipboard"] is True
    # surfaces persist across reload
    assert PassiveCapture(path=p).status()["surfaces"]["clipboard"] is True


# ── endpoints ─────────────────────────────────────────────────────

def _client(monkeypatch, tmp_path):
    import agents.core.routers.capture as _capture_mod
    monkeypatch.setattr(_capture_mod, "_passive_capture",
                        PassiveCapture(path=str(tmp_path / "c.json"),
                                       scanner=_FakeScanner(), kg_updater=_FakeKG()))
    monkeypatch.setattr(web, "orch", None)
    return TestClient(web.app)


def test_endpoint_gated_then_captures(monkeypatch, tmp_path, on):
    client = _client(monkeypatch, tmp_path)
    # surface off → not captured
    r0 = client.post("/api/capture/ingest", json={"surface": "clipboard", "content": "x"})
    assert r0.json()["captured"] is False
    # enable the surface, then capture
    assert client.post("/api/capture/surfaces",
                       json={"surfaces": {"clipboard": True}}).json()["surfaces"]["clipboard"] is True
    r1 = client.post("/api/capture/ingest",
                     json={"surface": "clipboard", "content": "note SECRET here"})
    assert r1.json()["captured"] is True and r1.json()["redacted"] is True
    recs = client.get("/api/capture").json()["records"]
    assert len(recs) == 1 and "SECRET" not in recs[0]["preview"]
    # forget it
    assert client.delete(f"/api/capture/{recs[0]['id']}").json()["forgotten"] is True


def test_endpoint_unknown_surface_422(monkeypatch, tmp_path, on):
    client = _client(monkeypatch, tmp_path)
    assert client.post("/api/capture/ingest",
                       json={"surface": "mic", "content": "x"}).status_code == 422


# ── 0.26 export (portable, already-redacted) ──────────────────────────────────

def test_export_packages_redacted_records(cap, on):
    cap.set_surfaces({"clipboard": True, "browser": True})
    cap.ingest("clipboard", "note SECRET here")
    cap.ingest("browser", "a normal page")

    exp = cap.export(now=4242.0)
    assert exp["version"] == 1 and exp["exported_at"] == 4242.0
    assert exp["surface"] is None and exp["count"] == 2
    assert exp["surfaces"]["clipboard"] is True
    # the secret was redacted at ingest, so the export can't leak it
    blob = " ".join(r["preview"] for r in exp["records"])
    assert "SECRET" not in blob and "[REDACTED]" in blob


def test_export_filters_by_surface(cap, on):
    cap.set_surfaces({"clipboard": True, "browser": True})
    cap.ingest("clipboard", "clip one")
    cap.ingest("browser", "browse one")
    exp = cap.export(surface="browser")
    assert exp["surface"] == "browser" and exp["count"] == 1
    assert exp["records"][0]["surface"] == "browser"


def test_export_empty_when_nothing_captured(cap):
    exp = cap.export(now=1.0)
    assert exp["count"] == 0 and exp["records"] == []


def test_write_export_writes_json_file(cap, on, tmp_path):
    cap.set_surfaces({"clipboard": True})
    cap.ingest("clipboard", "secret token SECRET")
    dest = tmp_path / "out" / "capture-export.json"

    res = cap.write_export(dest, now=7.0)
    assert res["path"] == str(dest) and res["count"] == 1
    import json as _json
    loaded = _json.loads(dest.read_text(encoding="utf-8"))
    assert loaded["exported_at"] == 7.0 and loaded["count"] == 1
    assert "SECRET" not in _json.dumps(loaded)   # redacted before storage → safe export
