"""
discord.py — Discord channel adapter for Jarvis.

Port of OpenJarvis's Discord channel to pure Python.
Uses discord.py for message handling.
"""

import asyncio
import contextlib
import logging
from collections import OrderedDict
from typing import Optional

from .base import ChannelAdapter
from .descriptor import DIALECT_MARKDOWN, ChannelDescriptor
from .ephemeral import EphemeralDeletes, EphemeralReply, ephemeral_ttl
from .render import render_outbound

logger = logging.getLogger("jarvis.channels.discord")

#: Discord's cap on one message; it renders Markdown itself, so text is only chunked.
DISCORD_MAX_MESSAGE_LENGTH = 2_000

try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:
    discord = None
    DISCORD_AVAILABLE = False


def _positive_id(value) -> bool:
    """Discord snowflakes from the SDK, without bool or string coercion."""
    return type(value) is int and value > 0


def _requested_id(value) -> int | None:
    if _positive_id(value):
        return value
    if type(value) is str and 1 <= len(value) <= 20 and value.isascii() and value.isdecimal():
        number = int(value)
        if number > 0 and str(number) == value:
            return number
    return None


class DiscordChannel(ChannelAdapter):
    descriptor = ChannelDescriptor(
        dialect=DIALECT_MARKDOWN,
        max_message_length=DISCORD_MAX_MESSAGE_LENGTH,
        supports_edit=True,
        supports_media=True,
        supports_threads=True,
    )

    def __init__(self, token: str | None = None, handler=None,
                 pending_reply_handler=None, pending_callback_handler=None, pairing=None):
        super().__init__("discord", handler)
        self.token = token or ""
        self._client: Optional[discord.Client] = None
        self.pending_reply_handler = pending_reply_handler
        self.pending_callback_handler = pending_callback_handler
        self._pairing = pairing
        self._pending_callback_generation = object()
        self._pending_callback_fast: dict[int, asyncio.Task] = {}
        self._pending_views: OrderedDict[tuple[str, str], object] = OrderedDict()
        self._pending_task_sequence = 0
        self._pending_sending = 0
        self._ephemeral_deletes = EphemeralDeletes()
        # H117: a burst from one author in one channel is handed over as one turn.
        from .batching import AsyncBatcher, configured
        self._batch = AsyncBatcher(self._deliver_turn, *configured())

    async def start(self):
        if not DISCORD_AVAILABLE:
            logger.warning("discord.py not installed — Discord channel unavailable")
            return
        if not self.token:
            logger.warning("No Discord token configured")
            return
        if self._ephemeral_deletes._closed:
            self._ephemeral_deletes = EphemeralDeletes()

        intents = discord.Intents.default()
        intents.message_content = True

        self._pending_callback_generation = None
        for view in self._pending_views.values():
            view.stop()
        self._pending_views.clear()
        prior = tuple(self._pending_callback_fast.values())
        for task in prior:
            task.cancel()
        if prior:
            await asyncio.gather(*prior, return_exceptions=True)
        self._pending_callback_fast.clear()
        self._pending_callback_generation = object()
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            logger.info(f"Discord bot connected as {self._client.user}")

        @self._client.event
        async def on_message(message):
            await self._handle_message(message)

        self._running = True
        # discord.py 2.x: Client.loop is the MISSING sentinel until start() runs,
        # so `self._client.loop.create_task` raises AttributeError. Schedule on the
        # running loop instead, and keep the task so stop() can cancel it.
        self._start_task = asyncio.create_task(self._client.start(self.token))

    async def _handle_message(self, message) -> None:
        """Route one inbound Discord message through the handler.

        Lives outside the ``on_message`` closure so the inbound path can be driven
        without a live client. The sender is threaded as ``message.author.id`` — the
        stable Discord identity, unlike the display name — so the gateway's pairing
        gate can hold a stranger; before this the handler saw no sender at all and
        pairing could never apply to Discord. Nothing else about the author is
        observed or logged. (Hermes absorption 5b)
        """
        author = getattr(message, "author", None)
        if author is None or (self._client is not None and author == self._client.user):
            return
        if not self.handler:
            return
        author_id = getattr(author, "id", None)
        target_id = getattr(getattr(message, "channel", None), "id", None)
        if not _positive_id(author_id) or not _positive_id(target_id):
            return
        sender, channel_id = str(author_id), str(target_id)
        chat_type = ("thread" if getattr(message.channel, "parent_id", None) is not None
                     else "group" if getattr(message, "guild", None) is not None else "private")
        # A pending text answer is independent of the held model turn. Only an
        # original human message is eligible; the resolver checks the live prompt.
        if (callable(self.pending_reply_handler) and type(message.content) is str
                and message.content and getattr(author, "bot", False) is False
                and getattr(message, "webhook_id", None) is None
                and getattr(message, "edited_at", None) is None
                and not (callable(getattr(message, "is_system", None))
                         and message.is_system())
                and self._paired(sender)):
            try:
                consumed = await self.pending_reply_handler(
                    message.content, channel="discord", sender=sender,
                    channel_id=channel_id, chat_type=chat_type,
                )
            except Exception:
                logger.warning("Discord pending reply not applied")
                consumed = False
            if consumed is True:
                return
        # H117: held for the batch window, so a split message is one turn.
        await self._batch.submit((channel_id, sender), message.content,
                                 sender=sender, channel_id=channel_id, chat_type=chat_type)

    async def _deliver_turn(self, key, text: str, meta: dict) -> None:
        if not self.handler:
            return
        # The orchestrator queues a governed channel.reply. Echoing its return
        # value here would bypass approval (and duplicate an approved delivery).
        await self.handler(text, channel="discord", sender=meta["sender"], channel_id=meta["channel_id"],
                           chat_type=meta.get("chat_type", "private"))

    async def stop(self):
        self._running = False
        self._pending_callback_generation = None
        await self._ephemeral_deletes.aclose()
        self._batch.discard()              # H117: a stopping channel starts no new turn
        for view in self._pending_views.values():
            view.stop()
        self._pending_views.clear()
        tasks = tuple(self._pending_callback_fast.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._pending_callback_fast.clear()
        if self._client:
            await self._client.close()
        task = getattr(self, "_start_task", None)
        if task is not None:
            task.cancel()

    def _pending_view(self, markup: dict, generation):
        """Translate the bounded card markup into real Discord components."""
        rows = markup.get("inline_keyboard") if type(markup) is dict else None
        if (type(rows) is not list or not rows or len(rows) > 11
                or not DISCORD_AVAILABLE):
            return None
        buttons = []
        for row in rows:
            if type(row) is not list or not row:
                return None
            for item in row:
                if type(item) is not dict:
                    return None
                label, data = item.get("text"), item.get("callback_data")
                if (type(label) is not str or not label or type(data) is not str
                        or not data.startswith("h067:") or len(data) > 100):
                    return None
                buttons.append((label, data))
        if len(buttons) > 25:
            return None
        # The runtime retires this exact card when its prompt completes. A fixed
        # UI timeout could make a still-live long clarification unanswerable.
        view = discord.ui.View(timeout=None)
        view._h067_generation = generation
        view._h067_receipt = None
        view._h067_message = None
        view._h067_retired = False
        for index, (label, data) in enumerate(buttons):
            # Discord allows five buttons per row and five rows per message.
            label = label.encode("utf-16-le")[:158].decode("utf-16-le", errors="ignore")
            action = data.rsplit(":", 1)[-1]
            style = (discord.ButtonStyle.danger if action == "x" else
                     discord.ButtonStyle.success if action == "s" else
                     discord.ButtonStyle.secondary if action == "o" else
                     discord.ButtonStyle.primary)
            button = discord.ui.Button(label=label, style=style, custom_id=data,
                                       row=index // 5)

            async def pressed(interaction, *, owner=view, custom_id=data):
                await self._on_pending_button(interaction, owner, custom_id)

            button.callback = pressed
            view.add_item(button)
        return view

    def _paired(self, sender: str) -> bool:
        if self._pairing is None:
            return False
        try:
            return self._pairing.is_allowed("discord", sender) is True
        except Exception:
            return False

    async def send_pending_card(self, message: str, *, reply_markup: dict, **kwargs):
        """Post a native card and bind only its final, verified bot message."""
        generation = self._pending_callback_generation
        client = self._client
        channel_id = _requested_id(kwargs.get("channel_id"))
        if (not self._running or generation is None or client is None
                or not client.is_ready() or channel_id is None or type(message) is not str
                or not message.strip() or type(reply_markup) is not dict):
            return None
        channel = client.get_channel(channel_id)
        if channel is None or not _positive_id(getattr(channel, "id", None)):
            return None
        pieces = render_outbound(message, self.descriptor)
        if not pieces:
            return None
        view = self._pending_view(reply_markup, generation)
        if view is None:
            return None
        # Reserve before the first await: concurrent sends cannot evict a live
        # acknowledged card or exceed the bound while their receipts are in flight.
        if len(self._pending_views) + self._pending_sending >= 128:
            view.stop()
            return None
        self._pending_sending += 1
        try:
            return await self._post_pending_parts(channel, pieces, view, generation, client, channel_id)
        finally:
            self._pending_sending -= 1

    async def _post_pending_parts(self, channel, pieces, view, generation, client, channel_id):
        for index, piece in enumerate(pieces):
            if (not self._running or generation is not self._pending_callback_generation
                    or client is not self._client or not client.is_ready()):
                view.stop()
                return None
            try:
                sent = await channel.send(piece, **({"view": view} if index == len(pieces) - 1 else {}))
            except Exception:
                logger.warning("Discord pending card delivery failed")
                view.stop()
                return None
            if (not self._running or generation is not self._pending_callback_generation
                    or client is not self._client or not client.is_ready()
                    or not _positive_id(getattr(sent, "id", None))
                    or getattr(sent, "channel", None) is None
                    or getattr(sent.channel, "id", None) != channel_id
                    or getattr(sent, "author", None) is None
                    or getattr(sent.author, "id", None) != getattr(client.user, "id", None)
                    or not _positive_id(getattr(client.user, "id", None))):
                view.stop()
                return None
        receipt = {"channel": "discord", "target": str(channel_id),
                   "message_id": str(sent.id), "thread_id": None, "team_id": None}
        key = (receipt["target"], receipt["message_id"])
        view._h067_receipt = key
        view._h067_message = sent
        old = self._pending_views.pop(key, None)
        if old is not None:
            old.stop()
        self._pending_views[key] = view
        return receipt

    def discard_pending_card(self, receipt) -> None:
        """Retire local callbacks for an exact card, without a network edit."""
        if type(receipt) is not dict or receipt.get("channel") != "discord":
            return
        target, message_id = receipt.get("target"), receipt.get("message_id")
        if (_requested_id(target) is None or _requested_id(message_id) is None
                or type(target) is not str or type(message_id) is not str):
            return
        old = self._pending_views.pop((target, message_id), None)
        if old is not None:
            old.stop()

    async def _pending_notice(self, interaction, applied: bool) -> None:
        try:
            await interaction.followup.send("Applied." if applied else "Not applied.", ephemeral=True)
        except Exception:
            logger.debug("Discord pending callback notice failed")

    async def _on_pending_button(self, interaction, view, custom_id: str) -> None:
        """Acknowledge immediately, then run a bounded pending-only task."""
        generation = self._pending_callback_generation
        receipt = getattr(view, "_h067_receipt", None)
        client = self._client
        sent = getattr(interaction, "message", None)
        data = getattr(interaction, "data", None)
        sender = getattr(interaction, "user", None)
        if (not self._running or generation is None or view._h067_generation is not generation
                or client is None or getattr(interaction, "client", None) is not client
                or not client.is_ready() or receipt is None
                or self._pending_views.get(receipt) is not view
                or view._h067_retired
                or not _positive_id(getattr(interaction, "channel_id", None))
                or str(interaction.channel_id) != receipt[0]
                or not _positive_id(getattr(sent, "id", None))
                or str(sent.id) != receipt[1]
                or not _positive_id(getattr(getattr(sent, "channel", None), "id", None))
                or sent.channel.id != interaction.channel_id
                or not _positive_id(getattr(getattr(sent, "author", None), "id", None))
                or not _positive_id(getattr(client.user, "id", None))
                or sent.author.id != client.user.id
                or not _positive_id(getattr(sender, "id", None))
                or getattr(sender, "bot", False) is not False
                or not self._paired(str(sender.id))
                or type(data) is not dict or data.get("custom_id") != custom_id
                or custom_id not in {button.custom_id for button in view.children}
                or not callable(self.pending_callback_handler)
                or len(self._pending_callback_fast) >= 32):
            with contextlib.suppress(Exception):
                await interaction.response.send_message("Not applied.", ephemeral=True)
            return
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            return
        if (not self._running or generation is not self._pending_callback_generation
                or client is not self._client or self._pending_views.get(receipt) is not view
                or not self._paired(str(sender.id))):
            await self._pending_notice(interaction, False)
            return
        callback = {"channel": "discord", "target": receipt[0], "message_id": receipt[1],
                    "thread_id": None, "team_id": None, "sender": str(sender.id), "data": custom_id}
        self._pending_task_sequence += 1
        sequence = self._pending_task_sequence
        task = asyncio.create_task(self._run_pending_callback(
            interaction, view, callback, generation, client), name="discord-pending-callback")
        self._pending_callback_fast[sequence] = task
        task.add_done_callback(lambda done, key=sequence: self._pending_callback_fast.get(key) is done
                               and self._pending_callback_fast.pop(key, None))

    async def _run_pending_callback(self, interaction, view, callback, generation, client) -> None:
        receipt = view._h067_receipt
        if (not self._running or generation is not self._pending_callback_generation
                or client is not self._client or self._pending_views.get(receipt) is not view
                or view._h067_retired
                or not self._paired(callback["sender"])):
            return
        try:
            result = await self.pending_callback_handler(callback, channel="discord")
        except Exception:
            logger.warning("Discord pending callback not applied")
            await self._pending_notice(interaction, False)
            return
        applied = getattr(result, "applied", False) is True
        if (not self._running or generation is not self._pending_callback_generation
                or client is not self._client or self._pending_views.get(receipt) is not view
                or view._h067_retired
                or not self._paired(callback["sender"])):
            return
        if applied:
            markup = getattr(result, "markup", None)
            replacement = self._pending_view(markup, generation) if markup else None
            view._h067_retired = True
            view.stop()
            if replacement is not None:
                replacement._h067_receipt = receipt
                replacement._h067_message = view._h067_message
            try:
                await view._h067_message.edit(view=replacement)
            except Exception:
                logger.warning("Discord pending card buttons could not be updated")
                if replacement is not None:
                    replacement.stop()
                if self._pending_views.get(receipt) is view:
                    self._pending_views.pop(receipt, None)
            else:
                if (replacement is not None and self._running
                        and generation is self._pending_callback_generation
                        and client is self._client
                        and self._pending_views.get(receipt) is view):
                    self._pending_views[receipt] = replacement
                else:
                    if replacement is not None:
                        replacement.stop()
                    if self._pending_views.get(receipt) is view:
                        self._pending_views.pop(receipt, None)
        await self._pending_notice(interaction, applied)

    async def send(self, message: str, **kwargs) -> bool:
        if not self._client or not self._client.is_ready():
            return False
        channel_id = kwargs.get("channel_id")
        try:
            client, generation = self._client, self._pending_callback_generation
            ttl = 0
            if isinstance(message, EphemeralReply):
                from ..settings_db import get_value

                default = get_value("display", "ephemeral_system_ttl", 0) if message.ttl_seconds is None else 0
                ttl = min(ephemeral_ttl(message, default=default), 86400)
            if channel_id:
                channel = client.get_channel(int(channel_id))
                if channel:
                    for piece in render_outbound(str(message or ""), self.descriptor):
                        sent = await channel.send(piece)
                        if (ttl and _positive_id(getattr(sent, "id", None))
                                and str(getattr(getattr(sent, "channel", None), "id", "")) == str(channel_id)
                                and callable(getattr(sent, "delete", None)) and generation is not None):
                            async def delete(owned=sent):
                                if (not self._running or self._client is not client
                                        or self._pending_callback_generation is not generation):
                                    return False
                                await owned.delete()
                                return True

                            self._ephemeral_deletes.schedule(ttl, delete)
                    return True
        except Exception:
            logger.warning("Discord reply transport failed", exc_info=True)
        return False
