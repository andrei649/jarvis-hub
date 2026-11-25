"""Two isolated, text-only model calls for the owner comparison surface."""

from __future__ import annotations

import asyncio
import threading
from contextlib import nullcontext

from agents.core.channels.outbound_safety import sanitize_outbound
from agents.core.env_config import env_flag
from agents.core.llm.anthropic import ClaudeBackend
from agents.core.llm.base import LMStudioBackend, OllamaBackend, is_degraded_reply
from agents.core.llm.data_handling import physical_request_scope
from agents.core.llm.direct_transport import require_direct_async_transport
from agents.core.llm.gemini import GeminiBackend
from agents.core.llm.hybrid_router import LOCAL_ONLY_AGENTS
from agents.core.llm.model_roles import public_local_origin, same_origin
from agents.core.llm.physical_local import ollama_local_selector, physical_local_scope
from agents.core.llm.providers import ProviderProfile
from agents.core.llm.request_context import primary_ollama_no_think
from agents.core.llm.vision_capability import read_local_model_metadata
from agents.core.reply_language import append_reply_language, requested_reply_language
from agents.core.security.guardrails import GuardrailsEngine
from agents.core.turn_usage import model_calls_from_snapshot, model_usage_scope, turn_usage_scope

_TIMEOUT_S = 120
_MAX_TOKENS = 1024
_SYSTEM = (
    "Answer the user's question directly as {name}, whose public role is {role}. "
    "Use the current question's requested language for the answer, including any draft or translation. "
    "If no language is requested, use the question's language. Preserve quotations in their "
    "original language unless the question asks to translate them. "
    "Do not use tools or assume access to private context."
)
_IN_FLIGHT = threading.Lock()


def acquire_comparison() -> bool:
    """One comparison at a time across event loops and HTTP worker threads; no wait queue."""
    return _IN_FLIGHT.acquire(blocking=False)


def release_comparison() -> None:
    _IN_FLIGHT.release()


def _preflight(backend, *, local: bool):
    """Require the final egress hook; local routes also need a direct loopback transport."""
    effective = backend._backend if type(backend) is GuardrailsEngine else backend
    if local and type(effective) not in (LMStudioBackend, OllamaBackend):
        raise ValueError("local backend is not physically proven")
    if not local:
        # These built-ins construct one text-only payload from the supplied prompt.
        # Hooked/custom providers may rewrite it or add opaque replay and are excluded.
        if type(effective) not in (GeminiBackend, ClaudeBackend) or type(effective.profile) is not ProviderProfile:
            raise ValueError("cloud text backend is not proven")
        if type(effective) is GeminiBackend:
            binding = effective.current_binding()
            if binding is not None and binding.cache_name:
                raise ValueError("cached cloud context is not permitted")
    client = effective.client
    hooks = client.event_hooks.get("request", ())
    if not hooks or getattr(hooks[-1], "_nerva_egress_recorder", False) is not True:
        raise ValueError("final request guard unavailable")
    if local:
        endpoint = str(effective.base_url)
        if not public_local_origin(endpoint) or not same_origin(endpoint, str(client.base_url)):
            raise ValueError("local endpoint is not loopback")
        path = "/v1/chat/completions" if type(effective) is LMStudioBackend else "/api/generate"
        expected = client.build_request("POST", path).url
        if not same_origin(endpoint, str(expected)):
            raise ValueError("local endpoint changed")
        require_direct_async_transport(client, expected)
    return effective


async def run_opinions(router, question: str, agents: list[str], *, allow_cloud: bool,
                       labels: dict[str, tuple[str, str]] | None = None,
                       is_disconnected=None) -> list[dict]:
    """Return two independent opinions in request order; never open an orchestrator turn."""
    labels = labels or {}

    async def one(agent_id: str) -> dict:
        def failed(reason: str) -> dict:
            return {"agent": agent_id, "ok": False, "reason": reason}

        try:
            if is_disconnected is not None and await is_disconnected():
                return failed("disconnected")
            backend, selected_model, route = router.select_backend(agent_id, question)
            local = route.startswith("local") or route == "ollama-howard"
            cloud = route.startswith(("cloud", "claude"))
            if route in {"local-moa", "hybrid-moa"}:
                return failed("route_unavailable")
            if cloud and not allow_cloud:
                return failed("cloud_disabled")
            if cloud and (agent_id in LOCAL_ONLY_AGENTS or env_flag("JARVIS_STRICT_LOCAL", False)):
                return failed("route_unavailable")
            if not local and not cloud:
                return failed("route_unavailable")
            native = _preflight(backend, local=local)
            bound_client = native.client
            bound_base_url = getattr(native, "base_url", None)
            bound_client_base_url = str(bound_client.base_url)
        except Exception:
            return failed("route_unavailable")

        count = 0

        def check():
            return router.check_data_handling(backend, selected_model, route)

        async def one_send(_request):
            nonlocal count
            if asyncio.current_task().cancelling():
                raise ValueError("comparison request was cancelled")
            if is_disconnected is not None and await is_disconnected():
                raise ValueError("comparison client disconnected")
            if (native.client is not bound_client
                    or getattr(native, "base_url", None) != bound_base_url
                    or str(bound_client.base_url) != bound_client_base_url
                    or (type(backend) is GuardrailsEngine and backend._backend is not native)):
                raise ValueError("comparison model destination changed")
            if count:
                raise ValueError("opinion HTTP retry refused")
            count += 1

        name, role = labels.get(agent_id, (agent_id, "assistant"))
        name = (str(name).splitlines() or [agent_id])[0][:80]
        role = (str(role).splitlines() or ["assistant"])[0][:120]
        system = append_reply_language(_SYSTEM.format(name=name, role=role), requested_reply_language(question))
        timer = asyncio.timeout(_TIMEOUT_S)
        try:
            # Context-local scopes keep parallel members independent, including a backend
            # that swallows an HTTP error and tries to return a degraded answer.
            with turn_usage_scope() as usage:
                with physical_local_scope() if local else nullcontext():
                    async with timer:
                        no_think = nullcontext()
                        if local and type(native) is OllamaBackend:
                            check()
                            client, base_url = native.client, native.base_url
                            client_base_url = str(client.base_url)
                            wire_model = ollama_local_selector(selected_model)
                            metadata = await read_local_model_metadata(native, wire_model, check=check)
                            check()
                            if (native.client is client and native.base_url == base_url
                                    and str(native.client.base_url) == client_base_url
                                    and native.supports_no_think(metadata)):
                                no_think = primary_ollama_no_think(native, wire_model)
                            if _preflight(backend, local=True) is not native:
                                raise ValueError("comparison backend changed")
                        with (
                            physical_request_scope(check, request_check=one_send),
                            model_usage_scope(model=selected_model, route=route, agent_id=agent_id),
                            no_think,
                        ):
                            answer = await backend.generate(selected_model, question, system=system,
                                                            max_tokens=_MAX_TOKENS)
                receipt = model_calls_from_snapshot(usage.snapshot())
            if count != 1 or not isinstance(answer, str) or not answer.strip() or is_degraded_reply(answer):
                return failed("generation_failed")
            safe = sanitize_outbound(answer.strip())
            if not isinstance(safe, str) or not safe.strip():
                return failed("generation_failed")
            result = {"agent": agent_id, "ok": True, "text": safe, "route": route}
            if receipt and len(receipt) == 1:
                result["model"] = receipt[0]["model"]
            return result
        except TimeoutError:
            return failed("timed_out")
        except Exception:
            return failed("timed_out" if timer.expired() else "generation_failed")

    return list(await asyncio.gather(*(one(aid) for aid in agents)))
