"""Explicit provider capabilities and reviewed model effort declarations.

Wire references (reviewed 2026-09-15): ai.google.dev/gemini-api/docs/generate-content/thinking,
platform.openai.com/docs/api-reference/chat/create, openrouter.ai/docs/guides/best-practices/reasoning-tokens.
Unknown providers/models remain silent; catalog data never invents a wire schema.
"""
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import replace
from urllib.parse import urlsplit

from .reasoning_effort import ReasoningEffortRefused, clamp_vocabulary
from .request_context import current_session, selected_reasoning

# Exact model IDs, not speculative family prefixes. Gemini 2.5 uses budgets,
# not levels; the adapter translates these product rungs into bounded budgets.
GEMINI_LEVELS = {
    'gemini-2.5-pro': ('low', 'medium', 'high'),
    'gemini-2.5-flash': ('low', 'medium', 'high'),
    'gemini-2.5-flash-lite': ('low', 'medium', 'high'),
    'gemini-3.1-pro': ('low', 'medium', 'high'),
    'gemini-3.1-pro-preview': ('low', 'medium', 'high'),
    'gemini-3-flash-preview': ('minimal', 'low', 'medium', 'high'),
    'gemini-3.1-flash-lite': ('minimal', 'low', 'medium', 'high'),
}

_HEADER = re.compile(r"[A-Za-z0-9-]{1,64}\Z")
_BODY_PROTECTED = {
    "model", "messages", "input", "contents", "prompt", "system", "systemInstruction",
    "tools", "tool_choice", "toolConfig", "stream", "store", "provider", "include",
    "authorization", "headers", "api_key", "base_url", "endpoint", "url", "transport",
    "client", "generationConfig", "cachedContent", "max_tokens", "max_output_tokens",
    "num_predict", "temperature", "prompt_cache_key", "prompt_cache_retention",
}
_HEADER_PROTECTED = {
    "authorization", "proxy-authorization", "cookie", "host", "content-type",
    "accept", "accept-encoding", "user-agent", "x-api-key", "api-key",
    "anthropic-version", "x-goog-api-key", "openai-organization", "openai-project",
    "chatgpt-account-id", "x-openai-internal-codex-residency",
}
_CHAT_SIDECARS = frozenset({
    "codex_reasoning_items", "codex_message_items", "tool_name", "effect_disposition",
    "timestamp", "platform_message_id", "api_content", "anthropic_content_blocks",
    "bedrock_content_blocks", "message_uid", "reasoning_details",
})
_TOOL_CALL_SIDECARS = frozenset({"call_id", "response_item_id", "extra_content"})
_UNSET = object()


class ProfileRequestRefused(ValueError):
    """A provider declaration cannot change a governed request field."""


def require_profile_base(profile, native_base):
    """A fixed-wire adapter may use only its reviewed destination."""
    declared = getattr(profile, "default_base_url", None)
    if type(declared) is not str or type(native_base) is not str:
        raise ProfileRequestRefused("invalid provider destination")
    try:
        left, right = urlsplit(declared), urlsplit(native_base)
        same = ((left.scheme.lower(), left.hostname, left.port, left.path.rstrip("/"))
                == (right.scheme.lower(), right.hostname, right.port, right.path.rstrip("/")))
        if not same or any((left.username, left.password, left.query, left.fragment)):
            raise ProfileRequestRefused("profile destination differs from native adapter")
    except ValueError:
        raise ProfileRequestRefused("invalid provider destination") from None


def require_profile_kind(profile, backend_kind, api_mode):
    """Bind a declaration to the adapter's actual physical wire schema."""
    if (getattr(profile, "backend_kind", None) != backend_kind
            or getattr(profile, "api_mode", None) != api_mode):
        raise ProfileRequestRefused("profile wire schema differs from native adapter")


def _owned_json(value, *, maximum=16384):
    try:
        wire = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(wire.encode("utf-8")) > maximum:
            raise ProfileRequestRefused("profile request declaration too large")
        return json.loads(wire)
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, ProfileRequestRefused):
            raise
        raise ProfileRequestRefused("profile request declaration is not bounded JSON") from None


def profile_headers(profile, original=None):
    """Add only static, non-governing headers from a profile."""
    declared = getattr(profile, "default_headers", {}) or {}
    if not isinstance(declared, Mapping) or len(declared) > 32:
        raise ProfileRequestRefused("invalid profile headers")
    result = dict(original or {})
    seen = {key.lower() for key in result}
    for key, value in declared.items():
        if (type(key) is not str or not _HEADER.fullmatch(key)
                or key.lower() in seen or key.lower() in _HEADER_PROTECTED
                or key.lower().startswith(("proxy-", "x-openai-", "sec-"))
                or type(value) is not str or not value or len(value) > 512
                or any(ord(char) < 32 or ord(char) > 126 for char in value)):
            raise ProfileRequestRefused("profile header overrides governed request")
        result[key] = value
        seen.add(key.lower())
    return result


def prepare_profile_messages(profile, messages, *, preserve_replay=False):
    """Sanitize donor chat sidecars, call the hook, then guard owned history.

    Codex's opaque replay is carried outside the hook and reattached unchanged.
    The caller performs any model-specific developer-role conversion afterward.
    """
    from .provider_replay import KEY
    if preserve_replay and getattr(profile, "id", None) != "openai-codex":
        raise ProfileRequestRefused("only Codex can preserve model replay")
    if type(messages) is not list or len(messages) > 256 or any(type(row) is not dict for row in messages):
        raise ProfileRequestRefused("invalid profile messages")
    replay = []
    sanitized = []
    for row in messages:
        if any(type(key) is not str for key in row):
            raise ProfileRequestRefused("invalid profile message key")
        if KEY in row and not preserve_replay:
            raise ProfileRequestRefused("opaque provider replay cannot cross profile")
        replay.append(_owned_json(row[KEY], maximum=128 * 1024) if KEY in row else None)
        clean = {key: value for key, value in row.items()
                 if type(key) is str and key not in _CHAT_SIDECARS
                 and key != KEY and not key.startswith("_")}
        if clean.get("role") == "tool":
            clean.pop("name", None)
        if type(clean.get("tool_calls")) is list:
            if len(clean["tool_calls"]) > 64:
                raise ProfileRequestRefused("profile tool history exceeds bound")
            clean["tool_calls"] = [
                {key: value for key, value in call.items()
                 if key not in _TOOL_CALL_SIDECARS}
                if type(call) is dict else call for call in clean["tool_calls"]]
        if clean.get("role") == "assistant" and not clean.get("tool_calls"):
            clean.pop("tool_calls", None)
        sanitized.append(clean)
    if preserve_replay:
        replay = _owned_json(replay, maximum=256 * 1024)
    original = _owned_json(sanitized, maximum=256 * 1024)
    if type(original) is not list or len(original) > 256 or any(type(row) is not dict for row in original):
        raise ProfileRequestRefused("invalid profile messages")
    prepared = _owned_json(profile.prepare_messages(_owned_json(original, maximum=256 * 1024)),
                           maximum=256 * 1024)
    if type(prepared) is not list or len(prepared) != len(original):
        raise ProfileRequestRefused("profile changed message count")
    for before, after, sidecar in zip(original, prepared, replay, strict=True):
        if type(after) is not dict:
            raise ProfileRequestRefused("invalid prepared message")
        if set(after) != set(before):
            raise ProfileRequestRefused("profile changed message structure")
        for key in ("tool_calls", "tool_call_id", KEY):
            if before.get(key) != after.get(key):
                raise ProfileRequestRefused("profile changed tool or replay history")
        if before.get("role") == "tool" and before != after:
            raise ProfileRequestRefused("profile changed tool result")
        if sidecar is not None and before != after:
            raise ProfileRequestRefused("profile changed replay-bound assistant history")
        if before.get("role") != after.get("role") and not (
                getattr(profile, "id", None) == "openai-codex"
                and before.get("role") == "system" and after.get("role") == "developer"):
            raise ProfileRequestRefused("profile changed message authority")
    if preserve_replay:
        for row, sidecar in zip(prepared, replay, strict=True):
            if sidecar is not None:
                row[KEY] = sidecar
    return prepared


def profile_reasoning_config(profile, model, default_effort=None, *,
                             passthrough_undeclared=False, vocabulary=_UNSET,
                             supports_wire=True):
    """Describe the actual selected H679 rung to both request hooks."""
    chosen = selected_reasoning(default_effort)
    if vocabulary is _UNSET:
        vocabulary = profile.supported_reasoning_efforts(model)
    if not supports_wire:
        return {"enabled": False} if vocabulary == () else None
    if chosen == "none" or vocabulary == ():
        return {"enabled": False}
    if vocabulary is None:
        return ({"enabled": True, "effort": chosen}
                if passthrough_undeclared and chosen else None)
    if chosen is None or chosen == "":
        return None
    level, reason = clamp_vocabulary(vocabulary, chosen)
    if reason == "below-minimum":
        raise ReasoningEffortRefused()
    return {"enabled": True, "effort": level} if level is not None else {"enabled": False}


def profile_request_defaults(profile, model, *, session_id=None, context=None):
    """Snapshot bounded profile hooks before a transport finalizes its wire body.

    A declared positive output cap is a conservative ceiling over explicit Nerva
    limits; it can fill only an otherwise absent or automatic limit.
    """
    if type(model) is not str or not model or len(model) > 256:
        raise ProfileRequestRefused("invalid profile model")
    if session_id is not None and (type(session_id) is not str or len(session_id) > 256):
        raise ProfileRequestRefused("invalid profile session")
    context = _owned_json(context or {})
    if type(context) is not dict or set(context) & {"model", "session_id"}:
        raise ProfileRequestRefused("invalid profile context")
    # Hooks receive independent JSON copies. A mutable nested value such as
    # reasoning_config must not let the first hook rewrite the control used by
    # the second hook or by the authority check below.
    body_context = _owned_json(context)
    kwargs_context = _owned_json(context)
    raw_body = profile.build_extra_body(session_id=session_id, model=model, **body_context)
    extra, kwargs = profile.build_api_kwargs_extras(
        reasoning_config=kwargs_context.get("reasoning_config"), model=model,
        session_id=session_id, **{key: value for key, value in kwargs_context.items()
                                  if key != "reasoning_config"})
    if type(extra) is not dict or type(kwargs) is not dict or type(raw_body) is not dict:
        raise ProfileRequestRefused("invalid profile request extras")
    if set(raw_body) & set(extra) or (set(raw_body) | set(extra)) & set(kwargs):
        raise ProfileRequestRefused("profile request additions collide")
    body = _owned_json({**raw_body, **extra})
    top = _owned_json(kwargs)
    if set(body) & _BODY_PROTECTED or set(top) & _BODY_PROTECTED:
        raise ProfileRequestRefused("profile request overrides governed field")
    # A hook may restate the already-selected rung, but cannot invent or raise
    # one. Dedicated transports still perform their final wire reconciliation.
    requested_reasoning = {key: value for key, value in {**body, **top}.items()
                           if key in {"reasoning", "reasoning_effort", "thinking"}}
    if requested_reasoning:
        configuration = context.get("reasoning_config")
        if type(configuration) is not dict or configuration.get("enabled") is not True:
            raise ProfileRequestRefused("profile reasoning is not declared")
        level = configuration.get("effort")
        if type(level) is not str or "thinking" in requested_reasoning:
            raise ProfileRequestRefused("profile reasoning exceeds the selected effort")
        if ("reasoning_effort" in requested_reasoning
                and requested_reasoning["reasoning_effort"] != level):
            raise ProfileRequestRefused("profile reasoning exceeds the selected effort")
        if ("reasoning" in requested_reasoning
                and requested_reasoning["reasoning"] not in (
                    {"effort": level}, {"effort": level, "enabled": True})):
            raise ProfileRequestRefused("profile reasoning exceeds the selected effort")
    if len(body) > 32 or len(top) > 32:
        raise ProfileRequestRefused("profile request has too many additions")
    cap = profile.get_max_tokens(model)
    if cap is not None and (type(cap) is not int or not 1 <= cap <= 1_000_000):
        raise ProfileRequestRefused("invalid profile output cap")
    fixed = getattr(profile, "fixed_temperature", None)
    from .providers import OMIT_TEMPERATURE
    omit_temperature = fixed == OMIT_TEMPERATURE
    if not omit_temperature and fixed is not None and (
            type(fixed) not in {int, float} or not math.isfinite(fixed)
            or not 0 <= fixed <= 2):
        raise ProfileRequestRefused("invalid profile temperature")
    return {"extra_body": body, "api_kwargs": top, "headers": profile_headers(profile),
            "max_tokens": cap, "fixed_temperature": fixed if not omit_temperature else None,
            "omit_temperature": omit_temperature}


def apply_profile_request(profile, payload, *, model=None, session_id=None,
                          context=None, cap_key="max_tokens", temperature_key="temperature"):
    """Merge only bounded additions into an owned wire draft before final guards."""
    if type(payload) is not dict:
        raise ProfileRequestRefused("invalid provider request")
    model = model or payload.get("model")
    if session_id is None:
        session_id = current_session() or None
    defaults = profile_request_defaults(profile, model, session_id=session_id, context=context)
    additions = {**defaults["extra_body"], **defaults["api_kwargs"]}
    if set(additions) & set(payload):
        raise ProfileRequestRefused("profile request collides with owned body")
    payload.update(additions)
    cap = defaults["max_tokens"]
    if cap is not None:
        current = payload.get(cap_key)
        if current is None or current == -1 or current == 0:
            payload[cap_key] = cap
        elif type(current) is int and current > 0:
            payload[cap_key] = min(current, cap)
        else:
            raise ProfileRequestRefused("invalid provider output cap")
    if defaults["omit_temperature"]:
        payload.pop(temperature_key, None)
    elif defaults["fixed_temperature"] is not None:
        payload[temperature_key] = defaults["fixed_temperature"]
    return payload


def profile_with_declarations(profile, declarations, *, defaults=None):
    """Build an immutable constructor-owned snapshot, never mutate the registry.

    Clearing settings discards previous constructor overrides while retaining
    the profile's immutable declarations. Other adapters keep their snapshots.
    """
    snapshot = dict(defaults or {})
    snapshot.update(profile.reasoning_declarations or {})
    if isinstance(declarations, str):
        try:
            declarations = json.loads(declarations)
        except (ValueError, TypeError):
            declarations = {}
    if isinstance(declarations, dict):
        snapshot.update({model: levels for model, levels in declarations.items()
                         if isinstance(model, str) and isinstance(levels, (list, tuple, str))})
    return replace(profile, reasoning_declarations=snapshot)


def compatible_parameters(profile, model, effort):
    effort = selected_reasoning(effort)
    params = {}
    sid = current_session()
    if profile.supports_prompt_cache_key and sid:
        params['prompt_cache_key'] = 'nerva-' + hashlib.sha256(
            json.dumps([profile.id, sid], separators=(',', ':')).encode()
        ).hexdigest()[:48]
    if 'reasoning-effort' in profile.capabilities:
        level, reason = clamp_vocabulary(profile.supported_reasoning_efforts(model), effort)
        if reason == "below-minimum":
            raise ReasoningEffortRefused()
        if level is not None:
            if profile.id == 'openrouter':
                params['reasoning'] = {'effort': level}
            else:
                params['reasoning_effort'] = level
    return params
