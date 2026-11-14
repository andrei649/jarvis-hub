"""Slack-native AI-app surfaces for Socket Mode & Web API (H126).

Provides pure builders and bounded per-thread state for Slack's AI-app surfaces:
* ``chat.startStream`` / ``chat.appendStream`` / ``chat.stopStream`` native streaming where the
  streamed message *is* the final message (with seamless ``chat.postMessage`` + ``chat.update``
  fallback when the workspace lacks native stream methods).
* Native plan/task Block Kit cards with per-tool ``running`` / ``complete`` / ``error`` rows
  keyed by ``(team_id, channel, thread_ts)``.
* ``assistant.threads.setSuggestedPrompts`` capped at 4 sanitized prompts.
* Automatic thread titles derived once from the first user message via
  ``assistant.threads.setTitle``.
* ``assistant_thread_context_changed`` / ``app_context_changed`` stored strictly as a bounded
  channel label — never fetching ``conversations.history`` or ``conversations.replies``.
* ``render_rich_blocks`` converting headings, fenced code blocks, dividers, and paragraphs into
  Slack Block Kit blocks (<= 50 blocks, <= 3000 chars per section).
* ``👍`` / ``👎`` feedback buttons and validated ``block_actions`` parsing.
"""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from .outbound_safety import sanitize_label

MAX_SUGGESTED_PROMPTS = 4
MAX_THREAD_TITLE_CHARS = 80
MAX_PLAN_THREADS = 256
MAX_CONTEXT_THREADS = 256
MAX_FEEDBACK_RECORDS = 256
MAX_BLOCKS = 50
MAX_SECTION_CHARS = 3000

PLAN_STATES = frozenset({"running", "complete", "error"})
_STATE_ICONS = {"running": ":hourglass_flowing_sand:", "complete": ":white_check_mark:", "error": ":x:"}
_SLACK_MENTION_RE = re.compile(r"<@[UW][A-Z0-9]{1,63}(?:\|[^>]+)?>")
_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
_FEEDBACK_VALUE_RE = re.compile(r"^h126:([A-Za-z0-9_-]{4,64}):(up|down)$")
_CHANNEL_ID_RE = re.compile(r"^[CDG][A-Z0-9]{1,63}$")
_TEAM_ID_RE = re.compile(r"^T[A-Z0-9]{1,63}$")
_USER_ID_RE = re.compile(r"^[UW][A-Z0-9]{1,63}$")
_TS_RE = re.compile(r"^[0-9]{1,20}\.[0-9]{1,6}$")


def _bound_lru(store: OrderedDict, limit: int) -> None:
    while len(store) > limit:
        store.popitem(last=False)


async def _call_slack_api(client: Any, sdk_method: str, api_method: str, **params: Any) -> dict:
    """Invoke a Slack WebClient method on a worker thread, falling back to ``api_call``."""
    fn = getattr(client, sdk_method, None)
    if callable(fn):
        res = await asyncio.to_thread(fn, **params)
    else:
        api_call = getattr(client, "api_call", None)
        if not callable(api_call):
            return {"ok": False, "error": "client_unavailable"}
        res = await asyncio.to_thread(api_call, api_method, json=params)
    if isinstance(res, dict):
        return res
    data = getattr(res, "data", None)
    return data if isinstance(data, dict) else {"ok": bool(getattr(res, "get", lambda _k: False)("ok"))}


def derive_thread_title(first_message: str) -> str:
    """Derive a clean, single-line thread title from the first user message."""
    cleaned = _CODE_FENCE_RE.sub(" ", str(first_message or ""))
    cleaned = _SLACK_MENTION_RE.sub(" ", cleaned)
    first_line = next((ln.strip() for ln in cleaned.splitlines() if ln.strip()), "")
    first_line = re.sub(r"^#+\s*", "", first_line)
    first_line = " ".join(first_line.split())
    safe = sanitize_label(first_line) if first_line else ""
    if not safe:
        return "New conversation"
    if len(safe) > MAX_THREAD_TITLE_CHARS:
        return safe[: MAX_THREAD_TITLE_CHARS - 1].rstrip() + "…"
    return safe


def normalize_suggested_prompts(
    prompts: list[Any] | tuple[Any, ...],
) -> list[dict[str, str]]:
    """Normalize and cap suggested prompts to at most 4 ``{title, message}`` dicts."""
    out: list[dict[str, str]] = []
    for item in prompts or ():
        if len(out) >= MAX_SUGGESTED_PROMPTS:
            break
        if isinstance(item, str):
            title = message = item.strip()
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("message") or "").strip()
            message = str(item.get("message") or item.get("title") or "").strip()
        else:
            continue
        if not title or not message:
            continue
        out.append({
            "title": sanitize_label(title)[:75],
            "message": message[:1000],
        })
    return out


def build_feedback_actions_block(feedback_id: str) -> dict[str, Any] | None:
    """Build a ``👍`` / ``👎`` Block Kit actions row with validated H126 action IDs."""
    fid = str(feedback_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", fid):
        return None
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "👍 Helpful", "emoji": True},
                "action_id": "h126_feedback_up",
                "value": f"h126:{fid}:up",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "👎 Needs work", "emoji": True},
                "action_id": "h126_feedback_down",
                "value": f"h126:{fid}:down",
            },
        ],
    }


def render_rich_blocks(
    text: str,
    *,
    include_feedback: bool = False,
    feedback_id: str = "",
) -> list[dict[str, Any]]:
    """Render ordinary reply markdown/mrkdwn into bounded Slack Block Kit blocks."""
    raw = str(text or "").strip()
    if not raw:
        return []
    blocks: list[dict[str, Any]] = []
    limit = MAX_BLOCKS - (1 if include_feedback else 0)
    for segment in _split_rich_segments(raw):
        if len(blocks) >= limit:
            break
        blocks.extend(_segment_to_blocks(segment, remaining=limit - len(blocks)))
    if include_feedback:
        fb = build_feedback_actions_block(feedback_id)
        if fb is not None and len(blocks) < MAX_BLOCKS:
            blocks.append(fb)
    return blocks[:MAX_BLOCKS]


def _split_rich_segments(raw: str) -> list[tuple[str, str]]:
    """Split *raw* into ``(kind, content)`` tuples: ``code``, ``header``, ``divider``, ``text``."""
    segments: list[tuple[str, str]] = []
    pos = 0
    for match in _CODE_FENCE_RE.finditer(raw):
        if match.start() > pos:
            segments.extend(_split_prose_lines(raw[pos : match.start()]))
        segments.append(("code", match.group(0)))
        pos = match.end()
    if pos < len(raw):
        segments.extend(_split_prose_lines(raw[pos:]))
    return segments


def _split_prose_lines(chunk: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            joined = "\n".join(buf).strip()
            if joined:
                out.append(("text", joined))
            buf.clear()

    for line in chunk.splitlines():
        stripped = line.strip()
        if stripped in {"---", "***", "___"}:
            flush()
            out.append(("divider", ""))
        elif stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                flush()
                out.append(("header", heading))
            else:
                buf.append(line)
        else:
            buf.append(line)
    flush()
    return out


def _segment_to_blocks(segment: tuple[str, str], *, remaining: int) -> list[dict[str, Any]]:
    if remaining <= 0:
        return []
    kind, body = segment
    if kind == "divider":
        return [{"type": "divider"}]
    if kind == "header":
        safe = sanitize_label(body)[:150] or "Section"
        return [{"type": "header", "text": {"type": "plain_text", "text": safe}}]
    out: list[dict[str, Any]] = []
    for offset in range(0, len(body), MAX_SECTION_CHARS):
        if len(out) >= remaining:
            break
        piece = body[offset : offset + MAX_SECTION_CHARS]
        out.append({"type": "section", "text": {"type": "mrkdwn", "text": piece}})
    return out


@dataclass
class PlanStep:
    step_id: str
    tool: str
    label: str
    state: str = "running"
    detail: str = ""


@dataclass
class PlanCard:
    title: str
    channel: str
    thread_ts: str | None
    message_ts: str | None = None
    steps: OrderedDict[str, PlanStep] = field(default_factory=OrderedDict)

    def to_blocks(self) -> list[dict[str, Any]]:
        header_text = sanitize_label(self.title)[:150] or "Execution Plan"
        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        ]
        lines = []
        for step in list(self.steps.values())[:30]:
            icon = _STATE_ICONS.get(step.state, ":hourglass_flowing_sand:")
            suffix = f" — _{sanitize_label(step.detail)[:120]}_" if step.detail else ""
            lines.append(f"{icon} *{sanitize_label(step.tool)[:60]}*: {sanitize_label(step.label)[:140]}{suffix}")
        body = "\n".join(lines) if lines else "_Preparing steps…_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body[:MAX_SECTION_CHARS]}})
        counts = {s: sum(1 for st in self.steps.values() if st.state == s) for s in ("running", "complete", "error")}
        summary = (f"Running: {counts['running']} · Complete: {counts['complete']} · "
                   f"Errors: {counts['error']}")
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": summary}]})
        return blocks


@dataclass
class ActiveStream:
    channel: str
    thread_ts: str | None
    stream_ts: str
    native_stream: bool
    buffer: str = ""


def parse_context_changed_event(payload: Any, *, expected_team: str) -> tuple[tuple[str, str, str], dict] | None:
    """Extract ONLY a bounded channel label from ``assistant_thread_context_changed`` /
    ``app_context_changed`` — never reading message history from the viewed channel."""
    if not isinstance(payload, dict) or payload.get("type") != "event_callback":
        return None
    team = payload.get("team_id")
    event = payload.get("event")
    if not isinstance(team, str) or team != expected_team or not _TEAM_ID_RE.fullmatch(team):
        return None
    if not isinstance(event, dict) or event.get("type") not in {
        "assistant_thread_context_changed", "app_context_changed",
    }:
        return None
    assistant_thread = event.get("assistant_thread") if isinstance(event.get("assistant_thread"), dict) else event
    channel = str(assistant_thread.get("channel_id") or event.get("channel_id") or "")
    thread_ts = str(assistant_thread.get("thread_ts") or event.get("thread_ts") or "")
    ctx = assistant_thread.get("context") if isinstance(assistant_thread.get("context"), dict) else (
        event.get("context") if isinstance(event.get("context"), dict) else {}
    )
    viewed_id = str(ctx.get("channel_id") or event.get("viewed_channel_id") or "").strip()
    viewed_name = sanitize_label(str(ctx.get("channel_name") or "").strip())[:80]
    if not _CHANNEL_ID_RE.fullmatch(channel) or (thread_ts and not _TS_RE.fullmatch(thread_ts)):
        return None
    if viewed_id and not _CHANNEL_ID_RE.fullmatch(viewed_id):
        return None
    label = f"#{viewed_name} ({viewed_id})" if (viewed_name and viewed_id) else (viewed_id or viewed_name or "none")
    return (team, channel, thread_ts), {
        "viewed_channel_id": viewed_id,
        "label": f"viewed_channel:{label}"[:140],
    }


def parse_feedback_action(
    payload: Any,
    *,
    expected_team: str,
    bot_user_id: str,
) -> dict[str, Any] | None:
    """Validate a Block Kit ``👍`` / ``👎`` feedback button click."""
    if not isinstance(payload, dict) or payload.get("type") != "block_actions":
        return None
    team = (payload.get("team") or {}).get("id") if isinstance(payload.get("team"), dict) else None
    user = (payload.get("user") or {}).get("id") if isinstance(payload.get("user"), dict) else None
    container = payload.get("container")
    message = payload.get("message")
    actions = payload.get("actions")
    if (team != expected_team or not isinstance(team, str) or not _TEAM_ID_RE.fullmatch(team)
            or not isinstance(user, str) or not _USER_ID_RE.fullmatch(user) or user == bot_user_id
            or not isinstance(container, dict) or not isinstance(message, dict)
            or not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], dict)):
        return None
    channel, msg_ts = container.get("channel_id"), container.get("message_ts")
    if (not isinstance(channel, str) or not _CHANNEL_ID_RE.fullmatch(channel)
            or not isinstance(msg_ts, str) or not _TS_RE.fullmatch(msg_ts)):
        return None
    if message.get("user") is not None and bot_user_id and message.get("user") != bot_user_id:
        return None
    action = actions[0]
    aid = action.get("action_id")
    val = str(action.get("value") or "")
    match = _FEEDBACK_VALUE_RE.fullmatch(val)
    if aid not in {"h126_feedback_up", "h126_feedback_down"} or match is None:
        return None
    sentiment = match.group(2)
    if (aid == "h126_feedback_up" and sentiment != "up") or (aid == "h126_feedback_down" and sentiment != "down"):
        return None
    return {
        "feedback_id": match.group(1),
        "sentiment": sentiment,
        "sender": f"{team}:{user}",
        "channel": channel,
        "message_ts": msg_ts,
        "thread_ts": message.get("thread_ts") if isinstance(message.get("thread_ts"), str) else None,
    }


class SlackAISurfaces:
    """Per-adapter bounded coordinator for Slack AI-app streaming, plans, titles, prompts & feedback."""

    def __init__(self) -> None:
        self.streams: OrderedDict[tuple[str, str, str], ActiveStream] = OrderedDict()
        self.plans: OrderedDict[tuple[str, str, str], PlanCard] = OrderedDict()
        self.titled_threads: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        self.context_labels: OrderedDict[tuple[str, str, str], dict] = OrderedDict()
        self.feedback: list[dict[str, Any]] = []

    def clear(self) -> None:
        self.streams.clear()
        self.plans.clear()
        self.titled_threads.clear()
        self.context_labels.clear()

    def record_context_change(self, key: tuple[str, str, str], info: dict) -> None:
        self.context_labels[key] = dict(info)
        _bound_lru(self.context_labels, MAX_CONTEXT_THREADS)

    def get_context_label(self, team: str, channel: str, thread_ts: str | None) -> str | None:
        entry = self.context_labels.get((team, channel, str(thread_ts or "")))
        return entry.get("label") if isinstance(entry, dict) else None

    def record_feedback(self, item: dict[str, Any]) -> None:
        self.feedback.append(dict(item))
        if len(self.feedback) > MAX_FEEDBACK_RECORDS:
            del self.feedback[: len(self.feedback) - MAX_FEEDBACK_RECORDS]

    async def start_stream(
        self,
        client: Any,
        *,
        team: str,
        channel: str,
        thread_ts: str | None = None,
        initial_text: str = "…",
    ) -> str | None:
        """Open a native ``chat.startStream`` (falling back to ``chat.postMessage``)."""
        if client is None or not _CHANNEL_ID_RE.fullmatch(str(channel or "")):
            return None
        key = (team, channel, str(thread_ts or ""))
        params: dict[str, Any] = {"channel": channel, "markdown_text": initial_text or "…"}
        if thread_ts:
            params["thread_ts"] = thread_ts
        resp = await _call_slack_api(client, "chat_startStream", "chat.startStream", **params)
        if resp.get("ok") is True and isinstance(resp.get("ts"), str):
            self.streams[key] = ActiveStream(
                channel=channel, thread_ts=thread_ts, stream_ts=resp["ts"],
                native_stream=True, buffer=initial_text if initial_text != "…" else "",
            )
            _bound_lru(self.streams, MAX_PLAN_THREADS)
            return resp["ts"]
        post_params: dict[str, Any] = {"channel": channel, "text": initial_text or "…"}
        if thread_ts:
            post_params["thread_ts"] = thread_ts
        fallback = await _call_slack_api(client, "chat_postMessage", "chat.postMessage", **post_params)
        if fallback.get("ok") is True and isinstance(fallback.get("ts"), str):
            self.streams[key] = ActiveStream(
                channel=channel, thread_ts=thread_ts, stream_ts=fallback["ts"],
                native_stream=False, buffer=initial_text if initial_text != "…" else "",
            )
            _bound_lru(self.streams, MAX_PLAN_THREADS)
            return fallback["ts"]
        return None

    async def append_stream(
        self,
        client: Any,
        *,
        team: str,
        channel: str,
        thread_ts: str | None = None,
        delta: str,
    ) -> bool:
        key = (team, channel, str(thread_ts or ""))
        stream = self.streams.get(key)
        if client is None or stream is None or not delta:
            return False
        stream.buffer += delta
        if stream.native_stream:
            resp = await _call_slack_api(
                client, "chat_appendStream", "chat.appendStream",
                channel=channel, ts=stream.stream_ts, markdown_text=delta,
            )
            if resp.get("ok") is True:
                return True
            stream.native_stream = False
        resp = await _call_slack_api(
            client, "chat_update", "chat.update",
            channel=channel, ts=stream.stream_ts, text=stream.buffer,
        )
        return resp.get("ok") is True

    async def finalize_stream(
        self,
        client: Any,
        *,
        team: str,
        channel: str,
        thread_ts: str | None = None,
        final_text: str | None = None,
        rich_blocks: bool = True,
        feedback_id: str = "",
    ) -> str | None:
        """Finalize the in-place streamed message so the streamed message IS the final message."""
        key = (team, channel, str(thread_ts or ""))
        stream = self.streams.pop(key, None)
        if client is None or stream is None:
            return None
        body = final_text if final_text is not None else stream.buffer
        blocks = (render_rich_blocks(body, include_feedback=bool(feedback_id), feedback_id=feedback_id)
                  if rich_blocks else None)
        if stream.native_stream:
            stop_params: dict[str, Any] = {"channel": channel, "ts": stream.stream_ts}
            if final_text is not None:
                stop_params["markdown_text"] = body
            if blocks:
                stop_params["blocks"] = blocks
            resp = await _call_slack_api(client, "chat_stopStream", "chat.stopStream", **stop_params)
            if resp.get("ok") is True:
                return stream.stream_ts
        upd: dict[str, Any] = {"channel": channel, "ts": stream.stream_ts, "text": body or " "}
        if blocks:
            upd["blocks"] = blocks
        resp = await _call_slack_api(client, "chat_update", "chat.update", **upd)
        return stream.stream_ts if resp.get("ok") is True else None

    async def upsert_plan_step(
        self,
        client: Any,
        *,
        team: str,
        channel: str,
        thread_ts: str | None,
        step_id: str,
        tool: str,
        label: str,
        state: str = "running",
        detail: str = "",
        title: str = "Execution Plan",
    ) -> str | None:
        """Create or update a native plan/task card row (``running`` / ``complete`` / ``error``)."""
        if client is None or state not in PLAN_STATES or not _CHANNEL_ID_RE.fullmatch(str(channel or "")):
            return None
        key = (team, channel, str(thread_ts or ""))
        card = self.plans.get(key)
        if card is None:
            card = PlanCard(title=title, channel=channel, thread_ts=thread_ts)
            self.plans[key] = card
            _bound_lru(self.plans, MAX_PLAN_THREADS)
        card.steps[step_id] = PlanStep(
            step_id=step_id, tool=tool, label=label, state=state, detail=detail,
        )
        blocks = card.to_blocks()
        fallback_text = f"{card.title}: {tool} ({state})"
        if card.message_ts:
            resp = await _call_slack_api(
                client, "chat_update", "chat.update",
                channel=channel, ts=card.message_ts, text=fallback_text, blocks=blocks,
            )
            return card.message_ts if resp.get("ok") is True else None
        params: dict[str, Any] = {"channel": channel, "text": fallback_text, "blocks": blocks}
        if thread_ts:
            params["thread_ts"] = thread_ts
        resp = await _call_slack_api(client, "chat_postMessage", "chat.postMessage", **params)
        if resp.get("ok") is True and isinstance(resp.get("ts"), str):
            card.message_ts = resp["ts"]
            return card.message_ts
        return None

    async def set_suggested_prompts(
        self,
        client: Any,
        *,
        channel: str,
        thread_ts: str,
        prompts: list[Any] | tuple[Any, ...],
        title: str = "Suggested next steps",
    ) -> bool:
        cleaned = normalize_suggested_prompts(prompts)
        if client is None or not cleaned or not _CHANNEL_ID_RE.fullmatch(str(channel or "")) \
                or not _TS_RE.fullmatch(str(thread_ts or "")):
            return False
        resp = await _call_slack_api(
            client,
            "assistant_threads_setSuggestedPrompts",
            "assistant.threads.setSuggestedPrompts",
            channel_id=channel,
            thread_ts=thread_ts,
            title=sanitize_label(title)[:75] or "Suggested next steps",
            prompts=cleaned,
        )
        return resp.get("ok") is True

    async def ensure_thread_title(
        self,
        client: Any,
        *,
        team: str,
        channel: str,
        thread_ts: str,
        first_message: str,
    ) -> str | None:
        """Set the Slack assistant thread title once from the first user message."""
        if client is None or not _CHANNEL_ID_RE.fullmatch(str(channel or "")) \
                or not _TS_RE.fullmatch(str(thread_ts or "")):
            return None
        key = (team, channel, thread_ts)
        if key in self.titled_threads:
            return self.titled_threads[key]
        title = derive_thread_title(first_message)
        resp = await _call_slack_api(
            client,
            "assistant_threads_setTitle",
            "assistant.threads.setTitle",
            channel_id=channel,
            thread_ts=thread_ts,
            title=title,
        )
        if resp.get("ok") is True:
            self.titled_threads[key] = title
            _bound_lru(self.titled_threads, MAX_PLAN_THREADS)
            return title
        return None
