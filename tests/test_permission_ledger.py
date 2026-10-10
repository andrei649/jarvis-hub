"""op-permission-ledger — one consent ledger (per-app / per-site / OS-input /
file-root / terminal-target grants) behind the Action Kernel.

Pins the governance rules, not the plumbing:
  * DEFAULT_DENY entries can never be requested, granted or checked as allow;
  * a `once` grant is consumed by exactly one allowing check();
  * `session` grants die with the boot (a new ledger instance expires them);
  * request() goes through the injected govern_enqueue at EXTERNAL/ASK and never
    transitions the task itself;
  * apply_grant() refuses tasks not decided by a human (policy/system/empty) and
    non-approval decisions;
  * revoke() writes an audit row and never rows are immutable;
  * the routes are user-guarded and honour the narrowing-only rule.
"""

from __future__ import annotations

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
for p in (REPO, REPO / "agents"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from agents.core import permission_ledger as pl  # noqa: E402
from agents.core.kernel import Decision, Verdict  # noqa: E402
from agents.core.routers import permissions as permissions_routes  # noqa: E402
from agents.core.routers._deps import user_guard  # noqa: E402


class _Secrets:
    def __init__(self):
        self.data = {}

    def set(self, name, value):
        self.data[name] = value

    def get(self, name, default=None):
        return self.data.get(name, default)

    def delete(self, name):
        return self.data.pop(name, None) is not None


class _Enqueue:
    """A govern_enqueue fake that records the call and mints a task id."""

    def __init__(self, start=100):
        self.calls = []
        self.start = start

    def __call__(self, **kw):
        self.calls.append(kw)
        return self.start + len(self.calls)


def _task(payload, *, decided_by="owner", decision="accept", kind=pl.KIND, task_id=7):
    return SimpleNamespace(
        id=task_id, kind=kind, payload=payload, decided_by=decided_by, decision=decision,
        status="running",
        human_decision={"action": decision, "by": decided_by},
    )


@pytest.fixture
def ledger(tmp_path):
    led = pl.PermissionLedger(tmp_path / "permissions.db", enabled=True, secret_store=_Secrets())
    yield led
    led.close()


async def _grant(ledger, surface, key, scope, *, requested_by="browser", decided_by="owner"):
    prior_requests = sum(r["event"] == "grant.requested" for r in ledger.audit_rows(limit=1000))
    enq = _Enqueue(start=100 + prior_requests)
    task_id = ledger.request(surface, key, scope, requested_by, enq)
    payload = enq.calls[-1]["payload"]
    out = await ledger.apply_grant(_task(payload, decided_by=decided_by, task_id=task_id))
    assert out["status"] == "ok", out
    return out


# ── flag + default deny ──────────────────────────────────────────────────────


def test_flag_off_allows_and_records_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(pl.FLAG, raising=False)
    led = pl.PermissionLedger(tmp_path / "p.db", secret_store=_Secrets())
    try:
        assert led.enabled is False
        assert led.check("site", "chase.com") == "allow"
        assert led.check("app", "anything") == "allow"
        assert led.audit_rows() == []
        assert led.list_grants(include_inactive=True) == []
    finally:
        led.close()


def test_flag_on_first_contact_asks(tmp_path, monkeypatch):
    monkeypatch.setenv(pl.FLAG, "1")
    led = pl.PermissionLedger(tmp_path / "p.db", secret_store=_Secrets())
    try:
        assert led.enabled is True
        assert led.check("site", "example.com") == "ask"
    finally:
        led.close()


@pytest.mark.parametrize(
    ("surface", "key"),
    [
        ("site", "https://online.chase.com/login"),
        ("site", "my-bank.example"),
        ("site", "app.coinbase.com"),
        ("site", "vault.bitwarden.com"),
        ("site", "login.microsoftonline.com"),
        ("site", "www.onlyfans.com"),
        ("app", "C:/Program Files/1Password/1Password.exe"),
        ("app", "KeePassXC.exe"),
        ("file_root", "/home/owner/.ssh"),
        ("file_root", "C:\\Users\\owner\\.aws\\credentials"),
    ],
)
def test_default_deny_is_never_approvable(ledger, surface, key):
    rule = pl.default_denied(surface, key)
    assert rule is not None and rule.category
    assert ledger.check(surface, key) == "deny"
    enq = _Enqueue()
    with pytest.raises(pl.PermissionRequestError) as exc:
        ledger.request(surface, key, "always", "browser", enq)
    assert exc.value.reason == "default_denied"
    assert enq.calls == []


def test_default_deny_does_not_overreach(ledger):
    assert pl.default_denied("site", "github.com") is None
    assert pl.default_denied("site", "riverbank-photos.example") is None  # 'bank' is a token, not a substring
    assert pl.default_denied("app", "notepad.exe") is None
    assert pl.default_denied("file_root", "/home/owner/projects") is None
    assert ledger.check("site", "github.com") == "ask"


async def test_default_deny_refuses_even_an_approved_task(ledger):
    payload = {"surface": "site", "key": "chase.com", "scope": "always", "requested_by": "x"}
    out = await ledger.apply_grant(_task(payload))
    assert out == {"status": "refused", "reason": "default_denied"}
    assert ledger.check("site", "chase.com") == "deny"


# ── scopes ───────────────────────────────────────────────────────────────────


async def test_once_is_consumed_exactly_once(ledger):
    await _grant(ledger, "site", "docs.example.com", "once")
    assert ledger.check("site", "docs.example.com") == "allow"
    assert ledger.check("site", "docs.example.com") == "ask"
    rows = ledger.list_grants(include_inactive=True)
    assert [g.status for g in rows] == ["consumed"]
    assert any(r["event"] == "grant.consumed" for r in ledger.audit_rows())


async def test_always_survives_a_new_boot_but_session_does_not(tmp_path):
    path = tmp_path / "permissions.db"
    led = pl.PermissionLedger(path, enabled=True, secret_store=_Secrets())
    await _grant(led, "app", "code.exe", "session")
    await _grant(led, "site", "example.com", "always")
    assert led.check("app", "code") == "allow"
    assert led.check("app", "code") == "allow"  # session grants are not consumed
    assert led.check("site", "example.com") == "allow"
    led.close()

    reborn = pl.PermissionLedger(path, enabled=True, secret_store=_Secrets())
    try:
        assert reborn.check("app", "code.exe") == "ask"
        assert reborn.check("site", "https://example.com/path") == "allow"
        statuses = {g.key: g.status for g in reborn.list_grants(include_inactive=True)}
        assert statuses == {"code": "expired", "example.com": "active"}
        assert any(r["event"] == "grant.expired" and r["actor"] == "boot" for r in reborn.audit_rows())
    finally:
        reborn.close()


def test_never_scope_cannot_be_requested(ledger):
    enq = _Enqueue()
    with pytest.raises(pl.PermissionRequestError) as exc:
        ledger.request("site", "example.com", "never", "browser", enq)
    assert exc.value.reason == "scope_not_requestable"
    assert enq.calls == []


# ── request → approval queue ─────────────────────────────────────────────────


def test_request_enqueues_through_govern_enqueue_with_ask_and_external(ledger):
    enq = _Enqueue()
    task_id = ledger.request("terminal_target", "Docker:Dev", "session", "coder", enq, reason="run tests")
    assert task_id == 101
    (call,) = enq.calls
    assert call["kind"] == pl.KIND
    assert call["autonomy_level"] == "ask"
    assert call["risk_tier"] == int(pl.RiskTier.EXTERNAL)
    assert call["origin"] == "generated"
    assert call["payload"]["surface"] == "terminal_target"
    assert call["payload"]["key"] == "docker:dev"
    assert call["payload"]["scope"] == "session"
    assert call["payload"]["requested_by"] == "coder"
    # nothing was granted; the ledger only recorded the ask
    assert ledger.check("terminal_target", "docker:dev") == "ask"
    assert ledger.list_grants(include_inactive=True) == []
    events = [r["event"] for r in ledger.audit_rows()]
    assert events == ["grant.requested"]


def test_request_refuses_bad_input_before_enqueue(ledger):
    enq = _Enqueue()
    for surface, key, scope, by, reason in [
        ("gpu", "x", "once", "a", "invalid_surface"),
        ("site", "   ", "once", "a", "invalid_key"),
        ("site", "example.com", "forever", "a", "scope_not_requestable"),
        ("site", "example.com", "once", "", "requested_by_required"),
    ]:
        with pytest.raises(pl.PermissionRequestError) as exc:
            ledger.request(surface, key, scope, by, enq)
        assert exc.value.reason == reason
    assert enq.calls == []


def test_request_honours_a_kernel_deny(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    seen = []

    def authorize(action, capability=None):
        seen.append(action)
        return Decision(Verdict.DENY, reason="kill_switch")

    led = pl.PermissionLedger(tmp_path / "p.db", enabled=True, authorizer=authorize, secret_store=_Secrets())
    try:
        enq = _Enqueue()
        with pytest.raises(pl.PermissionRequestError) as exc:
            led.request("site", "example.com", "once", "browser", enq)
        assert exc.value.reason == "kernel_denied:kill_switch"
        assert enq.calls == []
        assert seen and seen[0].kind == pl.KIND
    finally:
        led.close()


def test_kernel_hook_is_not_consulted_while_the_kernel_flag_is_off(tmp_path, monkeypatch):
    """Default-off, like FileTools and ToolRPCServer: the hook is bound at boot but
    only consulted once JARVIS_ACTION_KERNEL is on, so the ask still reaches the inbox."""
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    seen = []

    def authorize(action, capability=None):
        seen.append(action)
        return Decision(Verdict.DENY, reason="kill_switch")

    led = pl.PermissionLedger(tmp_path / "p.db", enabled=True, authorizer=authorize, secret_store=_Secrets())
    try:
        enq = _Enqueue()
        assert led.request("site", "example.com", "once", "browser", enq) == 101
        assert seen == []
        assert len(enq.calls) == 1
    finally:
        led.close()


def test_request_with_kernel_queue_still_enqueues(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")

    def authorize(action, capability=None):
        return Decision(Verdict.QUEUE, reason="approval_required", tier=2)

    led = pl.PermissionLedger(tmp_path / "p.db", enabled=True, authorizer=authorize, secret_store=_Secrets())
    try:
        enq = _Enqueue()
        assert led.request("site", "example.com", "once", "browser", enq) == 101
        assert len(enq.calls) == 1
    finally:
        led.close()


def test_request_refuses_owner_never_rows(ledger):
    ledger.deny("site", "tracker.example", reason="owner said no")
    enq = _Enqueue()
    with pytest.raises(pl.PermissionRequestError) as exc:
        ledger.request("site", "tracker.example", "always", "browser", enq)
    assert exc.value.reason == "never_entry"
    assert ledger.check("site", "tracker.example") == "deny"


# ── apply_grant: only a human-decided task widens ────────────────────────────


@pytest.mark.parametrize("decided_by", ["policy", "system", "", None, "kernel"])
async def test_apply_grant_refuses_machine_decisions(ledger, decided_by):
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "x"}
    out = await ledger.apply_grant(_task(payload, decided_by=decided_by))
    assert out == {"status": "refused", "reason": "human_decision_required"}
    assert ledger.check("site", "example.com") == "ask"


@pytest.mark.parametrize("decision", ["reject", "defer", "", None])
async def test_apply_grant_refuses_non_approval_decisions(ledger, decision):
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "x"}
    out = await ledger.apply_grant(_task(payload, decision=decision))
    assert out["status"] == "refused" and out["reason"] == "decision_not_approval"
    assert ledger.check("site", "example.com") == "ask"


@pytest.mark.parametrize("record", [None, {}, "accept", {"action": "accept", "by": "other"},
                                    {"action": "edit", "by": "owner"}])
async def test_apply_grant_requires_matching_recorded_human_decision(ledger, record):
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "x"}
    task = _task(payload)
    task.human_decision = record
    result = await ledger.apply_grant(task)
    assert result == {"status": "refused", "reason": "human_decision_required"}
    assert ledger.list_grants() == []
    assert ledger.check("site", "example.com") == "ask"


async def test_apply_grant_refuses_other_kinds_and_bad_payloads(ledger):
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "x"}
    assert (await ledger.apply_grant(_task(payload, kind="house.control")))["reason"] == "kind_mismatch"
    assert (await ledger.apply_grant(_task(None)))["reason"] == "payload_required"
    bad = {**payload, "scope": "never"}
    assert (await ledger.apply_grant(_task(bad)))["reason"] == "scope_not_requestable"
    assert ledger.list_grants(include_inactive=True) == []


async def test_apply_grant_records_the_owner_and_task(ledger):
    out = await _grant(ledger, "file_root", "/home/owner/projects/", "always", decided_by="admin")
    (grant,) = ledger.list_grants()
    assert grant.id == out["grant_id"]
    assert grant.granted_by == "admin"
    assert grant.task_id == 101
    assert grant.key == "/home/owner/projects"
    assert grant.fingerprint and grant.as_dict()["immutable"] is False
    assert ledger.check("file_root", "/home/owner/projects") == "allow"
    applied = [r for r in ledger.audit_rows() if r["event"] == "grant.applied"]
    assert applied and applied[0]["actor"] == "admin" and applied[0]["task_id"] == 101


async def test_apply_grant_replay_after_restart_keeps_one_effect(tmp_path):
    path = tmp_path / "p.db"
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "browser"}
    first = pl.PermissionLedger(path, enabled=True, secret_store=_Secrets())
    try:
        original = await first.apply_grant(_task(payload, task_id=41))
    finally:
        first.close()
    again = pl.PermissionLedger(path, enabled=True, secret_store=_Secrets())
    try:
        replay = await again.apply_grant(_task(payload, task_id=41))
        assert replay["grant_id"] == original["grant_id"]
        assert replay["grant_status"] == "active"
        assert len(again.list_grants(include_inactive=True)) == 1
        assert [r["event"] for r in again.audit_rows()] == ["grant.applied"]
    finally:
        again.close()


@pytest.mark.parametrize("scope,final_status", [("once", "consumed"), ("always", "revoked")])
async def test_apply_grant_replay_does_not_restore_narrowed_authority(ledger, scope, final_status):
    payload = {"surface": "site", "key": "example.com", "scope": scope, "requested_by": "browser"}
    original = await ledger.apply_grant(_task(payload, task_id=42))
    if final_status == "consumed":
        assert ledger.check("site", "example.com") == "allow"
    else:
        ledger.revoke(original["grant_id"])
    replay = await ledger.apply_grant(_task(payload, task_id=42))
    assert replay["grant_id"] == original["grant_id"]
    assert replay["grant_status"] == final_status
    assert ledger.check("site", "example.com") == "ask"
    assert len(ledger.list_grants(include_inactive=True)) == 1
    changed = {**payload, "scope": "always" if scope == "once" else "once"}
    assert (await ledger.apply_grant(_task(changed, task_id=42)))["status"] == "refused"
    assert ledger.check("site", "example.com") == "ask"


async def test_apply_grant_audit_failure_rolls_back_before_retry(ledger):
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "browser"}
    ledger._conn.execute("""CREATE TRIGGER reject_applied BEFORE INSERT ON audit
        WHEN NEW.event='grant.applied' BEGIN SELECT RAISE(ABORT, 'audit failed'); END""")
    ledger._conn.commit()
    with pytest.raises(Exception, match="audit failed"):
        await ledger.apply_grant(_task(payload, task_id=43))
    ledger._conn.execute("DROP TRIGGER reject_applied")
    ledger._conn.commit()
    assert ledger.list_grants(include_inactive=True) == []
    replay = await ledger.apply_grant(_task(payload, task_id=43))
    assert replay["status"] == "ok"
    assert len(ledger.list_grants(include_inactive=True)) == 1


async def test_apply_grant_commit_outcome_uncertainty_replays_original(ledger):
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "browser"}
    real = ledger._conn

    class AmbiguousCommit:
        def __init__(self):
            self.once = True

        def __getattr__(self, name):
            return getattr(real, name)

        def commit(self):
            real.commit()
            if self.once:
                self.once = False
                raise RuntimeError("commit outcome unknown")

    ledger._conn = AmbiguousCommit()
    with pytest.raises(RuntimeError, match="commit outcome unknown"):
        await ledger.apply_grant(_task(payload, task_id=44))
    ledger._conn = real
    replay = await ledger.apply_grant(_task(payload, task_id=44))
    assert replay["status"] == "ok"
    assert replay["grant_id"] == ledger.list_grants(include_inactive=True)[0].id
    assert len(ledger.list_grants(include_inactive=True)) == 1
    assert [r["event"] for r in ledger.audit_rows()] == ["grant.applied"]


async def test_apply_grant_two_ledger_instances_share_task_receipt(tmp_path):
    path = tmp_path / "p.db"
    first = pl.PermissionLedger(path, enabled=True, secret_store=_Secrets())
    second = pl.PermissionLedger(path, enabled=True, secret_store=_Secrets())
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "browser"}
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(asyncio.run, ledger.apply_grant(_task(payload, task_id=45)))
                       for ledger in (first, second)]
            results = [f.result() for f in futures]
        assert results[0]["grant_id"] == results[1]["grant_id"]
        assert len(first.list_grants(include_inactive=True)) == 1
    finally:
        first.close()
        second.close()


def _insert_legacy_grant(ledger, *, task_id, grant_id):
    grant = pl.Grant(
        id=grant_id, surface="site", key="example.com", scope="always", status="active",
        requested_by="browser", granted_by="owner", task_id=task_id,
        boot_id=ledger.boot_id, created_at=100.0, updated_at=100.0,
    )
    with ledger._lock:
        ledger._insert(grant)
        ledger._conn.commit()
    return grant


async def test_apply_grant_adopts_one_matching_legacy_grant(tmp_path):
    path = tmp_path / "p.db"
    old = pl.PermissionLedger(path, enabled=True, secret_store=_Secrets())
    legacy = _insert_legacy_grant(old, task_id=46, grant_id="legacy-grant")
    with old._lock:
        old._conn.execute("DROP TABLE grant_task_receipts")
        old._conn.execute("PRAGMA user_version=1")
        old._conn.commit()
    old.close()
    reborn = pl.PermissionLedger(path, enabled=True, secret_store=_Secrets())
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "browser"}
    try:
        replay = await reborn.apply_grant(_task(payload, task_id=46))
        assert replay["grant_id"] == legacy.id
        assert len(reborn.list_grants(include_inactive=True)) == 1
        changed = {**payload, "scope": "once"}
        assert (await reborn.apply_grant(_task(changed, task_id=46)))["status"] == "refused"
    finally:
        reborn.close()


async def test_apply_grant_ambiguous_legacy_task_refused_but_ledger_stays_open(tmp_path):
    path = tmp_path / "p.db"
    old = pl.PermissionLedger(path, enabled=True, secret_store=_Secrets())
    _insert_legacy_grant(old, task_id=47, grant_id="legacy-a")
    _insert_legacy_grant(old, task_id=47, grant_id="legacy-b")
    old.close()
    reborn = pl.PermissionLedger(path, enabled=True, secret_store=_Secrets())
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "browser"}
    try:
        assert (await reborn.apply_grant(_task(payload, task_id=47)))["status"] == "refused"
        unrelated = await reborn.apply_grant(_task(payload, task_id=48))
        assert unrelated["status"] == "ok"
        assert len(reborn.list_grants(include_inactive=True)) == 3
    finally:
        reborn.close()


async def test_apply_grant_requires_durable_task_id(ledger):
    payload = {"surface": "site", "key": "example.com", "scope": "always", "requested_by": "browser"}
    assert (await ledger.apply_grant(_task(payload, task_id=None)))["status"] == "refused"
    assert ledger.list_grants(include_inactive=True) == []


async def test_apply_grant_replay_refuses_changed_governed_payload(ledger):
    payload = {
        "surface": "site", "key": "example.com", "scope": "always",
        "requested_by": "browser", "risk_tier": 2,
    }
    original = await ledger.apply_grant(_task(payload, task_id=50))
    changed = {**payload, "risk_tier": 0}
    replay = await ledger.apply_grant(_task(changed, task_id=50))
    assert replay["status"] == "refused"
    assert [g.id for g in ledger.list_grants(include_inactive=True)] == [original["grant_id"]]


async def test_os_input_replay_after_revoke_does_not_restore_token(tmp_path):
    store = _Secrets()
    ledger = pl.PermissionLedger(tmp_path / "p.db", enabled=True, secret_store=store)
    payload = {"surface": "os_input", "key": "keyboard", "scope": "always", "requested_by": "desktop"}
    try:
        first = await ledger.apply_grant(_task(payload, task_id=49))
        assert first["restore_token_stored"] is True
        ledger.revoke(first["grant_id"])
        replay = await ledger.apply_grant(_task(payload, task_id=49))
        assert replay["grant_id"] == first["grant_id"]
        assert replay["grant_status"] == "revoked"
        assert replay["restore_token_stored"] is False
        assert store.data == {}
    finally:
        ledger.close()


async def test_os_input_ambiguous_commit_keeps_original_restore_token(tmp_path):
    class RecordingSecrets(_Secrets):
        def __init__(self):
            super().__init__()
            self.set_count = 0

        def set(self, name, value):
            self.set_count += 1
            super().set(name, value)

    store = RecordingSecrets()
    ledger = pl.PermissionLedger(tmp_path / "p.db", enabled=True, secret_store=store)
    payload = {"surface": "os_input", "key": "keyboard", "scope": "always", "requested_by": "desktop"}
    real = ledger._conn

    class AmbiguousCommit:
        def __getattr__(self, name):
            return getattr(real, name)

        def commit(self):
            assert store.set_count == 1  # token must precede the durable grant
            real.commit()
            raise RuntimeError("commit outcome unknown")

    try:
        ledger._conn = AmbiguousCommit()
        with pytest.raises(RuntimeError, match="commit outcome unknown"):
            await ledger.apply_grant(_task(payload, task_id=51))
        ledger._conn = real
        (name, token), = store.data.items()
        grant_id = name.removeprefix("permission.os_input.")
        assert ledger.restore_token(grant_id) == token
        replay = await ledger.apply_grant(_task(payload, task_id=51))
        assert replay["grant_id"] == grant_id
        assert replay["restore_token_stored"] is True
        assert ledger.restore_token(grant_id) == token
        assert store.set_count == 1
        assert len(ledger.list_grants(include_inactive=True)) == 1
    finally:
        ledger.close()


async def test_os_input_precommit_failure_leaves_no_usable_authority(tmp_path):
    store = _Secrets()
    ledger = pl.PermissionLedger(tmp_path / "p.db", enabled=True, secret_store=store)
    payload = {"surface": "os_input", "key": "keyboard", "scope": "always", "requested_by": "desktop"}
    real = ledger._conn

    class FailedCommit:
        def __getattr__(self, name):
            return getattr(real, name)

        def commit(self):
            raise RuntimeError("commit failed before write")

    try:
        ledger._conn = FailedCommit()
        with pytest.raises(RuntimeError, match="commit failed before write"):
            await ledger.apply_grant(_task(payload, task_id=52))
        ledger._conn = real
        assert ledger.check("os_input", "keyboard") == "ask"
        assert ledger.list_grants(include_inactive=True) == []
        assert len(store.data) == 1  # an orphan secret is inert without a grant
        assert all(ledger.restore_token(name.removeprefix("permission.os_input.")) is None
                   for name in store.data)
    finally:
        ledger.close()


async def test_os_input_secret_store_failure_does_not_commit_grant(tmp_path):
    class BrokenSecrets(_Secrets):
        def set(self, name, value):
            raise RuntimeError("secret store unavailable")

    ledger = pl.PermissionLedger(tmp_path / "p.db", enabled=True, secret_store=BrokenSecrets())
    payload = {"surface": "os_input", "key": "keyboard", "scope": "always", "requested_by": "desktop"}
    try:
        with pytest.raises(RuntimeError, match="secret store unavailable"):
            await ledger.apply_grant(_task(payload, task_id=53))
        assert ledger.check("os_input", "keyboard") == "ask"
        assert ledger.list_grants(include_inactive=True) == []
    finally:
        ledger.close()


async def test_os_input_grant_keeps_its_restore_token_in_the_secret_store(tmp_path):
    secrets = _Secrets()
    led = pl.PermissionLedger(tmp_path / "p.db", enabled=True, secret_store=secrets)
    try:
        out = await _grant(led, "os_input", "keyboard", "always", requested_by="desktop")
        assert out["restore_token_stored"] is True
        token = led.restore_token(out["grant_id"])
        assert token and len(token) >= 24
        assert list(secrets.data) == [f"permission.os_input.{out['grant_id']}"]
        # the token never lands in the SQLite row
        raw = (tmp_path / "p.db").read_bytes()
        assert token.encode() not in raw
        led.revoke(out["grant_id"])
        assert secrets.data == {}
        assert led.restore_token(out["grant_id"]) is None
    finally:
        led.close()


# ── narrowing ────────────────────────────────────────────────────────────────


async def test_revoke_writes_an_audit_row_and_is_final(ledger):
    out = await _grant(ledger, "site", "example.com", "always")
    revoked = ledger.revoke(out["grant_id"], by="hud", reason="done")
    assert revoked.status == "revoked"
    assert ledger.check("site", "example.com") == "ask"
    row = next(r for r in ledger.audit_rows() if r["event"] == "grant.revoked")
    assert row["grant_id"] == out["grant_id"] and row["actor"] == "hud" and row["detail"] == "done"
    with pytest.raises(pl.PermissionRequestError) as exc:
        ledger.revoke(out["grant_id"])
    assert exc.value.reason == "invalid_transition"
    with pytest.raises(KeyError):
        ledger.revoke("nope")


async def test_never_rows_are_immutable_and_supersede_grants(ledger):
    out = await _grant(ledger, "site", "example.com", "always")
    never = ledger.deny("site", "example.com", reason="owner")
    assert never.status == "never" and never.as_dict()["immutable"] is True
    assert ledger.get(out["grant_id"]).status == "revoked"
    assert ledger.check("site", "example.com") == "deny"
    with pytest.raises(pl.PermissionRequestError) as exc:
        ledger.revoke(never.id)
    assert exc.value.reason == "never_is_immutable"
    assert ledger.deny("site", "example.com").id == never.id  # idempotent


def test_grant_fingerprint_detects_tampering(ledger):
    ledger.deny("site", "example.com")
    with ledger._lock:
        ledger._conn.execute("UPDATE grants SET key='other.example'")
        ledger._conn.commit()
    with pytest.raises(ValueError, match="fingerprint"):
        ledger.list_grants(include_inactive=True)


def test_contract_shape_for_the_manifest():
    view = {"surface": "site", "key": "example.com", "scope": "once", "requested_by": "x"}
    decision = pl.PERMISSION_GRANT_CONTRACT.evaluate(view, now=0.0)
    assert decision.admissible and decision.requires_approval
    assert pl.KIND == "permission.grant"
    assert pl.SURFACES == (
        "app",
        "site",
        "os_input",
        "file_root",
        "terminal_target",
        "session_command",
        "skill_switch",
    )


def test_skill_switch_grant_only_accepts_exact_once_digest(ledger):
    digest = "a" * 64
    enq = _Enqueue()
    assert ledger.request("skill_switch", digest, "once", "owner", enq) == 101
    assert enq.calls[0]["payload"]["key"] == digest
    for key, scope in (("not-a-digest", "once"), (digest, "always"), (digest, "session")):
        with pytest.raises(pl.PermissionRequestError):
            ledger.request("skill_switch", key, scope, "owner", enq)
    assert len(enq.calls) == 1


# ── routes ───────────────────────────────────────────────────────────────────


def _app(ledger):
    app = FastAPI()
    app.include_router(permissions_routes.router)
    return app


@pytest.fixture
def client(ledger, monkeypatch):
    async def _get():
        return ledger

    monkeypatch.setattr(permissions_routes, "_get_ledger", _get)
    app = _app(ledger)
    app.dependency_overrides[user_guard] = lambda: None
    return TestClient(app)


def test_routes_are_user_guarded():
    """Mirror tests/test_route_auth_matrix._runtime_guards: walk the dependant graph."""
    from tests._route_introspect import iter_effective_routes

    app = _app(None)
    guarded = {}
    for route in iter_effective_routes(app):
        dep = getattr(route, "dependant", None)
        if not getattr(route, "methods", None) or dep is None:
            continue  # starlette's built-in docs/openapi routes carry no dependant
        names = set()
        stack = list(getattr(dep, "dependencies", []))
        while stack:
            d = stack.pop()
            call = getattr(d, "call", None)
            if call is not None:
                names.add(getattr(call, "__name__", ""))
            stack.extend(getattr(d, "dependencies", []))
        guarded[route.path] = names
    assert guarded == {
        "/api/permissions": {"user_guard"},
        "/api/permissions/{grant_id}/revoke": {"user_guard"},
    }


def test_routes_refuse_without_a_user_token(ledger, monkeypatch):
    async def _get():
        return ledger

    monkeypatch.setattr(permissions_routes, "_get_ledger", _get)
    app = _app(ledger)

    async def _deny(request: Request):
        raise HTTPException(status_code=401, detail="user token required")

    app.dependency_overrides[user_guard] = _deny
    c = TestClient(app)
    assert c.get("/api/permissions").status_code == 401
    assert c.post("/api/permissions/x/revoke").status_code == 401


async def test_get_permissions_snapshot(client, ledger):
    out = await _grant(ledger, "site", "example.com", "always")
    r = client.get("/api/permissions")
    assert r.status_code == 200
    assert r.headers["cache-control"].startswith("no-cache")
    body = r.json()
    assert body["enabled"] is True and body["flag"] == pl.FLAG
    assert body["active"] == 1
    assert body["grants"][0]["id"] == out["grant_id"]
    assert body["surfaces"] == list(pl.SURFACES)
    assert any(d["category"] == "bank" for d in body["default_deny"])
    assert any(a["event"] == "grant.applied" for a in body["audit"])


async def test_revoke_route_narrows_and_refuses_never(client, ledger):
    out = await _grant(ledger, "site", "example.com", "always")
    r = client.post(f"/api/permissions/{out['grant_id']}/revoke")
    assert r.status_code == 200 and r.json()["grant"]["status"] == "revoked"
    assert ledger.check("site", "example.com") == "ask"
    never = ledger.deny("site", "blocked.example")
    r = client.post(f"/api/permissions/{never.id}/revoke")
    assert r.status_code == 409 and r.json()["reason"] == "never_is_immutable"
    r = client.post("/api/permissions/missing/revoke")
    assert r.status_code == 404 and r.json()["reason"] == "unknown_grant"
    r = client.post("/api/permissions/" + "x" * 65 + "/revoke")
    assert r.status_code == 400


def test_router_has_no_widening_route():
    app = _app(None)
    methods = {(r.path, tuple(sorted(r.methods))) for r in app.routes if hasattr(r, "methods")}
    assert ("/api/permissions", ("POST",)) not in methods
    assert not any(p.endswith("/grant") for p, _ in methods)


def test_ledger_default_path_is_under_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    led = pl.PermissionLedger(secret_store=_Secrets())
    try:
        assert str(led.path).startswith(str(tmp_path))
        assert led.path.name == "permissions.db"
    finally:
        led.close()
