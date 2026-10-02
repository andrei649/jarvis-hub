"""Owner-configured video fallback routes remain bounded and credential isolated."""

import json
from dataclasses import FrozenInstanceError

import httpx
import pytest

from agents.core.llm.video_routes import VideoRouteConfigError, resolve_video_fallbacks


def configured(*routes, **extra):
    return {"JARVIS_ROLE_VIDEO_FALLBACKS": json.dumps(routes), **extra}


def route(provider="openai-compatible", model="video-model", base_url="https://video.example/v1"):
    return {"provider": provider, "model": model, "base_url": base_url}


@pytest.mark.parametrize("env", [{}, {"JARVIS_ROLE_VIDEO_FALLBACKS": "  "},
                                {"JARVIS_ROLE_VIDEO_FALLBACKS": "[]"}])
def test_absent_or_empty_chain_has_no_fallbacks(env):
    assert resolve_video_fallbacks(env) == ()


def test_four_routes_preserve_order_and_take_only_slot_keys():
    env = configured(
        route("lm-studio", "local-one", " http://LOCALHOST:80/v1/ "),
        route("openai-compatible", "remote-two", "https://VIDEO.EXAMPLE:443/v1/"),
        route("openai-compatible", "local-three", "http://[::1]:1234/v1"),
        route("lm-studio", "local-four", "http://127.0.0.1:1234"),
        JARVIS_ROLE_VIDEO_FALLBACK_2_KEY="  dedicated-two  ",
        JARVIS_ROLE_VIDEO_FALLBACK_4_KEY="dedicated-four",
        JARVIS_ROLE_VIDEO_KEY="primary-secret",
        JARVIS_ROLE_VISION_KEY="vision-secret",
        JARVIS_ROLE_MAIN_KEY="main-secret",
    )

    rows = resolve_video_fallbacks(env)

    assert [(r.slot, r.provider, r.model, r.base_url, r.api_key) for r in rows] == [
        (1, "lm-studio", "local-one", "http://localhost/v1", ""),
        (2, "openai-compatible", "remote-two", "https://video.example/v1", "dedicated-two"),
        (3, "openai-compatible", "local-three", "http://[::1]:1234/v1", ""),
        (4, "lm-studio", "local-four", "http://127.0.0.1:1234", "dedicated-four"),
    ]
    assert isinstance(rows, tuple)
    with pytest.raises(FrozenInstanceError):
        rows[0].model = "changed"
    assert "dedicated-two" not in repr(rows)
    assert "video.example" not in repr(rows)


def test_process_environment_is_read_at_call_time(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([route()]))
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "first-key")
    assert resolve_video_fallbacks()[0].api_key == "first-key"
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "second-key")
    assert resolve_video_fallbacks()[0].api_key == "second-key"


@pytest.mark.parametrize("raw", ["{", "null", "{}", '"route"', "[1]", "[[]]",
                                 json.dumps([route()] * 5),
                                 json.dumps([route(), {**route(), "extra": "secret"}]),
                                 json.dumps([{"provider": "lm-studio", "model": "x"}]),
                                 json.dumps([{"provider": 3, "model": "x", "base_url": "x"}]),
                                 json.dumps([{"provider": "lm-studio", "model": None,
                                              "base_url": "http://localhost:1234"}])])
def test_invalid_structure_refuses_entire_chain_without_echo(raw):
    with pytest.raises(VideoRouteConfigError) as exc:
        resolve_video_fallbacks({"JARVIS_ROLE_VIDEO_FALLBACKS": raw})
    assert raw not in str(exc.value)
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("bad", ["", "  ", "auto", " AUTO ", "x" * 257])
def test_blank_auto_or_long_model_refused(bad):
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks(configured(route(model=bad)))


@pytest.mark.parametrize("provider", ["ollama", "anthropic", "made-up", "", "x" * 65])
def test_only_implemented_native_providers_accepted(provider):
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks(configured(route(provider=provider)))


@pytest.mark.parametrize("url", [
    "", "localhost:1234", "ftp://localhost:1234", "http://", "http://localhost:0",
    "http://localhost:65536", "http://user:pass@localhost:1234/v1",
    "https://user@video.example/v1", "https://video.example/v1?key=secret",
    "https://video.example/v1#secret", "https://video.example/v1?",
    "http://video.example/v1", "http://192.168.1.2:1234/v1",
    "http://video.example:1234/v1", "https://video.example/v1\nHeader: secret",
    "https://video.example/v1\\other", "https://video.example/" + "x" * 2049,
])
def test_unsafe_or_oversized_urls_refused(url):
    with pytest.raises(VideoRouteConfigError) as exc:
        resolve_video_fallbacks(configured(route(base_url=url)))
    assert "secret" not in str(exc.value)


def test_lm_studio_remote_https_is_refused_even_with_tls():
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks(configured(route("lm-studio", "model", "https://model.example/v1")))


def test_malformed_later_route_refuses_all_earlier_usable_routes():
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks(configured(route(), route(base_url="http://remote.example/v1")))


def test_oversized_json_or_key_is_refused_before_return():
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks({"JARVIS_ROLE_VIDEO_FALLBACKS": "[" + " " * 8193 + "]"})
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks(configured(route(), JARVIS_ROLE_VIDEO_FALLBACK_1_KEY="x" * 4097))


def test_mapping_does_not_borrow_process_credentials(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "process-secret")
    assert resolve_video_fallbacks(configured(route()))[0].api_key == ""


def test_duplicate_json_fields_refuse_ambiguous_configuration():
    raw = ('[{"provider":"lm-studio","provider":"openai-compatible",'
           '"model":"m","base_url":"https://video.example/v1"}]')
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks({"JARVIS_ROLE_VIDEO_FALLBACKS": raw})


def test_invalid_unicode_is_sanitized():
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks({"JARVIS_ROLE_VIDEO_FALLBACKS": "\ud800"})


def test_deeply_nested_json_refuses_with_sanitized_error():
    with pytest.raises(VideoRouteConfigError):
        resolve_video_fallbacks({"JARVIS_ROLE_VIDEO_FALLBACKS": "[" * 3000 + "]" * 3000})


@pytest.mark.parametrize("host", ["api.anthropic.com", "bedrock-runtime.us-east-1.amazonaws.com"])
def test_host_with_incompatible_mandated_protocol_refused(host):
    with pytest.raises(VideoRouteConfigError) as exc:
        resolve_video_fallbacks(configured(route(base_url=f"https://{host}/v1")))
    assert host not in str(exc.value)


@pytest.mark.parametrize("bad_route", [
    route(model="broken\ud800model"),
    route(base_url="https://video.example/v1/\ud800"),
    route(base_url="https://video.example/v1/\x7f"),
])
def test_invalid_unicode_or_del_in_second_route_refuses_whole_chain(bad_route):
    with pytest.raises(VideoRouteConfigError) as exc:
        resolve_video_fallbacks(configured(route(), bad_route))
    assert "video.example" not in str(exc.value)
    assert "broken" not in str(exc.value)


def test_non_ascii_second_slot_key_refuses_whole_chain():
    with pytest.raises(VideoRouteConfigError) as exc:
        resolve_video_fallbacks(configured(route(), route(), JARVIS_ROLE_VIDEO_FALLBACK_2_KEY="clé"))
    assert "clé" not in str(exc.value)


def test_valid_utf8_model_and_path_remain_usable_by_httpx():
    selected = resolve_video_fallbacks(configured(
        route(model="vidéo-modèle", base_url="https://video.example/vidéo/")))[0]
    request = httpx.Request("POST", selected.base_url + "/v1/chat/completions",
                            json={"model": selected.model})
    assert selected.model == "vidéo-modèle"
    assert str(request.url) == "https://video.example/vid%C3%A9o/v1/chat/completions"
