"""Declarative local image registration and bounded offline wire protocol."""
import base64
import json
import struct
import zlib

import httpx
import pytest

from tests.test_local_image_runtime import rig as rig


def environment(**overrides):
    return {'JARVIS_LOCAL_IMAGE_GENERATION': '1',
            'JARVIS_LOCAL_IMAGE_DEFAULT_BACKEND': 'studio',
            'JARVIS_LOCAL_IMAGE_PROVIDERS': json.dumps({'studio': {
                'protocol': 'openai_images', 'url': 'http://127.0.0.1:9090', 'models': ['image-v1']}}),
            **overrides}


def png(width=64, height=64):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x00' * width * 3) * height)) + chunk(b'IEND', b''))


def test_explicit_default_without_comfy_checkpoint(tmp_path):
    from agents.core.media_backends.registry import (
        configuration_status,
        normalize_options,
        resolve_config,
    )
    config = resolve_config(env=environment(), output_root=tmp_path)
    assert config.model == 'image-v1'
    assert normalize_options('boat', {}, config) == {'width': 512, 'height': 512}
    status = configuration_status(environment())
    assert status['backend'] == 'studio' and status['configured'] and status['reachable'] is None
    assert status['backends'] == [{'id': 'studio', 'models': ['image-v1'], 'protocol': 'openai_images',
                                   'edit': False, 'max_references': 0, 'upscale': []}]


async def test_valid_native_post_writes_opaque_artifact_once(tmp_path):
    from agents.core.media_backends.local_openai_image import LocalOpenAIImageBackend
    from agents.core.media_backends.registry import resolve_config
    calls, guards = [], []
    def service(request):
        calls.append(request)
        assert request.url == 'http://127.0.0.1:9090/v1/images/generations'
        assert json.loads(request.content) == {'model': 'image-v1', 'prompt': 'boat', 'size': '64x64',
                                              'n': 1, 'response_format': 'b64_json'}
        assert 'authorization' not in request.headers
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode()}]})
    config = resolve_config(env=environment(), output_root=tmp_path)
    value = await LocalOpenAIImageBackend(config, transport=httpx.MockTransport(service)).generate(
        'boat', {'width': 64, 'height': 64}, guard=lambda: guards.append(True))
    assert len(calls) == 1 and len(guards) >= 2
    assert value['width'] == value['height'] == 64
    assert (tmp_path / (value['artifact_id'] + '.png')).read_bytes() == png()


@pytest.mark.parametrize('url', ['http://localhost:9090', 'https://127.0.0.1:9090',
    'http://127.0.0.1', 'http://127.0.0.1:0', 'http://127.0.0.1:9090/v1',
    'http://u:p@127.0.0.1:9090', 'http://127.0.0.1:9090?', 'http://127.0.0.1:9090#',
    'http://remote.example:9090', 'http://127.0.0.1:9090/../', None])
def test_invalid_endpoints_fail_without_transport(url):
    from agents.core.media_backends.comfyui import ImageGenerationError
    from agents.core.media_backends.registry import resolve_config
    env = environment(JARVIS_LOCAL_IMAGE_PROVIDERS=json.dumps({'studio': {
        'protocol': 'openai_images', 'url': url, 'models': ['m']}}))
    with pytest.raises(ImageGenerationError):
        resolve_config(env=env)


@pytest.mark.parametrize('raw', [
    '{"studio":{"protocol":"openai_images","url":"http://127.0.0.1:9","models":["m"],"models":["x"]}}',
    '{"studio":{},"studio":{}}', '[]', 'null', '{"openai":{}}', '{"comfyui":{}}',
    json.dumps({'studio': {'protocol': 'python', 'url': 'http://127.0.0.1:9', 'models': ['m']}}),
    json.dumps({'studio': {'protocol': 'openai_images', 'url': 'http://127.0.0.1:9', 'models': ['m', 'm']}}),
    json.dumps({'studio': {'protocol': 'openai_images', 'url': 'http://127.0.0.1:9', 'models': [17]}}),
    json.dumps({'studio': {'protocol': 'openai_images', 'url': 'http://127.0.0.1:9', 'models': ['bad\nmodel']}}),
    json.dumps({'studio': {'protocol': 'openai_images', 'url': 'http://127.0.0.1:9', 'models': ['m'], 'auth': 'key'}}),
    ' ' * 8193,
])
def test_invalid_or_duplicate_registration_is_rejected(raw):
    from agents.core.media_backends.comfyui import ImageGenerationError
    from agents.core.media_backends.registry import resolve_config
    with pytest.raises(ImageGenerationError):
        resolve_config(env=environment(JARVIS_LOCAL_IMAGE_PROVIDERS=raw))


def test_catalog_collision_and_entry_cap():
    from agents.core.media_backends.comfyui import ImageGenerationError
    from agents.core.media_backends.registry import resolve_config
    with pytest.raises(ImageGenerationError):
        resolve_config(env=environment(JARVIS_COMFYUI_CHECKPOINT='base.safetensors',
            JARVIS_LOCAL_IMAGE_BACKENDS=json.dumps({'studio': {'url': 'http://127.0.0.1:8',
                                                               'checkpoints': ['base.safetensors']}})))
    row = {'protocol': 'openai_images', 'url': 'http://127.0.0.1:9', 'models': ['m']}
    with pytest.raises(ImageGenerationError):
        resolve_config(env=environment(JARVIS_LOCAL_IMAGE_PROVIDERS=json.dumps({f'p{i}': row for i in range(9)})))


@pytest.mark.parametrize('options', [{'seed': 0}, {'steps': 20}, {'reference': 'a' * 32},
    {'references': ['a' * 32]}, {'strength': 50}, {'upscale': 2}, {'width': True},
    {'width': 63}, {'height': 1088}, {'height': 65}, {'model': 'wrong'}])
def test_normalization_never_drops_unsupported_options(tmp_path, options):
    from agents.core.media_backends.comfyui import ImageGenerationError
    from agents.core.media_backends.registry import normalize_options, resolve_config
    with pytest.raises(ImageGenerationError):
        normalize_options('boat', options, resolve_config(env=environment(), output_root=tmp_path))


def test_status_is_pure_and_model_names_are_data(monkeypatch):
    # The backend module (and the direct transport it imports) reads httpx.AsyncClient at
    # import time: import it BEFORE AsyncClient is replaced, so this test does not depend
    # on another test having imported it first (review round 6).
    import agents.core.media_backends.local_openai_image  # noqa: F401
    from agents.core.media_backends.registry import configuration_status, resolve_config
    def forbidden(*args, **kwargs):
        raise AssertionError('status constructed a client')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    env = environment(JARVIS_LOCAL_IMAGE_PROVIDERS=json.dumps({'studio': {'protocol': 'openai_images',
        'url': 'http://[::1]:9090/', 'models': ['org/image:v1', 'image-v2']}}))
    assert configuration_status(env)['reachable'] is None
    assert resolve_config({'model': 'org/image:v1'}, env=env).base_url == 'http://[::1]:9090'
    assert resolve_config(env={}) is None


@pytest.mark.parametrize('kind', ['url', 'two', 'duplicate', 'base64', 'png', 'dimensions', 'encoding', 'redirect'])
async def test_invalid_responses_never_publish(tmp_path, kind):
    from agents.core.media_backends.comfyui import ImageGenerationError
    from agents.core.media_backends.local_openai_image import LocalOpenAIImageBackend
    from agents.core.media_backends.registry import resolve_config
    calls = []
    def service(request):
        calls.append(request)
        if kind == 'encoding':
            return httpx.Response(200, headers={'content-encoding': 'gzip'}, content=b'bad')
        if kind == 'redirect':
            return httpx.Response(307, headers={'location': 'http://remote.example/image'})
        if kind == 'duplicate':
            return httpx.Response(200, content=b'{"data":[],"data":[]}')
        item = {'b64_json': base64.b64encode(png(128 if kind == 'dimensions' else 64)).decode()}
        if kind == 'url':
            item = {'url': 'http://remote.example/image'}
        elif kind == 'base64':
            item = {'b64_json': '%%%'}
        elif kind == 'png':
            item = {'b64_json': base64.b64encode(b'invalid PNG').decode()}
        return httpx.Response(200, json={'data': [item, item] if kind == 'two' else [item]})
    config = resolve_config(env=environment(), output_root=tmp_path)
    with pytest.raises(ImageGenerationError):
        await LocalOpenAIImageBackend(config, transport=httpx.MockTransport(service)).generate('boat', {'width': 64, 'height': 64})
    assert len(calls) == 1 and not list(tmp_path.glob('*.png'))


@pytest.mark.parametrize('phase, cause', [
    ('send', 'kernel_denied'),
    ('publication', 'kernel_denied'),
    ('publication', 'mediation_execution_required'),
    # The guard BREAKING is not governance (review round 5, item 1).
    ('publication', 'local_guard_failed'),
    ('publication', 'approval_binding_invalid'),
])
async def test_fresh_guard_prevents_send_or_publication(tmp_path, phase, cause):
    from agents.core.media_backends.comfyui import (
        ImageGenerationError,
        ImageWithheldAfterGeneration,
    )
    from agents.core.media_backends.local_openai_image import LocalOpenAIImageBackend
    from agents.core.media_backends.registry import resolve_config
    calls, checks = [], []
    def guard():
        checks.append(True)
        if phase == 'send' or len(checks) > 1:
            raise ImageGenerationError(cause)
    def service(request):
        calls.append(True)
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode()}]})
    with pytest.raises(ImageGenerationError) as raised:
        await LocalOpenAIImageBackend(resolve_config(env=environment(), output_root=tmp_path),
                                      transport=httpx.MockTransport(service)).generate(
            'boat', {'width': 64, 'height': 64}, guard=guard)
    assert len(calls) == (phase == 'publication') and not list(tmp_path.iterdir())
    if phase == 'send':
        assert raised.value.reason == cause              # before the request: the gate itself
    elif cause in {'kernel_denied', 'mediation_execution_required'}:
        # After the request a governance gate withholds the generated image, the gate as
        # its cause (review round 4, item 3).
        assert (raised.value.reason, raised.value.cause) == ('withheld_after_generation', cause)
    else:
        # ... while a guard that broke is a failure under its own reason, never withheld
        # (review round 5, item 1). Nothing is published either way.
        assert raised.value.reason == cause
        assert not isinstance(raised.value, ImageWithheldAfterGeneration)


async def test_uncertain_post_is_never_retried(tmp_path):
    from agents.core.media_backends.comfyui import ImageGenerationError
    from agents.core.media_backends.local_openai_image import LocalOpenAIImageBackend
    from agents.core.media_backends.registry import resolve_config
    calls = []
    def service(request):
        calls.append(True)
        raise httpx.ReadTimeout('uncertain', request=request)
    with pytest.raises(ImageGenerationError, match='submission_unknown'):
        await LocalOpenAIImageBackend(resolve_config(env=environment(), output_root=tmp_path),
                                      transport=httpx.MockTransport(service)).generate('boat', {})
    assert calls == [True]


@pytest.mark.parametrize('module_name', ['registry', 'local_openai_image', 'comfyui'])
def test_loaded_registry_and_backend_source_drift_refuses(tmp_path, monkeypatch, module_name):
    import importlib

    from agents.core.media_backends.comfyui import ImageGenerationError
    from agents.core.media_backends.registry import resolve_config
    config = resolve_config(env=environment(), output_root=tmp_path)
    before = config.fingerprint()
    assert before == config.fingerprint()
    changed = tmp_path / 'changed.py'
    changed.write_text('# changed implementation')
    module = importlib.import_module('agents.core.media_backends.' + module_name)
    monkeypatch.setattr(module, 'Path', lambda _: changed)
    with pytest.raises(ImageGenerationError, match='source_changed'):
        config.fingerprint()


@pytest.mark.parametrize('limit', ['response', 'image'])
async def test_wire_and_decoded_byte_limits(tmp_path, limit):
    from dataclasses import replace

    from agents.core.media_backends.comfyui import ImageGenerationError
    from agents.core.media_backends.local_openai_image import LocalOpenAIImageBackend
    from agents.core.media_backends.registry import resolve_config
    config = resolve_config(env=environment(), output_root=tmp_path)
    config = replace(config, **({'max_json_bytes': 10} if limit == 'response' else {'max_image_bytes': 10}))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'data': [
        {'b64_json': base64.b64encode(png()).decode()}]}))
    with pytest.raises(ImageGenerationError):
        await LocalOpenAIImageBackend(config, transport=transport).generate('boat', {'width': 64, 'height': 64})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('headers', [{'content-type': 'text/html'},
    {'content-type': 'application/json', 'content-length': '999999999'},
    {'content-type': 'application/json', 'content-length': '-1'}])
async def test_headers_refuse_before_reading_stream(tmp_path, headers):
    from agents.core.media_backends.comfyui import ImageGenerationError
    from agents.core.media_backends.local_openai_image import LocalOpenAIImageBackend
    from agents.core.media_backends.registry import resolve_config
    reads = []
    class NoRead(httpx.AsyncByteStream):
        async def __aiter__(self):
            reads.append(True)
            yield b'never read'
    transport = httpx.MockTransport(lambda _: httpx.Response(200, headers=headers, stream=NoRead()))
    with pytest.raises(ImageGenerationError):
        await LocalOpenAIImageBackend(resolve_config(env=environment(), output_root=tmp_path),
                                      transport=transport).generate('boat', {})
    assert reads == []


def test_comfy_runtime_head_checks_registry_source(tmp_path, monkeypatch):
    from agents.core import image_generation_runtime as runtime
    from agents.core.media_backends import registry
    from agents.core.media_backends.comfyui import ComfyUIConfig, ImageGenerationError
    config = ComfyUIConfig.from_env({'JARVIS_LOCAL_IMAGE_GENERATION': '1',
                                    'JARVIS_COMFYUI_CHECKPOINT': 'base.safetensors'}, output_root=tmp_path)
    service = runtime.LocalImageRuntime(queue=None, approved_task=lambda: None, authorizer=None, enqueue=None)
    service._head(config)
    changed = tmp_path / 'changed.py'
    changed.write_text('# changed registry')
    monkeypatch.setattr(registry, 'Path', lambda _: changed)
    with pytest.raises(ImageGenerationError, match='registry_source_changed'):
        service._head(config)


def test_exclusive_authority_write_syncs_file_then_entire_parent_chain(tmp_path, monkeypatch):
    import os
    import stat

    from agents.core import image_generation_runtime as runtime
    target = tmp_path / 'new' / 'nested' / 'authority.attempt'
    events = []
    original = os.fsync
    def observed(fd):
        info = os.fstat(fd)
        events.append(('dir' if stat.S_ISDIR(info.st_mode) else 'file', info.st_ino))
        original(fd)
    monkeypatch.setattr(runtime.os, 'fsync', observed)
    runtime._write_exclusive(target, {'consumed': True})
    assert events[0] == ('file', target.stat().st_ino)
    assert events[1:] == [('dir', parent.stat().st_ino)
                          for parent in (target.parent, *target.parent.parents)]
    assert json.loads(target.read_text()) == {'consumed': True}


def test_directory_sync_failure_preserves_exclusive_marker_and_refuses_replay(tmp_path, monkeypatch):
    import os
    import stat

    from agents.core import image_generation_runtime as runtime
    target = tmp_path / 'new' / 'authority.attempt'
    original = os.fsync
    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError('directory durability unavailable')
        original(fd)
    monkeypatch.setattr(runtime.os, 'fsync', fail_directory)
    with pytest.raises(OSError, match='directory durability unavailable'):
        runtime._write_exclusive(target, {'consumed': True})
    assert target.exists()
    before = target.read_bytes()
    monkeypatch.setattr(runtime.os, 'fsync', original)
    with pytest.raises(FileExistsError):
        runtime._write_exclusive(target, {'consumed': False})
    assert target.read_bytes() == before


@pytest.mark.parametrize('failure', ['fsync', 'open'])
async def test_directory_durability_failure_refuses_actual_approved_post(rig, monkeypatch, failure):
    import os
    import stat

    from tests.test_local_image_runtime import propose
    task_id = (await propose(rig))['task_id']
    await rig.worker.apply_decision(task_id, 'accept', decided_by='owner')
    original_sync, original_open = os.fsync, os.open
    if failure == 'fsync':
        def unavailable(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('directory sync unsupported')
            original_sync(fd)
        monkeypatch.setattr(rig.module.os, 'fsync', unavailable)
    else:
        def unavailable(*args, **kwargs):
            raise OSError('directory descriptors unsupported')
        monkeypatch.setattr(rig.module.os, 'open', unavailable)
    await rig.worker.tick()
    assert rig.requests == []
    assert rig.queue.get(task_id).result['reason'] == 'durable_attempt_unavailable'
    marker, = (rig.root / 'media' / 'image_approvals').glob('*.attempt')
    before = marker.read_bytes()
    monkeypatch.setattr(rig.module.os, 'fsync', original_sync)
    monkeypatch.setattr(rig.module.os, 'open', original_open)
    with pytest.raises(FileExistsError):
        rig.module._write_exclusive(marker, {'new': 'attempt'})
    assert marker.read_bytes() == before
    retry = await rig.coordinator._approved_image_tool_rpc_execute(rig.queue.get(task_id))
    assert retry['status'] == 'failed' and rig.requests == []
