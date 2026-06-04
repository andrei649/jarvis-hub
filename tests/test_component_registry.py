"""Tests for the A2 ComponentRegistry (god-object reduction)."""
import logging
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.core.component_registry import ComponentRegistry


class _Owner:
    pass


def _reg():
    return ComponentRegistry(_Owner(), logging.getLogger("test"))


# ── unit ─────────────────────────────────────────────────────────────────────

def test_register_ok_sets_attr_and_status():
    r = _reg()
    inst = r.register("foo", lambda: {"x": 1}, "foo component")
    assert inst == {"x": 1}
    assert r._owner.foo == {"x": 1}
    assert r.status["foo"] == "ok" and r.failed() == []


def test_register_failure_sets_none_and_tracks():
    r = _reg()
    inst = r.register("bar", lambda: (_ for _ in ()).throw(RuntimeError("boom")), "bar")
    assert inst is None
    assert r._owner.bar is None                 # attr still set (back-compat)
    assert r.status["bar"] == "failed" and "bar" in r.failed()


def test_add_imports_and_constructs():
    r = _reg()
    # import a real lightweight component by module:attr
    r.add("notes", ".notes", "NotesStore", path=None, label="notes")
    assert r.status["notes"] == "ok" and r._owner.notes is not None


def test_register_group_all_or_none():
    r = _reg()
    r.register_group(("a", "b"), lambda: (1, 2), "pair")
    assert r._owner.a == 1 and r._owner.b == 2 and r.status["a"] == "ok"
    r.register_group(("c", "d"), lambda: (_ for _ in ()).throw(ValueError()), "pair2")
    assert r._owner.c is None and r._owner.d is None
    assert r.status["c"] == "failed" and r.status["d"] == "failed"


def test_summary_format():
    r = _reg()
    r.register("ok1", lambda: 1)
    r.register("bad1", lambda: (_ for _ in ()).throw(Exception()))
    s = r.summary()
    assert "1/2 components ok" in s and "failed: bad1" in s


# ── integration: real orchestrator registers all 19 components ───────────────

def test_orchestrator_components_all_ok_and_endpoint():
    from agents import web
    with TestClient(web.app) as c:
        reg = getattr(web.orch, "components", None)
        if reg is None:
            return
        # every optional component initialized in this offline environment
        assert reg.failed() == [], f"failed components: {reg.failed()}"
        # back-compat: the attributes are still directly accessible
        for name in ("arena", "rooms", "notes", "review_queue", "action_approvals",
                     "secret_broker", "quality", "consolidation", "kg_updater"):
            assert getattr(web.orch, name, None) is not None

        r = c.get("/api/health/components")
        assert r.status_code == 200
        body = r.json()
        assert body["failed"] == [] and "components ok" in body["summary"]
