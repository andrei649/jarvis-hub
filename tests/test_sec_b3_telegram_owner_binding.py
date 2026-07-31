"""SEC-B3 — Telegram owner binding, and the pairing gate that failed open.

Adversarial audit 2026-07-25. `TelegramChannel(...)` was constructed with no
`allowed_user_ids`, so `self.allowed_users == []` and BOTH `if self.allowed_users and ...`
guards inside the channel were unreachable no-ops — the code read as guarded and was not.
The decision callback then discarded the `user_id`/`chat_id` it was handed and applied the
approval regardless.

The audit narrowed the blast radius honestly, and that narrowing is preserved in the
comments rather than argued away: the card sender has one caller and targets the configured
owner chat, and a callback query cannot be synthesised by someone who cannot see the
button. But "narrow" was a property of the surrounding wiring, not of these functions, and
approving an autonomy task is the most privileged thing a channel can do.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest


# ── the allowlist can actually be populated now ────────────────────
def test_allowlist_is_parsed_from_the_environment(monkeypatch):
    import agents.web as web

    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111, 222 ,333")
    assert web._telegram_allowed_user_ids() == [111, 222, 333]


def test_absent_allowlist_is_empty_not_an_error(monkeypatch):
    import agents.web as web

    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    assert web._telegram_allowed_user_ids() == []


def test_a_typo_drops_one_entry_rather_than_widening_the_list(monkeypatch):
    """Raising would take the bot down; ignoring the whole var would admit everyone."""
    import agents.web as web

    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111,not-an-id,333")
    assert web._telegram_allowed_user_ids() == [111, 333]


def test_the_channel_guards_are_reachable_when_ids_are_supplied():
    """The guards were dead code because the list could never be non-empty."""
    from agents.core.channels.telegram import TelegramChannel

    channel = TelegramChannel(token="t", allowed_user_ids=[42])
    assert channel.allowed_users == [42]


# ── owner binding on the decision callback ─────────────────────────
class _Autonomy:
    def __init__(self):
        self.applied = []

    async def apply_decision(self, task_id, action, decided_by=""):
        self.applied.append((task_id, action, decided_by))


class _Orch:
    def __init__(self, owner_chat="", allowed_users=None):
        self.autonomy = _Autonomy()
        self._owner_chat = owner_chat
        self.channels = {}
        if allowed_users is not None:
            channel = type("TelegramChannel", (), {"allowed_users": allowed_users})()
            self.channels = {"telegram": channel}

    def get_setting(self, key, default=None):
        return self._owner_chat if key == "autonomy.owner_chat_id" else default


def _coordinator(orch):
    from agents.core.autonomy_coordinator import AutonomyCoordinator

    coord = AutonomyCoordinator.__new__(AutonomyCoordinator)
    coord._orch = orch
    return coord


async def test_the_owner_can_approve():
    orch = _Orch(owner_chat="999", allowed_users=[42])
    result = await _coordinator(orch)._on_callback(7, "approve", chat_id=999, user_id=42)
    assert result == "Task #7: approve"
    assert orch.autonomy.applied == [(7, "approve", "telegram")]


async def test_a_stranger_in_the_owner_chat_cannot_approve():
    """The group case the audit named: right chat, wrong person."""
    orch = _Orch(owner_chat="999", allowed_users=[42])
    result = await _coordinator(orch)._on_callback(7, "approve", chat_id=999, user_id=1234)
    assert result is None
    assert orch.autonomy.applied == [], "an autonomy task was approved by a non-owner"


async def test_the_owner_in_another_chat_cannot_approve():
    orch = _Orch(owner_chat="999", allowed_users=[42])
    result = await _coordinator(orch)._on_callback(7, "approve", chat_id=555, user_id=42)
    assert result is None
    assert orch.autonomy.applied == []


async def test_no_owner_binding_configured_fails_closed():
    """An approval surface with nothing identifying the owner must not approve.

    Declining costs the owner one settings entry. Allowing costs them the guarantee that
    only they can approve — which is the whole point of the queue.
    """
    orch = _Orch(owner_chat="", allowed_users=None)
    result = await _coordinator(orch)._on_callback(7, "approve", chat_id=999, user_id=42)
    assert result is None
    assert orch.autonomy.applied == []


async def test_missing_identity_on_the_callback_fails_closed():
    orch = _Orch(owner_chat="999", allowed_users=[42])
    result = await _coordinator(orch)._on_callback(7, "approve")
    assert result is None
    assert orch.autonomy.applied == []


# ── the pairing gate ───────────────────────────────────────────────
async def test_pairing_gate_holds_the_sender_when_its_store_errors():
    """It defaulted to allowed=True — the gate admitted the sender it exists to hold.

    Reachable only for an unknown first-contact sender during a write failure (a blocked
    sender's path is in-memory and cannot raise; corrupt JSON normalises to {} and already
    fails closed). That is still exactly the sender this gate is for.
    """
    from agents.core.channels.gateway import Gateway

    class _ExplodingPairing:
        def gate_inbound(self, channel, sender, code=None):
            raise OSError("pairing store unreadable")

    handled = []

    async def _handler(text, **kwargs):
        handled.append(text)
        return "handled"

    gateway = Gateway(handler=_handler, pairing=_ExplodingPairing())
    gateway.register_channel("telegram")

    result = await gateway.route("hello", sender="stranger-1")
    assert handled == [], "an unpaired sender reached the handler through a gate error"
    assert result is None
