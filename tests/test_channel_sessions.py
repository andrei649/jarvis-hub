"""Hermes-style channel session primitives."""

from agents.core.validation import is_valid_session_id


def test_build_session_key_prefers_explicit_safe_session_id():
    from agents.core.channels.session import SessionSource, build_session_key

    source = SessionSource(channel="telegram", sender="42", explicit_session_id="session_manual")

    assert build_session_key(source) == "session_manual"


def test_build_session_key_is_filesystem_safe_for_hostile_sender():
    from agents.core.channels.session import SessionSource, build_session_key

    source = SessionSource(channel="matrix room", sender="../../secrets/token")
    key = build_session_key(source)

    assert is_valid_session_id(key)
    assert ".." not in key
    assert "secrets" not in key
    assert key.startswith("ch_matrix_room_sender_")


def test_build_session_key_uses_thread_before_sender():
    from agents.core.channels.session import SessionSource, build_session_key

    with_sender = SessionSource(channel="telegram", sender="user-1")
    with_thread = SessionSource(channel="telegram", sender="user-1", thread_id="topic-9")

    assert build_session_key(with_sender) != build_session_key(with_thread)
    assert "_thread_" in build_session_key(with_thread)


def test_delivery_router_prefers_explicit_target():
    from agents.core.channels.session import DeliveryRouter, DeliveryTarget, SessionSource

    source = SessionSource(channel="telegram", sender="42")
    explicit = DeliveryTarget(channel="email", recipient="andrei@example.test")

    decision = DeliveryRouter().resolve(source, explicit_target=explicit)

    assert decision.send is True
    assert decision.target == explicit
    assert decision.reason == "explicit-target"


def test_delivery_router_replies_to_home_channel_with_sender():
    from agents.core.channels.session import DeliveryRouter, SessionSource

    source = SessionSource(channel="telegram", sender="42")
    decision = DeliveryRouter().resolve(source)

    assert decision.send is True
    assert decision.target.channel == "telegram"
    assert decision.target.recipient == "42"
    assert decision.reason == "home-channel"


def test_delivery_router_silences_empty_or_local_only_messages():
    from agents.core.channels.session import DeliveryRouter, SessionSource

    source = SessionSource(channel="cron", local_only=True)

    assert DeliveryRouter().resolve(source, text="").send is False
    assert DeliveryRouter().resolve(source, text="status").send is False
