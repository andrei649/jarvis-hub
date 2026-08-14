"""SEC-B8 owner approvals live outside candidate-controlled skill trees."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

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
