"""Governed replies for live channel inbox threads."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from .automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    one_of,
    predicate,
)
from .autonomy.dry_run import preview_task
from .channel_inbox import SUPPORTED_INBOX_CHANNELS, ChannelInboxStore
from .channels.ephemeral import EphemeralReply, ephemeral_ttl
from .channels.pending_input_workspace import (
    pack_markup,
    receipt_matches,
    unpack_markup,
    valid_markup,
)

logger = logging.getLogger("jarvis.channel_reply")

CHANNEL_REPLY_CONTRACT_KIND = "channel_reply"
CHANNEL_REPLY_TASK_KIND = "channel.reply"
_RISK_TIER = 2
_TEXT_CAP = 4_000
_PROMPT_TEXT_CAP = 80_000
_PROMPT_CONTENT_BYTES = 2 * 1024 * 1024
_PROMPT_CONTENT_TOTAL = 32 * 1024 * 1024


@dataclass
class _PromptDelivery:
    future: asyncio.Future
    current: Callable
    deadline: float | None
    payload: dict | None = None
    content: bytes | None = None

    def live(self):
        try:
            return (not self.future.done() and self.current() is True
                    and (self.deadline is None or time.monotonic() < self.deadline))
        except Exception:
            return False


def _contract_template() -> ContractTemplate:
    def supported_channel(view, now):
        return view.get("channel") in SUPPORTED_INBOX_CHANNELS

    def reply_target_present(view, now):
        reply = view.get("reply")
        if not isinstance(reply, dict) or not reply:
            return False
        channel = view.get("channel")
        if channel == "telegram":
            return "chat_id" in reply
        if channel == "web":
            return "client_id" in reply
        if channel == "email":
            return "to" in reply
        if channel == "slack":
            target = reply.get("slack_channel")
            thread = reply.get("thread_ts")
            return (
                isinstance(target, str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", target) is not None
                and (thread is None or (
                    isinstance(thread, str)
                    and re.fullmatch(r"[0-9]{1,20}\.[0-9]{1,10}", thread) is not None
                ))
            )
        if channel == "discord":
            target = reply.get("channel_id")
            return (
                isinstance(target, (str, int)) and not isinstance(target, bool)
                and re.fullmatch(r"[1-9][0-9]{0,19}", str(target)) is not None
            )
        if channel == "ntfy":
            return (isinstance(reply.get("ntfy_topic"), str)
                    and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", reply["ntfy_topic"]) is not None
                    and isinstance(reply.get("ntfy_context"), str)
                    and re.fullmatch(r"[a-f0-9]{64}", reply["ntfy_context"]) is not None)
        return False

    def native_prompt_valid(view, now):
        if "native_prompt" not in view:
            return True
        prompt = view["native_prompt"]
        if (type(prompt) is not dict
                or type(prompt.get("sender")) is not str or not prompt["sender"]):
            return False
        text_only = view.get("channel") == "ntfy" and prompt.get("mode") == "text"
        if not text_only and view.get("channel") not in {"slack", "discord"}:
            return False
        fields = {"expires_at", "sender"} | ({"mode"} if text_only else set())
        inline_fields = fields | (set() if text_only else {"buttons"})
        if set(prompt) == inline_fields:
            if not text_only and unpack_markup(prompt["buttons"]) is None:
                return False
        elif set(prompt) == fields | {"content_sha256", "content_size"}:
            if (type(prompt["content_sha256"]) is not str
                    or re.fullmatch(r"[a-f0-9]{64}", prompt["content_sha256"]) is None
                    or type(prompt["content_size"]) is not int
                    or not 0 < prompt["content_size"] <= _PROMPT_CONTENT_BYTES):
                return False
        else:
            return False
        expiry = prompt["expires_at"]
        return (expiry is None or (type(expiry) in {int, float}
                                  and math.isfinite(expiry) and expiry > now))

    return ContractTemplate(kind=CHANNEL_REPLY_CONTRACT_KIND, constraints=(
        one_of("kind", {CHANNEL_REPLY_TASK_KIND}),
        field_present("thread_id", "text"),
        predicate("supported_channel", supported_channel, reason="unsupported_channel"),
        predicate("reply_target_present", reply_target_present, reason="missing_reply_target"),
        predicate("native_prompt_valid", native_prompt_valid, reason="invalid_native_prompt"),
        predicate("ephemeral_ttl_valid", lambda view, _now: "ephemeral_ttl" not in view or
                  (type(view["ephemeral_ttl"]) is int and 0 <= view["ephemeral_ttl"] <= 86400),
                  reason="invalid_ephemeral_ttl"),
    ), description="Admissibility for governed replies to live channel inbox threads.")


CHANNEL_REPLY_CONTRACT = _contract_template()


class ChannelReplyBroker:
    """Reply draft -> approval queue -> live channel send."""

    def __init__(self, *, inbox: ChannelInboxStore | None = None,
                 enqueue: Callable | None = None, channel_manager=None,
                 agent: str = "veronica", audit=None, kernel=None, task_reader=None) -> None:
        self._inbox = inbox or ChannelInboxStore()
        self._enqueue = enqueue
        self._channel_manager = channel_manager
        self.agent = agent
        self._audit = audit
        self._kernel = kernel
        self._task_reader = task_reader
        self._pending_prompts: dict[int, _PromptDelivery] = {}

    async def deliver_prompt(self, message_id: str, text: str, *, channel: str,
                             sender: str, markup: dict | None, current: Callable,
                             timeout_seconds: float | None = 3600) -> dict | bool | None:
        """Wait for actual governed delivery, never for approval alone.

        The in-process binding deliberately does not survive restart. A stale
        durable task cannot send a question whose resolver no longer exists.
        """
        text_only = channel == "ntfy" and markup is None
        if (not (text_only or (channel in {"slack", "discord"} and valid_markup(markup)))
                or not callable(current) or len(self._pending_prompts) >= 4096
                or type(text) is not str or not text.strip() or len(text) > _PROMPT_TEXT_CAP):
            return None
        if timeout_seconds is not None and (type(timeout_seconds) not in {int, float}
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            return None
        message = self._inbox.get_message(message_id)
        if (not message or message.get("direction") != "in" or message.get("channel") != channel
                or message.get("sender") != sender):
            return None
        future = asyncio.get_running_loop().create_future()
        entry = _PromptDelivery(future, current, None if timeout_seconds is None
                                else time.monotonic() + timeout_seconds)
        task_id = None
        try:
            if not entry.live():
                return None
            result = self._request({
                "thread_id": message["thread_id"], "last_message_id": message["id"],
                "channel": channel, "reply": dict(message.get("reply") or {}), "from": sender,
            }, text, agent=None, source="pending-input", pending=entry, native_prompt={
                **({"mode": "text"} if text_only else {"buttons": pack_markup(markup)}), "sender": sender,
                "expires_at": None if timeout_seconds is None else time.time() + timeout_seconds,
            })
            task_id = result.get("task_id")
            if (result.get("ok") is not True or result.get("queued") is not True
                    or type(task_id) is not int or task_id <= 0):
                return None
            while not future.done():
                if not entry.live():
                    return None
                if callable(self._task_reader):
                    queued = self._task_reader(task_id)
                    if (queued is None or queued.payload != entry.payload
                            or queued.status in {"rejected", "cancelled", "failed", "done"}):
                        return None
                await asyncio.wait({future}, timeout=0.1)
            return future.result()
        finally:
            if type(task_id) is int:
                self._pending_prompts.pop(task_id, None)
            if not future.done():
                future.cancel()

    def close_pending_prompts(self):
        for entry in self._pending_prompts.values():
            if not entry.future.done():
                entry.future.set_result(None)
        self._pending_prompts.clear()

    def request(self, thread_id: str, text: str, *, agent: str | None = None,
                source: str = "") -> dict:
        thread = self._inbox.thread(thread_id)
        if thread is None:
            return {"ok": False, "reason": "unknown_thread"}
        return self._request(thread, text, agent=agent, source=source)

    def request_for_message(self, message_id: str, text: str, *, channel: str,
                            agent: str | None = None, source: str = "") -> dict:
        """Queue an automatic reply to the exact persisted inbound turn.

        A concurrent arrival must not move the reply to the thread's latest
        message. The gateway supplies this id after pairing and persistence.
        """
        message = self._inbox.get_message(message_id)
        if (message is None or message.get("direction") != "in"
                or message.get("channel") != channel):
            return {"ok": False, "reason": "unknown_inbound_message"}
        return self._request({
            "thread_id": message["thread_id"],
            "last_message_id": message["id"],
            "channel": channel,
            "reply": dict(message.get("reply") or {}),
            "from": message.get("sender", ""),
        }, text, agent=agent, source=source)

    def _request(self, thread: dict, text: str, *, agent: str | None, source: str,
                 pending: _PromptDelivery | None = None, native_prompt: dict | None = None) -> dict:
        from .action_origin import current_action_origin
        from .security.taint import mark_if_untrusted

        origin = current_action_origin()
        thread_id = thread["thread_id"]
        clean_text = str(text or "").strip()[:_PROMPT_TEXT_CAP if pending else _TEXT_CAP]
        if not clean_text:
            return {"ok": False, "reason": "missing_text"}
        payload = {
            "thread_id": thread["thread_id"],
            "message_id": thread.get("last_message_id", ""),
            "channel": thread["channel"],
            "text": clean_text,
            "reply": dict(thread.get("reply") or {}),
            "source": source,
        }
        if isinstance(text, EphemeralReply):
            from .settings_db import get_value

            default = get_value("display", "ephemeral_system_ttl", 0) if text.ttl_seconds is None else 0
            # Bound transport-owned timers; zero retains the notice.
            payload["ephemeral_ttl"] = min(ephemeral_ttl(text, default=default), 86400)
        if native_prompt is not None:
            payload["native_prompt"] = native_prompt
        payload = mark_if_untrusted(payload, origin)
        if pending is not None:
            from .autonomy.mediation import canonical_json

            try:
                canonical_json(payload)
            except ValueError:
                # Keep full content on the existing, non-restartable binding.
                # Only its exact digest and length enter the signed task.
                try:
                    content = json.dumps({"text": clean_text, "buttons": native_prompt.get("buttons")},
                                         ensure_ascii=False, allow_nan=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")
                    if (len(content) > _PROMPT_CONTENT_BYTES
                            or len(content) + sum(len(e.content or b"") for e in self._pending_prompts.values())
                            > _PROMPT_CONTENT_TOTAL):
                        return {"ok": False, "reason": "prompt_content_capacity"}
                    payload["text"] = clean_text[:1024] + "\n[Full question and choices available in preview]"
                    payload["native_prompt"] = {
                        "sender": native_prompt["sender"], "expires_at": native_prompt["expires_at"],
                        "content_sha256": hashlib.sha256(content).hexdigest(), "content_size": len(content),
                        **({"mode": "text"} if native_prompt.get("mode") == "text" else {}),
                    }
                    canonical_json(payload)
                except (ValueError, TypeError, KeyError, UnicodeError):
                    return {"ok": False, "reason": "invalid_prompt_content"}
                pending.content = content
            pending.payload = json.loads(json.dumps(payload))
        contract_payload = {
            **payload,
            "kind": CHANNEL_REPLY_TASK_KIND,
            "agent": agent or self.agent,
            "risk_tier": _RISK_TIER,
        }
        try:
            decision = CHANNEL_REPLY_CONTRACT.evaluate(contract_payload, now=time.time())
        except Exception:
            logger.warning("channel reply contract evaluation failed", exc_info=True)
            return {"ok": False, "reason": "contract_error", "kind": CHANNEL_REPLY_TASK_KIND}
        denial = contract_denial(decision)
        if denial:
            self._record("channel_reply.deny", denial, thread_id=thread_id)
            return {"ok": False, "reason": denial, "kind": CHANNEL_REPLY_TASK_KIND}

        title = f"Reply via {thread['channel']}: {thread.get('from') or thread['thread_id']}"
        preview = preview_task({
            "kind": CHANNEL_REPLY_TASK_KIND,
            "title": title,
            "payload": payload,
            "risk_tier": _RISK_TIER,
        })
        autonomy_level = "ask"
        if self._kernel is not None:
            from .kernel import Action, Verdict, kernel_enabled
            if kernel_enabled():
                verdict = self._kernel(Action(
                    kind=CHANNEL_REPLY_TASK_KIND,
                    agent=agent or self.agent,
                    title=title,
                    payload=payload,
                    origin=origin,
                ))
                if verdict.verdict is Verdict.DENY:
                    return {"ok": False, "reason": verdict.reason, "kind": CHANNEL_REPLY_TASK_KIND}
                if verdict.verdict is Verdict.GRANT:
                    autonomy_level = "act"
        if self._enqueue is None:
            return {"ok": True, "queued": False, "kind": CHANNEL_REPLY_TASK_KIND,
                    "title": title, "payload": payload, "preview": preview}
        try:
            task_id = self._enqueue(
                agent or self.agent,
                CHANNEL_REPLY_TASK_KIND,
                title,
                payload=payload,
                risk_tier=_RISK_TIER,
                autonomy_level=autonomy_level,
                origin=origin,
            )
        except Exception:
            logger.warning("channel reply enqueue failed", exc_info=True)
            return {"ok": False, "reason": "enqueue_failed", "kind": CHANNEL_REPLY_TASK_KIND}
        if pending is not None and type(task_id) is int and task_id > 0:
            self._pending_prompts[task_id] = pending
        self._record("channel_reply.request", thread["channel"], thread_id=thread_id)
        return {"ok": True, "queued": True, "task_id": task_id,
                "kind": CHANNEL_REPLY_TASK_KIND, "title": title, "preview": preview}

    async def execute(self, task) -> dict:
        if isinstance(task.payload, dict) and "native_prompt" in task.payload:
            return await self._execute_prompt(task)
        payload = getattr(task, "payload", None) or {}
        channel = (payload.get("channel") or "").strip().lower()
        text = str(payload.get("text") or "")[:_TEXT_CAP]
        reply = payload.get("reply") if isinstance(payload.get("reply"), dict) else {}
        thread_id = payload.get("thread_id") or ""
        message_id = payload.get("message_id") or ""
        decision = CHANNEL_REPLY_CONTRACT.evaluate({
            **payload,
            "kind": CHANNEL_REPLY_TASK_KIND,
            "channel": channel,
            "text": text,
            "reply": reply,
        }, now=time.time())
        denial = contract_denial(decision)
        if denial:
            return {"status": "blocked", "reason": denial, "channel": channel}
        if "ephemeral_ttl" in payload:
            text = EphemeralReply(text, payload["ephemeral_ttl"])
        if channel == "ntfy":
            message = self._inbox.get_message(message_id)
            if (not message or message.get("direction") != "in"
                    or message.get("channel") != channel or message.get("thread_id") != thread_id
                    or message.get("reply") != reply):
                return {"status": "blocked", "reason": "inbound_binding_changed", "channel": channel}
        if self._channel_manager is None:
            return {"status": "failed", "reason": "channel_manager_unavailable",
                    "channel": channel}
        send_reply = getattr(self._channel_manager, "send_channel_reply", None)
        if not callable(send_reply):
            return {"status": "failed", "reason": "reply_transport_unavailable",
                    "channel": channel}
        try:
            sent = await send_reply(channel, text, **reply)
        except Exception:
            logger.warning("channel reply send failed", exc_info=True)
            return {"status": "failed", "reason": "send_failed", "channel": channel}
        if not sent:
            return {"status": "failed", "reason": "send_failed", "channel": channel}
        self._inbox.record_outbound(
            channel,
            text,
            thread_id=thread_id,
            reply_to=message_id,
            metadata=reply,
        )
        self._record("channel_reply.execute", channel, thread_id=thread_id)
        return {"status": "ok", "channel": channel, "thread_id": thread_id}

    def _prompt_content(self, task):
        """Hydrate only the exact live task; no path, disk or cross-task lookup."""
        payload = task.payload
        entry = self._pending_prompts.get(task.id)
        if (entry is None or not entry.live() or entry.payload != payload
                or task.kind != CHANNEL_REPLY_TASK_KIND
                or task.status in {"rejected", "cancelled", "failed", "done"}):
            return None
        if callable(self._task_reader):
            queued = self._task_reader(task.id)
            if (queued is None or queued.payload != payload
                    or queued.status in {"rejected", "cancelled", "failed", "done"}):
                return None
        decision = CHANNEL_REPLY_CONTRACT.evaluate({**payload, "kind": CHANNEL_REPLY_TASK_KIND},
                                                   now=time.time())
        if contract_denial(decision):
            return None
        message = self._inbox.get_message(payload["message_id"])
        prompt = payload["native_prompt"]
        if (not message or message.get("direction") != "in"
                or message.get("channel") != payload["channel"]
                or message.get("thread_id") != payload["thread_id"]
                or message.get("reply") != payload["reply"]
                or message.get("sender") != prompt["sender"]):
            return None
        if "content_sha256" not in prompt:
            return {"text": payload["text"], "markup": None if prompt.get("mode") == "text"
                    else unpack_markup(prompt["buttons"])}
        content = entry.content
        if (type(content) is not bytes or len(content) != prompt["content_size"]
                or hashlib.sha256(content).hexdigest() != prompt["content_sha256"]):
            return None
        try:
            body = json.loads(content)
            if (type(body) is not dict or set(body) != {"text", "buttons"}
                    or type(body["text"]) is not str or not body["text"].strip()
                    or len(body["text"]) > _PROMPT_TEXT_CAP):
                return None
            if prompt.get("mode") == "text":
                return {"text": body["text"], "markup": None} if body["buttons"] is None else None
            markup = unpack_markup(body["buttons"])
            return {"text": body["text"], "markup": markup} if markup is not None else None
        except (ValueError, UnicodeError):
            return None

    def review_prompt(self, task):
        """Full content for the existing owner-only preview, without sending."""
        content = self._prompt_content(task)
        if content is None:
            return {"available": False}
        return {"available": True, "text": content["text"],
                "choices": [b["text"] for row in (content["markup"] or {}).get("inline_keyboard", []) for b in row]}

    async def _execute_prompt(self, task):
        payload = task.payload
        entry = self._pending_prompts.get(task.id)
        result = {"status": "blocked", "reason": "prompt_binding_lost",
                  "channel": payload.get("channel")}
        receipt = None
        accepted = False
        try:
            content = self._prompt_content(task)
            if content is None:
                return result
            text_only = payload["native_prompt"].get("mode") == "text"
            send = getattr(self._channel_manager, "send_channel_text_prompt" if text_only
                           else "send_channel_prompt", None)
            if not callable(send) or not entry.live():
                return result
            if text_only:
                receipt = await send(payload["channel"], content["text"],
                                     current=lambda: self._prompt_content(task) == content, **payload["reply"])
            else:
                receipt = await send(payload["channel"], content["text"], content["markup"], **payload["reply"])
            if (self._prompt_content(task) != content
                    or (receipt is not True if text_only else not receipt_matches(
                        receipt, payload["channel"], payload["reply"], payload["native_prompt"]["sender"]))):
                return result
            if callable(self._task_reader):
                queued = self._task_reader(task.id)
                if queued is None or queued.payload != entry.payload:
                    return result
            self._inbox.record_outbound(payload["channel"], content["text"],
                                        thread_id=payload["thread_id"],
                                        reply_to=payload["message_id"], metadata=payload["reply"])
            self._record("channel_reply.prompt.execute", payload["channel"],
                         thread_id=payload["thread_id"])
            entry.future.set_result(receipt)
            accepted = True
            return {"status": "ok", "channel": payload["channel"],
                    "thread_id": payload["thread_id"]}
        except Exception:
            logger.warning("Governed prompt delivery failed")
            return {**result, "status": "failed", "reason": "prompt_delivery_failed"}
        finally:
            if entry is not None and not entry.future.done():
                entry.future.set_result(None)
            if not accepted and receipt is not None:
                discard = getattr(self._channel_manager, "discard_pending_card", None)
                if callable(discard):
                    discard(payload["channel"], receipt)

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is None:
            return
        try:
            self._audit.record(action, "channel_reply", why, **meta)
        except Exception:
            logger.debug("channel reply audit failed", exc_info=True)
