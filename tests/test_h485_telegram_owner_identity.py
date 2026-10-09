"""Trusted Telegram sender identity for owner-scoped decisions."""

import pytest

from agents.core.telegram_owner import is_telegram_owner_sender, telegram_owner_user_ids


@pytest.mark.parametrize("container", [list, tuple, set, frozenset])
def test_explicit_owner_membership_is_independent_of_chat_destination(container):
    owners = container([42, "84"])
    assert is_telegram_owner_sender(42, chat_id=-900, owner_chat_id=-800,
                                    allowed_user_ids=owners)
    assert is_telegram_owner_sender("84", chat_id=None, owner_chat_id=None,
                                    allowed_user_ids=owners)
    assert not is_telegram_owner_sender(85, chat_id=84, owner_chat_id=84,
                                        allowed_user_ids=owners)


@pytest.mark.parametrize("allowed", [None, [], (), set(), frozenset()])
def test_empty_owner_list_allows_only_exact_private_chat_identity(allowed):
    assert is_telegram_owner_sender(42, chat_id=42, owner_chat_id="42",
                                    allowed_user_ids=allowed)
    assert not is_telegram_owner_sender(42, chat_id=-42, owner_chat_id=-42,
                                        allowed_user_ids=allowed)
    assert not is_telegram_owner_sender(42, chat_id=43, owner_chat_id=42,
                                        allowed_user_ids=allowed)
    assert not is_telegram_owner_sender(43, chat_id=42, owner_chat_id=42,
                                        allowed_user_ids=allowed)


@pytest.mark.parametrize("user_id", [None, True, False, 0, -1, 1.0, "01", "+1",
                                       " 1", "1 ", "١", "１", "1.0", "", 0x10000000000])
def test_malformed_sender_never_authorizes(user_id):
    assert not is_telegram_owner_sender(user_id, chat_id=1, owner_chat_id=1,
                                        allowed_user_ids=[user_id])


@pytest.mark.parametrize("allowed", [["bad"], [False], [0], [0x10000000000],
                                         "42", {"42": True}, 42])
def test_nonempty_invalid_or_wrong_container_never_becomes_private_fallback(allowed):
    assert not is_telegram_owner_sender(42, chat_id=42, owner_chat_id=42,
                                        allowed_user_ids=allowed)


def test_valid_entries_survive_a_typo_without_widening_fallback():
    assert is_telegram_owner_sender("42", chat_id=-99, owner_chat_id=-99,
                                    allowed_user_ids=["bad", "42", True])
    assert not is_telegram_owner_sender(43, chat_id=43, owner_chat_id=43,
                                        allowed_user_ids=["bad", "42", True])


def test_bot_api_user_id_bounds_are_inclusive():
    maximum = 0xffffffffff
    assert is_telegram_owner_sender(1, chat_id=1, owner_chat_id=1,
                                    allowed_user_ids=None)
    assert is_telegram_owner_sender(str(maximum), chat_id=maximum,
                                    owner_chat_id=str(maximum), allowed_user_ids=())
    assert not is_telegram_owner_sender(str(maximum + 1), chat_id=maximum + 1,
                                        owner_chat_id=maximum + 1, allowed_user_ids=None)


@pytest.mark.parametrize("bad_chat", [None, True, 1.0, "01", "+1", "١", 0, -1,
                                         0x10000000000])
def test_private_fallback_requires_canonical_positive_chat_ids(bad_chat):
    assert not is_telegram_owner_sender(1, chat_id=bad_chat, owner_chat_id=1,
                                        allowed_user_ids=[])
    assert not is_telegram_owner_sender(1, chat_id=1, owner_chat_id=bad_chat,
                                        allowed_user_ids=[])


@pytest.mark.parametrize("configured", [[99], "[99]"])
def test_configured_owner_is_independent_of_ingress_allowlist(configured):
    owners = telegram_owner_user_ids(configured, allowed_user_ids=[])
    assert is_telegram_owner_sender(99, chat_id=-50, owner_chat_id=-50,
                                    allowed_user_ids=owners)
    assert not is_telegram_owner_sender(50, chat_id=-50, owner_chat_id=-50,
                                        allowed_user_ids=owners)


def test_absent_owner_config_uses_legacy_ingress_list_or_private_fallback():
    legacy = [42]
    assert telegram_owner_user_ids(None, allowed_user_ids=legacy) is legacy
    assert is_telegram_owner_sender(42, chat_id=-5, owner_chat_id=-5,
                                    allowed_user_ids=legacy)
    empty = telegram_owner_user_ids(None, allowed_user_ids=[])
    assert is_telegram_owner_sender(42, chat_id=42, owner_chat_id=42,
                                    allowed_user_ids=empty)


@pytest.mark.parametrize("configured", ["", " ", "[", "null", "99", "{}", '"99"',
                                              99, True, {"owners": [99]}])
def test_malformed_explicit_config_never_falls_back_to_legacy_or_private(configured):
    owners = telegram_owner_user_ids(configured, allowed_user_ids=[99])
    assert owners is not None
    assert not is_telegram_owner_sender(99, chat_id=99, owner_chat_id=99,
                                        allowed_user_ids=owners)


@pytest.mark.parametrize("configured", [[], (), set(), frozenset(), "[]"])
def test_explicit_empty_owner_list_disables_legacy_but_keeps_exact_private_fallback(configured):
    owners = telegram_owner_user_ids(configured, allowed_user_ids=[99])
    assert not is_telegram_owner_sender(99, chat_id=-99, owner_chat_id=-99,
                                        allowed_user_ids=owners)
    assert is_telegram_owner_sender(99, chat_id=99, owner_chat_id=99,
                                    allowed_user_ids=owners)


@pytest.mark.parametrize("configured", [["bad", 99], '["bad",99]'])
def test_mixed_config_keeps_valid_owner_without_private_fallback(configured):
    owners = telegram_owner_user_ids(configured, allowed_user_ids=[42])
    assert is_telegram_owner_sender(99, chat_id=-7, owner_chat_id=-7,
                                    allowed_user_ids=owners)
    assert not is_telegram_owner_sender(42, chat_id=42, owner_chat_id=42,
                                        allowed_user_ids=owners)
