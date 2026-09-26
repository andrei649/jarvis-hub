"""Explicit, transient browser vision turns; legacy VLM inputs stay separate."""

import base64
import binascii
import hashlib
import io
import json
import secrets
import sqlite3
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json


class _BoundedValidationRoute(APIRoute):
    """A refused body is answered with its first reason, never FastAPI's default 422,
    which echoes every rejected image back (megabytes) and hides the reason under
    ``detail[0].msg`` (review-H586 m3). The HUD and the CLI both read ``error``."""

    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def bounded_route_handler(request: Request):
            try:
                return await route_handler(request)
            except RequestValidationError as exc:
                errors = exc.errors()
                first = errors[0].get("msg", "") if errors and isinstance(errors[0], dict) else ""
                reason = str(first).removeprefix("Value error, ")[:200] or "invalid request"
                return nocache_json({"error": reason, "reason": "vlm_invalid_request"},
                                    status_code=422)

        return bounded_route_handler


router = APIRouter(tags=["multimodal"], dependencies=[Depends(user_guard)],
                   route_class=_BoundedValidationRoute)
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_URI = 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 32
# Accept ordinary 4K screenshots/panoramas, bound decode before allocation, then
# let the existing bytes encoder downscale to its 1024-pixel model-input edge.
MAX_IMAGE_EDGE = 8192
MAX_IMAGE_PIXELS = 16 * 1024 * 1024


def validate_raster(raw, mime):
    from PIL import Image, UnidentifiedImageError

    expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/gif": "GIF", "image/webp": "WEBP"}[
        mime
    ]
    try:
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            if image.format != expected:
                raise ValueError("raster format differs from MIME type")
            if (
                width < 1
                or height < 1
                or max(width, height) > MAX_IMAGE_EDGE
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise ValueError("raster dimensions exceed bounded decode limit")
            if getattr(image, "is_animated", False):
                raise ValueError("animated images are not supported")
            image.verify()
        # verify() alone does not fully decode JPEG/GIF. Allocation is now bounded
        # to one static image, at most 16 MP, independent of attacker header sizes.
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
    ) as error:
        raise ValueError("invalid, animated or excessive raster image") from error


def destination_revision(config):
    """Public nonce independent of credential entropy, stable across workers.

    Only a private fingerprint and random revision are stored, never image bytes
    or raw endpoint credentials. This fixed metadata key grants no new authority.
    """
    from agents.core import settings_db

    fingerprint = hashlib.sha256(
        json.dumps([config.backend, config.base_url, config.model, config.is_local]).encode()
    ).hexdigest()
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM settings WHERE category='composer_vision' AND key='destination_revision'"
        ).fetchone()
        try:
            stored = json.loads(row["value"]) if row else {}
        except (ValueError, TypeError):
            stored = {}
        if (
            isinstance(stored, dict)
            and stored.get("fingerprint") == fingerprint
            and isinstance(stored.get("revision"), str)
            and len(stored["revision"]) == 64
        ):
            return stored["revision"]
        revision = secrets.token_hex(32)
        document = json.dumps({"fingerprint": fingerprint, "revision": revision})
        conn.execute(
            """INSERT INTO settings(category,key,value,label,kind,opts)
                     VALUES('composer_vision','destination_revision',?,'Vision destination revision','json','[]')
                     ON CONFLICT(category,key) DO UPDATE SET value=excluded.value""",
            (document,),
        )
        conn.commit()
        return revision
    finally:
        conn.close()


def public_config(config):
    parts = urlsplit(config.base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("invalid vision destination")
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    if parts.port:
        host += f":{parts.port}"
    destination = urlunsplit((parts.scheme, host, parts.path, "", ""))
    binding = destination_revision(config)
    return {
        "destination": destination,
        "binding": binding,
        "model": config.model,
        "backend": config.backend,
        "local": config.is_local,
    }


class ComposerVisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=4000)
    images: list[Annotated[str, Field(max_length=MAX_URI)]] = Field(min_length=1, max_length=8)
    expected_destination: str = Field(min_length=1, max_length=2048)
    expected_binding: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]+$")
    remote_ack: bool = False

    @field_validator("prompt")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("image question is empty")
        return value

    @field_validator("images")
    @classmethod
    def raster_data(cls, images):
        for image in images:
            header, sep, payload = image.partition(",")
            mime = header.removeprefix("data:").removesuffix(";base64")
            if (
                not sep
                or header != f"data:{mime};base64"
                or mime not in ("image/png", "image/jpeg", "image/gif", "image/webp")
            ):
                raise ValueError("bounded raster data URI required")
            try:
                raw = base64.b64decode(payload, validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("invalid image encoding") from None
            if not raw or len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("image exceeds 4 MiB")
            valid = (
                mime == "image/png"
                and raw.startswith(b"\x89PNG\r\n\x1a\n")
                or mime == "image/jpeg"
                and raw.startswith(b"\xff\xd8\xff")
                or mime == "image/gif"
                and raw[:6] in (b"GIF87a", b"GIF89a")
                or mime == "image/webp"
                and raw[:4] == b"RIFF"
                and raw[8:12] == b"WEBP"
            )
            if not valid:
                raise ValueError("image signature does not match raster MIME type")
            validate_raster(raw, mime)
        return images


@router.get("/api/vlm/composer/status")
async def composer_status():
    from agents.core.llm.vlm import VLMNotConfigured, resolve_vlm_config

    try:
        return nocache_json(
            dict(configured=True, reachable=None, **public_config(resolve_vlm_config()))
        )
    except (VLMNotConfigured, ValueError, sqlite3.Error, OSError):
        return nocache_json(
            {"configured": False, "reason": "vlm_not_configured", "reachable": None}
        )


@router.post("/api/vlm/composer/describe")
async def composer_describe(body: ComposerVisionBody):
    from agents.core.llm.vlm import VLMBackend, VLMNotConfigured, resolve_vlm_config

    try:
        config = resolve_vlm_config()
        public = public_config(config)
    except (VLMNotConfigured, ValueError, sqlite3.Error, OSError):
        return nocache_json(
            {"error": "Vision model unavailable", "reason": "vlm_not_configured"}, status_code=503
        )
    if (
        body.expected_destination != public["destination"]
        or body.expected_binding != public["binding"]
    ):
        return nocache_json(
            {
                "error": "Vision destination changed; review it again",
                "reason": "vlm_destination_changed",
            },
            status_code=409,
        )
    if not config.is_local and not body.remote_ack:
        return nocache_json(
            {
                "error": "Acknowledge the remote vision destination",
                "reason": "vlm_remote_ack_required",
            },
            status_code=403,
        )
    backend = None
    try:
        backend = VLMBackend(base_url=config.base_url, api_key=config.api_key)
        answer = await backend.generate_vision_checked(
            config.model,
            body.prompt,
            images=[base64.b64decode(image.partition(",")[2]) for image in body.images],
        )
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty vision answer")
        return nocache_json(
            dict(ok=True, response=answer, **{k: v for k, v in public.items() if k != "binding"})
        )
    except Exception:
        return nocache_json(
            {"error": "Vision analysis failed", "reason": "vlm_generation_failed"}, status_code=502
        )
    finally:
        if backend is not None:
            await backend.aclose()
