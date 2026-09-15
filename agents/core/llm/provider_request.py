"""Explicit provider capabilities and reviewed model effort declarations.

Wire references (reviewed 2026-09-15): ai.google.dev/gemini-api/docs/generate-content/thinking,
platform.openai.com/docs/api-reference/chat/create, openrouter.ai/docs/guides/best-practices/reasoning-tokens.
Unknown providers/models remain silent; catalog data never invents a wire schema.
"""
import hashlib
import json
from dataclasses import replace

from .reasoning_effort import ReasoningEffortRefused
from .request_context import current_session

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


def profile_with_declarations(profile, declarations, *, defaults=None):
    """Build an immutable constructor-owned snapshot, never mutate the registry.

    Clearing settings produces a fresh empty snapshot. Other live adapters keep
    their own declarations even when the next connection has different options.
    """
    snapshot = dict(defaults or {})
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
    params = {}
    sid = current_session()
    if profile.supports_prompt_cache_key and sid:
        params['prompt_cache_key'] = 'nerva-' + hashlib.sha256(
            json.dumps([profile.id, sid], separators=(',', ':')).encode()
        ).hexdigest()[:48]
    if 'reasoning-effort' in profile.capabilities:
        level, reason = profile.clamp_reasoning_effort(model, effort)
        if reason == "below-minimum":
            raise ReasoningEffortRefused()
        if level is not None:
            if profile.id == 'openrouter':
                params['reasoning'] = {'effort': level}
            else:
                params['reasoning_effort'] = level
    return params
