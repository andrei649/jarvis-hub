"""Body reading, validators, JSON responses and the error handlers (spec §5 http.py, errors.py)."""

from __future__ import annotations

import json
from typing import Annotated

import pytest
from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.testclient import TestClient

from agents.core.workspace import http
from agents.core.workspace.errors import WorkspaceError, error_response, register_handlers
from tests.support.workspace_fixtures import make_app

probe = APIRouter(prefix="/api/workspace")


@probe.post("/echo")
async def echo(request: Request):
    return http.ws_json(await http.read_json(request, max_bytes=64))


@probe.post("/echo-optional")
async def echo_optional(request: Request):
    return http.ws_json(await http.read_json(request, max_bytes=64, allow_empty=True))


@probe.post("/echo-large")
async def echo_large(request: Request):
    data = await http.read_json(request)
    return http.ws_json({"keys": sorted(data)})


@probe.get("/limited")
def limited(limit: Annotated[int, Query(ge=1, le=5)] = 1):
    return http.ws_json({"limit": limit})


@probe.get("/fail")
def fail():
    raise WorkspaceError("rate_limited", "slow down", 429, retry_after_seconds=7)


@probe.get("/cookie")
def cookie():
    holder = Response()
    holder.set_cookie("probe", "1", httponly=True)
    return http.ws_json({"ok": True}, 201, {"X-Extra": "y"}, cookies_from=holder)


@probe.delete("/nothing")
def nothing():
    return http.ws_no_content()


def _client() -> TestClient:
    app = make_app(probe)

    @app.get("/api/elsewhere")
    def elsewhere(limit: Annotated[int, Query(ge=1)] = 1):
        return {"limit": limit}

    return TestClient(app)


def test_read_json_happy_path():
    r = _client().post("/api/workspace/echo", json={"a": "ă"})
    assert r.status_code == 200 and r.json() == {"a": "ă"}
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("kwargs", "status", "code"), [
    ({"content": b'{"a":1}', "headers": {"Content-Type": "text/plain"}}, 415, "unsupported_media_type"),
    ({"content": b'{"a":1}'}, 415, "unsupported_media_type"),
    ({"content": b"{not json", "headers": {"Content-Type": "application/json"}}, 422, "invalid_request"),
    ({"content": b"[1, 2]", "headers": {"Content-Type": "application/json"}}, 422, "invalid_request"),
    ({"content": b"", "headers": {"Content-Type": "application/json"}}, 422, "invalid_request"),
    ({"content": b'"\xff\xfe"', "headers": {"Content-Type": "application/json"}}, 422, "invalid_request"),
    ({"content": b'{"a":"' + b"x" * 100 + b'"}', "headers": {"Content-Type": "application/json"}},
     413, "payload_too_large"),
])
def test_read_json_errors(kwargs, status, code):
    r = _client().post("/api/workspace/echo", **kwargs)
    assert r.status_code == status, r.text
    assert r.json()["error"] == code
    assert r.headers["cache-control"] == "no-store"


def test_read_json_caps_a_streamed_body_without_content_length():
    def chunks():
        yield b'{"a": "'
        yield b"x" * 200
        yield b'"}'

    r = _client().post("/api/workspace/echo", content=chunks(),
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"] == "payload_too_large"


def test_read_json_accepts_a_charset_parameter():
    r = _client().post("/api/workspace/echo", content=b'{"ok":true}',
                       headers={"Content-Type": "application/json; charset=utf-8"})
    assert r.json() == {"ok": True}


def test_allow_empty_reads_no_body_as_an_empty_object():
    client = _client()
    assert client.post("/api/workspace/echo-optional").json() == {}
    assert client.post("/api/workspace/echo-optional", json={"x": 1}).json() == {"x": 1}
    r = client.post("/api/workspace/echo-optional", content=b"x=1",
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415


def test_error_response_shape_and_retry_after():
    r = _client().get("/api/workspace/fail")
    assert r.status_code == 429
    assert r.json() == {"error": "rate_limited", "message": "slow down", "retry_after_seconds": 7}
    assert r.headers["retry-after"] == "7"
    assert r.headers["cache-control"] == "no-store"


def test_error_message_defaults_to_the_code():
    exc = WorkspaceError("not_found", status=404)
    assert exc.message == "not found"
    body = json.loads(error_response(exc).body)
    assert body == {"error": "not_found", "message": "not found"}


def test_ws_json_copies_cookies_and_headers():
    r = _client().get("/api/workspace/cookie")
    assert r.status_code == 201
    assert r.headers["x-extra"] == "y" and r.headers["cache-control"] == "no-store"
    assert "probe=1" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]


def test_ws_no_content():
    r = _client().delete("/api/workspace/nothing")
    assert r.status_code == 204 and r.content == b"" and r.headers["cache-control"] == "no-store"


def test_validation_errors_use_the_workspace_shape_only_under_the_prefix():
    client = _client()
    r = client.get("/api/workspace/limited?limit=9")
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request" and r.json()["field"] == "limit"
    other = client.get("/api/elsewhere?limit=0")
    assert other.status_code == 422 and "detail" in other.json(), "hub routes keep FastAPI's shape"


@pytest.mark.parametrize(("query", "reason"), [
    ("limit=9", "too_large"), ("limit=0", "too_small"), ("limit=abc", "type"),
])
def test_validation_errors_carry_a_reason(query, reason):
    r = _client().get(f"/api/workspace/limited?{query}")
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_request", "message": "invalid value for limit",
                        "field": "limit", "reason": reason}


def test_validation_shape_is_root_path_aware():
    client = TestClient(make_app(probe), root_path="/nerva")
    r = client.get("/nerva/api/workspace/limited?limit=0")
    assert r.status_code == 422 and r.json()["field"] == "limit"


def test_register_handlers_installs_both():
    app = FastAPI()
    register_handlers(app)
    assert WorkspaceError in app.exception_handlers


def _raises(fn, *args, **kwargs) -> WorkspaceError:
    with pytest.raises(WorkspaceError) as caught:
        fn(*args, **kwargs)
    assert caught.value.status == 422 and caught.value.code == "invalid_request"
    return caught.value


def test_require_str():
    assert http.require_str({"n": "  Ana  "}, "n", max_len=10) == "Ana"
    assert http.require_str({"p": "  pw  "}, "p", max_len=10, strip=False) == "  pw  "
    assert http.require_str({}, "n", max_len=5, required=False) == ""
    assert _raises(http.require_str, {}, "n", max_len=5).extra == {"field": "n", "reason": "required"}
    assert _raises(http.require_str, {"n": 3}, "n", max_len=5).extra["reason"] == "type"
    assert _raises(http.require_str, {"n": "toolong"}, "n", max_len=3).extra["reason"] == "too_long"
    assert _raises(http.require_str, {"n": "ab"}, "n", max_len=9, min_len=3).extra["reason"] == "too_short"
    assert _raises(http.require_str, {"n": "  "}, "n", max_len=9, min_len=1).extra["reason"] == "required"
    assert _raises(http.require_str, {"n": "a\r\nb"}, "n", max_len=9).extra["reason"] == "control_characters"


def test_multiline_strings_keep_line_breaks_and_tabs():
    value = http.require_str({"d": "a\r\nb\tc\rd"}, "d", max_len=20, multiline=True)
    assert value == "a\nb\tc\nd"
    assert _raises(http.require_str, {"d": "a\x00b"}, "d", max_len=9, multiline=True)


@pytest.mark.parametrize("body", [
    pytest.param(b'{"a": NaN}', id="nan"),
    pytest.param(b'{"a": Infinity}', id="inf"),
    pytest.param(b'{"a": -Infinity}', id="-inf"),
    pytest.param(b'{"a": 1e999}', id="1e999"),
    pytest.param(b'{"a": -1e999}', id="-1e999"),
    # explicit id: a 40K-character id overflows the Windows environment-variable cap
    pytest.param(b'{"a": ' + b"[" * 20000 + b"]" * 20000 + b"}", id="deep-nesting"),
])
def test_read_json_refuses_numbers_json_cannot_carry_and_runaway_nesting(body):
    r = _client().post("/api/workspace/echo-large", content=body,
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_request", "message": "the body is not valid JSON",
                        "field": "body", "reason": "malformed"}


def test_read_json_keeps_ordinary_numbers():
    r = _client().post("/api/workspace/echo-large", content=b'{"a": 1.5e10, "b": -0.25, "c": 7}',
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 200 and r.json() == {"keys": ["a", "b", "c"]}


@pytest.mark.parametrize("multiline", [False, True])
def test_lone_surrogates_are_refused(multiline):
    error = _raises(http.require_str, {"n": "Ana\ud800"}, "n", max_len=99, multiline=multiline)
    assert error.extra["reason"] == "control_characters"
    assert http.require_str({"n": "Ana \U0001F600"}, "n", max_len=99, multiline=multiline) == \
        "Ana \U0001F600", "real astral characters (emoji) are fine"


@pytest.mark.parametrize("char", ["\x85", "\x9b", "\u2028", "\u2029", "\x7f", "\t"])
def test_single_line_strings_refuse_c1_controls_and_unicode_line_breaks(char):
    error = _raises(http.require_str, {"n": f"Ana{char}Bcc: x@evil.test"}, "n", max_len=99)
    assert error.extra == {"field": "n", "reason": "control_characters"}


def test_multiline_strings_normalize_unicode_separators_and_refuse_c1():
    assert http.require_str({"d": "a\u2028b\u2029c"}, "d", max_len=9, multiline=True) == "a\nb\nc"
    assert _raises(http.require_str, {"d": "a\x85b"}, "d", max_len=9,
                   multiline=True).extra["reason"] == "control_characters"
    assert http.require_str({"d": "Vânzări — ședință"}, "d", max_len=99, multiline=True) == \
        "Vânzări — ședință", "ordinary Unicode text is untouched"


def test_optional_str():
    assert http.optional_str({}, "n", max_len=3) is None
    assert http.optional_str({"n": None}, "n", max_len=3) is None
    assert http.optional_str({"n": "ab"}, "n", max_len=3) == "ab"
    _raises(http.optional_str, {"n": ""}, "n", max_len=3, min_len=1)


def test_integers_and_booleans():
    assert http.require_int({"i": 4}, "i", minimum=1, maximum=5) == 4
    assert _raises(http.require_int, {"i": True}, "i").extra["reason"] == "type"
    assert _raises(http.require_int, {"i": "4"}, "i").extra["reason"] == "type"
    assert _raises(http.require_int, {"i": 0}, "i", minimum=1).extra["reason"] == "too_small"
    assert _raises(http.require_int, {"i": 9}, "i", maximum=5).extra["reason"] == "too_large"
    assert _raises(http.require_int, {}, "i").extra["reason"] == "required"
    assert http.optional_int({}, "i") is None and http.optional_int({"i": 2}, "i") == 2
    assert http.optional_bool({}, "b") is None
    assert http.optional_bool({}, "b", default=False) is False
    assert http.optional_bool({"b": True}, "b") is True
    assert _raises(http.optional_bool, {"b": 1}, "b").extra["reason"] == "type"


def test_integers_stay_inside_the_sqlite_range():
    assert http.require_int({"i": http.MAX_ID}, "i") == http.MAX_ID
    assert _raises(http.require_int, {"i": http.MAX_ID + 1}, "i").extra["reason"] == "too_large"
    assert _raises(http.require_int, {"i": http.MIN_INT - 1}, "i").extra["reason"] == "too_small"
    assert _raises(http.require_int, {"i": 10 ** 30}, "i", maximum=10 ** 40).extra["reason"] == \
        "too_large", "an explicit maximum never widens the database range"
    assert _raises(http.require_id_list, {"ids": [1, 2 ** 63]}, "ids").extra["reason"] == "too_large"


def test_choices():
    assert http.require_choice({"r": "admin"}, "r", ("admin", "member")) == "admin"
    assert http.require_choice({}, "r", ("ro", "en"), default="ro") == "ro"
    assert _raises(http.require_choice, {}, "r", ("a",)).extra["reason"] == "required"
    assert _raises(http.require_choice, {"r": "root"}, "r", ("a",)).extra["reason"] == "invalid_choice"
    assert http.optional_choice({}, "r", ("a",)) is None


def test_lists_and_id_lists():
    assert http.require_list({"l": [1, "a"]}, "l", max_items=2) == [1, "a"]
    assert http.require_list({}, "l", max_items=2, required=False) == []
    assert _raises(http.require_list, {"l": "x"}, "l", max_items=2).extra["reason"] == "type"
    assert _raises(http.require_list, {"l": [1, 2, 3]}, "l", max_items=2).extra["reason"] == "too_many"
    assert _raises(http.require_list, {"l": []}, "l", max_items=2, min_items=1).extra["reason"] == "too_few"
    assert http.require_id_list({"ids": [3, 1, 3]}, "ids") == [3, 1]
    for bad in ([0], [-1], ["1"], [True], [1.5]):
        _raises(http.require_id_list, {"ids": bad}, "ids")
    assert _raises(http.require_id_list, {"ids": [1, 1]}, "ids", min_items=2).extra["reason"] == "too_few"
    assert _raises(http.require_id_list, {"ids": list(range(1, 52))}, "ids").extra["reason"] == "too_many"
    assert http.optional_id_list({}, "ids") is None
    assert http.optional_id_list({"ids": [2]}, "ids") == [2]


@pytest.mark.parametrize(("value", "expected"), [
    ("Ana@Acme.TEST", "ana@acme.test"), ("  a.b+c@sub.acme.ro ", "a.b+c@sub.acme.ro"),
    ("no-at-sign", None), ("a@b", None), ("a b@acme.test", None), ("a@acme.test\r\nBcc: x", None),
    ("Ana <ana@acme.test>", None), ("a@acme.test,b@acme.test", None), (None, None), (42, None),
    ("x" * 250 + "@a.ro", None), ("a@-acme.test", None),
])
def test_normalize_email(value, expected):
    assert http.normalize_email(value) == expected
    assert http.is_valid_email(value) is (expected is not None)


def test_require_email_and_lists():
    assert http.require_email({"e": "A@ACME.test"}, "e") == "a@acme.test"
    assert http.require_email({}, "e", required=False) == ""
    assert http.require_email({"e": " "}, "e", required=False) == ""
    assert _raises(http.require_email, {}, "e").extra["reason"] == "required"
    assert _raises(http.require_email, {"e": "nope"}, "e").extra["reason"] == "invalid_email"
    emails = http.require_email_list({"to": ["A@acme.test", "a@acme.test", "b@acme.test"]}, "to")
    assert emails == ["a@acme.test", "b@acme.test"]
    assert http.require_email_list({}, "to") == []
    assert _raises(http.require_email_list, {"to": ["bad"]}, "to").extra["reason"] == "invalid_email"
    many = [f"u{i}@acme.test" for i in range(21)]
    assert _raises(http.require_email_list, {"to": many}, "to").extra["reason"] == "too_many"
