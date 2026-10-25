"""Task-aware, strict-local text generation for unattended auxiliary work.

One rail for every side task (H414, Hermes' ``auxiliary_client``): the fixed tasks in
``_TASKS`` and the open-ended ``run_oneshot`` all resolve the same way — the router's
fail-closed local backend, a task-scoped model override, the job-pin exclusion, the
auxiliary data-handling scope (an inherited owner principal cannot authorize the
unattended call) and the model usage scope that attributes the spend to the ambient
turn without threading a session id through the caller. Every call is stateless: no
history goes in unless the caller puts it in the prompt, and nothing here writes a turn.
"""

from __future__ import annotations

import copy
import json
import re
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
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


class AuxiliaryBackendFailure(RuntimeError):
    """The local backend answered a one-shot with its fixed failure text, not an answer."""


_TASKS: Mapping[str, tuple[str, str, bool]] = MappingProxyType({
    "session_title": ("JARVIS_AUX_SESSION_TITLE_MODEL", DEFAULT_LOCAL_MODEL, True),
    "query_rewrite": ("JARVIS_AUX_QUERY_REWRITE_MODEL", DEFAULT_LOCAL_MODEL, True),
    "review": ("JARVIS_AUX_REVIEW_MODEL", "google/gemma-4-31b-a4b", True),
    "compression": ("JARVIS_AUX_COMPRESSION_MODEL", DEFAULT_LOCAL_MODEL, True),
    "acquisition_capability": ("JARVIS_AUX_ACQUISITION_CAPABILITY_MODEL", "local", False),
    "acquisition_draft": ("JARVIS_AUX_ACQUISITION_DRAFT_MODEL", "local", False),
    "soul_description": ("JARVIS_AUX_SOUL_DESCRIPTION_MODEL", DEFAULT_LOCAL_MODEL, True),
    # H414: the open-ended stateless call (``run_oneshot``). Same rail, its own override.
    "oneshot": ("JARVIS_AUX_ONESHOT_MODEL", DEFAULT_LOCAL_MODEL, True),
})

#: A one-shot's output budget: the ceiling a caller may ask for, and the default.
MAX_ONESHOT_TOKENS = 1024
DEFAULT_ONESHOT_TOKENS = 256
#: The prompt and the system text are each bounded; a one-shot is a side call, not a
#: context window. The compression summariser owns the long-input case.
MAX_ONESHOT_CHARS = 48_000
#: The ``/btw`` side question: how much of the conversation it reads, how long the
#: question may be, how long the answer may be.
BTW_SNAPSHOT_CHARS = 12_000
BTW_QUESTION_CHARS = 1_000
BTW_MAX_TOKENS = 400
#: Purposes are short labels (``btw``, ``plugin:weather``); the ledger keeps this many.
MAX_ONESHOT_PURPOSES = 64
_PURPOSE = re.compile(r"[a-z][a-z0-9_.:-]{0,63}")
_ONESHOT_USAGE: dict[str, dict] = {}
_ONESHOT_LOCK = threading.Lock()


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
    selected = raw.strip(" ")
    # A cosmetic title always defaults to the declared small local model. Other
    # auxiliary tasks keep their existing active-model fallback.
    return selected or (fallback if task == "session_title" else active_model or fallback)


def prepare_local_auxiliary(router, task: str):
    """Bind one local route for an operation; guard every awaited attempt afresh."""
    if not isinstance(task, str) or task not in _TASKS:
        raise AuxiliaryConfigError("unknown auxiliary task")
    exclude_job_pins = _TASKS[task][2]
    if exclude_job_pins and current_selection() is not None:
        raise SelectionError("job model pins exclude auxiliary calls")
    active_model = None if task == "session_title" else getattr(router, "active_model", None)
    model = resolve_auxiliary_model(task, active_model)
    backend = router.local_backend

    async def generate(*, system: str, prompt: str, max_tokens: int,
                       temperature: float, summary_idle: float | None = None,
                       on_token: Callable[[str], Awaitable[None] | None] | None = None) -> str:
        if exclude_job_pins and current_selection() is not None:
            raise SelectionError("job model pins exclude auxiliary calls")
        if task in {"session_title", "query_rewrite", "soul_description"} and "qwen3" in model.lower():
            prompt = f"{prompt}\n/no_think"
        request_check = (_direct_local_request_check(
            router, backend, model, prompt, system, max_tokens, temperature)
                         if task == "soul_description" else None)
        from agents.core.turn_usage import model_usage_scope
        with auxiliary_request_scope(router, backend, model, role=task,
                                     request_check=request_check), model_usage_scope(model=model, route="local"):
            if task == "compression":
                from agents.core.compaction_hold import DEFAULT_IDLE, stream_summary

                recovery = ({"call_scope": lambda: auxiliary_temperature_recovery_scope(
                    backend, model, role=task)} if isinstance(backend, LMStudioBackend) else {})
                return await stream_summary(
                    backend, DEFAULT_IDLE if summary_idle is None else summary_idle,
                    model=model, prompt=prompt, system=system,
                    max_tokens=max_tokens, temperature=temperature, **recovery,
                )
            # H414: a one-shot caller's stream hook rides the same guarded scope — the
            # whole-call guard covers a streamed request exactly as a whole one.
            kwargs = {"model": model, "prompt": prompt, "system": system,
                      "max_tokens": max_tokens, "temperature": temperature}
            if on_token is not None:
                kwargs["on_token"] = on_token
            call = backend.generate_stream if on_token is not None else backend.generate
            if isinstance(backend, LMStudioBackend):
                with auxiliary_temperature_recovery_scope(backend, model, role=task):
                    return await call(**kwargs)
            return await call(**kwargs)

    return generate


async def generate_local_auxiliary(
    router, task: str, *, system: str, prompt: str, max_tokens: int,
    temperature: float, summary_idle: float | None = None,
) -> str:
    """Generate once on the selected local backend with H513's whole-call guard."""
    generate = prepare_local_auxiliary(router, task)
    return await generate(system=system, prompt=prompt, max_tokens=max_tokens,
                          temperature=temperature, summary_idle=summary_idle)


# ── H414: the open-ended stateless call ───────────────────────────────────────────


def _bounded_text(value, *, name: str, required: bool) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise AuxiliaryConfigError(f"one-shot {name} must be a non-empty string")
    if len(value) > MAX_ONESHOT_CHARS:
        raise AuxiliaryConfigError(f"one-shot {name} exceeds {MAX_ONESHOT_CHARS} characters")
    return value


def _record_oneshot(purpose: str, *, prompt_chars: int, max_tokens: int,
                    model: str | None, answered: bool) -> None:
    """Count the call under its purpose. Bounded: the oldest label makes room."""
    with _ONESHOT_LOCK:
        row = _ONESHOT_USAGE.get(purpose)
        if row is None:
            if len(_ONESHOT_USAGE) >= MAX_ONESHOT_PURPOSES:
                oldest = min(_ONESHOT_USAGE, key=lambda key: _ONESHOT_USAGE[key]["last_at"])
                del _ONESHOT_USAGE[oldest]
            row = _ONESHOT_USAGE[purpose] = {"calls": 0, "answered": 0, "refused": 0,
                                             "prompt_chars": 0, "max_tokens": 0, "model": None}
        row["calls"] += 1
        row["answered" if answered else "refused"] += 1
        row["prompt_chars"] += prompt_chars
        row["max_tokens"] = max(row["max_tokens"], max_tokens)
        if model is not None:
            row["model"] = model
        row["last_at"] = time.time()


def oneshot_usage() -> dict[str, dict]:
    """What ``run_oneshot`` has been asked to do, per purpose, since the hub started.

    Calls, answers, refusals, prompt characters, the largest output budget and the
    model that last answered. A copy: the ledger itself is not handed out."""
    with _ONESHOT_LOCK:
        return copy.deepcopy(_ONESHOT_USAGE)


async def run_oneshot(
    router, prompt: str, *, purpose: str, system: str | None = None,
    max_tokens: int = DEFAULT_ONESHOT_TOKENS, temperature: float = 0.2,
    on_token: Callable[[str], Awaitable[None] | None] | None = None,
) -> str:
    """One stateless side call on the auxiliary rail (Hermes' ``run_oneshot``).

    For the side work the fixed tasks do not name — a ``/btw`` question, a plugin's own
    completion. It is the same rail, not a shortcut past it: ``prepare_local_auxiliary``
    picks the fail-closed local backend and the ``oneshot`` task's model, refuses under
    a job model pin, and wraps the request in the auxiliary data-handling scope and the
    model usage scope. What this adds is the bounds an open-ended caller needs — a
    short ``purpose`` label, a capped output budget, bounded prompt and system text —
    and a per-purpose usage ledger (``oneshot_usage``). It never reads or writes a
    session turn: history reaches the model only if the caller puts it in *prompt*.
    ``on_token`` streams the answer through the same guarded scope.
    """
    if not isinstance(purpose, str) or _PURPOSE.fullmatch(purpose) is None:
        raise AuxiliaryConfigError("one-shot purpose must be a short lowercase label")
    prompt = _bounded_text(prompt, name="prompt", required=True)
    system = _bounded_text(system, name="system", required=False)
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= MAX_ONESHOT_TOKENS:
        raise AuxiliaryConfigError(f"one-shot max_tokens must be an int in 1..{MAX_ONESHOT_TOKENS}")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise AuxiliaryConfigError("one-shot temperature must be a number in 0..2")
    prompt_chars = len(prompt) + len(system)
    model = None
    try:
        generate = prepare_local_auxiliary(router, "oneshot")
        model = resolve_auxiliary_model("oneshot", getattr(router, "active_model", None))
        answer = await generate(system=system, prompt=prompt, max_tokens=max_tokens,
                                temperature=temperature, on_token=on_token)
        # The local backends answer a failed call with a fixed degraded text instead of
        # raising (H681); that is a failure, not an answer, and the ledger says so.
        from .base import is_backend_failure_reply

        if is_backend_failure_reply(answer):
            raise AuxiliaryBackendFailure("the local model did not answer")
    except BaseException:
        _record_oneshot(purpose, prompt_chars=prompt_chars, max_tokens=max_tokens,
                        model=model, answered=False)
        raise
    _record_oneshot(purpose, prompt_chars=prompt_chars, max_tokens=max_tokens,
                    model=model, answered=True)
    return answer
