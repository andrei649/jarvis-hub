"""H373 — see how much provider quota is left, and never hammer a provider that said stop.

Nerva learned of a provider's limit only from a failed request, in one process's memory. Now a
response hook on every cloud backend's client records the provider's own quota headers
(OpenAI-style ``x-ratelimit-*``, Anthropic's ``anthropic-ratelimit-*``, ``retry-after``) in a
SQLite file every process shares; a 429 holds that backend and key in every process until the
provider's retry-after, refused before the request is sent; ``GET /api/llm/quota``, the HUD
Provider Quota panel and ``/usage`` show it.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time

import httpx
import pytest

from agents.core.llm import quota as q
from agents.core.llm.quota import QuotaStore


@pytest.fixture
def store(tmp_path):
    s = QuotaStore(tmp_path / "quota.db")
    q.set_store(s)
    yield s
    q.set_store(None)


@pytest.fixture
def cloud(monkeypatch):
    """Classify hosts without DNS: localhost and 127.0.0.1 are local, anything else is cloud."""
    import agents.core.http_client as http_client

    monkeypatch.setattr(http_client, "host_is_local", lambda host: host in ("localhost", "127.0.0.1"))


# ── reading the headers ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,seconds", [
    ("6m0s", 360.0), ("1.5s", 1.5), ("20ms", 0.02), ("1h2m3s", 3723.0), ("30", 30.0), ("0.5", 0.5),
    ("-3", 0.0), ("", None), ("abc", None), ("5x", None), ("5s junk", None), (None, None),
])
def test_durations_are_read_in_every_form_providers_use(text, seconds):
    got = q.parse_duration(text)
    assert got == (None if seconds is None else pytest.approx(seconds))


@pytest.mark.parametrize("text", ["inf", "Infinity", "-inf", "1e999", "nan", "NaN", "9" * 400 + "s"])
def test_a_value_that_is_not_a_finite_number_is_unreadable(text):
    assert q.parse_duration(text) is None
    assert q.retry_after({"retry-after": text}, now=0) is None
    assert q.parse_headers({"x-ratelimit-reset-requests": text, "x-ratelimit-remaining-requests": "5"}, now=0) \
        == {"requests": {"remaining": 5}}


def test_a_negative_retry_after_is_unreadable_so_the_default_hold_applies(store):
    assert q.retry_after({"retry-after": "-5"}, now=0) is None
    until = store.block("x", "", q.parse_headers({"retry-after": "-5"}).get("retry_after"), now=0)
    assert until == q.DEFAULT_BLOCK_SECONDS


def test_retry_after_is_seconds_or_an_http_date():
    assert q.retry_after({"retry-after": "12"}, now=0) == 12.0
    assert q.retry_after({"retry-after": "Thu, 01 Jan 1970 00:01:40 GMT"}, now=40) == 60.0
    assert q.retry_after({"retry-after": "Thu, 01 Jan 1970 00:00:10 GMT"}, now=40) == 0.0
    assert q.retry_after({"retry-after": "Thu, 01 Jan 1970 00:01:40"}, now=40) == 60.0     # no zone: UTC
    assert q.retry_after({"retry-after": "soon"}, now=0) is None
    assert q.retry_after({}, now=0) is None and q.retry_after(None) is None


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset is Unix-only")
def test_a_date_without_a_zone_is_utc_whatever_the_hosts_zone(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        assert q.retry_after({"retry-after": "Thu, 01 Jan 1970 00:01:40"}, now=40) == 60.0
        assert q.parse_headers({"x-ratelimit-reset-requests": "1970-01-01T00:16:40"}, now=0) \
            == {"requests": {"reset_at": 1000.0}}                             # a reset time too (review F7)
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_openai_style_headers():
    got = q.parse_headers({
        "x-ratelimit-limit-requests": "100", "x-ratelimit-remaining-requests": "42",
        "x-ratelimit-reset-requests": "6m0s", "x-ratelimit-limit-tokens": "40000",
        "x-ratelimit-remaining-tokens": "39000", "x-ratelimit-reset-tokens": "20ms",
    }, now=1000.0)
    assert got == {"requests": {"limit": 100, "remaining": 42, "reset_at": 1360.0},
                   "tokens": {"limit": 40000, "remaining": 39000, "reset_at": pytest.approx(1000.02)}}


def test_anthropic_headers():
    got = q.parse_headers({
        "anthropic-ratelimit-requests-limit": "50", "anthropic-ratelimit-requests-remaining": "49",
        "anthropic-ratelimit-requests-reset": "1970-01-01T00:16:40Z",
        "anthropic-ratelimit-input-tokens-limit": "20000", "anthropic-ratelimit-input-tokens-remaining": "0",
        "anthropic-ratelimit-output-tokens-remaining": "7", "retry-after": "5",
    }, now=0.0)
    assert got == {"requests": {"limit": 50, "remaining": 49, "reset_at": 1000.0},
                   "input-tokens": {"limit": 20000, "remaining": 0}, "output-tokens": {"remaining": 7},
                   "retry_after": 5.0}


def test_unreadable_values_are_left_out():
    got = q.parse_headers({"x-ratelimit-limit-requests": "lots", "x-ratelimit-remaining-requests": "3",
                           "x-ratelimit-reset-requests": "someday"}, now=0)
    assert got == {"requests": {"remaining": 3}}
    assert q.parse_headers({"content-type": "application/json"}) == {}


def test_a_key_is_known_only_by_a_short_fingerprint():
    def req(headers=None, url="https://api.example.com/v1/x"):
        return httpx.Request("POST", url, headers=headers or {})

    fp = q.key_fingerprint(req({"x-api-key": "sk-secret"}))
    assert len(fp) == 12 and "secret" not in fp
    assert q.key_fingerprint(req({"x-api-key": "sk-secret"})) == fp
    assert q.key_fingerprint(req({"authorization": "Bearer sk-secret"})) != fp
    assert q.key_fingerprint(req({"x-goog-api-key": "g"})) == q.key_fingerprint(req(url="https://x/y?key=g"))
    assert q.key_fingerprint(req({"api-key": "a"})) != ""
    assert q.key_fingerprint(req()) == ""


# ── the shared store ─────────────────────────────────────────────────────────────

def test_the_latest_numbers_are_kept_per_backend_and_key(store):
    store.record("anthropic", "k1", {"requests": {"limit": 100, "remaining": 10, "reset_at": 150.0}}, now=100)
    store.record("anthropic", "k1", {"requests": {"limit": 100, "remaining": 5, "reset_at": 160.0}}, now=110)
    store.record("gemini", "", {"tokens": {"limit": 0, "remaining": 3}}, now=110)
    rows = store.snapshot(now=120)
    assert [(r["backend"], r["key"]) for r in rows] == [("anthropic", "k1"), ("gemini", "")]
    assert rows[0]["quota"] == {"requests": {"limit": 100, "remaining": 5, "left": 0.05, "resets_in": 40.0}}
    assert rows[0]["observed_at"] == 110 and rows[0]["blocked"] is False and rows[0]["blocked_for"] is None
    assert rows[1]["quota"] == {"tokens": {"limit": 0, "remaining": 3, "left": None, "resets_in": None}}


def test_left_is_clamped_and_a_passed_reset_is_zero(store):
    store.record("x", "", {"requests": {"limit": 10, "remaining": 20, "reset_at": 5.0}}, now=1)
    (row,) = store.snapshot(now=50)
    assert row["quota"]["requests"]["left"] == 1.0 and row["quota"]["requests"]["resets_in"] == 0.0


def test_a_negative_limit_has_no_fraction(store):
    store.record("x", "", {"requests": {"limit": -5, "remaining": 3}}, now=1)
    assert store.snapshot(now=2)[0]["quota"]["requests"]["left"] is None


def test_a_429_blocks_until_its_retry_after(store):
    until = store.block("anthropic", "k1", 12.0, now=100)
    assert until == 112.0
    assert store.blocked_until("anthropic", "k1", now=111.9) == 112.0
    assert store.blocked_until("anthropic", "k1", now=112.0) is None
    assert store.blocked_until("anthropic", "k2", now=105) is None       # another key is not held
    assert store.blocked_until("gemini", "k1", now=105) is None


def test_a_block_without_retry_after_uses_the_default_and_never_exceeds_the_cap(store):
    assert store.block("x", "", None, now=0) == q.DEFAULT_BLOCK_SECONDS == 30.0
    assert store.block("x", "", 10_000, now=0) == q.MAX_BLOCK_SECONDS == 900.0
    assert store.block("x", "", -5, now=0) == 0.0


def test_a_blocked_backend_shows_even_before_any_numbers(store):
    store.block("gemini", "k9", 20, status=429, now=100)
    (row,) = store.snapshot(now=105)
    assert row == {"backend": "gemini", "key": "k9", "model": "", "observed_at": None, "quota": {},
                   "blocked": True, "blocked_for": 15.0, "block_status": 429}
    assert store.snapshot(now=200) == []


def test_a_hold_on_one_model_leaves_the_keys_other_models_free(store):
    """Providers limit each model on its own (review F4); a hold with no model covers the key."""
    store.block("gemini", "k1", 30, now=0, model="gemini-2.5-pro")
    assert store.blocked_until("gemini", "k1", now=10, model="gemini-2.5-pro") == 30
    assert store.blocked_until("gemini", "k1", now=10, model="gemini-2.5-flash") is None
    assert store.blocked_until("gemini", "k1", now=10) is None
    store.block("gemini", "k1", 60, now=0)                               # no model: the whole key
    assert store.blocked_until("gemini", "k1", now=10, model="gemini-2.5-flash") == 60
    assert store.blocked_until("gemini", "k1", now=10, model="gemini-2.5-pro") == 60   # the later end


def test_the_numbers_are_kept_per_model(store):
    store.record("gemini", "k1", {"requests": {"limit": 10, "remaining": 1}}, now=0, model="gemini-2.5-pro")
    store.record("gemini", "k1", {"requests": {"limit": 10, "remaining": 9}}, now=1, model="gemini-2.5-flash")
    store.block("gemini", "k1", 30, now=0, model="gemini-2.5-pro")
    rows = store.snapshot(now=2)
    assert [(r["model"], r["quota"]["requests"]["remaining"], r["blocked"]) for r in rows] == [
        ("gemini-2.5-flash", 9, False), ("gemini-2.5-pro", 1, True)]
    assert q.render(rows).splitlines()[1:] == [
        "gemini gemini-2.5-flash (key k1): requests 9/10",
        "gemini gemini-2.5-pro (key k1): requests 1/10 — BLOCKED for 28s after a 429"]


def test_a_store_from_before_models_is_started_afresh(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE quota (backend TEXT NOT NULL, key_fp TEXT NOT NULL, observed_at REAL NOT NULL,"
                     " data TEXT NOT NULL, PRIMARY KEY (backend, key_fp))")
        conn.execute("CREATE TABLE blocks (backend TEXT NOT NULL, key_fp TEXT NOT NULL, until REAL NOT NULL,"
                     " status INTEGER NOT NULL, at REAL NOT NULL, PRIMARY KEY (backend, key_fp))")
        conn.execute("INSERT INTO quota VALUES ('x', '', 0, '{}')")
    s = QuotaStore(path)
    s.block("x", "k", 60, now=0, model="m")
    s.record("x", "k", {"requests": {"remaining": 1}}, now=0, model="m")
    assert [(r["backend"], r["model"]) for r in s.snapshot(now=1)] == [("x", "m")]


@pytest.mark.parametrize("url,body,model", [
    ("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent", None,
     "gemini-2.5-pro"),
    ("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse",
     {"contents": []}, "gemini-2.5-flash"),
    ("https://generativelanguage.googleapis.com/v1beta/cachedContents", {"model": "models/gemini-2.5-pro"},
     "gemini-2.5-pro"),
    ("https://api.anthropic.com/v1/messages", {"model": "claude-a", "messages": [{"model": "no"}]}, "claude-a"),
    ("https://api.anthropic.com/v1/models", None, ""),
    ("https://api.anthropic.com/v1/messages", [1], ""),
    ("https://api.anthropic.com/v1/messages", {"model": 7}, ""),
])
def test_the_model_a_request_asks_for(url, body, model):
    request = httpx.Request("POST", url, json=body) if body is not None else httpx.Request("GET", url)
    assert q.request_model(request) == model


def test_a_body_that_is_not_json_or_not_read_names_no_model():
    assert q.request_model(httpx.Request("POST", "https://x/v1/messages", content=b"not json")) == ""

    async def chunks():
        yield b'{"model": "m"}'

    assert q.request_model(httpx.Request("POST", "https://x/v1/messages", content=chunks())) == ""


def test_every_process_sees_the_same_state(tmp_path):
    a, b = QuotaStore(tmp_path / "shared.db"), QuotaStore(tmp_path / "shared.db")
    a.block("anthropic", "k", 60, now=0)
    a.record("anthropic", "k", {"requests": {"remaining": 1}}, now=0)
    assert b.blocked_until("anthropic", "k", now=10) == 60
    assert b.snapshot(now=10)[0]["quota"]["requests"]["remaining"] == 1


def test_damaged_stored_numbers_read_as_none(store, tmp_path):
    store.record("x", "", {"requests": {"remaining": 1}}, now=0)
    with sqlite3.connect(tmp_path / "quota.db") as conn:
        conn.execute("UPDATE quota SET data='not json'")
    assert store.snapshot(now=1)[0]["quota"] == {}
    with sqlite3.connect(tmp_path / "quota.db") as conn:
        conn.execute("UPDATE quota SET data='[1]'")
    assert store.snapshot(now=1)[0]["quota"] == {}
    store.record("y", "", {"requests": "garbage"}, now=0)
    assert [r["quota"] for r in store.snapshot(now=1) if r["backend"] == "y"] == [{}]


def test_the_default_store_lives_in_the_data_folder(tmp_path, monkeypatch):
    import agents.core.paths as paths

    monkeypatch.setattr(paths, "data_path", lambda name: tmp_path / name)
    q.set_store(None)
    try:
        s = q.get_store()
        assert s.path == tmp_path / "provider_quota.db" and q.get_store() is s
    finally:
        q.set_store(None)


# ── the hooks on every cloud client ──────────────────────────────────────────────

def _client(handler, backend="anthropic"):
    from agents.core.llm.egress import llm_async_client

    return llm_async_client(backend, transport=httpx.MockTransport(handler))


async def test_every_cloud_response_records_its_quota(store, cloud):
    def handler(request):
        return httpx.Response(200, headers={"anthropic-ratelimit-requests-limit": "50",
                                            "anthropic-ratelimit-requests-remaining": "7"}, json={})

    async with _client(handler) as client:
        await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": "sk-1"})
    (row,) = store.snapshot()
    assert row["backend"] == "anthropic" and row["quota"]["requests"]["remaining"] == 7
    assert row["key"] == q.key_fingerprint(httpx.Request("POST", "https://x", headers={"x-api-key": "sk-1"}))


async def test_a_response_without_quota_headers_records_nothing(store, cloud):
    async with _client(lambda r: httpx.Response(200, json={})) as client:
        await client.get("https://api.anthropic.com/v1/models")
    assert store.snapshot() == []


async def test_a_429_holds_that_key_in_every_process_before_the_next_request_leaves(store, cloud):
    from agents.core.observability.egress_monitor import EGRESS_MONITOR

    calls = []

    def handler(request):
        calls.append(request.headers.get("x-api-key"))
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "40"}, json={})
        return httpx.Response(200, json={})

    async with _client(handler) as client:
        first = await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": "sk-1"})
        assert first.status_code == 429
        before = EGRESS_MONITOR.snapshot("llm:anthropic")["plugins"].get("llm:anthropic", {}).get("total", 0)
        with pytest.raises(q.ProviderRateLimited) as err:
            await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": "sk-1"})
        after = EGRESS_MONITOR.snapshot("llm:anthropic")["plugins"].get("llm:anthropic", {}).get("total", 0)
        assert "rate-limited" in str(err.value) and "shared 429 guard" in str(err.value)
        assert calls == ["sk-1"] and after == before                  # never dialled, never an egress row
        other = await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": "sk-2"})
        assert other.status_code == 200 and calls == ["sk-1", "sk-2"]  # another key is not held
    assert isinstance(q.ProviderRateLimited("x"), httpx.RequestError)
    other_process = QuotaStore(store.path)
    assert other_process.blocked_until("anthropic", q.key_fingerprint(
        httpx.Request("POST", "https://x", headers={"x-api-key": "sk-1"}))) is not None
    (row,) = [r for r in store.snapshot() if r["blocked"]]
    assert row["block_status"] == 429 and 35 <= row["blocked_for"] <= 40


async def test_a_429_holds_that_model_only_and_records_numbers_per_model(store, cloud):
    base = "https://generativelanguage.googleapis.com/v1beta/models/"
    sent = []

    def handler(request):
        sent.append(q.request_model(request))
        if len(sent) == 1:
            return httpx.Response(429, headers={"retry-after": "40"}, json={})
        return httpx.Response(200, headers={"x-ratelimit-remaining-requests": "9"}, json={})

    async with _client(handler, backend="gemini") as client:
        headers = {"x-goog-api-key": "g-1"}
        assert (await client.post(base + "gemini-2.5-pro:generateContent", headers=headers)).status_code == 429
        assert (await client.post(base + "gemini-2.5-flash:generateContent", headers=headers)).status_code == 200
        with pytest.raises(q.ProviderRateLimited):
            await client.post(base + "gemini-2.5-pro:generateContent", headers=headers)
        assert (await client.post("https://generativelanguage.googleapis.com/v1beta/cachedContents",
                                  headers=headers, json={"model": "models/gemini-2.5-flash"})).status_code == 200
    assert sent == ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash"]
    assert [(r["model"], r["blocked"]) for r in store.snapshot()] == [("gemini-2.5-flash", False), ("gemini-2.5-pro", True)]


async def test_a_429_on_a_request_naming_no_model_holds_the_whole_key(store, cloud):
    async with _client(lambda r: httpx.Response(429, json={})) as client:
        await client.get("https://api.anthropic.com/v1/models", headers={"x-api-key": "sk-1"})
        with pytest.raises(q.ProviderRateLimited):
            await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": "sk-1"},
                              json={"model": "claude-a"})


async def test_a_429_without_retry_after_holds_for_the_default(store, cloud):
    async with _client(lambda r: httpx.Response(429, json={})) as client:
        await client.post("https://api.anthropic.com/v1/messages")
    (row,) = store.snapshot()
    assert row["blocked"] and 25 <= row["blocked_for"] <= q.DEFAULT_BLOCK_SECONDS


async def test_other_errors_hold_nothing(store, cloud):
    async with _client(lambda r: httpx.Response(503, headers={"retry-after": "9"}, json={})) as client:
        await client.post("https://api.anthropic.com/v1/messages")
        await client.post("https://api.anthropic.com/v1/messages")
    assert not any(r["blocked"] for r in store.snapshot())


async def test_a_local_model_is_never_tracked_or_held(store, cloud):
    def handler(request):
        return httpx.Response(429, headers={"x-ratelimit-remaining-requests": "0"}, json={})

    async with _client(handler, backend="lm-studio") as client:
        await client.post("http://localhost:1234/v1/chat/completions")
        await client.post("http://localhost:1234/v1/chat/completions")
    assert store.snapshot() == []


async def test_a_local_request_is_never_held_even_when_its_backend_is_held_in_the_cloud(store, cloud):
    store.block("vlm", "", 60)
    async with _client(lambda r: httpx.Response(200, json={}), backend="vlm") as client:
        assert (await client.post("http://localhost:8080/v1/chat")).status_code == 200
        with pytest.raises(q.ProviderRateLimited):
            await client.post("https://vlm.example.com/v1/chat")


async def test_the_guard_never_breaks_a_request_when_its_store_fails(cloud, monkeypatch):
    class _Broken:
        def blocked_until(self, *a):
            raise sqlite3.OperationalError("disk I/O error")

        def record(self, *a):
            raise sqlite3.OperationalError("disk I/O error")

        def block(self, *a):
            raise sqlite3.OperationalError("disk I/O error")

    q.set_store(_Broken())
    try:
        async with _client(lambda r: httpx.Response(429, headers={"x-ratelimit-remaining-requests": "0"})) as client:
            assert (await client.get("https://api.anthropic.com/v1/models")).status_code == 429
            assert (await client.get("https://api.anthropic.com/v1/models")).status_code == 429
    finally:
        q.set_store(None)


# ── a held key fails over to the next key in the pool (review F1) ──────────────────

_CLAUDE_OK = {"content": [{"type": "text", "text": "hi"}]}
_CLAUDE_STREAM = ('data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}\n\n'
                  'data: {"type": "message_stop"}\n\n')
_GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}


def _fp(key):
    return q.key_fingerprint(httpx.Request("POST", "https://x", headers={"x-api-key": key}))


def _pool_backend(kind, handler):
    from agents.core.llm.anthropic import ClaudeBackend
    from agents.core.llm.auth_rotation import AuthProfilePool
    from agents.core.llm.gemini import GeminiBackend

    cls, backend = (ClaudeBackend, "anthropic") if kind == "claude" else (GeminiBackend, "gemini")
    pool = AuthProfilePool(["k-A", "k-B"], backend)
    b = cls(api_key="", auth_pool=pool)
    b.client = _client(handler, backend=backend)
    return b, pool


def _answering(sent, body=None, text=None):
    def handler(request):
        sent.append(request.headers.get("x-api-key") or request.headers.get("x-goog-api-key"))
        return httpx.Response(200, text=text) if text is not None else httpx.Response(200, json=body)
    return handler


@pytest.mark.parametrize("call", ["generate", "tool_turn", "stream"])
async def test_a_key_another_process_held_fails_over_to_the_next_key_in_claudes_pool(store, cloud, call):
    store.block("anthropic", _fp("k-A"), 600)                       # written by another process
    sent = []
    b, pool = _pool_backend("claude", _answering(sent, _CLAUDE_OK, _CLAUDE_STREAM if call == "stream" else None))
    if call == "generate":
        assert await b.generate("", "hello") == "hi"
    elif call == "tool_turn":
        assert (await b.generate_tool_turn("", [{"role": "user", "content": "hello"}], [])).content == "hi"
    else:
        assert await b.generate_stream("", "hello") == "hi"
    assert sent == ["k-B"] and pool.current_key() == "k-B"            # the held key never dialled


@pytest.mark.parametrize("call", ["generate", "tool_turn", "stream"])
async def test_a_key_another_process_held_fails_over_to_the_next_key_in_geminis_pool(store, cloud, call):
    store.block("gemini", _fp("k-A"), 600)
    sent = []
    stream = "data: " + json.dumps(_GEMINI_OK) + "\n\n" if call == "stream" else None
    b, pool = _pool_backend("gemini", _answering(sent, _GEMINI_OK, stream))
    if call == "generate":
        assert await b.generate("gemini-2.5-flash", "hello") == "hi"
    elif call == "tool_turn":
        assert (await b.generate_tool_turn("gemini-2.5-flash", [{"role": "user", "content": "hello"}], [])).content == "hi"
    else:
        assert await b.generate_stream("gemini-2.5-flash", "hello") == "hi"
    assert sent == ["k-B"] and pool.current_key() == "k-B"


async def test_a_short_hold_that_ended_is_not_blocked_behind_a_long_one_in_the_same_process(store, cloud):
    """k-A drew a 600 s hold, k-B a 1 s one that is over; the pool still cools k-B in memory."""
    store.block("anthropic", _fp("k-A"), 600)
    sent = []
    b, pool = _pool_backend("claude", _answering(sent, _CLAUDE_OK))
    pool.report_failure("k-B")
    assert pool.current_key() == "k-A"
    assert await b.generate("", "hello") == "hi" and sent == ["k-B"]


def test_the_pool_keeps_a_held_key_cool_for_the_whole_hold():
    from agents.core.llm.auth_rotation import AuthProfilePool

    clock = [0.0]
    pool = AuthProfilePool(["k1", "k2"], "x", clock=lambda: clock[0])
    pool.report_failure("k1", cooldown=600)
    clock[0] = 599
    assert pool.healthy_count() == 1
    clock[0] = 600
    assert pool.healthy_count() == 2
    pool.report_failure("k1", cooldown=1)                               # the backoff is still the floor
    clock[0] = 600 + 30 * 2 - 1
    assert pool.healthy_count() == 1


async def test_a_single_held_key_still_says_why(store, cloud):
    from agents.core.llm.anthropic import ClaudeBackend

    store.block("anthropic", _fp("k-A"), 600)
    b = ClaudeBackend(api_key="k-A")
    b.client = _client(lambda r: httpx.Response(200, json=_CLAUDE_OK))
    assert "shared 429 guard" in await b.generate("", "hello")


def test_cloud_means_not_a_local_host(monkeypatch):
    import agents.core.http_client as http_client

    seen = []
    monkeypatch.setattr(http_client, "host_is_local", lambda host: seen.append(host) or host == "box.lan")
    assert q._cloud(httpx.Request("GET", "https://API.Example.com./x")) is True
    assert q._cloud(httpx.Request("GET", "http://box.lan/x")) is False
    assert seen == ["api.example.com", "box.lan"]


def test_every_backend_client_carries_both_hooks():
    from agents.core.llm.egress import llm_async_client

    client = llm_async_client("gemini")
    try:
        names = [h.__qualname__ for h in client.event_hooks["request"]]
        assert names[0].startswith("request_hook") and names[1].startswith("_recorder")
        assert [h.__qualname__.split(".")[0] for h in client.event_hooks["response"]] == ["response_hook"]
    finally:
        asyncio.run(client.aclose())


# ── what the owner sees ──────────────────────────────────────────────────────────

def test_usage_renders_each_backend(store):
    store.record("anthropic", "abcdef123456", {"requests": {"limit": 50, "remaining": 7, "reset_at": 9e18},
                                               "tokens": {"remaining": 900}}, now=0)
    store.record("gemini", "", {}, now=0)
    store.block("gemini", "", 30)
    text = q.render(q.usage())
    lines = text.splitlines()
    assert lines[0] == "Provider quota:"
    assert lines[1].startswith("anthropic (key abcdef): requests 7/50, resets in ") and lines[1].endswith(", tokens 900")
    assert lines[2].startswith("gemini: no quota headers — BLOCKED for ") and lines[2].endswith("s after a 429")


def test_usage_skips_a_kind_with_no_remaining_count(store):
    store.record("xai", "", {"tokens": {"limit": 100}, "requests": {"remaining": 4}}, now=0)
    assert q.render(q.usage()).splitlines()[1] == "xai: requests 4"


def test_usage_says_where_the_numbers_come_from_when_there_are_none(store):
    assert q.render([]) == "No provider quota seen yet: it is read from each cloud provider's responses."


@pytest.fixture
def admin_client(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm")
    return TestClient(web.app), {"X-Admin-Token": "adm"}


def test_the_quota_route_is_admin_only_and_answers_every_backend(store, admin_client):
    client, hdr = admin_client
    store.block("xai", "", 10)
    assert client.get("/api/llm/quota").status_code in (401, 403)
    got = client.get("/api/llm/quota", headers=hdr)
    assert got.status_code == 200 and got.json()["ok"] is True
    assert [p["backend"] for p in got.json()["providers"]] == ["xai"]
    assert "no-store" in got.headers["Cache-Control"]


def test_the_quota_route_says_when_it_cannot_read(admin_client, monkeypatch):
    client, hdr = admin_client
    monkeypatch.setattr(q, "usage", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    got = client.get("/api/llm/quota", headers=hdr)
    assert got.status_code == 503 and got.json() == {"ok": False, "reason": "quota_unavailable", "providers": []}
    monkeypatch.setattr(q, "usage", lambda: [{"backend": "x", "resets_in": float("inf")}])
    got = client.get("/api/llm/quota", headers=hdr)                   # not JSON: still the 503, never a 500
    assert got.status_code == 503 and got.json()["reason"] == "quota_unavailable"


def test_an_infinite_reset_stored_before_the_check_reads_as_unknown(store, admin_client):
    client, hdr = admin_client
    store.record("openrouter", "k", {"requests": {"limit": 100, "remaining": 5, "reset_at": float("inf")}})
    got = client.get("/api/llm/quota", headers=hdr)
    assert got.status_code == 200
    assert got.json()["providers"][0]["quota"]["requests"]["resets_in"] is None
    assert q.render(q.usage()).splitlines()[1].endswith("requests 5/100")


async def test_the_usage_command_is_for_the_owner(store):
    from agents.core.commands import Principal, build_default_registry

    store.block("anthropic", "", 30)
    registry = build_default_registry()
    owner = await registry.dispatch("/usage", orch=None, principal=Principal(channel="web", admin=True))
    assert owner.reply.startswith("Provider quota:\nanthropic: no quota headers — BLOCKED")
    guest = await registry.dispatch("/usage", orch=None, principal=Principal(channel="telegram"))
    assert "Provider quota" not in guest.reply
    assert json.dumps(q.KINDS) == '["requests", "tokens", "input-tokens", "output-tokens"]'
