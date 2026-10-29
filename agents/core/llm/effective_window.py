"""Synchronous, request-local capacity metadata; never probes or unwraps backends."""
import inspect
from dataclasses import dataclass


@dataclass(frozen=True)
class EffectiveWindow:
    tokens: int | None = None
    valid: bool = True
    # Set only by the raw backend metadata read. Job/configured ceilings and
    # estimated family budgets may govern dispatch but are not H686 evidence.
    backend_tokens: int | None = None

    def authoritative_tokens(self) -> int | None:
        """One immutable, actual backend window suitable for status projection."""
        value = self.backend_tokens
        if (self.valid and type(value) is int and 0 < value <= 1_000_000_000_000
                and type(self.tokens) is int and self.tokens == value):
            return value
        return None


def resolve_effective_window(backend, model: str) -> EffectiveWindow:
    from .job_selection import selected_window
    pinned = selected_window(model)
    if pinned is not None:
        return EffectiveWindow(pinned)
    try:
        reader = getattr(backend, 'context_window', None)
        if reader is None:
            return EffectiveWindow()
        if not callable(reader):
            return EffectiveWindow(valid=False)
        value = reader(model)
        if inspect.isawaitable(value):
            if inspect.iscoroutine(value):
                value.close()
            return EffectiveWindow(valid=False)
        if value is None:
            return EffectiveWindow()
        if type(value) is not int or value <= 0:
            return EffectiveWindow(valid=False)
        return EffectiveWindow(value, backend_tokens=value)
    except Exception:
        return EffectiveWindow(valid=False)


def authoritative_context_window(backend, model: str, *, resolved: int | None = None) -> int | None:
    """Physical backend window only; a configured/model-family fallback is insufficient."""
    try:
        reader = getattr(backend, 'context_window', None)
        if not callable(reader):
            return None
        value = reader(model)
        if inspect.isawaitable(value):
            if inspect.iscoroutine(value):
                value.close()
            return None
        if type(value) is not int or not 0 < value <= 1_000_000_000_000:
            return None
        if resolved is not None and (type(resolved) is not int or resolved != value):
            return None
        return value
    except Exception:
        return None
