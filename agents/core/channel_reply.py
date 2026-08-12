"""Governed replies for live channel inbox threads."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    one_of,
    predicate,
)
from .autonomy.dry_run import preview_task
from .channel_inbox import SUPPORTED_INBOX_CHANNELS, ChannelInboxStore

logger = logging.getLogger("jarvis.channel_reply")

CHANNEL_REPLY_CONTRACT_KIND = "channel_reply"
CHANNEL_REPLY_TASK_KIND = "channel.reply"
_RISK_TIER = 2
_TEXT_CAP = 4_000


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
        return False

    return ContractTemplate(kind=CHANNEL_REPLY_CONTRACT_KIND, constraints=(
        one_of("kind", {CHANNEL_REPLY_TASK_KIND}),
        field_present("thread_id", "text"),
        predicate("supported_channel", supported_channel, reason="unsupported_channel"),
        predicate("reply_target_present", reply_target_present, reason="missing_reply_target"),
    ), description="Admissibility for governed replies to live channel inbox threads.")


CHANNEL_REPLY_CONTRACT = _contract_template()


class ChannelReplyBroker:
    """Reply draft -> approval queue -> live channel send."""

    def __init__(self, *, inbox: ChannelInboxStore | None = None,
                 enqueue: Callable | None = None, channel_manager=None,
                 agent: str = "veronica", audit=None, kernel=None) -> None:
        self._inbox = inbox or ChannelInboxStore()
        self._enqueue = enqueue
        self._channel_manager = channel_manager
        self.agent = agent
        self._audit = audit
        self._kernel = kernel

    def request(self, thread_id: str, text: str, *, agent: str | None = None,
                source: str = "") -> dict:
        thread = self._inbox.thread(thread_id)
        if thread is None:
            return {"ok": False, "reason": "unknown_thread"}
        clean_text = str(text or "").strip()[:_TEXT_CAP]
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
            from .action_origin import current_action_origin
            from .kernel import Action, Verdict, kernel_enabled
            if kernel_enabled():
                verdict = self._kernel(Action(
                    kind=CHANNEL_REPLY_TASK_KIND,
                    agent=agent or self.agent,
                    title=title,
                    payload=payload,
                    origin=current_action_origin(),
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
                origin="generated",
            )
        except Exception:
            logger.warning("channel reply enqueue failed", exc_info=True)
            return {"ok": False, "reason": "enqueue_failed", "kind": CHANNEL_REPLY_TASK_KIND}
        self._record("channel_reply.request", thread["channel"], thread_id=thread_id)
        return {"ok": True, "queued": True, "task_id": task_id,
                "kind": CHANNEL_REPLY_TASK_KIND, "title": title, "preview": preview}

    async def execute(self, task) -> dict:
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

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is None:
            return
        try:
            self._audit.record(action, "channel_reply", why, **meta)
        except Exception:
            logger.debug("channel reply audit failed", exc_info=True)
