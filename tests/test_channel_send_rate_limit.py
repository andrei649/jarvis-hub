"""0.44 — per-channel OUTBOUND send rate limits (opt-in, default-off).

Bounds how much an external webhook channel can broadcast. Off by default
(unlimited); a per-channel or global env cap turns it on. The interactive reply
path is intentionally out of scope (never drop a user reply).
"""

from pathlib import Path

import pytest

from agents.core.channels import send_rate_limit as srl
from agents.core.channels.send_rate_limit import SendRateLimiter, limit_for


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("JARVIS_CHANNEL_SEND_RATE", raising=False)
    monkeypatch.delenv("JARVIS_CHANNEL_SEND_RATES", raising=False)
    srl.reset()
    yield
    srl.reset()


# ── config parsing ────────────────────────────────────────────────────────────
def test_default_is_unlimited():
    assert limit_for("whatsapp") == 0


def test_global_cap_applies_to_all(monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATE", "5")
    assert limit_for("whatsapp") == 5 and limit_for("teams") == 5


def test_per_channel_override_beats_global(monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATE", "5")
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATES", "whatsapp:2, teams:30 ,junk,bad:x")
    assert limit_for("whatsapp") == 2     # override
    assert limit_for("teams") == 30       # override
    assert limit_for("signal") == 5       # falls back to global
    assert limit_for("bad") == 5          # unparseable entry ignored → global


def test_malformed_global_cap_is_unlimited(monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATE", "banana")
    assert limit_for("whatsapp") == 0
    assert srl.configured_rates()[0] == 0
    assert srl.status_snapshot()["enabled"] is False


def test_negative_global_cap_is_unlimited(monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATE", "-4")
    assert limit_for("whatsapp") == 0
    assert srl.configured_rates()[0] == 0
    assert srl.status_snapshot()["enabled"] is False


def test_global_channel_send_rate_uses_env_int():
    src = (Path(__file__).resolve().parents[1]
           / "agents/core/channels/send_rate_limit.py").read_text(encoding="utf-8")
    assert 'env_int("JARVIS_CHANNEL_SEND_RATE"' in src
    assert 'int(os.environ.get("JARVIS_CHANNEL_SEND_RATE"' not in src


# ── limiter mechanics ─────────────────────────────────────────────────────────
def test_unlimited_never_blocks_and_records_nothing():
    lim = SendRateLimiter()
    for _ in range(1000):
        assert lim.allow("whatsapp") is True
    assert lim._hits == {}                # allocation-free on the default path


def test_cap_blocks_after_n_within_window(monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATES", "whatsapp:3")
    lim = SendRateLimiter()
    assert [lim.allow("whatsapp") for _ in range(4)] == [True, True, True, False]
    # a different channel has its own independent budget
    assert lim.allow("teams") is True


def test_window_slides_so_old_hits_expire(monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATES", "whatsapp:2")
    lim = SendRateLimiter(window=60.0)
    assert lim.allow("whatsapp", now=0.0) is True
    assert lim.allow("whatsapp", now=1.0) is True
    assert lim.allow("whatsapp", now=2.0) is False     # full within the 60s window
    assert lim.allow("whatsapp", now=61.0) is True     # first hit aged out → room again


# ── integration: WebhookChannel.send honors the limit ─────────────────────────
class _FakeTransport:
    def __init__(self):
        self.calls = 0

    async def request(self, method, url, headers=None, json=None):
        self.calls += 1
        class _R:
            def raise_for_status(self_inner):
                return None
        return _R()


@pytest.mark.asyncio
async def test_webhook_send_is_rate_limited(monkeypatch):
    from agents.core.channels.webhook_channels import WhatsAppChannel
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATES", "whatsapp:2")
    srl.reset()
    transport = _FakeTransport()
    ch = WhatsAppChannel(config={"phone_id": "PH", "token": "tok"}, transport=transport)
    r1 = await ch.send("a", to="15551112222")
    r2 = await ch.send("b", to="15551112222")
    r3 = await ch.send("c", to="15551112222")          # over the cap
    assert (r1, r2, r3) == (True, True, False)
    assert transport.calls == 2                         # the 3rd never hit the network


@pytest.mark.asyncio
async def test_webhook_send_unlimited_by_default(monkeypatch):
    from agents.core.channels.webhook_channels import WhatsAppChannel
    srl.reset()
    transport = _FakeTransport()
    ch = WhatsAppChannel(config={"phone_id": "PH", "token": "tok"}, transport=transport)
    for _ in range(10):
        assert await ch.send("x", to="15551112222") is True
    assert transport.calls == 10                        # default: nothing dropped


# ── read surface: snapshot / status_snapshot ───────────────────────────────────
def test_snapshot_is_a_pure_view(monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATES", "whatsapp:5")
    lim = SendRateLimiter(window=60.0)
    # snapshot counts only live hits and never mutates state / affects allow()
    assert lim.snapshot(now=0.0) == {}
    lim.allow("whatsapp", now=0.0)
    lim.allow("whatsapp", now=1.0)
    assert lim.snapshot(now=2.0) == {"whatsapp": 2}
    assert lim.snapshot(now=61.0) == {}            # both aged out of the 60s window
    # a pure view: calling it didn't consume budget
    assert lim.allow("whatsapp", now=2.0) is True


def test_status_snapshot_disabled_by_default():
    s = srl.status_snapshot()
    assert s["enabled"] is False
    assert s["global_cap"] == 0
    assert s["channels"] == []
    assert s["window_seconds"] == 60


def test_status_snapshot_reports_caps_and_usage(monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATE", "20")
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATES", "whatsapp:3")
    srl.reset()
    assert srl.allow_send("whatsapp") is True
    assert srl.allow_send("whatsapp") is True
    s = srl.status_snapshot()
    assert s["enabled"] is True and s["global_cap"] == 20
    wa = next(c for c in s["channels"] if c["channel"] == "whatsapp")
    assert wa["cap"] == 3 and wa["used"] == 2 and wa["remaining"] == 1


def test_status_snapshot_unlimited_channel_has_null_remaining(monkeypatch):
    # a per-channel entry of 0 = unlimited for that channel → remaining is null,
    # but a positive global cap still makes the surface "enabled".
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATE", "10")
    monkeypatch.setenv("JARVIS_CHANNEL_SEND_RATES", "teams:0")
    srl.reset()
    s = srl.status_snapshot()
    teams = next(c for c in s["channels"] if c["channel"] == "teams")
    assert teams["cap"] == 0 and teams["remaining"] is None
