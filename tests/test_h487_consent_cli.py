"""Native owner choices use the authenticated H487 consent route."""

from __future__ import annotations

import io
import json

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

REVISION = "a" * 64


class FakeHub:
    def __init__(self, response=None):
        self.response = response
        self.calls = []
        self.base_url = "http://127.0.0.1:8080"

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def get(self, path):
        self.calls.append(("GET", path, None))
        return self.response


def run(args, response=None):
    hub = FakeHub(response)
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, client_factory=lambda _: hub)
    code = main(args, context=ctx)
    return code, out.getvalue(), err.getvalue(), hub.calls


@pytest.mark.parametrize("choice,status", [
    ("session", "accepted"), ("always", "accepted"), ("deny", "rejected"),
])
def test_consent_posts_only_exact_reviewed_choice_and_revision(choice, status):
    response = {"ok": True, "tasks": [{"id": 7, "status": status}, {"id": 8, "status": status}]}
    code, out, err, calls = run(
        ["approvals", "consent", "7", "--choice", choice, "--revision", REVISION,
         "--reason", "  reviewed  "], response,
    )
    assert code == EXIT_OK and err == ""
    assert calls == [("POST", "/autonomy/tasks/7/consent", {
        "choice": choice, "revision": REVISION, "reason": "reviewed",
    })]
    assert "#7" in out and choice in out and "2" in out


def test_consent_json_returns_verified_server_result():
    response = {"ok": True, "tasks": [{"id": 7, "status": "accepted"}]}
    code, out, err, _ = run(
        ["approvals", "consent", "7", "--choice", "always", "--revision", REVISION, "--json"],
        response,
    )
    assert code == EXIT_OK and err == "" and json.loads(out) == response


@pytest.mark.parametrize("args", [
    ["7", "--choice", "always"],
    ["7", "--revision", REVISION],
    ["0", "--choice", "always", "--revision", REVISION],
    ["-1", "--choice", "always", "--revision", REVISION],
    ["7", "--choice", "always", "--revision", "A" * 64],
    ["7", "--choice", "always", "--revision", "a" * 63],
    ["7", "--choice", "other", "--revision", REVISION],
    ["7", "--choice", "always", "--revision", REVISION, "--reason", "x" * 281],
    ["7", "--choice", "always", "--revision", REVISION, "--payload", "{}"],
])
def test_invalid_consent_input_is_usage_error_without_post(args, capsys):
    code, out, err, calls = run(["approvals", "consent", *args])
    assert code == EXIT_USAGE and out == "" and (err or capsys.readouterr().err)
    assert calls == []


@pytest.mark.parametrize("response", [
    None, {}, {"ok": "true", "tasks": [{"id": 7}]},
    {"ok": True, "tasks": []}, {"ok": True, "tasks": [None]},
    {"ok": True, "tasks": [{}]}, {"ok": False, "tasks": [{"id": 7}]},
])
def test_consent_refuses_malformed_or_unsuccessful_response(response):
    code, out, err, calls = run(
        ["approvals", "consent", "7", "--choice", "deny", "--revision", REVISION, "--json"],
        response,
    )
    assert code == EXIT_FAILED and out == "" and err
    assert calls == [("POST", "/autonomy/tasks/7/consent", {
        "choice": "deny", "revision": REVISION,
    })]


@pytest.mark.parametrize("response,expected", [
    (HubError(401, "admin token required"), EXIT_AUTH),
    (HubError(409, "consent offer changed"), EXIT_FAILED),
    (HubUnavailable("http://127.0.0.1:8080", "connection refused"), EXIT_NO_HUB),
])
def test_consent_keeps_existing_hub_failure_exit_codes(response, expected):
    code, out, err, calls = run(
        ["approvals", "consent", "7", "--choice", "session", "--revision", REVISION], response,
    )
    assert code == expected and out == "" and err
    assert len(calls) == 1


def test_list_displays_valid_offer_without_losing_ordinary_approval_guidance():
    offer = {"revision": REVISION, "count": 2, "choices": ["session", "always", "deny"],
             "categories": [{"description": "Can remove files", "permanent": True},
                            {"description": "Requires a local session", "permanent": False}]}
    response = {"pending": [
        {"id": 7, "kind": "toolrpc.terminal_run", "title": "reviewed command",
         "risk_tier": 3, "reversible": False, "consent_offer": offer},
        {"id": 8, "kind": "payment.send", "title": "pay", "risk_tier": 3,
         "reversible": False},
    ], "reversible": [], "irreversible": []}
    code, out, err, calls = run(["approvals", "list"], response)
    assert code == EXIT_OK and err == ""
    assert calls == [("GET", "/autonomy/approvals", None)]
    assert "#7" in out and "#8" in out and "accept|reject|defer" in out
    assert "2 matching requests" in out and "Can remove files" in out
    assert "Requires a local session" in out and "session only" in out
    assert f"nerva approvals consent 7 --choice session --revision {REVISION}" in out
    assert "session|always|deny" in out


@pytest.mark.parametrize("offer", [
    {"revision": "stale", "count": 1, "choices": ["session", "always", "deny"],
     "categories": [{"description": "danger", "permanent": True}]},
    {"revision": REVISION, "count": 0, "choices": ["session", "always", "deny"],
     "categories": [{"description": "danger", "permanent": True}]},
    {"revision": REVISION, "count": 1, "choices": ["always"],
     "categories": [{"description": "danger", "permanent": True}]},
    {"revision": REVISION, "count": 1, "choices": ["session", "always", "deny"],
     "categories": [{"description": "", "permanent": True}]},
])
def test_list_does_not_advertise_malformed_offer_as_reusable(offer):
    response = {"pending": [{"id": 7, "kind": "toolrpc.terminal_run", "title": "reviewed command",
                             "risk_tier": 3, "reversible": False, "consent_offer": offer}]}
    code, out, err, calls = run(["approvals", "list"], response)
    assert code == EXIT_OK and err == "" and len(calls) == 1
    assert "#7" in out and "accept|reject|defer" in out
    assert "nerva approvals consent" not in out


def test_list_json_preserves_bounded_offer_projection():
    response = {"pending": [{"id": 7, "consent_offer": {
        "revision": REVISION, "count": 1, "choices": ["session", "always", "deny"],
        "categories": [{"description": "Can remove files", "permanent": True}],
    }}]}
    code, out, err, calls = run(["approvals", "list", "--json"], response)
    assert code == EXIT_OK and err == "" and json.loads(out) == response
    assert calls == [("GET", "/autonomy/approvals", None)]
