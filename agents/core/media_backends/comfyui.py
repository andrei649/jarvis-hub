"""Bounded, loopback-only ComfyUI transport for two fixed workflows: text-to-image
and an edit of an artifact this hub already generated.

This module does not grant permission to generate. The governed runtime owns
approval and the durable single-use attempt before calling this transport.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import struct
import tempfile
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ..env_config import truthy

_IMPORTED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_READ_CHUNK_BYTES = 64 * 1024


class ImageGenerationError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ComfyUIConfig:
    base_url: str
    checkpoint: str
    output_root: Path
    timeout: float = 120.0
    poll_interval: float = 0.5
    max_json_bytes: int = 1024 * 1024
    max_image_bytes: int = 16 * 1024 * 1024

    @classmethod
    def from_env(cls, env=None, *, output_root=None):
        env = os.environ if env is None else env
        if not truthy(env.get("JARVIS_LOCAL_IMAGE_GENERATION")):
            return None
        checkpoint = env.get("JARVIS_COMFYUI_CHECKPOINT", "")
        if not checkpoint:
            raise ImageGenerationError("checkpoint_required")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,160}\.safetensors", checkpoint):
            raise ImageGenerationError("invalid_checkpoint")
        raw = env.get("JARVIS_COMFYUI_URL", "http://127.0.0.1:8188")
        try:
            url = urlsplit(raw)
            port = url.port
            valid = (
                url.scheme == "http" and url.hostname in {"127.0.0.1", "::1"}
                and port is not None and 1 <= port <= 65535
                and url.username is None and url.password is None
                and url.path in {"", "/"} and not url.query and not url.fragment
                and not any(char.isspace() for char in raw)
                and "?" not in raw and "#" not in raw
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ImageGenerationError("invalid_endpoint")
        if output_root is None:
            from ..paths import data_path
            output_root = data_path("media", "generated")
        host = "[::1]" if url.hostname == "::1" else "127.0.0.1"
        return cls(f"http://{host}:{port}", checkpoint, Path(output_root).resolve())

    def fingerprint(self) -> str:
        # Include implementation bytes: a queued approval does not authorize a
        # changed workflow/backend after a software update.
        try:
            current_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        except OSError:
            raise ImageGenerationError("backend_source_changed") from None
        if current_hash != _IMPORTED_SOURCE_SHA256:
            raise ImageGenerationError("backend_source_changed")
        encoded = json.dumps({
            "url": self.base_url, "checkpoint": self.checkpoint,
            "root": str(self.output_root), "timeout": self.timeout,
            "backend_sha256": _IMPORTED_SOURCE_SHA256,
        }, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()


ARTIFACT_ID = re.compile(r"[a-f0-9]{32}")
OPTION_KEYS = ("seed", "width", "height", "steps", "reference", "strength")


def validate_options(prompt, options):
    """Normalize one generation's options into the exact dict the approval will bind.

    Two shapes, never mixed. Without ``reference`` this is text-to-image and the
    caller chooses the canvas. With one it is an *edit*: the size comes from the
    reference's own pixels, so ``width``/``height`` are refused rather than accepted
    and silently ignored — an ignored option is a lie told to whoever approves it.
    """
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise ImageGenerationError("invalid_prompt")
    if not isinstance(options, dict) or set(options) - set(OPTION_KEYS):
        raise ImageGenerationError("invalid_options")
    reference = options.get("reference")
    if reference is None:
        if "reference" in options or "strength" in options:
            raise ImageGenerationError("invalid_options")
        result = {"seed": 0, "width": 512, "height": 512, "steps": 20, **options}
        bounds = (("seed", 0, 2**63 - 1), ("width", 64, 1024), ("height", 64, 1024), ("steps", 1, 40))
    else:
        if "width" in options or "height" in options:
            raise ImageGenerationError("invalid_options")
        # The id is the whole handle. Nothing here accepts a host path, a URL or a
        # filename, so no argument can point the edit at a file outside the artifact
        # root — see ``artifact_bytes``.
        if not isinstance(reference, str) or not ARTIFACT_ID.fullmatch(reference):
            raise ImageGenerationError("invalid_options")
        result = {"seed": 0, "steps": 20, "strength": 60, **options}
        bounds = (("seed", 0, 2**63 - 1), ("steps", 1, 40), ("strength", 1, 100))
    for key, low, high in bounds:
        value = result[key]
        if type(value) is not int or not low <= value <= high:
            raise ImageGenerationError("invalid_options")
    if reference is None and (result["width"] % 64 or result["height"] % 64):
        raise ImageGenerationError("invalid_options")
    return result


def artifact_bytes(artifact_id, root):
    """Read one already-generated PNG out of the artifact root, by opaque id only.

    This is the single reader for both the HTTP artifact route and the edit path, so
    a reference image is reachable on exactly the terms a download is: a 32-hex id
    this hub minted, resolving to a real file directly inside the root. A symlink, a
    path that resolves elsewhere, an oversized file or bytes that are not the PNG
    subset ``validate_png`` accepts are all one refusal — the caller learns that the
    reference is unusable, not which of those it was.
    """
    if not isinstance(artifact_id, str) or not ARTIFACT_ID.fullmatch(artifact_id):
        raise ImageGenerationError("reference_not_found")
    root = Path(root).resolve()
    candidate = root / (artifact_id + ".png")
    try:
        if candidate.is_symlink() or candidate.resolve() != candidate or candidate.parent != root:
            raise OSError
        with candidate.open("rb") as handle:
            data = handle.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise OSError
        validate_png(data)
    except (OSError, ImageGenerationError):
        raise ImageGenerationError("reference_not_found") from None
    return data


def _workflow(config, prompt, opts, reference_name=None):
    """One graph in two fixed shapes. Node "9" is the only output in both, so the
    result extraction never has to ask which shape ran.

    Text-to-image samples an empty latent at full denoise. An edit encodes the
    owner's own uploaded artifact into the latent instead and samples it at
    ``strength`` — denoise below 1 is precisely what makes the result an edit of
    that image rather than a fresh one that merely shares the prompt.
    """
    graph = {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": opts["seed"], "steps": opts["steps"], "cfg": 7,
            "sampler_name": "euler", "scheduler": "normal", "denoise": 1,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
        }},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": config.checkpoint}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "nerva", "images": ["8", 0]}},
    }
    if reference_name is None:
        graph["5"] = {"class_type": "EmptyLatentImage", "inputs": {
            "width": opts["width"], "height": opts["height"], "batch_size": 1}}
        return graph
    graph["3"]["inputs"]["latent_image"] = ["10", 0]
    graph["3"]["inputs"]["denoise"] = opts["strength"] / 100
    graph["10"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["11", 0], "vae": ["4", 2]}}
    graph["11"] = {"class_type": "LoadImage", "inputs": {"image": reference_name, "upload": "image"}}
    return graph


def validate_png(data: bytes):
    """Validate the fixed writer's static, noninterlaced 8-bit PNG output.

    Framing/CRC alone accepts corrupt compressed pixels. Bound inflation to the
    IHDR scanline size and validate filters before publishing any bytes. This
    deliberately supports the grayscale/RGB (+alpha) subset emitted by SaveImage,
    not palette, interlaced or animated images. PNG rules: https://www.w3.org/TR/png-3/
    """
    if len(data) > 16 * 1024 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ImageGenerationError("invalid_image")
    pos, chunks, dimensions, has_data = 8, 0, None, False
    compressed = bytearray()
    data_ended, channels = False, 0
    while pos + 12 <= len(data):
        size = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + size
        if end > len(data) or chunks >= 4096 or not re.fullmatch(b"[A-Za-z]{4}", kind):
            break
        body = data[pos + 8:pos + 8 + size]
        crc = struct.unpack_from(">I", data, pos + 8 + size)[0]
        if zlib.crc32(kind + body) != crc:
            break
        if chunks == 0:
            if kind != b"IHDR" or size != 13:
                break
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color, 0)
            if not (0 < width <= 1024 and 0 < height <= 1024 and channels
                    and depth == 8 and compression == filtering == interlace == 0):
                break
            dimensions = (width, height)
        elif kind == b"IHDR":
            break
        elif kind == b"IDAT":
            if data_ended:
                break
            compressed.extend(body)
        elif kind != b"IEND":
            # Unsupported critical data and compressed metadata are outside the
            # fixed SaveImage contract and must not reach the browser decoder.
            if kind[0] < ord("a") or kind in {b"acTL", b"fcTL", b"fdAT", b"zTXt", b"iCCP"}:
                break
            if kind == b"iTXt":
                # SaveImage/Pillow uses uncompressed international text for a
                # non-Latin-1 prompt. Flag=1 would make a browser inflate data
                # outside our pixel-size budget, so only flag=method=0 is valid.
                keyword, separator, rest = body.partition(b"\0")
                if (not separator or not 1 <= len(keyword) <= 79
                        or rest[:2] != b"\0\0" or len(rest[2:].split(b"\0", 2)) != 3):
                    break
            data_ended |= has_data
        has_data |= kind == b"IDAT"
        if kind == b"IEND":
            if size == 0 and end == len(data) and dimensions and has_data:
                stride = dimensions[0] * channels + 1
                expected = stride * dimensions[1]
                decoder = zlib.decompressobj()
                try:
                    pixels = decoder.decompress(compressed, expected + 1)
                except zlib.error:
                    break
                if (len(pixels) != expected or not decoder.eof or decoder.unused_data
                        or decoder.unconsumed_tail or any(pixels[row] > 4 for row in range(0, expected, stride))):
                    break
                return dimensions
            break
        pos, chunks = end, chunks + 1
    raise ImageGenerationError("invalid_image")


class ComfyUIBackend:
    def __init__(self, config: ComfyUIConfig, *, transport=None):
        self.config = config
        self._transport = transport

    async def _request(self, client, method, path, *, binary=False, **kwargs):
        limit = self.config.max_image_bytes if binary else self.config.max_json_bytes
        async with client.stream(method, self.config.base_url + path, **kwargs) as response:
            if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
                raise ImageGenerationError("content_encoding_refused")
            if 300 <= response.status_code < 400:
                raise ImageGenerationError("redirect_refused")
            if response.status_code != 200:
                raise ImageGenerationError("backend_http_error")
            if binary and response.headers.get("content-type", "").split(";")[0].lower() != "image/png":
                raise ImageGenerationError("invalid_image")
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=_READ_CHUNK_BYTES):
                if len(data) + len(chunk) > limit:
                    raise ImageGenerationError("response_too_large")
                data.extend(chunk)
        if binary:
            return bytes(data)
        try:
            value = json.loads(data)
        except (ValueError, UnicodeError, RecursionError):
            raise ImageGenerationError("invalid_response") from None
        if not isinstance(value, dict):
            raise ImageGenerationError("invalid_response")
        return value

    async def _upload(self, client, data):
        """Put the reference into ComfyUI's own input directory; LoadImage reads
        nothing else.

        The name we send is fixed. The name we *use* is the one the service returns,
        because it renames on collision — and that returned name is re-validated
        before it may reach a workflow node, so the transport still chooses no
        filename on the strength of a response body.
        """
        try:
            body = await self._request(
                client, "POST", "/upload/image",
                files={"image": ("nerva-reference.png", data, "image/png")},
                data={"type": "input", "subfolder": "", "overwrite": "false"},
            )
        except httpx.HTTPError:
            # The /prompt rule applies here too: a POST whose outcome we cannot
            # observe is never retried, not even after a restart.
            raise ImageGenerationError("reference_upload_unknown") from None
        name = body.get("name")
        if (not isinstance(name, str)
                or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_. ()-]{0,180}\.png", name)
                or body.get("subfolder") not in {"", None} or body.get("type") != "input"):
            raise ImageGenerationError("invalid_response")
        return name

    async def generate(self, prompt, options):
        self.config.fingerprint()
        opts = validate_options(prompt, options)
        # Resolved before a socket is opened. An unusable reference must not cost a
        # submission whose outcome we would then be unable to observe.
        reference = artifact_bytes(opts["reference"], self.config.output_root) if "reference" in opts else None
        try:
            async with asyncio.timeout(self.config.timeout):
                async with httpx.AsyncClient(
                    trust_env=False, follow_redirects=False, transport=self._transport,
                    headers={"Accept-Encoding": "identity"},
                    timeout=httpx.Timeout(10.0, connect=3.0),
                ) as client:
                    reference_name = None if reference is None else await self._upload(client, reference)
                    try:
                        submitted = await self._request(client, "POST", "/prompt", json={"prompt": _workflow(self.config, prompt, opts, reference_name)})
                    except httpx.HTTPError:
                        # A response timeout cannot tell us whether ComfyUI queued
                        # the job. Never retry POST, including after restart.
                        raise ImageGenerationError("submission_unknown") from None
                    prompt_id = submitted.get("prompt_id")
                    if not isinstance(prompt_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", prompt_id) or submitted.get("node_errors"):
                        raise ImageGenerationError("invalid_response")
                    while True:
                        history = await self._request(client, "GET", "/history/" + prompt_id)
                        entry = history.get(prompt_id)
                        if entry is not None:
                            break
                        await asyncio.sleep(self.config.poll_interval)
                    if not isinstance(entry, dict):
                        raise ImageGenerationError("invalid_response")
                    status = entry.get("status", {})
                    if not isinstance(status, dict) or status.get("status_str") != "success" or status.get("completed") is not True:
                        raise ImageGenerationError("generation_failed")
                    try:
                        images = entry["outputs"]["9"]["images"]
                        if not isinstance(images, list) or len(images) != 1:
                            raise KeyError
                        output = images[0]
                        filename = output["filename"]
                        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,180}\.png", filename):
                            raise KeyError
                        if output.get("subfolder") != "" or output.get("type") != "output":
                            raise KeyError
                    except (KeyError, TypeError):
                        raise ImageGenerationError("invalid_output") from None
                    data = await self._request(client, "GET", "/view", binary=True, params={"filename": filename, "subfolder": "", "type": "output"})
                    width, height = validate_png(data)
        except TimeoutError:
            raise ImageGenerationError("generation_timeout_submission_may_continue") from None
        except httpx.HTTPError:
            raise ImageGenerationError("backend_unavailable_submission_may_continue") from None
        # Only validated bytes cross to the filesystem. Backend names never
        # choose a destination and exclusive creation never overwrites a file.
        artifact_id = uuid.uuid4().hex
        destination = self.config.output_root / (artifact_id + ".png")
        temporary = None
        try:
            self.config.output_root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.config.output_root,
                                             prefix=".nerva-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # Both files are on the same filesystem. link is atomic and refuses
            # an existing destination on Windows and POSIX; replace would erase
            # an unrelated artifact on a collision. Unsupported filesystems fail.
            os.link(temporary, destination)
        except OSError:
            raise ImageGenerationError("artifact_write_failed") from None
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink(missing_ok=True)
        return {"path": str(destination), "artifact_id": artifact_id, "prompt_id": prompt_id,
                "bytes": len(data), "width": width, "height": height}
