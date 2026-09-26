"""
telegram.py — Telegram channel adapter.

Long-polls Telegram for incoming messages and forwards
responses back as Telegram replies.
Uses the PermissionGate to enforce domain restrictions.
"""

import asyncio
import logging
import re
import time
from typing import Callable, Optional

import httpx

from .base import ChannelAdapter
from .descriptor import DIALECT_TELEGRAM_HTML, ChannelDescriptor
from .group_policy import ANSWER, OBSERVE, GroupPolicy, gate_message
from .inbound_media import (
    KIND_PHOTO,
    KIND_VOICE,
    READABLE_KINDS,
    RECOGNISED_KINDS,
    classify,
    describe,
    turn_text,
)
from . import voice_mode
from .inbound_voice import InboundVoiceReader, Transcript, echo_line
from .inbound_voice import REASON_DOWNLOAD as VOICE_REASON_DOWNLOAD
from .inbound_voice import note as voice_note
from .inbound_voice import turn_text as voice_turn_text
from .media_reader import (
    REASON_DOWNLOAD,
    Description,
    InboundImageReader,
)
from .media_reader import note as read_note
from .media_reader import turn_text as image_turn_text
from .render import chunk, to_plain, to_telegram_html
from .spoken_reply import REASON_SEND, Audio, SpokenReply
from ..log_safe import log_safe
from ..settings_db import get_value

logger = logging.getLogger("jarvis.channels.telegram")

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
#: Seconds between two edits of a streaming draft — Telegram's per-message edit budget is
#: about one a second; going faster earns a 429 and a frozen message.
STREAM_EDIT_INTERVAL = 1.2
#: H677: at stop, how long the turns already in their chats' lanes get to finish.
LANE_DRAIN_BUDGET = 2.0
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
        if ok:
            # Same rule as `send()`: the text landed, so the chat's voice mode applies.
            await self._channel._after_reply(self._chat_id, text)
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
        recognises_media=RECOGNISED_KINDS,
        reads_media=tuple(sorted(READABLE_KINDS)),
    )

    def __init__(self, token: str, handler: Optional[Callable] = None,
                 allowed_user_ids: Optional[list[int]] = None,
                 group_policy: Optional[GroupPolicy] = None,
                 pairing=None):
        super().__init__("telegram", handler)
        # H117: a burst from one sender (a split message, an album, a photo then its
        # question) is held for the batch window and handed over as one turn.
        from .batching import Coalescer, configured
        self._batch = Coalescer(*configured())
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
        # H677: while the poll loop runs, each chat's turns go to that chat's lane, so
        # one slow answer never holds another chat's messages.
        self._lanes = None
        # Decision-inbox callback: on_callback(task_id, action, chat_id=..., user_id=...)
        self.on_callback: Optional[Callable] = None
        # The process's ONE `SenderPairing` — the object the gateway gates on and
        # the pairing router mints and revokes deeplinks from; `web.py` hands it
        # in. It is never built here: a second store over the same file is not a
        # second view of it, and whichever saves last writes the other's spent
        # links back to disk — a link redeemed here would pair a second phone
        # after the owner's store next saved. None means "not wired", and
        # `_maybe_pair_deeplink` then refuses to pair rather than opening its own.
        self._pairing = pairing
        # H108 second half: reads an inbound photo over a *proven-local* vision
        # model. Built on first use from the environment, so a deployment with
        # no local VLM costs nothing and simply refuses with a reason.
        self._image_reader: Optional[InboundImageReader] = None
        # The same shape for a voice note, transcribed on the host's own speech
        # engine. Built on first use; a host without one simply refuses.
        self._voice_reader: Optional[InboundVoiceReader] = None
        # H071, the spoken half: a delivered reply becomes a voice note too when
        # this chat asked for it with `/voice`. Built on first use; a host with
        # no speech engine refuses with a reason and the text still lands.
        self._speaker: Optional[SpokenReply] = None
        # Injectable per-chat mode store; production uses the process-wide one.
        self._voice_modes: Optional[voice_mode.VoiceModeStore] = None
        # Chats whose current turn arrived as a voice note. The reply answering
        # it consumes the mark, which is how "voice for voice" tells a spoken
        # question from a typed one.
        self._voice_turns: set = set()
        # H677: chats whose NEXT delivered turn was a voice note. The mark is taken
        # when the note is read, but with chat lanes an earlier turn of the chat may
        # still be running then; the turn carries the mark into its lane and sets it
        # only when it runs, so that earlier reply is not the one spoken.
        self._voice_pending: set = set()

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
        lanes, self._lanes = self._lanes, None
        if lanes is not None:
            await lanes.drain(LANE_DRAIN_BUDGET)
        await self.client.aclose()
        logger.info("Telegram channel stopped")

    async def send(self, message: str, chat_id: int = None, **kwargs) -> bool:
        """Deliver *message* as one or more Telegram messages the owner will actually see.

        The reply is chunked to Telegram's cap on the source and each chunk is rendered to
        the HTML subset Telegram accepts, with only balanced markers turned into markup. If
        Telegram still rejects a chunk's markup (HTTP 400), the same chunk is sent again as
        plain text — the words always arrive; the formatting is best effort. Returns True
        only when every chunk was delivered, in order.

        ``plain=True`` sends every chunk as it is, never rendered and with no link
        preview: a notice whose text came from outside (a webhook's sender) must not
        become markup, least of all a link that hides its address.
        """
        cid = chat_id or kwargs.get("chat_id")
        if not cid:
            logger.warning("No chat_id provided for Telegram send")
            return False
        plain = kwargs.get("plain") is True
        for piece in chunk(str(message or ""), self.descriptor.max_message_length):
            sent = await self._send_plain_chunk(cid, piece) if plain else await self._send_chunk(cid, piece)
            if not sent:
                return False
        # The words are delivered; a voice note follows only if this chat asked.
        # `voice=False` marks a service line (a transcript echo) that is never spoken.
        await self._after_reply(cid, str(message or ""), speak=kwargs.get("voice", True))
        return True

    async def send_scheduled_text(self, text: str, *, chat_id: int) -> bool:
        """One bounded plain-text request, without fallback, retries or exception logging."""
        if not isinstance(text, str) or not 0 < len(text) <= 2000 or type(chat_id) is not int or not chat_id:
            return False
        response = await self.client.post(self.api_base + '/sendMessage',
                                          json={'chat_id': chat_id, 'text': text})
        return self._scheduled_ack(response)

    @staticmethod
    def _scheduled_ack(response) -> bool:
        if not response.is_success:
            return False
        try:
            body = response.json()
        except ValueError:
            return False
        if not isinstance(body, dict):
            return False
        result = body.get('result')
        return (body.get('ok') is True and isinstance(result, dict)
                and type(result.get('message_id')) is int and result['message_id'] > 0)

    async def send_media(self, data: bytes, *, mime: str, filename: str, chat_id: int) -> bool:
        """Send captured bounded bytes to an already-bound owner. Never retries."""
        import re
        from ..artifact_store import MAX_UPLOAD, sniff

        if (not isinstance(data, bytes) or not 0 < len(data) <= MAX_UPLOAD
                or type(chat_id) is not int or not chat_id
                or not isinstance(filename, str)
                or not re.fullmatch(r'(?:ba-[a-f0-9]{32}|md-[a-f0-9]{12}|[a-f0-9]{32})', filename)):
            return False
        try:
            if sniff(data) != mime:
                return False
        except ValueError:
            return False
        response = await self.client.post(self.api_base + '/sendDocument',
            data={'chat_id': str(chat_id)}, files={'document': (filename, data, mime)})
        return self._scheduled_ack(response)

    async def _send_chunk(self, cid, piece: str) -> bool:
        try:
            return await self._send_message(cid, to_telegram_html(piece), plain=to_plain(piece)) is not None
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    async def _send_plain_chunk(self, cid, piece: str) -> bool:
        """One chunk as plain text: no parse mode, no link preview. False on any failure
        (logged by type only: an HTTP error names the URL, and the URL holds the token)."""
        try:
            resp = await self.client.post(f"{self.api_base}/sendMessage", json={
                "chat_id": cid, "text": piece, "link_preview_options": {"is_disabled": True}})
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error("Telegram send error: %s", type(e).__name__)
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
        from .chat_lanes import ChatLanes

        self._lanes = ChatLanes(name="telegram")
        while self._running:
            try:
                # H117: while pieces of a burst are held, poll without the long wait so
                # the batch flushes when its window closes, not 25 s later.
                wait = self._batch.wait()
                if wait is None:
                    updates = await self._get_updates()
                else:
                    if wait > 0:
                        await asyncio.sleep(wait)
                    updates = await self._get_updates(timeout=0)
                for up in updates:
                    self._offset = up["update_id"] + 1
                    await self._handle_update(up)
                for key in self._batch.due():
                    await self._flush_turn(key)
            except Exception as e:
                logger.warning(f"Telegram poll error: {e}")
                await asyncio.sleep(3)
        # Stopping never drops what a sender already said: held pieces go out now, and
        # the turns already in their chats' lanes get a bounded time to finish.
        await self._flush_all_turns()
        lanes, self._lanes = self._lanes, None
        if lanes is not None:
            await lanes.drain(LANE_DRAIN_BUDGET)

    async def _handle_update(self, up: dict) -> None:
        """One update: a button tap, an ignored message, or a turn piece to batch (H117)."""
        # Decision-inbox button taps arrive as callback_query updates.
        cb = up.get("callback_query")
        if cb:
            await self._flush_all_turns()      # what was said before the tap goes first
            chat = ((cb.get("message") or {}).get("chat") or {}).get("id")
            await self._in_chat(chat, lambda: self._handle_callback(cb))
            return
        msg = up.get("message") or up.get("edited_message")
        if not msg:
            return
        uid = msg["from"]["id"]
        if self.allowed_users and uid not in self.allowed_users:
            logger.info("Ignored message from user %s", log_safe(uid))
            return
        text = msg.get("text", "")
        chat_id = msg["chat"]["id"]
        # A photo, a voice note or a captioned image used to land
        # here and be dropped by `if not text`, with no reply and
        # nothing the sender could learn from. Recognise it first;
        # a text-only message is unaffected (classify returns None).
        attachment = classify(msg)
        if not text and attachment is None:
            return
        # A `/start <token>` deeplink pairs this sender and stops here:
        # the payload is a credential, so it must never be forwarded to
        # the orchestrator, echoed, or logged as message text.
        if await self._maybe_pair_deeplink(text, uid, chat_id):
            return
        chat = msg.get("chat") or {}
        # A caption is the sender's own words about what they sent,
        # so it is what the group gate must judge and what the turn
        # carries — with its own entity list, or an @mention in a
        # caption would not count as addressing the bot.
        spoken = turn_text(attachment, text) if attachment else text
        decision = gate_message(
            self.group_policy,
            chat_type=chat.get("type", "private"),
            chat_id=chat_id,
            thread_id=msg.get("message_thread_id"),
            text=spoken,
            entities=msg.get("entities") or msg.get("caption_entities") or (),
            reply_to_from_id=(
                ((msg.get("reply_to_message") or {}).get("from") or {}).get("id")
            ),
            bot_id=self._bot_id,
            bot_username=self._bot_username,
        )
        if decision.action == OBSERVE:
            if decision.text:
                await self._flush_all_turns()
                observed = decision.text
                await self._in_chat(chat_id, lambda: self.receive(
                    observed, chat_id=chat_id, sender=str(uid), observe_only=True,
                ))
            return
        if decision.action != ANSWER:
            logger.debug("Ignored group message (%s)", decision.reason)
            return
        turn = decision.text
        if attachment is not None:
            logger.info("Telegram inbound media: %s", attachment.to_dict())
            read, why = await self._read_attachment(
                attachment, decision.text, chat_id)
            if read:
                turn = read
            else:
                # Nothing was read. Say exactly that, rather than
                # answering about a file nobody opened — and rather
                # than arriving into silence, which is what this
                # whole path exists to stop.
                await self.send(describe(attachment, note=why), chat_id=chat_id)
        # Pass the sender id so the gateway's H12.19 pairing gate can
        # hold unknown senders for approval (no-op unless enabled). H117: the
        # piece is held so a burst from this sender becomes one turn.
        if turn:
            await self._queue_turn(chat_id, uid, turn)

    async def _queue_turn(self, chat_id, uid, turn: str) -> None:
        if not self._batch.enabled:
            await self._deliver_turn(chat_id, uid, turn)
            return
        key = (chat_id, str(uid))
        if self._batch.add(key, turn):
            await self._flush_turn(key)

    async def _flush_turn(self, key) -> None:
        held = self._batch.pop(key)
        if held is not None and held.text:
            await self._deliver_turn(key[0], key[1], held.text)

    async def _flush_all_turns(self) -> None:
        for key in self._batch.held_keys():
            await self._flush_turn(key)

    async def _deliver_turn(self, chat_id, uid, turn: str) -> None:
        spoken = chat_id in self._voice_pending
        self._voice_pending.discard(chat_id)
        await self._in_chat(chat_id, lambda: self._run_turn(chat_id, uid, turn, spoken=spoken))

    async def _in_chat(self, chat_id, work) -> None:
        """Run *work* after everything already queued for *chat_id* (H677): in that chat's
        lane while the poll loop runs — the loop goes straight back to reading — and
        inline otherwise. Work with no chat waits for every lane first."""
        lanes = self._lanes
        if lanes is None:
            await work()
        elif chat_id is None:
            await lanes.settle()
            await work()
        else:
            lanes.submit(chat_id, work)

    async def _run_turn(self, chat_id, uid, turn: str, *, spoken: bool = False) -> None:
        if spoken:
            self._voice_turns.add(chat_id)
        try:
            await self.receive(turn, chat_id=chat_id, sender=str(uid))
        finally:
            # A turn the router answered with nothing must not leave
            # its voice mark behind for the next, typed, question.
            self._voice_turns.discard(chat_id)


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
        pairing = self._pairing
        if pairing is None:
            # Not wired to the shared store. Opening one here is the bug this branch
            # exists to prevent — see ``__init__`` — so refuse instead, in the same
            # words as a bad token: the sender learns nothing, and the log says why.
            logger.warning("Telegram deeplink pairing refused: no shared pairing store is wired")
            await self.send("That pairing link is not valid.", chat_id=chat_id)
            return True
        try:
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

    # ---- inbound media ----------------------------------------------------

    #: One path segment as Telegram spells them (``photos``, ``file_0.jpg``).
    #: A ``file_path`` is a value from the network, so it is checked segment by
    #: segment before it is pasted into a URL that carries the bot token —
    #: otherwise a hostile one could redirect that request, and the token with
    #: it, at a host of the sender's choosing. The alphabet has no ``:``, ``/``
    #: or whitespace, so a scheme, an authority or a forged line cannot survive.
    _FILE_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

    def _safe_file_path(self, file_path: object) -> str:
        """Return ``file_path`` if Telegram-shaped, else "" — never a partial fix-up.

        Rejecting outright rather than sanitising is deliberate: a "cleaned" path
        is still a path someone else chose, and there is no legitimate case where
        Telegram hands back something this refuses.
        """
        path = file_path if isinstance(file_path, str) else ""
        if not path or len(path) > 512:
            return ""
        # An empty segment is a leading, trailing or doubled slash; "." and ".."
        # are traversal. Neither can appear in a real Telegram file_path.
        segments = path.split("/")
        if any(seg in ("", ".", "..") or not self._FILE_PATH_SEGMENT_RE.match(seg)
               for seg in segments):
            return ""
        return path

    async def _download_file(self, file_id: str, max_bytes: int) -> bytes:
        """Fetch one attachment's bytes, bounded by what actually arrives.

        The cap is enforced against the stream, not against ``file_size``: the
        declared size is a number in an update, and believing it would let a
        message that claims 1 KB spend the host's memory. The transfer is
        abandoned the moment it crosses the ceiling.
        """
        resp = await self.client.get(f"{self.api_base}/getFile",
                                     params={"file_id": file_id}, timeout=15.0)
        resp.raise_for_status()
        path = self._safe_file_path((resp.json().get("result") or {}).get("file_path"))
        if not path:
            logger.warning("Telegram getFile returned an unusable file_path")
            return b""
        url = f"https://api.telegram.org/file/bot{self.token}/{path}"
        buf = bytearray()
        async with self.client.stream("GET", url, timeout=httpx.Timeout(15.0, read=60.0)) as r:
            r.raise_for_status()
            async for piece in r.aiter_bytes():
                buf.extend(piece)
                if len(buf) > max_bytes:
                    # Stop reading; the context manager closes the response.
                    logger.info("Telegram download exceeded %d bytes; abandoned", max_bytes)
                    return b""
        return bytes(buf)

    async def _read_attachment(self, attachment, spoken: str, chat_id) -> tuple[str, str]:
        """Turn one readable attachment into a turn, or into the reason it is not.

        Returns ``(turn_text, note)``: exactly one is ever non-empty. The two
        readers stay separate on purpose — a photo description is a machine's
        observation of someone else's bytes and travels fenced, while a
        transcript is the sender's own words and travels as an ordinary turn
        (see :mod:`inbound_voice`). Collapsing them into one "read the file"
        helper would lose that distinction, which is the security design.
        """
        if not attachment.readable:
            return "", ""
        # Reading takes seconds; say so rather than leaving the chat silent.
        await self.send_action(chat_id, "typing")
        if attachment.kind == KIND_PHOTO:
            description = await self._read_image(attachment)
            logger.info("Telegram photo read: %s", description.to_dict())
            return ((image_turn_text(description, spoken), "") if description.ok
                    else ("", read_note(description)))
        if attachment.kind == KIND_VOICE:
            transcript = await self._read_voice(attachment)
            logger.info("Telegram voice read: %s", transcript.to_dict())
            if not transcript.ok:
                return "", voice_note(transcript)
            # The reply to this turn answers speech: `/voice voice` keys on the mark,
            # which the turn takes with it when it is delivered (H677).
            self._voice_pending.add(chat_id)
            if self._echo_transcripts():
                # Hermes `stt_echo_transcripts`: say what was heard before answering
                # it, so a misheard note is caught by the person who sent it. A
                # service line — it is never itself spoken, and it never spends the
                # mark above.
                await self.send(echo_line(transcript), chat_id=chat_id, voice=False)
            return voice_turn_text(transcript, spoken), ""
        # A kind in READABLE_KINDS with no branch here would silently answer
        # nothing; say so instead, and the descriptor invariant catches the
        # declaration half.
        logger.warning("Telegram: %s is readable but has no reader", attachment.kind)
        return "", ""

    async def _read_voice(self, attachment) -> Transcript:
        """Download and transcribe one voice note. Failures are Transcripts, not raises."""
        if self._voice_reader is None:
            self._voice_reader = InboundVoiceReader()
        reader = self._voice_reader
        refused = reader.refusal()
        if refused is not None:
            return refused
        try:
            data = await self._download_file(attachment.file_id, reader.max_bytes)
        except Exception as e:
            logger.warning("Telegram voice download failed: %s", e)
            return Transcript(False, reason=VOICE_REASON_DOWNLOAD)
        if not data:
            return Transcript(False, reason=VOICE_REASON_DOWNLOAD)
        return await reader(data)

    # ── the spoken half (H071) ──────────────────────────────────────────────

    @staticmethod
    def _echo_transcripts() -> bool:
        return bool(get_value("voice", "stt_echo_transcripts", False))

    def _voice_mode_store(self) -> voice_mode.VoiceModeStore:
        if self._voice_modes is None:
            self._voice_modes = voice_mode.default_store()
        return self._voice_modes

    async def _after_reply(self, chat_id, text: str, *, speak: bool = True) -> None:
        """After the words landed: a voice note too, when this chat asked for one.

        Reached only from a delivery that succeeded, so the mode can never hand a
        chat as audio what it was not going to receive as text — whether to reply
        at all was decided upstream and stays decided. A failure anywhere below
        costs the voice note and nothing else, and is logged as a reason, never
        as the reply.
        """
        if not speak:
            return
        inbound_voice = chat_id in self._voice_turns
        self._voice_turns.discard(chat_id)
        try:
            mode = self._voice_mode_store().get("telegram", chat_id)
        except Exception:
            logger.debug("Telegram voice mode lookup failed; staying text-only", exc_info=True)
            return
        if not voice_mode.wants_voice(mode, inbound_voice=inbound_voice):
            return
        audio = await self._speak(chat_id, text)
        if not audio.ok:
            logger.info("Telegram spoken reply skipped: %s", audio.to_dict())
            return
        if not await self._send_voice(chat_id, audio):
            logger.info("Telegram spoken reply not delivered: %s",
                        {**audio.to_dict(), "reason": REASON_SEND})

    async def _speak(self, chat_id, text: str) -> Audio:
        """Synthesize one reply. Refusals are Audio values, never raises."""
        if self._speaker is None:
            self._speaker = SpokenReply()
        speaker = self._speaker
        # The first probe imports the optional speech stack: off the loop, like the reader.
        refused = await __import__("asyncio").to_thread(speaker.refusal)
        if refused is not None:
            return refused
        # Synthesis takes a moment; the "recording a voice message" indicator says so.
        await self.send_action(chat_id, "record_voice")
        lang = str(get_value("voice", "stt_language", "ro") or "ro")
        return await speaker(text, lang=lang)

    async def _send_voice(self, chat_id, audio: Audio) -> bool:
        """POST the clip as a voice message; as an audio file if Telegram refuses the format.

        Telegram plays an ``.ogg``/OPUS, ``.mp3`` or ``.m4a`` body inline as a voice
        message; anything it refuses with a 400 is sent once more as a plain audio
        file rather than dropped. True only when Telegram acknowledged a message.
        """
        suffix = {"audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/wav": "wav",
                  "audio/mp4": "m4a"}.get(audio.mime, "bin")
        filename = f"reply.{suffix}"
        try:
            resp = await self.client.post(
                f"{self.api_base}/sendVoice",
                data={"chat_id": str(chat_id)},
                files={"voice": (filename, audio.data, audio.mime)},
            )
            if resp.status_code == 400:
                logger.info("Telegram refused the clip as a voice message; sending it as audio")
                resp = await self.client.post(
                    f"{self.api_base}/sendAudio",
                    data={"chat_id": str(chat_id)},
                    files={"audio": (filename, audio.data, audio.mime)},
                )
            return self._scheduled_ack(resp)
        except Exception as e:
            logger.warning("Telegram sendVoice failed: %s", e)
            return False

    async def _read_image(self, attachment) -> Description:
        """Download and describe one photo. Every failure is a Description, not a raise."""
        if self._image_reader is None:
            self._image_reader = InboundImageReader.from_env()
        reader = self._image_reader
        # Ask the gate before spending a download: a deployment with no local
        # vision model must not pull someone's photo onto the host for nothing.
        refused = reader.refusal()
        if refused is not None:
            return refused
        try:
            data = await self._download_file(attachment.file_id, reader.max_bytes)
        except Exception as e:
            logger.warning("Telegram media download failed: %s", e)
            return Description(False, reason=REASON_DOWNLOAD)
        if not data:
            return Description(False, reason=REASON_DOWNLOAD)
        return await reader(data, caption=attachment.caption)

    async def _get_me(self) -> Optional[dict]:
        try:
            resp = await self.client.get(f"{self.api_base}/getMe")
            resp.raise_for_status()
            return resp.json().get("result")
        except Exception:
            return None

    async def _get_updates(self, timeout: int = 25) -> list:
        # The read timeout must exceed the 25s long-poll, or httpx aborts every
        # idle cycle at the client's 15s default and churns the connection. Let
        # failures propagate — _poll_loop logs and backs off 3s; swallowing them
        # here turned an outage into an unthrottled tight reconnect loop.
        resp = await self.client.get(
            f"{self.api_base}/getUpdates",
            params={"offset": self._offset, "timeout": timeout},
            timeout=httpx.Timeout(15.0, read=30.0),
        )
        resp.raise_for_status()
        return resp.json().get("result", [])
