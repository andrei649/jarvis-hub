"""Strict CLI validation for signed extension command inspection."""
import io
from types import SimpleNamespace

import pytest

from agents.cli.nerva import Context, main


def _run(row):
    report = {"mode": "inspection_only", "reason": row.get("reason", "activated"),
              "extensions": [row]}
    out, err = io.StringIO(), io.StringIO()
    context = Context(environ={}, out=out, err=err,
                      client_factory=lambda _: SimpleNamespace(get=lambda _path: report))
    code = main(["extensions", "list", "--json"], context=context)
    return code, out.getvalue(), err.getvalue()


_VALID = {"id": "boats", "version": "1.0.0", "reason": "activated",
          "execution_available": True, "signature_verified": True,
          "callable_tools": [], "declared_commands": ["boat_report"],
          "callable_commands": ["boat_report"]}


def test_cli_accepts_bounded_verified_command_subset():
    code, out, err = _run(dict(_VALID))
    assert code == 0 and '"boat_report"' in out and not err


def test_cli_accepts_exact_manifest_declaration_limit():
    names = [f"cmd_{index}" for index in range(64)]
    row = dict(_VALID, declared_commands=names, callable_commands=names)
    code, out, err = _run(row)
    assert code == 0 and '"cmd_63"' in out and not err


def test_cli_rejects_above_manifest_declaration_limit():
    names = [f"cmd_{index}" for index in range(65)]
    row = dict(_VALID, declared_commands=names, callable_commands=names)
    code, _out, err = _run(row)
    assert code == 1 and "malformed" in err


@pytest.mark.parametrize("changes", [
    {"signature_verified": False},
    {"execution_available": False},
    {"reason": "acquired_inactive"},
    {"declared_commands": []},
    {"callable_commands": ["boat_report", "not_declared"]},
    {"callable_commands": ["BadName"]},
    {"callable_commands": "boat_report"},
])
def test_cli_rejects_unverified_or_malformed_callable_command_rows(changes):
    row = dict(_VALID)
    row.update(changes)
    code, _out, err = _run(row)
    assert code == 1 and "malformed" in err
