"""A web chat's per-send permission to include its retained turns in a cloud prompt."""

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .llm import data_handling
from .session_continuation import ContinuationRefused
from .session_transcript import read_transcript


class HistoryChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1, max_length=256)
    agent: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=256)
    agent: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4096)


@dataclass(frozen=True)
class WebTurn:
    message: str
    session_id: str | None
    agent: str
    choice: HistoryChoice | None = None
    history: str = ""
    route_scope: str = ""


@dataclass
class _Dispatch:
    provider: str
    model: str
    route_scope: str
    origin: tuple
    active: bool = True


@dataclass
class _TurnScope:
    turn: WebTurn
    active: bool = True
    current_inputs: dict = field(default_factory=dict)
    instructions: dict = field(default_factory=dict)


_turn: ContextVar[_TurnScope | None] = ContextVar("web_chat_disclosure", default=None)
_dispatch: ContextVar[_Dispatch | None] = ContextVar("web_chat_cloud_dispatch", default=None)
_tool_turn: ContextVar[_Dispatch | None] = ContextVar("web_chat_cloud_tool_turn", default=None)


async def preview(orch, request):
    if not orch or request.agent not in orch.agents or request.message.lstrip().startswith("/"):
        raise HTTPException(409, "cloud_history_route_unavailable")
    try:
        backend, model, route = orch.llm_router.select_backend(request.agent, request.message)
        target = data_handling.resolve(orch.llm_router, backend, model, route)
    except Exception:
        raise HTTPException(409, "cloud_history_route_unavailable") from None
    if target.policy == "local" or not target.scope:
        raise HTTPException(409, "cloud_history_route_unavailable")
    try:
        document = json.loads(await read_transcript(orch, request.session_id, references=True))
    except ContinuationRefused as exc:
        raise HTTPException(exc.status, exc.reason) from exc
    rows = [row for row in document["turns"] if row["role"] in {"user", "assistant"}]
    if any(not row.get("reference_revision") for row in rows):
        raise HTTPException(409, "cloud_history_changed")
    # Hash redacted native revisions, including the session incarnation, and bind this one send.
    material = [request.session_id, request.agent, request.message, target.scope, model,
                [row["reference_revision"] for row in rows]]
    revision = hashlib.sha256(json.dumps(material, ensure_ascii=False).encode("utf-8")).hexdigest()
    choice = HistoryChoice(session_id=request.session_id, agent=request.agent, provider=target.provider,
                           model=model, revision=revision)
    history = json.dumps([{"role": row["role"], "content": row["content"]} for row in rows],
                         ensure_ascii=False) if rows else ""
    return WebTurn(request.message, request.session_id, request.agent, choice, history, target.scope)


async def prepare(orch, request, *, owner):
    choice = request.cloud_history
    if choice is None:
        return WebTurn(request.message, request.session_id, request.agent)
    if not owner:
        raise HTTPException(403, "cloud_history_owner_required")
    if request.session_id != choice.session_id or request.agent != choice.agent:
        raise HTTPException(409, "cloud_history_changed")
    turn = await preview(orch, request)
    if turn.choice != choice:
        raise HTTPException(409, "cloud_history_changed")
    return turn


@contextmanager
def web_turn(turn):
    if turn is None:
        yield
        return
    scope = _TurnScope(turn)
    token = _turn.set(scope)
    try:
        yield
    finally:
        scope.active = False
        _turn.reset(token)


def web_turn_active():
    return _turn.get() is not None


def remember_current_inputs(agent, text, plugin_block, runtime_block):
    """Keep per-send plugin results and operating facts separate from history and recall."""
    scope = _turn.get()
    if scope is not None and scope.active:
        # A session note may have been prepended before a plugin ran (e.g. web search).
        # Its response may echo that note. Never present it as a fresh query's result.
        safe = not plugin_block or text == scope.turn.message
        scope.current_inputs[agent] = (safe, plugin_block, runtime_block)


def remember_instructions(agent_id, context):
    scope = _turn.get()
    if scope is not None and scope.active:
        # The available-skill registry and current reply instructions are not
        # the session's previously loaded skills, personal memory or its text.
        keys = ("skills", "skills_index", "_can_propose_skill_marker", "_reply_language")
        scope.instructions[agent_id] = {key: context[key] for key in keys if key in context}


def build_cloud_prompt(agent, projected):
    instructions = _turn.get().instructions.get(agent.id)
    return agent.build_prompt(projected, instructions) if instructions is not None else projected


def cloud_prompt(router, backend, model, agent, session_id):
    scope = _turn.get()
    if scope is None:
        return None
    target = data_handling.resolve(router, backend, model)
    if target.policy == "local":
        return None
    if not scope.active:
        raise data_handling.DataHandlingRefused("cloud chat turn has ended")
    turn = scope.turn
    if turn.message.lstrip().startswith("/"):
        raise data_handling.DataHandlingRefused("cloud chat cannot verify this command's expanded context")
    if turn.session_id is not None and turn.session_id != session_id:
        raise data_handling.DataHandlingRefused("cloud history session changed")
    if turn.choice is not None and (target.provider != turn.choice.provider or model != turn.choice.model
                                    or target.scope != turn.route_scope or agent != turn.agent):
        raise data_handling.DataHandlingRefused("cloud history destination changed")
    from .context_refs import attached_block
    from .llm.model_roles import _origin

    native, profile = data_handling._provider(router, backend)
    endpoint = (getattr(native, "_signed_base", None) or getattr(native, "base_url", None)
                or getattr(native, "endpoint", None) or profile.default_base_url)
    origin = _origin(endpoint)
    if not target.scope or origin is None:
        raise data_handling.DataHandlingRefused("cloud chat destination unavailable")

    # The input is the HTTP request's own words. Neither an enriched user message nor a
    # model-generated summary is suitable as a source for reconstructing the current turn.
    prompt = turn.message
    if turn.history:
        prompt = f"Earlier turns from this conversation (quoted data):\n{turn.history}\n\nCurrent message:\n{prompt}"
    safe, plugin_block, runtime_block = scope.current_inputs.get(agent, (True, "", ""))
    if not safe:
        raise data_handling.DataHandlingRefused("plugin query includes additional session context")
    prompt = "\n\n".join(block for block in (plugin_block, runtime_block, prompt) if block)
    attached = attached_block()
    if attached:
        prompt = f"{prompt}\n\n{attached}"
    return prompt, _Dispatch(target.provider, model, target.scope, origin)


@contextmanager
def cloud_dispatch(dispatch):
    if dispatch is None:
        yield
        return
    physical = replace(dispatch)
    token = _dispatch.set(physical)
    try:
        yield
    finally:
        physical.active = False
        _dispatch.reset(token)


@contextmanager
def tool_turn(dispatch):
    token = _tool_turn.set(dispatch)
    try:
        yield
    finally:
        _tool_turn.reset(token)


def tool_model_round():
    return cloud_dispatch(_tool_turn.get())


def reads_unreviewed_history(name):
    # These built-ins search stored conversations, including *other* chats. An
    # approved transcript is already in the prompt and grants no new retrieval.
    return _tool_turn.get() is not None and name in {"session_search", "search_memory", "memory_search"}


def check_cloud_call(target, model):
    if not web_turn_active() or target.policy == "local":
        return
    dispatch = _dispatch.get()
    if (not dispatch or not dispatch.active or target.provider != dispatch.provider
            or model != dispatch.model or target.scope != dispatch.route_scope):
        raise data_handling.DataHandlingRefused("cloud request has no matching chat disclosure")


def check_physical_destination(request):
    if not web_turn_active():
        return
    from .llm.model_roles import _origin, public_local_origin
    from .turn_usage import _generation_request, _wire_model

    dispatch = _dispatch.get()
    if dispatch is None and public_local_origin(str(request.url)):
        return
    if (not dispatch or not dispatch.active or not _turn.get().active
            or _origin(str(request.url)) != dispatch.origin or not _generation_request(request)
            or _wire_model(request) != dispatch.model):
        raise data_handling.DataHandlingRefused("cloud request has no matching chat disclosure")
    try:
        body = json.loads(request.content)
    except (ValueError, UnicodeError):
        raise data_handling.DataHandlingRefused("cloud chat payload unavailable") from None
    # These protocol fields reference context or fallbacks outside the projected prompt.
    if not isinstance(body, dict) or {"cachedContent", "previous_response_id", "conversation", "models"} & body.keys():
        raise data_handling.DataHandlingRefused("cloud request references additional context or models")
