"""H051 — `nerva pairing list|approve|revoke|clear-pending`.

Who may talk to the agent over a DM channel was decided only from the HUD card. These
verbs ride the same admin routes (agents/core/routers/pairing.py). The round-trip tests
below drive the real route handlers against a real ``SenderPairing`` store, so the CLI
is proven against what the hub actually answers, not against a hand-written stub.
"""

from __future__ import annotations

import asyncio
import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from agents.cli.client import HubError
from agents.cli.nerva import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    Context,
    build_parser,
    command_tree,
    completion_script,
    main,
)


class _RouteHub:
    """A HubClient stand-in that dispatches to the real pairing route handlers."""

    def __init__(self, store, monkeypatch):
        from agents.core.routers import pairing as routes

        monkeypatch.setattr(routes, "_get_sender_pairing", lambda: store)
        self.routes = routes
        self.calls = []
        self.base_url = "http://127.0.0.1:8080"

    @staticmethod
    def _answer(response):
        payload = json.loads(response.body)
        if response.status_code >= 400:
            raise HubError(response.status_code, str(payload.get("error")))
        return payload

    def get(self, path):
        self.calls.append(("GET", path, None))
        url = urlsplit(path)
        assert url.path == "/api/channels/pairing", path
        status = parse_qs(url.query).get("status", [None])[0]
        return self._answer(asyncio.run(self.routes.pairing_list(status=status)))

    def post(self, path, body=None):
        body = body if body is not None else {}
        self.calls.append(("POST", path, body))
        if path == "/api/channels/pairing/decide":
            reply = self.routes.pairing_decide(self.routes.PairingDecisionBody(**body))
        elif path == "/api/channels/pairing/clear-pending":
            reply = self.routes.pairing_clear_pending()
        else:  # pragma: no cover - a wrong path is the failure being tested for
            raise HubError(404, f"no route {path}")
        return self._answer(asyncio.run(reply))


class _Refuse:
    """A hub that refuses every write, as the route's body validation would."""

    base_url = "http://127.0.0.1:8080"

    def post(self, path, body=None):
        raise HubError(422, "sender_id too long")

    def get(self, path):  # pragma: no cover - never reached
        raise HubError(422, "unused")


@pytest.fixture
def store(tmp_path, monkeypatch):
    from agents.core.channels.pairing import SenderPairing

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    return SenderPairing(path=tmp_path / "sender_pairing.json")


def _run(argv, hub):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


def test_pairing_verbs_are_in_the_tree_and_the_completion():
    assert command_tree(build_parser())["pairing"] == ["approve", "clear-pending", "list", "revoke"]
    assert "pairing) COMPREPLY" in completion_script("bash")


def test_list_shows_every_sender_with_its_status_and_filters_by_status(store, monkeypatch):
    store.request("telegram", "111", name="maria")
    store.approve("slack", "U7", name="ion")
    store.block("sms", "+40", name="troll")
    hub = _RouteHub(store, monkeypatch)

    code, out, _err = _run(["pairing", "list"], hub)
    assert code == EXIT_OK
    assert "1 allowed · 1 pending · 1 blocked" in out
    lines = out.splitlines()
    assert any("telegram" in ln and "111" in ln and "pending" in ln and "maria" in ln for ln in lines)
    assert any("slack" in ln and "U7" in ln and "allowed" in ln for ln in lines)

    code, out, _err = _run(["pairing", "list", "--status", "allowed"], hub)
    assert code == EXIT_OK and "U7" in out and "111" not in out and "+40" not in out
    assert hub.calls[-1] == ("GET", "/api/channels/pairing?status=allowed", None)

    code, out, _err = _run(["pairing", "list", "--json"], hub)
    reply = json.loads(out)
    assert code == EXIT_OK and {s["sender_id"] for s in reply["senders"]} == {"111", "U7", "+40"}


def test_list_says_so_when_nobody_has_asked(store, monkeypatch):
    code, out, _err = _run(["pairing", "list"], _RouteHub(store, monkeypatch))
    assert code == EXIT_OK and "no senders" in out


def test_approve_lets_a_pending_sender_through(store, monkeypatch):
    monkeypatch.setattr("agents.core.channels.pairing.pairing_enabled", lambda: True)
    store.request("telegram", "111", name="maria")
    assert not store.is_allowed("telegram", "111")
    hub = _RouteHub(store, monkeypatch)

    code, out, _err = _run(["pairing", "approve", "telegram", "111"], hub)
    assert code == EXIT_OK and "approved telegram:111" in out
    assert hub.calls[-1] == ("POST", "/api/channels/pairing/decide",
                             {"channel": "telegram", "sender_id": "111", "action": "approve"})
    assert store.status("telegram", "111") == "allowed"
    assert store.is_allowed("telegram", "111")


def test_approve_can_name_the_sender(store, monkeypatch):
    hub = _RouteHub(store, monkeypatch)
    code, _out, _err = _run(["pairing", "approve", "slack", "U7", "--name", "ion"], hub)
    assert code == EXIT_OK and hub.calls[-1][2]["name"] == "ion"
    assert store.list_senders("allowed")[0]["name"] == "ion"


def test_revoke_takes_an_approved_sender_back_to_unknown(store, monkeypatch):
    monkeypatch.setattr("agents.core.channels.pairing.pairing_enabled", lambda: True)
    store.approve("telegram", "111")
    hub = _RouteHub(store, monkeypatch)

    code, out, _err = _run(["pairing", "revoke", "telegram", "111"], hub)
    assert code == EXIT_OK and "revoked telegram:111" in out
    assert hub.calls[-1][2] == {"channel": "telegram", "sender_id": "111", "action": "unpair"}
    assert store.status("telegram", "111") == "unknown"
    assert not store.is_allowed("telegram", "111")


def test_revoke_also_lifts_a_block(store, monkeypatch):
    store.block("sms", "+40")
    code, _out, _err = _run(["pairing", "revoke", "sms", "+40"], _RouteHub(store, monkeypatch))
    assert code == EXIT_OK and store.status("sms", "+40") == "unknown"


def test_revoking_a_sender_with_no_record_fails_and_says_so(store, monkeypatch):
    code, out, err = _run(["pairing", "revoke", "telegram", "nobody"], _RouteHub(store, monkeypatch))
    assert code == EXIT_FAILED and out == ""
    assert "no pairing record for telegram:nobody" in err


def test_clear_pending_without_confirm_only_previews(store, monkeypatch):
    store.request("telegram", "1")
    store.request("telegram", "2")
    store.approve("slack", "U7")
    hub = _RouteHub(store, monkeypatch)

    code, out, _err = _run(["pairing", "clear-pending"], hub)
    assert code == EXIT_OK
    assert "would drop 2 pending" in out and "--confirm" in out
    assert all(method == "GET" for method, _p, _b in hub.calls)
    assert len(store.list_senders("pending")) == 2


def test_clear_pending_with_confirm_drops_only_pending_and_reports_the_audit(store, monkeypatch):
    store.request("telegram", "1")
    store.request("telegram", "2")
    store.approve("slack", "U7")
    store.block("sms", "+40")
    hub = _RouteHub(store, monkeypatch)

    code, out, _err = _run(["pairing", "clear-pending", "--confirm"], hub)
    assert code == EXIT_OK
    assert hub.calls[-1] == ("POST", "/api/channels/pairing/clear-pending", {})
    # No orchestrator in the test, so no audit log: said, never implied.
    assert "cleared 2 pending · not audited" in out
    assert store.list_senders("pending") == []
    assert store.status("slack", "U7") == "allowed" and store.status("sms", "+40") == "blocked"


def test_a_bad_status_filter_is_a_usage_error(store, monkeypatch):
    hub = _RouteHub(store, monkeypatch)
    code, _out, _err = _run(["pairing", "list", "--status", "paired"], hub)
    assert code == EXIT_USAGE and hub.calls == []


def test_a_refused_decision_exits_1_with_the_hubs_reason():
    code, _out, err = _run(["pairing", "approve", "telegram", "x" * 200], _Refuse())
    assert code == EXIT_FAILED and "sender_id too long" in err
