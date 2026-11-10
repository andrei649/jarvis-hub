"""G12 (H560 / H614) — an OpenAI-compatible API, so other chat apps can use Nerva as their backend.

Routes (all off until the owner turns ``openai_api.enabled`` on; each then demands a bearer key):

- ``POST /v1/chat/completions`` — streamed (SSE ``chat.completion.chunk`` frames, ``[DONE]``)
  or not; an ``Idempotency-Key`` on a non-streamed call returns the first answer to a retry.
- ``POST /v1/responses`` — the Responses API: stored responses, ``previous_response_id``
  chaining, named ``conversation``s, typed streaming events.
- ``GET`` / ``DELETE /v1/responses/{response_id}`` — a stored response, for the key that made it.
- ``GET /v1/models`` — ``nerva`` (Nerva itself) and ``nerva/<agent>`` for each Nerva agent.

What a request starts is an ordinary Nerva turn (``agents/core/openai_api/turn.py``): tools,
memory, the Action Kernel and the approval queue apply as for any turn. A key the owner marked
as the owner's speaks as the owner at the HUD; every other key speaks on the inbound
``openai_api`` channel, so its turns are untrusted and each mutating action waits for the
owner's approval. Nothing here lends a provider credential or proxies a raw model (that is
H376/H565/H584, excluded by design): the model name picks a Nerva agent, never a provider.

The credential is checked in the handler (``_admit``), not by a dependency: the hub's own
user/admin tokens do not open this API and an API key opens nothing else. The route-auth
matrix lists these routes as in-handler guarded and ``tests/test_route_inhandler_guards.py``
proves each refuses without a key and admits with one.

Errors use OpenAI's envelope ``{"error": {"message", "type", "param", "code"}}``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agents.core.app_state import get_orch
from agents.core.openai_api import policy, protocol
from agents.core.openai_api.protocol import ApiError
from agents.core.openai_api.store import ApiKey, get_store
from agents.core.openai_api.turn import NoModel, TurnBusy, TurnIncomplete, run_turn

logger = logging.getLogger("nerva.openai_api")

router = APIRouter(tags=["openai-compatible"])

_NO_STORE = {"Cache-Control": "no-store"}
_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


def _error(exc: ApiError, extra: dict | None = None) -> JSONResponse:
    body = exc.body()
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=exc.status, headers={**_NO_STORE, **exc.headers})


def _audit(kind: str, *, owner: bool, reason: str, request: Request) -> None:
    try:
        from agents.core.security.auth_audit import submit_auth_event

        submit_auth_event(kind, tier="admin" if owner else "user", reason=reason,
                          client=request.client.host if request.client else "")
    except Exception:  # noqa: BLE001 — the audit never decides the request
        logger.debug("openai_api: auth audit unavailable", exc_info=True)


def _admit(request: Request) -> ApiKey:
    """The switch, the bearer key and the key's rate limit, in that order."""
    if not policy.enabled():
        raise ApiError(404, "The OpenAI-compatible API is turned off. The owner turns it on in "
                       "Settings (openai_api.enabled).", code="api_disabled")
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    supplied = supplied.strip()
    if scheme.lower() != "bearer" or not supplied:
        _audit("auth_failure", owner=False, reason="missing", request=request)
        raise ApiError(401, "Missing API key. Send 'Authorization: Bearer <key>'.", code="invalid_api_key",
                       headers={"WWW-Authenticate": "Bearer"})
    key = get_store().verify(supplied)
    if key is None:
        _audit("auth_failure", owner=False, reason="invalid", request=request)
        raise ApiError(401, "Incorrect API key provided.", code="invalid_api_key",
                       headers={"WWW-Authenticate": "Bearer"})
    _audit("auth_success", owner=key.owner, reason="credential", request=request)
    if not policy.GATE.allow(key.key_id, policy.limits().rate_limit_per_min):
        raise ApiError(429, "Rate limit reached for this API key. Try again in a minute.",
                       code="rate_limit_exceeded", err_type="requests", headers={"Retry-After": "60"})
    return key


async def _read_json(request: Request) -> tuple[bytes, dict]:
    limit = policy.limits().max_request_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise ApiError(413, f"The request body is larger than {limit // 1024} KB.", code="request_too_large")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ApiError(413, f"The request body is larger than {limit // 1024} KB.", code="request_too_large")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        raise ApiError(400, "The request body is not valid JSON.", code="invalid_json") from None
    if not isinstance(body, dict):
        raise ApiError(400, "The request body must be a JSON object.", code="invalid_json")
    return raw, body


def _orch():
    orch = get_orch()
    if orch is None:
        raise ApiError(503, "Nerva is still starting.", code="not_ready", err_type="server_error")
    return orch


def _agents(orch) -> list[str]:
    agents = getattr(orch, "agents", None)
    return sorted(str(name) for name in agents) if isinstance(agents, dict) else []


def _check_size(text: str) -> None:
    cap = policy.limits().max_input_chars
    if len(text) > cap:
        raise ApiError(413, f"The conversation sent for this turn is longer than {cap} characters. "
                       "Start a new conversation or send less history.", code="context_length_exceeded")


def _turn_error(exc: Exception) -> ApiError:
    if isinstance(exc, TurnBusy):
        return ApiError(409, "Nerva is still answering the previous message in this conversation.",
                        code="conversation_busy")
    if isinstance(exc, NoModel):
        return ApiError(503, "No language model is loaded in Nerva yet.", code="model_unavailable",
                        err_type="server_error")
    return ApiError(502, "Nerva could not finish this turn.", code="agent_incomplete", err_type="server_error")


def _idempotency_refusal(response) -> ApiError:
    try:
        payload = json.loads(bytes(response.body).decode("utf-8"))
    except Exception:  # noqa: BLE001
        payload = {}
    headers = {"Retry-After": response.headers["retry-after"]} if "retry-after" in response.headers else None
    return ApiError(response.status_code, str(payload.get("detail") or "idempotency refused"),
                    code=str(payload.get("error") or "idempotency_error"), headers=headers)


class _Slot:
    """One of the key's concurrent-turn slots, released exactly once."""

    def __init__(self, key: ApiKey) -> None:
        self.key = key
        self.token: int | None = None

    def take(self) -> None:
        token = policy.GATE.acquire(self.key.key_id, policy.limits().max_concurrent)
        if token is None:
            raise ApiError(429, "This API key already has as many turns running as it may. "
                           "Wait for one to finish.", code="too_many_concurrent_requests",
                           err_type="requests", headers={"Retry-After": "5"})
        self.token = token

    def release(self) -> None:
        if self.token is not None:
            token, self.token = self.token, None
            policy.GATE.release(self.key.key_id, token)


# ── /v1/models ───────────────────────────────────────────────────────────────

@router.get("/v1/models")
async def openai_models(request: Request):
    try:
        _admit(request)
        orch = _orch()
    except ApiError as exc:
        return _error(exc)
    return JSONResponse(protocol.models_list(_agents(orch)), headers=_NO_STORE)


# ── /v1/chat/completions ─────────────────────────────────────────────────────

def _chat_session(request: Request, key: ApiKey, body: dict, convo: protocol.Conversation) -> str:
    handle = protocol.conversation_handle(request.headers.get(protocol.CONVERSATION_HEADER) or None,
                                          param=protocol.CONVERSATION_HEADER)
    metadata = body.get("metadata")
    if handle is None and isinstance(metadata, dict) and metadata.get("conversation_id") is not None:
        handle = protocol.conversation_handle(metadata.get("conversation_id"), param="metadata.conversation_id")
    if handle is not None:
        return protocol.session_for(key.key_id, tag="conversation", value=handle)
    return protocol.session_for(key.key_id, tag="fingerprint", value=protocol.fingerprint_handle(convo))


@router.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    from agents.core import idempotency

    started = None
    try:
        key = _admit(request)
        raw, body = await _read_json(request)
        orch = _orch()
        stream = protocol.stream_flag(body)
        model, agent = protocol.resolve_model(body.get("model"), _agents(orch))
        convo = protocol.chat_conversation(body)
        session_id = _chat_session(request, key, body, convo)
        store = get_store()
        known = await asyncio.to_thread(store.conversation_turns, session_id, key.key_id) > 0
        text = protocol.turn_text(convo, include_history=not known)
        _check_size(text)
        stream_options = body.get("stream_options")
        include_usage = isinstance(stream_options, dict) and stream_options.get("include_usage") is True
        if stream:
            refusal = idempotency.check_header(request)
            if refusal is not None:
                raise _idempotency_refusal(refusal)
            slot = _Slot(key)
            slot.take()
            return StreamingResponse(
                _chat_stream(orch, key, slot, text, session_id=session_id, agent=agent, model=model,
                             known=known, include_usage=include_usage),
                media_type="text/event-stream", headers=_SSE_HEADERS)
        started = await asyncio.to_thread(idempotency.begin, request, f"openai_api:{key.key_id}", raw)
        if started.refusal is not None:
            raise _idempotency_refusal(started.refusal)
        if started.replay is not None:
            ref = started.replay.ref or {}
            stored = await asyncio.to_thread(store.get_response, str(ref.get("id", "")), key.key_id)
            if stored is None:
                raise ApiError(409, "This Idempotency-Key was used, but its answer is no longer stored.",
                               code="idempotency_expired")
            return JSONResponse(stored[1], headers={**_NO_STORE, idempotency.REPLAYED_HEADER: "true"})
    except ApiError as exc:
        return _error(exc)

    slot = _Slot(key)
    try:
        slot.take()
    except ApiError as exc:
        if started.claim is not None:
            started.claim.release()
        return _error(exc)
    try:
        if started.claim is not None:
            async with started.claim.kept_alive():
                outcome = await run_turn(orch, key, text, session_id=session_id, agent_override=agent,
                                         known_session=known)
        else:
            outcome = await run_turn(orch, key, text, session_id=session_id, agent_override=agent,
                                     known_session=known)
    except (TurnBusy, NoModel, TurnIncomplete) as exc:
        if started.claim is not None:
            started.claim.release()
        approvals = getattr(exc, "approvals", [])
        return _error(_turn_error(exc), {"nerva": {"session_id": session_id, "pending_approvals": approvals}})
    except BaseException:
        if started.claim is not None:
            started.claim.release()
        raise
    finally:
        slot.release()
    await asyncio.to_thread(store.record_turn, session_id, key.key_id)
    completion_id = protocol.new_id("chatcmpl-")
    completion = protocol.chat_completion(completion_id, model, outcome.text, created=int(time.time()),
                                          session_id=session_id, approvals=outcome.approvals,
                                          usage=outcome.usage)
    if started.claim is not None:
        await asyncio.to_thread(store.save_response, completion_id, key.key_id, session_id, completion)
        await asyncio.to_thread(started.claim.done, {"id": completion_id})
    return JSONResponse(completion, headers=_NO_STORE)


async def _chat_stream(orch, key: ApiKey, slot: _Slot, text: str, *, session_id: str, agent: str | None,
                       model: str, known: bool, include_usage: bool):
    """``chat.completion.chunk`` frames; the turn runs in a task that a disconnect cancels."""
    completion_id = protocol.new_id("chatcmpl-")
    created = int(time.time())
    queue: asyncio.Queue = asyncio.Queue()

    async def on_token(token: str) -> None:
        await queue.put(("token", token))

    async def runner() -> None:
        try:
            outcome = await run_turn(orch, key, text, session_id=session_id, agent_override=agent,
                                     known_session=known, on_token=on_token)
        except (TurnBusy, NoModel, TurnIncomplete) as exc:
            await queue.put(("error", exc))
            return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — reported in the stream, never as content
            logger.exception("openai_api: stream runner failed")
            await queue.put(("error", TurnIncomplete("turn_failed")))
            return
        await asyncio.to_thread(get_store().record_turn, session_id, key.key_id)
        await queue.put(("end", outcome))

    task = asyncio.create_task(runner())
    try:
        yield protocol.sse_data(protocol.chat_chunk(completion_id, model, created=created,
                                                    delta={"role": "assistant", "content": ""}))
        streamed = False
        while True:
            kind, data = await queue.get()
            if kind == "token":
                if data:
                    streamed = True
                    yield protocol.sse_data(protocol.chat_chunk(completion_id, model, created=created,
                                                                delta={"content": data}))
            elif kind == "end":
                if not streamed:     # a reply that arrived whole (a command, a cached answer)
                    yield protocol.sse_data(protocol.chat_chunk(completion_id, model, created=created,
                                                                delta={"content": data.text}))
                extra = {"nerva": protocol.nerva_extension(session_id, data.approvals, data.usage)}
                yield protocol.sse_data(protocol.chat_chunk(completion_id, model, created=created, delta={},
                                                            finish_reason="stop", extra=extra))
                if include_usage:
                    yield protocol.sse_data(protocol.chat_usage_chunk(completion_id, model, created=created,
                                                                      usage=data.usage))
                yield protocol.sse_data("[DONE]")
                break
            else:
                error = _turn_error(data)
                payload = error.body()
                payload["nerva"] = {"session_id": session_id,
                                    "pending_approvals": getattr(data, "approvals", [])}
                yield protocol.sse_data(payload)
                yield protocol.sse_data("[DONE]")
                break
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("openai_api: stream cleanup failed")
        slot.release()


# ── /v1/responses ────────────────────────────────────────────────────────────

@router.post("/v1/responses")
async def openai_create_response(request: Request):
    try:
        key = _admit(request)
        _raw, body = await _read_json(request)
        orch = _orch()
        stream = protocol.stream_flag(body)
        model, agent = protocol.resolve_model(body.get("model"), _agents(orch))
        convo = protocol.responses_conversation(body)
        store = get_store()
        response_id = protocol.new_id("resp_")
        previous = body.get("previous_response_id")
        conversation = protocol.conversation_handle(body.get("conversation"), param="conversation")
        if previous is not None and conversation is not None:
            raise ApiError(400, "Send either 'previous_response_id' or 'conversation', not both.",
                           param="previous_response_id")
        if previous is not None:
            if not isinstance(previous, str) or not previous:
                raise ApiError(400, "'previous_response_id' must be a string", param="previous_response_id")
            stored = await asyncio.to_thread(store.get_response, previous, key.key_id)
            if stored is None:
                raise ApiError(404, f"No stored response '{previous[:80]}' for this key.",
                               code="previous_response_not_found", param="previous_response_id")
            session_id = stored[0]
        elif conversation is not None:
            session_id = protocol.session_for(key.key_id, tag="conversation", value=conversation)
        elif convo.history:
            session_id = protocol.session_for(key.key_id, tag="fingerprint",
                                              value=protocol.fingerprint_handle(convo))
        else:
            session_id = protocol.session_for(key.key_id, tag="response", value=response_id)
        keep = body.get("store", True)
        if not isinstance(keep, bool):
            raise ApiError(400, "'store' must be a boolean", param="store")
        known = await asyncio.to_thread(store.conversation_turns, session_id, key.key_id) > 0
        text = protocol.turn_text(convo, include_history=not known)
        _check_size(text)
        instructions = body.get("instructions") if isinstance(body.get("instructions"), str) else None
        context = {"response_id": response_id, "model": model, "previous": previous,
                   "instructions": instructions, "conversation": conversation, "keep": keep,
                   "session_id": session_id}
        slot = _Slot(key)
        slot.take()
    except ApiError as exc:
        return _error(exc)
    if stream:
        return StreamingResponse(_responses_stream(orch, key, slot, text, agent=agent, known=known, **context),
                                 media_type="text/event-stream", headers=_SSE_HEADERS)
    created = int(time.time())
    try:
        outcome = await run_turn(orch, key, text, session_id=session_id, agent_override=agent,
                                 known_session=known)
    except (TurnBusy, NoModel, TurnIncomplete) as exc:
        return _error(_turn_error(exc), {"nerva": {"session_id": session_id,
                                                   "pending_approvals": getattr(exc, "approvals", [])}})
    finally:
        slot.release()
    await asyncio.to_thread(store.record_turn, session_id, key.key_id)
    obj = _response(context, created=created, status="completed", text=outcome.text,
                    approvals=outcome.approvals, usage=outcome.usage)
    if keep:
        await asyncio.to_thread(store.save_response, response_id, key.key_id, session_id, obj)
    return JSONResponse(obj, headers=_NO_STORE)


def _response(context: dict, *, created: int, status: str, text: str | None, approvals: list[int],
              usage: dict | None, error: dict | None = None, message_id: str | None = None) -> dict:
    return protocol.response_object(
        context["response_id"], context["model"], created=created, status=status, text=text,
        message_id=message_id or "msg_" + context["response_id"][len("resp_"):],
        previous_response_id=context["previous"], instructions=context["instructions"],
        conversation=context["conversation"], session_id=context["session_id"], approvals=approvals,
        usage=usage, error=error)


async def _responses_stream(orch, key: ApiKey, slot: _Slot, text: str, *, agent: str | None, known: bool,
                            **context: Any):
    """The Responses API's typed events, each with its ``sequence_number``."""
    created = int(time.time())
    session_id = context["session_id"]
    message_id = "msg_" + context["response_id"][len("resp_"):]
    queue: asyncio.Queue = asyncio.Queue()
    sequence = 0

    def event(name: str, **fields: Any) -> str:
        nonlocal sequence
        payload = {"type": name, "sequence_number": sequence, **fields}
        sequence += 1
        return protocol.sse_event(name, payload)

    async def on_token(token: str) -> None:
        await queue.put(("token", token))

    async def runner() -> None:
        try:
            outcome = await run_turn(orch, key, text, session_id=session_id, agent_override=agent,
                                     known_session=known, on_token=on_token)
        except (TurnBusy, NoModel, TurnIncomplete) as exc:
            await queue.put(("error", exc))
            return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("openai_api: responses stream runner failed")
            await queue.put(("error", TurnIncomplete("turn_failed")))
            return
        await asyncio.to_thread(get_store().record_turn, session_id, key.key_id)
        await queue.put(("end", outcome))

    task = asyncio.create_task(runner())
    try:
        pending = _response(context, created=created, status="in_progress", text=None, approvals=[], usage=None)
        yield event("response.created", response=pending)
        yield event("response.in_progress", response=pending)
        item = {"type": "message", "id": message_id, "status": "in_progress", "role": "assistant", "content": []}
        yield event("response.output_item.added", output_index=0, item=item)
        yield event("response.content_part.added", item_id=message_id, output_index=0, content_index=0,
                    part={"type": "output_text", "text": "", "annotations": []})
        parts: list[str] = []
        while True:
            kind, data = await queue.get()
            if kind == "token":
                if data:
                    parts.append(data)
                    yield event("response.output_text.delta", item_id=message_id, output_index=0,
                                content_index=0, delta=data, logprobs=[])
            elif kind == "end":
                if not parts:
                    parts.append(data.text)
                    yield event("response.output_text.delta", item_id=message_id, output_index=0,
                                content_index=0, delta=data.text, logprobs=[])
                final_text = data.text
                part = {"type": "output_text", "text": final_text, "annotations": []}
                yield event("response.output_text.done", item_id=message_id, output_index=0, content_index=0,
                            text=final_text, logprobs=[])
                yield event("response.content_part.done", item_id=message_id, output_index=0, content_index=0,
                            part=part)
                yield event("response.output_item.done", output_index=0,
                            item={**item, "status": "completed", "content": [part]})
                done = _response(context, created=created, status="completed", text=final_text,
                                 approvals=data.approvals, usage=data.usage)
                if context["keep"]:
                    await asyncio.to_thread(get_store().save_response, context["response_id"], key.key_id,
                                            session_id, done)
                yield event("response.completed", response=done)
                break
            else:
                error = _turn_error(data)
                failed = _response(context, created=created, status="failed", text=None,
                                   approvals=getattr(data, "approvals", []), usage=None,
                                   error={"code": error.code, "message": error.message})
                yield event("response.failed", response=failed)
                break
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("openai_api: responses stream cleanup failed")
        slot.release()


@router.get("/v1/responses/{response_id}")
async def openai_get_response(response_id: str, request: Request):
    try:
        key = _admit(request)
        stored = await asyncio.to_thread(get_store().get_response, response_id, key.key_id)
        if stored is None:
            raise ApiError(404, f"No stored response '{response_id[:80]}' for this key.", code="not_found")
    except ApiError as exc:
        return _error(exc)
    return JSONResponse(stored[1], headers=_NO_STORE)


@router.delete("/v1/responses/{response_id}")
async def openai_delete_response(response_id: str, request: Request):
    try:
        key = _admit(request)
        deleted = await asyncio.to_thread(get_store().delete_response, response_id, key.key_id)
        if not deleted:
            raise ApiError(404, f"No stored response '{response_id[:80]}' for this key.", code="not_found")
    except ApiError as exc:
        return _error(exc)
    return JSONResponse({"id": response_id, "object": "response.deleted", "deleted": True}, headers=_NO_STORE)
