"""Task-aware, strict-local text generation for unattended auxiliary work."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType

from agents.core.env_config import env_str

from .auxiliary_recovery import (
    auxiliary_temperature_recovery_scope,
    may_omit_rejected_output_cap,
)
from .base import LMStudioBackend, OllamaBackend
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
    "soul_description": ("JARVIS_AUX_SOUL_DESCRIPTION_MODEL", DEFAULT_LOCAL_MODEL, True),
})


def _direct_local_request_check(router, backend, model, prompt, system, max_tokens, temperature):
    """Bind a private auxiliary prompt to its owned loopback HTTPX route."""
    from .data_handling import DataHandlingRefused
    from .direct_transport import require_direct_async_transport
    from .model_roles import public_local_origin, same_origin

    if type(backend) not in (LMStudioBackend, OllamaBackend):
        raise DataHandlingRefused("private auxiliary backend is unsupported")
    endpoint = str(backend.base_url)
    client = backend.client
    hooks = client.event_hooks.get("request", [])
    if not hooks or getattr(hooks[-1], "_nerva_egress_recorder", False) is not True:
        raise DataHandlingRefused("private auxiliary final request guard is unavailable")
    final_hook = hooks[-1]
    lm_studio = type(backend) is LMStudioBackend
    path = "/v1/chat/completions" if lm_studio else "/api/generate"
    if (not public_local_origin(endpoint)
            or not same_origin(endpoint, str(client.base_url))):
        raise DataHandlingRefused("private auxiliary endpoint is not local")
    expected = client.build_request("POST", path).url
    if not same_origin(endpoint, str(expected)):
        raise DataHandlingRefused("private auxiliary endpoint changed")
    require_direct_async_transport(client, expected)

    def request_check(request):
        try:
            selected = router.local_backend
        except Exception as exc:
            raise DataHandlingRefused("private auxiliary backend changed") from exc
        current_hooks = client.event_hooks.get("request", [])
        if (selected is not backend or backend.client is not client
                or not public_local_origin(str(backend.base_url))
                or not same_origin(endpoint, str(backend.base_url))
                or not current_hooks or current_hooks[-1] is not final_hook
                or request.method != "POST" or request.url != expected):
            raise DataHandlingRefused("private auxiliary destination changed")
        require_direct_async_transport(client, request.url)
        try:
            if len(request.content) > 65536:
                raise ValueError("request too large")
            body = json.loads(request.content)
        except (RuntimeError, TypeError, ValueError) as exc:
            raise DataHandlingRefused("private auxiliary request changed") from exc
        if type(body) is not dict or body.get("model") != model or body.get("stream") is not False:
            raise DataHandlingRefused("private auxiliary model request changed")
        if lm_studio:
            messages = ([{"role": "system", "content": system}] if system and system.strip() else [])
            messages.append({"role": "user", "content": prompt})
            allowed = {"model", "messages", "stream", "max_tokens", "temperature"}
            cap_valid = (body["max_tokens"] == max_tokens if "max_tokens" in body
                         else may_omit_rejected_output_cap(backend, model))
            if (set(body) - allowed or body.get("messages") != messages
                    or not cap_valid
                    or ("temperature" in body and body["temperature"] != temperature)):
                raise DataHandlingRefused("private auxiliary prompt changed")
        else:
            options = body.get("options")
            if (set(body) != {"model", "prompt", "system", "stream", "options"}
                    or body.get("prompt") != prompt or body.get("system") != system
                    or type(options) is not dict
                    or set(options) - {"num_ctx", "num_predict", "temperature"}
                    or options.get("num_predict") != max_tokens
                    or options.get("temperature") != temperature):
                raise DataHandlingRefused("private auxiliary prompt changed")

    return request_check


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
        if task in {"session_title", "query_rewrite", "soul_description"} and "qwen3" in model.lower():
            prompt = f"{prompt}\n/no_think"
        request_check = (_direct_local_request_check(
            router, backend, model, prompt, system, max_tokens, temperature)
                         if task == "soul_description" else None)
        with auxiliary_request_scope(router, backend, model, role=task,
                                     request_check=request_check):
            if task == "compression":
                from agents.core.compaction_hold import DEFAULT_IDLE, stream_summary

                recovery = ({"call_scope": lambda: auxiliary_temperature_recovery_scope(
                    backend, model, role=task)} if isinstance(backend, LMStudioBackend) else {})
                return await stream_summary(
                    backend, DEFAULT_IDLE if summary_idle is None else summary_idle,
                    model=model, prompt=prompt, system=system,
                    max_tokens=max_tokens, temperature=temperature, **recovery,
                )
            if isinstance(backend, LMStudioBackend):
                with auxiliary_temperature_recovery_scope(backend, model, role=task):
                    return await backend.generate(
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
