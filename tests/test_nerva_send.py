"""Hermes send parity uses the live inbox and its governed reply queue."""
import json

import pytest

from agents.cli.client import HubError
from agents.cli.nerva import EXIT_AUTH, EXIT_FAILED, EXIT_OK, EXIT_USAGE
from tests.test_nerva_cli import _FakeHub, _run

TARGET = "telegram:0123456789ab"
THREAD = {"thread_id": TARGET, "channel": "telegram", "from": "owner",
          "reply": {"chat_id": "42"}}
REPLY_PATH = f"/api/channels/inbox/{TARGET}/reply"


def test_list_shows_stored_destinations_without_sending():
    hub = _FakeHub({
        "GET /api/channels/inbox/status": {"enabled": True},
        "GET /api/channels/inbox?limit=200": {"threads": [THREAD]},
    })
    code, out, _, hub = _run(["send", "--list"], hub)
    assert code == EXIT_OK and TARGET in out and "owner" in out
    assert all(method == "GET" for method, _, _ in hub.calls)


def test_list_distinguishes_unavailable_from_empty():
    hub = _FakeHub({"GET /api/channels/inbox/status": {"enabled": False}})
    code, out, err, hub = _run(["send", "--list"], hub)
    assert code == EXIT_FAILED and "unavailable" in out + err
    # `--list` used to make exactly one call. Since H018/H480 it has two things to list —
    # configured destinations and inbox threads — so the pin that matters is the one the
    # original assertion was protecting: listing never mutates anything.
    assert all(method == "GET" for method, _, _ in hub.calls)
    assert [path for _m, path, _b in hub.calls] == [
        "/api/channels/targets", "/api/channels/inbox/status"]


def test_send_queues_exact_text_and_does_not_approve_or_claim_delivery():
    message = "Backup terminat. Și pozele sunt salvate 📷."
    hub = _FakeHub({f"GET /api/channels/inbox/{TARGET}": {"thread": THREAD},
                    f"POST {REPLY_PATH}": {"ok": True, "queued": True, "task_id": 71}})
    code, out, _, hub = _run(["send", "--to", TARGET, message], hub)
    assert code == EXIT_OK and "queued" in out and "71" in out
    assert "delivered" not in out.lower() and "sent" not in out.lower()
    assert hub.calls[-1] == ("POST", REPLY_PATH, {"text": message, "source": "nerva.cli.send"})
    assert len(hub.calls) == 2


@pytest.mark.parametrize("answer", [
    {"ok": False, "reason": "blocked"},
    {"ok": True, "queued": False, "payload": {"text": "draft"}},
    {"ok": True, "queued": True},
    {"ok": True, "queued": "true", "task_id": 1},
    {"ok": True, "queued": True, "task_id": True},
    {}, [], None,
])
def test_send_never_reports_success_for_a_refusal_preview_or_malformed_reply(answer):
    hub = _FakeHub({f"GET /api/channels/inbox/{TARGET}": {"thread": THREAD},
                    f"POST {REPLY_PATH}": answer})
    code, out, _, _ = _run(["send", "--to", TARGET, "hello", "--json"], hub)
    assert code == EXIT_FAILED
    assert json.loads(out) == answer


@pytest.mark.parametrize("args", [
    ["--to", "../../autonomy/approvals", "hello"],
    ["--to", "telegram:a%2fb", "hello"],
    ["--to", TARGET], ["--to", TARGET, "  "],
    ["--to", TARGET, "x" * 4001], ["--list", "hello"],
    ["--list", "--to", TARGET], [],
])
def test_invalid_request_is_rejected_before_any_hub_call(args):
    code, _, _, hub = _run(["send", *args])
    assert code == EXIT_USAGE and hub.calls == []


def test_unknown_target_never_creates_an_outbound_request():
    hub = _FakeHub(raise_with=HubError(404, "thread not found"))
    code, _, _, hub = _run(["send", "--to", TARGET, "hello"] , hub)
    assert code == EXIT_FAILED
    assert all(method == "GET" for method, _, _ in hub.calls)


@pytest.mark.parametrize("thread", [None, {}, {**THREAD, "thread_id": "other"}, {**THREAD, "reply": {}}])
def test_unresolved_recipient_never_reaches_reply_route(thread):
    hub = _FakeHub({f"GET /api/channels/inbox/{TARGET}": {"thread": thread}})
    code, _, _, hub = _run(["send", "--to", TARGET, "hello"], hub)
    assert code == EXIT_FAILED and len(hub.calls) == 1


def test_send_uses_the_hubs_existing_auth_failure_exit():
    hub = _FakeHub(raise_with=HubError(401, "user token required"))
    code, _, err, _ = _run(["send", "--to", TARGET, "hello"], hub)
    assert code == EXIT_AUTH and "JARVIS_USER_TOKEN" in err
