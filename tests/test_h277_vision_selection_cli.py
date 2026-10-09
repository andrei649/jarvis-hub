"""CLI disclosures and explicit per-image-turn training/cost confirmation."""

import pytest

from agents.cli import nerva
from tests.test_h277_vision_selection_consent import audit, route, setting  # noqa: F401
from tests.test_nerva_chat_image import LOCAL, REMOTE, Fake, _run, png  # noqa: F401

TRAINING = {"needs": "acknowledge_training", "message": "Images may be used for training."}
COST = {"needs": "confirm_expensive", "message": "Output costs $80 per million tokens."}


def test_missing_selection_confirmation_stops_before_post(png):  # noqa: F811
    hub = Fake(status={**LOCAL, "selection_requirements": [TRAINING, COST]})
    code, out, err = _run(["-z", "--image", str(png), "what?"], hub)
    assert code == nerva.EXIT_USAGE and not out
    assert TRAINING["message"] in err and COST["message"] in err
    assert "--acknowledge-training" in err and "--confirm-expensive" in err
    assert len(hub.calls) == 1


@pytest.mark.parametrize("flags,expected", [
    (["--acknowledge-training"], nerva.EXIT_USAGE),
    (["--confirm-expensive"], nerva.EXIT_USAGE),
    (["--acknowledge-training", "--confirm-expensive"], nerva.EXIT_OK),
])
def test_both_requirements_need_independent_flags(png, flags, expected):  # noqa: F811
    hub = Fake(status={**LOCAL, "selection_requirements": [TRAINING, COST]})
    code, out, err = _run(["-z", "--image", str(png), *flags, "what?"], hub)
    assert code == expected
    if expected == nerva.EXIT_OK:
        assert out == "A screenshot.\n"
        assert hub.calls[-1][2]["acknowledge_training"] is True
        assert hub.calls[-1][2]["confirm_expensive"] is True
        assert "selection_requirements" not in hub.calls[-1][2]
        assert TRAINING["message"] in err and COST["message"] in err
    else:
        assert len(hub.calls) == 1


def test_training_ack_does_not_replace_remote_ack(png):  # noqa: F811
    hub = Fake(status={**REMOTE, "selection_requirements": [TRAINING]})
    code, _, err = _run(["-z", "--image", str(png), "--acknowledge-training", "what?"], hub)
    assert code == nerva.EXIT_USAGE and "--remote-vision" in err
    assert len(hub.calls) == 1


def test_remote_ack_does_not_replace_training_ack(png):  # noqa: F811
    hub = Fake(status={**REMOTE, "selection_requirements": [TRAINING]})
    code, _, err = _run(["-z", "--image", str(png), "--remote-vision", REMOTE["destination"], "what?"], hub)
    assert code == nerva.EXIT_USAGE and "--acknowledge-training" in err
    assert len(hub.calls) == 1


@pytest.mark.parametrize("requirements", [None, {}, "training", [None],
    [{"needs": "unknown", "message": "x"}], [TRAINING, TRAINING],
    [{"needs": "acknowledge_training", "message": ""}],
    [{"needs": "acknowledge_training", "message": "x" * 501}],
    [{"needs": "acknowledge_training", "message": "unsafe\x1b[31m"}],
])
def test_malformed_requirements_never_send_images(png, requirements):  # noqa: F811
    hub = Fake(status={**LOCAL, "selection_requirements": requirements})
    code, out, err = _run(["-z", "--image", str(png), "what?"], hub)
    assert code == nerva.EXIT_FAILED and not out
    assert "selection" in err and "nothing was sent" in err
    assert len(hub.calls) == 1


@pytest.mark.parametrize("flag", ["--acknowledge-training", "--confirm-expensive"])
def test_image_selection_flags_never_silently_apply_to_text_chat(flag):
    hub = Fake()
    code, _, err = _run(["-z", flag, "hello"], hub)
    assert code == nerva.EXIT_USAGE and "image turn" in err
    assert not hub.calls


def test_explicit_flags_are_forwarded_to_older_hub_without_claiming_approval(png):  # noqa: F811
    hub = Fake()
    code, _, _ = _run(["-z", "--image", str(png), "--acknowledge-training", "what?"], hub)
    assert code == nerva.EXIT_OK
    assert hub.calls[-1][2]["acknowledge_training"] is True
    assert "confirm_expensive" not in hub.calls[-1][2]


def test_legacy_status_keeps_original_request_shape(png):  # noqa: F811
    hub = Fake()
    code, _, _ = _run(["-z", "--image", str(png), "what?"], hub)
    assert code == nerva.EXIT_OK
    assert "acknowledge_training" not in hub.calls[-1][2]
    assert "confirm_expensive" not in hub.calls[-1][2]


def test_cli_confirmations_reach_real_composer_audit_and_provider(route, audit, png, monkeypatch):  # noqa: F811
    from agents.core.llm import cost_estimator
    from tests.test_nerva_chat_image import Routed

    setting("openrouter_data_collection", "allow")
    monkeypatch.setitem(cost_estimator.MODELS, "vision", {"input": 1, "output": 50})
    hub = Routed(route.client)
    args = ["-z", "--image", str(png), "--remote-vision", "https://openrouter.ai/api/v1"]
    code, _, err = _run([*args, "what?"], hub)
    assert code == nerva.EXIT_USAGE and "--acknowledge-training" in err and "--confirm-expensive" in err
    assert not route.sent and not audit.events
    code, out, _ = _run([*args, "--acknowledge-training", "--confirm-expensive", "what?"], hub)
    assert code == nerva.EXIT_OK and out == "An image.\n"
    assert len(route.sent) == 1
    assert {event.action_taken for event in audit.events} == {"model_training_consent", "model_cost_confirmed"}
