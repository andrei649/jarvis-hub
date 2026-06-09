"""H12.20: cloud auth-profile rotation + failover.

A provider can hold several API keys; a rotatable error (401/403/429) fails over
to the next healthy key, and the failed key cools down (exponential backoff).
Single-key pools behave exactly like the old single-key backend.
"""
import sys
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.auth_rotation import AuthProfilePool, is_rotatable_status, _split_keys  # noqa: E402
from core.llm.anthropic import ClaudeBackend  # noqa: E402
from core.llm.gemini import GeminiBackend  # noqa: E402


# ── pool: construction ────────────────────────────────────────────

def test_single_key_pool_has_no_rotation():
    p = AuthProfilePool(["only"], "anthropic")
    assert p.size == 1 and p.current_key() == "only"


def test_dedup_and_skip_empties():
    p = AuthProfilePool(["a", "", "a", "b", None], "x")
    assert p.size == 2 and p.current_key() == "a"


def test_split_keys_parses_separators():
    assert _split_keys("a, b\nc  d") == ["a", "b", "c", "d"]
    assert _split_keys("  ") == []


def test_from_env_prefers_multi_then_single(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEYS", "k1, k2 k3")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "single")
    assert AuthProfilePool.from_env("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS").size == 3
    monkeypatch.delenv("ANTHROPIC_API_KEYS")
    assert AuthProfilePool.from_env("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS").current_key() == "single"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert AuthProfilePool.from_env("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS").size == 0


# ── pool: rotation + cooldown ─────────────────────────────────────

def test_report_failure_cools_and_rotates():
    p = AuthProfilePool(["k1", "k2"], "x")
    assert p.current_key() == "k1"
    p.report_failure("k1")
    assert p.current_key() == "k2"          # rotated away from the failed key
    assert p.healthy_count() == 1           # k1 is cooling


def test_exponential_backoff_with_fake_clock():
    t = [0.0]
    p = AuthProfilePool(["k1", "k2"], "x", base_cooldown=30.0, clock=lambda: t[0])
    p.report_failure("k1")                  # failures=1 → 30s
    assert p._find("k1").cooldown_until == 30.0
    t[0] = 31.0
    assert p.healthy_count() == 2           # k1 recovered
    p.report_failure("k1")                  # failures=2 → 60s, from t=31
    assert p._find("k1").cooldown_until == 91.0


def test_cooldown_is_capped():
    p = AuthProfilePool(["k1"], "x", base_cooldown=30.0, max_cooldown=100.0, clock=lambda: 0.0)
    for _ in range(10):
        p.report_failure("k1")
    assert p._find("k1").cooldown_until == 100.0


def test_report_success_resets():
    p = AuthProfilePool(["k1", "k2"], "x")
    p.report_failure("k1")
    p.report_success("k1")
    assert p._find("k1").failures == 0 and p.healthy_count() == 2


def test_current_falls_back_when_all_cooling():
    p = AuthProfilePool(["only"], "x", clock=lambda: 0.0)
    p.report_failure("only")
    # all profiles cooling → still return one (don't disable the tier)
    assert p.current_key() == "only"


def test_rotate_skips_unhealthy():
    t = [0.0]
    p = AuthProfilePool(["k1", "k2", "k3"], "x", clock=lambda: t[0])
    p.report_failure("k2")                  # cools k2, active → k3
    assert p.current_key() == "k3"
    assert p.rotate().id.endswith("1")      # wraps to k1 (k2 still cooling)


def test_is_rotatable_status():
    assert all(is_rotatable_status(s) for s in (401, 403, 429))
    assert not any(is_rotatable_status(s) for s in (200, 500, 503))


def test_status_masks_keys():
    p = AuthProfilePool(["supersecret1", "supersecret2"], "anthropic")
    st = p.status()
    assert st["size"] == 2 and st["healthy"] == 2
    assert st["profiles"][0]["key_hint"] == "supe…"
    assert "supersecret1" not in str(st)


# ── backend fakes (offline) ───────────────────────────────────────

class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", "https://api.test/x")
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=req,
                response=httpx.Response(self.status_code, request=req))

    def json(self):
        return self._data


_CLAUDE_OK = {"content": [{"type": "text", "text": "hi"}]}
_GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}


class _ClaudeFakeClient:
    def __init__(self, behaviors):
        self.behaviors = behaviors           # key -> status
        self.calls = []

    async def post(self, url, headers=None, json=None):
        key = headers["x-api-key"]
        self.calls.append(key)
        return _Resp(self.behaviors.get(key, 200), _CLAUDE_OK)


class _GeminiFakeClient:
    def __init__(self, behaviors):
        self.behaviors = behaviors
        self.calls = []

    async def post(self, url, json=None):
        key = url.split("key=")[1].split("&")[0]
        self.calls.append(key)
        return _Resp(self.behaviors.get(key, 200), _GEMINI_OK)


# ── backend: failover behavior ────────────────────────────────────

def test_claude_headers_without_pool_use_api_key():
    assert ClaudeBackend(api_key="direct")._headers()["x-api-key"] == "direct"


async def test_claude_fails_over_on_429():
    pool = AuthProfilePool(["k1", "k2"], "anthropic")
    b = ClaudeBackend(api_key="", auth_pool=pool)
    b.client = _ClaudeFakeClient({"k1": 429})
    out = await b.generate("m", "prompt")
    assert out == "hi"
    assert b.client.calls == ["k1", "k2"]    # rotated to the healthy key
    assert pool.current_key() == "k2"


async def test_claude_single_key_does_not_loop():
    pool = AuthProfilePool(["k1"], "anthropic")
    b = ClaudeBackend(api_key="", auth_pool=pool)
    b.client = _ClaudeFakeClient({"k1": 429})
    out = await b.generate("m", "prompt")
    assert "Claude API error" in out
    assert b.client.calls == ["k1"]          # one attempt, no failover


async def test_claude_exhausts_all_keys():
    pool = AuthProfilePool(["k1", "k2"], "anthropic")
    b = ClaudeBackend(api_key="", auth_pool=pool)
    b.client = _ClaudeFakeClient({"k1": 429, "k2": 429})
    out = await b.generate("m", "prompt")
    assert "exhausted" in out and b.client.calls == ["k1", "k2"]


async def test_claude_success_resets_failures():
    pool = AuthProfilePool(["k1", "k2"], "anthropic")
    pool.report_failure("k1")                # k1 cooling, active k2
    b = ClaudeBackend(api_key="", auth_pool=pool)
    b.client = _ClaudeFakeClient({})         # everything 200
    assert await b.generate("m", "p") == "hi"
    assert pool._find("k2").failures == 0


async def test_gemini_fails_over_on_429():
    pool = AuthProfilePool(["g1", "g2"], "gemini")
    b = GeminiBackend(api_key="", auth_pool=pool)
    b.client = _GeminiFakeClient({"g1": 429})
    out = await b.generate("gemini-2.5-flash", "prompt")
    assert out == "hi"
    assert b.client.calls == ["g1", "g2"]
