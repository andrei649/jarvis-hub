"""H046 — look back at what the assistant learned (Hermes `hermes journey`, aliases
`learning` / `memory-graph`).

The learning timeline is GET /api/dashboard/today (agents/core/memory/timeline.py). This
pins what the row adds to it, through the real entry points:

* every feed item carries a stable ``entry_id`` (a learning's survives an edit of its
  value; an id is never reused after a delete);
* one learned entry is read, edited and deleted by that id under
  /api/dashboard/today/entries/{entry_id}, and the edit and the delete cross ``kg.write``
  the way the externally-driven /api/kg/* writes do (the write contract, then the Action
  Kernel with a capability token; deny before lookup; keys-only payload);
* `nerva journey` / `nerva learning` / `nerva memory-graph` print the timeline and edit
  ($EDITOR or --text) and delete one entry, here driven against the real app.

Hermetic: a temp memory.db (``store.DEFAULT_DB_PATH``), a stub orchestrator carrying the
kernel's real collaborators (kill switch, capability broker, policy), no network.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.cli.client import HubError
from agents.cli.nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE, Context, command_tree, main
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import Decision, Verdict
from agents.core.memory import store as store_mod
from agents.core.memory.store import MemoryStore
from agents.core.memory.timeline import build_unified_digest, learning_entry_id, parse_entry_id
from agents.core.routers import dashboard, memory_kg
from agents.core.security.capability import CapabilityBroker, KillSwitch

ENTRY = "/api/dashboard/today/entries/"


class _Queue:
    def __init__(self, done=()):
        self._done = list(done)

    def list(self, status=None, limit=500):
        return list(self._done) if status == "done" else []


def _task(tid, title):
    return SimpleNamespace(id=tid, title=title, updated_at=datetime.now(UTC).isoformat(),
                           risk_tier=1, agent_id="jarvis")


@pytest.fixture
def hub(tmp_path, monkeypatch):
    """The real app over a temp memory store and a stub orchestrator."""
    db = tmp_path / "memory.db"
    monkeypatch.setattr(store_mod, "DEFAULT_DB_PATH", db)
    purged = []
    orch = SimpleNamespace(
        autonomy_queue=_Queue([_task(7, "synced calendar")]),
        kill_switch=KillSwitch(tmp_path / "kill.json"),
        capabilities=CapabilityBroker(),
        autonomy_policy=AutonomyPolicy(),
        intent_log=None,
        _recall_purged=lambda **kw: purged.append(kw),
    )
    monkeypatch.setattr(web, "orch", orch)
    store = MemoryStore(db)
    return SimpleNamespace(client=TestClient(web.app), orch=orch, store=store, db=db, purged=purged)


def _seed(store, category, key, value):
    import asyncio
    asyncio.run(store.upsert(category, key, value, metadata={"source": "test"}))
    return asyncio.run(store.get(category, key))


def _learned(client, **query):
    body = client.get("/api/dashboard/today", params={"days": 30, **query}).json()
    return [it for it in body["items"] if it["kind"] == "learning"], body


# ── ids on the feed ──────────────────────────────────────────────────────────


def test_every_feed_item_has_a_stable_id_naming_its_row(hub):
    row = _seed(hub.store, "preference", "tone", "concise")
    _seed(hub.store, "open_concern", "launch", "worried about the launch")
    learned, body = _learned(hub.client)
    by_key = {it["key"]: it for it in learned}
    assert by_key["tone"]["entry_id"] == f"learning:{row['id']}"
    actions = [it for it in body["items"] if it["kind"] == "action"]
    assert [it["entry_id"] for it in actions] == ["action:7"]
    followups = [it for it in body["items"] if it["kind"] == "followup"]
    # A follow-up names the entry it was read from, so its id is stable too.
    launch = by_key["launch"]["entry_id"]
    assert [it["entry_id"] for it in followups] == [f"followup:open_concern:{launch}"]
    assert all(it["entry_id"] and parse_entry_id(it["entry_id"]) for it in body["items"])
    # Asked again, the same rows carry the same ids.
    again = [it["entry_id"] for it in hub.client.get("/api/dashboard/today?days=30").json()["items"]]
    assert sorted(again) == sorted(it["entry_id"] for it in body["items"])


def test_an_edit_keeps_the_id_and_a_deleted_id_is_never_reused(hub):
    row = _seed(hub.store, "fact", "city", "Bucharest")
    entry = f"learning:{row['id']}"
    assert hub.client.patch(ENTRY + entry, json={"value": "Cluj"}).status_code == 200
    learned, _ = _learned(hub.client)
    assert [(it["entry_id"], it["value"]) for it in learned] == [(entry, "Cluj")]
    assert hub.client.delete(ENTRY + entry).status_code == 200
    fresh = _seed(hub.store, "fact", "city", "Iasi")       # same category/key, a new fact
    assert fresh["id"] != row["id"]
    # The old id names nothing now: it can never edit or delete the new fact.
    assert hub.client.patch(ENTRY + entry, json={"value": "x"}).status_code == 404
    assert hub.client.delete(ENTRY + entry).status_code == 404
    assert hub.client.get(ENTRY + f"learning:{fresh['id']}").json()["entry"]["value"] == "Iasi"


def test_kind_and_limit_narrow_the_items_counts_stay_whole(hub):
    for n in range(5):
        _seed(hub.store, "fact", f"k{n}", f"v{n}")
    body = hub.client.get("/api/dashboard/today?days=30&kind=learning&limit=2").json()
    assert [it["kind"] for it in body["items"]] == ["learning", "learning"]
    assert body["counts"]["learnings"] == 5 and body["counts"]["actions"] == 1
    assert hub.client.get("/api/dashboard/today?kind=nonsense").status_code == 422
    assert hub.client.get("/api/dashboard/today?limit=0").status_code == 422
    assert hub.client.get("/api/dashboard/today?limit=501").status_code == 422


def test_builder_ids_and_parser():
    now = datetime(2026, 6, 27, 12, tzinfo=UTC).timestamp()
    ts = datetime(2026, 6, 27, 9, tzinfo=UTC).isoformat()
    out = build_unified_digest(None, [{"id": 3, "category": "fact", "key": "k", "value": "v",
                                       "updated_at": ts}], now=now)
    assert out["items"][0]["entry_id"] == "learning:3"
    assert learning_entry_id(None) is None and learning_entry_id(True) is None
    assert learning_entry_id(0) is None and learning_entry_id(2**63) is None
    assert parse_entry_id("learning:12") == ("learning", "12")
    assert parse_entry_id("action:7") == ("action", "7")
    assert parse_entry_id("followup:open_concern:learning:3") == ("followup", "learning:3")
    for bad in ("learning:0", "learning:012", "learning:-1", "learning:1x", "learning:", "fact:1",
                "learning:9223372036854775808", " learning:1", "followup:x:action:1", None, 12):
        assert parse_entry_id(bad) is None, bad


# ── read / edit / delete one learned entry ────────────────────────────────────


def test_read_edit_delete_one_learned_entry(hub):
    row = _seed(hub.store, "preference", "tone", "concise")
    entry = f"learning:{row['id']}"
    got = hub.client.get(ENTRY + entry)
    assert got.status_code == 200 and got.json()["entry"]["value"] == "concise"

    edited = hub.client.patch(ENTRY + entry, json={"value": "  warm and brief  "})
    assert edited.status_code == 200
    assert edited.json()["changed"] is True and edited.json()["entry"]["value"] == "warm and brief"
    stored = hub.store._get_by_id_sync(row["id"])
    assert stored["value"] == "warm and brief" and stored["category"] == "preference"
    assert json.loads(stored["metadata"]) == {"source": "test"}           # metadata kept
    # The search index follows the edit: the old words no longer find it.
    assert [r["key"] for r in hub.store._search_sync("brief", 10)] == ["tone"]
    assert hub.store._search_sync("concise", 10) == []
    assert hub.purged, "an edit must drop cached recall results (H428)"

    same = hub.client.patch(ENTRY + entry, json={"value": "warm and brief"})
    assert same.status_code == 200 and same.json()["changed"] is False

    gone = hub.client.delete(ENTRY + entry)
    assert gone.status_code == 200
    assert gone.json() == {"ok": True, "deleted": entry, "category": "preference", "key": "tone"}
    assert hub.store._get_by_id_sync(row["id"]) is None
    assert hub.store._search_sync("brief", 10) == []
    assert _learned(hub.client)[0] == []
    assert hub.client.get(ENTRY + entry).status_code == 404


def test_refusals_name_why(hub):
    assert hub.client.get(ENTRY + "nonsense").status_code == 400
    assert hub.client.delete(ENTRY + "learning:abc").status_code == 400
    action = hub.client.delete(ENTRY + "action:7")
    assert action.status_code == 409 and "record of what it did" in action.json()["error"]
    follow = hub.client.patch(ENTRY + "followup:open_concern:learning:3", json={"value": "x"})
    assert follow.status_code == 409 and follow.json()["source"] == "learning:3"
    assert hub.client.patch(ENTRY + "learning:1", json={"value": "   "}).status_code == 400
    assert hub.client.patch(ENTRY + "learning:1", json={"value": "x" * 2001}).status_code == 422
    assert hub.client.patch(ENTRY + "learning:1", json={"value": 5}).status_code == 422
    assert hub.client.delete(ENTRY + "learning:999").status_code == 404


def test_no_orchestrator_is_503(hub, monkeypatch):
    monkeypatch.setattr(web, "orch", None)
    assert hub.client.get(ENTRY + "learning:1").status_code == 503
    assert hub.client.delete(ENTRY + "learning:1").status_code == 503
    assert hub.client.patch(ENTRY + "learning:1", json={"value": "x"}).status_code == 503


# ── kg.write: the same mediation as the external /api/kg/* writes ─────────────


def test_halted_kernel_denies_edit_and_delete_before_any_lookup(hub, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    row = _seed(hub.store, "fact", "city", "Bucharest")
    entry = f"learning:{row['id']}"
    hub.orch.kill_switch.engage("global", "test halt")
    patch = hub.client.patch(ENTRY + entry, json={"value": "Cluj"})
    delete = hub.client.delete(ENTRY + entry)
    assert patch.status_code == 403 and patch.json()["error"].startswith("kernel denied")
    assert delete.status_code == 403
    # A missing entry is 403 too while halted: the deny says nothing about existence.
    assert hub.client.delete(ENTRY + "learning:999").status_code == 403
    assert hub.store._get_by_id_sync(row["id"])["value"] == "Bucharest"
    hub.orch.kill_switch.disengage("global")
    assert hub.client.patch(ENTRY + entry, json={"value": "Cluj"}).status_code == 200


def test_kernel_mints_a_kg_write_token_or_honours_a_presented_one(hub, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    row = _seed(hub.store, "fact", "city", "Bucharest")
    entry = f"learning:{row['id']}"
    assert hub.client.patch(ENTRY + entry, json={"value": "Cluj"}).status_code == 200
    minted = hub.orch.capabilities.list()
    assert len(minted) == 1 and minted[0]["capabilities"] == ["kg:write"]
    bogus = hub.client.delete(ENTRY + entry, headers={"x-capability-token": "bogus"})
    assert bogus.status_code == 403 and hub.store._get_by_id_sync(row["id"]) is not None
    tok = hub.orch.capabilities.issue(["kg:write"])["id"]
    assert hub.client.delete(ENTRY + entry, headers={"x-capability-token": tok}).status_code == 200
    assert len(hub.orch.capabilities.list()) == 2          # the presented token; none minted


def test_the_kernel_sees_kg_write_with_ids_only(hub, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    row = _seed(hub.store, "fact", "secret", "PII value")
    entry = f"learning:{row['id']}"
    seen = []

    def _spy(action, capability=None, budget=None):
        seen.append((action, capability))
        return Decision(Verdict.GRANT, reason="spy")

    monkeypatch.setattr("agents.core.kernel.binding.make_action_kernel", lambda o: _spy)
    hub.client.patch(ENTRY + entry, json={"value": "new PII text"})
    hub.client.delete(ENTRY + entry)
    assert [a.kind for a, _ in seen] == ["kg.write", "kg.write"]
    assert all(a.origin == "external" and c.name == "kg:write" and c.token_id for a, c in seen)
    assert seen[0][0].payload == {"op": "edit_learning", "entry": entry, "value_len": len("new PII text")}
    assert seen[1][0].payload == {"op": "delete_learning", "entry": entry}
    assert "PII" not in str([a.payload for a, _ in seen])


def test_the_write_contract_is_consulted(hub, monkeypatch):
    from agents.core.automation_contracts import ContractTemplate, predicate
    row = _seed(hub.store, "fact", "city", "Bucharest")
    deny = ContractTemplate(kind="kg.write", constraints=(
        predicate("never", lambda view, now: False, reason="test_denied"),), requires_approval=False)
    monkeypatch.setattr(memory_kg, "KG_WRITE_CONTRACT", deny)
    for resp in (hub.client.patch(ENTRY + f"learning:{row['id']}", json={"value": "Cluj"}),
                 hub.client.delete(ENTRY + f"learning:{row['id']}")):
        assert resp.status_code == 403 and resp.json()["error"] == "contract denied: test_denied"
    assert hub.store._get_by_id_sync(row["id"])["value"] == "Bucharest"


def test_the_contract_knows_both_learning_operations():
    for op in ("edit_learning", "delete_learning"):
        assert memory_kg._kg_contract_denial({"op": op}) is None
    assert memory_kg._kg_contract_denial({"op": "drop_everything"}) == "unknown_operation"


def test_routes_are_user_guarded():
    # The route-auth matrix (tests/_snapshots/route_auth.json) is the ground truth; pin the
    # three rows here too so this row's guard cannot drift unnoticed in a snapshot reseed.
    snap = json.loads((Path(__file__).resolve().parent / "_snapshots" / "route_auth.json")
                      .read_text(encoding="utf-8"))
    for method in ("GET", "PATCH", "DELETE"):
        assert snap[f"{method} {ENTRY}{{entry_id}}"] == "user"
    assert callable(dashboard.dashboard_today_entry_delete)


# ── the store's by-id calls ───────────────────────────────────────────────────


def test_store_delete_by_id_erases_like_delete(tmp_path):
    db = tmp_path / "m.db"
    store = MemoryStore(db)
    row = _seed(store, "fact", "pet", "a cat named Zorro")
    assert store._delete_by_id_sync(row["id"])["key"] == "pet"
    assert store._delete_by_id_sync(row["id"]) is None
    assert store._update_value_by_id_sync(row["id"], "x") is None
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT count(*) FROM memory").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM memory_fts").fetchone()[0] == 0
    finally:
        conn.close()
    assert b"Zorro" not in db.read_bytes()
    wal = db.with_name(db.name + "-wal")
    assert not wal.exists() or b"Zorro" not in wal.read_bytes()


# ── nerva journey / learning / memory-graph, against the real app ─────────────


class _AppHub:
    """The CLI's HubClient surface, answered by the real app in-process."""

    base_url = "http://testserver"

    def __init__(self, client):
        self._client = client
        self.calls = []

    def request(self, method, path, body=None, *, timeout=None):
        self.calls.append((method, path))
        resp = self._client.request(method, path, json=body)
        if resp.status_code >= 400:
            try:
                reason = resp.json().get("error") or resp.text
            except ValueError:
                reason = resp.text
            raise HubError(resp.status_code, reason)
        return resp.json()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None, *, timeout=None):
        return self.request("POST", path, body or {})


def _cli(argv, hub, *, stdin="", environ=None):
    out, err = io.StringIO(), io.StringIO()
    app_hub = _AppHub(hub.client)
    ctx = Context(environ=dict(environ or {}), out=out, err=err, inp=io.StringIO(stdin),
                  client_factory=lambda env: app_hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue(), app_hub


def test_the_verb_and_both_aliases_are_in_the_tree():
    tree = command_tree()
    for name in ("journey", "learning", "memory-graph"):
        assert tree[name] == ["delete", "edit", "list", "show"]


@pytest.mark.parametrize("verb", ["journey", "learning", "memory-graph"])
def test_list_prints_the_learning_timeline_with_ids(hub, verb):
    row = _seed(hub.store, "preference", "tone", "concise")
    code, out, _err, app_hub = _cli([verb], hub)
    assert code == EXIT_OK
    assert "1 did" in out and "1 learned" in out
    assert f"learning:{row['id']}" in out and "preference/tone: concise" in out
    assert "action:7" in out and "synced calendar" in out
    assert app_hub.calls == [("GET", "/api/dashboard/today?days=30&limit=50")]
    code, out, _err, app_hub = _cli([verb, "list", "--kind", "learning", "--days", "3", "--json"], hub)
    assert code == EXIT_OK
    assert [it["entry_id"] for it in json.loads(out)["items"]] == [f"learning:{row['id']}"]
    assert _cli([verb, "list", "--days", "31"], hub)[0] == EXIT_USAGE


def test_cli_edit_with_text_then_delete_with_typed_yes(hub):
    row = _seed(hub.store, "fact", "city", "Bucharest")
    entry = f"learning:{row['id']}"
    code, out, _err, _ = _cli(["journey", "edit", entry, "--text", "Cluj"], hub)
    assert code == EXIT_OK and "changed" in out and "fact/city: Cluj" in out
    assert hub.store._get_by_id_sync(row["id"])["value"] == "Cluj"

    code, out, _err, _ = _cli(["learning", "delete", entry], hub, stdin="no\n")
    assert code == EXIT_FAILED and "nothing was forgotten" in out
    assert hub.store._get_by_id_sync(row["id"]) is not None
    code, out, _err, _ = _cli(["learning", "delete", entry], hub, stdin="yes\n")
    assert code == EXIT_OK and f"forgot {entry}" in out
    assert hub.store._get_by_id_sync(row["id"]) is None


def test_cli_edit_opens_the_editor_on_the_entry(hub, monkeypatch, tmp_path):
    row = _seed(hub.store, "preference", "tone", "concise")
    entry = f"learning:{row['id']}"
    seen = {}

    def _editor(argv, path):
        with open(path, encoding="utf-8") as fh:
            seen["argv"], seen["text"] = argv, fh.read()
        seen["mode"] = os.stat(path).st_mode & 0o777
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("warm and brief\n")
        return 0

    monkeypatch.setattr("agents.cli.nerva._run_editor", _editor)
    code, out, err, _ = _cli(["memory-graph", "edit", entry], hub, environ={"EDITOR": "nano -w"})
    assert code == EXIT_OK, err
    assert seen["argv"] == ["nano", "-w"] and seen["text"] == "concise\n"
    assert seen["mode"] == 0o600                       # owner-only while the editor has it
    assert hub.store._get_by_id_sync(row["id"])["value"] == "warm and brief"

    # Saved unchanged: nothing is written; an editor that fails writes nothing either.
    monkeypatch.setattr("agents.cli.nerva._run_editor", lambda argv, path: 0)
    code, out, _err, app_hub = _cli(["journey", "edit", entry], hub)
    assert code == EXIT_OK and "nothing changed" in out
    assert [m for m, _ in app_hub.calls] == ["GET"]
    monkeypatch.setattr("agents.cli.nerva._run_editor", lambda argv, path: 1)
    code, _out, err, app_hub = _cli(["journey", "edit", entry], hub)
    assert code == EXIT_FAILED and "editor exited 1" in err
    assert [m for m, _ in app_hub.calls] == ["GET"]


def test_cli_kernel_refusal_is_reported_and_nothing_changes(hub, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    row = _seed(hub.store, "fact", "city", "Bucharest")
    hub.orch.kill_switch.engage("global", "test halt")
    code, _out, err, _ = _cli(["journey", "delete", f"learning:{row['id']}", "--yes"], hub)
    assert code == EXIT_FAILED and err.startswith("kernel denied") and "nothing changed" in err
    code, _out, err, _ = _cli(["journey", "edit", f"learning:{row['id']}", "--text", "Cluj"], hub)
    assert code == EXIT_FAILED and err.startswith("kernel denied")
    assert hub.store._get_by_id_sync(row["id"])["value"] == "Bucharest"


def test_cli_refuses_to_change_an_action(hub):
    code, _out, err, _ = _cli(["journey", "delete", "action:7", "--yes"], hub)
    assert code == EXIT_FAILED and "record of what it did" in err
    code, _out, err, _ = _cli(["journey", "edit", "learning:1", "--text", "   "], hub)
    assert code == EXIT_USAGE and "empty" in err
