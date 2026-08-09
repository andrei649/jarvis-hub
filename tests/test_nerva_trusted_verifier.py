from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import nerva_trusted_verifier as verifier  # noqa: E402
from check_nerva_program_manifest import load_json_strict  # noqa: E402

MANIFEST = REPO / "docs" / "nerva2" / "NERVA_PROGRAM_MANIFEST_V1.json"
REGISTRY = REPO / "docs" / "nerva2" / "CONTRACT_REGISTRY.json"
DOCUMENT = REPO / "docs" / "nerva2" / "NERVA_PROGRAM_MANIFEST_V1.md"


def _manifest() -> dict:
    return load_json_strict(MANIFEST)


def _registry() -> dict:
    return load_json_strict(REGISTRY)


_MISSING = object()


def _verify(data: object = _MISSING) -> verifier.ManifestVerdict:
    return verifier.verify_data(
        _manifest() if data is _MISSING else data,
        registry=_registry(),
        root=REPO,
        verify_git=False,
    )


def _stream(data: dict, stream_id: str) -> dict:
    return next(item for item in data["streams"] if item["id"] == stream_id)


def _evidence(claim: str) -> dict:
    return {
        "commit": "458df5afabdf12536236522034e7c84493200147",
        "repo_path": "docs/nerva2/DEPENDENCIES.md",
        "issue": 757,
        "pull_request": 852,
        "claim_code": claim,
    }


def _all_done_manifest() -> dict:
    data = _manifest()
    for stream in data["streams"]:
        stream_id = stream["id"]
        stream["program_status"] = "done"
        stream["delivery_eligibility"] = "satisfied"
        for edge in stream["delivery_prerequisites"]:
            edge["gate_state"] = "satisfied"
            edge["accepted_evidence"] = [_evidence("consumer_delivery_gate_accepted")]
        stream["blockers"] = []
        stream["completion_evidence"] = [
            _evidence(
                "e0_control_gate_accepted" if stream_id == "E0" else "stream_completion_accepted"
            )
        ]
    return data


class TestGolden:
    def test_canonical_manifest_verdict_is_clean_and_non_enforcing(self) -> None:
        verdict = _verify()

        assert verdict.structurally_valid is True
        assert verdict.errors == ()
        assert verdict.manifest_id == "nerva.program-manifest.v1"
        assert verdict.schema_version == 1
        assert len(verdict.streams) == 13
        assert verdict.release_ready is False
        assert verdict.authority is not None
        assert verdict.authority.non_enforcing is True
        assert verdict.authority.ultron_remains_sole_action_authority is True
        assert verdict.authority.release_ready is False

    def test_canonical_manifest_golden_render_is_byte_identical(self) -> None:
        assert verifier.render_markdown(_manifest()) == DOCUMENT.read_text(encoding="utf-8")

    def test_canonical_manifest_path_verdict_confirms_no_render_drift(self) -> None:
        verdict = verifier.verify_path(
            MANIFEST,
            registry_path=REGISTRY,
            document_path=DOCUMENT,
            root=REPO,
            verify_git=False,
        )

        assert verdict.structurally_valid is True
        assert verdict.render_current is True

    def test_canonical_stream_verdicts_are_honest(self) -> None:
        verdict = _verify()
        by_id = {assessment.stream_id: assessment for assessment in verdict.streams}

        e0 = by_id["E0"]
        assert e0.program_status == "done"
        assert e0.delivery_eligibility == "satisfied"
        assert e0.derived_eligibility == "satisfied"
        assert e0.eligibility_matches is True
        assert e0.open_gate_count == 0
        assert e0.open_blocker_count == 0
        assert e0.evidence_count == 1
        assert e0.verdict_label == "DONE"

        e1 = by_id["E1"]
        assert e1.program_status == "building"
        assert e1.derived_eligibility == "in_progress"
        assert e1.eligibility_matches is True
        assert e1.verdict_label == "BUILDING"

        e4 = by_id["E4"]
        assert e4.program_status == "not_started"
        assert e4.derived_eligibility == "blocked"
        assert e4.eligibility_matches is True
        assert e4.open_gate_count == 1
        assert e4.open_blocker_count == 1
        assert e4.verdict_label == "BLOCKED"

        e5 = by_id["E5"]
        assert e5.open_gate_count == 4
        assert e5.open_blocker_count == 5
        assert e5.verdict_label == "BLOCKED"

        e11 = by_id["E11"]
        assert e11.open_gate_count == 11
        assert e11.open_blocker_count == 14
        assert e11.verdict_label == "BLOCKED"

        e12 = by_id["E12"]
        assert e12.program_status == "discovery"
        assert e12.derived_eligibility == "in_progress"
        assert e12.verdict_label == "BUILDING"


class TestHostileStructures:
    @pytest.mark.parametrize(
        "hostile",
        ["not-a-dict", ["nested", "list"], 42, True, None],
    )
    def test_verify_data_rejects_non_object_roots(self, hostile: object) -> None:
        verdict = _verify(hostile)

        assert verdict.structurally_valid is False
        assert verdict.errors
        assert verdict.streams == ()
        assert verdict.authority is None
        assert verdict.release_ready is False

    def test_verify_data_rejects_unknown_extra_stream_field(self) -> None:
        data = _manifest()
        _stream(data, "E0")["extra_state"] = True

        verdict = _verify(data)

        assert verdict.structurally_valid is False
        assert any("unknown fields" in error for error in verdict.errors)

    def test_verify_data_rejects_contradictory_delivery_eligibility(self) -> None:
        data = _manifest()
        _stream(data, "E1")["delivery_eligibility"] = "satisfied"

        verdict = _verify(data)
        e1 = next(a for a in verdict.streams if a.stream_id == "E1")

        assert verdict.structurally_valid is False
        assert any(
            "E1: delivery_eligibility must be 'in_progress'" in error for error in verdict.errors
        )
        assert e1.eligibility_matches is False
        assert e1.derived_eligibility == "in_progress"

    def test_verify_data_reports_forged_authority_honestly(self) -> None:
        data = _manifest()
        data["authority"]["can_execute"] = True

        verdict = _verify(data)

        assert verdict.structurally_valid is False
        assert any("authority.can_execute" in error for error in verdict.errors)
        assert verdict.authority is not None
        assert verdict.authority.can_execute is True
        assert verdict.authority.non_enforcing is False

    def test_verify_data_reports_absent_authority(self) -> None:
        data = _manifest()
        del data["authority"]

        verdict = _verify(data)

        assert verdict.structurally_valid is False
        assert verdict.authority is None

    def test_verify_data_rejects_unknown_program_status(self) -> None:
        data = _manifest()
        _stream(data, "E0")["program_status"] = "alien_state"

        verdict = _verify(data)
        e0 = next(a for a in verdict.streams if a.stream_id == "E0")

        assert verdict.structurally_valid is False
        assert any("E0: invalid program_status" in error for error in verdict.errors)
        assert e0.verdict_label == "UNKNOWN"

    def test_verify_data_rejects_missing_streams(self) -> None:
        data = _manifest()
        del data["streams"]

        verdict = _verify(data)

        assert verdict.structurally_valid is False
        assert any("streams must be a list" in error for error in verdict.errors)

    def test_verify_data_rejects_wrong_type_snapshot(self) -> None:
        data = _manifest()
        data["evidence_snapshot"] = "not-an-object"

        verdict = _verify(data)

        assert verdict.structurally_valid is False
        assert any("evidence_snapshot" in error for error in verdict.errors)


class TestHostileJsonLoad:
    def test_verify_path_fails_closed_on_duplicate_json_keys(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.json"
        path.write_text(
            '{"schema_version": 1, "schema_version": 2, "manifest_id": "nerva.program-manifest.v1"}',
            encoding="utf-8",
        )

        verdict = verifier.verify_path(path, registry_path=REGISTRY, root=REPO)

        assert verdict.structurally_valid is False
        assert verdict.errors
        assert verdict.errors[0].startswith("failed to load")

    def test_verify_path_fails_closed_on_non_finite_json(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.json"
        path.write_text(
            '{"schema_version": NaN, "manifest_id": "nerva.program-manifest.v1"}', encoding="utf-8"
        )

        verdict = verifier.verify_path(path, registry_path=REGISTRY, root=REPO)

        assert verdict.structurally_valid is False
        assert verdict.errors[0].startswith("failed to load")

    def test_verify_path_fails_closed_on_missing_file(self) -> None:
        verdict = verifier.verify_path(
            MANIFEST / "does-not-exist.json", registry_path=REGISTRY, root=REPO
        )

        assert verdict.structurally_valid is False
        assert verdict.errors[0].startswith("failed to load")

    def test_verify_path_fails_closed_on_empty_manifest(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.json"
        path.write_text("{}", encoding="utf-8")

        verdict = verifier.verify_path(path, registry_path=REGISTRY, root=REPO)

        assert verdict.structurally_valid is False
        assert verdict.errors


class TestVerdictLabels:
    @pytest.mark.parametrize(
        ("status", "eligibility", "expected"),
        [
            ("done", "satisfied", "DONE"),
            ("done", "blocked", "PARTIAL"),
            ("blocked", "blocked", "BLOCKED"),
            ("building", "in_progress", "BUILDING"),
            ("discovery", "in_progress", "BUILDING"),
            ("verifying", "in_progress", "BUILDING"),
            ("not_started", "blocked", "BLOCKED"),
            ("not_started", "eligible", "OPEN"),
            ("alien", "eligible", "UNKNOWN"),
        ],
    )
    def test_verdict_label_mapping(self, status: str, eligibility: str, expected: str) -> None:
        assert verifier.verdict_label(status, eligibility) == expected

    def test_assess_stream_tolerates_non_dict_stream(self) -> None:
        assessment = verifier.assess_stream("junk")

        assert assessment.verdict_label == "UNKNOWN"
        assert assessment.eligibility_matches is False


class TestCli:
    def test_main_is_informational_and_non_enforcing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = DOCUMENT.read_bytes()

        exit_code = verifier.main(["--manifest", str(MANIFEST)])

        after = DOCUMENT.read_bytes()
        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out.strip()
        assert before == after

    def test_main_returns_zero_even_for_hostile_manifest(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "manifest.json"
        path.write_text('{"schema_version": NaN}', encoding="utf-8")

        exit_code = verifier.main(["--manifest", str(path)])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out.strip()


class TestTrustedSource:
    def test_verify_trusted_source_is_true_on_canonical_repo(self) -> None:
        trusted, errors = verifier.verify_trusted_source()

        assert trusted is True
        assert errors == ()

    def test_verify_data_reports_trusted_source_true(self) -> None:
        verdict = _verify()

        assert verdict.trusted_source is True
        assert verdict.source_errors == ()

    def test_tampered_checker_bytes_are_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tampered = tmp_path / "check_nerva_program_manifest.py"
        tampered.write_text(
            "def validate_manifest(*args, **kwargs):\n    return []\n", encoding="utf-8"
        )
        monkeypatch.setattr(sys.modules["check_nerva_program_manifest"], "__file__", str(tampered))

        trusted, errors = verifier.verify_trusted_source()

        assert trusted is False
        assert errors
        assert any("sha256" in error or "digest" in error for error in errors)

    def test_verify_data_reports_untrusted_source_for_tampered_checker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tampered = tmp_path / "check_nerva_program_manifest.py"
        tampered.write_text("# weakened\n", encoding="utf-8")
        monkeypatch.setattr(sys.modules["check_nerva_program_manifest"], "__file__", str(tampered))

        verdict = _verify()

        assert verdict.trusted_source is False
        assert verdict.source_errors


class TestReleaseAuthority:
    def test_all_streams_done_does_not_imply_release_ready(self) -> None:
        verdict = _verify(_all_done_manifest())

        assert verdict.structurally_valid is True
        assert verdict.all_streams_done is True
        assert verdict.release_ready is False

    def test_canonical_manifest_is_not_all_streams_done(self) -> None:
        verdict = _verify()

        assert verdict.all_streams_done is False
        assert verdict.release_ready is False


class TestNonEnforcingInvariants:
    @pytest.mark.parametrize(
        "posture",
        [
            {"status_is_evidence_label_only": False},
            {"can_authorize": True},
            {"can_execute": True},
            {"completion_authority": True},
            {"release_ready": True},
            {"ultron_remains_sole_action_authority": False},
        ],
    )
    def test_every_false_invariant_flips_non_enforcing(self, posture: dict) -> None:
        base = {
            "status_is_evidence_label_only": True,
            "can_authorize": False,
            "can_execute": False,
            "completion_authority": False,
            "release_ready": False,
            "ultron_remains_sole_action_authority": True,
        }
        base.update(posture)

        assert verifier.AuthorityPosture(**base).non_enforcing is False

    def test_verify_data_reports_non_enforcing_false_for_tampered_invariant(self) -> None:
        data = _manifest()
        data["authority"]["ultron_remains_sole_action_authority"] = False

        verdict = _verify(data)

        assert verdict.structurally_valid is False
        assert verdict.authority is not None
        assert verdict.authority.ultron_remains_sole_action_authority is False
        assert verdict.authority.non_enforcing is False


class TestRootDiscovery:
    def test_verify_path_discovers_repo_root_from_manifest(self) -> None:
        verdict = verifier.verify_path(
            MANIFEST,
            document_path=DOCUMENT,
            verify_git=False,
        )

        assert verdict.structurally_valid is True
        assert verdict.render_current is True

    def test_verify_path_fails_closed_when_root_not_discoverable(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.json"
        path.write_text("{}", encoding="utf-8")

        verdict = verifier.verify_path(path, verify_git=False)

        assert verdict.structurally_valid is False
        assert verdict.errors
