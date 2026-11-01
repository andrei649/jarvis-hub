"""Inert owner credential vault: signed record, real Kernel and private bytes."""
import multiprocessing
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agents.core.kernel import Verdict
from agents.core.kernel.binding import make_action_kernel
from agents.core.llm.providers.packages import ProviderPackageError
from tests.test_h361_provider_install_kernel import _bind_real_kernel
from tests.test_h361_provider_install_service import owner, service


def _process_write(args):
    from agents.core.llm.providers.credentials import ProviderCredentialStore
    root, binding, key = args
    return ProviderCredentialStore(root).put(binding, key)


def active(service, tmp_path):
    svc, profile, hooks, _ = service
    svc, orch, kill, seen = _bind_real_kernel(service, tmp_path)
    events = []
    svc.audit = SimpleNamespace(log=events.append)
    profile = replace(profile, auth_type="bearer", fallback_models=("synthetic-model",))
    artifact = svc.stage("addon", profile=profile, hooks=hooks, source="user", actor=owner())
    offer = svc.propose(artifact["artifact_id"], actor=owner())
    svc.decide(offer["proposal_id"], artifact_id=artifact["artifact_id"],
               package_hash=artifact["package_hash"], approved=True, permanent=True,
               actor=owner())
    svc.promote(offer["proposal_id"], actor=owner())
    return svc, orch, kill, seen, events, artifact


def test_real_owner_put_delete_mints_persisted_tombstone_without_secret_echo(service, tmp_path):
    from agents.core.llm.providers.credentials import ProviderCredentialStore, credential_binding

    svc, _, _, seen, events, artifact = active(service, tmp_path)
    key = "synthetic-only-credential-20261028"
    target = ("synthetic-addon", artifact["package_hash"])
    first = svc.put_credential(*target, key, actor=owner())
    assert first == {"configured": True, "generation": 1}
    assert svc.credential_status(*target, actor=owner()) == first
    record = svc._store().require_runnable(target[0], expected_hash=target[1], home=svc.home)
    binding = credential_binding(record, svc.home)
    vault = ProviderCredentialStore(svc.root / "credentials")
    assert vault.read(binding, 1) == key
    assert svc.delete_credential(*target, actor=owner()) == {
        "configured": False, "generation": 2}
    assert svc.credential_status(*target, actor=owner()) == {
        "configured": False, "generation": 2}
    with pytest.raises(ProviderPackageError):
        vault.read(binding, 1)
    assert svc.put_credential(*target, "synthetic-replacement-key", actor=owner()) == {
        "configured": True, "generation": 3}
    actions = [action for action, _ in seen if action.kind == "provider.credential"]
    assert [a.payload["operation"] for a in actions] == ["write", "delete", "write"]
    assert all(a.payload["artifact_id"] == artifact["artifact_id"] for a in actions)
    assert all(decision.verdict is Verdict.GRANT and decision.tier == 3
               for action, decision in seen if action.kind == "provider.credential")
    assert events
    assert key not in str(actions) + str(events) + str(first)
    for path in (svc.root / "credentials").rglob("*"):
        if path.is_file():
            assert key.encode() not in path.read_bytes()


def test_copied_or_absent_receipt_cannot_grant_credential_action(service, tmp_path):
    svc, orch, _, seen, _, artifact = active(service, tmp_path)
    svc.put_credential("synthetic-addon", artifact["package_hash"], "synthetic-key",
                       actor=owner())
    action = next(action for action, _ in seen if action.kind == "provider.credential")
    bound = make_action_kernel(orch)
    assert bound(action, approval_check=lambda _: True).verdict is Verdict.QUEUE
    copied = replace(action, payload=dict(action.payload))
    assert bound(copied, approval_check=lambda _: True).verdict is Verdict.QUEUE


@pytest.mark.parametrize("change", ["wrong_hash", "revoked", "kill", "ask", "expired_owner"])
def test_stale_or_denied_authority_cannot_mutate_vault(service, tmp_path, change):
    svc, orch, kill, seen, _, artifact = active(service, tmp_path)
    target = ("synthetic-addon", artifact["package_hash"])
    actor = owner()
    if change == "wrong_hash":
        target = (target[0], "0" * 64)
    elif change == "revoked":
        svc.revoke("synthetic-addon", actor=owner())
    elif change == "kill":
        kill.engage("provider:synthetic-addon", reason="synthetic halt")
    elif change == "ask":
        orch.autonomy.policy.mode = "ask"
    else:
        actor = owner(lambda: False)
    with pytest.raises(ProviderPackageError):
        svc.put_credential(*target, "synthetic-denied-key", actor=actor)
    if (svc.root / "credentials").exists():
        assert not list((svc.root / "credentials").glob("*.enc"))
    if change in {"kill", "ask"}:
        credential = [d for a, d in seen if a.kind == "provider.credential"]
        if credential:
            assert credential[-1].verdict is (Verdict.DENY if change == "kill" else Verdict.QUEUE)


def test_vault_requires_fernet_and_refuses_symlink_or_replaced_root(service, tmp_path, monkeypatch):
    from agents.core import secrets
    from agents.core.llm.providers.credentials import ProviderCredentialStore, credential_binding

    svc, _, _, _, _, artifact = active(service, tmp_path)
    record = svc._store().require_runnable("synthetic-addon",
        expected_hash=artifact["package_hash"], home=svc.home)
    binding = credential_binding(record, svc.home)
    vault = ProviderCredentialStore(svc.root / "credentials")
    with monkeypatch.context() as patch:
        patch.setattr(secrets, "_HAS_CRYPTOGRAPHY", False)
        with pytest.raises(ProviderPackageError):
            vault.put(binding, "synthetic-key")
    vault.put(binding, "synthetic-key")
    path = vault.path(binding)
    path.rename(path.with_suffix(".saved"))
    path.symlink_to(path.with_suffix(".saved"))
    with pytest.raises(ProviderPackageError):
        vault.status(binding)
    path.unlink()
    (svc.root / "credentials").rename(svc.root / "credentials-old")
    (svc.root / "credentials").mkdir()
    with pytest.raises(ProviderPackageError):
        vault.status(binding)


@pytest.mark.parametrize("master", [None, "synthetic-concurrent-passphrase"])
def test_concurrent_processes_advance_one_durable_generation(
    service, tmp_path, monkeypatch, master
):
    from agents.core.llm.providers.credentials import ProviderCredentialStore, credential_binding
    if master is None:
        monkeypatch.delenv("JARVIS_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("JARVIS_SECRET_KEY", master)
    svc, _, _, _, _, artifact = active(service, tmp_path)
    record = svc._store().require_runnable("synthetic-addon",
        expected_hash=artifact["package_hash"], home=svc.home)
    binding = credential_binding(record, svc.home)
    root = svc.root / "credentials"
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        results = pool.map(_process_write, [
            (root, binding, f"synthetic-parallel-key-{n}") for n in range(4)])
    assert sorted(result["generation"] for result in results) == [1, 2, 3, 4]
    assert ProviderCredentialStore(root).status(binding) == {
        "configured": True, "generation": 4}


@pytest.mark.parametrize("changed", [
    {"home": "other-home"}, {"endpoint": "https://other.invalid/v1"},
    {"source": "legacy"}, {"artifact_id": "f" * 32}, {"package_hash": "f" * 64},
])
def test_copied_ciphertext_cannot_adopt_different_signed_binding(
    service, tmp_path, changed
):
    from agents.core.llm.providers.credentials import ProviderCredentialStore, credential_binding
    svc, _, _, _, _, artifact = active(service, tmp_path)
    record = svc._store().require_runnable("synthetic-addon",
        expected_hash=artifact["package_hash"], home=svc.home)
    binding = credential_binding(record, svc.home)
    vault = ProviderCredentialStore(svc.root / "credentials")
    vault.put(binding, "synthetic-bound-key")
    other = replace(binding, **changed)
    vault.path(other).write_bytes(vault.path(binding).read_bytes())
    vault.path(other).chmod(0o600)
    with pytest.raises(ProviderPackageError):
        vault.read(other, 1)


def test_no_auth_profile_does_not_create_a_key(service, tmp_path):
    svc, profile, hooks, _ = service
    svc, _, _, seen = _bind_real_kernel(service, tmp_path)
    svc.audit = SimpleNamespace(log=lambda _event: None)
    artifact = svc.stage("addon", profile=profile, hooks=hooks, source="user", actor=owner())
    offer = svc.propose(artifact["artifact_id"], actor=owner())
    svc.decide(offer["proposal_id"], artifact_id=artifact["artifact_id"],
                package_hash=artifact["package_hash"], approved=True, permanent=True,
                actor=owner())
    svc.promote(offer["proposal_id"], actor=owner())
    status = svc.credential_status("synthetic-addon", artifact["package_hash"], actor=owner())
    assert status == {"configured": False, "generation": 0}
    assert not list((svc.root / "credentials").glob("cipher*"))
    with pytest.raises(ProviderPackageError):
        svc.put_credential("synthetic-addon", artifact["package_hash"], "synthetic-key",
                           actor=owner())
    assert not [action for action, _ in seen if action.kind == "provider.credential"]


def test_copied_action_during_live_receipt_still_queues(service, tmp_path):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    original = svc.kernel
    copies = []

    def copied_kernel():
        real = original()
        def authorize(action, *, approval_check):
            if action.kind == "provider.credential":
                copy = replace(action, payload=dict(action.payload))
                copies.append(real(copy, approval_check=lambda _: True))
            return real(action, approval_check=approval_check)
        return authorize

    svc.kernel = copied_kernel
    assert svc.put_credential("synthetic-addon", artifact["package_hash"],
                              "synthetic-key", actor=owner())["configured"] is True
    assert len(copies) == 1 and copies[0].verdict is Verdict.QUEUE


def test_audit_failure_prevents_credential_commit(service, tmp_path):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    def failed(_event):
        raise RuntimeError("audit unavailable")
    svc.audit.log = failed
    with pytest.raises(ProviderPackageError):
        svc.put_credential("synthetic-addon", artifact["package_hash"],
                           "synthetic-key", actor=owner())
    assert svc.credential_status("synthetic-addon", artifact["package_hash"],
                                 actor=owner()) == {"configured": False, "generation": 0}


def test_inbound_taint_queues_real_kernel_credential_mutation(service, tmp_path):
    from agents.core.action_origin import bind_action_origin, reset_action_origin

    svc, _, _, seen, _, artifact = active(service, tmp_path)
    token = bind_action_origin("inbound")
    try:
        with pytest.raises(ProviderPackageError):
            svc.put_credential("synthetic-addon", artifact["package_hash"],
                               "synthetic-tainted-key", actor=owner())
    finally:
        reset_action_origin(token)
    credential = [(action, decision) for action, decision in seen
                  if action.kind == "provider.credential"]
    assert len(credential) == 1
    assert credential[0][0].origin == "inbound"
    assert credential[0][1].verdict is Verdict.QUEUE
    assert svc.credential_status("synthetic-addon", artifact["package_hash"],
                                 actor=owner()) == {"configured": False, "generation": 0}


def test_owner_expiring_during_audit_prevents_write(service, tmp_path):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    live = {"yes": True}
    actor = owner(lambda: live["yes"])
    svc.audit.log = lambda _event: live.update(yes=False)
    with pytest.raises(ProviderPackageError):
        svc.put_credential("synthetic-addon", artifact["package_hash"],
                           "synthetic-expired-key", actor=actor)
    assert svc.credential_status("synthetic-addon", artifact["package_hash"],
                                 actor=owner()) == {"configured": False, "generation": 0}


def test_reapproval_of_same_signed_bytes_cannot_adopt_old_secret(service, tmp_path):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    target = ("synthetic-addon", artifact["package_hash"])
    assert svc.put_credential(*target, "synthetic-old-key", actor=owner())["configured"]
    svc.revoke("synthetic-addon", actor=owner())
    _, original_profile, hooks, _ = service
    profile = replace(original_profile, auth_type="bearer",
                      fallback_models=("synthetic-model",))
    again = svc.stage("addon", profile=profile, hooks=hooks,
                      source="user", actor=owner())
    assert again["artifact_id"] != artifact["artifact_id"]
    assert again["package_hash"] == artifact["package_hash"]
    offer = svc.propose(again["artifact_id"], actor=owner())
    svc.decide(offer["proposal_id"], artifact_id=again["artifact_id"],
               package_hash=again["package_hash"], approved=True, permanent=True,
               actor=owner())
    svc.promote(offer["proposal_id"], actor=owner())
    assert svc.credential_status(*target, actor=owner()) == {
        "configured": False, "generation": 0}


@pytest.mark.parametrize("next_operation", ["put", "delete"])
def test_saved_same_binding_envelope_cannot_replay_past_high_water(
    service, tmp_path, next_operation
):
    from agents.core.llm.providers.credentials import ProviderCredentialStore, credential_binding

    svc, _, _, _, _, artifact = active(service, tmp_path)
    target = ("synthetic-addon", artifact["package_hash"])
    record = svc._store().require_runnable(target[0], expected_hash=target[1], home=svc.home)
    binding = credential_binding(record, svc.home)
    vault = ProviderCredentialStore(svc.root / "credentials")
    assert svc.put_credential(*target, "synthetic-old-key", actor=owner())["generation"] == 1
    saved = vault.path(binding).read_bytes()
    if next_operation == "put":
        assert svc.put_credential(*target, "synthetic-new-key", actor=owner())["generation"] == 2
    else:
        assert svc.delete_credential(*target, actor=owner())["generation"] == 2
    vault.path(binding).write_bytes(saved)
    vault.path(binding).chmod(0o600)
    with pytest.raises(ProviderPackageError):
        vault.status(binding)
    with pytest.raises(ProviderPackageError):
        vault.read(binding, 1)
    repaired = svc.put_credential(*target, "synthetic-repair-key", actor=owner())
    assert repaired == {"configured": True, "generation": 3}
    assert vault.read(binding, 3) == "synthetic-repair-key"


def test_interrupted_anchor_first_write_fails_closed_and_repair_advances(
    service, tmp_path, monkeypatch
):
    from agents.core.llm.providers.credentials import ProviderCredentialStore, credential_binding

    svc, _, _, _, _, artifact = active(service, tmp_path)
    target = ("synthetic-addon", artifact["package_hash"])
    record = svc._store().require_runnable(target[0], expected_hash=target[1], home=svc.home)
    binding = credential_binding(record, svc.home)
    vault = ProviderCredentialStore(svc.root / "credentials")
    original = vault._write_file
    failed = {"yes": False}

    def crash_before_envelope(path, content):
        if path == vault.path(binding) and not failed["yes"]:
            failed["yes"] = True
            raise OSError("synthetic crash after anchor")
        return original(path, content)

    monkeypatch.setattr(vault, "_write_file", crash_before_envelope)
    with pytest.raises(OSError):
        vault.put(binding, "synthetic-interrupted-key")
    assert vault.anchor_path(binding).exists()
    assert not vault.path(binding).exists()
    with pytest.raises(ProviderPackageError):
        vault.status(binding)
    with pytest.raises(ProviderPackageError):
        vault.read(binding, 1)
    assert vault.put(binding, "synthetic-repair-key") == {
        "configured": True, "generation": 2}
    assert vault.read(binding, 2) == "synthetic-repair-key"


def test_saved_anchor_alone_cannot_lower_generation_on_repair(service, tmp_path):
    from agents.core.llm.providers.credentials import ProviderCredentialStore, credential_binding

    svc, _, _, _, _, artifact = active(service, tmp_path)
    target = ("synthetic-addon", artifact["package_hash"])
    record = svc._store().require_runnable(target[0], expected_hash=target[1], home=svc.home)
    binding = credential_binding(record, svc.home)
    vault = ProviderCredentialStore(svc.root / "credentials")
    vault.put(binding, "synthetic-old-key")
    old_anchor = vault.anchor_path(binding).read_bytes()
    vault.put(binding, "synthetic-new-key")
    vault.anchor_path(binding).write_bytes(old_anchor)
    vault.anchor_path(binding).chmod(0o600)
    with pytest.raises(ProviderPackageError):
        vault.status(binding)
    with pytest.raises(ProviderPackageError):
        vault.put(binding, "synthetic-repair-key")


def test_anchor_write_failure_keeps_previous_envelope(service, tmp_path, monkeypatch):
    from agents.core.llm.providers.credentials import ProviderCredentialStore, credential_binding

    svc, _, _, _, _, artifact = active(service, tmp_path)
    record = svc._store().require_runnable("synthetic-addon",
        expected_hash=artifact["package_hash"], home=svc.home)
    binding = credential_binding(record, svc.home)
    vault = ProviderCredentialStore(svc.root / "credentials")
    vault.put(binding, "synthetic-old-key")
    original = vault._write_file

    def fail_anchor(path, content):
        if path == vault.anchor_path(binding):
            raise OSError("synthetic anchor write failure")
        return original(path, content)

    monkeypatch.setattr(vault, "_write_file", fail_anchor)
    with pytest.raises(OSError):
        vault.put(binding, "synthetic-new-key")
    assert vault.status(binding) == {"configured": True, "generation": 1}
    assert vault.read(binding, 1) == "synthetic-old-key"


@pytest.mark.parametrize("master", [None, "synthetic-vault-passphrase"])
def test_first_use_syncs_key_or_salt_and_directory_before_anchor(
    service, tmp_path, monkeypatch, master
):
    from agents.core.llm.providers.credentials import ProviderCredentialStore, credential_binding

    svc, _, _, _, _, artifact = active(service, tmp_path)
    record = svc._store().require_runnable("synthetic-addon",
        expected_hash=artifact["package_hash"], home=svc.home)
    binding = credential_binding(record, svc.home)
    vault = ProviderCredentialStore(svc.root / "credentials")
    if master is None:
        monkeypatch.delenv("JARVIS_SECRET_KEY", raising=False)
        material = vault.root / "cipher.json.key"
    else:
        monkeypatch.setenv("JARVIS_SECRET_KEY", master)
        material = vault.root / "cipher.json.salt"
    events = []
    actual_sync = os.fsync
    actual_replace = os.replace

    def sync(fd):
        info = os.fstat(fd)
        if material.exists() and info.st_ino == material.stat().st_ino:
            events.append("material")
        elif info.st_ino == vault.root.stat().st_ino:
            events.append("directory")
        actual_sync(fd)

    def replace(src, dst):
        if str(dst) == str(vault.anchor_path(binding)):
            events.append("anchor")
        actual_replace(src, dst)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    vault.put(binding, "synthetic-first-use-key")
    assert "material" in events
    assert "directory" in events
    assert events.index("material") < events.index("directory") < events.index("anchor")


def test_failed_first_use_material_fsync_never_commits_envelope(
    service, tmp_path, monkeypatch
):
    from agents.core.llm.providers.credentials import ProviderCredentialStore, credential_binding

    svc, _, _, _, _, artifact = active(service, tmp_path)
    record = svc._store().require_runnable("synthetic-addon",
        expected_hash=artifact["package_hash"], home=svc.home)
    binding = credential_binding(record, svc.home)
    vault = ProviderCredentialStore(svc.root / "credentials")
    monkeypatch.delenv("JARVIS_SECRET_KEY", raising=False)
    material = vault.root / "cipher.json.key"
    actual_sync = os.fsync

    def fail_material(fd):
        if material.exists() and os.fstat(fd).st_ino == material.stat().st_ino:
            raise OSError("synthetic material fsync failure")
        actual_sync(fd)

    monkeypatch.setattr(os, "fsync", fail_material)
    with pytest.raises(OSError):
        vault.put(binding, "synthetic-uncommitted-key")
    assert not vault.path(binding).exists()
    assert not vault.anchor_path(binding).exists()
