"""Model-scoped, offline eligibility for the selected main image route."""

from __future__ import annotations

from types import MappingProxyType


def main_vision_eligibility(backend: object, model: str) -> bool | None:
    """Read an exact, backend-owned model verdict without provider or network probes.

    ``backend.model_vision_capabilities`` may be a plain dict or read-only
    mapping proxy of exact model IDs to real booleans. A missing entry is
    unknown; provider-wide capabilities and model-name guesses are not proof.
    The snapshot is read directly from instance state so a property cannot
    initiate an ambient lookup while preparing an image turn.
    """
    if (type(model) is not str or not model or model.strip() != model
            or len(model) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in model)):
        return None
    try:
        state = object.__getattribute__(backend, "__dict__")
    except (AttributeError, TypeError):
        return None
    if type(state) is not dict:
        return None
    snapshot = state.get("model_vision_capabilities")
    if type(snapshot) not in (dict, MappingProxyType):
        return None
    verdict = snapshot.get(model)
    return verdict if type(verdict) is bool else None
