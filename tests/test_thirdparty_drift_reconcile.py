"""Closing the loop on the third-party drift alert (DRA-61).

The workflow opens/refreshes a tracking issue when drift appears but never
closes it once the pins catch up, so a stale alert outlives the drift. This
tests the closer: a pure decision module plus an owner-gated workflow step.

The decisive property is that "no drift found" is NOT the same signal as "drift
resolved": a crashed script, an empty result set or a GitHub API blip all produce
zero DRIFT rows, and closing on that would auto-close a live alert.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "scripts"))

import check_thirdparty_drift as drift  # noqa: E402
import reconcile_drift_alert as reconcile_mod  # noqa: E402

WORKFLOW = repo_root / ".github/workflows/thirdparty-drift.yml"


def _row(name="superpowers", drift_state="ok", consistency="ok"):
    return {
        "name": name, "repo": "o/r", "pinned": "1.0.0", "latest": "1.0.0",
        "consistency": consistency, "drift": drift_state, "auto_update": False,
    }


# ── drift_resolved ───────────────────────────────────────────────────────────

def test_drift_resolved_only_when_every_tracked_source_is_ok():
    assert drift.drift_resolved([_row(), _row("memory-mcp")]) is True


def test_drift_resolved_false_on_actual_drift():
    assert drift.drift_resolved([_row(), _row("memory-mcp", drift_state="DRIFT")]) is False


def test_drift_resolved_false_on_fetch_error():
    # The network-blip regression: an unreachable GitHub API records
    # "error: ..." rather than "DRIFT", so a `not has_drift` shortcut would
    # read the run as resolved and close a live alert.
    errored = _row("memory-mcp", drift_state="error: HTTPError 503")
    assert drift.drift_resolved([_row(), errored]) is False


def test_drift_resolved_false_without_any_tracked_source():
    assert drift.drift_resolved([]) is False
    assert drift.drift_resolved([_row(drift_state="skipped")]) is False


def test_drift_resolved_false_on_consistency_mismatch():
    assert drift.drift_resolved([_row(consistency="MISMATCH")]) is False


# ── issue selection ──────────────────────────────────────────────────────────

def _auto_issue(number=836, title=None, body=None, login="github-actions[bot]"):
    body = (
        f"{reconcile_mod.AUTO_MARKER}\nA vendored source is behind upstream.\n\n"
        f"{reconcile_mod.AUTO_FOOTER}\n"
    ) if body is None else body
    return {
        "number": number,
        "title": reconcile_mod.ALERT_TITLE if title is None else title,
        "body": body,
        "user": {"login": login},
    }


def test_workflow_strings_match_the_scripts_constants():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert reconcile_mod.ALERT_TITLE in text
    assert reconcile_mod.AUTO_MARKER in text
    assert reconcile_mod.AUTO_FOOTER in text


def test_is_auto_managed_refuses_anything_not_written_by_this_workflow():
    assert reconcile_mod.is_auto_managed(_auto_issue()) is True
    assert reconcile_mod.is_auto_managed(_auto_issue(body=None, login="andrei649")) is False
    assert reconcile_mod.is_auto_managed(_auto_issue(body="no marker here")) is False
    assert reconcile_mod.is_auto_managed({**_auto_issue(), "body": None}) is False
    assert reconcile_mod.is_auto_managed(
        _auto_issue(title=reconcile_mod.ALERT_TITLE + " (manual)")
    ) is False
    assert reconcile_mod.is_auto_managed(
        {**_auto_issue(), "pull_request": {"url": "..."}}
    ) is False
    # Marker present but the workflow footer stripped by a human edit.
    assert reconcile_mod.is_auto_managed(
        _auto_issue(body=f"{reconcile_mod.AUTO_MARKER}\nhand-edited")
    ) is False


def test_select_closable_is_empty_while_drift_is_unresolved():
    assert reconcile_mod.select_closable([_auto_issue()], resolved=False) == []
    assert reconcile_mod.select_closable([_auto_issue()], resolved=True) == [_auto_issue()]


# ── reconcile ────────────────────────────────────────────────────────────────

class _FakeClient:
    def __init__(self):
        self.calls = []

    def comment(self, number, body):
        self.calls.append(("comment", number, body))

    def close(self, number):
        self.calls.append(("close", number))


def test_reconcile_comments_before_closing_and_is_idempotent():
    client = _FakeClient()
    closed = reconcile_mod.reconcile(
        [_row()], [_auto_issue()], client.comment, client.close, table="table body"
    )
    assert closed == [836]
    assert [c[0] for c in client.calls] == ["comment", "close"]
    assert client.calls[0][1] == 836 and "table body" in client.calls[0][2]

    # Re-run once the issue is closed: it is no longer in the open list.
    again = _FakeClient()
    assert reconcile_mod.reconcile([_row()], [], again.comment, again.close) == []
    assert again.calls == []


def test_reconcile_closes_only_the_auto_managed_issue():
    client = _FakeClient()
    human = _auto_issue(number=900, login="andrei649", body="Third-party drift, filed by hand")
    closed = reconcile_mod.reconcile(
        [_row()], [human, _auto_issue()], client.comment, client.close
    )
    assert closed == [836]
    assert all(call[1] == 836 for call in client.calls)


def test_reconcile_touches_nothing_when_drift_is_unresolved():
    client = _FakeClient()
    closed = reconcile_mod.reconcile(
        [_row(drift_state="DRIFT")], [_auto_issue()], client.comment, client.close
    )
    assert closed == []
    assert client.calls == []


# ── workflow wiring ──────────────────────────────────────────────────────────

def test_workflow_runs_the_closer_behind_the_owner_gate():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/reconcile_drift_alert.py" in text
    step = text.split("Reconcile resolved drift alert", 1)[1].split("- name:", 1)[0]
    assert "vars.THIRDPARTY_DRIFT_AUTOCLOSE == 'true'" in step
    assert "steps.drift.outcome == 'success'" in step
    assert "github.event_name != 'pull_request'" in step
