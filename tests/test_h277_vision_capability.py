"""Selected-main vision eligibility uses only explicit per-model evidence."""

from types import MappingProxyType, SimpleNamespace

import pytest

from agents.core.llm.vision_capability import main_vision_eligibility


@pytest.mark.parametrize(("declared", "expected"), [(True, True), (False, False)])
def test_exact_selected_model_uses_explicit_boolean_verdict(declared, expected):
    backend = SimpleNamespace(model_vision_capabilities={"vendor/model:1": declared})

    assert main_vision_eligibility(backend, "vendor/model:1") is expected


def test_other_model_or_case_is_not_inferred_from_declared_model():
    backend = SimpleNamespace(model_vision_capabilities={"vendor/model:1": False})

    assert main_vision_eligibility(backend, "vendor/model:2") is None
    assert main_vision_eligibility(backend, "Vendor/model:1") is None


def test_provider_wide_vision_claim_does_not_classify_selected_model():
    backend = SimpleNamespace(profile=SimpleNamespace(capabilities=frozenset({"vision"})))

    assert main_vision_eligibility(backend, "vendor/text") is None


@pytest.mark.parametrize("entry", ["false", "true", 0, 1, None, {"vision": False}])
def test_malformed_model_verdict_is_unknown(entry):
    backend = SimpleNamespace(model_vision_capabilities={"vendor/model": entry})

    assert main_vision_eligibility(backend, "vendor/model") is None


def test_read_only_model_snapshot_is_supported():
    backend = SimpleNamespace(model_vision_capabilities=MappingProxyType({"vision": True}))

    assert main_vision_eligibility(backend, "vision") is True


def test_dynamic_property_is_not_invoked_to_discover_capability():
    class Backend:
        @property
        def model_vision_capabilities(self):
            raise AssertionError("capability lookup invoked a dynamic provider probe")

    assert main_vision_eligibility(Backend(), "vision") is None


@pytest.mark.parametrize("model", [None, "", " vision", "vision ", 42])
def test_invalid_or_changed_model_identity_is_unknown(model):
    backend = SimpleNamespace(model_vision_capabilities={"vision": False})

    assert main_vision_eligibility(backend, model) is None
