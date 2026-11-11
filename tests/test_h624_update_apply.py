"""H624 — update a running install safely, and undo it when it goes wrong.

Real temporary git repositories and real signatures (OpenPGP with gpg in a throwaway
keyring; SSH with ssh-keygen where it is installed), nothing faked about git:

* trust — no trust configured refuses every apply; changing trust is an irreversible-tier
  card only a person's accept of the unchanged payload applies; a declared fingerprint that
  is not the block's is refused; the repository's own git config cannot pick the program
  that verifies;
* the target — unsigned and signed-by-another-key targets are refused, a target signed by a
  pinned key (commit or tag) and a pinned commit apply;
* the pipeline — dirty tree refused (or stashed when the owner chose it), a fresh verified
  backup required, a human accept required, fast-forward only, receipt written, restart
  requested; the post-restart check verifies, or rolls back (git back, backup staged when a
  migration may have run, restart); the boot guard rolls back a hub that never starts;
* rollback — a card for the last verified update, applied only on a person's accept;
* the routes are admin-only and the CLI verbs exist.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import backup, hub_restart, hub_update, hub_update_apply
from agents.core.autonomy import irreversible

ADMIN = {"X-Admin-Token": "adm-h624"}
USER = {"Authorization": "Bearer usr-h624"}
HAS_GPG = shutil.which("gpg") is not None
HAS_SSH_KEYGEN = shutil.which("ssh-keygen") is not None
needs_gpg = pytest.mark.skipif(not HAS_GPG, reason="gpg is not installed")


def _env(home: Path, gnupg: Path | None = None) -> dict:
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home), "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org", "LC_ALL": "C"}
    if gnupg is not None:
        env["GNUPGHOME"] = str(gnupg)
    return env


def _run(cwd, *args, env=None, check=True):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, check=False)
    if check and done.returncode != 0:
        raise AssertionError(f"git {args}: {done.stderr}")
    return done.stdout.strip()


def _gpg_key(home: Path, uid: str) -> str:
    home.mkdir(mode=0o700, parents=True)
    env = {"PATH": os.environ.get("PATH", os.defpath), "GNUPGHOME": str(home)}
    subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", uid, "ed25519", "sign", "never"],
                   env=env, check=True, capture_output=True)
    out = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys"], env=env, check=True,
                         capture_output=True, text=True).stdout
    return next(line.split(":")[9] for line in out.splitlines() if line.startswith("fpr"))


def _armored(home: Path, fpr: str) -> str:
    return subprocess.run(["gpg", "--batch", "--armor", "--export", fpr], check=True, capture_output=True,
                          text=True, env={"PATH": os.environ.get("PATH", os.defpath), "GNUPGHOME": str(home)}).stdout


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    if not HAS_GPG:
        pytest.skip("gpg is not installed")
    base = tmp_path_factory.mktemp("k")
    owner = _gpg_key(base / "owner", "Owner <owner@example.org>")
    other = _gpg_key(base / "other", "Other <other@example.org>")
    return SimpleNamespace(owner_home=base / "owner", owner=owner, other_home=base / "other", other=other,
                           armored=_armored(base / "owner", owner))


class _Autonomy:
    def __init__(self):
        self.tasks = {}

    def govern_enqueue(self, agent, kind, title, payload=None, risk_tier=2, autonomy_level="ask",
                       origin="generated", attention_mode="interrupt"):
        task_id = len(self.tasks) + 1
        self.tasks[task_id] = SimpleNamespace(id=task_id, kind=kind, title=title, payload=dict(payload or {}),
                                              risk_tier=risk_tier, autonomy_level=autonomy_level,
                                              decided_by="", decision="")
        return task_id


class _Audit:
    def __init__(self):
        self.records = []

    def record(self, actor, action, why, metadata=None, **_kw):
        self.records.append({"actor": actor, "action": action, "metadata": metadata})

    def log(self, event):
        self.records.append({"action": getattr(event, "action_taken", None)})


@pytest.fixture
def upd(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import ops as ops_router

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))          # the hub's git sees no global config of the test box
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(data))
    env = _env(home)
    origin = tmp_path / "origin.git"
    _run(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin), env=env)
    work = tmp_path / "work"
    _run(tmp_path, "clone", "-q", str(origin), str(work), env=env)
    (work / "agents").mkdir()
    (work / "agents" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (work / "README.md").write_text("one\n", encoding="utf-8")
    _run(work, "add", ".", env=env)
    _run(work, "commit", "-q", "-m", "one", env=env)
    _run(work, "push", "-q", "-u", "origin", "HEAD:main", env=env)
    upstream = tmp_path / "upstream"
    _run(tmp_path, "clone", "-q", str(origin), str(upstream), env=env)
    monkeypatch.setattr(hub_update, "repo_root", lambda: work)
    monkeypatch.setattr(hub_update, "_install_kind", lambda: "git")
    hub_update.reset_for_tests()
    hub_restart.reset()
    restarts: list[bool] = []
    hub_restart.install(lambda: restarts.append(True))
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h624")
    monkeypatch.setattr(web, "USER_TOKEN", "usr-h624")
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    orch = SimpleNamespace(autonomy=_Autonomy(), intent_log=_Audit(), audit=_Audit())
    monkeypatch.setattr(ops_router, "get_orch", lambda: orch)
    ns = SimpleNamespace(client=TestClient(web.app), work=work, upstream=upstream, data=data, home=home,
                         env=env, orch=orch, restarts=restarts, tmp=tmp_path)
    yield ns
    hub_restart.reset()
    hub_update.reset_for_tests()


def _publish(u, *, version="1.1.0", files=None, sign_home=None, sign_key=None, tag=None, ssh_key=None):
    """Commit a new version upstream (optionally signed) and fetch it into the checkout."""
    env = _env(u.home, sign_home)
    (u.upstream / "agents" / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    for path, text in (files or {}).items():
        target = u.upstream / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _run(u.upstream, "add", ".", env=env)
    sign: list[str] = []
    if sign_key:
        sign = ["-c", "gpg.format=openpgp", "-c", f"user.signingkey={sign_key}"]
    if ssh_key:
        sign = ["-c", "gpg.format=ssh", "-c", "gpg.ssh.program=ssh-keygen", "-c", f"user.signingkey={ssh_key}"]
    _run(u.upstream, *sign, "commit", "-q", *(["-S"] if sign and not tag else []), "-m", f"release {version}", env=env)
    if tag:
        _run(u.upstream, *sign, "tag", "-s", "-m", tag, tag, env=env)
    _run(u.upstream, "push", "-q", "origin", "HEAD:main", *([tag] if tag else []), env=env)
    _run(u.work, "fetch", "-q", "--tags", "origin", env=u.env)
    return _run(u.upstream, "rev-parse", "HEAD", env=env)


def _head(u):
    return _run(u.work, "rev-parse", "HEAD", env=u.env)


def _accept(u, task_id, who="owner", decision="accept", payload=None):
    task = u.orch.autonomy.tasks[task_id]
    task.decided_by, task.decision = who, decision
    if payload is not None:
        task = SimpleNamespace(**{**vars(task), "payload": payload})
    return asyncio.run(irreversible.execute(task, orch=u.orch))


def _trust_gpg(u, keys):
    queued = u.client.post("/api/admin/ops/update/trust", headers=ADMIN,
                           json={"mode": "gpg", "public_key": keys.armored, "fingerprints": [keys.owner]})
    assert queued.status_code == 202, queued.text
    assert _accept(u, queued.json()["task_id"])["status"] == "ok"


def _request_apply(u, **body):
    queued = u.client.post("/api/admin/ops/update/apply", headers=ADMIN, json=body)
    assert queued.status_code == 202, queued.text
    return queued.json()


# ── trust ─────────────────────────────────────────────────────────────────────

def test_no_trust_refuses_every_apply_with_a_clear_message(upd):
    _publish(upd)
    plan = upd.client.get("/api/admin/ops/update/plan", headers=ADMIN).json()
    assert "no_trust_configured" in plan["refused"] and plan["can_apply"] is False
    refused = upd.client.post("/api/admin/ops/update/apply", headers=ADMIN, json={})
    assert refused.status_code == 409 and refused.json()["error"] == "no_trust_configured"
    check = upd.client.get("/api/admin/ops/update", headers=ADMIN).json()
    assert check["can_apply"] is False and check["trust"]["configured"] is False
    assert any("signature" in reason for reason in check["apply_refused"])
    assert upd.orch.autonomy.tasks == {}


@needs_gpg
def test_changing_trust_is_an_irreversible_card_a_person_accepts_unchanged(upd, keys):
    mismatch = upd.client.post("/api/admin/ops/update/trust", headers=ADMIN,
                               json={"mode": "gpg", "public_key": keys.armored, "fingerprints": [keys.other]})
    assert mismatch.status_code == 400 and mismatch.json()["error"] == "fingerprint_mismatch"
    assert upd.client.post("/api/admin/ops/update/trust", headers=USER,
                           json={"mode": "pinned", "commit": "a" * 40}).status_code in (401, 403)
    queued = upd.client.post("/api/admin/ops/update/trust", headers=ADMIN,
                             json={"mode": "gpg", "public_key": keys.armored, "fingerprints": [keys.owner]})
    assert queued.status_code == 202, queued.text
    task = upd.orch.autonomy.tasks[queued.json()["task_id"]]
    assert task.kind == "hub.update_trust" and task.risk_tier == irreversible.RISK_TIER
    assert task.payload["preview"]["new_trust"]["fingerprints"] == [keys.owner]
    assert hub_update_apply.trust_status()["configured"] is False      # nothing until accepted
    assert _accept(upd, task.id, who="policy")["reason"] == "human_decision_required"
    assert _accept(upd, task.id, decision="edit")["reason"] == "edit_not_supported"
    tampered = {**task.payload, "trust": {"mode": "pinned", "commit": "b" * 40}}
    assert _accept(upd, task.id, payload=tampered)["reason"] == "payload_changed"
    assert _accept(upd, task.id)["status"] == "ok"
    state = hub_update_apply.trust_status()
    assert state["configured"] and state["mode"] == "gpg" and state["fingerprints"] == [keys.owner]
    assert _accept(upd, task.id)["reason"] == "not_requested"              # once
    assert any(r["action"] == "hub.update.trust_set" for r in upd.orch.intent_log.records)


def test_trust_requests_are_validated():
    with pytest.raises(hub_update_apply.UpdateRefused) as bad:
        hub_update_apply._normalise_trust({"mode": "ssh", "keys": ["ssh-ed25519 not-base64!"]})
    assert bad.value.code == "invalid_key"
    with pytest.raises(hub_update_apply.UpdateRefused):
        hub_update_apply._normalise_trust({"mode": "pinned", "commit": "HEAD"})
    with pytest.raises(hub_update_apply.UpdateRefused):
        hub_update_apply._normalise_trust({"mode": "gpg", "public_key": "x", "fingerprints": ["A" * 40]})
    # a real key line (an ed25519 public key built by hand) gets OpenSSH's fingerprint format
    import base64
    import struct

    blob = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + bytes(range(32))
    line = "ssh-ed25519 " + base64.b64encode(blob).decode() + " me@host"
    record = hub_update_apply._normalise_trust({"mode": "ssh", "keys": [line]})
    assert record["keys"][0]["fingerprint"].startswith("SHA256:") and "me@host" not in record["keys"][0]["key"]
    wrong_type = "ssh-rsa " + base64.b64encode(blob).decode()
    with pytest.raises(hub_update_apply.UpdateRefused):
        hub_update_apply.ssh_fingerprint(wrong_type)


# ── the target ────────────────────────────────────────────────────────────────

@needs_gpg
def test_unsigned_and_wrongly_signed_targets_are_refused(upd, keys):
    _trust_gpg(upd, keys)
    before = _head(upd)
    _publish(upd, version="1.1.0")
    plan = upd.client.get("/api/admin/ops/update/plan", headers=ADMIN).json()
    assert plan["refused"] == ["untrusted_target"] and plan["verdict"]["reason"] == "signature_not_trusted"
    _publish(upd, version="1.2.0", sign_home=keys.other_home, sign_key=keys.other)
    plan = upd.client.get("/api/admin/ops/update/plan", headers=ADMIN).json()
    assert plan["refused"] == ["untrusted_target"]
    refused = upd.client.post("/api/admin/ops/update/apply", headers=ADMIN, json={})
    assert refused.status_code == 409 and refused.json()["error"] == "untrusted_target"
    assert _head(upd) == before and upd.orch.autonomy.tasks.keys() == {1}   # only the trust card


@needs_gpg
def test_verification_never_runs_a_program_the_repository_configures(upd, keys):
    _trust_gpg(upd, keys)
    target = _publish(upd, sign_home=keys.owner_home, sign_key=keys.owner)
    marker = upd.tmp / "pwned"
    script = upd.tmp / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    for key in ("gpg.program", "gpg.openpgp.program", "gpg.ssh.program", "core.fsmonitor", "core.hooksPath"):
        _run(upd.work, "config", key, str(script), env=upd.env)
    verdict = hub_update_apply.verify_target(target)
    assert verdict["trusted"] and verdict["signer"] == keys.owner
    assert not marker.exists()


@needs_gpg
def test_a_signed_tag_is_accepted_for_its_commit(upd, keys):
    _trust_gpg(upd, keys)
    target = _publish(upd, sign_home=keys.owner_home, sign_key=keys.owner, tag="v1.1.0")
    plan = upd.client.get("/api/admin/ops/update/plan", headers=ADMIN, params={"ref": "v1.1.0"}).json()
    assert plan["can_apply"], plan["refused"]
    assert plan["to"] == target and plan["verdict"]["how"] == "signed_tag"
    unsigned_commit = hub_update_apply.verify_target(target)            # the commit itself is unsigned
    assert unsigned_commit["trusted"] is False


def test_a_pinned_commit_applies_and_nothing_else(upd):
    first = _publish(upd, version="1.1.0")
    _publish(upd, version="1.2.0")
    hub_update_apply._write_trust({"mode": "pinned", "commit": first}, "owner", None)
    plan = hub_update_apply.plan()
    assert plan["can_apply"] and plan["to"] == first and plan["verdict"]["how"] == "pinned"
    other = hub_update_apply.plan("origin/main")
    assert "untrusted_target" in other["refused"]


# ── the pipeline ──────────────────────────────────────────────────────────────

@needs_gpg
def test_a_verified_target_applies_after_a_person_accepts_and_is_verified_after_restart(upd, keys):
    _trust_gpg(upd, keys)
    before = _head(upd)
    target = _publish(upd, sign_home=keys.owner_home, sign_key=keys.owner, files={"docs/notes.md": "x\n"})
    plan = upd.client.get("/api/admin/ops/update/plan", headers=ADMIN).json()
    assert plan["can_apply"], plan["refused"]
    assert plan["from"] == before and plan["to"] == target and plan["commit_count"] == 1
    assert plan["from_version"] == "1.0.0" and plan["to_version"] == "1.1.0"
    assert {f["path"] for f in plan["files"]} == {"agents/__init__.py", "docs/notes.md"}
    assert plan["dependencies"]["changed"] is False and plan["migrations"] == []
    queued = _request_apply(upd)
    task = upd.orch.autonomy.tasks[queued["task_id"]]
    assert task.kind == "hub.update" and task.risk_tier == irreversible.RISK_TIER
    assert task.payload["to"] == target and task.payload["preview"]["to"] == target
    assert _head(upd) == before and upd.restarts == []                 # nothing until accepted
    assert _accept(upd, task.id, who="system")["reason"] == "human_decision_required"
    assert _accept(upd, task.id, payload={**task.payload, "to": before})["reason"] == "payload_changed"
    done = _accept(upd, task.id)
    assert done["status"] == "ok" and done["restart"] == "requested", done
    assert _head(upd) == target and upd.restarts == [True]
    in_flight = hub_update_apply.current()
    assert in_flight["phase"] == "restarting" and in_flight["from"] == before and in_flight["to"] == target
    archive = backup.resolve_backup(in_flight["backup"])
    assert archive is not None and backup.verify_backup(str(archive))["ok"]
    assert any("fast-forwarded" in line for line in in_flight["log"])
    action = upd.client.get(f"/api/admin/ops/actions/{in_flight['action_id']}", headers=ADMIN).json()
    assert action["kind"] == "update" and any("backup" in line for line in action["lines"])
    verified = hub_update_apply.verify_after_restart(
        lambda: {"ready": True, "version": "1.1.0", "commit": target}, deadline=1, sleep=lambda s: None)
    assert verified["result"] == "verified"
    assert hub_update_apply.current() is None
    rows = upd.client.get("/api/admin/ops/update/receipts", headers=ADMIN).json()
    last = rows["last_receipt"]
    assert last["result"] == "verified" and last["from"] == before and last["to"] == target
    assert last["backup"] == in_flight["backup"] and last["approved_by"] == "owner"
    assert rows["rollback"]["can_rollback"] is True
    assert any(r["action"] == "hub.update.apply" for r in upd.orch.intent_log.records)


@needs_gpg
def test_a_dirty_tree_is_refused_unless_the_owner_chose_to_stash(upd, keys):
    _trust_gpg(upd, keys)
    target = _publish(upd, sign_home=keys.owner_home, sign_key=keys.owner)
    (upd.work / "README.md").write_text("local edit\n", encoding="utf-8")
    refused = upd.client.post("/api/admin/ops/update/apply", headers=ADMIN, json={})
    assert refused.status_code == 409 and refused.json()["error"] == "dirty_tree"
    queued = _request_apply(upd, dirty_policy="stash")
    done = _accept(upd, queued["task_id"])
    assert done["status"] == "ok", done
    assert _head(upd) == target
    stash = hub_update_apply.current()["stash"]
    assert stash and _run(upd.work, "stash", "list", env=upd.env)          # kept, never discarded
    assert (upd.work / "README.md").read_text(encoding="utf-8") == "one\n"


@needs_gpg
def test_the_tree_dirtied_after_the_card_is_refused_at_apply(upd, keys):
    _trust_gpg(upd, keys)
    before = _head(upd)
    _publish(upd, sign_home=keys.owner_home, sign_key=keys.owner)
    queued = _request_apply(upd)
    (upd.work / "README.md").write_text("late edit\n", encoding="utf-8")
    done = _accept(upd, queued["task_id"])
    assert done["status"] == "refused" and done["reason"] == "dirty_tree"
    assert _head(upd) == before and upd.restarts == []


@needs_gpg
def test_no_verified_backup_means_no_update(upd, keys, monkeypatch):
    _trust_gpg(upd, keys)
    before = _head(upd)
    _publish(upd, sign_home=keys.owner_home, sign_key=keys.owner)
    queued = _request_apply(upd)
    monkeypatch.setattr(backup, "verify_backup", lambda *a, **k: {"ok": False, "problem": "corrupt"})
    done = _accept(upd, queued["task_id"])
    assert done["status"] == "failed" and done["reason"] == "backup_failed_verify"
    assert _head(upd) == before and upd.restarts == [] and hub_update_apply.current() is None
    assert hub_update_apply.receipts()[-1]["result"] == "failed"


@needs_gpg
def test_a_failing_post_restart_check_rolls_back_and_restores_the_backup(upd, keys):
    _trust_gpg(upd, keys)
    before = _head(upd)
    target = _publish(upd, sign_home=keys.owner_home, sign_key=keys.owner,
                      files={"agents/core/persistence/migrations.py": "# v2\n"})
    plan = hub_update_apply.plan()
    assert plan["migrations"] == ["agents/core/persistence/migrations.py"]
    queued = _request_apply(upd)
    assert _accept(upd, queued["task_id"])["status"] == "ok"
    assert _head(upd) == target
    out = hub_update_apply.verify_after_restart(
        lambda: {"ready": False, "version": "1.1.0", "commit": target}, deadline=0, sleep=lambda s: None)
    assert out["phase"] == "rolled_back_restarting" and "readyz" in out["rollback_reason"]
    assert _head(upd) == before and upd.restarts == [True, True]
    staged = backup.pending_restore()
    assert staged and staged["name"] == out["backup"]
    # the previous code boots: the rollback is recorded as done
    hub_update_apply._BOOT["commit"] = None
    finished = hub_update_apply.on_boot()
    assert finished["result"] == "rolled_back" and hub_update_apply.current() is None


@needs_gpg
def test_a_hub_serving_the_wrong_version_is_rolled_back(upd, keys):
    _trust_gpg(upd, keys)
    before = _head(upd)
    target = _publish(upd, sign_home=keys.owner_home, sign_key=keys.owner)
    _accept(upd, _request_apply(upd)["task_id"])
    out = hub_update_apply.verify_after_restart(
        lambda: {"ready": True, "version": "1.0.0", "commit": target}, deadline=0, sleep=lambda s: None)
    assert "version 1.0.0" in out["rollback_reason"] and _head(upd) == before
    assert backup.pending_restore() is None                              # no migration: data kept


@needs_gpg
def test_the_boot_guard_rolls_back_code_that_never_starts(upd, keys):
    _trust_gpg(upd, keys)
    before = _head(upd)
    _publish(upd, sign_home=keys.owner_home, sign_key=keys.owner)
    _accept(upd, _request_apply(upd)["task_id"])
    for _ in range(hub_update_apply.max_boots()):
        assert hub_update_apply.boot_guard() is False
    assert hub_update_apply.boot_guard() is True
    assert _head(upd) == before
    assert hub_update_apply.current()["phase"] == "rolled_back_restarting"


@needs_gpg
def test_rollback_is_an_owner_approved_command_for_the_last_update(upd, keys):
    _trust_gpg(upd, keys)
    before = _head(upd)
    target = _publish(upd, sign_home=keys.owner_home, sign_key=keys.owner)
    refused = upd.client.post("/api/admin/ops/update/rollback", headers=ADMIN, json={})
    assert refused.status_code == 409 and refused.json()["error"] == "nothing_to_roll_back"
    _accept(upd, _request_apply(upd)["task_id"])
    hub_update_apply.verify_after_restart(lambda: {"ready": True, "version": "1.1.0", "commit": target},
                                          deadline=1, sleep=lambda s: None)
    queued = upd.client.post("/api/admin/ops/update/rollback", headers=ADMIN, json={"restore_data": False})
    assert queued.status_code == 202, queued.text
    task = upd.orch.autonomy.tasks[queued.json()["task_id"]]
    assert task.kind == "hub.update_rollback" and task.risk_tier == irreversible.RISK_TIER
    assert task.payload["to"] == before and task.payload["from"] == target
    assert _head(upd) == target
    assert _accept(upd, task.id, who="policy")["reason"] == "human_decision_required"
    done = _accept(upd, task.id)
    assert done["status"] == "ok", done
    assert _head(upd) == before and upd.restarts == [True, True]
    hub_update_apply._BOOT["commit"] = None
    assert hub_update_apply.on_boot()["result"] == "rolled_back"
    kinds = [(r["kind"], r.get("result")) for r in hub_update_apply.receipts()]
    assert ("update", "verified") in kinds and ("rollback", "rolled_back") in kinds
    assert hub_update_apply.last_update() is None                      # nothing left to roll back


@needs_gpg
def test_offline_rollback_refuses_while_a_hub_runs(upd, keys, monkeypatch):
    from agents.core import install_identity

    monkeypatch.setattr(install_identity, "hub_lock_held_elsewhere", lambda root=None: True)
    with pytest.raises(hub_update_apply.UpdateRefused) as refused:
        hub_update_apply.rollback_offline()
    assert refused.value.code == "hub_running"


def test_dependency_installs_are_hash_pinned_wheels_only():
    argv = hub_update_apply._pip_argv(Path("/x/requirements-beta.lock"))
    assert argv[1:4] == ["-m", "pip", "install"]
    for flag in ("--require-hashes", "--no-deps", "--no-input"):
        assert flag in argv
    assert argv[argv.index("--only-binary") + 1] == ":all:"
    assert argv[-2:] == ["-r", "/x/requirements-beta.lock"]


@pytest.mark.skipif(not HAS_SSH_KEYGEN, reason="ssh-keygen is not installed")
def test_ssh_signing_keys_verify_through_nervas_own_allowed_signers_file(upd):
    owner = upd.tmp / "id_owner"
    other = upd.tmp / "id_other"
    for path in (owner, other):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
    hub_update_apply._write_trust(hub_update_apply._normalise_trust(
        {"mode": "ssh", "keys": [(owner.with_suffix(".pub")).read_text().strip()]}), "owner", None)
    assert "namespaces=\"git\"" in (upd.data / "update" / "allowed_signers").read_text()
    bad = _publish(upd, version="1.1.0", ssh_key=str(other))
    assert hub_update_apply.verify_target(bad)["trusted"] is False
    good = _publish(upd, version="1.2.0", ssh_key=str(owner))
    verdict = hub_update_apply.verify_target(good)
    assert verdict["trusted"] and verdict["signer"].startswith("SHA256:")


# ── surfaces ──────────────────────────────────────────────────────────────────

def test_every_update_route_refuses_a_non_admin(upd):
    calls = [("GET", "/api/admin/ops/update/plan", None), ("GET", "/api/admin/ops/update/receipts", None),
             ("POST", "/api/admin/ops/update/apply", {}), ("POST", "/api/admin/ops/update/rollback", {}),
             ("POST", "/api/admin/ops/update/trust", {"mode": "pinned", "commit": "a" * 40})]
    for headers in ({}, USER):
        for method, path, body in calls:
            kwargs = {"headers": headers, **({"json": body} if body is not None else {})}
            assert upd.client.request(method, path, **kwargs).status_code in (401, 403), (method, path)
    cross = upd.client.post("/api/admin/ops/update/apply", headers={**ADMIN, "Sec-Fetch-Site": "cross-site"},
                            json={})
    assert cross.status_code == 403
    assert upd.orch.autonomy.tasks == {}


def test_the_irreversible_tier_knows_the_update_kinds():
    assert {"hub.update", "hub.update_rollback", "hub.update_trust"} <= set(irreversible.kinds())


def test_the_cli_has_the_update_verbs():
    from agents.cli.nerva import build_parser, command_tree

    assert command_tree(build_parser())["update"] == ["apply", "plan", "rollback", "status", "trust"]


def test_status_reads_without_a_receipt(upd):
    body = hub_update_apply.status()
    assert body["in_progress"] is None and body["last_receipt"] is None
    assert json.dumps(body)
