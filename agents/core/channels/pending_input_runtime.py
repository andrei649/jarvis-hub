"""H067 gateway/model clarification binding, before conversation turn leases.

This runtime supports Telegram, governed Slack/Discord cards, typed ntfy prompts
and authenticated HTTP questions. CLI/email remain separate work.
Hermes reference59b2aeef6c7a; see licenses/hermes-pending-input-MIT.txt.
"""

from __future__ import annotations

import asyncio
import contextvars
import time
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import chain

from ..native_human_wait import native_human_wait_window
from .clarify_protocol import _normalize_questions
from .ephemeral import EphemeralReply
from .pending_input import PendingInputs, parse_clarify, parse_confirmation
from .pending_input_cards import NativePromptCards
from .session import SessionSource, build_session_key


@dataclass
class _Binding:
    runtime: ChannelPendingRuntime
    source: SessionSource
    delivery: dict
    active: bool = True
    http_send: object = None
    http_current: object = None
    http_poll: bool = False


_CURRENT = contextvars.ContextVar("channel_pending_input", default=None)
ENABLED_SETTING = "channels.pending_inputs_enabled"
UNAVAILABLE = {"ok": False, "reason": "clarify_context_unavailable"}


def _without_recommendation(label):
    label = label.strip()
    suffix = "(Recommended)"
    return label[: -len(suffix)].strip() if label.casefold().endswith(suffix.casefold()) else label


def pending_key(source: SessionSource):
    if (
        source.silent
        or source.local_only
        or not source.sender
        or not source.thread_id
        or not source.channel
    ):
        return None
    return str(source.channel), build_session_key(source), str(source.sender)


class ChannelPendingRuntime:
    def __init__(self, orch):
        self.orch = orch
        self.inputs = PendingInputs()
        self.closed = False
        self._delivered: dict[str, _Binding] = {}
        self._offered: dict[str, _Binding] = {}
        self._http_acks: dict[str, asyncio.Future] = {}
        self._card_tokens: dict[str, str] = {}
        self._card_generations: dict[str, object] = {}
        self._card_receipts: dict[str, dict] = {}
        self.cards = NativePromptCards(self.inputs, self._card_eligible)

    def _card_eligible(self, prompt):
        binding = self._delivered.get(prompt.id) or self._offered.get(prompt.id)
        if (binding is None or not binding.active
                or binding.source.channel not in {"telegram", "slack", "discord", "ntfy", "web"}
                or pending_key(binding.source) != prompt.key or not self._allowed(binding.source)):
            return False
        if binding.source.channel == "ntfy":
            adapter = (getattr(self.orch, "channels", None) or {}).get("ntfy")
            allowed = getattr(adapter, "_reply_allowed", None)
            if (not callable(allowed) or not allowed(binding.delivery.get("ntfy_topic"),
                                                       binding.delivery.get("ntfy_context"))):
                return False
        if prompt.id in self._card_generations:
            adapter = (getattr(self.orch, "channels", None) or {}).get(binding.source.channel)
            if (not getattr(adapter, "_running", False)
                    or self._card_generations[prompt.id]
                    is not getattr(adapter, "_pending_callback_generation", None)):
                return False
        return (prompt.kind != "confirmation" or self.orch._channel_principal(
            binding.source.channel, binding.source.sender, binding.delivery.get("chat_id")).admin)

    async def _deliver_workspace(self, prompt, binding, text):
        from .pending_input_workspace import receipt_matches

        channel = binding.source.channel
        broker = getattr(self.orch, "channel_replies", None)
        deliver = getattr(broker, "deliver_prompt", None)
        adapter = (getattr(self.orch, "channels", None) or {}).get(channel)
        generation = getattr(adapter, "_pending_callback_generation", None)
        if (not callable(deliver) or generation is None or not getattr(adapter, "_running", False)
                or not binding.delivery.get("_inbox_message_id")):
            return False
        self._offered[prompt.id] = binding
        self._card_generations[prompt.id] = generation
        offer = None
        receipt = None

        def current():
            self.inputs.pending(prompt.key, prompt.kind)
            return prompt.id in self.inputs._active and self._card_eligible(prompt)

        try:
            offer = self.cards.register(prompt)
            receipt = await deliver(binding.delivery["_inbox_message_id"], text, channel=channel,
                                    sender=binding.source.sender, markup=offer.markup,
                                    current=current, timeout_seconds=None if prompt.deadline is None
                                    else max(0, prompt.deadline - time.monotonic()))
            if (current() and receipt_matches(receipt, channel, binding.delivery, binding.source.sender)
                    and self.cards.bind_workspace(offer.token, receipt)):
                self._card_tokens[prompt.id] = offer.token
                self._card_receipts[prompt.id] = receipt
                self._delivered[prompt.id] = binding
                return True
            return False
        except Exception:
            return False
        finally:
            self._offered.pop(prompt.id, None)
            if prompt.id not in self._card_tokens:
                if offer is not None:
                    self.cards.discard(offer.token)
                self._card_generations.pop(prompt.id, None)
                discard = getattr(self.orch.channel_manager, "discard_pending_card", None)
                if receipt is not None and callable(discard):
                    discard(channel, receipt)

    async def _deliver_ntfy(self, prompt, binding, text):
        broker = getattr(self.orch, "channel_replies", None)
        deliver = getattr(broker, "deliver_prompt", None)
        adapter = (getattr(self.orch, "channels", None) or {}).get("ntfy")
        generation = getattr(adapter, "_pending_callback_generation", None)
        if not callable(deliver) or generation is None or not binding.delivery.get("_inbox_message_id"):
            return False
        self._offered[prompt.id] = binding
        self._card_generations[prompt.id] = generation

        def current():
            self.inputs.pending(prompt.key, prompt.kind)
            return prompt.id in self.inputs._active and self._card_eligible(prompt)

        try:
            receipt = await deliver(binding.delivery["_inbox_message_id"], text, channel="ntfy",
                                    sender=binding.source.sender, markup=None, current=current,
                                    timeout_seconds=None if prompt.deadline is None else
                                    max(0, prompt.deadline - time.monotonic()))
            if receipt is True and current():
                self._delivered[prompt.id] = binding
                return True
            return False
        finally:
            self._offered.pop(prompt.id, None)
            if prompt.id not in self._delivered:
                self._card_generations.pop(prompt.id, None)

    async def _deliver(self, prompt, binding, text):
        """Bind native callbacks only after a strict transport receipt; else use text."""
        if binding.source.channel == "web":
            if binding.http_poll:
                self._offered[prompt.id] = binding
                ack = asyncio.get_running_loop().create_future()
                self._http_acks[prompt.id] = ack
                while not ack.done():
                    candidate = self.inputs.pending(prompt.key, "clarify")
                    if (candidate is None or candidate.id != prompt.id
                            or not binding.active or not self._allowed(binding.source)):
                        return False
                    await asyncio.wait({ack}, timeout=0.5)
                return not ack.cancelled() and ack.result() is True
            sent = await binding.http_send({
                "type": "clarify", "id": prompt.id, "question": prompt.question,
                "choices": list(prompt.choices or ()), "multi_select": prompt.multi_select,
            })
            if sent is True and binding.active and self._allowed(binding.source):
                self._delivered[prompt.id] = binding
                return True
            return False
        if binding.source.channel in {"slack", "discord"}:
            return await self._deliver_workspace(prompt, binding, text)
        if binding.source.channel == "ntfy":
            return await self._deliver_ntfy(prompt, binding, text)
        if binding.source.channel != "telegram":
            return False
        send_card = getattr(self.orch.channel_manager, "send_pending_card", None)
        offer = None
        if callable(send_card):
            self._offered[prompt.id] = binding
            adapter = (getattr(self.orch, "channels", None) or {}).get("telegram")
            generation = getattr(adapter, "_pending_callback_generation", None)
            try:
                offer = self.cards.register(prompt)
                receipt = await send_card("telegram", text, offer.markup, **binding.delivery)
                if (generation is not None and generation
                        is getattr(adapter, "_pending_callback_generation", None)):
                    self._card_generations[prompt.id] = generation
                    if self.cards.bind(offer.token, binding.delivery.get("chat_id"), receipt,
                                       binding.delivery.get("message_thread_id")):
                        self._card_tokens[prompt.id] = offer.token
                        self._delivered[prompt.id] = binding
                        return True
            except Exception:
                self._card_generations.pop(prompt.id, None)
            finally:
                self._offered.pop(prompt.id, None)
                if offer is not None and prompt.id not in self._card_tokens:
                    self.cards.discard(offer.token)
                    self._card_generations.pop(prompt.id, None)
        if not binding.active or not self._allowed(binding.source):
            return False
        try:
            sent = await self.orch.channel_manager.send(
                "telegram", EphemeralReply(text, 0), **binding.delivery, voice=False, plain=True)
        except Exception:
            return False
        if sent is not True or not binding.active or not self._allowed(binding.source):
            return False
        self._delivered[prompt.id] = binding
        return True

    def _retire(self, prompt):
        self._delivered.pop(prompt.id, None)
        self._offered.pop(prompt.id, None)
        ack = self._http_acks.pop(prompt.id, None)
        if ack is not None and not ack.done():
            ack.cancel()
        token = self._card_tokens.pop(prompt.id, None)
        if token is not None:
            self.cards.discard(token)
        self._card_generations.pop(prompt.id, None)
        receipt = self._card_receipts.pop(prompt.id, None)
        discard = getattr(self.orch.channel_manager, "discard_pending_card", None)
        if receipt is not None and callable(discard):
            discard(prompt.key[0], receipt)
        self.inputs.cancel_prompt(prompt.id, prompt.key)

    def enabled(self):
        return not self.closed and self.orch.get_setting(ENABLED_SETTING, False) is True

    def _allowed(self, source):
        if not self.enabled() or pending_key(source) is None:
            return False
        if source.channel == "web":
            # Only bind_http creates this capability; channel payloads cannot
            # provide callbacks or impersonate an HTTP credential/session.
            candidates = chain((_CURRENT.get(),), self._delivered.values(), self._offered.values())
            for binding in candidates:
                if (binding is not None and binding.runtime is self and binding.active
                        and binding.source == source and (callable(binding.http_send) or binding.http_poll)
                        and callable(binding.http_current)):
                    try:
                        return binding.http_current() is True
                    except Exception:
                        return False
            return False
        adapter = (getattr(self.orch, "channels", None) or {}).get(source.channel)
        if adapter is None:
            return False
        if source.channel == "ntfy" and (not getattr(adapter, "_running", False)
                or not getattr(adapter, "inbound", False) or source.sender != getattr(adapter, "topic", None)):
            return False
        pairing = getattr(adapter, "_pairing", None) or getattr(adapter, "pairing", None)
        if pairing is None:
            return source.channel == "telegram"  # Preserve direct Telegram's legacy posture.
        try:
            return pairing.is_allowed(source.channel, str(source.sender)) is True
        except Exception:
            return False

    @contextmanager
    def bind_http(self, actor, session_id, send, current, *, poll=False):
        if (not isinstance(actor, str) or len(actor) != 64
                or not isinstance(session_id, str) or not session_id
                or (not callable(send) and not (poll is True and send is None))
                or not callable(current)):
            raise ValueError("verified HTTP clarification binding required")
        source = SessionSource(channel="web", sender=actor, thread_id=session_id,
                               explicit_session_id=session_id, chat_type="private")
        binding = _Binding(self, source, {}, http_send=send, http_current=current, http_poll=poll is True)
        token = _CURRENT.set(binding)
        try:
            yield
        finally:
            binding.active = False
            _CURRENT.reset(token)

    def http_questions(self, actor, *, session_id=None, offset=0, limit=20):
        """Only poll bindings owned by this current credential can be exposed."""
        questions = []
        for prompt_id, binding in {**self._offered, **self._delivered}.items():
            if (not binding.http_poll or binding.source.sender != actor
                    or (session_id is not None and binding.source.thread_id != session_id)
                    or not binding.active or not self._allowed(binding.source)):
                continue
            prompt = self.inputs.pending(pending_key(binding.source), "clarify")
            if prompt is None or prompt.id != prompt_id:
                continue
            questions.append({"id": prompt.id, "session_id": binding.source.thread_id,
                              "question": prompt.question, "choices": list(prompt.choices or ()),
                              "multi_select": prompt.multi_select})
        return questions[offset:offset + limit], len(questions) > offset + limit

    def acknowledge_http(self, prompt_id, actor):
        """A response's completed send acknowledges this exact live offer."""
        binding = self._offered.get(prompt_id)
        if (binding is None or not binding.http_poll or binding.source.sender != actor
                or not binding.active or not self._allowed(binding.source)):
            return
        prompt = self.inputs.pending(pending_key(binding.source), "clarify")
        ack = self._http_acks.get(prompt_id)
        if prompt is None or prompt.id != prompt_id or ack is None or ack.done():
            return
        self._delivered[prompt_id] = binding
        ack.set_result(True)

    def answer_http(self, prompt_id, actor, value, *, other=False, cancel=False):
        binding = self._delivered.get(prompt_id)
        if (binding is None or binding.source.channel != "web"
                or binding.source.sender != actor):
            return "unavailable"
        key = pending_key(binding.source)
        prompt = self.inputs.pending(key, "clarify")
        if prompt is None or prompt.id != prompt_id:
            return "unavailable"
        if not self._card_eligible(prompt):
            self.inputs.cancel_prompt(prompt.id, key)
            return "unavailable"
        if cancel:
            return "resolved" if self.inputs.cancel_prompt(prompt.id, key) else "unavailable"
        if other and (not isinstance(value, str) or not value.strip() or len(value) > 16384
                      or not self.inputs.mark_other(prompt.id, key)):
            return "invalid"
        return "resolved" if self.inputs.resolve(prompt.id, key, value) else "invalid"

    @contextmanager
    def bind(self, source, delivery):
        # Only trusted transport routing metadata crosses into the tool callback.
        fields = {
            "telegram": ("chat_id", "message_thread_id"),
            "slack": ("slack_channel", "thread_ts", "_inbox_message_id"),
            "discord": ("channel_id", "_inbox_message_id"),
            "ntfy": ("chat_id", "ntfy_topic", "ntfy_context", "_inbox_message_id"),
        }.get(source.channel, ())
        metadata = {
            key: delivery[key] for key in fields if key in delivery
        }
        binding = _Binding(self, source, metadata)
        token = _CURRENT.set(binding)
        try:
            yield
        finally:
            binding.active = False
            _CURRENT.reset(token)

    def intercept(self, source, text, *, pending_only=False):
        if source.channel == "web":
            return None  # HTTP answers must cross answer_http's actor binding.
        key = pending_key(source)
        if key is None:
            return None
        if not self._allowed(source):
            self.inputs.cancel(key)
            return None
        prompt = self.inputs.pending(key)
        if prompt is None or prompt.id not in self._delivered:
            return None
        binding = self._delivered[prompt.id]
        if source.channel in {"slack", "discord", "ntfy"} and not self._card_eligible(prompt):
            return None
        if not binding.active:
            self.inputs.cancel(key)
            return None
        if prompt.kind == "clarify" and text.strip().casefold() in {"/cancel", "!cancel"}:
            # Cancelling this exact delivered wait is not a new model turn.
            # Resolve it before the transport queues commands behind its waiter.
            return "" if self.inputs.cancel_prompt(prompt.id, key) else None
        if prompt.kind == "confirmation" and parse_confirmation(text) is None:
            return None
        if source.channel == "ntfy" and prompt.kind == "clarify":
            parsed = parse_clarify(text, prompt.choices, prompt.multi_select, prompt.awaiting_text)
            # Hermes's text-only fallback maps valid choices first, then
            # accepts an own answer; it must not wait for an Other button.
            if (parsed.status in {"prose", "invalid_selection"}
                    and text.strip() and len(text.strip()) <= 16384
                    and self.inputs.mark_other(prompt.id, key)
                    and self.inputs.resolve(prompt.id, key, text.strip())):
                return ""
        if prompt.kind == "clarify" and pending_only and parse_clarify(
            text, prompt.choices, prompt.multi_select, prompt.awaiting_text
        ).status in {"prose", "fallthrough"}:
            # A new-turn message must pass rate admission before cancelling the
            # waiting question. The early transport hook has no model fallback.
            return None
        result = self.inputs.intercept(key, text)
        if result.status == "consumed":
            return ""
        if result.status == "retry":
            return EphemeralReply(
                "Choose a listed option by number or label; the question is still waiting."
            )
        return None

    async def command(self, source, text, delivery):
        from .session_command_runtime import SessionCommandRuntime

        return await SessionCommandRuntime(self).handle(source, text, delivery)

    async def confirmation(self, command, question):
        binding = _CURRENT.get()
        if (binding is None or binding.runtime is not self or not binding.active
                or not self._allowed(binding.source)):
            return None
        prompt = self.inputs.register_confirmation(pending_key(binding.source), command, question)
        waiter = asyncio.create_task(self.inputs.wait(prompt), name="channel-command-confirmation")
        try:
            sent = await self._deliver(prompt, binding, question +
                "\nApprove Once: /approve | Always Approve: /always | Cancel: /cancel")
            if not sent:
                return None
            while not waiter.done():
                if (not binding.active or not self._allowed(binding.source)
                        or not self._card_eligible(prompt)
                        or not self.orch._channel_principal(
                            binding.source.channel, binding.source.sender,
                            binding.delivery.get("chat_id")).admin):
                    return None
                await asyncio.wait({waiter}, timeout=0.5)
            answer = await waiter
            return answer.choice if answer and self._card_eligible(prompt) else None
        finally:
            self._retire(prompt)
            if not waiter.done():
                waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    async def clarify(self, args):
        if isinstance(args, dict) and "questions" in args:
            # Donor normalization runs for the whole batch before any prompt.
            normalized, error = _normalize_questions(args["questions"])
            if error:
                return {"ok": False, "reason": "invalid_clarify_args"}
            if normalized:
                if any(len(entry["question"]) > 4096
                       or (entry["id"] is not None and len(entry["id"]) > 256)
                       or any(len(c) > 16384 for c in entry["choices"] or ())
                       for entry in normalized):
                    return {"ok": False, "reason": "invalid_clarify_args"}
                responses = [{**({"id": entry["id"]} if entry["id"] else {}),
                              "question": entry["question"],
                              "choices_offered": entry["choices_offered"],
                              "user_response": ""} for entry in normalized]
                result = {"ok": True, "responses": responses}
                for entry, response in zip(normalized, responses, strict=True):
                    answer = await self._clarify_one(entry)
                    if not answer.get("ok"):
                        result.update(timed_out=True, notice=answer.get("reason", "clarify_unavailable"))
                        break
                    response["user_response"] = answer["user_response"]
                return result
        return await self._clarify_one(args)

    async def _clarify_one(self, args):
        binding = _CURRENT.get()
        if (
            binding is None
            or binding.runtime is not self
            or not binding.active
            or binding.source.channel not in {"telegram", "slack", "discord", "ntfy", "web"}
            or (binding.source.channel == "web"
                and ((not callable(binding.http_send) and not binding.http_poll)
                     or not callable(binding.http_current)))
            or not self._allowed(binding.source)
        ):
            return dict(UNAVAILABLE)
        if (
            not isinstance(args, dict)
            or not isinstance(args.get("question"), str)
            or type(args.get("multi_select", False)) is not bool
        ):
            return {"ok": False, "reason": "invalid_clarify_args"}
        choices = args.get("choices")
        if choices is not None:
            if not isinstance(choices, list) or any(
                not isinstance(choice, str) for choice in choices
            ):
                return {"ok": False, "reason": "invalid_clarify_args"}
            choices = [choice.strip() for choice in choices]
            if any(not _without_recommendation(choice) for choice in choices):
                return {"ok": False, "reason": "invalid_clarify_args"}
            if len(choices) >= 2 and not choices[0].casefold().endswith("(recommended)"):
                choices[0] += " (Recommended)"
        try:
            prompt = self.inputs.register_clarify(
                pending_key(binding.source),
                args["question"],
                choices,
                multi_select=args.get("multi_select", False),
                timeout_seconds=self.orch.get_setting("agent.clarify_timeout", 3600),
            )
        except (TypeError, ValueError, OverflowError, RuntimeError):
            return {"ok": False, "reason": "invalid_clarify_args"}
        waiter = asyncio.create_task(self.inputs.wait(prompt), name="channel-clarify-answer")
        text = prompt.question
        if prompt.choices:
            text += "\n" + "\n".join(
                f"{index}. {choice}" for index, choice in enumerate(prompt.choices, 1)
            )
            text += (
                "\nReply with numbers separated by commas or spaces, or option labels."
                if prompt.multi_select
                else "\nReply with an option number or label."
            )
        else:
            text += "\nType your answer."
        if binding.source.channel == "ntfy" and prompt.choices:
            text += "\nYou can also type your own answer."

        def current():
            candidate = self.inputs.pending(prompt.key, "clarify")
            return (
                binding.active
                and self._allowed(binding.source)
                and (binding.source.channel == "telegram" or self._card_eligible(prompt))
                and self._delivered.get(prompt.id) is binding
                and candidate is not None
                and candidate.id == prompt.id
            )

        try:
            sent = await self._deliver(prompt, binding, text)
            if sent is not True:
                return {"ok": False, "reason": "prompt_delivery_failed"}
            # A stopped or detached request cannot gain a new delivery binding.
            if (not binding.active or not self._allowed(binding.source)
                    or (binding.source.channel != "telegram" and not self._card_eligible(prompt))):
                return {"ok": False, "reason": "prompt_binding_lost"}
            self._delivered[prompt.id] = binding
            deadline = prompt.deadline or (time.monotonic() + 1_000_000_000)
            with native_human_wait_window(deadline=deadline, current=current):
                while not waiter.done():
                    if (not binding.active or not self._allowed(binding.source)
                            or (binding.source.channel != "telegram" and not self._card_eligible(prompt))):
                        return {"ok": False, "reason": "prompt_binding_lost"}
                    await asyncio.wait({waiter}, timeout=0.5)
                answer = await waiter
            if answer is None:
                return {"ok": False, "reason": "clarify_cancelled_or_timed_out"}
            return {
                "ok": True,
                "user_response": answer.value,
                "choices_offered": [
                    _without_recommendation(choice) for choice in prompt.choices or ()
                ],
                "multi_select": prompt.multi_select,
            }
        finally:
            self._retire(prompt)
            if not waiter.done():
                waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    def close(self):
        self.closed = True
        for ack in self._http_acks.values():
            if not ack.done():
                ack.cancel()
        self._http_acks.clear()
        discard = getattr(self.orch.channel_manager, "discard_pending_card", None)
        if callable(discard):
            for receipt in self._card_receipts.values():
                discard(receipt["channel"], receipt)
        self._card_receipts.clear()
        close_prompts = getattr(getattr(self.orch, "channel_replies", None), "close_pending_prompts", None)
        if callable(close_prompts):
            close_prompts()
        self._delivered.clear()
        self._offered.clear()
        self._card_tokens.clear()
        self._card_generations.clear()
        self.cards.close()
        return self.inputs.close()


def register_clarify_tool(server, orch):
    getter = getattr(orch, "get_setting", None)
    try:
        enabled = callable(getter) and getter(ENABLED_SETTING, False) is True
    except Exception:
        enabled = False
    if not enabled:
        return False
    async def clarify(args):
        # A same-instance channel restart retires the old runtime. Resolve at
        # call time so a registered tool cannot retain its closed prompt store.
        runtime = orch._pending_input_service()
        return await runtime.clarify(args) if runtime is not None else dict(UNAVAILABLE)

    server.register_tool(
        "clarify",
        clarify,
        gated=False,
        untrusted_output=True,
        description="Ask this conversation's user a clarification and wait for their reply.",
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "minLength": 1, "maxLength": 4096},
                "choices": {
                    "type": "array",
                    "maxItems": 4,
                    "items": {"type": "string", "minLength": 1, "maxLength": 16384},
                },
                "multi_select": {"type": "boolean"},
                "questions": {
                    "type": "array", "maxItems": 5,
                    "items": {"anyOf": [{"type": "string", "maxLength": 4096},
                                         {"type": "object"}]},
                },
            },
            "anyOf": [{"required": ["question"]}, {"required": ["questions"]}],
            "additionalProperties": False,
        },
        capability_id="tool:clarify",
        max_result_bytes=65536,
    )
    return True
