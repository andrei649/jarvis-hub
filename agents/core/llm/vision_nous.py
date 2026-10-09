"""Explicit Nous vision role with account-bound, encrypted model selection.

Normal resolution is a local read. Only ``prepare_config`` may refresh the
account or ask the Portal for a recommendation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..env_config import env_str
from .nous_auth import NousAuthError, NousAuthService, NousCredentials
from .nous_models import recommend_vision, wire_mode

_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z", re.ASCII)
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,255}\Z", re.ASCII)
_SOURCES = frozenset({"nous_recommended_paid", "nous_recommended_free", "nous_fallback"})
_WELCOME_HOST = "welcome-api.nousresearch.com"


@dataclass(frozen=True)
class _Settings:
    profile: str
    model: str
    role_base: str
    wire: str
    portal_setting: str
    inference_setting: str
    client_id: str


def _read(env: Mapping[str, str] | None, name: str) -> str:
    return str(env.get(name, "") or "") if env is not None else env_str(name, "")


def _auth_service_factory(env: Mapping[str, str] | None) -> NousAuthService:
    return NousAuthService(env=env)


def _settings(env: Mapping[str, str] | None) -> _Settings:
    from .vlm import VLMNotConfigured

    if _read(env, "JARVIS_ROLE_VISION_PROVIDER").strip().lower() != "nous":
        raise VLMNotConfigured("vlm_disabled")
    profile = _read(env, "JARVIS_ROLE_VISION_PROFILE").strip() or "default"
    if _PROFILE.fullmatch(profile) is None:
        raise VLMNotConfigured("vlm_profile_invalid")
    if _read(env, "JARVIS_ROLE_VISION_KEY").strip():
        raise VLMNotConfigured("vlm_key_conflict")
    raw_model = _read(env, "JARVIS_ROLE_VISION_MODEL")
    model = raw_model.strip()
    if model and (len(raw_model) > 512 or _MODEL.fullmatch(model) is None):
        raise VLMNotConfigured("vlm_model_invalid")
    base = _read(env, "JARVIS_ROLE_VISION_BASE_URL")
    if len(base) > 2048 or any(ord(char) < 33 or ord(char) == 127 for char in base if char != " "):
        raise VLMNotConfigured("vlm_url_invalid")
    return _Settings(
        profile=profile, model=model, role_base=base.strip().rstrip("/"),
        wire=_read(env, "JARVIS_NOUS_ANTHROPIC_WIRE").strip().lower() or "chat",
        portal_setting=_read(env, "JARVIS_NOUS_PORTAL_URL"),
        inference_setting=_read(env, "JARVIS_NOUS_INFERENCE_BASE_URL"),
        client_id=_read(env, "JARVIS_NOUS_CLIENT_ID"),
    )


def _refusal(exc: NousAuthError):
    from .vlm import VLMNotConfigured

    return VLMNotConfigured(
        "vlm_url_invalid" if exc.reason == "invalid_configuration" else "vlm_key_unset"
    )


def _credentials(service: NousAuthService, profile: str, state: dict) -> NousCredentials:
    try:
        return service._credentials_from_state(profile, state)
    except NousAuthError as exc:
        raise _refusal(exc) from None


def _check_role_base(settings: _Settings, credentials: NousCredentials) -> None:
    from .vlm import VLMNotConfigured

    if settings.role_base and settings.role_base != credentials.base_url.rstrip("/"):
        raise VLMNotConfigured("vlm_url_invalid")


def _identity(settings: _Settings, credentials: NousCredentials, state: dict) -> str:
    # Only a digest goes into the small selection record. No OAuth token or
    # account metadata enters the public recommendation cache.
    fields = (
        settings.profile, settings.model, settings.role_base, settings.wire,
        settings.portal_setting, settings.inference_setting, settings.client_id,
        credentials.api_key, credentials.base_url, credentials.portal_base_url,
        credentials.expires_at, state.get("access_token"), state.get("agent_key"),
        state.get("refresh_token"),
    )
    return hashlib.sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()


def _welcome(credentials: NousCredentials) -> bool:
    return urlsplit(credentials.base_url).hostname == _WELCOME_HOST


def _valid_model(model: object) -> bool:
    return isinstance(model, str) and _MODEL.fullmatch(model) is not None


def _selected(settings: _Settings, credentials: NousCredentials, state: dict) -> tuple[str, str]:
    from .vlm import VLMNotConfigured

    if _welcome(credentials):
        return "nous/welcome", "nous_welcome"
    if settings.model:
        return settings.model, "JARVIS_ROLE_VISION_MODEL"
    selection = state.get("vision_selection")
    if (
        not isinstance(selection, dict)
        or selection.get("identity") != _identity(settings, credentials, state)
        or not _valid_model(selection.get("model"))
        or selection.get("source") not in _SOURCES
    ):
        raise VLMNotConfigured("vlm_model_unset")
    return selection["model"], selection["source"]


def _config(settings: _Settings, credentials: NousCredentials, model: str):
    from .model_roles import _is_loopback_base
    from .vlm import VLMConfig

    return VLMConfig(
        backend="nous", base_url=credentials.base_url, model=model,
        api_key=credentials.api_key, is_local=_is_loopback_base(credentials.base_url),
        wire_mode=wire_mode(model, settings.wire),
    )


def resolve_config(env: Mapping[str, str] | None = None):
    """Read one encrypted account snapshot; never refresh or discover."""
    settings = _settings(env)
    service = _auth_service_factory(env)
    state = service.store.read(settings.profile)
    credentials = _credentials(service, settings.profile, state)
    _check_role_base(settings, credentials)
    model, _source = _selected(settings, credentials, state)
    return _config(settings, credentials, model)


def model_source(env: Mapping[str, str] | None = None) -> str:
    """A fixed public label, with no account or recommendation content."""
    settings = _settings(env)
    try:
        service = _auth_service_factory(env)
        credentials = service.peek_credentials(settings.profile)
        if _welcome(credentials):
            return "nous_welcome"
    except NousAuthError:
        pass
    return "JARVIS_ROLE_VISION_MODEL" if settings.model else "nous_recommendation"


async def prepare_config(env: Mapping[str, str] | None = None, *, force_refresh: bool = False):
    """Refresh off-loop, recommend, then publish only under matching authority."""
    from .vlm import VLMNotConfigured

    settings = _settings(env)
    service = _auth_service_factory(env)
    try:
        # Catalog freshness does not force OAuth rotation. Expired credentials
        # still refresh through the account service's normal usability check.
        credentials = await asyncio.to_thread(
            service.prepare_credentials, settings.profile,
        )
    except NousAuthError as exc:
        raise _refusal(exc) from None
    _check_role_base(settings, credentials)
    initial_state = service.store.read(settings.profile)
    initial_credentials = _credentials(service, settings.profile, initial_state)
    if initial_credentials != credentials:
        raise VLMNotConfigured("vlm_model_unset")
    expected_identity = _identity(settings, credentials, initial_state)

    def validate() -> None:
        if _settings(env) != settings:
            raise VLMNotConfigured("vlm_model_unset")
        snapshot = service.store.read(settings.profile)
        current = _credentials(service, settings.profile, snapshot)
        _check_role_base(settings, current)
        if current != credentials or _identity(settings, current, snapshot) != expected_identity:
            raise VLMNotConfigured("vlm_model_unset")

    validate()
    if _welcome(credentials):
        return _config(settings, credentials, "nous/welcome")
    if settings.model:
        return _config(settings, credentials, settings.model)

    owner = secrets.token_urlsafe(16)

    def reserve() -> None:
        with service.store.transaction(settings.profile) as state:
            if _settings(env) != settings:
                raise VLMNotConfigured("vlm_model_unset")
            current = _credentials(service, settings.profile, state)
            _check_role_base(settings, current)
            if current != credentials or _identity(settings, current, state) != expected_identity:
                raise VLMNotConfigured("vlm_model_unset")
            state["vision_prepare"] = owner

    def release() -> None:
        with service.store.transaction(settings.profile) as state:
            if state.get("vision_prepare") == owner:
                state.pop("vision_prepare", None)

    def publish(model: str, source: str) -> None:
        with service.store.transaction(settings.profile) as state:
            if state.get("vision_prepare") != owner or _settings(env) != settings:
                raise VLMNotConfigured("vlm_model_unset")
            current = _credentials(service, settings.profile, state)
            _check_role_base(settings, current)
            if current != credentials or _identity(settings, current, state) != expected_identity:
                raise VLMNotConfigured("vlm_model_unset")
            state["vision_selection"] = {
                "model": model, "source": source,
                "identity": expected_identity,
            }
            state.pop("vision_prepare", None)

    await asyncio.to_thread(reserve)
    try:
        recommendation = await recommend_vision(
            credentials, force_refresh=force_refresh, validate=validate,
        )
        if not _valid_model(recommendation.model) or recommendation.source not in _SOURCES:
            raise VLMNotConfigured("vlm_model_unset")
        await asyncio.to_thread(publish, recommendation.model, recommendation.source)
    except BaseException as exc:
        await asyncio.to_thread(release)
        if isinstance(exc, (VLMNotConfigured, asyncio.CancelledError)):
            raise
        raise VLMNotConfigured("vlm_model_unset") from None
    validate()
    return _config(settings, credentials, recommendation.model)
