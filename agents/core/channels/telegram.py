"""
telegram.py — Telegram channel adapter.

Long-polls Telegram for incoming messages and forwards
responses back as Telegram replies.
Uses the PermissionGate to enforce domain restrictions.
"""

import logging
import time
from typing import Callable, Optional

import httpx

from .base import ChannelAdapter
from .descriptor import DIALECT_TELEGRAM_HTML, ChannelDescriptor
from .group_policy import ANSWER, OBSERVE, GroupPolicy, gate_message
from .render import chunk, to_plain, to_telegram_html
from ..log_safe import log_safe

logger = logging.getLogger("jarvis.channels.telegram")

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
#: Seconds between two edits of a streaming draft — Telegram's per-message edit budget is
#: about one a second; going faster earns a 429 and a frozen message.
STREAM_EDIT_INTERVAL = 1.2
_STREAM_CURSOR = " ▍"


class TelegramDraft:
    """One reply written in place as the model produces it (Hermes absorption 4c).

    On a chat surface a long silence and a crash look the same. The first token sends the
    message; later tokens edit it, at most one edit per :data:`STREAM_EDIT_INTERVAL` and
    only when the visible text changed; ``finish()`` renders the final text exactly as
    ``send()`` would — the first chunk lands in the edited message, further chunks follow
    as new messages. Every step is best effort and never raises into the turn: a failed
    edit is a skipped frame, a failed final edit becomes a fresh send, markup Telegram
    rejects is retried as plain text. ``finish()`` is True only when the final text was
    delivered.
    """

    def __init__(self, channel: "TelegramChannel", chat_id, *, interval: float | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._channel = channel
        self._chat_id = chat_id
        self._interval = STREAM_EDIT_INTERVAL if interval is None else float(interval)
        self._clock = clock
        self._text = ""
        self._message_id: Optional[int] = None
        self._last_edit = 0.0
        self._last_shown = ""
        self._cap = channel.descriptor.max_message_length or TELEGRAM_MAX_MESSAGE_LENGTH
        self.finished = False

    @property
    def started(self) -> bool:
        return self._message_id is not None

    @property
    def text(self) -> str:
        return self._text

    async def push(self, token) -> None:
        """Append *token*; show progress when the edit budget allows. Never raises."""
        if self.finished:
            return
        self._text += str(token or "")
        if not self._text.strip():
            return
        try:
            now = self._clock()
            if self._message_id is None:
                self._message_id = await self._channel._send_message(
                    self._chat_id, self._preview(), plain=to_plain(self._preview_source()),
                )
                self._last_edit = now
                self._last_shown = self._preview()
                return
            if now - self._last_edit < self._interval:
                return
            shown = self._preview()
            if shown == self._last_shown:
                return
            if await self._channel._edit_message(
                self._chat_id, self._message_id, shown, plain=to_plain(self._preview_source()),
            ):
                self._last_shown = shown
            self._last_edit = now
        except Exception:
            logger.debug("Telegram draft frame skipped", exc_info=True)

    def _preview_source(self) -> str:
        budget = self._cap - len(_STREAM_CURSOR) - 1
        source = self._text
        if len(source) > budget:
            source = source[:budget] + "…"
        return source + _STREAM_CURSOR

    def _preview(self) -> str:
        return to_telegram_html(self._preview_source())

    async def finish(self, final_text: Optional[str] = None) -> bool:
        """Deliver the final text: edit the streamed message, then send any overflow."""
        if self.finished:
            return False
        self.finished = True
        text = self._text if final_text is None else str(final_text or "")
        if not text.strip():
            return False
        if self._message_id is None:
            return await self._channel.send(text, chat_id=self._chat_id)
        pieces = chunk(text, self._cap)
        try:
            ok = await self._channel._edit_message(
                self._chat_id, self._message_id, to_telegram_html(pieces[0]), plain=to_plain(pieces[0]),
            )
        except Exception:
            ok = False
        if not ok:
            ok = await self._channel._send_chunk(self._chat_id, pieces[0])
        for piece in pieces[1:]:
            if not await self._channel._send_chunk(self._chat_id, piece):
                return False
        return ok


def _message_id_of(resp) -> int:
    """The message id Telegram returned, or 0 when the body did not carry one."""
    try:
        payload = resp.json()
    except Exception:
        return 0
    result = payload.get("result") if isinstance(payload, dict) else None
    value = result.get("message_id") if isinstance(result, dict) else None
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


class TelegramChannel(ChannelAdapter):
    descriptor = ChannelDescriptor(
        dialect=DIALECT_TELEGRAM_HTML,
        max_message_length=TELEGRAM_MAX_MESSAGE_LENGTH,
        supports_edit=True,
        supports_media=True,
        supports_threads=True,
    )

    def __init__(self, token: str, handler: Optional[Callable] = None,
                 allowed_user_ids: Optional[list[int]] = None,
                 group_policy: Optional[GroupPolicy] = None):
        super().__init__("telegram", handler)
        self.token = token
        self.api_base = f"https://api.telegram.org/bot{token}"
        self.client = httpx.AsyncClient(timeout=15.0)
        self.allowed_users = allowed_user_ids or []
        # Hermes absorption 0.4: what to do with a message that arrives in a group.
        # Default is fail-closed — answer only when mentioned or replied to.
        self.group_policy = group_policy or GroupPolicy()
        # The bot's own identity, learned from getMe at start; mention and reply
        # detection need it, and without it a group message is never "addressed".
        self._bot_id: Optional[int] = None
        self._bot_username: Optional[str] = None
        self._offset = 0
        self._poll_task = None
        # Decision-inbox callback: on_callback(task_id, action, chat_id=..., user_id=...)
        self.on_callback: Optional[Callable] = None
        # Injectable so deeplink pairing is testable without touching the data
        # root; production leaves it None and the store is built on first use.
        self._pairing = None

    async def start(self):
        self._running = True
        me = await self._get_me()
        if me:
            self._bot_id = me.get("id")
            self._bot_username = me.get("username")
            logger.info(f"Telegram bot connected: {me.get('username', '?')}")
        else:
            logger.warning(
                "Telegram getMe failed — the bot cannot recognise its own mentions, so "
                "group messages will be dropped until it can"
            )
        self._poll_task = __import__("asyncio").create_task(self._poll_loop())
        logger.info("Telegram channel started")

    async def stop(self):
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
        await self.client.aclose()
        logger.info("Telegram channel stopped")

    async def send(self, message: str, chat_id: int = None, **kwargs) -> bool:
        """Deliver *message* as one or more Telegram messages the owner will actually see.

        The reply is chunked to Telegram's cap on the source and each chunk is rendered to
        the HTML subset Telegram accepts, with only balanced markers turned into markup. If
        Telegram still rejects a chunk's markup (HTTP 400), the same chunk is sent again as
        plain text — the words always arrive; the formatting is best effort. Returns True
        only when every chunk was delivered, in order.
        """
        cid = chat_id or kwargs.get("chat_id")
        if not cid:
            logger.warning("No chat_id provided for Telegram send")
            return False
        for piece in chunk(str(message or ""), self.descriptor.max_message_length):
            if not await self._send_chunk(cid, piece):
                return False
        return True

    async def _send_chunk(self, cid, piece: str) -> bool:
        try:
            return await self._send_message(cid, to_telegram_html(piece), plain=to_plain(piece)) is not None
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    async def _send_message(self, cid, html_text: str, *, plain: str) -> Optional[int]:
        """POST one message as HTML, as plain text if Telegram rejects the markup (400).
        Returns the new message id (or 0 when Telegram did not say), raises on failure."""
        resp = await self.client.post(
            f"{self.api_base}/sendMessage",
            json={"chat_id": cid, "text": html_text, "parse_mode": "HTML"},
        )
        if resp.status_code == 400:
            logger.info("Telegram rejected the markup; resending the chunk as plain text")
            resp = await self.client.post(
                f"{self.api_base}/sendMessage", json={"chat_id": cid, "text": plain},
            )
        resp.raise_for_status()
        return _message_id_of(resp)

    async def _edit_message(self, cid, message_id, html_text: str, *, plain: str) -> bool:
        """Edit a message in place, HTML first and plain on a 400. False on any failure."""
        try:
            body = {"chat_id": cid, "message_id": message_id, "text": html_text, "parse_mode": "HTML"}
            resp = await self.client.post(f"{self.api_base}/editMessageText", json=body)
            if resp.status_code == 400:
                resp = await self.client.post(
                    f"{self.api_base}/editMessageText",
                    json={"chat_id": cid, "message_id": message_id, "text": plain},
                )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.debug(f"Telegram edit failed: {e}")
            return False

    def begin_stream(self, chat_id=None, **kwargs) -> Optional[TelegramDraft]:
        """A draft for a reply that will be written in place; None without a chat."""
        cid = chat_id or kwargs.get("chat_id")
        if not cid:
            return None
        return TelegramDraft(self, cid)

    async def send_card(self, chat_id: int, card: dict) -> bool:
        """Send a decision-inbox card (text + inline keyboard) built by inbox.py."""
        try:
            body = {"chat_id": chat_id, **card}
            resp = await self.client.post(f"{self.api_base}/sendMessage", json=body)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram send_card error: {e}")
            return False

    async def _answer_callback(self, callback_id: str, text: str = ""):
        try:
            await self.client.post(
                f"{self.api_base}/answerCallbackQuery",
                json={"callback_query_id": callback_id, "text": text},
            )
        except Exception as e:
            logger.debug("Telegram answerCallbackQuery failed (cosmetic): %s", e)

    async def send_action(self, chat_id: int, action: str = "typing"):
        try:
            await self.client.post(
                f"{self.api_base}/sendChatAction",
                json={"chat_id": chat_id, "action": action},
            )
        except Exception as e:
            logger.debug("Telegram sendChatAction failed (cosmetic): %s", e)

    async def _poll_loop(self):
        while self._running:
            try:
                updates = await self._get_updates()
                for up in updates:
                    self._offset = up["update_id"] + 1
                    # Decision-inbox button taps arrive as callback_query updates.
                    cb = up.get("callback_query")
                    if cb:
                        await self._handle_callback(cb)
                        continue
                    msg = up.get("message") or up.get("edited_message")
                    if not msg:
                        continue
                    uid = msg["from"]["id"]
                    if self.allowed_users and uid not in self.allowed_users:
                        logger.info("Ignored message from user %s", log_safe(uid))
                        continue
                    text = msg.get("text", "")
                    chat_id = msg["chat"]["id"]
                    if not text:
                        continue
                    # A `/start <token>` deeplink pairs this sender and stops here:
                    # the payload is a credential, so it must never be forwarded to
                    # the orchestrator, echoed, or logged as message text.
                    if await self._maybe_pair_deeplink(text, uid, chat_id):
                        continue
                    chat = msg.get("chat") or {}
                    decision = gate_message(
                        self.group_policy,
                        chat_type=chat.get("type", "private"),
                        chat_id=chat_id,
                        thread_id=msg.get("message_thread_id"),
                        text=text,
                        entities=msg.get("entities") or (),
                        reply_to_from_id=(
                            ((msg.get("reply_to_message") or {}).get("from") or {}).get("id")
                        ),
                        bot_id=self._bot_id,
                        bot_username=self._bot_username,
                    )
                    if decision.action == OBSERVE:
                        await self.receive(
                            decision.text, chat_id=chat_id, sender=str(uid), observe_only=True
                        )
                        continue
                    if decision.action != ANSWER:
                        logger.debug("Ignored group message (%s)", decision.reason)
                        continue
                    # Pass the sender id so the gateway's H12.19 pairing gate can
                    # hold unknown senders for approval (no-op unless enabled).
                    await self.receive(decision.text, chat_id=chat_id, sender=str(uid))
            except Exception as e:
                logger.warning(f"Telegram poll error: {e}")
                await __import__("asyncio").sleep(3)

    async def _maybe_pair_deeplink(self, text: str, uid, chat_id) -> bool:
        """Redeem a ``/start <token>`` deeplink. True when this message was one.

        Returning True swallows the message deliberately: the payload is a live
        credential until it is spent, so it must not reach the orchestrator, the
        transcript, or a log line. A plain ``/start`` with no payload is not a
        pairing attempt and falls through to normal handling.

        The reply is the same length either way — "paired" or "that link is not
        valid" — and never says *why* a token failed. Wrong, spent and expired are
        indistinguishable from outside on purpose.
        """
        stripped = str(text or "").strip()
        if not stripped.startswith("/start"):
            return False
        parts = stripped.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return False  # bare /start — an ordinary message
        token = parts[1].strip()
        try:
            from ..channels.pairing import SenderPairing

            pairing = self._pairing or SenderPairing()
            result = pairing.redeem_deeplink(token, "telegram", str(uid))
        except Exception:
            # Never leak the token or the failure detail through an exception path.
            logger.warning("Telegram deeplink pairing failed")
            result = {"ok": False}
        if result.get("ok"):
            logger.info("Telegram sender paired by deeplink: %s", log_safe(uid))
            await self.send("Paired. This device can now talk to Nerva.", chat_id=chat_id)
        else:
            await self.send("That pairing link is not valid.", chat_id=chat_id)
        return True

    async def _handle_callback(self, cb: dict):
        """Parse an inline-button tap and dispatch to on_callback."""
        from ..autonomy.inbox import parse_callback_data
        uid = (cb.get("from") or {}).get("id")
        if self.allowed_users and uid not in self.allowed_users:
            return
        parsed = parse_callback_data(cb.get("data", ""))
        if not parsed or not self.on_callback:
            await self._answer_callback(cb.get("id", ""))
            return
        task_id, action = parsed
        chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
        try:
            await self.on_callback(task_id, action, chat_id=chat_id, user_id=uid)
            await self._answer_callback(cb.get("id", ""), f"OK: {action}")
        except Exception as e:
            logger.warning(f"Telegram callback dispatch error: {e}")
            await self._answer_callback(cb.get("id", ""))

    async def _get_me(self) -> Optional[dict]:
        try:
            resp = await self.client.get(f"{self.api_base}/getMe")
            resp.raise_for_status()
            return resp.json().get("result")
        except Exception:
            return None

    async def _get_updates(self) -> list:
        # The read timeout must exceed the 25s long-poll, or httpx aborts every
        # idle cycle at the client's 15s default and churns the connection. Let
        # failures propagate — _poll_loop logs and backs off 3s; swallowing them
        # here turned an outage into an unthrottled tight reconnect loop.
        resp = await self.client.get(
            f"{self.api_base}/getUpdates",
            params={"offset": self._offset, "timeout": 25},
            timeout=httpx.Timeout(15.0, read=30.0),
        )
        resp.raise_for_status()
        return resp.json().get("result", [])
