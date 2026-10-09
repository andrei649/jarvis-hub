"""Explicit, transient browser vision turns; legacy VLM inputs stay separate."""

import base64
import binascii
import hashlib
import io
import json
import secrets
import sqlite3
import time
from contextlib import suppress
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.core.commands import Principal
from agents.core.routers._deps import owner_web_principal, user_guard
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
from agents.core.llm.vision_review import VisionReviewRefused, VisionReviewStore

_SELECTED_REVIEWS = VisionReviewStore()
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
        **identity.public(),
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
    from agents.core.llm.vision_policy import VisionPolicyUnavailable
    from agents.core.llm.vlm import VLMNotConfigured, resolve_vlm_config

    try:
        return nocache_json(
            dict(configured=True, reachable=None, **public_config(resolve_vlm_config()))
        )
    except (VLMNotConfigured, ValueError, VisionPolicyUnavailable, sqlite3.Error, OSError):
        return nocache_json(
            {"configured": False, "reason": "vlm_not_configured", "reachable": None}
        )


@router.post("/api/vlm/composer/describe")
async def composer_describe(body: ComposerVisionBody):
    from agents.core.commands import Principal
    from agents.core.llm import selection_guards as sg
    from agents.core.llm.vision_policy import (
        VisionDestinationChanged,
        VisionPolicyUnavailable,
        composer_request_scope,
        describe,
    )
    from agents.core.llm.vlm import VLMBackend, VLMNotConfigured, resolve_vlm_config

    try:
        config = resolve_vlm_config()
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
        findings = sg.evaluate([sg.Choice("vision.model", identity.provider, config.model)])
        if findings:
            raise sg.SelectionRefused(findings, sorted({finding.needs for finding in findings}))
        try:
            backend = VLMBackend(base_url=config.base_url, api_key=config.api_key, composer_auth=True)
            with composer_request_scope(config, backend, resolve_config=resolve_vlm_config,
                                        remote_ack=body.remote_ack, principal=Principal(channel="web", admin=False),
                                        frozen=identity) as recheck:
                answer = await backend.generate_vision_checked(
                    config.model,
                    body.prompt,
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
    except Exception:
        return nocache_json(
            {"error": "Vision analysis failed", "reason": "vlm_generation_failed"}, status_code=502
        )


class SelectedImagePrepare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=4000)
    agent: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    session_id: str
    image_digests: list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]] = Field(
        default_factory=list, max_length=8)
    active_image_handles: list[Annotated[str, Field(min_length=20, max_length=128)]] = Field(
        default_factory=list, max_length=8)

    @field_validator("prompt")
    @classmethod
    def question(cls, value):
        if not value.strip():
            raise ValueError("image question is empty")
        return value

    @field_validator("session_id")
    @classmethod
    def session(cls, value):
        from agents.core.validation import is_valid_session_id
        if not is_valid_session_id(value):
            raise ValueError("invalid image session")
        return value

    @model_validator(mode="after")
    def images_selected(self):
        if not self.image_digests and not self.active_image_handles:
            raise ValueError("selected images are required")
        if len(set(self.active_image_handles)) != len(self.active_image_handles):
            raise ValueError("duplicate active image")
        return self


class SelectedImageSend(ComposerVisionBody):
    images: list[Annotated[str, Field(max_length=MAX_URI)]] = Field(default_factory=list, max_length=8)
    expected_binding: str = Field(min_length=20, max_length=128, pattern=r"^[-_A-Za-z0-9]+$")
    agent: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    session_id: str
    review_token: str = Field(min_length=20, max_length=128)
    active_image_handles: list[Annotated[str, Field(min_length=20, max_length=128)]] = Field(
        default_factory=list, max_length=8)

    @field_validator("session_id")
    @classmethod
    def session(cls, value):
        from agents.core.validation import is_valid_session_id
        if not is_valid_session_id(value):
            raise ValueError("invalid image session")
        return value

    @model_validator(mode="after")
    def images_selected(self):
        if not self.images and not self.active_image_handles:
            raise ValueError("selected images are required")
        if len(set(self.active_image_handles)) != len(self.active_image_handles):
            raise ValueError("duplicate active image")
        return self


def _selected_destination(turn):
    from agents.core.llm import selection_guards as sg
    from agents.core.llm.base import OllamaBackend
    from agents.core.llm.direct_transport import require_direct_async_transport
    from agents.core.llm.model_roles import public_local_origin, same_origin

    backend = turn.backend
    if type(backend) is not OllamaBackend or not turn.route.startswith("local"):
        raise ValueError("selected route is not Ollama")
    if not isinstance(turn.model, str) or not 0 < len(turn.model) <= 512 or any(
            ord(char) < 33 or ord(char) == 127 for char in turn.model):
        raise ValueError("invalid selected model")
    findings = sg.evaluate([sg.Choice("vision.model", "ollama", turn.model)])
    if findings:
        raise VisionReviewRefused("vlm_selection_changed")
    origin = public_local_origin(backend.base_url)
    parts = urlsplit(backend.base_url)
    client_parts = urlsplit(str(backend.client.base_url))
    if (not origin or not same_origin(origin, str(backend.client.base_url))
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path not in ("", "/") or client_parts.username or client_parts.password
            or client_parts.query or client_parts.fragment or client_parts.path not in ("", "/")):
        raise ValueError("selected Ollama destination is not local")
    expected = backend.client.build_request("POST", "/api/chat", json={"model": turn.model})
    if (not same_origin(origin, str(expected.url)) or backend.client.cookies
            or backend.client.headers.get("Authorization") or backend.client.headers.get("Cookie")
            or getattr(backend.client, "_auth", None) is not None):
        raise ValueError("selected Ollama client changed")
    require_direct_async_transport(backend.client, expected.url)
    return origin


def _active_selection(orch, session_id, agent_id, handles):
    if not handles:
        return (), ()
    conversation = orch.memory.conversation
    instance = conversation.active_image_instance(session_id)
    if instance is None:
        raise ValueError("active image unavailable")
    turns = conversation.active_images.resolve_turns(session_id, instance, agent_id, handles)
    signature = (instance, tuple(handles), tuple(
        (row.question, row.answer, tuple(hashlib.sha256(image).hexdigest() for image in row.images))
        for row in turns))
    return turns, signature


async def _selected_turn(orch, body):
    from agents.core.llm.vision_turn import prepare_selected_image_turn

    try:
        turn = await prepare_selected_image_turn(
            orch, question=body.prompt, agent_id=body.agent, session_id=body.session_id)
        return turn, _selected_destination(turn)
    except ValueError:
        raise VisionReviewRefused("vlm_destination_changed") from None


def _selected_binding(turn, origin, image_digests, active_signature):
    return ("ollama-selected-v1", turn.history_digest, turn.prompt_digest, origin,
            tuple(image_digests), active_signature)


def _owner_profile(principal):
    """The web owner's resolved role, without copying a credential into review state."""
    if principal.channel != "web" or not principal.admin:
        raise VisionReviewRefused("vlm_owner_required")
    return (principal.channel, principal.sender, principal.admin, principal.chat)


@router.get("/api/vlm/composer/active-images")
async def composer_active_images(session_id: str,
                                 principal: Annotated[Principal, Depends(owner_web_principal)],
                                 agent: str = "jarvis"):
    from agents.core.app_state import get_orch
    from agents.core.validation import is_valid_session_id

    _owner_profile(principal)
    orch = get_orch()
    if orch is None or not is_valid_session_id(session_id) or agent not in orch.agents:
        return nocache_json({"error": "Image session unavailable", "reason": "vlm_session_changed"}, status_code=409)
    conversation = orch.memory.conversation
    instance = conversation.active_image_instance(session_id)
    rows = conversation.active_images.list(session_id, instance, agent) if instance else []
    return nocache_json({"session_id": session_id, "images": rows})


@router.post("/api/vlm/composer/selected-prepare")
async def composer_selected_prepare(body: SelectedImagePrepare,
                                    principal: Annotated[Principal, Depends(owner_web_principal)]):
    from agents.core.app_state import get_orch
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal

    profile = _owner_profile(principal)
    orch = get_orch()
    if orch is None:
        return nocache_json({"error": "Conversation unavailable", "reason": "vlm_orchestrator_unavailable"}, status_code=503)
    principal_token = bind_turn_principal(principal)
    try:
        turn, destination = await _selected_turn(orch, body)
        active_turns, signature = _active_selection(
            orch, body.session_id, body.agent, body.active_image_handles)
        count = len(body.image_digests) + sum(len(row.images) for row in active_turns)
        if count > 8:
            raise ValueError("too many images")
        token = _SELECTED_REVIEWS.issue(
            session_id=body.session_id, agent_id=body.agent, prompt=body.prompt,
            model=turn.model, route=turn.route,
            binding=_selected_binding(turn, destination, body.image_digests, signature),
            principal=profile)
        return nocache_json({"configured": True, "reachable": None, "review_token": token,
                             "session_id": body.session_id, "destination": destination,
                             "model": turn.model, "backend": "ollama", "local": True,
                             "active_image_count": count - len(body.image_digests)})
    except (ValueError, VisionReviewRefused):
        return nocache_json({"error": "Selected Ollama vision unavailable",
                             "reason": "vlm_selected_unavailable"}, status_code=409)
    finally:
        reset_turn_principal(principal_token)


async def _composer_selected_chat(body: SelectedImageSend, request: Request, profile):
    from agents.core.app_state import get_orch
    from agents.core.llm.data_handling import physical_request_scope
    from agents.core.llm.direct_transport import require_direct_async_transport
    from agents.core.llm.vision_ollama_wire import chat_answer, chat_payload
    from agents.core.llm.vision_turn import history_fingerprint
    from agents.core.llm.vlm import encode_image_block

    orch = get_orch()
    if orch is None:
        return nocache_json({"error": "Conversation unavailable", "reason": "vlm_orchestrator_unavailable"}, status_code=503)
    async with orch.turn_lease(body.session_id) as acquired:
        if not acquired:
            return nocache_json({"error": "Conversation is busy", "reason": "vlm_turn_busy"}, status_code=409)
        try:
            turn, destination = await _selected_turn(orch, body)
            if (body.expected_destination != destination or body.expected_binding != body.review_token
                    or body.remote_ack):
                raise VisionReviewRefused("vlm_destination_changed")
            try:
                active_turns, signature = _active_selection(
                    orch, body.session_id, body.agent, body.active_image_handles)
            except ValueError:
                raise VisionReviewRefused("vlm_active_image_unavailable") from None
            images = [base64.b64decode(image.partition(",")[2]) for image in body.images]
            count = len(images) + sum(len(row.images) for row in active_turns)
            if count > 8:
                raise VisionReviewRefused("vlm_image_limit")
            digests = [hashlib.sha256(image.encode("utf-8")).hexdigest() for image in body.images]
            _SELECTED_REVIEWS.consume(
                body.review_token, session_id=body.session_id, agent_id=body.agent,
                prompt=body.prompt, model=turn.model, route=turn.route,
                binding=_selected_binding(turn, destination, digests, signature),
                principal=profile)
            messages = []
            for prior in active_turns:
                messages.append({"role": "user", "content": [
                    {"type": "text", "text": prior.question},
                    *(encode_image_block(image) for image in prior.images)]})
                messages.append({"role": "assistant", "content": prior.answer})
            messages.append({"role": "user", "content": [
                {"type": "text", "text": turn.prompt},
                *(encode_image_block(image) for image in images)]})
            payload = chat_payload({"model": turn.model, "messages": messages,
                                    "max_tokens": 1024, "temperature": 0.2})
            if len(json.dumps(payload, separators=(",", ":")).encode()) > 20_000_000:
                raise VisionReviewRefused("vlm_image_limit")
            client = turn.backend.client
            expected = client.build_request("POST", "/api/chat", json=payload)

            def check():
                if history_fingerprint(orch, body.session_id) != turn.history_digest:
                    raise VisionReviewRefused("vlm_destination_changed")
                current, model, route = orch.llm_router.select_backend(body.agent, turn.prompt)
                if current is not turn.backend or model != turn.model or route != turn.route:
                    raise VisionReviewRefused("vlm_destination_changed")
                try:
                    if _selected_destination(turn) != destination or turn.backend.client is not client:
                        raise VisionReviewRefused("vlm_destination_changed")
                except ValueError:
                    raise VisionReviewRefused("vlm_destination_changed") from None
                if signature:
                    try:
                        current_signature = _active_selection(
                            orch, body.session_id, body.agent, body.active_image_handles)[1]
                    except ValueError:
                        raise VisionReviewRefused("vlm_active_image_unavailable") from None
                    if current_signature != signature:
                        raise VisionReviewRefused("vlm_active_image_unavailable")
                require_direct_async_transport(client, expected.url)

            def request_check(wire):
                if (wire.method != "POST" or wire.url != expected.url or
                        wire.content != expected.content or wire.headers.get("Authorization") or
                        wire.headers.get("Cookie")):
                    raise VisionReviewRefused("vlm_destination_changed")

            check()
            if await request.is_disconnected():
                raise VisionReviewRefused("vlm_client_disconnected")
            started = time.perf_counter()
            with physical_request_scope(check, request_check=request_check):
                async with client.stream("POST", "/api/chat", json=payload, follow_redirects=False) as response:
                    response.raise_for_status()
                    result = bytearray()
                    async for chunk in response.aiter_bytes():
                        result.extend(chunk)
                        if len(result) > 128 * 1024:
                            raise ValueError("vision response too large")
            check()
            if await request.is_disconnected():
                raise VisionReviewRefused("vlm_client_disconnected")
            answer = chat_answer(json.loads(result))
            if not answer:
                raise ValueError("empty vision answer")
            check()
            await orch.complete_selected_image_turn(
                session_id=body.session_id, agent_id=body.agent, question=body.prompt,
                answer=answer, image_count=count, model=turn.model,
                route_name=turn.route, latency=time.perf_counter() - started)
            instance = orch.memory.conversation.active_image_instance(body.session_id)
            try:
                handle = orch.memory.conversation.active_images.remember(
                    body.session_id, instance, body.agent, body.prompt, answer,
                    [image for prior in active_turns for image in prior.images] + images)
            except ValueError:
                handle = None
            return nocache_json({"ok": True, "committed": True, "response": answer,
                                 "model": turn.model, "backend": "ollama",
                                 "destination": destination, "local": True,
                                 "active_image_handle": handle})
        except VisionReviewRefused as exc:
            with suppress(VisionReviewRefused):
                _SELECTED_REVIEWS.cancel(body.review_token, session_id=body.session_id)
            return nocache_json({"error": "Vision review changed; review it again",
                                 "reason": exc.reason}, status_code=409)
        except Exception:
            with suppress(VisionReviewRefused):
                _SELECTED_REVIEWS.cancel(body.review_token, session_id=body.session_id)
            return nocache_json({"error": "Vision analysis failed",
                                 "reason": "vlm_generation_failed"}, status_code=502)


@router.post("/api/vlm/composer/selected-chat")
async def composer_selected_chat(body: SelectedImageSend, request: Request,
                                 principal: Annotated[Principal, Depends(owner_web_principal)]):
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal

    profile = _owner_profile(principal)
    principal_token = bind_turn_principal(principal)
    try:
        return await _composer_selected_chat(body, request, profile)
    finally:
        reset_turn_principal(principal_token)
