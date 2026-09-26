"""H659 — a retried external request returns the original run instead of starting a second one.

A sender that times out retries. Before this row every retry of ``POST /api/actions/request``
queued a second approval card, every redelivered webhook ran a second turn, and every re-sent
A2A task became a second inbox row. Now an ``Idempotency-Key`` (1–255 visible ASCII) is
reserved in a durable SQLite row ``UNIQUE(scope, key)`` under ``BEGIN IMMEDIATE``, after the
caller is authenticated and before anything is queued or run; a retry gets the first request's
public reference back and nothing runs again.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from agents.core import idempotency as idem
from agents.core.idempotency import IdempotencyStore


@pytest.fixture
def store(tmp_path):
    s = IdempotencyStore(tmp_path / "idem.db")
    idem.set_store(s)
    yield s
    idem.set_store(None)


# ── the key ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["a", "!", "~", "run-2026-09-26:42", "~" * 255, "A" * 255])
def test_a_visible_ascii_key_of_up_to_255_characters_is_accepted(key):
    assert idem.parse_key(key) == key


def test_no_header_is_no_key():
    assert idem.parse_key(None) is None


@pytest.mark.parametrize("key", ["", " ", "a b", "tab\there", "é", "\x7f", "\x00", "a" * 256, " lead", "trail "])
def test_anything_else_is_refused(key):
    with pytest.raises(idem.InvalidKey):
        idem.parse_key(key)


def test_a_non_string_key_is_refused():
    with pytest.raises(idem.InvalidKey):
        idem.parse_key(b"abc")


# ── the fingerprint ──────────────────────────────────────────────────────────────

def test_the_fingerprint_is_stable_and_covers_method_path_and_body():
    fp = idem.fingerprint("post", "/api/x", b"{}")
    assert fp == idem.fingerprint("POST", "/api/x", b"{}") and len(fp) == 64
    assert fp != idem.fingerprint("PUT", "/api/x", b"{}")
    assert fp != idem.fingerprint("POST", "/api/y", b"{}")
    assert fp != idem.fingerprint("POST", "/api/x", b"{ }")


def test_the_fingerprint_cannot_be_shifted_across_its_parts():
    assert idem.fingerprint("POST", "/a", b"bc") != idem.fingerprint("POST", "/ab", b"c")
    assert idem.fingerprint("POST", "/a", b"") == idem.fingerprint("POST", "/a", None)


# ── the store ────────────────────────────────────────────────────────────────────

def test_a_first_request_reserves_and_a_retry_waits_until_it_is_done(store):
    assert store.reserve("s", "k", "fp").state == "new"
    assert store.reserve("s", "k", "fp").state == "in_progress"
    assert store.complete("s", "k", "fp", {"id": "a1"}, 202) is True
    got = store.reserve("s", "k", "fp")
    assert (got.state, got.ref, got.status_code) == ("replay", {"id": "a1"}, 202)


def test_the_same_key_for_a_different_request_is_a_conflict(store):
    store.reserve("s", "k", "fp")
    assert store.reserve("s", "k", "other").state == "conflict"
    store.complete("s", "k", "fp", {"id": "a1"})
    assert store.reserve("s", "k", "other").state == "conflict"


def test_two_callers_never_share_a_key(store):
    assert store.reserve("webhook:a", "k", "fp").state == "new"
    assert store.reserve("webhook:b", "k", "fp").state == "new"
    assert store.count() == 2


def test_only_a_pending_reservation_with_its_fingerprint_is_completed_or_released(store):
    store.reserve("s", "k", "fp")
    assert store.complete("s", "k", "other", {"id": 1}) is False
    assert store.release("s", "k", "other") is False
    assert store.complete("s", "k", "fp", {"id": 1}) is True
    assert store.complete("s", "k", "fp", {"id": 2}) is False          # done once
    assert store.release("s", "k", "fp") is False                     # a finished run stays
    assert store.reserve("s", "k", "fp").ref == {"id": 1}


def test_a_released_key_runs_again(store):
    store.reserve("s", "k", "fp")
    assert store.release("s", "k", "fp") is True
    assert store.count() == 0
    assert store.reserve("s", "k", "fp").state == "new"


def test_an_abandoned_first_attempt_is_taken_over_after_the_stale_window(store):
    store.reserve("s", "k", "fp", now=1_000.0)
    assert store.reserve("s", "k", "fp", now=1_000.0 + idem.STALE_PENDING_SECONDS - 1).state == "in_progress"
    assert store.reserve("s", "k", "fp", now=1_000.0 + idem.STALE_PENDING_SECONDS).state == "new"
    # the take-over restarts the window
    assert store.reserve("s", "k", "fp", now=1_000.0 + idem.STALE_PENDING_SECONDS + 1).state == "in_progress"


def test_a_stale_reservation_for_a_different_request_is_still_a_conflict(store):
    store.reserve("s", "k", "fp", now=0.0)
    assert store.reserve("s", "k", "other", now=10 * idem.STALE_PENDING_SECONDS).state == "conflict"


def test_rows_expire_after_the_ttl(store):
    store.reserve("s", "k", "fp", now=5_000.0)
    store.complete("s", "k", "fp", {"id": 1})
    assert store.reserve("s", "k", "fp", now=5_000.0 + idem.TTL_SECONDS - 1).state == "replay"
    assert store.reserve("s", "k", "fp", now=5_000.0 + idem.TTL_SECONDS + 1).state == "new"
    assert idem.TTL_SECONDS == 86_400


def test_a_reservation_survives_a_restart(tmp_path):
    first = IdempotencyStore(tmp_path / "idem.db")
    first.reserve("s", "k", "fp")
    first.complete("s", "k", "fp", {"action_id": "abc"})
    again = IdempotencyStore(tmp_path / "idem.db")
    assert first.durable and again.durable
    assert again.reserve("s", "k", "fp").ref == {"action_id": "abc"}


def test_two_workers_on_one_file_cannot_both_win(tmp_path):
    a, b = IdempotencyStore(tmp_path / "idem.db"), IdempotencyStore(tmp_path / "idem.db")
    assert a.reserve("s", "k", "fp").state == "new"
    assert b.reserve("s", "k", "fp").state == "in_progress"


def test_racing_threads_get_exactly_one_reservation(tmp_path):
    stores = [IdempotencyStore(tmp_path / "idem.db") for _ in range(8)]
    states, gate = [], threading.Barrier(8)

    def go(s):
        gate.wait()
        states.append(s.reserve("s", "k", "fp").state)

    threads = [threading.Thread(target=go, args=(s,)) for s in stores]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(states) == ["in_progress"] * 7 + ["new"]


def test_an_in_memory_store_says_it_is_not_durable():
    s = IdempotencyStore(":memory:")
    assert s.durable is False
    assert s.reserve("s", "k", "fp").state == "new"
    assert s.reserve("s", "k", "fp").state == "in_progress"


def test_a_failing_reservation_in_memory_leaves_no_open_transaction(monkeypatch):
    s = IdempotencyStore(":memory:")
    real = s._connect

    from contextlib import contextmanager

    @contextmanager
    def failing():
        with real() as conn:
            class _Conn:
                def execute(self, sql, *a):
                    if sql.startswith("INSERT"):
                        raise sqlite3.OperationalError("disk full")
                    return conn.execute(sql, *a)
            yield _Conn()

    monkeypatch.setattr(s, "_connect", failing)
    with pytest.raises(sqlite3.OperationalError):
        s.reserve("s", "k", "fp")
    monkeypatch.setattr(s, "_connect", real)
    assert s.reserve("s", "k", "fp").state == "new"      # the shared connection was rolled back


def test_the_file_is_created_with_its_folder(tmp_path):
    s = IdempotencyStore(tmp_path / "deep" / "er" / "idem.db")
    assert (tmp_path / "deep" / "er" / "idem.db").exists() and s.count() == 0


def test_the_default_store_lives_in_the_data_folder(tmp_path, monkeypatch):
    import agents.core.paths as paths

    monkeypatch.setattr(paths, "data_path", lambda name: tmp_path / "data" / name)
    idem.set_store(None)
    try:
        s = idem.get_store()
        assert s.path == str(tmp_path / "data" / "idempotency.db") and s.durable
        assert idem.get_store() is s
    finally:
        idem.set_store(None)


def test_only_a_reference_is_stored_never_a_body(store, tmp_path):
    store.reserve("s", "k", "fp")
    with pytest.raises(ValueError):
        store.complete("s", "k", "fp", {"reply": "x" * idem.MAX_REF_BYTES})
    store.complete("s", "k", "fp", {"id": "a1"})
    rows = sqlite3.connect(tmp_path / "idem.db").execute("SELECT * FROM idempotency").fetchall()
    assert rows[0][:6] == ("s", "k", "fp", "done", '{"id": "a1"}', 200)


def test_an_unreadable_reference_replays_as_empty(store, tmp_path):
    store.reserve("s", "k", "fp")
    store.complete("s", "k", "fp", {"id": 1})
    with sqlite3.connect(tmp_path / "idem.db") as conn:
        conn.execute("UPDATE idempotency SET ref='not json'")
    assert store.reserve("s", "k", "fp").ref == {}
    with sqlite3.connect(tmp_path / "idem.db") as conn:
        conn.execute("UPDATE idempotency SET ref='[1]'")
    assert store.reserve("s", "k", "fp").ref == {}


def test_a_failing_reservation_is_rolled_back(store, monkeypatch):
    store.reserve("s", "k", "fp", now=0.0)

    class _Boom(Exception):
        pass

    real = store._connect

    from contextlib import contextmanager

    @contextmanager
    def failing():
        with real() as conn:
            class _Conn:
                def execute(self, sql, *a):
                    if sql.startswith("INSERT"):
                        raise _Boom()
                    return conn.execute(sql, *a)
            yield _Conn()

    monkeypatch.setattr(store, "_connect", failing)
    with pytest.raises(_Boom):
        store.reserve("s", "k2", "fp", now=0.0)
    monkeypatch.setattr(store, "_connect", real)
    assert store.count() == 1                       # nothing half-written, the lock is free
    assert store.reserve("s", "k2", "fp").state == "new"


# ── the route side ───────────────────────────────────────────────────────────────

def _request(key=None, method="POST", path="/api/x"):
    headers = {} if key is None else {idem.HEADER: key}
    return SimpleNamespace(headers=headers, method=method, url=SimpleNamespace(path=path))


def test_no_header_leaves_the_route_as_it_was(store):
    got = idem.begin(_request(), "s", b"{}")
    assert got.claim is None and got.refusal is None and got.replay is None
    assert store.count() == 0
    assert idem.check_header(_request()) is None


def test_a_malformed_header_is_a_400(store):
    got = idem.begin(_request("bad key"), "s", b"{}")
    assert got.refusal.status_code == 400
    assert json.loads(got.refusal.body)["error"] == "invalid_idempotency_key"
    assert idem.check_header(_request("bad key")).status_code == 400
    assert idem.check_header(_request("good")) is None
    assert store.count() == 0


def test_begin_maps_each_state_to_what_the_route_does(store):
    first = idem.begin(_request("k"), "s", b"{}")
    assert first.claim is not None and first.claim.scope == "s" and first.claim.key == "k"
    assert first.claim.fp == idem.fingerprint("POST", "/api/x", b"{}")
    busy = idem.begin(_request("k"), "s", b"{}")
    assert busy.refusal.status_code == 409 and busy.refusal.headers["Retry-After"] == "1"
    assert json.loads(busy.refusal.body)["error"] == "idempotency_in_progress"
    other = idem.begin(_request("k"), "s", b"{1}")
    assert other.refusal.status_code == 409 and json.loads(other.refusal.body)["error"] == "idempotency_key_reused"
    first.claim.done({"id": "a1"}, 201)
    again = idem.begin(_request("k"), "s", b"{}")
    assert again.replay.ref == {"id": "a1"} and again.replay.status_code == 201 and again.claim is None


def test_the_path_is_part_of_the_request(store):
    idem.begin(_request("k", path="/api/a"), "s", b"{}")
    assert idem.begin(_request("k", path="/api/b"), "s", b"{}").refusal.status_code == 409


def test_a_store_that_cannot_be_written_refuses_a_keyed_request(monkeypatch):
    class _Broken:
        def reserve(self, *a, **k):
            raise sqlite3.OperationalError("disk I/O error")

    got = idem.begin(_request("k"), "s", b"{}", store=_Broken())
    assert got.refusal.status_code == 503
    assert json.loads(got.refusal.body)["error"] == "idempotency_unavailable"


def test_a_claim_never_raises_when_the_store_fails(caplog):
    class _Broken:
        def complete(self, *a, **k):
            raise RuntimeError("gone")

        def release(self, *a, **k):
            raise RuntimeError("gone")

    claim = idem.Claim(_Broken(), "s", "k", "fp")
    claim.done({"id": 1})
    claim.release()
    assert sum("idempotency" in r.getMessage() for r in caplog.records) == 2


def test_a_replay_is_marked_as_such():
    resp = idem.replayed({"ok": True}, 202)
    assert resp.status_code == 202 and resp.headers[idem.REPLAYED_HEADER] == "true"
    assert resp.headers["Cache-Control"] == "no-store"
    assert json.loads(resp.body) == {"ok": True, "replayed": True}


# ── POST /api/actions/request ────────────────────────────────────────────────────

@pytest.fixture
def actions(store):
    from fastapi.testclient import TestClient

    from agents import web

    with TestClient(web.app) as client:
        q = getattr(web.orch, "action_approvals", None)
        if q is None:
            pytest.skip("action approvals are not wired on this hub")
        q.clear()
        yield client, q
        q.clear()


def test_a_retried_action_request_queues_one_card(actions, store):
    client, q = actions
    body = {"tool": "transfer", "args": {"amount": 100}}
    first = client.post("/api/actions/request", json=body, headers={idem.HEADER: "pay-1"})
    again = client.post("/api/actions/request", json=body, headers={idem.HEADER: "pay-1"})
    assert first.status_code == again.status_code == 200
    assert again.headers[idem.REPLAYED_HEADER] == "true" and again.json()["replayed"] is True
    assert again.json()["action"]["id"] == first.json()["action"]["id"]
    assert again.json()["action"]["tool"] == "transfer"
    assert len(q.list("pending")) == 1
    assert idem.REPLAYED_HEADER not in first.headers


def test_a_replayed_action_the_queue_no_longer_has_still_answers_its_id(actions, store):
    client, q = actions
    first = client.post("/api/actions/request", json={"tool": "x"}, headers={idem.HEADER: "k"})
    q.clear()
    again = client.post("/api/actions/request", json={"tool": "x"}, headers={idem.HEADER: "k"})
    assert again.json()["action"] == {"id": first.json()["action"]["id"]}


def test_a_key_reused_for_another_action_is_refused(actions):
    client, q = actions
    client.post("/api/actions/request", json={"tool": "a"}, headers={idem.HEADER: "k"})
    other = client.post("/api/actions/request", json={"tool": "b"}, headers={idem.HEADER: "k"})
    assert other.status_code == 409 and other.json()["error"] == "idempotency_key_reused"
    assert len(q.list("pending")) == 1


def test_without_a_key_every_request_queues(actions):
    client, q = actions
    client.post("/api/actions/request", json={"tool": "a"})
    client.post("/api/actions/request", json={"tool": "a"})
    assert len(q.list("pending")) == 2


def test_a_malformed_key_queues_nothing(actions, store):
    client, q = actions
    got = client.post("/api/actions/request", json={"tool": "a"}, headers={idem.HEADER: "has space"})
    assert got.status_code == 400 and got.json()["error"] == "invalid_idempotency_key"
    # checked before the body is even validated
    empty = client.post("/api/actions/request", json={}, headers={idem.HEADER: "has space"})
    assert empty.json()["error"] == "invalid_idempotency_key"
    assert q.list("pending") == [] and store.count() == 0


def test_an_invalid_action_does_not_burn_its_key(actions, store):
    client, q = actions
    assert client.post("/api/actions/request", json={}, headers={idem.HEADER: "k"}).status_code == 400
    assert store.count() == 0
    assert client.post("/api/actions/request", json={"tool": "a"}, headers={idem.HEADER: "k"}).status_code == 200


def test_a_failing_queue_gives_the_key_back(actions, store, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    client, q = actions

    def boom(body):
        raise RuntimeError("queue down")

    monkeypatch.setattr(q, "request", boom)
    failing = TestClient(web.app, raise_server_exceptions=False)   # same app, no second start-up
    assert failing.post("/api/actions/request", json={"tool": "a"}, headers={idem.HEADER: "k"}).status_code == 500
    assert store.count() == 0
    monkeypatch.undo()
    assert client.post("/api/actions/request", json={"tool": "a"}, headers={idem.HEADER: "k"}).status_code == 200


# ── POST /api/webhooks/{id} ──────────────────────────────────────────────────────

@pytest.fixture
def hub(monkeypatch, tmp_path, store):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.app_state import get_orch
    from agents.core.routers import webhooks as router
    from agents.core.webhooks import WebhookStore

    monkeypatch.setattr(web, "ADMIN_TOKEN", "test-admin-secret")
    monkeypatch.setattr(router, "_webhook_store", WebhookStore(path=tmp_path / "wh.json"))
    with TestClient(web.app, raise_server_exceptions=False) as client:
        orch = get_orch()
        turns = []
        state = {"fail": False}

        async def handle_input(text, **kwargs):
            if state["fail"]:
                raise RuntimeError("model down")
            turns.append(text)
            return f"reply to {text}"

        monkeypatch.setattr(orch, "audit", SimpleNamespace(log=lambda *a, **k: None))
        monkeypatch.setattr(orch, "handle_input", handle_input)
        yield client, turns, state


def _hook(client, **body):
    resp = client.post("/api/webhooks", json={"target": "jarvis", **body},
                       headers={"X-Admin-Token": "test-admin-secret"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _deliver(client, hook, text, key=None, token=None):
    headers = {"X-Webhook-Token": token or hook["token"]}
    if key is not None:
        headers[idem.HEADER] = key
    return client.post(f"/api/webhooks/{hook['id']}", json={"text": text}, headers=headers)


def _calls(client, hook_id):
    listed = client.get("/api/webhooks", headers={"X-Admin-Token": "test-admin-secret"}).json()["webhooks"]
    return next(h for h in listed if h["id"] == hook_id)["calls"]


def test_a_redelivered_webhook_runs_one_turn(hub):
    client, turns, _state = hub
    hook = _hook(client)
    first = _deliver(client, hook, "build failed", key="gh-1")
    again = _deliver(client, hook, "build failed", key="gh-1")
    assert first.status_code == again.status_code == 200
    assert first.json()["response"] == "reply to build failed"
    assert turns == ["build failed"]
    assert again.headers[idem.REPLAYED_HEADER] == "true"
    assert again.json() == {"ok": True, "target": "jarvis", "replayed": True}   # never the reply
    assert _calls(client, hook["id"]) == 1


def test_without_a_key_a_redelivery_runs_again(hub):
    client, turns, _state = hub
    hook = _hook(client)
    _deliver(client, hook, "x")
    _deliver(client, hook, "x")
    assert turns == ["x", "x"]


def test_a_key_reused_for_another_delivery_is_refused(hub):
    client, turns, _state = hub
    hook = _hook(client)
    _deliver(client, hook, "one", key="k")
    other = _deliver(client, hook, "two", key="k")
    assert other.status_code == 409 and other.json()["error"] == "idempotency_key_reused"
    assert turns == ["one"]


def test_two_hooks_may_use_the_same_key(hub):
    client, turns, _state = hub
    a, b = _hook(client), _hook(client)
    assert _deliver(client, a, "x", key="k").status_code == 200
    assert _deliver(client, b, "x", key="k").status_code == 200
    assert turns == ["x", "x"]


def test_an_unauthenticated_delivery_cannot_burn_a_key(hub, store):
    client, turns, _state = hub
    hook = _hook(client)
    assert _deliver(client, hook, "x", key="k", token="wrong").status_code == 401
    assert store.count() == 0
    assert _deliver(client, hook, "x", key="k").status_code == 200 and turns == ["x"]


def test_a_malformed_key_is_refused_before_the_delivery_runs(hub, store):
    client, turns, _state = hub
    hook = _hook(client)
    got = _deliver(client, hook, "x", key="a" * 256)
    assert got.status_code == 400 and got.json()["error"] == "invalid_idempotency_key"
    # before the token is checked or the body read
    assert _deliver(client, hook, "x", key="a" * 256, token="wrong").status_code == 400
    assert turns == [] and store.count() == 0 and _calls(client, hook["id"]) == 0


def test_a_failed_turn_gives_the_key_back_so_the_retry_runs(hub, store):
    client, turns, state = hub
    hook = _hook(client)
    state["fail"] = True
    assert _deliver(client, hook, "x", key="k").status_code == 500
    assert store.count() == 0
    state["fail"] = False
    retry = _deliver(client, hook, "x", key="k")
    assert retry.status_code == 200 and idem.REPLAYED_HEADER not in retry.headers and turns == ["x"]


def test_a_server_error_answer_gives_the_key_back(hub, store, monkeypatch):
    client, turns, _state = hub
    hook = _hook(client, target_type="workflow", target="wf")
    from agents.core.app_state import get_orch

    monkeypatch.setattr(get_orch(), "workflow_engine", None)
    got = _deliver(client, hook, "x", key="k")
    assert got.status_code == 501 and store.count() == 0


def test_a_skipped_delivery_replays_as_skipped(hub):
    client, turns, _state = hub
    hook = _hook(client, prompt="{payload.missing}")
    first = _deliver(client, hook, "x", key="k")
    again = _deliver(client, hook, "x", key="k")
    assert first.status_code == again.status_code == 202
    assert again.json()["skipped"] == first.json()["skipped"] and again.json()["replayed"] is True
    assert turns == []


def test_the_outcome_kept_for_a_replay_is_public_only():
    from fastapi.responses import JSONResponse

    from agents.core.routers.webhooks import _public_outcome

    resp = JSONResponse({"ok": False, "target": "wf", "error": "workflow not found",
                         "response": "secret reply", "steps": [{"out": "x"}], "delivery": {"sent": 1}})
    assert _public_outcome(resp) == {"ok": False, "target": "wf", "error": "workflow not found"}
    assert _public_outcome(SimpleNamespace(body=b"not json")) == {}
    assert _public_outcome(SimpleNamespace(body=b"[1]")) == {}
    assert _public_outcome(JSONResponse({"ok": 1, "target": None, "skipped": "why"})) == {"skipped": "why"}


# ── POST /api/a2a/task ───────────────────────────────────────────────────────────

@pytest.fixture
def a2a(monkeypatch, tmp_path, store):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.a2a import A2ARegistry
    from agents.core.routers import a2a as route

    monkeypatch.setenv("JARVIS_A2A_ENABLED", "1")
    registry = A2ARegistry(path=str(tmp_path / "a2a.json"), identity_secret="idk")
    monkeypatch.setattr(route, "_a2a_registry", registry)
    return TestClient(web.app, raise_server_exceptions=False), registry


def _send(client, peer, body, key=None, peer_id="alice", signature=None):
    from agents.core.a2a import _hmac

    raw = json.dumps(body)
    headers = {"X-A2A-Peer": peer_id, "X-Signature-256": signature or _hmac(peer["secret"], raw)}
    if key is not None:
        headers[idem.HEADER] = key
    return client.post("/api/a2a/task", content=raw, headers=headers)


def test_a_re_sent_peer_task_lands_once(a2a):
    client, registry = a2a
    peer = registry.add_peer("alice")
    first = _send(client, peer, {"task": {"kind": "research"}}, key="t-1")
    again = _send(client, peer, {"task": {"kind": "research"}}, key="t-1")
    assert first.status_code == again.status_code == 200
    assert again.json() == {**first.json(), "replayed": True}
    assert again.headers[idem.REPLAYED_HEADER] == "true"
    assert len(registry.list_inbox()) == 1


def test_a_bad_signature_is_rejected_and_reserves_nothing(a2a, store):
    client, registry = a2a
    peer = registry.add_peer("alice")
    bad = _send(client, peer, {"task": {}}, key="k", signature="sha256=no")
    assert bad.status_code == 401 and bad.json() == {"error": "rejected"}
    assert store.count() == 0
    assert _send(client, peer, {"task": {}}, key="k").status_code == 200


def test_a_forged_retry_never_reads_the_peers_receipt(a2a):
    client, registry = a2a
    peer = registry.add_peer("alice")
    _send(client, peer, {"task": {"kind": "research"}}, key="t-1")
    forged = _send(client, peer, {"task": {"kind": "research"}}, key="t-1", signature="sha256=no")
    assert forged.status_code == 401 and forged.json() == {"error": "rejected"}
    assert idem.REPLAYED_HEADER not in forged.headers


def test_two_peers_may_use_the_same_key(a2a):
    client, registry = a2a
    alice, bob = registry.add_peer("alice"), registry.add_peer("bob")
    _send(client, alice, {"task": {}}, key="k")
    _send(client, bob, {"task": {}}, key="k", peer_id="bob")
    assert len(registry.list_inbox()) == 2


def test_a_peer_reusing_a_key_for_another_task_is_refused(a2a):
    client, registry = a2a
    peer = registry.add_peer("alice")
    _send(client, peer, {"task": {"n": 1}}, key="k")
    other = _send(client, peer, {"task": {"n": 2}}, key="k")
    assert other.status_code == 409 and len(registry.list_inbox()) == 1


def test_a_refused_task_gives_its_key_back(a2a, store, monkeypatch):
    client, registry = a2a
    peer = registry.add_peer("alice")
    real = registry.receive_task
    outcomes = iter([PermissionError("contract denied"), ValueError("invalid JSON body"), RuntimeError("disk")])

    def failing(*a, **k):
        raise next(outcomes)

    monkeypatch.setattr(registry, "receive_task", failing)
    assert _send(client, peer, {"task": {}}, key="k").status_code == 401
    assert store.count() == 0
    assert _send(client, peer, {"task": {}}, key="k").status_code == 400
    assert store.count() == 0
    assert _send(client, peer, {"task": {}}, key="k").status_code == 500
    assert store.count() == 0
    monkeypatch.setattr(registry, "receive_task", real)
    assert _send(client, peer, {"task": {}}, key="k").status_code == 200


def test_a_malformed_key_is_refused_before_the_peer_is_checked(a2a, store):
    client, registry = a2a
    peer = registry.add_peer("alice")
    got = _send(client, peer, {"task": {}}, key=b"\xe9")     # a latin-1 byte on the wire
    assert got.status_code == 400 and registry.list_inbox() == [] and store.count() == 0
    unsigned = _send(client, peer, {"task": {}}, key="a b", signature="sha256=no")
    assert unsigned.status_code == 400 and unsigned.json()["error"] == "invalid_idempotency_key"


def test_the_receipt_kept_is_the_public_one(a2a, tmp_path):
    client, registry = a2a
    peer = registry.add_peer("alice")
    _send(client, peer, {"task": {"secret": "do not keep"}}, key="k")
    rows = sqlite3.connect(tmp_path / "idem.db").execute("SELECT scope, ref FROM idempotency").fetchall()
    assert rows[0][0] == "a2a:alice" and "do not keep" not in rows[0][1]
    assert set(json.loads(rows[0][1])) == {"id", "status", "accepted"}
