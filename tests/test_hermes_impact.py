"""Changed paths select contracts; unmatched paths never imply no impact."""

import subprocess

from scripts import hermes_impact


def _runner(changes, untracked=()):
    def run(argv, **kwargs):
        assert kwargs["timeout"] <= 20
        if "rev-parse" in argv:
            output = "a" * 40 + "\n"
        elif "diff" in argv:
            output = "\0".join(changes) + "\0"
        else:
            output = "\0".join(untracked) + "\0"
        return subprocess.CompletedProcess(argv, 0, output.encode(), b"")
    return run


def _row(ident, path):
    return {"id": ident, "status": "partial", "recorded_status": "partial",
            "evidence": [{"path": path, "sha256": "b" * 64}]}


def test_mapping_limits_detail_but_preserves_unknown_counts(tmp_path):
    rows = [_row("H001", "agents/core/shared.py"), _row("H002", "agents/core/shared.py")]
    result = hermes_impact.build_map(
        tmp_path, rows, {}, limit=1,
        runner=_runner(["agents/core/shared.py", "agents/core/new_dependency.py"]),
    )
    assert result["affected_count"] == 2
    assert [r["id"] for r in result["affected"]] == ["H001"]
    assert result["has_more"] is True
    assert result["unknown_count"] == 1
    assert result["unknown_paths"] == ["agents/core/new_dependency.py"]
    assert result["credit_changed"] is False


def test_document_edits_do_not_select_unrelated_contracts(tmp_path):
    rows = [_row("H001", "agents/core/a.py"), _row("H002", "docs/feature.md")]
    result = hermes_impact.build_map(
        tmp_path, rows, {}, runner=_runner(["docs/feature.md"]),
    )
    assert [r["id"] for r in result["affected"]] == ["H002"]
    assert result["unknown_count"] == 0


def test_untracked_source_is_visible_without_reading_its_bytes(tmp_path):
    result = hermes_impact.build_map(
        tmp_path, [], {}, runner=_runner([], ["agents/core/new.py", "private-note.md"]),
    )
    assert result["unknown_count"] == 2
    assert result["unknown_paths"] == ["agents/core/new.py", "private-note.md"]
    assert not list(tmp_path.iterdir())


def test_invalid_base_ref_does_not_fall_back_to_another_checkout(tmp_path):
    result = subprocess.CompletedProcess([], 128, b"", b"not a repository")
    import pytest

    with pytest.raises(RuntimeError, match="resolve"):
        hermes_impact.build_map(tmp_path, [], {}, runner=lambda *a, **k: result)


def test_explicit_dependency_receipts_map_shared_behavior(tmp_path):
    rows = [_row("H001", "agents/core/a.py"), _row("H002", "agents/core/b.py")]
    data = {"impact_receipts": [
        {"id": "H001", "paths": ["agents/core/a.py", "agents/core/security/guard.py"]},
    ]}
    result = hermes_impact.build_map(
        tmp_path, rows, data, runner=_runner(["agents/core/security/guard.py"]),
    )
    assert [row["id"] for row in result["affected"]] == ["H001"]
    assert result["affected"][0]["changes"] == [
        {"path": "agents/core/security/guard.py", "mapping": ["declared_dependency"]},
    ]
    assert result["unknown_count"] == 0
