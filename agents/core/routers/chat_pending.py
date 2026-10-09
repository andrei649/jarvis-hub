"""Authenticated discovery/replies to live HTTP clarification; same model turn."""

import asyncio
import hashlib
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.background import BackgroundTask

from ..app_state import get_orch
from ._deps import _web, user_guard

router = APIRouter(tags=["chat"])


def http_actor(request: Request):
    """Derive identity from currently valid server credentials, never payloads."""
    web = _web()
    admin = request.headers.get("x-admin-token", "")
    user = request.headers.get("x-user-token", "")
    if web._user_credential_required():
        if web._admin_credential_ok(admin):
            identity = f"admin\0{admin}"
        elif web._user_credential_ok(user_supplied=user, admin_supplied=""):
            identity = f"user\0{user}"
        else:
            return None
    else:
        peer = web._real_client_host(request)
        if peer not in web._LOCALHOSTS:
            return None
        identity = f"localhost\0{peer}\0{web._web_principal(request).admin}"
    return hashlib.sha256(identity.encode()).hexdigest()


@asynccontextmanager
async def http_chat_binding(orch, request: Request, session_id):
    actor = http_actor(request)
    service = getattr(orch, "_pending_input_service", None)
    runtime = service() if actor is not None and callable(service) else None
    if runtime is None or runtime.enabled() is not True:
        yield
        return
    task = asyncio.current_task()

    async def disconnect():
        while True:
            # The request body is already parsed. Await the disconnect event;
            # is_disconnected's cancelled scope can swallow watcher.cancel().
            if (await request.receive())["type"] == "http.disconnect":
                task.cancel()
                return

    with runtime.bind_http(actor, session_id, None, lambda: http_actor(request) == actor, poll=True):
        watcher = asyncio.create_task(disconnect(), name="chat-pending-disconnect")
        try:
            yield
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


@router.get("/chat/pending", dependencies=[Depends(user_guard)])
async def list_pending(request: Request,
                       session_id: str | None = Query(default=None, max_length=128),
                       offset: int = Query(default=0, ge=0, le=4096),
                       limit: int = Query(default=20, ge=1, le=32)):
    from ..session_continuation import is_valid_session_id

    if session_id is not None and not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid_session_id"}, status_code=422,
                            headers={"Cache-Control": "no-store"})
    runtime = getattr(get_orch(), "__dict__", {}).get("_pending_inputs")
    actor = http_actor(request)
    questions, has_more = (runtime.http_questions(actor, session_id=session_id, offset=offset, limit=limit)
                           if runtime is not None and actor is not None else ([], False))

    async def acknowledged():
        if runtime is not None:
            for question in questions:
                runtime.acknowledge_http(question["id"], actor)

    return JSONResponse({"questions": questions, "has_more": has_more},
                        headers={"Cache-Control": "no-store"}, background=BackgroundTask(acknowledged))


class PendingAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str | list[str] | None = Field(default=None, description=
        "Nonempty answer or up to four selected labels/numbers; 16384 characters total. Omit when cancelling.")
    other: bool = False
    cancel: bool = False

    @model_validator(mode="after")
    def bounded_answer(self):
        if self.cancel:
            if self.answer is not None or self.other:
                raise ValueError("cancel cannot include an answer")
            return self
        values = [self.answer] if isinstance(self.answer, str) else self.answer
        if (not isinstance(values, list) or not 1 <= len(values) <= 4
                or any(not isinstance(v, str) or not v.strip() for v in values)
                or sum(len(v) for v in values) > 16384
                or (self.other and not isinstance(self.answer, str))):
            raise ValueError("bounded nonempty answer required")
        return self


@router.post("/chat/pending/{prompt_id}/answer", dependencies=[Depends(user_guard)])
async def answer_pending(request: Request, body: PendingAnswer,
                         prompt_id: str = Path(pattern=r"^[0-9a-f]{32}$")):
    orch = get_orch()
    runtime = getattr(orch, "__dict__", {}).get("_pending_inputs")
    actor = http_actor(request)
    result = (runtime.answer_http(prompt_id, actor, body.answer, other=body.other, cancel=body.cancel)
              if runtime is not None and actor is not None else "unavailable")
    status = {"resolved": 200, "invalid": 422, "unavailable": 404}[result]
    return JSONResponse({"ok": result == "resolved", "status": result}, status_code=status,
                        headers={"Cache-Control": "no-store"})
