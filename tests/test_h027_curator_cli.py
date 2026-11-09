"""H027 owner CLI exposes all curator operations through the governed hub API."""

from __future__ import annotations

import io
import json

import pytest

from agents.cli.nerva import EXIT_FAILED, EXIT_OK, Context, command_tree, main

FINGERPRINT = "a" * 64
VERBS = {
    "status", "usage", "run", "pause", "resume", "pin", "unpin",
    "list-unmanaged", "adopt", "restore", "list-archived", "archive",
    "prune", "backup", "rollback", "ledger", "purge",
}


class FakeHub:
    def __init__(self):
        self.calls = []
        self.preview_fingerprint = FINGERPRINT

    def get(self, path):
        self.calls.append(("GET", path, None))
        return {"ok": True, "path": path, "skills": []}

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        if path == "/api/curator/preview":
            return {"ok": True, "status": "preview", "operation": body["operation"],
                    "targets": [{"id": "reviewed-skill"}],
                    "preview_fingerprint": self.preview_fingerprint}
        if path == "/api/curator/request":
            return {"ok": True, "status": "pending", "card_id": 7,
                    "targets": [{"id": "reviewed-skill"}],
                    "preview_fingerprint": body["preview_fingerprint"]}
        raise AssertionError(path)


def run_cli(args, hub=None):
    hub = hub or FakeHub()
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, client_factory=lambda _env: hub)
    code = main(["curator", *args], context=ctx)
    return code, out.getvalue(), err.getvalue(), hub


def test_curator_command_tree_has_every_frozen_verb():
    assert set(command_tree()["curator"]) == VERBS


@pytest.mark.parametrize("args,path", [
    (["status"], "/api/curator/status"),
    (["usage", "--origin", "agent", "--sort", "recent", "--limit", "5"],
     "/api/curator/usage?origin=agent&sort=recent&limit=5"),
    (["list-unmanaged"], "/api/curator/list-unmanaged"),
    (["list-archived"], "/api/curator/list-archived"),
    (["ledger", "--name", "notes", "--limit", "5"],
     "/api/curator/ledger?name=notes&limit=5"),
    (["rollback", "--list"], "/api/curator/backups"),
])
def test_read_verbs_use_owner_hub_projection_without_mutation(args, path):
    code, out, err, hub = run_cli([*args, "--json"])
    assert code == EXIT_OK and err == ""
    assert json.loads(out)["path"] == path
    assert hub.calls == [("GET", path, None)]


@pytest.mark.parametrize("args,operation,expected", [
    (["run"], "run", {}),
    (["run", "--consolidate"], "run", {"consolidate": True}),
    (["pause"], "pause", {}),
    (["resume"], "resume", {}),
    (["pin", "notes"], "pin", {"name": "notes"}),
    (["unpin", "notes"], "unpin", {"name": "notes"}),
    (["adopt", "--all-unmanaged"], "adopt", {"all_unmanaged": True}),
    (["restore", "archive-123"], "restore", {"archive_id": "archive-123"}),
    (["archive", "notes"], "archive", {"name": "notes"}),
    (["prune", "--days", "31"], "prune", {"days": 31}),
    (["backup", "--reason", "owner review"], "backup", {"reason": "owner review"}),
    (["rollback", "--ledger-id", "ledger-123"], "rollback", {"ledger_id": "ledger-123"}),
    (["rollback"], "rollback", {}),  # the core resolves the newest verified backup
    (["purge", "--days", "120", "--yes"], "purge", {"days": 120}),
])
def test_mutation_verb_previews_then_queues_exact_snapshot(args, operation, expected):
    code, out, err, hub = run_cli([*args, "--json"])
    assert code == EXIT_OK and err == ""
    assert json.loads(out)["status"] == "pending"
    assert hub.calls == [
        ("POST", "/api/curator/preview", {"operation": operation, "args": expected}),
        ("POST", "/api/curator/request", {"operation": operation, "args": expected,
                                           "preview_fingerprint": FINGERPRINT}),
    ]


def test_dry_run_only_previews_and_never_creates_approval_card():
    code, out, err, hub = run_cli(["prune", "--days", "31", "--dry-run", "--json"])
    assert code == EXIT_OK and err == ""
    assert json.loads(out)["status"] == "preview"
    assert hub.calls == [("POST", "/api/curator/preview",
                          {"operation": "prune", "args": {"days": 31}})]


def test_stale_explicit_fingerprint_refuses_before_queue():
    code, _out, err, hub = run_cli(["pin", "notes", "--preview-fingerprint", "b" * 64])
    assert code == EXIT_FAILED and "preview" in err
    assert len(hub.calls) == 1 and hub.calls[0][1] == "/api/curator/preview"


def test_refused_preview_never_reaches_request():
    class RefusingHub(FakeHub):
        def post(self, path, body):
            if path == "/api/curator/preview":
                self.calls.append(("POST", path, body))
                return {"ok": False, "status": "refused", "reason": "protected_origin"}
            return super().post(path, body)

    code, _out, err, hub = run_cli(["archive", "bundled"], RefusingHub())
    assert code == EXIT_FAILED and "protected_origin" in err
    assert len(hub.calls) == 1
