"""One explicit identity registry serves real image and speech providers."""
import importlib

import pytest


def api():
    assert importlib.util.find_spec("agents.core.media_providers") is not None, "shared provider API missing"
    return importlib.import_module("agents.core.media_providers")


def test_registry_has_stable_kind_scoped_identity_without_running_metadata_hooks():
    module = api()

    class Provider(module.ProviderBase):
        def __init__(self, kind, name):
            self._kind, self._name = kind, name

        @property
        def kind(self):
            return self._kind

        @property
        def name(self):
            return self._name

        def is_available(self):
            raise AssertionError("registry lookup cannot probe availability")

        def get_setup_schema(self):
            raise AssertionError("registry lookup cannot run setup")

    tts, stt = Provider("tts", "speech"), Provider("stt", "speech")
    source = [tts, stt]
    registry = module.ProviderRegistry(source)
    source.clear()
    assert registry.get("tts", "speech") is tts
    assert registry.get("stt", "speech") is stt
    assert registry.get("image", "speech") is None
    assert registry.list("tts") == (tts,)
    assert registry.list() == (tts, stt)
    with pytest.raises(ValueError, match="duplicate"):
        module.ProviderRegistry([tts, tts])


@pytest.mark.parametrize("kind,name", [("unknown", "ok"), ("tts", "../bad"),
                                      ("tts", "UPPER"), ("tts", ""), ("tts", "x" * 33)])
def test_registry_rejects_ambiguous_or_invalid_identity(kind, name):
    module = api()

    class Provider(module.ProviderBase):
        @property
        def kind(self):
            return kind

        @property
        def name(self):
            return name

    with pytest.raises(ValueError):
        module.ProviderRegistry([Provider()])


def test_default_metadata_is_nonexecuting_and_does_not_claim_availability():
    module = api()

    class Provider(module.ProviderBase):
        @property
        def kind(self):
            return "image"

        @property
        def name(self):
            return "synthetic"

    provider = Provider()
    assert provider.display_name == "synthetic"
    assert provider.get_setup_schema() == {"name": "synthetic", "badge": "", "tag": "", "env_vars": []}
    assert provider.is_available() is False
    with pytest.raises(TypeError):
        module.ProviderRegistry([object()])


def test_provider_implementation_fingerprint_is_stable_and_refuses_changed_source(monkeypatch):
    module = api()
    before = module.registry_source_fingerprint()
    assert len(before) == 64 and before == module.registry_source_fingerprint()
    original = module.Path.read_bytes
    monkeypatch.setattr(module.Path, "read_bytes", lambda self: b"changed" if str(self) == module.__file__ else original(self))
    with pytest.raises(ValueError, match="provider_registry_source_changed"):
        module.registry_source_fingerprint()


def test_image_configuration_resolves_through_common_registry():
    import json

    from agents.core.media_backends import registry

    module = api()
    builder = getattr(registry, "configured_provider_registry", None)
    assert callable(builder), "production image registry is not connected"
    env = {"JARVIS_LOCAL_IMAGE_GENERATION": "1", "JARVIS_LOCAL_IMAGE_DEFAULT_BACKEND": "drawing",
           "JARVIS_LOCAL_IMAGE_PROVIDERS": json.dumps({"drawing": {
               "protocol": "openai_images", "url": "http://127.0.0.1:9988", "models": ["synthetic"]}})}
    providers = builder(env)
    assert isinstance(providers, module.ProviderRegistry)
    selected = providers.get("image", "drawing")
    assert isinstance(selected, module.ProviderBase)
    assert selected.name == "drawing" and selected.protocol == "openai_images"
    assert selected.is_available() is True
    assert registry.resolve_config(env=env).model == "synthetic"
    assert builder({}).list() == ()


def test_image_fingerprint_includes_shared_implementation_and_refuses_drift(monkeypatch):
    from agents.core import media_providers
    from agents.core.media_backends import registry
    before = registry.registry_fingerprint()
    monkeypatch.setattr(registry, 'registry_source_fingerprint', lambda: 'replacement')
    assert registry.registry_fingerprint() != before
    monkeypatch.setattr(registry, 'registry_source_fingerprint', media_providers.registry_source_fingerprint)
    original = media_providers.Path.read_bytes
    monkeypatch.setattr(media_providers.Path, 'read_bytes',
                        lambda self: b'changed' if str(self) == media_providers.__file__ else original(self))
    with pytest.raises(registry.ImageGenerationError, match='registry_source_changed'):
        registry.registry_fingerprint()


# Reuse the actual signed image runtime, replacing only its external HTTP transport.
from tests.test_h517_provider_integration import rig as image_rig  # noqa: E402,F401


@pytest.mark.asyncio
async def test_approved_image_execution_calls_the_registered_adapter(image_rig, monkeypatch):
    from agents.core.media_backends.registry import OpenAIImageProvider
    from tests.test_h517_provider_integration import accept, propose
    seen = []
    original = OpenAIImageProvider.generate

    async def observed(self, *args, **kwargs):
        seen.append((self.kind, self.name))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(OpenAIImageProvider, 'generate', observed)
    async with image_rig.client() as client:
        tid = await propose(image_rig, client)
        assert seen == []
        await accept(client, tid)
        await image_rig.worker.tick()
        state = (await client.get(f'/api/media/generation-tasks/{tid}')).json()
        assert state['state'] == 'ready', state
        assert seen == [('image', 'studio')]
        assert len(image_rig.requests) == 1
