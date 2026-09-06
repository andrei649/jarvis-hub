"""H13.1 — VLM adapter (image preprocessing + vision messages + backend). Offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import base64
import pytest

from agents.core.llm.vlm import (
    to_data_uri, encode_image_block, build_vision_messages, VLMBackend,
)


class _Resp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class _Client:
    def __init__(self, data):
        self.calls = []
        self._data = data

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _Resp(self._data)


def test_to_data_uri():
    uri = to_data_uri(b"abc", "image/png")
    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == b"abc"


def test_encode_image_block_bytes_and_url():
    # raw bytes (not a real image → Pillow passthrough) → data URI block
    block = encode_image_block(b"rawbytes")
    assert block["type"] == "image_url" and block["image_url"]["url"].startswith("data:")
    # http url → passed through verbatim
    assert encode_image_block("https://x/i.png")["image_url"]["url"] == "https://x/i.png"
    # data uri → passed through
    assert encode_image_block("data:image/png;base64,AAA")["image_url"]["url"].startswith("data:")


def test_encode_image_block_bad_path_returns_none():
    assert encode_image_block("/no/such/file.png") is None


def test_file_paths_are_never_opened():
    # path injection guard: a filesystem path is never read — only URLs / data-URIs
    assert encode_image_block("/etc/hostname") is None
    assert encode_image_block("relative/path.png") is None
    assert encode_image_block("https://x/i.png")["image_url"]["url"] == "https://x/i.png"
    assert encode_image_block("data:image/png;base64,AAA") is not None


def test_build_vision_messages():
    msgs = build_vision_messages("what is this?", images=[b"img"], system="be terse")
    assert msgs[0] == {"role": "system", "content": "be terse"}
    user = msgs[1]
    assert user["role"] == "user"
    assert user["content"][0] == {"type": "text", "text": "what is this?"}
    assert user["content"][1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_generate_vision_sends_images_and_strips_thinking():
    client = _Client({"choices": [{"message": {"content": "a receipt <think>hmm</think>"}}]})
    vlm = VLMBackend(api_key="sk-vlm", client=client)
    out = await vlm.generate_vision("qwen3-vl", "describe", images=[b"img"])
    assert out == "a receipt"                          # thinking stripped
    call = client.calls[0]
    assert call["url"] == "/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-vlm"
    content = call["json"]["messages"][-1]["content"]
    assert any(c["type"] == "image_url" for c in content)


@pytest.mark.asyncio
async def test_text_only_generate_has_no_image_blocks():
    client = _Client({"choices": [{"message": {"content": "hello"}}]})
    out = await VLMBackend(client=client).generate("qwen3-vl", "hi")
    assert out == "hello"
    content = client.calls[0]["json"]["messages"][-1]["content"]
    assert all(c["type"] != "image_url" for c in content)


@pytest.mark.asyncio
async def test_error_is_caught():
    class _Boom:
        async def post(self, *a, **k):
            raise RuntimeError("vlm down")

    out = await VLMBackend(client=_Boom()).generate_vision("m", "p", images=[b"x"])
    assert out.startswith("[VLM error")


# --- GAP-9: config resolver (LM Studio as first-class local backend) ---

from agents.core.llm.vlm import (  # noqa: E402
    LMSTUDIO_VLM_BASE,
    VLMNotConfigured,
    resolve_vlm_config,
)


def test_resolver_refuses_when_nothing_is_configured():
    with pytest.raises(VLMNotConfigured) as exc:
        resolve_vlm_config(env={})
    assert exc.value.reason == "vlm_disabled"


def test_resolver_off_wins_over_a_set_url():
    with pytest.raises(VLMNotConfigured) as exc:
        resolve_vlm_config(env={"JARVIS_VLM_BACKEND": "off",
                                "JARVIS_VLM_URL": "http://localhost:8000/v1"})
    assert exc.value.reason == "vlm_disabled"


def test_resolver_legacy_url_only_keeps_working_as_custom():
    config = resolve_vlm_config(env={"JARVIS_VLM_URL": "http://localhost:8000/v1"})
    assert config.backend == "custom"
    assert config.base_url == "http://localhost:8000/v1"
    assert config.model == "qwen2-vl"  # the historical default, unchanged
    assert config.is_local is True


def test_resolver_lmstudio_defaults_to_port_1234_but_never_guesses_a_model():
    with pytest.raises(VLMNotConfigured) as exc:
        resolve_vlm_config(env={"JARVIS_VLM_BACKEND": "lmstudio"})
    assert exc.value.reason == "vlm_model_unset"
    config = resolve_vlm_config(env={"JARVIS_VLM_BACKEND": "lmstudio",
                                     "JARVIS_VLM_MODEL": "qwen2.5-vl-7b"})
    assert config.base_url == LMSTUDIO_VLM_BASE
    assert config.model == "qwen2.5-vl-7b"
    assert config.is_local is True


def test_resolver_custom_requires_url_and_labels_remote_as_not_local():
    with pytest.raises(VLMNotConfigured) as exc:
        resolve_vlm_config(env={"JARVIS_VLM_BACKEND": "custom"})
    assert exc.value.reason == "vlm_url_unset"
    config = resolve_vlm_config(env={"JARVIS_VLM_BACKEND": "custom",
                                     "JARVIS_VLM_URL": "http://gpu-box.lan:8000/v1"})
    assert config.is_local is False


def test_resolver_unknown_backend_is_a_refusal_not_a_guess():
    with pytest.raises(VLMNotConfigured) as exc:
        resolve_vlm_config(env={"JARVIS_VLM_BACKEND": "openai"})
    assert exc.value.reason == "vlm_backend_unknown"


def test_backend_carries_a_local_provenance_label():
    assert VLMBackend(base_url="http://localhost:1234/v1", client=_Client({})).is_local is True
    assert VLMBackend(base_url="http://gpu-box.lan:8000/v1", client=_Client({})).is_local is False


@pytest.mark.asyncio
async def test_vlm_routes_resolve_config_and_refuse_honestly(monkeypatch):
    from agents.core.routers import multimodal

    for name in ("JARVIS_VLM_BACKEND", "JARVIS_VLM_URL", "JARVIS_VLM_MODEL", "JARVIS_VLM_KEY"):
        monkeypatch.delenv(name, raising=False)
    status = (await multimodal.vlm_status()).body
    import json as _json
    payload = _json.loads(status)
    assert payload == {"configured": False, "backend": "off", "reason": "vlm_disabled",
                       "default_model": None, "reachable": None}
    describe = await multimodal.vlm_describe(
        multimodal.VLMDescribeBody(prompt="what is this?", images=[])
    )
    assert describe.status_code == 503
    assert _json.loads(describe.body)["reason"] == "vlm_disabled"

    monkeypatch.setenv("JARVIS_VLM_BACKEND", "lmstudio")
    monkeypatch.setenv("JARVIS_VLM_MODEL", "qwen2.5-vl-7b")
    payload = _json.loads((await multimodal.vlm_status()).body)
    assert payload["configured"] is True
    assert payload["backend"] == "lmstudio"
    assert payload["base_url"] == "http://localhost:1234/v1"
    assert payload["default_model"] == "qwen2.5-vl-7b"
    assert payload["local"] is True
    # reachable stays null: the route does no network probe, and says so.
    assert payload["reachable"] is None


# --- op-visual-grounding: pinned local grounder presets (JARVIS_VLM_PRESET) ---

from agents.core.llm.vlm import (  # noqa: E402
    COORDINATE_CONVENTIONS,
    VLM_PRESETS,
    VLMConfig,
    VLMPreset,
    resolve_vlm_preset,
)


def test_preset_table_is_pinned_and_apache_licensed():
    assert set(VLM_PRESETS) == {
        "qwen3-vl-4b", "qwen3-vl-8b", "ui-tars-1.5-7b", "holo-3.1-35b-a3b", "qwen3.8-27b",
    }
    for preset_id, preset in VLM_PRESETS.items():
        assert preset.id == preset_id
        assert preset.license == "Apache-2.0"
        assert preset.convention in COORDINATE_CONVENTIONS
        assert preset.size_gb > 0
        assert preset.prompt_hint
    # The two families that disagree are pinned to different conventions.
    assert VLM_PRESETS["qwen3-vl-8b"].convention == "relative_1000"
    assert VLM_PRESETS["ui-tars-1.5-7b"].convention == "absolute_resized"


def test_preset_dataclass_validates_itself():
    with pytest.raises(ValueError, match="convention"):
        VLMPreset("x", "fam", "pixels", 1.0, "hint")
    with pytest.raises(ValueError, match="size_gb"):
        VLMPreset("x", "fam", "absolute", 0, "hint")
    with pytest.raises(ValueError, match="preset id"):
        VLMPreset("", "fam", "absolute", 1.0, "hint")
    with pytest.raises(ValueError, match="convention"):
        VLMConfig(backend="custom", base_url="http://localhost:1/v1", model="m",
                  api_key="", is_local=True, convention="pixels")


def test_resolve_vlm_preset_is_case_insensitive_and_never_guesses():
    assert resolve_vlm_preset(" UI-TARS-1.5-7B ").id == "ui-tars-1.5-7b"
    with pytest.raises(VLMNotConfigured) as exc:
        resolve_vlm_preset("gpt-4v")
    assert exc.value.reason == "vlm_preset_unknown"


def test_resolver_annotates_the_preset_but_still_requires_the_model_pin():
    config = resolve_vlm_config(env={
        "JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_MODEL": "ui-tars-1.5-7b-q4",
        "JARVIS_VLM_PRESET": "ui-tars-1.5-7b",
    })
    assert config.preset == "ui-tars-1.5-7b"
    assert config.convention == "absolute_resized"
    assert config.model == "ui-tars-1.5-7b-q4"   # the served name, not the preset id

    # preset without a model → refused on every backend, legacy URL path included
    for env in (
        {"JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_PRESET": "qwen3-vl-4b"},
        {"JARVIS_VLM_BACKEND": "custom", "JARVIS_VLM_URL": "http://localhost:8000/v1",
         "JARVIS_VLM_PRESET": "qwen3-vl-4b"},
        {"JARVIS_VLM_URL": "http://localhost:8000/v1", "JARVIS_VLM_PRESET": "qwen3-vl-4b"},
    ):
        with pytest.raises(VLMNotConfigured) as exc:
            resolve_vlm_config(env=env)
        assert exc.value.reason == "vlm_model_unset"


def test_resolver_unknown_preset_is_a_refusal():
    with pytest.raises(VLMNotConfigured) as exc:
        resolve_vlm_config(env={"JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_MODEL": "m",
                                "JARVIS_VLM_PRESET": "nope"})
    assert exc.value.reason == "vlm_preset_unknown"


def test_no_preset_means_absolute_pixels_and_untouched_legacy_shape():
    config = resolve_vlm_config(env={"JARVIS_VLM_URL": "http://localhost:8000/v1"})
    assert config.preset == "" and config.convention == "absolute"
    assert config.backend == "custom" and config.model == "qwen2-vl"
    # 'off' still wins over everything, preset included
    with pytest.raises(VLMNotConfigured) as exc:
        resolve_vlm_config(env={"JARVIS_VLM_BACKEND": "off", "JARVIS_VLM_PRESET": "qwen3-vl-4b",
                                "JARVIS_VLM_MODEL": "m"})
    assert exc.value.reason == "vlm_disabled"


def test_loopback_label_docstring_names_the_real_gates():
    """DRA-06 residual (b): the docstring must say who enforces, not just 'label'."""
    from agents.core.llm.vlm import _is_loopback_base

    doc = _is_loopback_base.__doc__ or ""
    assert "label" in doc and "gate" in doc
    assert "routers/multimodal.py" in doc and "screen_locator" in doc
