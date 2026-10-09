"""Per-image-turn selection confirmations on the real composer HTTP path."""

import json
from types import SimpleNamespace

import pytest

from agents.core.llm import cost_estimator, vlm
from agents.core.llm import selection_guards as sg
from tests.test_composer_vision import DESCRIBE, PNG, STATUS
from tests.test_h277_openrouter_vision_consumer import approved_body, route, setting  # noqa: F401


@pytest.fixture
def audit(route, monkeypatch):
    state = SimpleNamespace(events=[], fail=False)

    class Audit:
        def log(self, event):
            if state.fail:
                raise OSError("private audit diagnostics")
            state.events.append(event)

    monkeypatch.setattr(sg, "_orch", lambda: SimpleNamespace(audit=Audit()))
    return state


def test_unchallenged_status_and_post_keep_old_shape(route):
    body = approved_body(route)
    assert "selection_requirements" not in route.client.get(STATUS).json()
    assert route.client.post(DESCRIBE, json=body).status_code == 200
    assert len(route.sent) == 1


def test_training_requirement_is_disclosed_and_missing_flag_refuses_before_io(route, audit):
    setting("openrouter_data_collection", "allow")
    body = approved_body(route)
    status = route.client.get(STATUS).json()
    assert status["selection_requirements"] == [{
        "needs": "acknowledge_training",
        "message": "OpenRouter may then send your prompts to upstream providers that store or train on them "
                   "(llm.openrouter_data_collection=allow)",
    }]
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 409
    assert response.json()["needs"] == ["acknowledge_training"]
    assert not route.sent and not audit.events


@pytest.mark.parametrize("name,flag", [
    ("acknowledge_training", 1), ("acknowledge_training", "true"),
    ("confirm_expensive", 1), ("confirm_expensive", "true"),
])
def test_selection_flags_require_literal_json_booleans(route, audit, name, flag):
    setting("openrouter_data_collection", "allow")
    body = approved_body(route)
    response = route.client.post(DESCRIBE, json={**body, name: flag})
    assert response.status_code == 422
    assert not route.sent and not audit.events


def test_training_consent_is_audited_before_client_and_allows_one_turn(route, audit, monkeypatch):
    setting("openrouter_data_collection", "allow")
    body = approved_body(route)
    original = vlm.VLMBackend

    def backend(*args, **kwargs):
        assert [event.action_taken for event in audit.events] == ["model_training_consent"]
        return original(*args, **kwargs)

    monkeypatch.setattr(vlm, "VLMBackend", backend)
    response = route.client.post(DESCRIBE, json={**body, "acknowledge_training": True})
    assert response.status_code == 200, response.text
    assert len(route.sent) == 1
    assert json.loads(route.sent[0].content)["provider"]["data_collection"] == "allow"
    assert route.client.post(DESCRIBE, json=body).status_code == 409
    assert len(route.sent) == 1


def test_required_training_audit_failure_refuses_without_private_diagnostics_or_io(route, audit, monkeypatch):
    setting("openrouter_data_collection", "allow")
    body = approved_body(route)
    audit.fail = True
    monkeypatch.setattr(vlm, "VLMBackend", lambda **kwargs: pytest.fail("client constructed"))
    response = route.client.post(DESCRIBE, json={**body, "acknowledge_training": True})
    assert response.status_code == 503
    assert response.json()["reason"] == "vlm_selection_audit_failed"
    assert "private audit diagnostics" not in response.text
    assert not route.sent


def test_price_and_threshold_are_bound_to_disclosure(route, audit, monkeypatch):
    monkeypatch.setitem(cost_estimator.MODELS, "vision", {"input": 1, "output": 50})
    body = approved_body(route)
    status = route.client.get(STATUS).json()
    assert [item["needs"] for item in status["selection_requirements"]] == ["confirm_expensive"]
    assert "$50/M output" in status["selection_requirements"][0]["message"]
    assert route.client.post(DESCRIBE, json=body).status_code == 409
    assert not route.sent
    assert route.client.post(DESCRIBE, json={**body, "confirm_expensive": True}).status_code == 200
    assert len(route.sent) == 1
    assert [event.action_taken for event in audit.events] == ["model_cost_confirmed"]
    monkeypatch.setitem(cost_estimator.MODELS, "vision", {"input": 2, "output": 50})
    assert route.client.post(DESCRIBE, json={**body, "confirm_expensive": True}).status_code == 409
    assert len(route.sent) == 1


def test_both_findings_need_independent_flags_and_audit(route, audit, monkeypatch):
    monkeypatch.setitem(cost_estimator.MODELS, "vision", {"input": 1, "output": 50})
    setting("openrouter_data_collection", "allow")
    body = approved_body(route)
    requirements = route.client.get(STATUS).json()["selection_requirements"]
    assert {item["needs"] for item in requirements} == {"acknowledge_training", "confirm_expensive"}
    for partial in ({"acknowledge_training": True}, {"confirm_expensive": True}):
        response = route.client.post(DESCRIBE, json={**body, **partial})
        assert response.status_code == 409
        assert len(response.json()["needs"]) == 1
    assert not route.sent and not audit.events
    response = route.client.post(DESCRIBE, json={**body, "acknowledge_training": True,
                                                 "confirm_expensive": True})
    assert response.status_code == 200, response.text
    assert {event.action_taken for event in audit.events} == {
        "model_training_consent", "model_cost_confirmed"}
    assert len(route.sent) == 1


def test_threshold_change_after_preview_revokes_confirmed_cost(route, audit, monkeypatch):
    monkeypatch.setitem(cost_estimator.MODELS, "vision", {"input": 1, "output": 50})
    body = approved_body(route)
    setting("cost_confirm_usd_per_mtok", 41)
    response = route.client.post(DESCRIBE, json={**body, "confirm_expensive": True})
    assert response.status_code == 409, response.text
    assert not route.sent and not audit.events


def test_cost_audit_remains_best_effort(route, audit, monkeypatch):
    monkeypatch.setitem(cost_estimator.MODELS, "vision", {"input": 1, "output": 50})
    body = approved_body(route)
    audit.fail = True
    response = route.client.post(DESCRIBE, json={**body, "confirm_expensive": True})
    assert response.status_code == 200, response.text
    assert len(route.sent) == 1


@pytest.mark.parametrize("mutation", ["price", "threshold"])
def test_confirmed_cost_change_at_final_http_hook_refuses(route, audit, monkeypatch, mutation):
    monkeypatch.setitem(cost_estimator.MODELS, "vision", {"input": 1, "output": 50})
    body = approved_body(route)

    def mutate(request):
        if mutation == "price":
            monkeypatch.setitem(cost_estimator.MODELS, "vision", {"input": 2, "output": 50})
        else:
            setting("cost_confirm_usd_per_mtok", 41)

    route.after_gate = mutate
    response = route.client.post(DESCRIBE, json={**body, "confirm_expensive": True})
    assert response.status_code == 409, response.text
    assert not route.sent
    assert [event.action_taken for event in audit.events] == ["model_cost_confirmed"]


def test_generic_remote_cost_confirmation_has_final_hook_without_retry(route, audit, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", "https://synthetic.invalid/v1")
    monkeypatch.setenv("JARVIS_ROLE_VISION_KEY", "synthetic-compatible-key")
    monkeypatch.setitem(cost_estimator.MODELS, "vision", {"input": 1, "output": 50})
    status = route.client.get(STATUS).json()
    assert status["configured"] and status["backend"] == "custom"
    assert [item["needs"] for item in status["selection_requirements"]] == ["confirm_expensive"]
    body = {"prompt": "What is shown?", "images": [PNG], "remote_ack": True,
            "expected_destination": status["destination"], "expected_binding": status["binding"],
            "confirm_expensive": True}

    def mutate(request):
        monkeypatch.setitem(cost_estimator.MODELS, "vision", {"input": 2, "output": 50})

    route.after_gate = mutate
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 409, response.text
    assert not route.sent


@pytest.mark.parametrize("retry", ["0", "1"])
def test_confirmed_training_change_at_final_http_hook_refuses(route, audit, monkeypatch, retry):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", retry)
    setting("openrouter_data_collection", "allow")
    body = approved_body(route)
    route.after_gate = lambda request: setting("openrouter_data_collection", "deny")
    response = route.client.post(DESCRIBE, json={**body, "acknowledge_training": True})
    assert response.status_code == 409, response.text
    assert not route.sent


def test_confirmed_training_change_during_cleanup_refuses(route, audit, monkeypatch):
    setting("openrouter_data_collection", "allow")
    body = approved_body(route)
    original = vlm.VLMBackend

    class Backend(original):
        async def aclose(self):
            setting("openrouter_data_collection", "deny")
            await super().aclose()

    monkeypatch.setattr(vlm, "VLMBackend", Backend)
    response = route.client.post(DESCRIBE, json={**body, "acknowledge_training": True})
    assert response.status_code == 409, response.text
    assert len(route.sent) == 1


def test_confirmed_training_retry_rechecks_each_request(route, audit, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    setting("openrouter_data_collection", "allow")
    route.empty_first = True
    body = approved_body(route)
    calls = 0

    def mutate_on_retry(request):
        nonlocal calls
        calls += 1
        if calls == 2:
            setting("openrouter_data_collection", "deny")

    route.after_gate = mutate_on_retry
    response = route.client.post(DESCRIBE, json={**body, "acknowledge_training": True})
    assert response.status_code == 409, response.text
    assert len(route.sent) == 1


def test_confirmed_training_empty_retry_succeeds_with_same_wire(route, audit, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    setting("openrouter_data_collection", "allow")
    route.empty_first = True
    body = approved_body(route)
    response = route.client.post(DESCRIBE, json={**body, "acknowledge_training": True})
    assert response.status_code == 200, response.text
    assert len(route.sent) == 2
    assert route.sent[0].content == route.sent[1].content


@pytest.mark.parametrize("need,message", [("unexpected_permission", "Unknown request"),
                                            ("acknowledge_training", "x" * 501),
                                            ("acknowledge_training", "   "),
                                            ("acknowledge_training", "contains\ncontrol")])
def test_unreadable_selection_requirements_refuse_safely(route, monkeypatch, need, message):
    body = approved_body(route)
    monkeypatch.setattr(sg, "GUARDS", [lambda choice: sg.Finding(
        "synthetic", need, choice, message, {})])
    status = route.client.get(STATUS).json()
    assert status["configured"] is False
    response = route.client.post(DESCRIBE, json=body)
    assert response.status_code == 503
    assert not route.sent


def test_composer_consent_does_not_authorize_unattended_vision(route, audit):
    from agents.core.channels.media_reader import InboundImageReader

    setting("openrouter_data_collection", "allow")
    body = approved_body(route)
    assert route.client.post(DESCRIBE, json={**body, "acknowledge_training": True}).status_code == 200
    assert InboundImageReader.from_env().refusal().reason == "local_vlm_not_proven_local"
