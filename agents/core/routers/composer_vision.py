"""Explicit, transient browser vision turns; legacy VLM inputs stay separate."""

import asyncio
import base64
import binascii
import hashlib
import io
import json
import logging
import secrets
import sqlite3
import time
from contextlib import suppress
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
    active_image_handles: list[Annotated[str, Field(min_length=20, max_length=128)]] = Field(
        default_factory=list, max_length=8)

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
        if self.selected_turn and not (self.image_digests or self.active_image_handles):
            raise ValueError("selected images are required")
        if not self.selected_turn and (self.image_digests is not None or self.active_image_handles):
            raise ValueError("image selection requires a selected turn")
        if self.image_digests and len(self.image_digests) + len(self.active_image_handles) > 8:
            raise ValueError("too many selected images")
        return self


class PreparedComposerVisionBody(ComposerVisionBody):
    images: list[Annotated[str, Field(max_length=MAX_URI)]] = Field(default_factory=list,
                                                                   max_length=8)
    review_token: str = Field(min_length=20, max_length=128)
    agent: str = Field(default="jarvis", min_length=1, max_length=64,
                       pattern=r"^[a-z][a-z0-9_-]*$")
    session_id: str | None = None
    selected_turn: StrictBool = False
    active_image_handles: list[Annotated[str, Field(min_length=20, max_length=128)]] = Field(
        default_factory=list, max_length=8)

    @field_validator("session_id")
    @classmethod
    def valid_session(cls, value):
        from agents.core.validation import is_valid_session_id
        if value is not None and not is_valid_session_id(value):
            raise ValueError("invalid session_id")
        return value

    @model_validator(mode="after")
    def images_or_history(self):
        if not (self.images or self.active_image_handles):
            raise ValueError("selected images are required")
        if self.active_image_handles and not self.selected_turn:
            raise ValueError("active images require a selected turn")
        return self


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
        from agents.core.llm.vision_capability import prepare_local_model_vision

        await prepare_local_model_vision(turn.backend, turn.model)
        main = _main_candidate(turn.backend, turn.model, turn.route)
        if main is None and agent in LOCAL_ONLY_AGENTS:
            raise VLMNotConfigured("vlm_local_only_unavailable")
    config = await _prepare_config(refresh_catalog=refresh_catalog, main_config=main)
    if agent in LOCAL_ONLY_AGENTS and not config.is_local:
        raise VLMNotConfigured("vlm_local_only_unavailable")
    return turn, config


def _main_candidate(backend, model, route):
    from agents.core.llm.vision_capability import main_vision_eligibility, owner_vision_eligibility
    from agents.core.llm.vision_main import selected_main_config
    from agents.core.llm.vlm import VLMNotConfigured

    runtime_verdict = main_vision_eligibility(backend, model)
    try:
        config = selected_main_config(backend, model, route)
    except VLMNotConfigured:
        if runtime_verdict is False:
            return None
        raise
    if config is None:
        return None
    owner_verdict = owner_vision_eligibility(config)
    if owner_verdict is False or (owner_verdict is None and runtime_verdict is False):
        return None
    return config


def _review_route(config, turn=None):
    route = config.route_source or f"explicit:{config.backend}"
    return f"turn:{turn.prompt_digest}:{route}" if turn is not None else route


def _review_binding(identity, *, turn=None, image_digests=None, active_signature=None):
    if turn is None:
        return identity.binding
    if active_signature is not None:
        return identity.binding + ("reviewed-image-history:v1", tuple(image_digests or ()),
                                   active_signature)
    return identity.binding + ("reviewed-image-digests:v1", tuple(image_digests))


def _active_history(orch, session_id, agent_id, handles):
    """Resolve exact active parts and their ordered private review fingerprint."""
    from agents.core.llm.vision_history import ActiveImageUnavailable

    if orch is None:
        raise ActiveImageUnavailable()
    conversation = orch.memory.conversation
    instance = conversation.active_image_instance(session_id)
    if instance is None:
        raise ActiveImageUnavailable()
    turns = conversation.active_images.resolve_turns(session_id, instance, agent_id, handles)
    digests = tuple(tuple(hashlib.sha256(image).hexdigest() for image in turn.images)
                    for turn in turns)
    return turns, (instance, tuple(handles), digests)


def _selected_resolver(turn, *, active_check=None):
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
    if active_check is not None:
        active_check(orch)
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


@router.get("/api/vlm/composer/active-images")
async def composer_active_images(session_id: str | None = None, agent: str = "jarvis"):
    """List private, process-local image handles for the displayed conversation."""
    from agents.core.app_state import get_orch
    from agents.core.validation import is_valid_session_id

    orch = get_orch()
    if orch is None:
        return nocache_json({"error": "Conversation unavailable",
                             "reason": "vlm_orchestrator_unavailable"}, status_code=503)
    sid = session_id or orch.session_id
    if sid != orch.session_id or not is_valid_session_id(sid) or agent not in orch.agents:
        return nocache_json({"error": "Image session changed",
                             "reason": "vlm_session_changed"}, status_code=409)
    conversation = orch.memory.conversation
    instance = conversation.active_image_instance(sid)
    rows = conversation.active_images.list(sid, instance, agent) if instance else []
    return nocache_json({"session_id": sid, "images": rows})


@router.post("/api/vlm/composer/prepare")
async def composer_prepare(body: ComposerPrepareBody, refresh_catalog: bool = False):
    """Review one prompt's configured destination before image bytes are sent."""
    from agents.core.app_state import get_orch
    from agents.core.llm.vision_history import ActiveImageUnavailable
    from agents.core.llm.vision_policy import VisionPolicyUnavailable, describe
    from agents.core.llm.vlm import VLMNotConfigured

    try:
        turn, config = (await _selected_config(
            prompt=body.prompt, agent=body.agent, session_id=body.session_id,
            refresh_catalog=refresh_catalog,
        ) if body.selected_turn else (None, await _prepare_config(refresh_catalog=refresh_catalog)))
        active_signature = None
        active_count = 0
        if body.active_image_handles:
            active_turns, active_signature = _active_history(
                get_orch(), turn.session_id, body.agent, body.active_image_handles)
            active_count = sum(len(row.images) for row in active_turns)
            if active_count + len(body.image_digests or ()) > 8:
                raise VisionReviewRefused("vlm_image_limit")
        identity = describe(config)
        public = public_config(config, identity=identity)
        token = _REVIEWS.issue(
            session_id=turn.session_id if turn is not None else body.session_id or "web",
            agent_id=body.agent,
            prompt=body.prompt, model=config.model,
            route=_review_route(config, turn),
            binding=_review_binding(identity, turn=turn, image_digests=body.image_digests,
                                    active_signature=active_signature),
        )
        return nocache_json(dict(configured=True, reachable=None,
                                 review_token=token,
                                 **({"active_image_count": active_count} if active_signature else {}),
                                 **({"session_id": turn.session_id, "selected_turn": True}
                                    if turn is not None else {}),
                                 **public))
    except VisionReviewRefused as exc:
        return nocache_json({"error": "Vision review unavailable", "reason": exc.reason},
                            status_code=422 if exc.reason == "vlm_image_limit" else 503)
    except ActiveImageUnavailable:
        return nocache_json({"error": "Active image unavailable; select it again",
                             "reason": "vlm_active_image_unavailable"}, status_code=409)
    except (VLMNotConfigured, ValueError, VisionPolicyUnavailable, sqlite3.Error, OSError):
        return nocache_json({"error": "Vision model unavailable",
                             "reason": "vlm_not_configured"}, status_code=503)


@router.post("/api/vlm/composer/describe-prepared")
async def composer_describe_prepared(body: PreparedComposerVisionBody):
    """Consume a reviewed route before invoking the existing physical guard."""
    from agents.core.llm.vision_policy import VisionPolicyUnavailable
    from agents.core.llm.vlm import VLMNotConfigured

    try:
        turn, config, _, _ = await _consume_prepared_review(body)
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


async def _consume_prepared_review(body: PreparedComposerVisionBody, *, require_main: bool = False):
    from agents.core.app_state import get_orch
    from agents.core.llm.vision_policy import describe
    from agents.core.llm.vlm import VLMNotConfigured, resolve_vlm_config
    from agents.core.memory.conversation import validated_media

    orch = get_orch() if body.selected_turn else None
    sid = body.session_id or (orch.session_id if orch is not None else "web")
    try:
        turn, config = (await _selected_config(
            prompt=body.prompt, agent=body.agent, session_id=body.session_id,
        ) if body.selected_turn else (None, resolve_vlm_config()))
        if require_main and (turn is None or config.route_source != "auto:main"):
            raise VLMNotConfigured("vlm_main_image_route_unavailable")
        if body.active_image_handles and not require_main:
            raise VisionReviewRefused("vlm_selected_turn_required")
        active_turns = ()
        active_signature = None
        if body.active_image_handles:
            active_turns, active_signature = _active_history(
                orch, turn.session_id, body.agent, body.active_image_handles)
        image_count = len(body.images) + sum(len(row.images) for row in active_turns)
        if image_count > 8:
            raise VisionReviewRefused("vlm_image_limit")
        if require_main:
            validated_media({"kind": "image", "count": image_count,
                             "model": config.model, "backend": config.backend,
                             "local": config.is_local})
        identity = describe(config)
        _REVIEWS.consume(
            body.review_token,
            session_id=turn.session_id if turn is not None else body.session_id or "web",
            agent_id=body.agent, prompt=body.prompt, model=config.model,
            route=_review_route(config, turn),
            binding=_review_binding(
                identity, turn=turn, active_signature=active_signature,
                image_digests=[hashlib.sha256(image.encode("utf-8")).hexdigest()
                               for image in body.images] if turn is not None else None,
            ),
        )
        def active_check(orch):
            if active_signature is not None:
                _, current = _active_history(
                    orch, turn.session_id, turn.agent_id, tuple(body.active_image_handles))
                if current != active_signature:
                    raise ValueError("active image changed")

        return turn, config, active_turns, active_check if active_signature else None
    except Exception:
        with suppress(VisionReviewRefused):
            _REVIEWS.cancel(body.review_token, session_id=sid)
        raise


@router.post("/api/vlm/composer/chat-prepared")
async def composer_chat_prepared(body: PreparedComposerVisionBody, request: Request):
    """Commit one reviewed selected image reply to the actual conversation."""
    from agents.core.app_state import get_orch
    from agents.core.llm.vision_policy import VisionPolicyUnavailable
    from agents.core.llm.vlm import VLMNotConfigured

    if not body.selected_turn:
        return nocache_json({"error": "A selected image turn is required",
                             "reason": "vlm_selected_turn_required"}, status_code=422)
    orch = get_orch()
    if orch is None:
        return nocache_json({"error": "Conversation unavailable",
                             "reason": "vlm_orchestrator_unavailable"}, status_code=503)
    sid = body.session_id or orch.session_id
    async with orch.turn_lease(sid) as acquired:
        if not acquired:
            return nocache_json({"error": "Conversation is busy",
                                 "reason": "vlm_turn_busy"}, status_code=409)
        try:
            turn, config, active_turns, active_check = await _consume_prepared_review(
                body, require_main=True)
        except VisionReviewRefused as exc:
            return nocache_json({"error": "Vision review changed; review it again",
                                 "reason": exc.reason}, status_code=409)
        except (VLMNotConfigured, ValueError, VisionPolicyUnavailable, sqlite3.Error, OSError):
            return nocache_json({"error": "Vision destination changed; review it again",
                                 "reason": "vlm_destination_changed"}, status_code=409)

        async def commit(answer: str, latency: float):
            if await request.is_disconnected():
                raise VisionReviewRefused("vlm_client_disconnected")
            await orch.complete_selected_image_turn(
                session_id=turn.session_id, agent_id=turn.agent_id,
                question=body.prompt, answer=answer,
                image_count=len(body.images) + sum(len(row.images) for row in active_turns),
                reused_image_count=sum(len(row.images) for row in active_turns),
                model=config.model, backend=config.backend, local=config.is_local,
                route_name=turn.route, latency=latency,
            )
            if body.images:
                try:
                    conversation = orch.memory.conversation
                    instance = conversation.active_image_instance(turn.session_id)
                    if instance:
                        conversation.active_images.remember(
                            turn.session_id, instance, turn.agent_id, body.prompt, answer,
                            [base64.b64decode(image.partition(",")[2]) for image in body.images],
                        )
                except Exception:
                    # This cache is optional and runs after the durable pair was
                    # committed. Never turn a committed success into a 502.
                    logging.getLogger(__name__).warning("active image cache unavailable after commit")

        return await _composer_describe_with_config(
            body, config, resolve_config=lambda: _selected_resolver(
                turn, active_check=active_check),
            image_prompt=turn.prompt, on_success=commit,
            disconnected=request.is_disconnected,
            history_turns=active_turns or None,
        )


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


async def _await_image_or_disconnect(operation_factory, disconnected):
    """Stop the owned image send when its client leaves before inference ends."""
    if await disconnected():
        raise VisionReviewRefused("vlm_client_disconnected")
    task = asyncio.create_task(operation_factory())
    try:
        while not task.done():
            if await disconnected():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise VisionReviewRefused("vlm_client_disconnected")
            await asyncio.wait({task}, timeout=0.05)
        return await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def _composer_describe_with_config(body, config, *, resolve_config, image_prompt=None,
                                         on_success=None, disconnected=None,
                                         history_turns=None):
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
        started = time.perf_counter()
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
                image_bytes = [base64.b64decode(image.partition(",")[2]) for image in body.images]

                def send():
                    return backend.generate_vision_checked(
                        config.model,
                        image_prompt if image_prompt is not None else body.prompt,
                        images=image_bytes,
                        **({"history": history_turns} if history_turns is not None else {}),
                    )

                answer = (await _await_image_or_disconnect(send, disconnected)
                          if disconnected is not None else await send())
        finally:
            if backend is not None:
                await backend.aclose()
        recheck()
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty vision answer")
        if on_success is not None:
            await on_success(answer, time.perf_counter() - started)
        return nocache_json(
            dict(ok=True, response=answer,
                 **({"committed": True} if on_success is not None else {}),
                 **{k: v for k, v in public.items() if k != "binding"})
        )
    except VisionDestinationChanged:
        return nocache_json({"error": "Vision destination changed; review it again",
                             "reason": "vlm_destination_changed"}, status_code=409)
    except VisionReviewRefused as exc:
        return nocache_json({"error": "Vision turn was not committed",
                             "reason": exc.reason}, status_code=409)
    except sg.SelectionRefused as exc:
        return nocache_json(exc.payload(), status_code=409)
    except sg.ConsentNotRecorded:
        return nocache_json({"error": "Vision selection acknowledgement could not be recorded",
                             "reason": "vlm_selection_audit_failed"}, status_code=503)
    except Exception:
        return nocache_json(
            {"error": "Vision analysis failed", "reason": "vlm_generation_failed"}, status_code=502
        )
