"""Synchronous, request-local capacity metadata; never probes or unwraps backends."""
import inspect
from dataclasses import dataclass


@dataclass(frozen=True)
class EffectiveWindow:
    tokens: int | None = None
    valid: bool = True


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
        return EffectiveWindow(value)
    except Exception:
        return EffectiveWindow(valid=False)
