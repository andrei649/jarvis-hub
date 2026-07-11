"""0.66 SaaS Connector Breadth — white-collar suite request builders.

Pure builders (Linear/Asana/Trello/Todoist/ClickUp/Sheets/M365): validated catalog, host
allowlist, secrets only at execute-time ({{secret:...}} handles in drafts), no network.
"""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core import writeback_connectors as wc  # noqa: E402


def test_catalog_covers_the_white_collar_suite():
    targets = {c["target"] for c in wc.catalog()}
    assert {"linear", "asana", "trello", "todoist", "clickup", "gsheets", "m365"} <= targets


def test_draft_carries_secret_handle_never_a_token():
    d = wc.draft_task_payload("linear", "create_issue",
                              {"team_id": "T1", "title": "Fix bug"})
    assert d["ok"] is True and d["kind"] == "connector.linear.create_issue"
    assert d["credential_ref"] == "{{secret:linear_token}}"     # handle, not a credential


def test_unknown_action_and_missing_fields_are_refused_with_reason():
    bad = wc.draft_task_payload("linear", "delete_everything", {})
    assert bad["ok"] is False and "unknown connector action" in bad["reason"]
    missing = wc.draft_task_payload("asana", "create_task", {"project_id": "P"})
    assert missing["ok"] is False and "name" in missing["reason"]


@pytest.mark.parametrize("target,action,fields,host", [
    ("linear", "create_issue", {"team_id": "T", "title": "t"}, "api.linear.app"),
    ("asana", "create_task", {"project_id": "P", "name": "n"}, "app.asana.com"),
    ("trello", "create_card", {"list_id": "L", "name": "n"}, "api.trello.com"),
    ("todoist", "create_task", {"content": "c"}, "api.todoist.com"),
    ("clickup", "create_task", {"list_id": "L", "name": "n"}, "api.clickup.com"),
    ("gsheets", "append_row", {"spreadsheet_id": "S", "range": "A1", "values": ["x"]},
     "sheets.googleapis.com"),
    ("m365", "create_draft", {"subject": "s", "body": "b", "to": "a@b.c"},
     "graph.microsoft.com"),
])
def test_every_builder_targets_its_allowlisted_host(target, action, fields, host):
    req = wc.build_connector_request(target, action, fields, {"token": "tok", "api_key": "k"})
    assert host in req["url"]
    assert req["method"] == "POST"
    assert "json" in req


def test_linear_builds_graphql_mutation_with_variables():
    req = wc.build_connector_request("linear", "create_issue",
                                     {"team_id": "T9", "title": "Ship it",
                                      "description": "detail"}, {"token": "lin_x"})
    assert "issueCreate" in req["json"]["query"]
    assert req["json"]["variables"]["input"] == {"teamId": "T9", "title": "Ship it",
                                                 "description": "detail"}
    assert req["headers"]["Authorization"] == "lin_x"


def test_trello_auth_uses_structured_params_not_a_loggable_url():
    req = wc.build_connector_request("trello", "create_card",
                                     {"list_id": "L1", "name": "card"},
                                     {"token": "tt", "api_key": "kk"})
    assert req["url"] == "https://api.trello.com/1/cards"
    assert req["params"] == {"idList": "L1", "key": "kk", "token": "tt"}
    assert "tt" not in req["url"] and "kk" not in req["url"]


def test_sheets_appends_a_single_sanitized_row():
    req = wc.build_connector_request("gsheets", "append_row",
                                     {"spreadsheet_id": "S1", "range": "Sheet1!A1",
                                      "values": ["a", 2, None]}, {"token": "g"})
    assert req["json"] == {"values": [["a", "2", ""]]}
    assert ":append?valueInputOption=RAW" in req["url"]


def test_m365_draft_builds_recipients_from_str_or_list():
    one = wc.build_connector_request("m365", "create_draft",
                                     {"subject": "s", "body": "b", "to": "x@y.z"},
                                     {"token": "m"})
    assert one["json"]["toRecipients"] == [{"emailAddress": {"address": "x@y.z"}}]
    many = wc.build_connector_request("m365", "create_draft",
                                      {"subject": "s", "body": "b",
                                       "to": ["a@b.c", "d@e.f"]}, {"token": "m"})
    assert len(many["json"]["toRecipients"]) == 2


def test_builder_refuses_invalid_draft():
    with pytest.raises(ValueError):
        wc.build_connector_request("linear", "create_issue", {"title": "no team"}, {})

def test_raw_secret_override_is_refused():
    d = wc.draft_task_payload(
        "linear",
        "create_issue",
        {"team_id": "T1", "title": "Fix bug"},
        secret_handle="sk-live-raw",
    )
    assert d == {"ok": False, "reason": "invalid credential reference"}


def test_draft_descriptor_is_explicitly_ask_tier_but_not_enqueued():
    d = wc.draft_task_payload(
        "linear", "create_issue", {"team_id": "T1", "title": "Fix bug"}
    )
    assert d["risk_tier"] == 2
    assert d["autonomy_level"] == "ask"
    assert d["requires_approval"] is True
    assert d["queued"] is False


def test_required_text_fields_reject_false_and_zero():
    false_title = wc.validate_draft(
        "linear", "create_issue", {"team_id": "T", "title": False}
    )
    zero_title = wc.validate_draft(
        "linear", "create_issue", {"team_id": "T", "title": 0}
    )
    empty_values = wc.validate_draft(
        "gsheets",
        "append_row",
        {"spreadsheet_id": "S", "range": "A1", "values": []},
    )
    assert false_title["ok"] is False
    assert zero_title["ok"] is False
    assert empty_values["ok"] is False


def test_draft_fields_are_bounded_before_entering_approval_queue():
    d = wc.draft_task_payload(
        "linear",
        "create_issue",
        {"team_id": "T", "title": "x" * 5000, "description": "d" * 50000},
    )
    assert len(d["fields"]["title"]) == wc._STR_CAP
    assert len(d["fields"]["description"]) == wc._LONG_CAP

