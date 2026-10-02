"""A reviewed image destination belongs to one prompt, session and route."""

import pytest

from agents.core.llm.vision_review import VisionReviewRefused, VisionReviewStore


def _issue(store, *, session="session-a", prompt="What is shown?", route="local"):
    return store.issue(
        session_id=session,
        agent_id="jarvis",
        prompt=prompt,
        model="vision-model",
        route=route,
        binding=("lm-studio", "http://127.0.0.1:1234/v1", "vision-model", "secret-key"),
    )


def _consume(store, token, *, session="session-a", prompt="What is shown?",
             route="local", binding=None):
    store.consume(
        token,
        session_id=session,
        agent_id="jarvis",
        prompt=prompt,
        model="vision-model",
        route=route,
        binding=binding or ("lm-studio", "http://127.0.0.1:1234/v1", "vision-model", "secret-key"),
    )


def test_changed_route_or_credential_refuses_and_burns_review():
    store = VisionReviewStore()
    token = _issue(store)
    with pytest.raises(VisionReviewRefused, match="vlm_destination_changed"):
        _consume(store, token, binding=("lm-studio", "http://127.0.0.1:1234/v1", "vision-model", "rotated-key"))
    with pytest.raises(VisionReviewRefused, match="vlm_review_unavailable"):
        _consume(store, token)

    token = _issue(store)
    with pytest.raises(VisionReviewRefused, match="vlm_destination_changed"):
        _consume(store, token, route="cloud-compatible")


def test_cross_session_or_changed_prompt_cannot_use_review():
    store = VisionReviewStore()
    token = _issue(store)
    with pytest.raises(VisionReviewRefused, match="vlm_destination_changed"):
        _consume(store, token, session="session-b")
    token = _issue(store)
    with pytest.raises(VisionReviewRefused, match="vlm_destination_changed"):
        _consume(store, token, prompt="What is behind it?")


def test_review_is_single_use_and_cancel_removes_it():
    store = VisionReviewStore()
    token = _issue(store)
    _consume(store, token)
    with pytest.raises(VisionReviewRefused, match="vlm_review_unavailable"):
        _consume(store, token)
    token = _issue(store)
    store.cancel(token, session_id="session-a")
    with pytest.raises(VisionReviewRefused, match="vlm_review_unavailable"):
        _consume(store, token)


def test_expired_review_refuses_and_releases_capacity():
    now = [100.0]
    store = VisionReviewStore(clock=lambda: now[0], ttl_seconds=30, max_pending=1)
    token = _issue(store)
    with pytest.raises(VisionReviewRefused, match="vlm_review_capacity"):
        _issue(store)
    now[0] = 131.0
    with pytest.raises(VisionReviewRefused, match="vlm_review_expired"):
        _consume(store, token)
    _issue(store)


def test_review_representation_never_contains_prompt_or_credential():
    store = VisionReviewStore()
    token = _issue(store)
    displayed = repr(store)
    assert token not in displayed
    assert "What is shown?" not in displayed
    assert "secret-key" not in displayed
