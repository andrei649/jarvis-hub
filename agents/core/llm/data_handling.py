"""H513: data policy at routed dispatch, with configuration-bound owner consent.

Selection metadata is pure; ``authorize`` is the actual-use boundary. Independent
direct backend clients are outside this boundary. Routed tool runtime rounds recheck
through its optional pre-request hook. Consent does not suppress a warning.
"""
from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import logging
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from agents.core import settings_db

from .providers import DATA_POLICIES, get_profile, list_profiles

logger = logging.getLogger("jarvis.llm.data_handling")
SETTING = ("security", "data_training_ack")
ROLE_SETTING = ("security", "data_training_role_ack")
JUDGE_TARGET = "role:approval_judge"
MEDIA_TARGET = "role:telegram_media_reader"
CAMERA_TARGET = "role:camera_descriptions"
VIDEO_TARGET = "role:video_analysis"
VIDEO_FALLBACK_TARGETS = tuple(f"role:video_fallback_{slot}" for slot in range(1, 5))
ROLE_TARGETS = {
    JUDGE_TARGET: "Approval judge",
    MEDIA_TARGET: "Telegram image descriptions",
    CAMERA_TARGET: "Camera descriptions",
    VIDEO_TARGET: "Video analysis",
    **{target: f"Video fallback {slot}" for slot, target in enumerate(VIDEO_FALLBACK_TARGETS, 1)},
}
COVERAGE = (
    "routed agent dispatch, synthesis, tool-loop requests, Gemini cache writes, "
    "session titles, recall query rewriting, background/on-demand review, context compression, "
    "acquisition drafting/generation, the optional presence explanation seam, the approval judge, "
    "interactive composer vision, strict-local describe/screen-reflex, unattended Telegram image descriptions, strict-local camera descriptions, approved video analysis, and local-only embeddings; "
    "unscoped multimodal library clients excluded"
)
_HEX = re.compile(r"[0-9a-f]{64}\Z")


@dataclass
class _RequestGuard:
    check: object
    request_check: object = None
    active: bool = True
    error: Exception | None = None


_physical_guard: ContextVar[_RequestGuard | None] = ContextVar("h513_physical_request_guard", default=None)


@contextmanager
def physical_request_scope(check, *, request_check=None):
    """Bind a routed call's guard, never mutate the shared backend/client.

    Child tasks inherit the same lifetime; retries after scope close cannot send.
    Re-raise a remembered denial even when an adapter returns a degraded reply.
    Optional request_check validates the final Request too, including DELETE; old
    scopes retain their cleanup exemption when no request validator is installed.
    """
    if check is None and request_check is None:
        yield
        return
    state = _RequestGuard(check, request_check)
    token = _physical_guard.set(state)
    try:
        yield
    finally:
        state.active = False
        _physical_guard.reset(token)
        if state.error is not None:
            raise state.error


@contextmanager
def auxiliary_request_scope(router, backend, model, *, role):
    """Guard a selected auxiliary generation as internal, including physical retries.

    Capture the actual adapter/model, but resolve configuration and consent again
    at every request. An inherited interactive principal cannot authorize this
    unattended work; no optional router hook is needed by the base LLMRouter.
    """
    from agents.core.action_origin import DEFAULT_ACTION_ORIGIN
    from agents.core.commands import Principal

    principal = Principal(channel="internal", admin=False)

    def check():
        return authorize(router, backend, model, route=role,
                         principal=principal, origin=DEFAULT_ACTION_ORIGIN)

    check()
    with physical_request_scope(check):
        yield


async def check_physical_request(request):
    state = _physical_guard.get()
    if state is None or (request.method == "DELETE" and state.request_check is None):
        return
    if state.error is not None:
        raise state.error
    try:
        if not state.active:
            raise DataHandlingRefused("routed request scope is closed")
        if state.check is not None:
            checked = state.check()
            if inspect.isawaitable(checked):
                await checked
        if state.request_check is not None:
            checked = state.request_check(request)
            if inspect.isawaitable(checked):
                await checked
        if not state.active:
            raise DataHandlingRefused("routed request scope is closed")
    except Exception as exc:
        state.error = exc
        raise


def check_physical_request_sync(request):
    """Synchronous counterpart for owned embedding clients; never run an event loop."""
    state = _physical_guard.get()
    if state is None or (request.method == "DELETE" and state.request_check is None):
        return
    if state.error is not None:
        raise state.error
    try:
        if not state.active:
            raise DataHandlingRefused("routed request scope is closed")
        for callback, args in ((state.check, ()), (state.request_check, (request,))):
            if callback is None:
                continue
            result = callback(*args)
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise DataHandlingRefused("asynchronous policy check cannot authorize a synchronous request")
        if not state.active:
            raise DataHandlingRefused("routed request scope is closed")
    except Exception as exc:
        state.error = exc
        raise


class DataHandlingRefused(RuntimeError):
    """An unattended route has no current durable consent."""

    def reply(self):
        return f"[data handling error: {self}]"


class StaleAcknowledgment(ValueError):
    """The configuration shown to the owner no longer matches."""


class ConsentUnavailable(RuntimeError):
    """Required consent audit or persistence failed."""


def _scope_key() -> bytes:
    # Domain-separated HMAC with the protected, persistent local secret-store key.
    # Public scopes cannot be used to check guesses of an API credential offline.
    from agents.core.secrets import SecretStore
    return hmac.digest(SecretStore()._key_b64, b"nerva:H513:scope:v1", "sha256")


def _unwrap(backend):
    for _ in range(8):
        child = getattr(backend, "_backend", None)
        if child is None or child is backend:
            break
        backend = child
    return backend


def _provider(router, backend):
    backend = _unwrap(backend)
    profile = getattr(backend, "profile", None)
    if profile is not None:
        return backend, profile
    known = (("_gemini_backend", "gemini"), ("_claude_backend", "anthropic"),
             ("_ollama_backend", "ollama"), ("_backend", getattr(router, "_backend_name", "")))
    for attr, provider in known:
        if backend is getattr(router, attr, None) and provider:
            try:
                return backend, get_profile(provider)
            except KeyError:
                break
    raise ValueError("routed backend provider is unknown")


def _ack_map(raw):
    providers = {p.id for p in list_profiles()}
    if not isinstance(raw, dict) or len(raw) > len(providers):
        raise ValueError("invalid data-handling consent store")
    if any(p not in providers or not isinstance(scope, str) or not _HEX.fullmatch(scope)
           for p, scope in raw.items()):
        raise ValueError("invalid data-handling consent store")
    return raw


def _read_ack():
    try:
        found, raw = settings_db.read_setting(*SETTING)
        return _ack_map(raw if found else {}), True
    except (settings_db.SettingsUnreadable, ValueError):
        return {}, False


def _role_ack_map(raw):
    if (not isinstance(raw, dict) or len(raw) > len(ROLE_TARGETS)
            or any(f"role:{key}" not in ROLE_TARGETS or not isinstance(scope, str) or not _HEX.fullmatch(scope)
                   for key, scope in raw.items())):
        raise ValueError("invalid role consent store")
    return raw


def _read_role_ack():
    try:
        found, raw = settings_db.read_setting(*ROLE_SETTING)
        return (_role_ack_map(raw), True) if found else ({}, False)
    except (settings_db.SettingsUnreadable, ValueError):
        return {}, False


def _judge_target(router):
    from agents.core.autonomy.approval_judge import describe_data_target
    return describe_data_target(router)


def _role_target(router, target, *, role_context=None):
    if target == JUDGE_TARGET:
        return _judge_target(router)
    if target == MEDIA_TARGET:
        from .vision_policy import describe_media_data_target
        return describe_media_data_target()
    if target == CAMERA_TARGET:
        from .vision_policy import describe_camera_data_target
        return describe_camera_data_target(role_context)
    if target == VIDEO_TARGET or target in VIDEO_FALLBACK_TARGETS:
        from .video_policy import describe_video_data_target
        return describe_video_data_target(target)
    raise ValueError("invalid role target")


def role_target_scope(descriptor):
    if (descriptor.target_id not in ROLE_TARGETS or descriptor.provider not in {p.id for p in list_profiles()}
            or descriptor.mode not in {"active", "dedicated"} or descriptor.policy not in DATA_POLICIES
            or not isinstance(descriptor.model, str) or not 0 < len(descriptor.model) <= 256):
        raise ValueError("invalid role data target")
    material = [descriptor.target_id, descriptor.provider, descriptor.model, descriptor.mode,
                descriptor.policy, descriptor.binding]
    try:
        wire = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(_scope_key(), b"H513:role-target:v1\0" + wire, hashlib.sha256).hexdigest()
    except Exception:
        return ""


def _role_public(descriptor, acks, readable, router):
    scope = role_target_scope(descriptor)
    warning = Resolved(descriptor.provider, descriptor.policy, descriptor.note, scope).warning
    used = getattr(router, "_data_handling_role_used", {}).get(descriptor.target_id, {})
    return {"target_id": descriptor.target_id, "label": ROLE_TARGETS[descriptor.target_id], "provider": descriptor.provider,
            "model": descriptor.model, "mode": descriptor.mode, "policy": descriptor.policy,
            "note": descriptor.note, "scope": scope, "warning": warning,
            "acknowledged": bool(scope) and readable and acks.get(descriptor.target_id.removeprefix("role:")) == scope,
            "last_used": used.get("at") if used.get("scope") == scope else None,
            "can_acknowledge": bool(scope) and readable,
            "acknowledgment_unavailable": "" if scope and readable else "role consent settings or configuration scope unavailable"}


def authorize_role_target(router, descriptor, *, actual_use=True):
    from agents.core.turn_notices import record_turn_notice

    acks, readable = _read_role_ack()
    row = _role_public(descriptor, acks, readable, router)
    if row["warning"] and not row["acknowledged"]:
        raise DataHandlingRefused(f"{row['warning']} {row['label']} use requires the owner's audited role acknowledgment.")
    if actual_use:
        if row["warning"]:
            logger.warning("%s (target=%s, acknowledged=%s)", row["warning"], descriptor.target_id, row["acknowledged"])
            record_turn_notice(f"data_handling:{descriptor.target_id}", row["warning"])
        if router is not None and row["scope"]:
            used = {key: value for key, value in getattr(router, "_data_handling_role_used", {}).items() if key in ROLE_TARGETS}
            used[descriptor.target_id] = {"scope": row["scope"], "at": time.time()}
            router._data_handling_role_used = used
    return row


@dataclass(frozen=True)
class Resolved:
    provider: str
    policy: str
    note: str
    scope: str

    @property
    def warning(self):
        if self.policy == "unknown":
            return f"{self.provider}: data handling is unknown; prompts may be retained or used for training."
        if self.policy == "trains-on-inputs":
            return f"{self.provider}: this route may use prompts for training."
        return ""

    def public(self, acknowledged=False, last_used=None):
        return {"provider": self.provider, "policy": self.policy, "note": self.note,
                "scope": self.scope, "warning": self.warning,
                "acknowledged": acknowledged, "last_used": last_used}


def resolve(router, backend, model, route="") -> Resolved:
    """Resolve actual profile/account/endpoint without a request or usage side effects."""
    backend, profile = _provider(router, backend)
    policy, note = profile.data_policy_for(model)
    endpoint = getattr(backend, "endpoint", None) or getattr(backend, "base_url", None) or profile.default_base_url
    if policy == "local":
        from .model_roles import _is_loopback_base
        if not _is_loopback_base(str(endpoint)):
            policy, note = "unknown", "The local adapter points outside loopback; data handling is unknown."
    routing = None
    if profile.id == "openrouter":
        # This reader is the exact H583 wire policy, including live owner changes.
        probe = getattr(backend, "_current_block", None)
        routing = probe() if callable(probe) else None
        if routing and routing.get("data_collection") == "allow":
            policy, note = "trains-on-inputs", "OpenRouter data collection is allowed on this route."
        elif routing and routing.get("data_collection") == "deny":
            note = f"{note} Outgoing OpenRouter requests restrict data collection to deny.".strip()
    if policy not in DATA_POLICIES:
        policy, note = "unknown", "The configured provider declaration is invalid."
    pool = getattr(backend, "auth_pool", None)
    profiles = getattr(pool, "_profiles", ()) if pool is not None else ()
    keys = sorted({str(p.api_key) for p in profiles}) if profiles else [str(getattr(backend, "api_key", ""))]
    material = [profile.id, str(endpoint), keys, policy, profile.data_policy, profile.data_policy_models, routing]
    try:
        scope = hmac.new(_scope_key(), json.dumps(material, sort_keys=True).encode(), hashlib.sha256).hexdigest()
    except Exception:
        # No public unkeyed fallback and no grant on missing scope. Safe local work
        # does not require consent and must not depend on the secret store.
        scope = ""
    return Resolved(profile.id, policy, note, scope)


def _configured(router):
    seen = set()
    for attr, model_attr in (("_backend", "_local_model"), ("_ollama_backend", "_howard_model"),
                             ("_gemini_backend", "_gemini_model"), ("_claude_backend", "_claude_model"),
                             ("_compatible_backend", "_compatible_model")):
        backend = getattr(router, attr, None)
        if backend is None or id(backend) in seen:
            continue
        seen.add(id(backend))
        yield resolve(router, backend, getattr(router, model_attr, "") or "")


def posture(router, *, role_context=None):
    acks, readable = _read_ack()
    used = getattr(router, "_data_handling_used", {})
    configured = list(_configured(router))
    registered = {p.id for p in list_profiles()}
    rows = []
    for resolved in configured:
        unique = sum(r.provider == resolved.provider for r in configured) == 1
        row = resolved.public(bool(resolved.scope) and acks.get(resolved.provider) == resolved.scope, used.get(resolved.scope))
        row["can_acknowledge"] = unique and resolved.provider in registered and bool(resolved.scope) and readable
        row["acknowledgment_unavailable"] = ("" if row["can_acknowledge"] else
                                             "provider has multiple configured accounts" if not unique else
                                             "provider is not registered" if resolved.provider not in registered else
                                             "consent settings or configuration scope unavailable")
        rows.append(row)
    role_acks, role_readable = _read_role_ack()
    targets = []
    for target in ROLE_TARGETS:
        try:
            descriptor = _role_target(router, target, role_context=role_context)
            if descriptor is not None:
                targets.append(_role_public(descriptor, role_acks, role_readable, router))
        except Exception:
            logger.warning("role data target unavailable (target=%s)", target)
    return {"providers": rows, "settings_readable": readable, "targets": targets,
            "role_settings_readable": role_readable, "coverage": COVERAGE}


def authorize(router, backend, model, route="", *, principal=None, origin=None, actual_use=True):
    from agents.core.action_origin import current_action_origin
    from agents.core.tool_profiles import SURFACE_INTERNAL, classify_turn
    from agents.core.turn_notices import record_turn_notice
    if principal is None:
        from agents.core.orchestrator import current_principal
        principal = current_principal()
    resolved = resolve(router, backend, model, route)
    acks, readable = _read_ack()
    acknowledged = readable and acks.get(resolved.provider) == resolved.scope
    surface = classify_turn(principal, current_action_origin() if origin is None else origin).surface
    channel = str(getattr(principal, "channel", "") or "").strip().lower()
    unattended = surface == SURFACE_INTERNAL or channel in {"", "unknown"}
    if resolved.warning and unattended and not acknowledged:
        raise DataHandlingRefused(f"{resolved.warning} Unattended use requires the owner's audited acknowledgment.")
    if not actual_use:
        return resolved.public(acknowledged)
    if resolved.warning:
        logger.warning("%s (surface=%s, acknowledged=%s)", resolved.warning, surface, acknowledged)
        record_turn_notice(f"data_handling:{resolved.provider}", resolved.warning)
    if not resolved.scope:
        # Without a scope, do not conflate different unavailable configurations
        # under the same empty-key last-used entry.
        return resolved.public(acknowledged)
    # Bounded by live configured provider scopes; historical revisions are not retained.
    used = getattr(router, "_data_handling_used", {})
    if len(used) >= 32 and resolved.scope not in used:
        used.clear()
    used[resolved.scope] = time.time()
    router._data_handling_used = used
    return resolved.public(acknowledged, used[resolved.scope])


def acknowledge(router, provider, acknowledged, scope, audit, *, target=None, role_context=None):
    if target is not None:
        return _acknowledge_role(router, provider, acknowledged, scope, audit, target, role_context=role_context)
    if not isinstance(provider, str) or type(acknowledged) is not bool or not isinstance(scope, str) or not _HEX.fullmatch(scope):
        raise ValueError("expected provider, strict acknowledged boolean and current scope")
    if provider not in {p.id for p in list_profiles()}:
        raise ValueError("provider must be registered")
    matches = [r for r in _configured(router) if r.provider == provider]
    if len(matches) != 1:
        raise ValueError("provider must identify one configured route")
    resolved = matches[0]
    if not hmac.compare_digest(scope, resolved.scope):
        raise StaleAcknowledgment("provider configuration changed; reload security posture")
    from agents.core.security.types import SecurityEvent, SecurityEventType
    try:
        conn = settings_db.get_conn()
    except Exception as exc:
        raise ConsentUnavailable("consent settings unavailable") from exc
    try:
        # Serializes concurrent grant/revoke across processes; audit has its own store.
        # A successful audit with a failed settings commit grants nothing; retry is safe.
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM settings WHERE category=? AND key=?", SETTING).fetchone()
        values = _ack_map(json.loads(row["value"]) if row else {})
        if audit is None:
            raise ConsentUnavailable("required consent audit unavailable")
        audit.log(SecurityEvent(event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
                               action_taken="model_training_consent" if acknowledged else "model_training_consent_revoked",
                               content_preview=f"H513 unattended {'acknowledged' if acknowledged else 'revoked'}: {provider}; policy={resolved.policy}; scope={scope}"))
        # A blocking audit may race with a configuration reload in another thread.
        current = [r for r in _configured(router) if r.provider == provider]
        if len(current) != 1 or current[0].scope != scope:
            raise ConsentUnavailable("configuration changed while recording consent")
        if acknowledged:
            values[provider] = scope
        else:
            values.pop(provider, None)
        _ack_map(values)
        conn.execute("UPDATE settings SET value=? WHERE category=? AND key=?", (json.dumps(values), *SETTING))
        if row is None:
            raise ConsentUnavailable("consent setting missing")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise ConsentUnavailable("consent audit or settings write failed; no permission was granted") from exc
    finally:
        conn.close()
    settings_db._changed(SETTING[0], {SETTING[1]: values})
    return {"ok": True, "provider": provider, "acknowledged": acknowledged, "scope": scope, "warning": resolved.warning}


def _acknowledge_role(router, provider, acknowledged, scope, audit, target, *, role_context=None):
    if (target not in ROLE_TARGETS or not isinstance(provider, str) or type(acknowledged) is not bool
            or not isinstance(scope, str) or not _HEX.fullmatch(scope)):
        raise ValueError("expected finite role target, provider, strict boolean and current scope")
    descriptor = _role_target(router, target, role_context=role_context)
    if descriptor is None or provider != descriptor.provider:
        raise ValueError("provider must match the configured role target")
    if not hmac.compare_digest(scope, role_target_scope(descriptor)):
        raise StaleAcknowledgment("role configuration changed; reload security posture")
    from agents.core.security.types import SecurityEvent, SecurityEventType
    try:
        conn = settings_db.get_conn()
    except Exception as exc:
        raise ConsentUnavailable("role consent settings unavailable") from exc
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM settings WHERE category=? AND key=?", ROLE_SETTING).fetchone()
        values = _role_ack_map(json.loads(row["value"]) if row else {})
        if audit is None:
            raise ConsentUnavailable("required consent audit unavailable")
        audit.log(SecurityEvent(event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
                               action_taken="model_training_consent" if acknowledged else "model_training_consent_revoked",
                               content_preview=f"H513 role {'acknowledged' if acknowledged else 'revoked'}: {target}; provider={provider}; policy={descriptor.policy}; scope={scope}"))
        current = _role_target(router, target, role_context=role_context)
        if current is None or current.provider != provider or role_target_scope(current) != scope:
            raise ConsentUnavailable("role configuration changed while recording consent")
        if acknowledged:
            values[target.removeprefix("role:")] = scope
        else:
            values.pop(target.removeprefix("role:"), None)
        _role_ack_map(values)
        if row is None:
            raise ConsentUnavailable("role consent setting missing")
        conn.execute("UPDATE settings SET value=? WHERE category=? AND key=?", (json.dumps(values), *ROLE_SETTING))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise ConsentUnavailable("role consent audit or settings write failed; no permission was granted") from exc
    finally:
        conn.close()
    settings_db._changed(ROLE_SETTING[0], {ROLE_SETTING[1]: values})
    return {"ok": True, "target": target, "provider": provider, "acknowledged": acknowledged,
            "scope": scope, "warning": Resolved(provider, descriptor.policy, descriptor.note, scope).warning}
