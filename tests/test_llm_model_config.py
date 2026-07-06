"""AUD-14: centralize LLM model-name configuration."""

from pathlib import Path

from core.llm import hybrid_router, model_config
from core.llm.base import LLMBackend


class _FakeBackend(LLMBackend):
    async def generate(self, *args, **kwargs):
        return "ok"


def test_deep_model_name_uses_shared_env_config(monkeypatch):
    monkeypatch.setenv("JARVIS_DEEP_MODEL", "local/deep-custom")
    assert model_config.deep_model_name() == "local/deep-custom"

    monkeypatch.setenv("JARVIS_DEEP_MODEL", "  ")
    assert model_config.deep_model_name() == model_config.DEFAULT_DEEP_MODEL


def test_hybrid_router_no_longer_reads_deep_model_env_directly():
    src = Path(hybrid_router.__file__).read_text(encoding="utf-8")
    assert 'os.environ.get("JARVIS_DEEP_MODEL"' not in src


def test_hybrid_router_uses_shared_deep_model_override(monkeypatch):
    monkeypatch.setenv("JARVIS_DEEP_MODEL", "local/deep-custom")
    router = hybrid_router.HybridRouter()
    router._local_available = True
    router._backend = _FakeBackend()
    router._served_models = {"local/deep-custom"}

    _, model, route = router.select_backend("frigga", "hello")

    assert route == "local-deep"
    assert model == "local/deep-custom"
