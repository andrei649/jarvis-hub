"""Task-aware, strict-local text generation for unattended auxiliary work."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from agents.core.env_config import env_str

from .data_handling import auxiliary_request_scope
from .job_selection import SelectionError, current_selection
from .model_config import DEFAULT_LOCAL_MODEL


class AuxiliaryConfigError(ValueError):
    """An auxiliary task or explicit model override is invalid."""


_TASKS: Mapping[str, tuple[str, str, bool]] = MappingProxyType({
    "session_title": ("JARVIS_AUX_SESSION_TITLE_MODEL", DEFAULT_LOCAL_MODEL, True),
    "query_rewrite": ("JARVIS_AUX_QUERY_REWRITE_MODEL", DEFAULT_LOCAL_MODEL, True),
    "review": ("JARVIS_AUX_REVIEW_MODEL", "google/gemma-4-31b-a4b", True),
    "compression": ("JARVIS_AUX_COMPRESSION_MODEL", DEFAULT_LOCAL_MODEL, True),
    "acquisition_capability": ("JARVIS_AUX_ACQUISITION_CAPABILITY_MODEL", "local", False),
    "acquisition_draft": ("JARVIS_AUX_ACQUISITION_DRAFT_MODEL", "local", False),
})


def resolve_auxiliary_model(
    task: str, active_model: str | None, *, env: Mapping[str, str] | None = None,
) -> str:
    """Resolve a fixed task's model from one current, validated environment read."""
    if not isinstance(task, str) or task not in _TASKS:
        raise AuxiliaryConfigError("unknown auxiliary task")
    name, fallback, _ = _TASKS[task]
    raw = env_str(name) if env is None else env.get(name, "")
    if not isinstance(raw, str) or len(raw) > 256 or not raw.isprintable():
        raise AuxiliaryConfigError("invalid auxiliary model override")
    return raw.strip(" ") or active_model or fallback


def prepare_local_auxiliary(router, task: str):
    """Bind one local route for an operation; guard every awaited attempt afresh."""
    if not isinstance(task, str) or task not in _TASKS:
        raise AuxiliaryConfigError("unknown auxiliary task")
    exclude_job_pins = _TASKS[task][2]
    if exclude_job_pins and current_selection() is not None:
        raise SelectionError("job model pins exclude auxiliary calls")
    model = resolve_auxiliary_model(task, getattr(router, "active_model", None))
    backend = router.local_backend

    async def generate(*, system: str, prompt: str, max_tokens: int,
                       temperature: float, summary_idle: float | None = None) -> str:
        if exclude_job_pins and current_selection() is not None:
            raise SelectionError("job model pins exclude auxiliary calls")
        if task in {"session_title", "query_rewrite"} and "qwen3" in model.lower():
            prompt = f"{prompt}\n/no_think"
        with auxiliary_request_scope(router, backend, model, role=task):
            if task == "compression":
                from agents.core.compaction_hold import DEFAULT_IDLE, stream_summary

                return await stream_summary(
                    backend, DEFAULT_IDLE if summary_idle is None else summary_idle,
                    model=model, prompt=prompt, system=system,
                    max_tokens=max_tokens, temperature=temperature,
                )
            return await backend.generate(
                model=model, prompt=prompt, system=system,
                max_tokens=max_tokens, temperature=temperature,
            )

    return generate


async def generate_local_auxiliary(
    router, task: str, *, system: str, prompt: str, max_tokens: int,
    temperature: float, summary_idle: float | None = None,
) -> str:
    """Generate once on the selected local backend with H513's whole-call guard."""
    generate = prepare_local_auxiliary(router, task)
    return await generate(system=system, prompt=prompt, max_tokens=max_tokens,
                          temperature=temperature, summary_idle=summary_idle)
