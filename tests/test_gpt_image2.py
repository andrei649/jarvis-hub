"""OpenAI Image 2 virtual tiers retain their wire quality and edit boundary."""

import pytest


@pytest.mark.parametrize("tier", ("low", "medium", "high"))
def test_tier_maps_to_native_model_and_quality(tier):
    from agents.core.media_backends.openai_image import normalize_request

    assert normalize_request("blue square", {"model": f"gpt-image-2-{tier}"}) == {
        "model": "gpt-image-2", "prompt": "blue square", "n": 1,
        "size": "1024x1024", "quality": tier,
    }


def test_tier_rejects_contradictory_quality():
    from agents.core.media_backends.openai_image import normalize_request

    with pytest.raises(ValueError):
        normalize_request("blue square", {"model": "gpt-image-2-low", "quality": "high"})
