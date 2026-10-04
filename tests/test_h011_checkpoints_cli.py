"""Owner checkpoint CLI is an authenticated /chat wrapper, not a local store writer."""

from __future__ import annotations

import io
import shlex

import pytest

from agents.cli.client import HubError, HubUnavailable
from agents.cli.nerva import (
    EXIT_AUTH,
    EXIT_FAILED,
    EXIT_NO_HUB,
    EXIT_OK,
    EXIT_USAGE,
    Context,
    main,
)


class FakeHub:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.base_url = "http://127.0.0.1:8080"

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def get(self, path):
        raise AssertionError(f"unexpected checkpoint GET: {path}")


def run(args, answer):
    hub = FakeHub(answer)
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, client_factory=lambda _: hub)
    code = main(["checkpoints", *args], context=ctx)
    return code, out.getvalue(), err.getvalue(), hub.calls


def notice(code, text="checkpoint result"):
    return {"notices": [{"code": code, "text": text}], "reply": "untrusted prose"}


@pytest.mark.parametrize("args,expected", [
    ([], "/checkpoints status"),
    (["status", "--limit", "7"], "/checkpoints status --limit 7"),
    (["list", "--project", "/tmp/a b's", "--limit", "2"],
     "/checkpoints list --project '/tmp/a b'\"'\"'s' --limit 2"),
    (["prune"], "/checkpoints prune --dry-run"),
    (["prune", "--project", "/tmp/project", "--execute", "--force"],
     "/checkpoints prune --project /tmp/project --execute --force"),
    (["clear"], "/checkpoints clear --dry-run"),
    (["clear-legacy", "--execute"], "/checkpoints clear-legacy --execute"),
])
def test_exact_canonical_chat_request_and_authoritative_complete(args, expected):
    code, out, err, calls = run(args, notice("checkpoint.complete", "done"))
    assert code == EXIT_OK and out == "done\n" and err == ""
    assert calls == [("POST", "/chat", {"message": expected})]
    assert shlex.split(calls[0][2]["message"]) == shlex.split(expected)


def test_preview_is_success_but_does_not_claim_actuation():
    code, out, err, calls = run(["clear"], notice("checkpoint.preview", "would remove 2"))
    assert code == EXIT_OK and out == "would remove 2\n" and err == ""
    assert calls == [("POST", "/chat", {"message": "/checkpoints clear --dry-run"})]


def test_wrapper_never_opens_a_local_checkpoint_store(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    code, out, err, calls = run(["status"], notice("checkpoint.complete", "healthy"))
    assert code == EXIT_OK and out == "healthy\n" and err == ""
    assert calls == [("POST", "/chat", {"message": "/checkpoints status"})]
    assert not (tmp_path / "data").exists()


def test_other_turn_notices_do_not_hide_the_single_checkpoint_status():
    answer = notice("checkpoint.complete", "healthy")
    answer["notices"].insert(0, {"code": "compaction_deferred", "text": "later"})
    code, out, err, _ = run(["status"], answer)
    assert code == EXIT_OK and out == "healthy\n" and err == ""


def test_pending_approval_precedes_misleading_complete_notice():
    answer = notice("checkpoint.complete", "done")
    answer["pending_approvals"] = [17, 23]
    code, out, err, _ = run(["prune", "--execute"], answer)
    assert code == EXIT_FAILED and out == ""
    assert "#17" in err and "#23" in err and "approval" in err.lower()


@pytest.mark.parametrize("pending", ["17", [17, "18"], [True], [-1], [17, 17]])
def test_unreadable_or_ambiguous_pending_ids_fail_without_invented_id(pending):
    answer = notice("checkpoint.complete", "done")
    answer["pending_approvals"] = pending
    code, out, err, _ = run(["clear", "--execute"], answer)
    assert code == EXIT_FAILED and out == "" and err
    assert "#18" not in err and "#-1" not in err and "#True" not in err


@pytest.mark.parametrize("answer", [
    None, {}, {"reply": "done"},
    {"notices": "checkpoint.complete", "reply": "done"},
    {"notices": [{"code": "checkpoint.complete", "text": "done"},
                 {"code": "checkpoint.refused", "text": "refused"}]},
    {"notices": [{"code": "checkpoint.complete", "text": "done"},
                 {"code": "checkpoint.complete", "text": "duplicate"}]},
    {"notices": [{"code": "checkpoint.complete"}]},
    {"notices": [{"code": "checkpoint.complete", "text": ""}]},
    {"notices": [{"code": "checkpoint.unknown", "text": "done"}]},
])
def test_missing_malformed_or_multiple_checkpoint_notices_never_succeed(answer):
    code, out, err, calls = run(["status"], answer)
    assert code == EXIT_FAILED and out == "" and err
    assert calls == [("POST", "/chat", {"message": "/checkpoints status"})]


@pytest.mark.parametrize("status", ["checkpoint.queued", "checkpoint.refused",
                                    "checkpoint.unavailable", "checkpoint.partial"])
def test_non_success_notice_is_nonzero_and_never_prints_prose_as_success(status):
    code, out, err, _ = run(["prune", "--execute"], notice(status, "not completed"))
    assert code == EXIT_FAILED and out == "" and "not completed" in err


@pytest.mark.parametrize("args", [
    ["status", "--project", ""],
    ["list", "--project", "x\n/rollback"],
    ["list", "--project", "x\x1by"],
    ["list", "--project", "x\x7fy"],
    ["list", "--project", "x" * 4097],
    ["list", "--limit", "0"],
    ["list", "--limit", "501"],
    ["clear", "--project", "/tmp/x"],
    ["clear-legacy", "--limit", "2"],
    ["status", "--execute"],
    ["prune", "--force"],
    ["clear", "--all"],
])
def test_bad_options_are_usage_without_network_or_store(args, capsys):
    code, out, err, calls = run(args, notice("checkpoint.complete"))
    assert code == EXIT_USAGE and out == "" and (err or capsys.readouterr().err)
    assert calls == []


def test_quoted_project_cannot_introduce_another_option():
    project = "/tmp/a --execute /rollback"
    code, out, err, calls = run(["list", "--project", project], notice("checkpoint.complete"))
    assert code == EXIT_OK and err == ""
    assert shlex.split(calls[0][2]["message"]) == [
        "/checkpoints", "list", "--project", project,
    ]


@pytest.mark.parametrize("failure,expected", [
    (HubError(401, "admin token required"), EXIT_AUTH),
    (HubError(403, "forbidden"), EXIT_AUTH),
    (HubUnavailable("http://127.0.0.1:8080", "offline"), EXIT_NO_HUB),
])
def test_existing_hub_auth_and_unavailable_exit_codes(failure, expected):
    code, out, err, calls = run(["status"], failure)
    assert code == expected and out == "" and err
    assert calls == [("POST", "/chat", {"message": "/checkpoints status"})]
