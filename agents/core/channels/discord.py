"""
discord.py — Discord channel adapter for Jarvis.

Port of OpenJarvis's Discord channel to pure Python.
Uses discord.py for message handling.
"""

import asyncio
import contextlib
import io
import logging
from collections import OrderedDict
from typing import Optional

from . import delivery_ledger
from .base import ChannelAdapter
from .connect_deadline import DEFAULT_CONNECT_TIMEOUT, channel_connect_timeout
from .credentials import credential_is_configured
from .descriptor import DIALECT_MARKDOWN, ChannelDescriptor
from .ephemeral import EphemeralDeletes, EphemeralReply, ephemeral_ttl
from .outbound_safety import sanitize_label
from .render import render_outbound

logger = logging.getLogger("jarvis.channels.discord")

#: Discord's cap on one message; it renders Markdown itself, so text is only chunked.
DISCORD_MAX_MESSAGE_LENGTH = 2_000
DISCORD_SLASH_SEEN_MAX = 2_048
_SLASH_RECEIPT = "Command received. If admitted, any reply will arrive in this channel."

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
                 pending_reply_handler=None, pending_callback_handler=None, pairing=None,
                 pre_turn_refused=None, command_registry=None, skill_loader=None,
                 skill_owner=None, skill_taken=None,
                 connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT):
        super().__init__("discord", handler)
        # H058: a probe (Gateway.pre_lane_refused) for a command its sender may not run here.
        self.pre_turn_refused = pre_turn_refused
        self.command_registry = command_registry
        self.skill_loader = skill_loader
        self.skill_owner = skill_owner
        self.skill_taken = skill_taken
        self._slash_tree = None
        self._slash_names: frozenset[str] = frozenset()
        self._slash_hidden_count = 0
        self._slash_generation = None
        self._ready_client = None
        self._ready_generation = None
        self._slash_synced = False
        self._slash_syncing = None
        self._slash_seen: OrderedDict[int, None] = OrderedDict()
        self.token = token or ""
        self._connect_timeout_seconds = channel_connect_timeout(connect_timeout_seconds)
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
        self._connection_claim = None
        self._opening_generation = None
        self._opening_decision_event = None
        # H117: a burst from one author in one channel is handed over as one turn.
        from .batching import AsyncBatcher, configured
        self._batch = AsyncBatcher(self._deliver_turn, *configured(), beside=self._refused_here)

    def _refused_here(self, _key, text: str, meta: dict) -> bool:
        """H058 — whether *text* is a command this author may not run in this channel."""
        probe = self.pre_turn_refused
        return callable(probe) and probe(
            channel="discord", sender=meta.get("sender"), chat_id=meta.get("channel_id"), text=text,
            chat_type=meta.get("chat_type", "private")) is True

    def _connection_lifecycle_lock(self) -> asyncio.Lock:
        # Minimal adapter fixtures may be built without __init__.
        lock = getattr(self, "_connection_start_stop_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._connection_start_stop_lock = lock
        return lock

    async def start(self):
        async with self._connection_lifecycle_lock():
            await self._start_locked()

    async def _start_locked(self):
        if self._running:
            return
        if not credential_is_configured(self.token):
            self.health.failed_fatally("invalid_credential")
            logger.warning("Discord credential is not configured")
            return
        self.health.starting()
        if not DISCORD_AVAILABLE:
            logger.warning("discord.py not installed — Discord channel unavailable")
            return
        if getattr(self, "_connection_claim", None) is not None:
            self.health.failed_fatally("connection_cleanup_required")
            logger.warning("Discord startup refused: prior connection cleanup incomplete")
            return
        from .polling_claims import ClaimUnavailable, acquire_discord_claim

        try:
            claim = acquire_discord_claim(self.token)
        except ClaimUnavailable as exc:
            reason = ("connection_claim_busy" if exc.reason == "busy"
                      else "connection_claim_unavailable")
            self.health.failed_fatally(reason)
            logger.warning("Discord startup refused: connection claim unavailable")
            return
        self._connection_claim = claim
        try:
            await self._start_claimed()
        except BaseException:
            # A failed or cancelled startup still needs a successful stop before release.
            self._running = False
            raise

    async def _start_claimed(self):
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
        self._slash_generation = object()
        self._ready_client = None
        self._ready_generation = None
        self._slash_synced = False
        self._slash_syncing = None
        self._slash_seen.clear()
        self._install_slash_tree()
        slash_generation = self._slash_generation
        slash_client = self._client
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._connect_timeout_seconds
        ready_event = asyncio.Event()
        decision_event = asyncio.Event()
        self._opening_generation = slash_generation
        self._opening_decision_event = decision_event

        @self._client.event
        async def on_ready():
            opening = self._opening_generation is slash_generation
            if opening and loop.time() >= deadline:
                self._opening_timeout(slash_generation)
                return
            if self._observe_ready(slash_client, slash_generation) is not True:
                return
            if opening:
                ready_event.set()
                # Do not admit late callback work if the event loop resumes after
                # the deadline. _await_initial_ready makes the final time check.
                await decision_event.wait()
                if (not self._running or self._client is not slash_client
                        or self._slash_generation is not slash_generation):
                    return
            logger.info(f"Discord bot connected as {slash_client.user}")
            await self._sync_slash_tree(slash_generation, slash_client)

        @self._client.event
        async def on_message(message):
            if (not self._running or self._client is not slash_client
                    or self._slash_generation is not slash_generation
                    or self._opening_generation is slash_generation):
                return
            await self._handle_message(message)

        self._running = True
        # discord.py 2.x: Client.loop is the MISSING sentinel until start() runs,
        # so `self._client.loop.create_task` raises AttributeError. Schedule on the
        # running loop instead, and keep the task so stop() can cancel it.
        self._start_task = asyncio.create_task(self._client.start(self.token))
        await self._await_initial_ready(slash_client, slash_generation, deadline,
                                        ready_event, decision_event)

    async def _await_initial_ready(self, client, generation, deadline, ready_event,
                                   decision_event) -> None:
        """Bound initial readiness without cancelling discord.py's reconnect loop."""
        loop = asyncio.get_running_loop()
        waiter = asyncio.create_task(ready_event.wait())
        start_task = self._start_task
        admitted = False
        try:
            remaining = max(0.0, deadline - loop.time())
            done, _pending = await asyncio.wait(
                {waiter, start_task}, timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            # A terminated SDK task wins even if its ready callback also ran in
            # this loop turn. The adapter cannot admit a dead connection.
            if start_task in done:
                exc = None if start_task.cancelled() else start_task.exception()
                name = type(exc).__name__ if exc is not None else ""
                reason = ("unauthorized" if name == "LoginFailure"
                          else "intents_refused" if name == "PrivilegedIntentsRequired"
                          else "gateway_closed")
                self._opening_failure(generation, reason)
                return
            # The callback is the readiness authority, and the monotonic check
            # here prevents a delayed event loop from admitting an expired signal.
            if (waiter in done and loop.time() < deadline
                    and self._running and client is self._client
                    and generation is self._slash_generation
                    and self._observe_ready(client, generation) is True):
                admitted = True
                self._opening_generation = None
                decision_event.set()
                return
            self._opening_timeout(generation)
        finally:
            if self._opening_generation is generation:
                # Cancellation/failure must revoke ingress before a held
                # on_ready callback is released below or during waiter cleanup.
                if not admitted:
                    self._running = False
                self._opening_generation = None
            decision_event.set()
            if not waiter.done():
                waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    def _opening_timeout(self, generation) -> None:
        if generation is not self._opening_generation:
            return
        self._opening_failure(generation, "connect_timeout")

    def _opening_failure(self, generation, reason: str) -> None:
        if generation is not self._opening_generation:
            return
        self._running = False
        self._opening_generation = None
        decision = self._opening_decision_event
        if decision is not None:
            decision.set()
        self.health.failed_fatally(reason)
        if reason == "connect_timeout":
            logger.warning("Discord gateway readiness timed out")
        else:
            logger.warning("Discord startup failed before readiness (%s)", reason)

    def _observe_ready(self, client, generation) -> bool | None:
        """True/False for a valid probe, None if the probe or generation is unknown."""
        if (not self._running or client is None or client is not self._client
                or generation is None or generation is not self._slash_generation):
            return None
        try:
            ready = bool(client.is_ready()) and not client.is_closed()
        except Exception:
            return None
        if ready:
            self._ready_client = client
            self._ready_generation = generation
        return ready

    def _install_slash_tree(self) -> None:
        """Register canonical built-ins locally; syncing is a separate startup act."""
        from ..commands import CommandRegistry
        from .discord_commands import project_commands

        self._slash_tree = None
        self._slash_names = frozenset()
        self._slash_hidden_count = 0
        if not DISCORD_AVAILABLE or not isinstance(self.command_registry, CommandRegistry):
            return
        client = self._client
        if client is None:
            return
        projection = project_commands(self.command_registry)
        tree = discord.app_commands.CommandTree(client)
        generation = self._slash_generation
        for entry in projection.entries:
            name = entry.name

            def callback_for(canonical):
                async def callback(interaction: discord.Interaction, text: str = ""):
                    await self._handle_slash_interaction(interaction, canonical, text,
                                                         generation=generation)
                return callback

            tree.add_command(discord.app_commands.Command(
                name=name, description=entry.description, callback=callback_for(name)))
        names = {entry.name for entry in projection.entries}
        skill_namespace = self._skill_namespace_available()
        if skill_namespace and len(names) < 100:
            async def skill_callback(interaction: discord.Interaction, name: str, text: str = ""):
                await self._handle_slash_interaction(interaction, "skill", text,
                                                     generation=generation, skill_name=name,
                                                     skill_picker=True)

            async def skill_autocomplete(interaction: discord.Interaction, current: str):
                return self._skill_autocomplete(interaction, current, generation=generation)

            command = discord.app_commands.Command(
                name="skill", description="Run an installed skill", callback=skill_callback)
            command.autocomplete("name")(skill_autocomplete)
            tree.add_command(command)
            names.add("skill")
        self._slash_tree = tree
        self._slash_names = frozenset(names)
        self._slash_hidden_count = projection.hidden_count + int(skill_namespace and len(names) == 100
                                                                 and "skill" not in names)
        logger.info("Discord native commands prepared: %d registered, %d hidden",
                    len(self._slash_names), self._slash_hidden_count)

    def _skill_namespace_available(self) -> bool:
        """A later plugin, quick command or bundle may claim the generic word."""
        if self.skill_loader is None or not callable(self.skill_owner) or not callable(self.skill_taken):
            return False
        try:
            from ..skills import bundles, slash_load
            return (not self.skill_taken("skill") and bundles.get("skill") is None
                    and slash_load.resolve("/skill", self.skill_loader,
                                           taken=self.skill_taken) is None)
        except Exception:
            return False

    def _skill_projection(self):
        from .skill_menu import project_skill_menu
        pool = getattr(self.skill_loader, "skills", None) or {}
        return project_skill_menu(self.skill_loader, platform="discord", slots=len(pool),
                                  taken=self.skill_taken, reserved=self._slash_names)

    def _skill_selected(self, name: str) -> bool:
        if type(name) is not str or not self._skill_namespace_available():
            return False
        try:
            projection = self._skill_projection()
            return not projection.unavailable and any(entry.name == name for entry in projection.entries)
        except Exception:
            return False

    def _skill_autocomplete(self, interaction, current: str, *, generation):
        """Return live owner-visible candidates without disclosing a guest catalog."""
        client = self._client
        user = getattr(interaction, "user", None)
        channel = getattr(interaction, "channel", None)
        sender_id = getattr(user, "id", None)
        channel_id = getattr(interaction, "channel_id", None)
        guild_id = getattr(interaction, "guild_id", None)
        parent_id = getattr(channel, "parent_id", None)
        if (not self._running or generation is not self._slash_generation
                or self._opening_generation is generation
                or client is None or getattr(interaction, "client", None) is not client
                or not client.is_ready() or not self._skill_namespace_available()
                or type(current) is not str or len(current) > 100
                or not _positive_id(sender_id) or getattr(user, "bot", None) is not False
                or not _positive_id(channel_id) or getattr(channel, "id", None) != channel_id
                or (guild_id is not None and not _positive_id(guild_id))
                or (parent_id is not None and not _positive_id(parent_id))
                or not _positive_id(getattr(getattr(client, "user", None), "id", None))
                or sender_id == client.user.id):
            return []
        chat_type = "thread" if parent_id is not None else "group" if guild_id is not None else "private"
        try:
            if self.skill_owner(str(sender_id), str(channel_id), chat_type) is not True:
                return []
            projection = self._skill_projection()
            if projection.unavailable:
                return []
            needle = current.casefold()
            return [discord.app_commands.Choice(name=entry.name, value=entry.name)
                    for entry in projection.entries if needle in entry.name.casefold()][:25]
        except Exception:
            return []

    async def _sync_slash_tree(self, generation, client) -> None:
        """Sync once after a real connection; a reconnect does not duplicate a write."""
        tree = self._slash_tree
        if (tree is None or not self._running or generation is not self._slash_generation
                or self._opening_generation is generation
                or client is not self._client or self._slash_synced or self._slash_syncing is not None):
            return
        self._slash_syncing = generation
        try:
            await tree.sync()
            if self._running and generation is self._slash_generation and client is self._client:
                self._slash_synced = True
        except Exception:
            logger.warning("Discord native commands could not be registered")
        finally:
            if self._slash_syncing is generation:
                self._slash_syncing = None

    async def _handle_slash_interaction(self, interaction, name: str, args: str,
                                        *, generation=None, skill_name: str | None = None,
                                        skill_picker: bool = False) -> None:
        """ACK with a neutral receipt, then take the same governed channel route as text."""
        generation = self._slash_generation if generation is None else generation
        client = self._client
        user = getattr(interaction, "user", None)
        sender_id = getattr(user, "id", None)
        channel_id = getattr(interaction, "channel_id", None)
        interaction_id = getattr(interaction, "id", None)
        channel = getattr(interaction, "channel", None)
        guild_id = getattr(interaction, "guild_id", None)
        parent_id = getattr(channel, "parent_id", None)
        if (not self._running or generation is None or generation is not self._slash_generation
                or self._opening_generation is generation
                or client is None or getattr(interaction, "client", None) is not client
                or not client.is_ready() or name not in self._slash_names
                or type(args) is not str or len(args) > 10_000
                or not _positive_id(sender_id) or getattr(user, "bot", None) is not False
                or not _positive_id(channel_id) or getattr(channel, "id", None) != channel_id
                or not _positive_id(interaction_id)
                or (guild_id is not None and not _positive_id(guild_id))
                or (parent_id is not None and not _positive_id(parent_id))
                or not _positive_id(getattr(getattr(client, "user", None), "id", None))
                or sender_id == client.user.id or interaction_id in self._slash_seen):
            return
        self._slash_seen[interaction_id] = None
        if len(self._slash_seen) > DISCORD_SLASH_SEEN_MAX:
            self._slash_seen.popitem(last=False)
        try:
            await interaction.response.send_message(_SLASH_RECEIPT, ephemeral=True)
        except Exception:
            self._slash_seen.pop(interaction_id, None)
            logger.warning("Discord native command acknowledgement failed; command not admitted")
            return
        if (not self._running or generation is not self._slash_generation
                or client is not self._client or not client.is_ready()):
            return
        chat_type = "thread" if parent_id is not None else "group" if guild_id is not None else "private"
        selected_skill = None
        if skill_picker:
            if not self._skill_namespace_available():
                return
            try:
                if (self.skill_owner(str(sender_id), str(channel_id), chat_type) is True
                        and self._skill_selected(skill_name)):
                    selected_skill = skill_name
            except Exception:
                selected_skill = None  # failed owner/catalog checks cannot select a skill
            if selected_skill is None:
                # Preserve pairing and the ordinary unknown-command refusal while
                # keeping a guest's attempted selection out of the gateway text.
                args = ""
            else:
                name = selected_skill
        text = f"/{name} {args}".strip()
        selected_meta = {"_skill_name": selected_skill} if selected_skill is not None else {}
        await self._batch.submit((str(channel_id), str(sender_id)), text,
                                 sender=str(sender_id), channel_id=str(channel_id),
                                 chat_type=chat_type, provider_id=str(interaction_id),
                                 pending_input_eligible=False,
                                 _slash_generation=generation, _slash_client=client,
                                 **selected_meta)

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
        message_id = getattr(message, "id", None)
        extra = {"provider_id": str(message_id)} if type(message_id) is int and message_id > 0 else {}
        await self._batch.submit((channel_id, sender), message.content,
                                 sender=sender, channel_id=channel_id, chat_type=chat_type, **extra)

    async def _deliver_turn(self, key, text: str, meta: dict) -> None:
        if not self.handler:
            return
        if "_slash_generation" in meta and (
            not self._running or meta["_slash_generation"] is not self._slash_generation
            or meta.get("_slash_client") is not self._client
        ):
            return
        if "_skill_name" in meta and not self._skill_selected(meta["_skill_name"]):
            return
        # The orchestrator queues a governed channel.reply. Echoing its return
        # value here would bypass approval (and duplicate an approved delivery).
        extra = {"provider_id": meta["provider_id"]} if meta.get("provider_id") else {}
        if meta.get("pending_input_eligible") is False:
            extra["pending_input_eligible"] = False
        await self.handler(text, channel="discord", sender=meta["sender"], channel_id=meta["channel_id"],
                           chat_type=meta.get("chat_type", "private"), **extra)

    async def stop(self):
        async with self._connection_lifecycle_lock():
            await self._stop_locked()

    async def _stop_locked(self):
        self._running = False
        self._slash_generation = None
        self._ready_client = None
        self._ready_generation = None
        self._slash_synced = False
        self._slash_syncing = None
        self._slash_seen.clear()
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
            # Closing the SDK client does not prove its gateway task has settled.
            # asyncio.wait does not forward a second cancellation to that task.
            await asyncio.wait({task})
            if not task.cancelled():
                task.exception()
            self._start_task = None
        claim = getattr(self, "_connection_claim", None)
        if claim is not None:
            claim.release()
            self._connection_claim = None
        self._opening_generation = None
        self._opening_decision_event = None

    def health_snapshot(self) -> dict:
        """H100 — discord.py reconnects the gateway itself; this reports what it sees:
        ready (healthy), running but not ready (retrying), or why the client gave up — a
        refused token or refused intents are fatal and named."""
        row = super().health_snapshot()
        row["native_commands_registered"] = len(self._slash_names)
        row["native_commands_hidden"] = self._slash_hidden_count
        row["native_commands_synced"] = self._slash_synced
        task = getattr(self, "_start_task", None)
        if task is not None and task.done() and not task.cancelled():
            exc = task.exception()
            if exc is not None:
                name = type(exc).__name__
                reason = ("unauthorized" if name == "LoginFailure"
                          else "intents_refused" if name == "PrivilegedIntentsRequired"
                          else "gateway_closed")
                return {**row, "state": "fatal", "fatal": reason, "error": reason}
        client = self._client
        if self._running and client is not None:
            generation = self._slash_generation
            ready = self._observe_ready(client, generation)
            if self._opening_generation is generation:
                # The SDK may flip is_ready before startup's monotonic admission
                # check resumes. Keep managed startup visibly unadmitted.
                row.update(state="retrying", error="not_ready", failures=0)
            elif ready is None:
                row.update(state="unknown", error="probe_failed", failures=0)
            else:
                row["state"] = "healthy" if ready else "retrying"
                row["error"] = None if ready else "not_ready"
                row["failures"] = 0 if ready else int(
                    self._ready_client is client and self._ready_generation is generation)
        return row

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
            label = sanitize_label(label)          # H069 review M3
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
            delivery_ledger.note_send_failure()
            return None
        channel = client.get_channel(channel_id)
        if channel is None or not _positive_id(getattr(channel, "id", None)):
            delivery_ledger.note_send_failure()
            return None
        pieces = render_outbound(message, self.descriptor)
        if not pieces:
            delivery_ledger.note_send_failure()
            return None
        view = self._pending_view(reply_markup, generation)
        if view is None:
            delivery_ledger.note_send_failure()
            return None
        # Reserve before the first await: concurrent sends cannot evict a live
        # acknowledged card or exceed the bound while their receipts are in flight.
        if len(self._pending_views) + self._pending_sending >= 128:
            view.stop()
            delivery_ledger.note_send_failure()
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
                delivery_ledger.note_send_failure()
                return None
            try:
                sent = await channel.send(piece, **({"view": view} if index == len(pieces) - 1 else {}))
            except asyncio.CancelledError:
                view.stop()
                raise
            except Exception:
                logger.warning("Discord pending card delivery failed")
                view.stop()
                delivery_ledger.note_unconfirmed_ack()
                return None
            # Verify the native ACK before the lifecycle fence: a validated part
            # remains accepted even if this callback generation has gone stale.
            if (not _positive_id(getattr(sent, "id", None))
                    or getattr(sent, "channel", None) is None
                    or not _positive_id(getattr(sent.channel, "id", None))
                    or sent.channel.id != channel_id
                    or getattr(sent, "author", None) is None
                    or not _positive_id(getattr(sent.author, "id", None))
                    or not _positive_id(getattr(client.user, "id", None))
                    or sent.author.id != client.user.id):
                view.stop()
                delivery_ledger.note_unconfirmed_ack()
                return None
            delivery_ledger.note_partial()
            if (not self._running or generation is not self._pending_callback_generation
                    or client is not self._client or not client.is_ready()):
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
        attachments = kwargs.get("attachments")
        from .discord_media import current_permit

        # Only the broker's active approval permit can attach files. Ordinary text,
        # including a literal MEDIA line from a job, follows the existing send path.
        permit = current_permit() if attachments is not None else None
        if attachments is not None:
            target = _requested_id(channel_id)
            if (permit is None or target is None
                    or not permit.current(self, target, attachments)
                    or not self.media_target_allowed(permit.sender_id, target,
                                                     permit.owner_allowed)):
                return False
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
                        if attachments is not None and (not _positive_id(getattr(sent, "id", None))
                                or not self._media_send_current(client, generation, permit, channel)):
                            from . import delivery_ledger
                            delivery_ledger.note_partial()
                            return False
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
                    if attachments is not None:
                        return await self._send_approved_files(channel, permit, client, generation)
                    return True
        except Exception:
            logger.warning("Discord reply transport failed", exc_info=True)
        return False

    def media_target_allowed(self, sender_id, channel_id, owner_allowed) -> bool:
        """The current paired owner and this exact SDK DM recipient must still agree."""
        sender, target = _requested_id(sender_id), _requested_id(channel_id)
        client = self._client
        if (not self._running or client is None or not client.is_ready()
                or sender is None or target is None or not callable(owner_allowed)
                or not DISCORD_AVAILABLE):
            return False
        try:
            channel = client.get_channel(target)
            return (isinstance(channel, discord.DMChannel)
                    and getattr(channel, "id", None) == target
                    and getattr(getattr(channel, "recipient", None), "id", None) == sender
                    and owner_allowed(str(sender), str(target)) is True)
        except Exception:
            return False

    def _media_send_current(self, client, generation, permit, channel) -> bool:
        from .discord_media import current_permit

        return (self._running and self._client is client
                and self._pending_callback_generation is generation
                and current_permit() is permit and permit is not None
                and permit.current(self, permit.channel_id, permit.files)
                and self.media_target_allowed(permit.sender_id, permit.channel_id,
                                              permit.owner_allowed)
                and client.get_channel(permit.channel_id) is channel)

    async def _send_approved_files(self, channel, permit, client, generation) -> bool:
        from . import delivery_ledger
        from .outbound_safety import sanitize_text

        store = delivery_ledger.store()
        for index, item in enumerate(permit.files, start=1):
            if not self._media_send_current(client, generation, permit, channel):
                delivery_ledger.note_partial()
                return False
            delivery = None
            if store is not None:
                try:
                    delivery = store.open_delivery(
                        "discord", permit.channel_id, f"[file {item.mime} {len(item.data)}]",
                        key=f"media:discord:{permit.reply_task_id}:{permit.channel_id}:"
                            f"{index}:{item.sha256}")
                except Exception:
                    logger.warning("Discord attachment delivery ledger unavailable", exc_info=True)
            if delivery is None:
                delivery_ledger.note_partial()
                return False
            if delivery is not None and not delivery.send:
                if not delivery.already_sent:
                    delivery_ledger.note_partial()
                    return False
                continue
            try:
                claimed = delivery.attempting_checked() is True
            except Exception:
                logger.warning("Discord attachment delivery claim unavailable", exc_info=True)
                claimed = False
            if not claimed:
                delivery_ledger.note_partial()
                return False
            if not self._media_send_current(client, generation, permit, channel):
                delivery.finished(False)
                delivery_ledger.note_partial()
                return False
            outcome, token = delivery_ledger.begin_outcome()
            try:
                safe_name = sanitize_text(item.name).replace("/", "_").replace("\\", "_")
                safe_name = "".join(c if c.isprintable() else "_" for c in safe_name).strip(" .")[:255]
                file = discord.File(io.BytesIO(item.data), filename=safe_name or "file")
                try:
                    sent = await channel.send(file=file)
                finally:
                    file.close()
                ok = _positive_id(getattr(sent, "id", None))
            except Exception:
                logger.warning("Discord attachment send failed", exc_info=True)
                # Once transport was entered, a raised error does not prove that
                # the platform rejected the file. Keep retries suppressed.
                outcome.ambiguous = True
                ok = False
            except BaseException as exc:
                delivery.raised(exc)
                raise
            finally:
                delivery_ledger.end_outcome(token)
            if delivery is not None:
                delivery.finished(ok, outcome)
            if not ok or not self._media_send_current(client, generation, permit, channel):
                delivery_ledger.note_partial()
                return False
        return True
