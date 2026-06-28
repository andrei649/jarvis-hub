"""0.44 — per-channel OUTBOUND send rate limits (opt-in, default-off).

Bounds how much an external webhook channel can broadcast. Off by default
(unlimited); a per-channel or global env cap turns it on. The interactive reply
path is intentionally out of scope (never drop a user reply).
"""

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
