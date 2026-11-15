from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from agents.cli.nerva import EXIT_OK, Context, main


def descriptor_file(tmp_path):
    value = {
        "manifest_version": 1,
        "api_version": 1,
        "id": "boats",
        "version": "1.0.0",
        "capabilities": ["tools"],
        "tools": ["summarize"],
        "commands": [],
        "events": [],
        "requires": {"extensions": {}, "python": {}},
    }
    path = tmp_path / "boats.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def run_cli(tmp_path, report, *argv):
    out, err = io.StringIO(), io.StringIO()
    calls = []

    def post(route, body):
        calls.append((route, body))
        return report

    context = Context(
        environ={}, out=out, err=err,
        client_factory=lambda _env: SimpleNamespace(post=post),
    )
    code = main(["extensions", *argv, str(descriptor_file(tmp_path))], context=context)
    return code, out.getvalue(), err.getvalue(), calls


def activate_report(restart_restore=None):
    report = {
        "ok": True,
        "activation": {
            "id": "boats", "version": "1.0.0",
            "callable_tools": ["boats.summarize"],
            "callable_commands": [], "observed_events": [],
        },
    }
    if restart_restore is not None:
        report["restart_restore"] = restart_restore
    return report


def test_save_failed_warns_but_keeps_live_activation_success(tmp_path):
    code, out, _err, calls = run_cli(
        tmp_path, activate_report({"state": "save_failed", "reason": "disk_full"}),
        "activate",
    )
    assert code == EXIT_OK
    assert "Activated boats 1.0.0" in out
    assert "active now" in out and "restart restoration was not confirmed" in out
    assert "disk_full" not in out
    assert calls[0][0] == "/api/plugins/extensions/activate"


def test_saved_state_has_no_warning_and_missing_field_keeps_legacy_output(tmp_path):
    code, saved, _err, _ = run_cli(
        tmp_path, activate_report({"state": "saved"}), "activate",
    )
    assert code == EXIT_OK and "Warning:" not in saved

    code, legacy, _err, _ = run_cli(tmp_path, activate_report(), "activate")
    assert code == EXIT_OK and "Activated boats 1.0.0" in legacy
    assert "Warning:" not in legacy


@pytest.mark.parametrize("status", [
    None,
    "saved",
    {},
    {"state": "future_state"},
    {"state": "saved", "unexpected": "do-not-show"},
    {"state": "saved", "reason": "raw secret contents"},
])
def test_malformed_or_unknown_restore_status_warns_without_crashing_or_echoing(status, tmp_path):
    report = activate_report(status)
    if status is None:
        report["restart_restore"] = None
    code, out, _err, _ = run_cli(tmp_path, report, "activate")
    assert code == EXIT_OK
    assert "Activated boats 1.0.0" in out
    assert "Warning:" in out and "status is unavailable" in out
    assert "do-not-show" not in out and "raw secret contents" not in out


def test_not_configured_is_a_clear_activation_warning(tmp_path):
    code, out, _err, _ = run_cli(
        tmp_path, activate_report({"state": "not_configured"}), "activate",
    )
    assert code == EXIT_OK
    assert "restart restoration is not configured" in out


def test_activation_json_is_the_unmodified_api_report(tmp_path):
    report = activate_report({"state": "save_failed", "reason": "io_error"})
    code, out, _err, _ = run_cli(tmp_path, report, "activate", "--json")
    assert code == EXIT_OK
    assert json.loads(out) == report
    assert "Warning:" not in out


def test_revoke_remove_failed_warns_consent_stays_revoked_and_json_stays_unchanged(tmp_path):
    report = {
        "ok": True,
        "revoked": True,
        "consent": "not_granted",
        "restart_restore": {"state": "remove_failed", "reason": "disk_error"},
    }
    code, out, _err, calls = run_cli(
        tmp_path, report, "consent", "--revoke",
    )
    assert code == EXIT_OK
    assert "Consent withdrawn." in out
    assert "consent is revoked" in out
    assert "removal of the saved restart route was not confirmed" in out
    assert "authority remains revoked" in out
    assert "disk_error" not in out
    assert calls[0][0] == "/api/plugins/extensions/consent"

    report_json = dict(report)
    code, out, _err, _ = run_cli(tmp_path, report_json, "consent", "--revoke", "--json")
    assert code == EXIT_OK and json.loads(out) == report_json


def test_removed_revoke_status_and_legacy_revoke_remain_warning_free(tmp_path):
    report = {"ok": True, "revoked": True, "restart_restore": {"state": "removed"}}
    code, out, _err, _ = run_cli(tmp_path, report, "consent", "--revoke")
    assert code == EXIT_OK and "Warning:" not in out

    report = {"ok": True, "revoked": True}
    code, out, _err, _ = run_cli(tmp_path, report, "consent", "--revoke")
    assert code == EXIT_OK and "Warning:" not in out


def test_grant_flow_keeps_existing_output_when_report_revoked_is_false(tmp_path):
    report = {
        "ok": True,
        "revoked": False,
        "consent": "granted",
        "declared_digest": "abcdef1234567890",
        "restart_restore": {"state": "remove_failed", "reason": "disk_error"},
    }
    code, out, _err, _ = run_cli(tmp_path, report, "consent")
    assert code == EXIT_OK
    assert "Consent recorded for boats (abcdef123456)" in out
    assert "Warning:" not in out


def test_revoke_request_warns_when_route_absent_but_removal_failed(tmp_path):
    report = {
        "ok": True,
        "revoked": False,
        "consent": "not_granted",
        "restart_restore": {"state": "remove_failed", "reason": "disk_error"},
    }
    code, out, _err, _ = run_cli(tmp_path, report, "consent", "--revoke")
    assert code == EXIT_OK
    assert "Consent withdrawn." in out
    assert "removal of the saved restart route was not confirmed" in out
    assert "authority remains revoked" in out
    assert "disk_error" not in out
