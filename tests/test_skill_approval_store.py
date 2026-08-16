"""SEC-B8 owner approvals live outside candidate-controlled skill trees."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agents.core.skills.approval import SkillApprovalStore
from agents.core.skills.signing import source_fingerprint


def _make_skill(path: Path, *, body: str = "VALUE = 1\n") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    (path / "main.py").write_text(body, encoding="utf-8")
    return path


def test_approval_is_bound_to_canonical_path_and_source(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path / "skills" / "demo")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")

    record = store.approve(skill)

    assert store.is_approved(skill)
    assert record["canonical_path"] == str(skill.resolve())
    assert record["source_fingerprint"] == source_fingerprint(skill)

    copied = _make_skill(tmp_path / "other" / "demo")
    assert not store.is_approved(copied)

    (skill / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert not store.is_approved(skill)


def test_private_record_keeps_drifted_path_classified_as_external(
    tmp_path: Path,
) -> None:
    skill = _make_skill(tmp_path / "external")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill)

    (skill / "main.py").write_text("VALUE = 'changed'\n", encoding="utf-8")

    assert store.tracks_path(skill)
    assert not store.is_approved(skill)


def test_copied_approval_registry_cannot_approve_another_path(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path / "skills" / "demo")
    registry = tmp_path / "private" / "approvals.json"
    SkillApprovalStore(registry).approve(skill)
    copied_skill = _make_skill(tmp_path / "copied" / "demo")
    copied_registry = tmp_path / "copied-private" / "approvals.json"
    copied_registry.parent.mkdir(parents=True)
    shutil.copy2(registry, copied_registry)

    assert not SkillApprovalStore(copied_registry).is_approved(copied_skill)


def test_corrupt_approval_registry_fails_closed(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path / "skills" / "demo")
    registry = tmp_path / "private" / "approvals.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("not-json", encoding="utf-8")

    assert not SkillApprovalStore(registry).is_approved(skill)


def test_unknown_approval_registry_schema_fails_closed(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path / "skills" / "demo")
    canonical = str(skill.resolve())
    key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    registry = tmp_path / "private" / "approvals.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "version": 999,
                "approvals": {
                    key: {
                        "canonical_path": canonical,
                        "source_fingerprint": source_fingerprint(skill),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert not SkillApprovalStore(registry).is_approved(skill)


def test_approval_fingerprints_nested_artifact_paths_and_bytes(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path / "skills" / "demo")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill)

    artifact = skill / "assets" / "prompt.txt"
    artifact.parent.mkdir()
    artifact.write_text("first\n", encoding="utf-8")
    assert not store.is_approved(skill)

    store.approve(skill)
    artifact.write_text("second\n", encoding="utf-8")
    assert not store.is_approved(skill)

    store.approve(skill)
    artifact.rename(artifact.with_name("renamed.txt"))
    assert not store.is_approved(skill)

    store.approve(skill)
    bytecode = skill / "__pycache__" / "helper.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"candidate-controlled-bytecode")
    assert not store.is_approved(skill)


def test_approval_fingerprints_provenance_sidecar(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path / "skills" / "demo")
    sidecar = skill / "manifest.json"
    sidecar.write_text('{"imported": true, "source": "one"}', encoding="utf-8")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill)

    sidecar.write_text('{"imported": true, "source": "two"}', encoding="utf-8")

    assert not store.is_approved(skill)


def test_linked_artifact_invalidates_approval(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path / "skills" / "demo")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill)
    external = tmp_path / "external.py"
    external.write_text("VALUE = 1\n", encoding="utf-8")
    link = skill / "helper.py"
    try:
        link.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    assert not store.is_approved(skill)


@pytest.mark.parametrize("replacement", [None, "not-json", '{"version": 999}'])
def test_loaded_store_rechecks_registry_at_decision_time(
    tmp_path: Path,
    replacement: str | None,
) -> None:
    skill = _make_skill(tmp_path / "skills" / "demo")
    registry = tmp_path / "private" / "approvals.json"
    store = SkillApprovalStore(registry)
    store.approve(skill)
    assert store.is_approved(skill)

    if replacement is None:
        registry.unlink()
    else:
        registry.write_text(replacement, encoding="utf-8")

    assert not store.is_approved(skill)


def test_stale_store_instances_reload_and_merge_approvals(tmp_path: Path) -> None:
    first = _make_skill(tmp_path / "skills" / "first")
    second = _make_skill(tmp_path / "skills" / "second")
    registry = tmp_path / "private" / "approvals.json"
    first_store = SkillApprovalStore(registry)
    second_store = SkillApprovalStore(registry)

    first_store.approve(first)
    second_store.approve(second)

    reloaded = SkillApprovalStore(registry)
    assert reloaded.is_approved(first)
    assert reloaded.is_approved(second)


def test_processes_lock_reload_and_merge_approvals(tmp_path: Path) -> None:
    first = _make_skill(tmp_path / "skills" / "first")
    second = _make_skill(tmp_path / "skills" / "second")
    registry = tmp_path / "private" / "approvals.json"
    ready = [tmp_path / "ready-1", tmp_path / "ready-2"]
    go = tmp_path / "go"
    script = """
import sys
import time
from pathlib import Path
from agents.core.skills.approval import SkillApprovalStore

registry, skill, ready, go = map(Path, sys.argv[1:])
store = SkillApprovalStore(registry)
ready.write_text("ready", encoding="utf-8")
while not go.exists():
    time.sleep(0.01)
store.approve(skill)
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(registry), str(skill), str(flag), str(go)],
            cwd=Path(__file__).resolve().parent.parent,
        )
        for skill, flag in zip((first, second), ready, strict=True)
    ]
    deadline = time.monotonic() + 10
    while not all(flag.exists() for flag in ready) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert all(flag.exists() for flag in ready)
    go.write_text("go", encoding="utf-8")
    return_codes = [process.wait(timeout=10) for process in processes]

    assert return_codes == [0, 0]
    reloaded = SkillApprovalStore(registry)
    assert reloaded.is_approved(first)
    assert reloaded.is_approved(second)
