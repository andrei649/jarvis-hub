"""H21.A–D — vaultwarden resolver, media skill, idle image-gen, video prompt."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.secrets_vault import VaultResolver
from agents.core.media_skill import MediaSummarizer
from agents.core.image_gen import ImageGenOrchestrator
from agents.core.video_prompt import build_video_prompt


# ── H21.A vaultwarden resolver ────────────────────────────────────────────────

def test_vault_hit():
    class _V:
        def get(self, k):
            return "vault-secret" if k == "API_KEY" else None
    out = VaultResolver(client=_V()).resolve("API_KEY")
    assert out == {"value": "vault-secret", "source": "vault"}


def test_vault_miss_falls_back_to_env(monkeypatch):
    class _V:
        def get(self, k):
            return None
    monkeypatch.setenv("API_KEY", "env-secret")
    assert VaultResolver(client=_V()).resolve("API_KEY")["source"] == "env"


def test_no_vault_uses_env(monkeypatch):
    monkeypatch.setenv("TOKEN", "e")
    assert VaultResolver().resolve("TOKEN")["value"] == "e"
    assert VaultResolver().available() is False


def test_missing_secret():
    monkeypatch_clear = VaultResolver(fallback_env=False)
    assert monkeypatch_clear.resolve("NOPE")["source"] == "missing"


# ── H21.B media skill ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_media_no_url():
    assert (await MediaSummarizer().summarize_url(""))["reason"] == "no_url"


@pytest.mark.asyncio
async def test_media_host_tools_unavailable():
    out = await MediaSummarizer().summarize_url("http://x/v")
    assert out["ok"] is False and out["reason"] == "host_tools_unavailable"


@pytest.mark.asyncio
async def test_media_full_pipeline_with_stubs():
    async def dl(url):
        return "/tmp/a.mp3"

    async def tr(audio):
        return "the transcript text"

    async def summ(t):
        return "SUMMARY"

    out = await MediaSummarizer(dl, tr, summ).summarize_url("http://x/v")
    assert out["ok"] is True and out["transcript"] == "the transcript text"
    assert out["summary"] == "SUMMARY"


# ── H21.C idle image-gen ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_image_gen_no_backend():
    out = await ImageGenOrchestrator().generate("a cat")
    assert out["ok"] is False and out["reason"] == "diffusion_unavailable"


@pytest.mark.asyncio
async def test_image_gen_swaps_llm_around_diffusion():
    events = []

    async def unload():
        events.append("unload")

    async def diff(prompt):
        events.append("diffuse")
        return "/tmp/img.png"

    async def load():
        events.append("load")

    out = await ImageGenOrchestrator(diff, unload, load).generate("a cat")
    assert out["ok"] is True and out["path"] == "/tmp/img.png" and out["swapped"] is True
    assert events == ["unload", "diffuse", "load"]      # LLM restored after


@pytest.mark.asyncio
async def test_image_gen_restores_llm_on_failure():
    events = []

    async def unload():
        events.append("unload")

    async def diff(prompt):
        raise RuntimeError("oom")

    async def load():
        events.append("load")

    out = await ImageGenOrchestrator(diff, unload, load).generate("x")
    assert out["ok"] is False and "load" in events       # restored even on failure


# ── H21.D video prompt-builder ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_video_prompt_template():
    out = await build_video_prompt("a dragon over mountains")
    assert out["ok"] is True and out["source"] == "template"
    assert "a dragon over mountains" in out["prompt"]


@pytest.mark.asyncio
async def test_video_prompt_uses_llm():
    async def llm(idea):
        return "REFINED PROMPT"

    out = await build_video_prompt("x", llm=llm)
    assert out["source"] == "llm" and out["prompt"] == "REFINED PROMPT"


@pytest.mark.asyncio
async def test_video_prompt_no_idea():
    assert (await build_video_prompt(""))["ok"] is False
