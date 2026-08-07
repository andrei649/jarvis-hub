from __future__ import annotations

import ast
import copy
import json
import shutil
from pathlib import Path

import pytest

from scripts.check_nerva_e8_1c_preflight import (
    DOCUMENT_RELATIVE,
    EVIDENCE_RELATIVE,
    PreflightError,
    load_json_strict,
    main,
    render_markdown,
    run,
    validate_evidence,
)

REPO = Path(__file__).resolve().parents[1]
CHECKER = REPO / "scripts/check_nerva_e8_1c_preflight.py"
DESIGN = REPO / "docs/superpowers/specs/2026-08-06-e8-1c-hermes-preflight-design.md"
EXPECTED_LICENSE_PATHS = {
    "skills/productivity/docx/LICENSE.txt",
    "skills/productivity/pdf/LICENSE.txt",
    "skills/productivity/powerpoint/LICENSE.txt",
    "skills/productivity/xlsx/LICENSE.txt",
}
EXPECTED_OSV_FINDINGS = {
    "aiohttp": {
        "version": "3.14.1",
        "ids": {"CVE-2026-59881", "CVE-2026-69243", "CVE-2026-69244"},
    },
    "cryptography": {
        "version": "48.0.1",
        "ids": {"CVE-2026-69247", "CVE-2026-69248", "CVE-2026-69249"},
    },
}
EXPECTED_CONTAINER_EFFECTS = {
    "container_default_root_entrypoint",
    "container_dispatches_via_s6_stage2",
    "container_narrow_shim_candidate",
    "container_stage2_mutation",
}
EXPECTED_PROVENANCE_LAYERS = {
    "linux/amd64": (
        "sha256:1011de3fa75e1d7fcc3542343a13cf0bf7ef565115a1e091354c0dd0f121f47a",
        263204,
    ),
    "linux/arm64": (
        "sha256:87bd0d7e671e0c152d2b813f31c4fd6223a3b99e7e14ad52527ceaf26ac5728c",
        340516,
    ),
}


def _evidence() -> dict[str, object]:
    return load_json_strict(REPO / EVIDENCE_RELATIVE)


def _copy_checker_root(tmp_path: Path) -> Path:
    for relative in (
        EVIDENCE_RELATIVE,
        DOCUMENT_RELATIVE,
        Path("pyproject.toml"),
        Path("requirements-beta.lock"),
        Path("requirements-beta.txt"),
        Path("requirements-dev.lock"),
        Path("requirements-dev.txt"),
        Path("requirements.lock"),
        Path("requirements.txt"),
        Path("worldview/ingestion-workers/pyproject.toml"),
        Path("worldview/ingestion-workers/requirements.txt"),
        Path(".github/third-party-manifest.json"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, target)
    return tmp_path


def test_canonical_evidence_validates_and_renders_current_document() -> None:
    evidence = _evidence()

    assert validate_evidence(evidence, root=REPO) == []
    assert (REPO / DOCUMENT_RELATIVE).read_text(encoding="utf-8") == render_markdown(evidence)


def test_working_design_does_not_claim_premature_acceptance() -> None:
    design = DESIGN.read_text(encoding="utf-8")

    assert "Accepted working design" not in design
    assert "pending independent exact-head acceptance" in design


def test_method_distinguishes_metadata_from_package_or_image_downloads() -> None:
    method = _evidence()["method"]

    assert "artifact_downloaded" not in method
    assert method["package_or_image_artifact_downloaded"] is False
    assert "provenance metadata payloads were fetched" in " ".join(method["limitations"])


def test_validator_rejects_unknown_evidence_method_source() -> None:
    evidence = _evidence()
    evidence["method"]["sources"].append("runtime_probe")

    assert any(
        "method.sources: must match the authoritative read-only source set" in error
        for error in validate_evidence(evidence, root=REPO)
    )


def test_renderer_is_stable_for_semantically_unordered_arrays() -> None:
    evidence = _evidence()
    reordered = copy.deepcopy(evidence)
    reordered["upstream"]["source_files"].reverse()
    reordered["invocation_surfaces"].reverse()
    reordered["side_effects"].reverse()
    reordered["method"]["limitations"].reverse()
    reordered["supply_chain"]["vulnerability_review"]["limitations"].reverse()
    reordered["compatibility"]["isolation"]["requirements"].reverse()

    assert validate_evidence(reordered, root=REPO) == []
    assert render_markdown(reordered) == render_markdown(evidence)


def test_strict_loader_rejects_oversized_json_before_parsing(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (1024 * 1024 + 1))

    with pytest.raises(PreflightError, match="exceeds 1048576 bytes"):
        load_json_strict(oversized)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b'{"key": 1, "key": 2}', "duplicate JSON key"),
        (b"\xef\xbb\xbf{}", "UTF-8 BOM"),
        (b'{"value": 1.5}', "floating-point JSON value"),
        (b'{"value": NaN}', "non-finite JSON value"),
    ],
)
def test_strict_loader_rejects_noncanonical_json(
    tmp_path: Path, payload: bytes, message: str
) -> None:
    candidate = tmp_path / "hostile.json"
    candidate.write_bytes(payload)

    with pytest.raises(PreflightError, match=message):
        load_json_strict(candidate)


def test_strict_loader_rejects_excessive_nesting(tmp_path: Path) -> None:
    nested: object = "leaf"
    for _ in range(50):
        nested = [nested]
    candidate = tmp_path / "deep.json"
    candidate.write_text(json.dumps(nested), encoding="utf-8")

    with pytest.raises(PreflightError, match="nesting exceeds"):
        load_json_strict(candidate)


def test_strict_loader_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(PreflightError, match="non-symlink regular file"):
        load_json_strict(link)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda item: item.update({"unknown": True}), "unknown fields"),
        (lambda item: item.pop("record_id"), "missing fields"),
        (
            lambda item: item["authority"].update({"can_execute": 0}),
            "authority.can_execute",
        ),
        (
            lambda item: item["authority"].update({"can_execute": True}),
            "authority.can_execute",
        ),
        (
            lambda item: item["status"].update({"release_ready": True}),
            "status.release_ready",
        ),
        (
            lambda item: item["e9"].update({"state": "measured"}),
            "e9.state",
        ),
        (
            lambda item: item["e9"].update({"can_promote": True}),
            "e9.can_promote",
        ),
        (
            lambda item: item["supply_chain"]["transitive_license_closure"].update(
                {"state": "verified", "complete": True}
            ),
            "transitive_license_closure",
        ),
    ],
)
def test_validator_rejects_schema_authority_and_promotion_mutations(
    mutator: object, message: str
) -> None:
    evidence = _evidence()
    mutator(evidence)

    assert any(message in error for error in validate_evidence(evidence, root=REPO))


def test_validator_accepts_shared_ledger_reconciliation_as_only_repository_effect() -> None:
    evidence = _evidence()
    evidence["repository_effects"]["shared_ledgers_changed"] = True

    assert validate_evidence(evidence, root=REPO) == []


@pytest.mark.parametrize(
    "field",
    [
        "dependency_enrolled",
        "manifest_enrolled",
        "adapter_implemented",
        "provider_registered",
        "route_added",
        "runtime_changed",
    ],
)
def test_validator_keeps_runtime_repository_effects_false(field: str) -> None:
    evidence = _evidence()
    evidence["repository_effects"][field] = True

    assert any(
        f"repository_effects.{field}" in error for error in validate_evidence(evidence, root=REPO)
    )


@pytest.mark.parametrize("value", [False, 0, 1, "true"])
def test_validator_requires_truthful_boolean_shared_ledger_claim(value: object) -> None:
    evidence = _evidence()
    evidence["repository_effects"]["shared_ledgers_changed"] = value

    assert any(
        "repository_effects.shared_ledgers_changed" in error
        for error in validate_evidence(evidence, root=REPO)
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda item: item["upstream"].update({"commit_sha": "0" * 40}),
            "upstream.commit_sha",
        ),
        (
            lambda item: item["upstream"].update({"tree_sha": "0" * 40}),
            "upstream.tree_sha",
        ),
        (
            lambda item: item["upstream"]["source_files"][0].update({"sha256": "0" * 64}),
            ".sha256",
        ),
        (
            lambda item: item["distribution"]["container"].update(
                {"index_digest": "sha256:" + "0" * 64}
            ),
            "container.index_digest",
        ),
        (
            lambda item: item["invocation_surfaces"][1].update({"selector": "--safe-mode -z"}),
            "surface hermes-oneshot.selector",
        ),
    ],
)
def test_validator_rejects_substituted_source_and_invocation_bindings(
    mutator: object, message: str
) -> None:
    evidence = _evidence()
    mutator(evidence)

    assert any(message in error for error in validate_evidence(evidence, root=REPO))


def test_oneshot_candidate_uses_environment_safe_mode_not_chat_flag() -> None:
    evidence = _evidence()
    surface = next(
        item for item in evidence["invocation_surfaces"] if item["id"] == "hermes-oneshot"
    )
    assertions = " ".join(evidence["compatibility"]["fixture"]["required_assertions"])

    assert surface["selector"] == "-z/--oneshot"
    assert "safe_mode_cli_not_supported_with_oneshot" in surface["reason_codes"]
    assert "HERMES_SAFE_MODE" in assertions
    assert "--safe-mode" not in surface["selector"]


def test_validator_requires_safe_mode_context_and_memory_limit() -> None:
    evidence = _evidence()
    surface = next(
        item for item in evidence["invocation_surfaces"] if item["id"] == "hermes-oneshot"
    )
    surface["reason_codes"].remove("safe_mode_does_not_skip_context_or_memory")

    assert any(
        "surface hermes-oneshot.reason_codes: required hazards are missing" in error
        for error in validate_evidence(evidence, root=REPO)
    )


def test_upstream_default_branch_drift_is_time_bounded() -> None:
    comparison = _evidence()["upstream"]["default_branch_comparison"]

    assert comparison == {
        "observed_at_utc": "2026-08-06T23:40:22Z",
        "ref": "main",
        "ahead_by": 300,
        "behind_by": 0,
        "status": "ahead",
        "evidence_state": "recorded_metadata",
    }


def test_container_default_and_bypass_risks_are_exactly_bound() -> None:
    evidence = _evidence()
    source_paths = {item["path"] for item in evidence["upstream"]["source_files"]}
    effects = {item["id"]: item for item in evidence["side_effects"]}
    assertions = " ".join(evidence["compatibility"]["fixture"]["required_assertions"])

    assert effects.keys() >= EXPECTED_CONTAINER_EFFECTS
    assert {
        "docker/entrypoint-dispatch.sh",
        "docker/hermes-exec-shim.sh",
        "docker/stage2-hook.sh",
    } <= source_paths
    assert "/opt/hermes/bin/hermes" in assertions
    assert "10000:10000" in assertions
    assert "/opt/data" in assertions
    assert "/init" in assertions
    assert "uid=10000" in assertions
    assert "mode=0700" in assertions


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("surface", "both_console_mappings"),
        ("phase", "runtime_static"),
        ("source_path", "LICENSE"),
        ("anchors", ["L1"]),
        ("anchors", ["L381-L466", "L228-L252", "L76-L86", "L2-L4"]),
        ("behavior", "No mutation occurs."),
        ("risk", "Safe."),
    ],
)
def test_validator_exactly_binds_each_side_effect_record(field: str, replacement: object) -> None:
    evidence = _evidence()
    effect = next(
        item for item in evidence["side_effects"] if item["id"] == "container_stage2_mutation"
    )
    effect[field] = replacement

    assert any(
        "side_effects: record binding mismatch for 'container_stage2_mutation'" in error
        for error in validate_evidence(evidence, root=REPO)
    )


def test_oci_provenance_is_observed_but_never_promoted_to_trust() -> None:
    evidence = _evidence()
    provenance = evidence["distribution"]["container"]["provenance"]
    layers = {
        item["platform"]: (item["layer_digest"], item["size"]) for item in provenance["statements"]
    }

    assert provenance["state"] == "recorded_metadata"
    assert provenance["authenticity_verified"] is False
    assert provenance["signature_present"] is False
    assert provenance["buildkit_materials_complete"] is False
    assert provenance["registry_referrer_count"] == 0
    assert provenance["workflow_run"] == 30834568564
    assert provenance["workflow_attempt"] == 1
    assert layers == EXPECTED_PROVENANCE_LAYERS


@pytest.mark.parametrize(
    "field", ["authenticity_verified", "signature_present", "buildkit_materials_complete"]
)
def test_validator_rejects_promoted_oci_provenance(field: str) -> None:
    evidence = _evidence()
    evidence["distribution"]["container"]["provenance"][field] = True

    assert any(
        f"distribution.container.provenance.{field}" in error
        for error in validate_evidence(evidence, root=REPO)
    )


@pytest.mark.parametrize("missing_token", ["/opt/hermes/bin/hermes", "HERMES_SAFE_MODE=1"])
def test_validator_rejects_missing_fixture_boundary(missing_token: str) -> None:
    evidence = _evidence()
    assertions = evidence["compatibility"]["fixture"]["required_assertions"]
    evidence["compatibility"]["fixture"]["required_assertions"] = [
        item for item in assertions if missing_token not in item
    ]

    assert any(
        "required_assertions: missing boundary" in error
        for error in validate_evidence(evidence, root=REPO)
    )


def test_restrictive_bundled_licenses_are_fail_closed_and_exactly_bound() -> None:
    evidence = _evidence()
    licenses = evidence["supply_chain"]["bundled_license_findings"]
    observed = {item["path"] for item in licenses["findings"]}

    assert licenses["state"] == "verified_static"
    assert licenses["complete"] is False
    assert licenses["owner_or_legal_acceptance"] is False
    assert observed == EXPECTED_LICENSE_PATHS
    assert all(
        item["classification"] == "separate_restrictive_anthropic_terms"
        for item in licenses["findings"]
    )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("complete", "bundled_license_findings.complete"),
        ("owner_or_legal_acceptance", "bundled_license_findings.owner_or_legal_acceptance"),
    ],
)
def test_validator_rejects_promoted_bundled_license_state(field: str, message: str) -> None:
    evidence = _evidence()
    evidence["supply_chain"]["bundled_license_findings"][field] = True

    assert any(message in error for error in validate_evidence(evidence, root=REPO))


def test_osv_snapshot_binds_six_deduplicated_groups_to_lock_versions() -> None:
    evidence = _evidence()
    review = evidence["supply_chain"]["vulnerability_review"]
    observed = {
        item["package"]: {"version": item["version"], "ids": set(item["finding_ids"])}
        for item in review["affected_lock_packages"]
    }

    assert review["complete"] is False
    assert review["alias_deduplication"] == "cve_group"
    assert review["finding_count"] == 6
    assert observed == EXPECTED_OSV_FINDINGS


def test_validator_rejects_substituted_osv_lock_version() -> None:
    evidence = _evidence()
    evidence["supply_chain"]["vulnerability_review"]["affected_lock_packages"][0]["version"] = (
        "3.14.2"
    )

    assert any(
        "affected_lock_packages: exact affected lock versions and CVE groups required" in error
        for error in validate_evidence(evidence, root=REPO)
    )


def test_validator_rejects_substituted_osv_source() -> None:
    evidence = _evidence()
    evidence["supply_chain"]["vulnerability_review"]["sources"] = [
        "https://example.invalid/advisories"
    ]

    assert any(
        "vulnerability_review.sources: must match the canonical primary-source set" in error
        for error in validate_evidence(evidence, root=REPO)
    )


def test_pypi_response_metadata_is_content_bound() -> None:
    evidence = _evidence()
    pypi = evidence["distribution"]["pypi"]

    assert pypi["response_bytes"] == 45448
    assert pypi["response_sha256"] == (
        "af89ca1ed4d433b307b1f3c0b65459424815d83077fa66c2934b61a5d07c15e2"
    )
    assert pypi["response_etag"] == '"p7GD9lV+0ULm+HAZzyDjPQ"'
    assert pypi["release_count"] == 11


@pytest.mark.parametrize(
    "requirement",
    [
        "hermes-agent==0.20.0",
        "hermes_agent==0.20.0",
        "hermes.agent==0.20.0",
        "HeRmEs__..Agent[cli]>=0.20.0",
        "hermes-agent @ https://example.invalid/hermes.whl",
    ],
)
def test_repository_guard_detects_dependency_enrolment(tmp_path: Path, requirement: str) -> None:
    root = _copy_checker_root(tmp_path)
    requirements = root / "requirements.txt"
    requirements.write_text(
        requirements.read_text(encoding="utf-8") + f"\n{requirement}\n",
        encoding="utf-8",
    )

    errors = validate_evidence(_evidence(), root=root)

    assert "repository_effects: hermes-agent is enrolled in requirements.txt" in errors


@pytest.mark.parametrize(
    "requirement",
    [
        "not-hermes-agent==1.0",
        "hermes-agent-tools==1.0",
        "hermes agent==0.20.0",
        "# hermes-agent==0.20.0",
    ],
)
def test_repository_guard_avoids_dependency_name_false_positives(
    tmp_path: Path, requirement: str
) -> None:
    root = _copy_checker_root(tmp_path)
    requirements = root / "requirements.txt"
    requirements.write_text(
        requirements.read_text(encoding="utf-8") + f"\n{requirement}\n",
        encoding="utf-8",
    )

    assert validate_evidence(_evidence(), root=root) == []


@pytest.mark.parametrize(
    "relative",
    [
        "worldview/ingestion-workers/pyproject.toml",
        "worldview/ingestion-workers/requirements.txt",
    ],
)
def test_repository_guard_detects_nested_dependency_enrolment(
    tmp_path: Path, relative: str
) -> None:
    root = _copy_checker_root(tmp_path)
    dependency_file = root / relative
    injected = (
        '"hermes.agent==0.20.0"' if relative.endswith("pyproject.toml") else "hermes.agent==0.20.0"
    )
    dependency_file.write_text(
        dependency_file.read_text(encoding="utf-8") + f"\n{injected}\n",
        encoding="utf-8",
    )

    errors = validate_evidence(_evidence(), root=root)

    assert f"repository_effects: hermes-agent is enrolled in {relative}" in errors


@pytest.mark.parametrize(
    "declaration",
    [
        'hermes-agent = { version = "0.20.0" }',
        'Hermes.Agent = "0.20.0"',
        'hermes_agent = "0.20.0"',
    ],
)
def test_repository_guard_detects_bare_pyproject_dependency_keys(
    tmp_path: Path, declaration: str
) -> None:
    root = _copy_checker_root(tmp_path)
    pyproject = root / "worldview/ingestion-workers/pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + f"\n{declaration}\n",
        encoding="utf-8",
    )

    errors = validate_evidence(_evidence(), root=root)

    assert (
        "repository_effects: hermes-agent is enrolled in worldview/ingestion-workers/pyproject.toml"
    ) in errors


def test_repository_guard_dependency_file_set_cannot_be_narrowed() -> None:
    evidence = _evidence()
    evidence["repository_effects"]["checked_dependency_files"].pop()

    assert any(
        "checked_dependency_files: must match the canonical dependency surfaces" in error
        for error in validate_evidence(evidence, root=REPO)
    )


@pytest.mark.parametrize(
    "source",
    [
        {"name": "hermes-agent"},
        {"name": "Hermes.Agent"},
        {"repo": "NousResearch/hermes-agent"},
    ],
)
@pytest.mark.parametrize("section", ["sources", "untracked"])
def test_repository_guard_detects_manifest_enrolment(
    tmp_path: Path, source: dict[str, str], section: str
) -> None:
    root = _copy_checker_root(tmp_path)
    manifest_path = root / ".github/third-party-manifest.json"
    manifest = load_json_strict(manifest_path)
    manifest[section].append(source)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = validate_evidence(_evidence(), root=root)

    assert "repository_effects: Hermes is enrolled in third-party manifest" in errors


@pytest.mark.parametrize("section", ["sources", "untracked"])
def test_repository_guard_rejects_non_object_manifest_records(tmp_path: Path, section: str) -> None:
    root = _copy_checker_root(tmp_path)
    manifest_path = root / ".github/third-party-manifest.json"
    manifest = load_json_strict(manifest_path)
    manifest[section].append("hermes-agent")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert any(
        f"third-party manifest {section} entries must be objects" in error
        for error in validate_evidence(_evidence(), root=root)
    )


def test_run_detects_drift_and_write_repairs_only_canonical_document(
    tmp_path: Path,
) -> None:
    root = _copy_checker_root(tmp_path)
    document = root / DOCUMENT_RELATIVE
    document.write_text("drift", encoding="utf-8")

    with pytest.raises(PreflightError, match="generated Markdown drift"):
        run(root, write=False)

    assert run(root, write=True) == ["generated Markdown updated"]
    assert run(root, write=False) == ["E8.1c preflight valid; generated Markdown current"]


def test_run_rejects_oversized_output_before_read(tmp_path: Path) -> None:
    root = _copy_checker_root(tmp_path)
    document = root / DOCUMENT_RELATIVE
    document.write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(PreflightError, match="generated Markdown target exceeds"):
        run(root, write=True)

    assert document.stat().st_size == 1024 * 1024 + 1


def test_run_rejects_symlink_output_target(tmp_path: Path) -> None:
    root = _copy_checker_root(tmp_path)
    document = root / DOCUMENT_RELATIVE
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    document.unlink()
    try:
        document.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(PreflightError, match="must not be a symlink"):
        run(root, write=True)

    assert outside.read_text(encoding="utf-8") == "outside"


def test_checker_import_graph_remains_standard_library_and_offline() -> None:
    tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots <= {
        "__future__",
        "argparse",
        "datetime",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "re",
        "stat",
        "sys",
        "tempfile",
        "typing",
        "unicodedata",
    }
    source = CHECKER.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "hermes_cli" not in imported_roots
    assert "run_agent" not in imported_roots


def test_cli_rejects_missing_root_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing"

    assert main(["--root", str(missing), "--check"]) == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert captured.err.strip()
