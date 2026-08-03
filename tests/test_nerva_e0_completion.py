from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Callable

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from check_nerva_e0_completion import validate_state  # noqa: E402

MANIFEST = REPO / "docs" / "nerva2" / "E0_COMPLETION.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _errors(data: dict) -> list[str]:
    errors: list[str] = []
    validate_state(data, errors)
    return errors


def test_current_e0_closure_state_is_internally_complete() -> None:
    assert _errors(_manifest()) == []


def _set_status_verifying(data: dict) -> None:
    data["status"] = "verifying"


def _set_close_false(data: dict) -> None:
    data["close_e0"] = False


def _restore_e0_blocker(data: dict) -> None:
    data["first_executable_slices"][0]["blocked_by"] = [758]


def _remove_atlas_blocker(data: dict) -> None:
    for item in data["first_executable_slices"]:
        if item["epic"] == "E3":
            item["blocked_by"] = []


def _remove_repository_ledger_evidence(data: dict) -> None:
    data["accepted_control_slices"] = [
        item
        for item in data["accepted_control_slices"]
        if item["slice"] != "E0.3b2b-repository-ledgers"
    ]


def _leave_one_repository_ledger_verifying(data: dict) -> None:
    data["repository_ledgers"]["STATUS.md"]["state"] = "reconciled"


def _leave_one_issue_ledger_verifying(data: dict) -> None:
    data["issue_ledger_status"]["778"]["state"] = "body_reconciled"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_set_status_verifying, "status=done and close_e0=true together"),
        (_set_close_false, "status=done and close_e0=true together"),
        (_restore_e0_blocker, "partial closure"),
        (_remove_atlas_blocker, "E3 must remain blocked only by #781"),
        (_remove_repository_ledger_evidence, "accepted control slice set"),
        (_leave_one_repository_ledger_verifying, "STATUS.md: state must be e0_done"),
        (_leave_one_issue_ledger_verifying, "issue #778: expected state 'e0_done'"),
    ],
)
def test_partial_e0_closure_states_fail_closed(
    mutate: Callable[[dict], None], message: str
) -> None:
    data = copy.deepcopy(_manifest())
    mutate(data)

    assert any(message in error for error in _errors(data))
