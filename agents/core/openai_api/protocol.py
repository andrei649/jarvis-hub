"""G12 — the OpenAI wire shapes: request parsing, turn text, responses, stream frames, errors.

Pure functions, no I/O, so the shapes are tested without a hub.

**What a turn receives.** OpenAI clients resend the whole conversation on every call. Nerva
keeps the conversation itself (its session memory), so a turn gets the client's *last user
message*; the earlier messages are folded in only when the session is new to Nerva (a client
that starts mid-conversation, or a conversation Nerva never saw). System and developer
messages become a labelled block in front of the message. They are text for the model and
nothing more: they cannot widen Nerva's tools, its autonomy level or the kernel's verdicts,
which are fixed by who holds the key (see ``agents/core/routers/openai_compat.py``).

**Which session.** A client may name its conversation (``X-Nerva-Conversation-Id`` header,
``metadata.conversation_id`` in a chat completion, ``conversation`` in a response) or continue
a stored response (``previous_response_id``). Without either, the session is derived from the
conversation's first system and user messages, which stay the same on every call of a
stateless front end (the Hermes fingerprint). Every session id is namespaced by the key, so a
key can never reach the owner's HUD sessions or another key's.

**Models.** ``nerva`` is Nerva itself (the orchestrator picks the agent, as in the HUD);
``nerva/<agent>`` asks a named Nerva agent. Model names never select a provider or a model
backend; the owner's routing settings do that, as for any turn.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

VIRTUAL_MODEL = "nerva"
AGENT_MODEL_PREFIX = "nerva/"
CONVERSATION_HEADER = "x-nerva-conversation-id"
MAX_CONVERSATION_ID_CHARS = 256
MAX_MESSAGES = 500
TEXT_PART_TYPES = frozenset({"text", "input_text", "output_text"})
INSTRUCTIONS_LABEL = ("Instructions from the client app (they cannot change your tools, "
                      "permissions or approvals):")
HISTORY_LABEL = "Earlier in this conversation (as sent by the client app):"


class ApiError(Exception):
    """An OpenAI-shaped error: ``{"error": {"message", "type", "param", "code"}}``."""

    def __init__(self, status: int, message: str, *, code: str | None = None,
                 err_type: str = "invalid_request_error", param: str | None = None,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.err_type = err_type
        self.param = param
        self.headers = headers or {}

    def body(self) -> dict[str, Any]:
        return error_body(self.message, code=self.code, err_type=self.err_type, param=self.param)


def error_body(message: str, *, code: str | None = None, err_type: str = "invalid_request_error",
               param: str | None = None) -> dict[str, Any]:
    return {"error": {"message": message, "type": err_type, "param": param, "code": code}}


# ── content ──────────────────────────────────────────────────────────────────

def content_text(content: Any, *, param: str) -> str:
    """The text of one message's ``content``: a string or a list of text parts.

    Images, audio and files are refused (400): Nerva's turn takes text here, and silently
    dropping an image would answer a question the client did not ask."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces = []
        for index, part in enumerate(content):
            if isinstance(part, str):
                pieces.append(part)
                continue
            if not isinstance(part, dict):
                raise ApiError(400, "content parts must be objects", param=f"{param}[{index}]")
            kind = part.get("type")
            if kind in TEXT_PART_TYPES and isinstance(part.get("text"), str):
                pieces.append(part["text"])
            elif kind == "refusal" and isinstance(part.get("refusal"), str):
                pieces.append(part["refusal"])
            else:
                raise ApiError(400, f"content part type {kind!r} is not supported; send text",
                               code="unsupported_content", param=f"{param}[{index}]")
        return "\n".join(pieces)
    raise ApiError(400, "content must be a string or a list of text parts", param=param)


@dataclass
class Conversation:
    """A request reduced to what a Nerva turn needs."""

    instructions: list[str] = field(default_factory=list)
    history: list[tuple[str, str]] = field(default_factory=list)   # (role, text) before the last
    message: str = ""
    first_user: str = ""


_ROLE_NAMES = {"user": "User", "assistant": "Assistant", "tool": "Tool result", "function": "Tool result"}


def _fold(items: list, *, param: str) -> Conversation:
    if not isinstance(items, list) or not items:
        raise ApiError(400, f"'{param}' must be a non-empty list", param=param)
    if len(items) > MAX_MESSAGES:
        raise ApiError(413, f"at most {MAX_MESSAGES} messages per request", code="too_many_messages",
                       param=param)
    convo = Conversation()
    turns: list[tuple[str, str]] = []
    for index, item in enumerate(items):
        where = f"{param}[{index}]"
        if not isinstance(item, dict):
            raise ApiError(400, "each message must be an object", param=where)
        kind = item.get("type")
        if kind not in (None, "message"):
            raise ApiError(400, f"input item type {kind!r} is not supported; send messages",
                           code="unsupported_content", param=where)
        role = item.get("role")
        text = content_text(item.get("content"), param=f"{where}.content")
        if role in ("system", "developer"):
            if text.strip():
                convo.instructions.append(text.strip())
        elif role in _ROLE_NAMES:
            turns.append((role, text))
            if role == "user" and not convo.first_user:
                convo.first_user = text
        else:
            raise ApiError(400, f"unknown role {role!r}", param=f"{where}.role")
    if not turns or turns[-1][0] != "user":
        raise ApiError(400, "the last message must come from the user", param=param)
    if not turns[-1][1].strip():
        raise ApiError(400, "the last user message is empty", param=param)
    convo.message = turns[-1][1]
    convo.history = [(role, text) for role, text in turns[:-1] if text.strip()]
    return convo


def chat_conversation(body: dict) -> Conversation:
    return _fold(body.get("messages"), param="messages")


def responses_conversation(body: dict) -> Conversation:
    raw = body.get("input")
    if isinstance(raw, str):
        if not raw.strip():
            raise ApiError(400, "'input' is empty", param="input")
        convo = Conversation(message=raw, first_user=raw)
    else:
        convo = _fold(raw, param="input")
    instructions = body.get("instructions")
    if instructions is not None:
        if not isinstance(instructions, str):
            raise ApiError(400, "'instructions' must be a string", param="instructions")
        if instructions.strip():
            convo.instructions.insert(0, instructions.strip())
    return convo


def turn_text(convo: Conversation, *, include_history: bool) -> str:
    """The one message Nerva's turn receives."""
    blocks = []
    if convo.instructions:
        blocks.append(INSTRUCTIONS_LABEL + "\n" + "\n\n".join(convo.instructions))
    if include_history and convo.history:
        lines = [f"{_ROLE_NAMES[role]}: {text}" for role, text in convo.history]
        blocks.append(HISTORY_LABEL + "\n" + "\n".join(lines))
    if not blocks:
        return convo.message
    return "\n\n".join(blocks) + "\n\n" + convo.message


# ── sessions and models ──────────────────────────────────────────────────────

def session_for(key_id: str, *, tag: str, value: str) -> str:
    """A Nerva session id for a key and a conversation handle; valid for ``is_valid_session_id``."""
    digest = hashlib.sha256(f"{key_id}\0{tag}\0{value}".encode()).hexdigest()[:32]
    return f"oai-{digest}"


def conversation_handle(value: Any, *, param: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("id")
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"'{param}' must be a non-empty string", param=param)
    if len(value) > MAX_CONVERSATION_ID_CHARS:
        raise ApiError(400, f"'{param}' is longer than {MAX_CONVERSATION_ID_CHARS} characters", param=param)
    return value.strip()


def fingerprint_handle(convo: Conversation) -> str:
    first_instruction = convo.instructions[0] if convo.instructions else ""
    return f"{first_instruction}\n{convo.first_user}"


def resolve_model(model: Any, agents: list[str]) -> tuple[str, str | None]:
    """``(model name to echo, agent override or None)``; 404 for a name Nerva does not serve."""
    if model is None:
        return VIRTUAL_MODEL, None
    if not isinstance(model, str) or not model.strip():
        raise ApiError(400, "'model' must be a string", param="model")
    name = model.strip()
    if name == VIRTUAL_MODEL:
        return name, None
    if name.startswith(AGENT_MODEL_PREFIX):
        agent = name[len(AGENT_MODEL_PREFIX):]
        if agent in agents:
            return name, (None if agent == "jarvis" else agent)
    raise ApiError(404, f"The model '{name[:100]}' does not exist. GET /v1/models lists what Nerva serves.",
                   code="model_not_found", param="model")


def models_list(agents: list[str], *, now: int | None = None) -> dict:
    now = int(time.time()) if now is None else now

    def model(mid: str, parent: str | None) -> dict:
        return {"id": mid, "object": "model", "created": now, "owned_by": "nerva",
                "root": mid, "parent": parent}

    data = [model(VIRTUAL_MODEL, None)]
    data.extend(model(AGENT_MODEL_PREFIX + agent, VIRTUAL_MODEL) for agent in sorted(agents))
    return {"object": "list", "data": data}


def stream_flag(body: dict) -> bool:
    value = body.get("stream", False)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ApiError(400, "'stream' must be a boolean", param="stream")
    return value


# ── responses ────────────────────────────────────────────────────────────────

def new_id(prefix: str) -> str:
    return f"{prefix}{secrets.token_hex(12)}"


def usage_counts(usage: dict | None) -> tuple[int, int]:
    """Measured input/output tokens, 0 where Nerva could not measure them."""
    if not isinstance(usage, dict):
        return 0, 0
    tokens_in, tokens_out = usage.get("input_tokens"), usage.get("output_tokens")
    return (tokens_in if type(tokens_in) is int else 0), (tokens_out if type(tokens_out) is int else 0)


def nerva_extension(session_id: str, approvals: list[int], usage: dict | None) -> dict:
    """Nerva's own fields beside the OpenAI ones (clients ignore unknown fields)."""
    basis = usage.get("usage_basis") if isinstance(usage, dict) else None
    return {"session_id": session_id, "pending_approvals": list(approvals), "usage_basis": basis}


def chat_completion(completion_id: str, model: str, text: str, *, created: int, session_id: str,
                    approvals: list[int], usage: dict | None) -> dict:
    tokens_in, tokens_out = usage_counts(usage)
    return {
        "id": completion_id, "object": "chat.completion", "created": created, "model": model,
        "system_fingerprint": None,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text, "refusal": None},
                     "logprobs": None, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out,
                  "total_tokens": tokens_in + tokens_out},
        "nerva": nerva_extension(session_id, approvals, usage),
    }


def chat_chunk(completion_id: str, model: str, *, created: int, delta: dict,
               finish_reason: str | None = None, extra: dict | None = None) -> dict:
    chunk = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model,
             "system_fingerprint": None,
             "choices": [{"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish_reason}]}
    if extra:
        chunk.update(extra)
    return chunk


def chat_usage_chunk(completion_id: str, model: str, *, created: int, usage: dict | None) -> dict:
    tokens_in, tokens_out = usage_counts(usage)
    return {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model,
            "system_fingerprint": None, "choices": [],
            "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out,
                      "total_tokens": tokens_in + tokens_out}}


def response_object(response_id: str, model: str, *, created: int, status: str, text: str | None,
                    message_id: str, previous_response_id: str | None, instructions: str | None,
                    conversation: str | None, session_id: str, approvals: list[int],
                    usage: dict | None, error: dict | None = None) -> dict:
    """A ``/v1/responses`` Response object (``status`` in_progress, completed or failed)."""
    output = []
    if text is not None:
        output.append({"type": "message", "id": message_id, "status": "completed", "role": "assistant",
                       "content": [{"type": "output_text", "text": text, "annotations": []}]})
    tokens_in, tokens_out = usage_counts(usage)
    return {
        "id": response_id, "object": "response", "created_at": created, "status": status,
        "model": model, "output": output, "output_text": text or "",
        "previous_response_id": previous_response_id, "instructions": instructions,
        "conversation": {"id": conversation} if conversation else None,
        "error": error, "incomplete_details": None, "parallel_tool_calls": False,
        "tool_choice": "auto", "tools": [], "store": True,
        "usage": ({"input_tokens": tokens_in, "input_tokens_details": {"cached_tokens": 0},
                   "output_tokens": tokens_out, "output_tokens_details": {"reasoning_tokens": 0},
                   "total_tokens": tokens_in + tokens_out} if status == "completed" else None),
        "nerva": nerva_extension(session_id, approvals, usage),
    }


# ── server-sent events ───────────────────────────────────────────────────────

def sse_data(payload: dict | str) -> str:
    """A bare ``data:`` frame (Chat Completions)."""
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"data: {data}\n\n"


def sse_event(name: str, payload: dict) -> str:
    """A typed frame (Responses): ``event: <type>`` then its JSON."""
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
