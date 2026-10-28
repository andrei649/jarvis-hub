"""H361 provider package bytes and owner admission, with synthetic fixtures only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agents.core.acquisition.managed_signing import ManagedSigningKeyStore
from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile
from agents.core.kernel import Decision, Verdict
from agents.core.llm.providers import ProviderProfile
from agents.core.llm.providers.admission_contract import provider_sandbox_profile
from agents.core.llm.providers.packages import ProviderPackageError, ProviderPackageStore


@pytest.fixture(autouse=True)
def _kernel_on(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")


def _package(tmp_path: Path, *, provider_id: str = "example") -> Path:
    package = tmp_path / "candidate"
    package.mkdir()
    (package / "provider.json").write_text(
        json.dumps({"schema_version": 1, "id": provider_id, "aliases": []}),
        encoding="utf-8",
    )
    (package / "main.py").write_bytes(b"def register_provider():\n    return {'id': 'example', 'hooks': []}\n")
    (package / "assets").mkdir()
    (package / "assets" / "prompt.txt").write_bytes(b"synthetic asset\n")
    (package / "requirements.lock").write_bytes(b"# synthetic only\n")
    return package


def _store(tmp_path: Path, *, enabled=True, authorizer=None, provision=True,
           owner_authorizer=lambda proposal_id, record, actor: True) -> ProviderPackageStore:
    signing = ManagedSigningKeyStore(tmp_path / "signing")
    if provision:
        signing.provision(key_id="owner", version=1, key=b"s" * 32)
    return ProviderPackageStore(
        tmp_path / "store", signing=signing,
        authorizer=authorizer, enabled=lambda: enabled,
        owner_authorizer=owner_authorizer,
    )


def _stage(store: ProviderPackageStore, package: Path, *, home="synthetic-home",
           source="user"):
    return store.stage(
        package,
        profile=ProviderProfile(
            id="example", display_name="Example", backend_kind="openai-compatible",
            auth_type="bearer", is_user_defined=True,
        ),
        hooks=("prepare_messages",), source=source, home=home,
        sandbox_profile=AcquisitionSandboxProfile(image="python@sha256:" + "a" * 64),
    )


def test_quarantine_requires_explicit_signing_key_before_write(tmp_path: Path):
    package = _package(tmp_path)
    store = _store(tmp_path, provision=False)
    with pytest.raises(ProviderPackageError):
        _stage(store, package)
    assert not (tmp_path / "store" / "registry.enc").exists()


def test_full_snapshot_owner_approval_and_fresh_restart(tmp_path: Path):
    package = _package(tmp_path)
    actions = []

    def grant(action):
        actions.append(action)
        return Decision(Verdict.GRANT, tier=3)

    store = _store(tmp_path, authorizer=grant)
    staged = _stage(store, package)
    assert staged.provider_id == "example"
    assert staged.manifest["runtime_image"] == "python@sha256:" + "a" * 64
    assert staged.manifest["runtime_config_hash"] == provider_sandbox_profile(
        AcquisitionSandboxProfile(image="python@sha256:" + "a" * 64)
    ).config_hash
    assert staged.manifest["sandbox"]["max_output_bytes"] == 896 * 1024
    assert AcquisitionSandboxProfile(image="python@sha256:" + "a" * 64).max_output_bytes == 32 * 1024
    assert {name for name, _ in staged.members} == {
        "provider.json", "main.py", "assets/prompt.txt", "requirements.lock",
    }
    with pytest.raises(ProviderPackageError):
        store.require_runnable("example", home="synthetic-home")
    proposal_id = store.propose(staged.artifact_id)
    with pytest.raises(ProviderPackageError):
        store.promote(proposal_id)
    with pytest.raises(ProviderPackageError):
        store.decide(proposal_id, approved=True, actor="operator", permanent=True)
    store.decide(proposal_id, approved=True, actor="owner", permanent=True)
    promoted = store.promote(proposal_id)
    fresh = _store(tmp_path, authorizer=grant)
    runnable = fresh.require_runnable("example", expected_hash=promoted.package_hash,
                                      home="synthetic-home")
    assert runnable.members == staged.members
    assert all(action.kind == "plugin.load" and action.payload["package_hash"] == staged.package_hash
               and action.payload["risk_tier"] == 3 for action in actions)
    fresh.revoke("example")
    with pytest.raises(ProviderPackageError):
        store.require_runnable("example", home="synthetic-home")


def test_scoped_decision_checks_artifact_and_hash_for_denial_too(tmp_path: Path):
    store = _store(tmp_path, authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    package = _package(tmp_path)
    first = _stage(store, package)
    second = _stage(store, package)
    proposal = store.propose(first.artifact_id)
    with pytest.raises(ProviderPackageError):
        store.decide(proposal, approved=False, actor="operator", permanent=True,
                     expected_artifact_id=first.artifact_id,
                     expected_package_hash=first.package_hash)
    with pytest.raises(ProviderPackageError):
        store.decide(proposal, approved=False, actor="owner", permanent=True,
                     expected_artifact_id=second.artifact_id,
                     expected_package_hash=second.package_hash)
    assert store.inspect(first.artifact_id).package_hash == first.package_hash
    store.decide(proposal, approved=False, actor="owner", permanent=True,
                 expected_artifact_id=first.artifact_id,
                 expected_package_hash=first.package_hash)
    with pytest.raises(ProviderPackageError):
        store.decide(proposal, approved=True, actor="owner", permanent=True,
                     expected_artifact_id=first.artifact_id,
                     expected_package_hash=first.package_hash)
    assert store.list_active(home="synthetic-home") == ()


def test_active_inventory_requires_exact_signed_scope(tmp_path: Path):
    store = _store(tmp_path, authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    record = _stage(store, _package(tmp_path))
    proposal = store.propose(record.artifact_id)
    store.decide(proposal, approved=True, actor="owner", permanent=True,
                 expected_artifact_id=record.artifact_id,
                 expected_package_hash=record.package_hash)
    store.promote(proposal)
    assert store.list_active(home="wrong-home") == ()
    assert [item.package_hash for item in store.list_active(home="synthetic-home")] == [record.package_hash]
    store.revoke("example")
    assert store.list_active(home="synthetic-home") == ()


def test_kernel_denial_blocks_promotion_and_execution(tmp_path: Path):
    package = _package(tmp_path)
    decision = Verdict.DENY
    store = _store(tmp_path, authorizer=lambda action: Decision(decision, tier=3))
    staged = _stage(store, package)
    proposal = store.propose(staged.artifact_id)
    store.decide(proposal, approved=True, actor="owner", permanent=True)
    with pytest.raises(ProviderPackageError):
        store.promote(proposal)
    decision = Verdict.GRANT
    store.promote(proposal)
    decision = Verdict.DENY
    with pytest.raises(ProviderPackageError):
        store.require_runnable("example", home="synthetic-home")


def test_untrusted_package_links_and_fifo_refused_before_read(tmp_path: Path):
    package = _package(tmp_path)
    store = _store(tmp_path)
    (package / "assets" / "link").symlink_to(package / "main.py")
    with pytest.raises(ProviderPackageError):
        _stage(store, package)
    (package / "assets" / "link").unlink()
    os.mkfifo(package / "assets" / "fifo")
    with pytest.raises(ProviderPackageError):
        _stage(store, package)
    assert not (tmp_path / "store" / "registry.enc").exists()


def test_missing_kernel_and_disabled_runtime_never_run(tmp_path: Path):
    package = _package(tmp_path)
    store = _store(tmp_path, authorizer=None)
    staged = _stage(store, package)
    proposal = store.propose(staged.artifact_id)
    store.decide(proposal, approved=True, actor="owner", permanent=True)
    with pytest.raises(ProviderPackageError):
        store.promote(proposal)
    disabled = _store(tmp_path, enabled=False,
                      authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    with pytest.raises(ProviderPackageError):
        disabled.promote(proposal)


@pytest.mark.parametrize("mutation", ["bytes", "invalid-base64", "profile", "sandbox", "signature"])
def test_stored_tamper_refuses_runnable_even_after_approval(tmp_path: Path, mutation: str):
    package = _package(tmp_path)
    store = _store(tmp_path, authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    staged = _stage(store, package)
    proposal = store.propose(staged.artifact_id)
    store.decide(proposal, approved=True, actor="owner", permanent=True)
    store.promote(proposal)
    state = json.loads(store._cipher.decrypt_bytes(store.path.read_bytes()))
    row = state["artifacts"][staged.artifact_id]
    if mutation == "bytes":
        row["members"][0]["data"] = "Y2hhbmdlZA=="
    elif mutation == "invalid-base64":
        row["members"][0]["data"] = "%%%"
    elif mutation == "profile":
        row["manifest"]["profile"]["display_name"] = "Other"
    elif mutation == "sandbox":
        row["manifest"]["runtime_image"] = "python@sha256:" + "b" * 64
    else:
        row["signature"]["signature"] = "0" * 64
    store.path.write_bytes(store._cipher.encrypt_bytes(json.dumps(state).encode()))
    with pytest.raises(ProviderPackageError):
        store.require_runnable("example", home="synthetic-home")


def test_metadata_profile_and_builtin_alias_mismatch_are_refused_before_write(tmp_path: Path):
    package = _package(tmp_path)
    store = _store(tmp_path)
    (package / "provider.json").write_text(
        json.dumps({"schema_version": 1, "id": "example", "aliases": ["ollama"]}),
        encoding="utf-8",
    )
    with pytest.raises(ProviderPackageError):
        _stage(store, package)
    assert not store.path.exists()
    (package / "provider.json").write_text(
        json.dumps({"schema_version": 1, "id": "wrong", "aliases": []}),
        encoding="utf-8",
    )
    with pytest.raises(ProviderPackageError):
        _stage(store, package)
    assert not store.path.exists()


def test_stale_approval_and_disabled_execution_revalidate_fresh_state(tmp_path: Path):
    package = _package(tmp_path)
    store = _store(tmp_path, authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    staged = _stage(store, package)
    proposal = store.propose(staged.artifact_id)
    second = _store(tmp_path, authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    second.decide(proposal, approved=True, actor="owner", permanent=True)
    with pytest.raises(ProviderPackageError):
        store.decide(proposal, approved=True, actor="owner", permanent=True)
    second.promote(proposal)
    disabled = _store(tmp_path, enabled=False,
                      authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    with pytest.raises(ProviderPackageError):
        disabled.require_runnable("example", home="synthetic-home")


def test_empty_directories_are_bound_and_file_byte_limit_refuses_before_write(tmp_path: Path):
    package = _package(tmp_path)
    (package / "empty").mkdir()
    store = _store(tmp_path)
    staged = _stage(store, package)
    assert "empty" in staged.manifest["directories"]
    second_root = tmp_path / "second"
    second_root.mkdir()
    oversize = _package(second_root)
    (oversize / "large.bin").write_bytes(b"x" * (1024 * 1024 + 1))
    before = store.path.read_bytes()
    with pytest.raises(ProviderPackageError):
        _stage(store, oversize)
    assert store.path.read_bytes() == before


def test_subscription_and_codex_identity_cannot_be_claimed_by_package(tmp_path: Path):
    package = _package(tmp_path, provider_id="openai-codex")
    (package / "provider.json").write_text(
        json.dumps({"schema_version": 1, "id": "openai-codex", "aliases": [],
                    "replacement_target": "openai-codex"}), encoding="utf-8",
    )
    store = _store(tmp_path)
    with pytest.raises(ProviderPackageError):
        store.stage(
            package,
            profile=ProviderProfile(id="openai-codex", display_name="Fake Codex",
                                    backend_kind="openai-compatible", auth_type="bearer",
                                    is_user_defined=True),
            hooks=(), source="user", home="synthetic-home",
            replacement_target="openai-codex",
            sandbox_profile=AcquisitionSandboxProfile(image="python@sha256:" + "a" * 64),
        )
    assert not store.path.exists()


def test_untyped_kernel_grant_cannot_promote(tmp_path: Path):
    package = _package(tmp_path)
    store = _store(tmp_path, authorizer=lambda action: True)
    staged = _stage(store, package)
    proposal = store.propose(staged.artifact_id)
    store.decide(proposal, approved=True, actor="owner", permanent=True)
    with pytest.raises(ProviderPackageError):
        store.promote(proposal)


def test_signed_profile_survives_fresh_hash_seed(tmp_path: Path):
    package = _package(tmp_path)
    store = _store(tmp_path, authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    profile = ProviderProfile(
        id="example", display_name="Example", backend_kind="openai-compatible",
        auth_type="bearer", is_user_defined=True,
        capabilities=frozenset({f"capability-{number}" for number in range(16)}),
    )
    staged = store.stage(
        package, profile=profile, hooks=("prepare_messages",), source="user", home="synthetic-home",
        sandbox_profile=AcquisitionSandboxProfile(image="python@sha256:" + "a" * 64),
    )
    proposal = store.propose(staged.artifact_id)
    store.decide(proposal, approved=True, actor="owner", permanent=True)
    store.promote(proposal)
    script = """
import sys
from agents.core.acquisition.managed_signing import ManagedSigningKeyStore
from agents.core.kernel import Decision, Verdict
from agents.core.llm.providers.packages import ProviderPackageStore
store = ProviderPackageStore(sys.argv[1], signing=ManagedSigningKeyStore(sys.argv[2]),
    authorizer=lambda action: Decision(Verdict.GRANT, tier=3), enabled=lambda: True)
assert store.require_runnable('example', home='synthetic-home').provider_id == 'example'
"""
    for seed in ("1", "2", "3"):
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / "store"), str(tmp_path / "signing")],
            env={**os.environ, "PYTHONHASHSEED": seed}, capture_output=True, text=True,
            check=False, timeout=10,
        )
        assert result.returncode == 0, result.stderr


def test_kernel_flag_off_refuses_before_authorizer(tmp_path: Path, monkeypatch):
    package = _package(tmp_path)
    actions = []

    def grant(action):
        actions.append(action)
        return Decision(Verdict.GRANT, tier=3)

    store = _store(tmp_path, authorizer=grant)
    staged = _stage(store, package)
    proposal = store.propose(staged.artifact_id)
    store.decide(proposal, approved=True, actor="owner", permanent=True)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "0")
    with pytest.raises(ProviderPackageError):
        store.promote(proposal)
    assert actions == []


def test_provider_metadata_uses_discovery_byte_cap(tmp_path: Path):
    package = _package(tmp_path)
    metadata = {"schema_version": 1, "id": "example", "aliases": []}
    (package / "provider.json").write_text(
        json.dumps(metadata) + " " * 16_384, encoding="utf-8",
    )
    store = _store(tmp_path)
    with pytest.raises(ProviderPackageError):
        _stage(store, package)
    assert not store.path.exists()


def test_owner_decision_requires_bound_authenticated_authority(tmp_path: Path):
    package = _package(tmp_path)
    store = _store(tmp_path, owner_authorizer=None)
    staged = _stage(store, package)
    proposal = store.propose(staged.artifact_id)
    with pytest.raises(ProviderPackageError):
        store.decide(proposal, approved=True, actor="owner", permanent=True)
    assert store._load()["proposals"][proposal]["status"] == "pending"


def test_restored_registry_cannot_resurrect_revoked_artifact(tmp_path: Path):
    package = _package(tmp_path)
    store = _store(tmp_path, authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    staged = _stage(store, package)
    proposal = store.propose(staged.artifact_id)
    store.decide(proposal, approved=True, actor="owner", permanent=True)
    store.promote(proposal)
    old_registry = store.path.read_bytes()
    store.revoke("example")
    store.path.write_bytes(old_registry)
    fresh = _store(tmp_path, authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    with pytest.raises(ProviderPackageError):
        fresh.require_runnable("example", home="synthetic-home")


def test_owner_authorizer_is_bound_to_exact_proposal_and_signed_record(tmp_path: Path):
    package = _package(tmp_path)
    accepted = set()

    def authenticated_owner(proposal_id, record, actor):
        return (proposal_id in accepted and record.provider_id == "example"
                and record.package_hash == staged.package_hash and actor == "owner")

    store = _store(tmp_path, owner_authorizer=authenticated_owner)
    staged = _stage(store, package)
    proposal = store.propose(staged.artifact_id)
    with pytest.raises(ProviderPackageError):
        store.decide(proposal, approved=True, actor="owner", permanent=True)
    accepted.add(proposal)
    store.decide(proposal, approved=True, actor="owner", permanent=True)


def test_contract_rejects_no_hook_surface_before_kernel_call(tmp_path: Path):
    package = _package(tmp_path)
    actions = []

    def grant(action):
        actions.append(action)
        return Decision(Verdict.GRANT, tier=3)

    store = _store(tmp_path, authorizer=grant)
    staged = store.stage(
        package,
        profile=ProviderProfile(id="example", display_name="Example",
                                backend_kind="openai-compatible", is_user_defined=True),
        hooks=(), source="user", home="synthetic-home",
        sandbox_profile=AcquisitionSandboxProfile(image="python@sha256:" + "a" * 64),
    )
    proposal = store.propose(staged.artifact_id)
    store.decide(proposal, approved=True, actor="owner", permanent=True)
    with pytest.raises(ProviderPackageError):
        store.promote(proposal)
    assert actions == []


def _approve_and_promote(store: ProviderPackageStore, staged):
    proposal = store.propose(staged.artifact_id)
    store.decide(proposal, approved=True, actor="owner", permanent=True)
    return store.promote(proposal)


def test_same_provider_id_in_two_homes_keeps_both_exact_admissions(tmp_path: Path):
    package_a = _package(tmp_path)
    second_root = tmp_path / "second"
    second_root.mkdir()
    package_b = _package(second_root)
    store = _store(tmp_path, authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    home_a = _approve_and_promote(store, _stage(store, package_a, home="home-a"))
    home_b = _approve_and_promote(store, _stage(store, package_b, home="home-b"))
    assert home_a.package_hash != home_b.package_hash
    assert store.require_runnable("example", expected_hash=home_a.package_hash,
                                  home="home-a").artifact_id == home_a.artifact_id
    assert store.require_runnable("example", expected_hash=home_b.package_hash,
                                  home="home-b").artifact_id == home_b.artifact_id
    assert store.require_runnable("example", home="home-a").artifact_id == home_a.artifact_id
    with pytest.raises(ProviderPackageError):
        store.require_runnable("example", expected_hash=home_a.package_hash, home="home-b")
    with pytest.raises(ProviderPackageError):
        store.require_runnable("example")
    store.revoke("example")
    with pytest.raises(ProviderPackageError):
        store.require_runnable("example", home="home-a")
    with pytest.raises(ProviderPackageError):
        store.require_runnable("example", home="home-b")


def test_bundled_and_legacy_admissions_preserve_exact_binding_and_rank(tmp_path: Path):
    bundled = _package(tmp_path)
    second_root = tmp_path / "second"
    second_root.mkdir()
    legacy = _package(second_root)
    store = _store(tmp_path, authorizer=lambda action: Decision(Verdict.GRANT, tier=3))
    bundled_record = _approve_and_promote(
        store, _stage(store, bundled, source="bundled", home=None),
    )
    legacy_record = _approve_and_promote(
        store, _stage(store, legacy, source="legacy", home=None),
    )
    assert store.require_runnable("example").artifact_id == legacy_record.artifact_id
    assert store.require_runnable("example", expected_hash=bundled_record.package_hash
                                  ).artifact_id == bundled_record.artifact_id


def test_package_module_imports_when_fcntl_is_unavailable():
    script = """
import builtins
real_import = builtins.__import__
def without_fcntl(name, *args, **kwargs):
    if name == 'fcntl':
        raise ImportError('synthetic unsupported host')
    return real_import(name, *args, **kwargs)
builtins.__import__ = without_fcntl
from agents.core.llm.providers.packages import KIND
assert KIND == 'plugin.load'
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True,
        check=False, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_store_refuses_without_safe_lock(tmp_path: Path, monkeypatch):
    package = _package(tmp_path)
    store = _store(tmp_path)
    monkeypatch.setattr("agents.core.llm.providers.packages.fcntl", None)
    with pytest.raises(ProviderPackageError):
        _stage(store, package)
    assert not store.path.exists()


def test_profile_json_bound_refuses_before_signing_or_registry_write(tmp_path: Path):
    package = _package(tmp_path)
    store = _store(tmp_path)
    with pytest.raises(ProviderPackageError):
        store.stage(
            package,
            profile=ProviderProfile(
                id="example", display_name="Example", backend_kind="openai-compatible",
                is_user_defined=True, description="x" * (33 * 1024),
            ),
            hooks=("prepare_messages",), source="user", home="synthetic-home",
            sandbox_profile=AcquisitionSandboxProfile(image="python@sha256:" + "a" * 64),
        )
    assert not store.path.exists()


def test_store_rejects_writable_nonsticky_ancestor(tmp_path: Path):
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    unsafe.chmod(0o777)
    signing = ManagedSigningKeyStore(tmp_path / "signing")
    with pytest.raises(ProviderPackageError):
        ProviderPackageStore(unsafe / "store", signing=signing)
    assert not (unsafe / "store").exists()


def test_store_checks_existing_root_owner_before_chmod(tmp_path: Path, monkeypatch):
    root = tmp_path / "store"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    signing = ManagedSigningKeyStore(tmp_path / "signing")
    actual_uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: actual_uid + 1)
    with pytest.raises(ProviderPackageError):
        ProviderPackageStore(root, signing=signing)
    assert root.stat().st_mode & 0o777 == 0o755


def test_sticky_owned_temp_ancestor_remains_supported(tmp_path: Path):
    sticky = tmp_path / "sticky"
    sticky.mkdir()
    sticky.chmod(0o1777)
    signing = ManagedSigningKeyStore(tmp_path / "signing")
    store = ProviderPackageStore(sticky / "store", signing=signing)
    assert store.root.is_dir()
    assert store.root.stat().st_mode & 0o777 == 0o700
