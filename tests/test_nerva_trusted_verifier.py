from __future__ import annotations

import importlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import nerva_trusted_verifier as verifier  # noqa: E402

MANIFEST = REPO / "docs" / "nerva2" / "NERVA_PROGRAM_MANIFEST_V1.json"


def _strict_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return _strict_json(MANIFEST)


def _all_done_manifest() -> dict:
    data = _manifest()
    for stream in data["streams"]:
        stream["program_status"] = "done"
        stream["delivery_eligibility"] = "satisfied"
        stream["delivery_prerequisites"] = []
        stream["blockers"] = []
    return data


def _write_candidate(
    root: Path, *, checker_source: str, manifest: object | None = None
) -> tuple[Path, Path]:
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "check_nerva_program_manifest.py").write_text(checker_source, encoding="utf-8")
    manifest_path = root / "docs" / "nerva2" / "NERVA_PROGRAM_MANIFEST_V1.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({} if manifest is None else manifest), encoding="utf-8")
    return manifest_path, scripts / "check_nerva_program_manifest.py"


class TestInformationalVerdict:
    def test_canonical_manifest_is_reported_but_never_trusted_or_validated(self) -> None:
        verdict = verifier.verify_data(_manifest())

        assert verdict.manifest_id == "nerva.program-manifest.v1"
        assert verdict.schema_version == 1
        assert len(verdict.streams) == 13
        assert verdict.structurally_valid is False
        assert verdict.trusted_source is False
        assert verdict.release_ready is False
        assert verdict.render_current is None
        assert verdict.errors == (verifier.STRUCTURAL_VALIDATION_ERROR,)
        assert verdict.source_errors == (verifier.SOURCE_TRUST_ERROR,)

    def test_canonical_authority_is_only_reported_as_declared(self) -> None:
        verdict = verifier.verify_data(_manifest())

        assert verdict.authority is not None
        assert verdict.authority.non_enforcing is True
        assert verdict.authority.ultron_remains_sole_action_authority is True
        assert verdict.release_ready is False

    @pytest.mark.parametrize("hostile", [None, [], "manifest", 7, True])
    def test_hostile_root_shapes_return_total_failed_verdict(self, hostile: object) -> None:
        verdict = verifier.verify_data(hostile)

        assert verdict.structurally_valid is False
        assert verdict.trusted_source is False
        assert verdict.release_ready is False
        assert verdict.authority is None
        assert verdict.streams == ()

    def test_forged_authority_is_reported_but_cannot_grant_release(self) -> None:
        data = _manifest()
        data["authority"].update(
            {
                "can_authorize": True,
                "can_execute": True,
                "completion_authority": True,
                "release_ready": True,
            }
        )

        verdict = verifier.verify_data(data)

        assert verdict.authority is not None
        assert verdict.authority.can_authorize is True
        assert verdict.authority.can_execute is True
        assert verdict.authority.completion_authority is True
        assert verdict.authority.release_ready is True
        assert verdict.authority.non_enforcing is False
        assert verdict.release_ready is False
        assert verdict.structurally_valid is False

    def test_all_declared_streams_done_cannot_grant_release(self) -> None:
        verdict = verifier.verify_data(_all_done_manifest())

        assert verdict.all_streams_done is True
        assert verdict.release_ready is False
        assert verdict.structurally_valid is False
        assert verdict.trusted_source is False


class TestStreamAssessment:
    def test_canonical_stream_labels_remain_informational(self) -> None:
        verdict = verifier.verify_data(_manifest())
        by_id = {assessment.stream_id: assessment for assessment in verdict.streams}

        assert by_id["E0"].verdict_label == "DONE"
        assert by_id["E0"].evidence_count == 1
        assert by_id["E1"].verdict_label == "BUILDING"
        assert by_id["E4"].verdict_label == "BLOCKED"
        assert by_id["E4"].open_gate_count == 1
        assert by_id["E4"].open_blocker_count == 1
        assert by_id["E11"].open_gate_count == 11
        assert by_id["E11"].open_blocker_count == 14

    @pytest.mark.parametrize(
        ("status", "eligibility", "expected"),
        [
            ("done", "satisfied", "DONE"),
            ("done", "blocked", "PARTIAL"),
            ("blocked", "blocked", "BLOCKED"),
            ("building", "in_progress", "BUILDING"),
            ("not_started", "eligible", "OPEN"),
            ("not_started", "blocked", "BLOCKED"),
            ("invented", "eligible", "UNKNOWN"),
        ],
    )
    def test_verdict_label_mapping(self, status: str, eligibility: str, expected: str) -> None:
        assert verifier.verdict_label(status, eligibility) == expected

    def test_assess_stream_tolerates_non_dict_stream(self) -> None:
        result = verifier.assess_stream(["hostile"])

        assert result.stream_id == "?"
        assert result.verdict_label == "UNKNOWN"
        assert result.eligibility_matches is False


class TestAuthorityDefaults:
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

    def test_missing_sole_ultron_evidence_fails_closed(self) -> None:
        data = _manifest()
        del data["authority"]["ultron_remains_sole_action_authority"]

        verdict = verifier.verify_data(data)

        assert verdict.structurally_valid is False
        assert verdict.trusted_source is False
        assert verdict.authority is not None
        assert verdict.authority.ultron_remains_sole_action_authority is False
        assert verdict.authority.non_enforcing is False


class TestStrictRawLoad:
    def test_canonical_path_is_still_permanently_fail_closed(self) -> None:
        verdict = verifier.verify_path(MANIFEST)

        assert verdict.manifest_id == "nerva.program-manifest.v1"
        assert verdict.structurally_valid is False
        assert verdict.trusted_source is False
        assert verdict.release_ready is False

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('{"manifest_id":"first","manifest_id":"second"}', "duplicate JSON key"),
            ('{"schema_version":NaN}', "non-finite JSON number"),
            ("", "failed to load manifest"),
        ],
    )
    def test_malformed_json_returns_total_failed_verdict(
        self, tmp_path: Path, raw: str, expected: str
    ) -> None:
        path = tmp_path / "manifest.json"
        path.write_text(raw, encoding="utf-8")

        verdict = verifier.verify_path(path)

        assert verdict.structurally_valid is False
        assert verdict.trusted_source is False
        assert verdict.release_ready is False
        assert any(expected in error for error in verdict.errors)

    def test_missing_path_returns_total_failed_verdict(self, tmp_path: Path) -> None:
        verdict = verifier.verify_path(tmp_path / "missing.json")

        assert verdict.structurally_valid is False
        assert verdict.trusted_source is False
        assert verdict.release_ready is False
        assert any("failed to load manifest" in error for error in verdict.errors)

    def test_fake_repository_root_cannot_change_verdict(self, tmp_path: Path) -> None:
        candidate = tmp_path / "candidate"
        (candidate / ".git").mkdir(parents=True)
        manifest, _ = _write_candidate(candidate, checker_source="VALUE = 1\n")

        verdict = verifier.verify_path(manifest)

        assert verdict.structurally_valid is False
        assert verdict.trusted_source is False
        assert verdict.release_ready is False


class TestCandidateSideTrustIsImpossible:
    def test_candidate_module_exposes_no_trust_granting_api(self) -> None:
        assert not hasattr(verifier, "verify_trusted_source")
        assert not hasattr(verifier, "render_markdown")
        assert "trust_anchor_path" not in inspect.signature(verifier.verify_data).parameters
        assert "trust_anchor_path" not in inspect.signature(verifier.verify_path).parameters
        assert "root" not in inspect.signature(verifier.verify_path).parameters

    def test_cli_has_no_candidate_supplied_trust_anchor_option(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        assert verifier.main(["--trust-anchor", "candidate-controlled.json"]) == 2
        output = capsys.readouterr()
        assert output.err == ""
        assert "trusted_source=no" in output.out
        assert "release_ready=no" in output.out

    def test_module_import_never_imports_candidate_checker(self) -> None:
        sys.modules.pop("check_nerva_program_manifest", None)

        importlib.reload(verifier)

        assert "check_nerva_program_manifest" not in sys.modules

    @pytest.mark.parametrize("anchor_location", ["local", "outside"])
    def test_arbitrary_anchor_files_cannot_grant_or_execute_checker(
        self, tmp_path: Path, anchor_location: str
    ) -> None:
        candidate = tmp_path / "candidate"
        marker = tmp_path / "checker-executed.txt"
        manifest, _ = _write_candidate(
            candidate,
            checker_source=(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
            ),
            manifest=_manifest(),
        )
        anchor = (
            candidate / "candidate-anchor.json"
            if anchor_location == "local"
            else tmp_path / "candidate-created-outside-anchor.json"
        )
        anchor.write_text('{"candidate":"controls this"}', encoding="utf-8")

        verdict = verifier.verify_path(manifest)

        assert anchor.exists()
        assert marker.exists() is False
        assert verdict.trusted_source is False
        assert verdict.structurally_valid is False
        assert verdict.release_ready is False

    @pytest.mark.skipif(os.name != "nt", reason="NTFS junction probe")
    def test_checker_junction_cannot_execute_or_grant_trust(self, tmp_path: Path) -> None:
        candidate = tmp_path / "candidate"
        candidate.mkdir()
        external_scripts = tmp_path / "external-scripts"
        external_scripts.mkdir()
        marker = tmp_path / "checker-executed.txt"
        (external_scripts / "check_nerva_program_manifest.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
            encoding="utf-8",
        )
        link = candidate / "scripts"
        result = subprocess.run(  # noqa: S603, S607
            ["cmd", "/c", "mklink", "/J", str(link), str(external_scripts)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"directory junction unavailable: {result.stderr or result.stdout}")
        try:
            manifest = candidate / "manifest.json"
            manifest.write_text(json.dumps(_manifest()), encoding="utf-8")

            verdict = verifier.verify_path(manifest)

            assert marker.exists() is False
            assert verdict.trusted_source is False
            assert verdict.structurally_valid is False
            assert verdict.release_ready is False
        finally:
            os.rmdir(link)

    def test_incompatible_checker_is_never_loaded_and_cannot_raise(self, tmp_path: Path) -> None:
        candidate = tmp_path / "candidate"
        manifest, _ = _write_candidate(candidate, checker_source="VALUE = 1\n")

        verdict = verifier.verify_path(manifest)

        assert verdict.trusted_source is False
        assert verdict.structurally_valid is False
        assert verdict.release_ready is False

    def test_candidate_module_contains_no_dynamic_checker_execution(self) -> None:
        source = inspect.getsource(verifier)

        assert "check_nerva_program_manifest" not in source
        assert "exec(" not in source
        assert "compile(" not in source


class TestCli:
    def test_main_is_informational_and_non_enforcing(self, capsys: pytest.CaptureFixture) -> None:
        exit_code = verifier.main(["--manifest", str(MANIFEST)])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert "structurally_valid=no" in output
        assert "trusted_source=no" in output
        assert "release_ready=no" in output
        assert "source-error:" in output
        assert "authority=declares_non_enforcing" in output
        assert "authority=non_enforcing" not in output
        assert "declared_verdicts=" in output

        for args, expected_code in (
            (["--help"], 0),
            (["--unknown\ntrusted_source=yes"], 2),
        ):
            completed = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "nerva_trusted_verifier.py"), *args],
                capture_output=True,
                text=True,
                check=False,
            )
            assert completed.returncode == expected_code
            assert completed.stderr == ""
            assert "structurally_valid=no" in completed.stdout
            assert "trusted_source=no" in completed.stdout
            assert "release_ready=no" in completed.stdout
            assert "\ntrusted_source=yes\n" not in completed.stdout
            assert completed.stdout.isascii()

        assert verifier.main(["\ud800"]) == 2
        captured = capsys.readouterr()
        assert captured.err == ""
        assert "structurally_valid=no" in captured.out
        assert "trusted_source=no" in captured.out
        assert "release_ready=no" in captured.out
        assert "\\ud800" in captured.out
        assert captured.out.isascii()

    def test_manifest_value_cannot_inject_cli_verdict_fields(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        path = tmp_path / "manifest.json"
        path.write_text(
            json.dumps(
                {
                    "manifest_id": "forged\ntrusted_source=yes",
                    "schema_version": 1,
                    "streams": [],
                }
            ),
            encoding="utf-8",
        )

        assert verifier.main(["--manifest", str(path)]) == 0
        output = capsys.readouterr().out

        assert "manifest_id=forged\\ntrusted_source=yes" in output
        assert "\ntrusted_source=yes\n" not in output
        assert output.isascii()

    def test_stream_values_cannot_inject_cli_verdict_fields(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        path = tmp_path / "manifest.json"
        path.write_text(
            json.dumps(
                {
                    "streams": [
                        {
                            "id": "E0\nrelease_ready=yes",
                            "program_status": "building\ntrusted_source=yes",
                            "delivery_eligibility": "in_progress\nauthority=owner",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        assert verifier.main(["--manifest", str(path)]) == 0
        output = capsys.readouterr().out

        assert "E0\\nrelease_ready=yes: UNKNOWN" in output
        assert "status=building\\ntrusted_source=yes" in output
        assert "eligibility=in_progress\\nauthority=owner" in output
        assert "\nrelease_ready=yes\n" not in output
        assert "\ntrusted_source=yes\n" not in output
        assert output.isascii()

    def test_error_values_cannot_inject_cli_verdict_fields(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        path = tmp_path / "manifest.json"
        hostile_key = "duplicate\nrelease_ready=yes"
        encoded_key = json.dumps(hostile_key)
        path.write_text(
            f"{{{encoded_key}: 1, {encoded_key}: 2}}",
            encoding="utf-8",
        )

        assert verifier.main(["--manifest", str(path)]) == 0
        output = capsys.readouterr().out

        assert "duplicate JSON key: duplicate\\nrelease_ready=yes" in output
        assert "\nrelease_ready=yes\n" not in output
        assert output.isascii()

    def test_lone_surrogate_is_ascii_escaped_without_crashing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        path = tmp_path / "manifest.json"
        path.write_text(
            '{"manifest_id": "\\ud800", "streams": []}',
            encoding="utf-8",
        )

        assert verifier.main(["--manifest", str(path)]) == 0
        output = capsys.readouterr().out

        assert "manifest_id=\\ud800" in output
        assert output.isascii()

    def test_deeply_nested_json_returns_failed_verdict_instead_of_raising(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        path = tmp_path / "manifest.json"
        path.write_text("[" * 80 + "0" + "]" * 80, encoding="utf-8")

        assert verifier.main(["--manifest", str(path)]) == 0
        output = capsys.readouterr().out

        assert "structurally_valid=no" in output
        assert "trusted_source=no" in output
        assert "release_ready=no" in output
        assert "error: failed to load manifest:" in output
        assert output.isascii()

    def test_main_returns_zero_for_hostile_manifest(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        path = tmp_path / "hostile.json"
        path.write_text("[]", encoding="utf-8")

        exit_code = verifier.main(["--manifest", str(path)])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert "structurally_valid=no" in output
        assert "trusted_source=no" in output
        assert "release_ready=no" in output
