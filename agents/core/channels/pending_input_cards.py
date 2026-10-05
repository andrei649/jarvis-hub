"""Ephemeral Telegram button state for exact, already-delivered pending prompts.

The caller sends ``CardOffer.markup`` and calls ``bind`` only after the Bot API
acknowledges the final bot-owned message. ``handle`` accepts a Telegram
``callback_query`` dictionary. It never sends messages or performs effects.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

from .pending_input import PendingInputs, Prompt
from .pending_input_workspace import receipt_identity, valid_callback, valid_receipt

_DATA = re.compile(r"h067:([A-Za-z0-9_-]{16}):([0-9]{1,10}):([a-z][0-9]?)\Z")
_RECOMMENDED = re.compile(r"\s*\(recommended\)\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CardOffer:
    token: str
    prompt_id: str
    markup: dict


@dataclass(frozen=True, slots=True)
class CardResult:
    applied: bool
    status: str
    prompt_id: str | None = None
    markup: dict | None = None


@dataclass(slots=True)
class _Card:
    prompt: Prompt
    token: str
    revision: int = 0
    selected: set[int] = field(default_factory=set)
    receipt: tuple | None = None


class NativePromptCards:
    """Bounded one-process offers; the pending resolver remains first writer."""

    def __init__(
        self,
        inputs: PendingInputs,
        eligible: Callable[[Prompt], bool],
        max_pending: int = 4096,
    ) -> None:
        if not isinstance(inputs, PendingInputs):
            raise TypeError("inputs must be PendingInputs")
        if not callable(eligible):
            raise TypeError("eligible must be callable")
        if type(max_pending) is not int or max_pending <= 0:
            raise TypeError("max_pending must be a positive integer")
        self._inputs = inputs
        self._eligible = eligible
        self._limit = max_pending
        self._cards: dict[str, _Card] = {}
        self._closed = False

    def _is_eligible(self, prompt: Prompt) -> bool:
        try:
            return self._eligible(prompt) is True
        except Exception:
            return False

    def _current(self, card: _Card) -> Prompt | None:
        # pending() expires deadlines; _active provides exact-ID lookup because
        # pending() intentionally returns only the FIFO head for an identity.
        self._inputs.pending(card.prompt.key, card.prompt.kind)
        prompt = self._inputs._active.get(card.prompt.id)
        if prompt is None or prompt.key != card.prompt.key or prompt.kind != card.prompt.kind:
            return None
        return prompt

    def _prune(self) -> None:
        if not self._cards:
            return
        if self._closed:
            self._cards.clear()
            return
        first = next(iter(self._cards.values()))
        self._inputs.pending(first.prompt.key, first.prompt.kind)
        for token, card in tuple(self._cards.items()):
            if card.prompt.id not in self._inputs._active:
                self._cards.pop(token, None)

    @staticmethod
    def _button(card: _Card, text: str, action: str) -> dict[str, str]:
        data = f"h067:{card.token}:{card.revision}:{action}"
        if len(data.encode("ascii")) > 64:
            raise ValueError("callback data exceeds Telegram's limit")
        return {"text": text, "callback_data": data}

    def _markup(self, card: _Card, prompt: Prompt) -> dict:
        rows: list[list[dict[str, str]]] = []
        if prompt.kind == "confirmation":
            rows.append([self._button(card, "Once", "n"), self._button(card, "Always", "a")])
        elif not prompt.awaiting_text:
            for index, choice in enumerate(prompt.choices or ()):
                label = f"{index + 1}. {choice}" if prompt.key[0] in {"slack", "discord"} else choice
                label = f"✓ {label}" if index in card.selected else label
                rows.append([self._button(card, label, f"{'t' if prompt.multi_select else 'c'}{index}")])
            if prompt.multi_select:
                rows.append([self._button(card, "Submit", "s")])
            if prompt.choices:
                rows.append([self._button(card, "Other", "o")])
        rows.append([self._button(card, "Cancel", "x")])
        return {"inline_keyboard": rows}

    def register(self, prompt: Prompt) -> CardOffer:
        if self._closed:
            raise RuntimeError("native prompt cards are closed")
        if not isinstance(prompt, Prompt):
            raise TypeError("prompt must be a Prompt")
        self._prune()
        self._inputs.pending(prompt.key, prompt.kind)
        live = self._inputs._active.get(prompt.id)
        if live is None or live.key != prompt.key or live.kind != prompt.kind:
            raise ValueError("prompt is not live")
        if not self._is_eligible(live):
            raise ValueError("prompt is not eligible")
        if any(card.prompt.id == prompt.id for card in self._cards.values()):
            raise ValueError("prompt already has an offer")
        if len(self._cards) >= self._limit:
            raise OverflowError("native card capacity reached")
        token = secrets.token_urlsafe(12)
        while token in self._cards:
            token = secrets.token_urlsafe(12)
        card = _Card(live, token)
        self._cards[token] = card
        return CardOffer(token, prompt.id, self._markup(card, live))

    def bind(self, token: str, chat_id: int, message_id: int, thread_id: int | None = None) -> bool:
        if self._closed or type(token) is not str:
            return False
        if (
            type(chat_id) is not int
            or type(message_id) is not int
            or chat_id == 0
            or message_id <= 0
            or (thread_id is not None and (type(thread_id) is not int or thread_id <= 0))
        ):
            return False
        card = self._cards.get(token)
        if card is None:
            return False
        prompt = self._current(card)
        if prompt is None:
            self._cards.pop(token, None)
            return False
        if not self._is_eligible(prompt):
            return False
        receipt = (chat_id, message_id, thread_id)
        if card.receipt is not None:
            return card.receipt == receipt
        card.receipt = receipt
        return True

    def handle(self, callback: dict) -> CardResult:
        rejected = CardResult(False, "rejected")
        if self._closed or not isinstance(callback, dict):
            return rejected
        data = callback.get("data")
        match = _DATA.fullmatch(data) if type(data) is str else None
        if match is None or len(data.encode("utf-8")) > 64:
            return rejected
        token, revision_text, action = match.groups()
        card = self._cards.get(token)
        if card is None or card.receipt is None:
            return rejected
        message = callback.get("message")
        sender = callback.get("from")
        if not isinstance(message, dict) or not isinstance(sender, dict):
            return rejected
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return rejected
        sender_id = sender.get("id")
        receipt = (chat.get("id"), message.get("message_id"), message.get("message_thread_id"))
        if (
            type(sender_id) is not int
            or type(receipt[0]) is not int
            or type(receipt[1]) is not int
            or (receipt[2] is not None and type(receipt[2]) is not int)
            or receipt != card.receipt
            or str(sender_id) != card.prompt.key[2]
            or int(revision_text) != card.revision
        ):
            return rejected
        prompt = self._current(card)
        if prompt is None:
            self._cards.pop(token, None)
            return rejected
        # Fresh owner/pairing/origin eligibility must precede every mutation.
        if not self._is_eligible(prompt):
            return rejected
        return self._apply(card, prompt, action)

    def bind_workspace(self, token: str, receipt: dict) -> bool:
        if self._closed or type(token) is not str or not valid_receipt(receipt):
            return False
        card = self._cards.get(token)
        if card is None or card.prompt.key[0] != receipt["channel"]:
            return False
        prompt = self._current(card)
        if prompt is None or not self._is_eligible(prompt):
            return False
        identity = receipt_identity(receipt)
        if card.receipt is not None:
            return card.receipt == identity
        card.receipt = identity
        return True

    def handle_workspace(self, callback: dict) -> CardResult:
        rejected = CardResult(False, "rejected")
        if self._closed or not isinstance(callback, dict):
            return rejected
        channel = callback.get("channel")
        if not valid_callback(callback, channel):
            return rejected
        token, revision, action = _DATA.fullmatch(callback["data"]).groups()
        card = self._cards.get(token)
        if (card is None or card.prompt.key[0] != channel
                or card.receipt != receipt_identity(callback)
                or card.prompt.key[2] != callback["sender"]
                or card.revision != int(revision)):
            return rejected
        prompt = self._current(card)
        if prompt is None or not self._is_eligible(prompt):
            return rejected
        return self._apply(card, prompt, action)

    def _apply(self, card: _Card, prompt: Prompt, action: str) -> CardResult:
        rejected = CardResult(False, "rejected")
        token = card.token
        key = prompt.key
        prompt_id = prompt.id
        if action == "x":
            success = (
                self._inputs.resolve(prompt_id, key, "cancel")
                if prompt.kind == "confirmation"
                else self._inputs.cancel_prompt(prompt_id, key)
            )
            status = "cancelled"
        elif prompt.kind == "confirmation":
            if action not in ("n", "a"):
                return rejected
            success = self._inputs.resolve(prompt_id, key, "once" if action == "n" else "always")
            status = "resolved"
        elif action == "o" and prompt.choices and not prompt.awaiting_text:
            success = self._inputs.mark_other(prompt_id, key)
            if success:
                card.revision += 1
                current = self._inputs._active[prompt_id]
                return CardResult(True, "awaiting_text", prompt_id, self._markup(card, current))
            status = "rejected"
        elif prompt.awaiting_text:
            return rejected
        elif action.startswith("c") and not prompt.multi_select:
            index = int(action[1:]) if action[1:].isdigit() else -1
            if not prompt.choices or not 0 <= index < len(prompt.choices):
                return rejected
            value = _RECOMMENDED.sub("", prompt.choices[index].strip()).strip()
            success = self._inputs.resolve(prompt_id, key, value)
            status = "resolved"
        elif action.startswith("t") and prompt.multi_select:
            index = int(action[1:]) if action[1:].isdigit() else -1
            if not prompt.choices or not 0 <= index < len(prompt.choices):
                return rejected
            if index in card.selected:
                card.selected.remove(index)
            else:
                card.selected.add(index)
            card.revision += 1
            return CardResult(True, "updated", prompt_id, self._markup(card, prompt))
        elif action == "s" and prompt.multi_select and card.selected:
            choices = prompt.choices or ()
            values = [_RECOMMENDED.sub("", choices[index].strip()).strip() for index in sorted(card.selected)]
            success = self._inputs.resolve(prompt_id, key, values)
            status = "resolved"
        else:
            return rejected
        if not success:
            return rejected
        self._cards.pop(token, None)
        return CardResult(True, status, prompt_id)

    def discard(self, token: str) -> None:
        self._cards.pop(token, None)

    def close(self) -> None:
        self._closed = True
        self._cards.clear()
