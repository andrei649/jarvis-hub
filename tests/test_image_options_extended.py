import pytest

from agents.core.media_backends.comfyui import (
    ComfyUIConfig,
    ImageGenerationError,
    _workflow,
    validate_options,
)

A, B = 'a'*32, 'b'*32


def test_multiple_references_and_upscale_are_bound_options():
    opts = validate_options('paint', {'references': [A, B], 'upscale': 2, 'backend': 'studio', 'model': 'b.safetensors'})
    assert opts['references'] == [A, B]
    assert opts['upscale'] == 2
    assert opts['strength'] == 60
    for bad in ({'references': []}, {'references':[A]*5}, {'reference':A, 'references':[B]}, {'upscale':3}, {'backend':'http://evil'}, {'model':'../x.safetensors'}):
        with pytest.raises(ImageGenerationError):
            validate_options('paint', bad)


def test_fixed_graph_blends_every_reference_and_upscales(tmp_path):
    cfg = ComfyUIConfig('http://127.0.0.1:8188', 'a.safetensors', tmp_path)
    opts = validate_options('paint', {'references':[A, B], 'upscale':2})
    graph = _workflow(cfg, 'paint', opts, ['first.png', 'second.png'], (128, 64))
    assert {n['inputs']['image'] for n in graph.values() if n['class_type']=='LoadImage'} == {'first.png','second.png'}
    assert any(n['class_type']=='ImageBlend' for n in graph.values())
    output = graph[graph['9']['inputs']['images'][0]]
    assert output['class_type'] == 'ImageScaleBy'
    assert output['inputs']['scale_by'] == 2


def test_selection_only_uses_configured_local_backends(monkeypatch, tmp_path):
    from agents.core.media_backends.comfyui import resolve_config
    monkeypatch.setenv('JARVIS_LOCAL_IMAGE_GENERATION','1')
    monkeypatch.setenv('JARVIS_COMFYUI_CHECKPOINT','a.safetensors')
    monkeypatch.setenv('JARVIS_COMFYUI_CHECKPOINTS','a.safetensors,b.safetensors')
    monkeypatch.setenv('JARVIS_LOCAL_IMAGE_BACKENDS', '{"studio":{"url":"http://127.0.0.1:8190","checkpoints":["c.safetensors"]}}')
    assert resolve_config({'model':'b.safetensors'}).checkpoint == 'b.safetensors'
    assert resolve_config({'backend':'studio','model':'c.safetensors'}).base_url == 'http://127.0.0.1:8190'
    with pytest.raises(ImageGenerationError):
        resolve_config({'model':'unknown.safetensors'})
    with pytest.raises(ImageGenerationError):
        resolve_config({'backend':'unknown'})


@pytest.mark.asyncio
async def test_multiple_uploads_one_submission_and_validated_saved_result(tmp_path):
    import json

    import httpx

    from agents.core.media_backends.comfyui import ComfyUIBackend
    from tests.test_image_edit import PNG, configured, edit_service, seeded
    seeded(tmp_path, A)
    seeded(tmp_path, B)
    requests = []
    def service(request):
        if request.url.path == '/upload/image':
            requests.append(request)
            return httpx.Response(200, json={'name':f'ref-{len(requests)}.png','subfolder':'','type':'input'})
        return edit_service(requests)(request)
    result = await ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service)).generate('blend', {'references':[A,B], 'upscale':2})
    assert [r.url.path for r in requests if r.method=='POST'] == ['/upload/image','/upload/image','/prompt']
    graph = json.loads(next(r.content for r in requests if r.url.path=='/prompt'))['prompt']
    assert {n['inputs']['image'] for n in graph.values() if n['class_type']=='LoadImage'} == {'ref-1.png','ref-2.png'}
    assert (tmp_path / (result['artifact_id'] + '.png')).read_bytes() == PNG
