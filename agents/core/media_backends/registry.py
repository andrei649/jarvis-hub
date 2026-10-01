"""Data-only local image protocols. Reading configuration never constructs clients."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..env_config import truthy
from ..media_providers import ProviderBase, ProviderRegistry, registry_source_fingerprint
from .comfyui import ComfyUIConfig, ImageGenerationError, validate_options

_IMPORTED_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ID = re.compile(r'[a-z][a-z0-9_-]{0,31}')
_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,172}')


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def registry_fingerprint():
    try:
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _IMPORTED_SHA:
            raise ImageGenerationError('registry_source_changed')
    except OSError:
        raise ImageGenerationError('registry_source_changed') from None
    try:
        shared = registry_source_fingerprint()
    except ValueError:
        raise ImageGenerationError('registry_source_changed') from None
    return hashlib.sha256(f'{_IMPORTED_SHA}:{shared}'.encode()).hexdigest()


def local_endpoint(raw):
    # Reuse the existing literal HTTP loopback-only endpoint contract.
    if not isinstance(raw, str):
        raise ImageGenerationError('invalid_endpoint')
    return ComfyUIConfig.from_env({'JARVIS_LOCAL_IMAGE_GENERATION': '1',
                                  'JARVIS_COMFYUI_CHECKPOINT': 'validation.safetensors',
                                  'JARVIS_COMFYUI_URL': raw}).base_url


def _object(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 8192:
        raise ValueError('catalog bound')
    value = strict_json(raw)
    if not isinstance(value, dict) or len(value) > 8:
        raise ValueError('invalid catalog')
    return value


def _catalog(env):
    records = {}
    if env.get('JARVIS_COMFYUI_CHECKPOINT'):
        default = ComfyUIConfig.from_env(env)
        models = list(dict.fromkeys([default.checkpoint, *env.get('JARVIS_COMFYUI_CHECKPOINTS', default.checkpoint).split(',')]))
        records['comfyui'] = {'protocol': 'comfyui', 'url': default.base_url, 'models': models}
    try:
        aliases = _object(env.get('JARVIS_LOCAL_IMAGE_BACKENDS', '{}'))
        if 'comfyui' in aliases:
            raise ValueError('reserved alias')
        for name, row in aliases.items():
            if not _ID.fullmatch(name) or not isinstance(row, dict) or set(row) != {'url', 'checkpoints'}:
                raise ValueError('invalid alias')
            records[name] = {'protocol': 'comfyui', 'url': row['url'], 'models': row['checkpoints']}
        for row in records.values():
            if not isinstance(row['models'], list) or not 1 <= len(row['models']) <= 32:
                raise ValueError('invalid models')
            for model in row['models']:
                ComfyUIConfig.from_env({'JARVIS_LOCAL_IMAGE_GENERATION': '1', 'JARVIS_COMFYUI_URL': row['url'],
                                       'JARVIS_COMFYUI_CHECKPOINT': model})
        providers = _object(env.get('JARVIS_LOCAL_IMAGE_PROVIDERS', '{}'))
        for name, row in providers.items():
            if (not _ID.fullmatch(name) or name in records or name in {'comfyui', 'openai'}
                    or not isinstance(row, dict) or set(row) != {'protocol', 'url', 'models'}
                    or row['protocol'] != 'openai_images'):
                raise ValueError('invalid provider')
            models = row['models']
            if (not isinstance(models, list) or not 1 <= len(models) <= 32
                    or any(not isinstance(m, str) or not _MODEL.fullmatch(m) for m in models)
                    or len(set(models)) != len(models)):
                raise ValueError('invalid models')
            records[name] = {**row, 'url': local_endpoint(row['url'])}
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ImageGenerationError('invalid_backend_catalog') from None
    return records


@dataclass(frozen=True)
class ImageProvider(ProviderBase):
    provider_id: str
    url: str
    models: tuple[str, ...]

    @property
    def name(self):
        return self.provider_id

    @property
    def kind(self):
        return 'image'

    def is_available(self):
        # Configuration has been validated; this is not a reachability probe.
        return True

    def selected_model(self, options):
        model = options.get('model', self.models[0])
        if not isinstance(model, str) or model not in self.models:
            raise ImageGenerationError('model_not_configured')
        return model


class ComfyImageProvider(ImageProvider):
    protocol = 'comfyui'

    def config(self, options, *, output_root=None):
        return ComfyUIConfig.from_env({'JARVIS_LOCAL_IMAGE_GENERATION': '1',
                                      'JARVIS_COMFYUI_URL': self.url,
                                      'JARVIS_COMFYUI_CHECKPOINT': self.selected_model(options)},
                                     output_root=output_root)

    async def generate(self, config, prompt, options, *, guard, backend_factories):
        return await backend_factories[self.protocol](config).generate(prompt, options, guard=guard)


class OpenAIImageProvider(ImageProvider):
    protocol = 'openai_images'

    def config(self, options, *, output_root=None):
        from .local_openai_image import LocalOpenAIImageConfig
        if output_root is None:
            from ..paths import data_path
            output_root = data_path('media', 'generated')
        return LocalOpenAIImageConfig(self.url, self.selected_model(options), Path(output_root).resolve())

    async def generate(self, config, prompt, options, *, guard, backend_factories):
        return await backend_factories[self.protocol](config).generate(prompt, options, guard=guard)


def configured_provider_registry(env=None):
    """Construct only built-in adapters, using validated data and no live probes."""
    env = os.environ if env is None else env
    if not truthy(env.get('JARVIS_LOCAL_IMAGE_GENERATION')):
        return ProviderRegistry()
    adapters = {'comfyui': ComfyImageProvider, 'openai_images': OpenAIImageProvider}
    return ProviderRegistry(adapters[row['protocol']](name, row['url'], tuple(row['models']))
                            for name, row in _catalog(env).items())


def resolve_provider(options=None, env=None):
    env = os.environ if env is None else env
    if not truthy(env.get('JARVIS_LOCAL_IMAGE_GENERATION')):
        return None
    options = {} if options is None else options
    if not isinstance(options, dict):
        raise ImageGenerationError('invalid_options')
    registry = configured_provider_registry(env)
    name = options.get('backend', env.get('JARVIS_LOCAL_IMAGE_DEFAULT_BACKEND', 'comfyui'))
    provider = registry.get('image', name)
    if provider is None:
        if name == 'comfyui' and not env.get('JARVIS_COMFYUI_CHECKPOINT'):
            raise ImageGenerationError('checkpoint_required')
        raise ImageGenerationError('backend_not_configured')
    return provider


def resolve_config(options=None, env=None, *, output_root=None):
    provider = resolve_provider(options, env)
    return provider.config(options or {}, output_root=output_root) if provider is not None else None


def normalize_options(prompt, options, config):
    if isinstance(config, ComfyUIConfig):
        return validate_options(prompt, options)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise ImageGenerationError('invalid_prompt')
    if not isinstance(options, dict) or set(options) - {'backend', 'model', 'width', 'height'}:
        raise ImageGenerationError('unsupported_options')
    result = {'width': 512, 'height': 512, **options}
    for key in ('width', 'height'):
        if type(result[key]) is not int or not 64 <= result[key] <= 1024 or result[key] % 64:
            raise ImageGenerationError('invalid_options')
    if 'model' in result and result['model'] != config.model:
        raise ImageGenerationError('model_not_configured')
    if 'backend' in result and (not isinstance(result['backend'], str) or not _ID.fullmatch(result['backend'])):
        raise ImageGenerationError('invalid_options')
    return result


def _capabilities(protocol):
    return {'edit': protocol == 'comfyui', 'max_references': 4 if protocol == 'comfyui' else 0,
            'upscale': [2] if protocol == 'comfyui' else []}


def configuration_status(env=None):
    env = os.environ if env is None else env
    name = env.get('JARVIS_LOCAL_IMAGE_DEFAULT_BACKEND', 'comfyui')
    try:
        config = resolve_config(env=env)
        providers = configured_provider_registry(env)
    except ImageGenerationError as exc:
        return {'configured': False, 'backend': name, 'reason': exc.reason, 'reachable': None}
    protocol = providers.get('image', name).protocol if config is not None else 'comfyui'
    return {'configured': config is not None, 'backend': name if config else 'off',
            'reason': 'not_probed' if config else 'disabled', 'reachable': None,
            'local': True, 'approval_required': True, **_capabilities(protocol),
            'backends': [{'id': provider.name, 'models': list(provider.models), 'protocol': provider.protocol,
                          **_capabilities(provider.protocol)} for provider in providers.list('image')]}
