"""Deeplink pairing — the 60-second path, and why it is safe to make it that easy.

Copying a code between two devices is where people give up, so the product hands
the owner a link they tap on their phone. That convenience is only acceptable
because the token behaves like a credential, and these tests pin exactly that:

  · **one use, ever** — a link that paired twice would pair whoever saw the screen
    after the owner did;
  · it **expires in minutes**, so a screenshot in a chat log is worthless tomorrow;
  · wrong, spent and expired are **indistinguishable** from outside — telling them
    apart tells a guesser which it was;
  · a token minted for one channel cannot pair another;
  · the token **never reaches the orchestrator, the transcript or a log line** —
    the `/start` message is swallowed, because until it is spent it is live.

Hermetic: a tmp_path store, an injected clock, and a fake Telegram transport.
"""

from __future__ import annotations

import logging

import pytest

from agents.core.channels.pairing import (
    ALLOWED,
    DEEPLINK_TTL_SECONDS,
    PENDING,
    SenderPairing,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def pairing(tmp_path):
    return SenderPairing(tmp_path / "pairing.json")


# ── the token behaves like a credential ──────────────────────────────────────

async def test_a_link_pairs_the_first_sender_to_use_it(pairing):
    link = pairing.mint_deeplink(now=0.0)
    result = pairing.redeem_deeplink(link["token"], "telegram", "42", now=1.0)
    assert result["ok"] is True
    assert pairing.status("telegram", "42") == ALLOWED


async def test_a_link_is_dead_after_one_use(pairing):
    """A link that paired twice would pair whoever saw the screen next."""
    link = pairing.mint_deeplink(now=0.0)
    assert pairing.redeem_deeplink(link["token"], "telegram", "42", now=1.0)["ok"] is True
    replay = pairing.redeem_deeplink(link["token"], "telegram", "99", now=2.0)
    assert replay["ok"] is False
    assert pairing.status("telegram", "99") != ALLOWED


async def test_a_link_expires(pairing):
    link = pairing.mint_deeplink(now=0.0)
    late = pairing.redeem_deeplink(
        link["token"], "telegram", "42", now=DEEPLINK_TTL_SECONDS + 1
    )
    assert late["ok"] is False
    assert pairing.status("telegram", "42") != ALLOWED


async def test_the_default_ttl_is_minutes_not_days(pairing):
    """Long enough to walk to your phone; short enough that a screenshot rots."""
    assert 60.0 <= DEEPLINK_TTL_SECONDS <= 900.0


async def test_wrong_spent_and_expired_are_indistinguishable(pairing):
    """Telling them apart tells a guesser which one it was."""
    spent = pairing.mint_deeplink(now=0.0)
    pairing.redeem_deeplink(spent["token"], "telegram", "1", now=1.0)
    expired = pairing.mint_deeplink(now=0.0)

    reasons = {
        pairing.redeem_deeplink("never-existed", "telegram", "2", now=2.0)["reason"],
        pairing.redeem_deeplink(spent["token"], "telegram", "3", now=2.0)["reason"],
        pairing.redeem_deeplink(
            expired["token"], "telegram", "4", now=DEEPLINK_TTL_SECONDS + 1
        )["reason"],
    }
    assert reasons == {"invalid_or_expired_token"}


async def test_a_token_minted_for_one_channel_cannot_pair_another(pairing):
    link = pairing.mint_deeplink("telegram", now=0.0)
    result = pairing.redeem_deeplink(link["token"], "discord", "42", now=1.0)
    assert result["ok"] is False
    assert result["reason"] == "wrong_channel"
    assert pairing.status("discord", "42") != ALLOWED


async def test_an_empty_token_is_refused_without_touching_the_store(pairing):
    pairing.mint_deeplink(now=0.0)
    assert pairing.redeem_deeplink("", "telegram", "42")["reason"] == "no_token"
    assert pairing.redeem_deeplink(None, "telegram", "42")["reason"] == "no_token"
    assert pairing.outstanding_deeplinks(now=1.0) == 1


async def test_tokens_are_unguessable_and_unique(pairing):
    tokens = {pairing.mint_deeplink(now=0.0)["token"] for _ in range(10)}
    assert len(tokens) == 10
    assert all(len(t) >= 32 for t in tokens)


# ── minting is bounded and revocable ─────────────────────────────────────────

async def test_outstanding_links_are_counted_but_never_returned(pairing):
    """The count is useful; handing the tokens back would defeat the point of
    returning each one exactly once."""
    # real clock: summary() has no injectable now, and neither does production
    pairing.mint_deeplink()
    pairing.mint_deeplink()
    assert pairing.outstanding_deeplinks() == 2
    assert "token" not in pairing.summary()
    assert pairing.summary()["deeplinks_outstanding"] == 2


async def test_expired_links_stop_counting(pairing):
    pairing.mint_deeplink(now=0.0)
    assert pairing.outstanding_deeplinks(now=DEEPLINK_TTL_SECONDS + 1) == 0


async def test_revoking_kills_every_outstanding_link(pairing):
    """The button for "I pasted that in the wrong window"."""
    a = pairing.mint_deeplink(now=0.0)
    pairing.mint_deeplink(now=0.0)
    assert pairing.revoke_deeplinks() == 2
    assert pairing.redeem_deeplink(a["token"], "telegram", "42", now=1.0)["ok"] is False


async def test_minting_is_bounded_and_drops_the_oldest(pairing):
    first = pairing.mint_deeplink(now=0.0)
    for i in range(1, 25):
        pairing.mint_deeplink(now=float(i))
    assert pairing.outstanding_deeplinks(now=30.0) <= 20
    # the oldest was dropped, not the newest
    assert pairing.redeem_deeplink(first["token"], "telegram", "1", now=30.0)["ok"] is False


async def test_links_survive_a_restart(tmp_path):
    path = tmp_path / "pairing.json"
    link = SenderPairing(path).mint_deeplink(now=0.0)
    reopened = SenderPairing(path)
    assert reopened.redeem_deeplink(link["token"], "telegram", "42", now=1.0)["ok"] is True


# ── the Telegram side ────────────────────────────────────────────────────────

class _Chan:
    """The `/start` handling, lifted off TelegramChannel without its transport."""

    def __init__(self, pairing):
        self._pairing = pairing
        self.sent: list[tuple[str, int]] = []

    async def send(self, message, chat_id=None, **_kw):
        self.sent.append((message, chat_id))
        return True

    _maybe_pair_deeplink = None  # bound below


def _channel(pairing):
    from agents.core.channels.telegram import TelegramChannel

    chan = _Chan(pairing)
    chan._maybe_pair_deeplink = TelegramChannel._maybe_pair_deeplink.__get__(chan)
    return chan


async def test_a_start_deeplink_pairs_and_never_reaches_the_orchestrator(pairing):
    """Until it is spent the payload is live, so it must not be forwarded."""
    # minted on the real clock: the channel path has no injectable now, exactly
    # as in production, so a fixture pinned to epoch 0 would arrive expired
    link = pairing.mint_deeplink()
    chan = _channel(pairing)
    handled = await chan._maybe_pair_deeplink(f"/start {link['token']}", 42, 1001)
    assert handled is True  # swallowed — the caller does NOT forward it
    assert pairing.status("telegram", "42") == ALLOWED
    assert chan.sent[0][0] == "Paired. This device can now talk to Nerva."


async def test_the_token_never_appears_in_a_log_line(pairing, caplog):
    link = pairing.mint_deeplink()
    chan = _channel(pairing)
    with caplog.at_level(logging.DEBUG):
        await chan._maybe_pair_deeplink(f"/start {link['token']}", 42, 1001)
    assert link["token"] not in caplog.text


async def test_the_token_never_appears_in_the_reply(pairing):
    link = pairing.mint_deeplink()
    chan = _channel(pairing)
    await chan._maybe_pair_deeplink(f"/start {link['token']}", 42, 1001)
    assert all(link["token"] not in msg for msg, _ in chan.sent)


async def test_a_bare_start_is_an_ordinary_message(pairing):
    """No payload is not a pairing attempt; swallowing it would break /start."""
    chan = _channel(pairing)
    assert await chan._maybe_pair_deeplink("/start", 42, 1001) is False
    assert await chan._maybe_pair_deeplink("/start   ", 42, 1001) is False
    assert chan.sent == []


async def test_an_ordinary_message_is_untouched(pairing):
    chan = _channel(pairing)
    assert await chan._maybe_pair_deeplink("what is on my calendar", 42, 1001) is False
    assert chan.sent == []


async def test_a_bad_token_is_swallowed_too_and_says_nothing_useful(pairing):
    """Still swallowed: a failed attempt carries a would-be credential as well."""
    chan = _channel(pairing)
    handled = await chan._maybe_pair_deeplink("/start not-a-real-token", 42, 1001)
    assert handled is True
    assert chan.sent[0][0] == "That pairing link is not valid."
    assert pairing.status("telegram", "42") != ALLOWED


async def test_a_store_failure_never_leaks_through_an_exception_path(pairing, caplog):
    class _Broken:
        def redeem_deeplink(self, token, *a, **k):
            raise RuntimeError(f"database is locked while redeeming {token}")

    chan = _channel(_Broken())
    with caplog.at_level(logging.DEBUG):
        handled = await chan._maybe_pair_deeplink("/start secret-token-value", 42, 1001)
    assert handled is True
    assert chan.sent[0][0] == "That pairing link is not valid."
    assert "secret-token-value" not in caplog.text


async def test_pairing_a_previously_pending_sender_promotes_them(pairing, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "1")
    pairing.request("telegram", "42")
    assert pairing.status("telegram", "42") == PENDING
    link = pairing.mint_deeplink()
    chan = _channel(pairing)
    await chan._maybe_pair_deeplink(f"/start {link['token']}", 42, 1001)
    assert pairing.status("telegram", "42") == ALLOWED
