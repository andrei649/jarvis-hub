"""One pairing store per process — and the Telegram adapter is handed it.

``SenderPairing`` reads its file once, at construction, and every save writes the
whole in-memory state back. Two instances over one file are therefore two *stores*,
not two views of one: a deeplink spent through one is still outstanding in the other,
and the other's next save — any save; a stranger knocking is enough — writes the
spent link back to disk, where a fresh instance redeems it again. That is exactly the
"pair twice" ``redeem_deeplink`` promises never happens: it would pair whoever saw
the screen after the owner did.

Production had two. The orchestrator registers the long-lived store (the gateway
gates on it, the pairing router mints and revokes on it), and ``TelegramChannel`` —
built in ``web.py`` without one — opened a throwaway ``SenderPairing()`` per
``/start <token>``. A token redeemed over Telegram came back the moment the owner's
store next saved, and a second phone could pair with the link the first had already
used. With a relocated data root (``JARVIS_HOME``) the two did not even agree on the
file — the registry spelled a cwd-relative path, the throwaway used the data root —
and no link ever redeemed.

The fix is one instance per process *by construction*: ``web.py`` hands the gateway's
store to the channel, an un-wired channel refuses to pair rather than opening its
own, and the registry spells the path through the data root. Pinned here at the
store (the hazard), at the adapter (it uses what it was handed, and nothing else)
and at the app (the lifespan really hands it over).

Hermetic: ``tmp_path`` stores, a stubbed Telegram transport, and the real app
lifespan with the channel's network start replaced.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agents.core.channels import pairing as pairing_mod
from agents.core.channels.pairing import ALLOWED, SenderPairing
from agents.core.channels.telegram import TelegramChannel

PAIRED = "Paired. This device can now talk to Nerva."
REFUSED = "That pairing link is not valid."


def _channel(pairing=None) -> tuple[TelegramChannel, list[str]]:
    """A ``TelegramChannel`` whose transport is a list of what it said."""
    chan = TelegramChannel(token="fixture-token", pairing=pairing)
    sent: list[str] = []

    async def _send(message, chat_id=None, **_kw):
        sent.append(message)
        return True

    chan.send = _send
    return chan, sent


# ── the hazard, at the store ─────────────────────────────────────────────────

def test_premise_a_second_store_over_the_same_file_resurrects_a_spent_link(tmp_path):
    """The mechanism the wiring below exists to keep out of production.

    Recorded as a premise, not a wish: if this stops holding, the store has grown a
    defence against a second instance and the wiring is belt and braces. Until then
    the wiring is the whole guarantee, which is why the rest of this file pins it.
    """
    path = tmp_path / "sender_pairing.json"
    owner = SenderPairing(path)                     # the long-lived one (orchestrator)
    link = owner.mint_deeplink(now=0.0)

    throwaway = SenderPairing(path)                 # what the Telegram path used to build
    assert throwaway.redeem_deeplink(link["token"], "telegram", "42", now=1.0)["ok"] is True
    assert SenderPairing(path).outstanding_deeplinks(now=1.0) == 0      # spent, on disk

    owner.request("telegram", "stranger")           # ANY later save from the stale one
    assert SenderPairing(path).outstanding_deeplinks(now=1.0) == 1      # ...and it is back

    replay = SenderPairing(path).redeem_deeplink(link["token"], "telegram", "99", now=2.0)
    assert replay["ok"] is True, "premise changed: the store now survives a second instance"
    assert SenderPairing(path).status("telegram", "99") == ALLOWED


# ── the adapter uses the store it was handed, and nothing else ──────────────

async def test_a_link_spent_over_telegram_stays_spent_after_the_owner_store_saves(tmp_path):
    """The production shape, fixed: one instance, so there is no stale copy to save."""
    path = tmp_path / "sender_pairing.json"
    shared = SenderPairing(path)
    chan, sent = _channel(pairing=shared)
    # real clock: the channel path has no injectable now, exactly as in production
    link = shared.mint_deeplink()

    assert await chan._maybe_pair_deeplink(f"/start {link['token']}", 42, 1001) is True
    assert shared.status("telegram", "42") == ALLOWED
    assert sent == [PAIRED]

    shared.request("telegram", "stranger")          # the save that used to resurrect it
    assert await chan._maybe_pair_deeplink(f"/start {link['token']}", 99, 1002) is True
    assert sent[-1] == REFUSED
    assert shared.status("telegram", "99") != ALLOWED
    # and the file agrees: a process restarting here finds nothing to redeem
    assert SenderPairing(path).outstanding_deeplinks() == 0
    assert SenderPairing(path).status("telegram", "99") != ALLOWED


async def test_revoking_on_the_shared_store_reaches_the_live_telegram_adapter(tmp_path):
    """H497 gap (c), for the deeplink path: the HUD's revoke button acts on the same
    object the adapter redeems from, so there is no second copy a link survives in."""
    shared = SenderPairing(tmp_path / "sender_pairing.json")
    chan, sent = _channel(pairing=shared)
    link = shared.mint_deeplink()

    assert shared.revoke_deeplinks() == 1
    assert await chan._maybe_pair_deeplink(f"/start {link['token']}", 42, 1001) is True
    assert sent == [REFUSED]
    assert shared.status("telegram", "42") != ALLOWED


async def test_an_unwired_channel_refuses_rather_than_opening_its_own_store(
    monkeypatch, tmp_path, caplog,
):
    """No store handed in → no pairing, and no ``SenderPairing()`` built on the side.

    A throwaway over the data root is the bug itself, so the un-wired case fails
    closed: same reply as a bad token (the sender learns nothing), a log line that
    says why, and the message still swallowed — the payload is a would-be credential.
    """
    built: list[object] = []
    real_init = SenderPairing.__init__

    def _recording_init(self, path=pairing_mod.DEFAULT_PATH):
        built.append(path)
        real_init(self, tmp_path / "never.json")    # off the data root either way

    monkeypatch.setattr(SenderPairing, "__init__", _recording_init)
    chan, sent = _channel()                         # nothing handed in

    with caplog.at_level(logging.DEBUG):
        handled = await chan._maybe_pair_deeplink("/start some-token-value", 42, 1001)

    assert handled is True
    assert sent == [REFUSED]
    assert built == [], "the adapter opened its own SenderPairing"
    assert "some-token-value" not in caplog.text
    assert any("no shared pairing store" in rec.getMessage() for rec in caplog.records)


# ── the app really hands it over ────────────────────────────────────────────

def test_the_app_hands_the_telegram_channel_the_orchestrators_store(monkeypatch):
    """``web.py``'s lifespan: the channel's store IS ``orch.sender_pairing`` — the
    object the gateway gates on and the pairing router mints from — and it lives
    under the data root, where a relocated install keeps everything else."""
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.paths import data_path
    from agents.core.routers.pairing import _get_sender_pairing

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:fixture-token")
    # default-on pairing is the guard that lets a bot with no allowlist boot at all
    monkeypatch.delenv("JARVIS_CHANNEL_PAIRING", raising=False)
    monkeypatch.delenv("JARVIS_CHANNEL_OPEN", raising=False)
    started: list[str] = []

    async def _start(self):
        started.append(self.channel_id)             # no getMe, no long-poll: wiring only

    monkeypatch.setattr(TelegramChannel, "start", _start)

    assert web.orch is None, "orchestrator should not exist before startup"
    with TestClient(web.app):
        orch = web.orch
        assert started == ["telegram"]
        telegram = orch.channels["telegram"]
        assert orch.sender_pairing is not None
        assert telegram._pairing is orch.sender_pairing
        assert web.gateway.pairing is orch.sender_pairing
        assert _get_sender_pairing() is orch.sender_pairing
        # one file, spelled through the data root on both sides
        store_path = Path(orch.sender_pairing.path).resolve()
        assert store_path == data_path("sender_pairing.json").resolve()
        assert store_path == Path(pairing_mod.DEFAULT_PATH).resolve()
        assert store_path.is_relative_to(Path(os.environ["JARVIS_HOME"]).resolve())
    assert web.orch is None, "lifespan shutdown did not release the orchestrator"
