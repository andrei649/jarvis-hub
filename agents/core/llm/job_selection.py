"""Closed-lifetime model selection for one scheduled model phase."""
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

PROVIDERS = frozenset({'lm-studio', 'ollama', 'gemini', 'anthropic', 'openrouter', 'openai-compatible'})


class SelectionError(RuntimeError):
    """An explicit job selection cannot be honored safely."""


@dataclass
class _Lifetime:
    open: bool = True
    resolved: tuple | None = None


@dataclass(frozen=True)
class Selection:
    model: str | None
    provider: str | None
    lifetime: _Lifetime

    def check(self):
        if not self.lifetime.open:
            raise SelectionError('job model scope is closed')


_selection: ContextVar[Selection | None] = ContextVar('job_model_selection', default=None)


def validate_pins(options):
    if 'model' in options:
        model = options['model']
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}', model):
            raise ValueError('model must be a bounded model identifier')
    if 'provider' in options and (not isinstance(options['provider'], str) or options['provider'] not in PROVIDERS):
        raise ValueError('provider must name a configured model adapter')
    if options.get('no_agent') and ('model' in options or 'provider' in options):
        raise ValueError('model/provider pins require an agent')


def current_selection():
    selection = _selection.get()
    if selection is not None:
        selection.check()
    return selection


@contextmanager
def selection_scope(options):
    validate_pins(options)
    if not ('model' in options or 'provider' in options):
        yield
        return
    selection = Selection(options.get('model'), options.get('provider'), _Lifetime())
    token = _selection.set(selection)
    try:
        yield selection
    finally:
        selection.lifetime.open = False
        _selection.reset(token)


class _ScopedBackend:
    def __init__(self, backend, model, selection):
        self._backend = backend
        self._model = model
        self._selection = selection

    def __getattr__(self, name):
        value = getattr(self._backend, name)
        if name not in {'generate', 'generate_stream', 'generate_turn', 'generate_tool_turn'}:
            return value

        async def call(*args, **kwargs):
            self._selection.check()
            requested = kwargs.get('model', args[0] if args else None)
            if requested != self._model:
                raise SelectionError('job model changed during execution')
            resolved = self._selection.lifetime.resolved
            if resolved is not None:
                from .tokenizer import estimate_tokens
                window = resolved[2]
                reserve = kwargs.get('max_tokens', window // 4)
                if type(reserve) is not int or reserve <= 0 or reserve > window // 4:
                    raise SelectionError('job completion budget exceeds resolved window')
                if estimate_tokens(json.dumps([args, kwargs], default=str)) + reserve > window:
                    raise SelectionError('job prompt exceeds resolved context window')
            result = await value(*args, **kwargs)
            self._selection.check()
            return result
        return call


def scoped_backend(backend, model):
    selection = current_selection()
    return _ScopedBackend(backend, model, selection) if selection is not None else backend


def apply_selection(router, agent_id, backend, model, route):
    """Constrain existing routing; selecting a provider never expands cloud policy.

    Local adapters can be selected explicitly. Cloud adapters must be the provider
    chosen by the existing policy for this request (including spend/fallback gates).
    """
    selection = current_selection()
    if selection is None:
        return backend, model, route
    if route.startswith(('local', 'ollama')):
        provider = 'ollama' if backend is getattr(router, '_ollama_backend', None) else router._backend_name
    elif route == 'claude':
        provider = 'anthropic'
    elif backend is getattr(router, '_compatible_backend', None):
        provider = getattr(getattr(backend, 'profile', None), 'id', None)
    else:
        provider = 'gemini'
    baseline_backend, baseline_model = backend, model
    wanted = selection.provider
    if wanted and wanted != provider:
        if wanted == 'lm-studio' and router._local_available and router._backend_name == wanted:
            backend, model, route = router._backend, router._local_model, 'local'
        elif wanted == 'ollama' and router._ollama_available:
            backend, model, route = router._ollama_backend, router.get_howard_model(), 'local-ollama'
        else:
            raise SelectionError('requested provider is unavailable or not selected by agent policy')
    if selection.model:
        model = selection.model
    from ..context_compressor import MODEL_WINDOWS, window_for
    probe = getattr(backend, 'context_window', None)
    window = probe(model) if callable(probe) else None
    if type(window) is not int or window <= 0:
        name = model.lower().rsplit('/', 1)[-1]
        if route.startswith(('local', 'ollama')) and (backend is not baseline_backend or model != baseline_model):
            raise SelectionError('changed local model requires a known loaded context window')
        if not any(name.startswith(family) for family in MODEL_WINDOWS) and model != baseline_model:
            raise SelectionError('pinned model context window is unknown')
        window = window_for(model)
    if window < 2048:
        raise SelectionError('pinned context window is too small for the job runtime')
    resolved = selection.lifetime.resolved
    if resolved is not None and (resolved[0] is not backend or resolved[1:] != (model, window)):
        raise SelectionError('job provider/model/window changed during execution')
    selection.lifetime.resolved = (backend, model, window)
    return scoped_backend(backend, model), model, route


def selected_window(model=None):
    """Resolved request window, or None for ordinary unpinned work."""
    selection = current_selection()
    if selection is None:
        return None
    resolved = selection.lifetime.resolved
    if resolved is None or (model is not None and model != resolved[1]):
        raise SelectionError('job model capability resolution is missing or mismatched')
    return resolved[2]
