"""One bounded, unretried OpenAI-images-compatible POST to literal loopback."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..llm.data_handling import DataHandlingRefused
from ..llm.direct_transport import require_direct_async_transport
from .comfyui import ImageGenerationError, implementation_fingerprint, save_artifact, validate_png
from .registry import local_endpoint, normalize_options, registry_fingerprint, strict_json

_IMPORTED_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class LocalOpenAIImageConfig:
    base_url: str
    model: str
    output_root: Path
    timeout: float = 120.0
    max_json_bytes: int = 24 * 1024 * 1024
    max_image_bytes: int = 16 * 1024 * 1024

    def fingerprint(self):
        try:
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _IMPORTED_SHA:
                raise ImageGenerationError('backend_source_changed')
        except OSError:
            raise ImageGenerationError('backend_source_changed') from None
        value = {'url': self.base_url, 'model': self.model, 'root': str(self.output_root),
                 'protocol': 'openai_images', 'timeout': self.timeout, 'json': self.max_json_bytes,
                 'image': self.max_image_bytes, 'backend_sha256': _IMPORTED_SHA,
                 'registry_sha256': registry_fingerprint(), 'shared_sha256': implementation_fingerprint()}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class LocalOpenAIImageBackend:
    def __init__(self, config: LocalOpenAIImageConfig, *, transport=None):
        self.config = config
        self._transport = transport

    async def generate(self, prompt, options, *, guard=None):
        config = self.config
        config.fingerprint()
        if local_endpoint(config.base_url) != config.base_url:
            raise ImageGenerationError('invalid_endpoint')
        opts = normalize_options(prompt, options, config)
        body = {'model': config.model, 'prompt': prompt, 'size': f"{opts['width']}x{opts['height']}",
                'n': 1, 'response_format': 'b64_json'}
        url = config.base_url + '/v1/images/generations'
        def recheck():
            config.fingerprint()
            if guard is not None:
                guard()
        try:
            async with asyncio.timeout(config.timeout):
                async with httpx.AsyncClient(trust_env=False, follow_redirects=False, transport=self._transport,
                                             headers={'Accept-Encoding': 'identity'},
                                             timeout=httpx.Timeout(120.0, connect=3.0)) as client:
                    async def physical(request):
                        recheck()
                        try:
                            require_direct_async_transport(client, request.url)
                        except DataHandlingRefused:
                            raise ImageGenerationError('direct_transport_refused') from None
                        if (str(request.url) != url or request.method != 'POST'
                                or 'authorization' in request.headers or 'cookie' in request.headers
                                or strict_json(request.content) != body):
                            raise ImageGenerationError('physical_request_changed')
                    client.event_hooks['request'].append(physical)
                    async with client.stream('POST', url, json=body) as response:
                        if response.headers.get('content-encoding', 'identity').strip().lower() not in {'', 'identity'}:
                            raise ImageGenerationError('content_encoding_refused')
                        if 300 <= response.status_code < 400:
                            raise ImageGenerationError('redirect_refused')
                        if response.status_code != 200:
                            raise ImageGenerationError('backend_http_error')
                        if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                            raise ImageGenerationError('invalid_response')
                        length = response.headers.get('content-length')
                        if length is not None:
                            if not length.isascii() or not length.isdecimal():
                                raise ImageGenerationError('invalid_response')
                            if len(length) > 12 or int(length) > config.max_json_bytes:
                                raise ImageGenerationError('response_too_large')
                        data = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            if len(data) + len(chunk) > config.max_json_bytes:
                                raise ImageGenerationError('response_too_large')
                            data.extend(chunk)
                # Close is awaited before publication; config/approval changes during it refuse.
                recheck()
                try:
                    result = strict_json(data)
                    entries = result['data']
                    if not isinstance(entries, list) or len(entries) != 1 or set(entries[0]) != {'b64_json'}:
                        raise ValueError('invalid image item')
                    encoded = entries[0]['b64_json']
                    if not isinstance(encoded, str) or len(encoded) > 4 * ((config.max_image_bytes + 2) // 3):
                        raise ValueError('invalid base64')
                    png = base64.b64decode(encoded, validate=True)
                    if len(png) > config.max_image_bytes:
                        raise ValueError('decoded bound')
                except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, binascii.Error):
                    raise ImageGenerationError('invalid_response') from None
                dimensions = validate_png(png)
                if dimensions != (opts['width'], opts['height']):
                    raise ImageGenerationError('image_dimensions_mismatch')
                return save_artifact(config.output_root, png, *dimensions, guard=recheck)
        except TimeoutError:
            raise ImageGenerationError('generation_timeout_submission_may_continue') from None
        except httpx.HTTPError:
            raise ImageGenerationError('submission_unknown') from None
