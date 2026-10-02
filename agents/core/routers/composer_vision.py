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
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from agents.core.llm.vision_review import VisionReviewRefused, VisionReviewStore
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
_REVIEWS = VisionReviewStore()
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


def destination_revision(config, *, identity=None):
    """Public nonce independent of credential entropy, stable across workers.

    Only a private fingerprint and random revision are stored, never image bytes
    or raw endpoint credentials. This fixed metadata key grants no new authority.
    """
    from agents.core import settings_db
    from agents.core.llm.vision_policy import describe

    fingerprint = hashlib.sha256(
        json.dumps((identity if identity is not None else describe(config)).binding).encode()
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


def public_config(config, *, identity=None):
    from agents.core.llm.vision_policy import describe
    identity = identity if identity is not None else describe(config)
    parts = urlsplit(config.base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("invalid vision destination")
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    if parts.port:
        host += f":{parts.port}"
    destination = urlunsplit((parts.scheme, host, parts.path, "", ""))
    binding = destination_revision(config, identity=identity)
    return {
        "destination": destination,
        "binding": binding,
        "model": config.model,
        "backend": config.backend,
        "local": config.is_local,
        **({"selection_source": config.route_source} if config.route_source else {}),
        **identity.public(),
    }


class ComposerVisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=4000)
    images: list[Annotated[str, Field(max_length=MAX_URI)]] = Field(min_length=1, max_length=8)
    expected_destination: str = Field(min_length=1, max_length=2048)
    expected_binding: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]+$")
    remote_ack: bool = False
    acknowledge_training: StrictBool = False
    confirm_expensive: StrictBool = False

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


class ComposerPrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=4000)
    agent: str = Field(default="jarvis", min_length=1, max_length=64,
                       pattern=r"^[a-z][a-z0-9_-]*$")
    session_id: str | None = None
    selected_turn: StrictBool = False
    image_digests: list[Annotated[str, Field(min_length=64, max_length=64,
                                             pattern=r"^[0-9a-f]{64}$")]] | None = Field(
                                                 default=None, min_length=1, max_length=8)

    @field_validator("prompt")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("image question is empty")
        return value

    @field_validator("session_id")
    @classmethod
    def valid_session(cls, value):
        from agents.core.validation import is_valid_session_id
        if value is not None and not is_valid_session_id(value):
            raise ValueError("invalid session_id")
        return value

    @model_validator(mode="after")
    def selected_images_bound(self):
        if self.selected_turn and not self.image_digests:
            raise ValueError("selected image digests are required")
        if not self.selected_turn and self.image_digests is not None:
            raise ValueError("image digests require a selected turn")
        return self


class PreparedComposerVisionBody(ComposerVisionBody):
    review_token: str = Field(min_length=20, max_length=128)
    agent: str = Field(default="jarvis", min_length=1, max_length=64,
                       pattern=r"^[a-z][a-z0-9_-]*$")
    session_id: str | None = None
    selected_turn: StrictBool = False

    @field_validator("session_id")
    @classmethod
    def valid_session(cls, value):
        from agents.core.validation import is_valid_session_id
        if value is not None and not is_valid_session_id(value):
            raise ValueError("invalid session_id")
        return value


async def _prepare_config(*, refresh_catalog: bool = False, main_config=None):
    from agents.core.env_config import env_str
    from agents.core.llm.vlm import resolve_vlm_config

    provider = env_str("JARVIS_ROLE_VISION_PROVIDER", "").strip().lower()
    if provider == "deepinfra":
        from agents.core.llm.vision_deepinfra import prepare_config
        return await prepare_config(force_refresh=refresh_catalog)
    if provider == "nous":
        from agents.core.llm.vision_nous import prepare_config
        return await prepare_config(force_refresh=refresh_catalog)
    if provider == "auto":
        from agents.core.llm.vision_auto import prepare_config
        return await prepare_config(force_refresh=refresh_catalog, main_config=main_config)
    return resolve_vlm_config()


async def _selected_config(*, prompt: str, agent: str, session_id: str | None,
                           refresh_catalog: bool = False):
    """Rebuild a conversation image turn before issuing or consuming a review."""
    from agents.core.app_state import get_orch
    from agents.core.env_config import env_str
    from agents.core.llm.hybrid_router import LOCAL_ONLY_AGENTS
    from agents.core.llm.vision_turn import prepare_selected_image_turn
    from agents.core.llm.vlm import VLMNotConfigured

    orch = get_orch()
    if orch is None:
        raise VLMNotConfigured("vlm_orchestrator_unavailable")
    sid = session_id or orch.session_id
    if sid != orch.session_id:
        # The HUD's image draft belongs to the shared conversation currently
        # displayed. A reset/resume cannot silently send an older session.
        raise VLMNotConfigured("vlm_session_changed")
    turn = await prepare_selected_image_turn(orch, question=prompt, agent_id=agent, session_id=sid)
    main = None
    if env_str("JARVIS_ROLE_VISION_PROVIDER", "").strip().lower() == "auto":
        main = _main_candidate(turn.backend, turn.model, turn.route)
        if main is None and agent in LOCAL_ONLY_AGENTS:
            raise VLMNotConfigured("vlm_local_only_unavailable")
    config = await _prepare_config(refresh_catalog=refresh_catalog, main_config=main)
    if agent in LOCAL_ONLY_AGENTS and not config.is_local:
        raise VLMNotConfigured("vlm_local_only_unavailable")
    return turn, config


def _main_candidate(backend, model, route):
    from agents.core.llm.vision_capability import main_vision_eligibility
    from agents.core.llm.vision_main import selected_main_config

    if main_vision_eligibility(backend, model) is False:
        return None
    return selected_main_config(backend, model, route)


def _review_route(config, turn=None):
    route = config.route_source or f"explicit:{config.backend}"
    return f"turn:{turn.prompt_digest}:{route}" if turn is not None else route


def _review_binding(identity, *, turn=None, image_digests=None):
    if turn is None:
        return identity.binding
    return identity.binding + ("reviewed-image-digests:v1", tuple(image_digests))


def _selected_resolver(turn):
    """Synchronous config check used by the final physical-request guard."""
    from agents.core.app_state import get_orch
    from agents.core.env_config import env_str
    from agents.core.llm.vision_auto import resolve_config as resolve_auto
    from agents.core.llm.vision_turn import history_fingerprint
    from agents.core.llm.vlm import resolve_vlm_config

    orch = get_orch()
    if (orch is None or orch.session_id != turn.session_id
            or history_fingerprint(orch, turn.session_id) != turn.history_digest):
        raise ValueError("image history changed")
    backend, model, route = orch.llm_router.select_backend(turn.agent_id, turn.prompt)
    if backend is not turn.backend or model != turn.model or route != turn.route:
        raise ValueError("image selected route changed")
    if env_str("JARVIS_ROLE_VISION_PROVIDER", "").strip().lower() == "auto":
        return resolve_auto(main_config=_main_candidate(backend, model, route))
    return resolve_vlm_config()


@router.get("/api/vlm/composer/status")
async def composer_status(refresh_catalog: bool = False):
    from agents.core.llm.vision_policy import VisionPolicyUnavailable
    from agents.core.llm.vlm import VLMNotConfigured

    try:
        config = await _prepare_config(refresh_catalog=refresh_catalog)
        return nocache_json(
            dict(configured=True, reachable=None, **public_config(config))
        )
    except (VLMNotConfigured, ValueError, VisionPolicyUnavailable, sqlite3.Error, OSError):
        return nocache_json(
            {"configured": False, "reason": "vlm_not_configured", "reachable": None}
        )


@router.post("/api/vlm/composer/prepare")
async def composer_prepare(body: ComposerPrepareBody, refresh_catalog: bool = False):
    """Review one prompt's configured destination before image bytes are sent."""
    from agents.core.llm.vision_policy import VisionPolicyUnavailable, describe
    from agents.core.llm.vlm import VLMNotConfigured

    try:
        turn, config = (await _selected_config(
            prompt=body.prompt, agent=body.agent, session_id=body.session_id,
            refresh_catalog=refresh_catalog,
        ) if body.selected_turn else (None, await _prepare_config(refresh_catalog=refresh_catalog)))
        identity = describe(config)
        public = public_config(config, identity=identity)
        token = _REVIEWS.issue(
            session_id=turn.session_id if turn is not None else body.session_id or "web",
            agent_id=body.agent,
            prompt=body.prompt, model=config.model,
            route=_review_route(config, turn),
            binding=_review_binding(identity, turn=turn, image_digests=body.image_digests),
        )
        return nocache_json(dict(configured=True, reachable=None,
                                 review_token=token,
                                 **({"session_id": turn.session_id, "selected_turn": True}
                                    if turn is not None else {}),
                                 **public))
    except VisionReviewRefused as exc:
        return nocache_json({"error": "Vision review unavailable", "reason": exc.reason},
                            status_code=503)
    except (VLMNotConfigured, ValueError, VisionPolicyUnavailable, sqlite3.Error, OSError):
        return nocache_json({"error": "Vision model unavailable",
                             "reason": "vlm_not_configured"}, status_code=503)


@router.post("/api/vlm/composer/describe-prepared")
async def composer_describe_prepared(body: PreparedComposerVisionBody):
    """Consume a reviewed route before invoking the existing physical guard."""
    from agents.core.llm.vision_policy import VisionPolicyUnavailable, describe
    from agents.core.llm.vlm import VLMNotConfigured, resolve_vlm_config

    try:
        turn, config = (await _selected_config(
            prompt=body.prompt, agent=body.agent, session_id=body.session_id,
        ) if body.selected_turn else (None, resolve_vlm_config()))
        identity = describe(config)
        _REVIEWS.consume(
            body.review_token,
            session_id=turn.session_id if turn is not None else body.session_id or "web",
            agent_id=body.agent, prompt=body.prompt, model=config.model,
            route=_review_route(config, turn),
            binding=_review_binding(
                identity, turn=turn,
                image_digests=[hashlib.sha256(image.encode("utf-8")).hexdigest()
                               for image in body.images] if turn is not None else None,
            ),
        )
    except VisionReviewRefused as exc:
        reason = ("vlm_destination_changed" if exc.reason == "vlm_destination_changed"
                  else exc.reason)
        return nocache_json({"error": "Vision review changed; review it again",
                             "reason": reason}, status_code=409)
    except (VLMNotConfigured, ValueError, VisionPolicyUnavailable, sqlite3.Error, OSError):
        return nocache_json({"error": "Vision destination changed; review it again",
                             "reason": "vlm_destination_changed"}, status_code=409)
    if turn is not None:
        return await _composer_describe_with_config(
            body, config, resolve_config=lambda: _selected_resolver(turn),
            image_prompt=turn.prompt,
        )
    return await composer_describe(body)


@router.post("/api/vlm/composer/describe")
async def composer_describe(body: ComposerVisionBody):
    from agents.core.llm.vision_policy import VisionPolicyUnavailable
    from agents.core.llm.vlm import VLMNotConfigured, resolve_vlm_config

    try:
        config = resolve_vlm_config()
    except (VLMNotConfigured, ValueError, VisionPolicyUnavailable, sqlite3.Error, OSError):
        return nocache_json(
            {"error": "Vision model unavailable", "reason": "vlm_not_configured"}, status_code=503
        )
    return await _composer_describe_with_config(body, config, resolve_config=resolve_vlm_config)


async def _composer_describe_with_config(body, config, *, resolve_config, image_prompt=None):
    from agents.core.commands import Principal
    from agents.core.llm import selection_guards as sg
    from agents.core.llm.vision_policy import (
        VisionDestinationChanged,
        VisionPolicyUnavailable,
        canonical_selection_findings,
        composer_request_scope,
        describe,
    )
    from agents.core.llm.vlm import VLMBackend, VLMNotConfigured

    try:
        identity = describe(config)
        public = public_config(config, identity=identity)
    except (VLMNotConfigured, ValueError, VisionPolicyUnavailable, sqlite3.Error, OSError):
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
        findings = sg.enforce([identity.selection_choice(config.model)],
                              acknowledge_training=body.acknowledge_training,
                              confirm_expensive=body.confirm_expensive)
        if canonical_selection_findings(findings) != identity.selection_findings:
            raise VisionDestinationChanged('vision selection policy changed')
        sg.record(findings, 'composer_vision')
        try:
            backend = VLMBackend(base_url=config.base_url, api_key=config.api_key, composer_auth=True,
                                 **({"provider_id": config.backend} if config.backend in ("openrouter", "deepinfra", "nous", "ollama", "anthropic", "gemini", "openai-responses", "xai") else {}),
                                 **({"wire_mode": config.wire_mode} if config.backend in ("nous", "ollama", "anthropic", "gemini", "openai-responses", "xai") else {}),
                                 **({"prompt_cache_retention": config.prompt_cache_retention}
                                    if config.backend == "openai-responses" else {}),
                                 **({"reasoning_effort": config.reasoning_effort}
                                    if config.backend == "xai" else {}))
            with composer_request_scope(config, backend, resolve_config=resolve_config,
                                        remote_ack=body.remote_ack, principal=Principal(channel="web", admin=False),
                                        frozen=identity, cleared_findings=identity.selection_findings) as recheck:
                answer = await backend.generate_vision_checked(
                    config.model,
                    image_prompt if image_prompt is not None else body.prompt,
                    images=[base64.b64decode(image.partition(",")[2]) for image in body.images],
                )
        finally:
            if backend is not None:
                await backend.aclose()
        recheck()
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty vision answer")
        return nocache_json(
            dict(ok=True, response=answer, **{k: v for k, v in public.items() if k != "binding"})
        )
    except VisionDestinationChanged:
        return nocache_json({"error": "Vision destination changed; review it again",
                             "reason": "vlm_destination_changed"}, status_code=409)
    except sg.SelectionRefused as exc:
        return nocache_json(exc.payload(), status_code=409)
    except sg.ConsentNotRecorded:
        return nocache_json({"error": "Vision selection acknowledgement could not be recorded",
                             "reason": "vlm_selection_audit_failed"}, status_code=503)
    except Exception:
        return nocache_json(
            {"error": "Vision analysis failed", "reason": "vlm_generation_failed"}, status_code=502
        )
