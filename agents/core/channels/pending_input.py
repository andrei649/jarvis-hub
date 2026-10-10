"""Ephemeral, identity-bound clarification and confirmation state.

This module only parses and resolves answers. The caller owns delivery, authority
checks and every effect that may follow a confirmation.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
import uuid
import weakref
from collections.abc import Callable
from dataclasses import dataclass, replace

type PendingKey = tuple[str, str, str]
type AnswerValue = str | list[str]


@dataclass(frozen=True, slots=True)
class ParseResult:
    status: str
    value: AnswerValue | None = None


@dataclass(frozen=True, slots=True)
class Answer:
    value: AnswerValue
    choice: str | None = None


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True)
class Prompt:
    id: str
    key: PendingKey
    kind: str
    question: str
    choices: tuple[str, ...] | None = None
    multi_select: bool = False
    awaiting_text: bool = False
    command: str | None = None
    deadline: float | None = None


@dataclass(frozen=True, slots=True)
class Resolution:
    status: str
    prompt_id: str | None = None
    answer: Answer | None = None


@dataclass(slots=True)
class _State:
    future: asyncio.Future[Answer | None] | None = None
    completed: bool = False
    answer: Answer | None = None
    timer: asyncio.TimerHandle | None = None


_RECOMMENDED = re.compile(r"\s*\(recommended\)\s*$", re.IGNORECASE)
_INTEGER = re.compile(r"[+-]?\d+\Z")
_NUMERIC_LIST = re.compile(r"\d+(?:\s+\d+)+\Z")
_COMMANDS = {
    "approve": "once",
    "yes": "once",
    "ok": "once",
    "confirm": "once",
    "always": "always",
    "remember": "always",
    "cancel": "cancel",
    "no": "cancel",
    "deny": "cancel",
    "nevermind": "cancel",
}
_TEXT = {
    "approve": "once",
    "approve once": "once",
    "once": "once",
    "always": "always",
    "always approve": "always",
    "cancel": "cancel",
    "nevermind": "cancel",
    "no": "cancel",
}


def _bare(value: str) -> str:
    return _RECOMMENDED.sub("", value.strip()).strip()


def parse_confirmation(text: str) -> str | None:
    """Recognize a whole confirmation reply, including slash/bang aliases."""
    if not isinstance(text, str):
        return None
    reply = text.strip().casefold()
    if reply.startswith(("/", "!")):
        return _COMMANDS.get(reply[1:])
    return _TEXT.get(reply)


def _match(token: str, choices: tuple[str, ...]) -> str | None:
    if _INTEGER.fullmatch(token):
        index = int(token) - 1
        if 0 <= index < len(choices):
            return _bare(choices[index])
    wanted = _bare(token).casefold()
    for choice in choices:
        if _bare(choice).casefold() == wanted:
            return _bare(choice)
    return None


def parse_clarify(
    text: str,
    choices: tuple[str, ...] | list[str] | None,
    multi_select: bool = False,
    awaiting_text: bool = False,
) -> ParseResult:
    """Coerce typed replies; distinguish retryable selections from new prose."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    response = text.strip()
    if response.startswith(("/", "!")):
        return ParseResult("fallthrough")
    if len(response) > 16384:
        return ParseResult("invalid_selection")
    options = tuple(choices or ())
    if not options:
        return ParseResult("resolved", response)
    if not multi_select:
        label = _match(response, options)
        if label is not None:
            if len(label) > 16384:
                return ParseResult("invalid_selection")
            return ParseResult("resolved", label)
        if awaiting_text:
            return ParseResult("resolved", response)
        return ParseResult("invalid_selection" if _INTEGER.fullmatch(response) else "prose")

    if "," in response:
        tokens = [item.strip() for item in response.split(",") if item.strip()]
        max_words = max(len(option.split()) for option in options)
        selection_shaped = bool(tokens) and all(
            token.isdigit() or len(token.split()) <= max_words for token in tokens
        )
    elif _NUMERIC_LIST.fullmatch(response):
        tokens = response.split()
        selection_shaped = True
    else:
        tokens = [response]
        selection_shaped = bool(_INTEGER.fullmatch(response))
    selected: list[str] = []
    for token in tokens:
        label = _match(token, options)
        if label is None:
            if awaiting_text:
                return ParseResult("resolved", response)
            return ParseResult("invalid_selection" if selection_shaped else "prose")
        if label not in selected:
            selected.append(label)
    if selected:
        if sum(len(label) for label in selected) > 16384:
            return ParseResult("invalid_selection")
        return ParseResult("resolved", selected)
    return ParseResult("resolved", response) if awaiting_text else ParseResult("prose")


class PendingInputs:
    """Bounded pending prompts for one async orchestrator instance."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_pending: int = 4096):
        if not callable(clock):
            raise TypeError("clock must be callable")
        if type(max_pending) is not int or max_pending <= 0:
            raise TypeError("max_pending must be a positive integer")
        self._clock = clock
        self._now()
        self._limit = max_pending
        self._active: dict[str, Prompt] = {}
        self._order: dict[PendingKey, dict[str, list[str]]] = {}
        self._states: weakref.WeakKeyDictionary[Prompt, _State] = weakref.WeakKeyDictionary()
        self._closed = False

    def _now(self) -> float:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("clock must return a finite number")
        try:
            value = float(value)
        except OverflowError as exc:
            raise ValueError("clock must return a finite number") from exc
        if not math.isfinite(value):
            raise ValueError("clock must return a finite number")
        return value

    @staticmethod
    def _key(key: PendingKey) -> PendingKey:
        if (
            not isinstance(key, tuple)
            or len(key) != 3
            or any(not isinstance(part, str) or not part for part in key)
        ):
            raise ValueError("key must be a three-part nonempty identity tuple")
        return key

    @staticmethod
    def _text(value: str, name: str, limit: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        value = value.strip()
        if not value or len(value) > limit:
            raise ValueError(f"{name} must be nonempty and at most {limit} characters")
        return value

    def _duration(self, value: float, *, clarify: bool) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("timeout_seconds must be a finite number")
        try:
            seconds = float(value)
        except OverflowError as exc:
            raise ValueError("timeout_seconds must be finite") from exc
        if not math.isfinite(seconds):
            raise ValueError("timeout_seconds must be finite")
        if clarify and seconds <= 0:
            return None
        if seconds <= 0:
            raise ValueError("confirmation timeout must be positive")
        return seconds

    def _deadline(self, duration: float | None) -> float | None:
        if duration is None:
            return None
        deadline = self._now() + duration
        if not math.isfinite(deadline):
            raise ValueError("deadline must be finite")
        return deadline

    def _register(self, prompt: Prompt) -> Prompt:
        if self._closed:
            raise RuntimeError("pending inputs are closed")
        self._expire_all()
        if len(self._active) >= self._limit:
            raise OverflowError("pending input capacity reached")
        state = _State()
        self._active[prompt.id] = prompt
        self._states[prompt] = state
        self._order.setdefault(prompt.key, {"clarify": [], "confirmation": []})[prompt.kind].append(
            prompt.id
        )
        if prompt.deadline is not None:
            self._arm(prompt, state)
        return prompt

    def _arm(self, prompt: Prompt, state: _State) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        remaining = max(0.0, prompt.deadline - self._now()) if prompt.deadline else 0.0
        state.timer = loop.call_later(remaining, self._expire_one, prompt.id)

    def _expire_one(self, prompt_id: str) -> None:
        prompt = self._active.get(prompt_id)
        if prompt is None or prompt.deadline is None:
            return
        state = self._states[prompt]
        if self._now() >= prompt.deadline:
            self._finish(prompt, None)
        else:
            self._arm(prompt, state)

    def _expire_all(self) -> None:
        now = self._now()
        for prompt in tuple(self._active.values()):
            if prompt.deadline is not None and now >= prompt.deadline:
                self._finish(prompt, None)

    def register_clarify(
        self,
        key: PendingKey,
        question: str,
        choices: list[str] | tuple[str, ...] | None = None,
        multi_select: bool = False,
        timeout_seconds: float = 3600,
    ) -> Prompt:
        key = self._key(key)
        question = self._text(question, "question", 4096)
        duration = self._duration(timeout_seconds, clarify=True)
        if type(multi_select) is not bool:
            raise TypeError("multi_select must be boolean")
        if choices is not None:
            if not isinstance(choices, (list, tuple)):
                raise TypeError("choices must be a sequence of strings")
            if len(choices) > 4:
                raise ValueError("choices supports at most four entries")
            cleaned = tuple(self._text(choice, "choice", 16384) for choice in choices)
            if len({_bare(choice).casefold() for choice in cleaned}) != len(cleaned):
                raise ValueError("choices must be distinct")
        else:
            cleaned = ()
        return self._register(
            Prompt(
                id=uuid.uuid4().hex,
                key=key,
                kind="clarify",
                question=question,
                choices=cleaned or None,
                multi_select=multi_select and bool(cleaned),
                awaiting_text=not bool(cleaned),
                deadline=self._deadline(duration),
            )
        )

    def register_confirmation(
        self, key: PendingKey, command: str, question: str, timeout_seconds: float = 300
    ) -> Prompt:
        key = self._key(key)
        command = self._text(command, "command", 256)
        question = self._text(question, "question", 4096)
        duration = self._duration(timeout_seconds, clarify=False)
        deadline = self._deadline(duration)
        if self._closed:
            raise RuntimeError("pending inputs are closed")
        self._expire_all()
        for prompt_id in tuple(self._order.get(key, {}).get("confirmation", ())):
            previous = self._active.get(prompt_id)
            if previous is not None:
                self._finish(previous, None)
        return self._register(
            Prompt(
                id=uuid.uuid4().hex,
                key=key,
                kind="confirmation",
                question=question,
                command=command,
                deadline=deadline,
            )
        )

    def pending(self, key: PendingKey, kind: str | None = None) -> Prompt | None:
        key = self._key(key)
        if kind not in (None, "clarify", "confirmation"):
            raise ValueError("kind must be clarify or confirmation")
        self._expire_all()
        buckets = self._order.get(key, {})
        for candidate in (kind,) if kind else ("clarify", "confirmation"):
            for prompt_id in buckets.get(candidate, ()):
                prompt = self._active.get(prompt_id)
                if prompt is not None:
                    return prompt
        return None

    def _finish(self, prompt: Prompt, answer: Answer | None) -> bool:
        current = self._active.get(prompt.id)
        if current is None:
            return False
        state = self._states[current]
        self._active.pop(prompt.id)
        bucket = self._order[current.key][current.kind]
        bucket.remove(prompt.id)
        if not any(self._order[current.key].values()):
            self._order.pop(current.key)
        if state.timer is not None:
            state.timer.cancel()
            state.timer = None
        state.completed = True
        state.answer = answer
        if state.future is not None and not state.future.done():
            state.future.set_result(answer)
        return True

    def resolve(self, prompt_id: str, key: PendingKey, value: AnswerValue) -> bool:
        key = self._key(key)
        self._expire_all()
        prompt = self._active.get(prompt_id)
        if prompt is None or prompt.key != key:
            return False
        if prompt.kind == "confirmation":
            if not isinstance(value, str) or value not in ("once", "always", "cancel"):
                return False
            answer = Answer(value, value)
        elif isinstance(value, str):
            parsed = parse_clarify(value, prompt.choices, prompt.multi_select, prompt.awaiting_text)
            if parsed.status != "resolved":
                return False
            answer = Answer(parsed.value)
        elif isinstance(value, list) and prompt.multi_select and not prompt.awaiting_text:
            if (
                not value
                or any(not isinstance(item, str) for item in value)
                or sum(len(item) for item in value) > 16384
            ):
                return False
            selected = [_match(item, prompt.choices or ()) for item in value]
            if (
                any(item is None for item in selected)
                or sum(len(item) for item in selected) > 16384
            ):
                return False
            answer = Answer(list(dict.fromkeys(selected)))
        else:
            return False
        return self._finish(prompt, answer)

    def mark_other(self, prompt_id: str, key: PendingKey) -> bool:
        key = self._key(key)
        self._expire_all()
        prompt = self._active.get(prompt_id)
        if prompt is None or prompt.key != key or prompt.kind != "clarify" or not prompt.choices:
            return False
        if prompt.awaiting_text:
            return True
        updated = replace(prompt, awaiting_text=True)
        self._states[updated] = self._states[prompt]
        self._active[prompt_id] = updated
        return True

    def intercept(self, key: PendingKey, text: str) -> Resolution:
        prompt = self.pending(key)
        if prompt is None:
            return Resolution("no_pending")
        if prompt.kind == "confirmation":
            choice = parse_confirmation(text)
            if choice is None:
                return Resolution("fallthrough", prompt.id)
            answer = Answer(choice, choice)
        else:
            parsed = parse_clarify(text, prompt.choices, prompt.multi_select, prompt.awaiting_text)
            if parsed.status == "invalid_selection":
                return Resolution("retry", prompt.id)
            if parsed.status == "fallthrough":
                return Resolution("fallthrough", prompt.id)
            if parsed.status == "prose":
                self._finish(prompt, None)
                return Resolution("fallthrough", prompt.id)
            answer = Answer(parsed.value)
        if self._finish(prompt, answer):
            return Resolution("consumed", prompt.id, answer)
        return Resolution("no_pending")

    async def wait(self, prompt: Prompt) -> Answer | None:
        state = self._states.get(prompt)
        if state is None:
            return None
        self._expire_all()
        if state.completed:
            return state.answer
        if state.future is None:
            state.future = asyncio.get_running_loop().create_future()
        if prompt.deadline is not None and state.timer is None:
            self._arm(prompt, state)
        try:
            return await asyncio.shield(state.future)
        except asyncio.CancelledError:
            current = self._active.get(prompt.id)
            if current is not None:
                self._finish(current, None)
            raise

    def cancel_prompt(self, prompt_id: str, key: PendingKey) -> bool:
        """Retire one exact prompt without cancelling its FIFO neighbours."""
        key = self._key(key)
        self._expire_all()
        prompt = self._active.get(prompt_id)
        if prompt is None or prompt.key != key:
            return False
        return self._finish(prompt, None)

    def cancel(self, key: PendingKey) -> int:
        key = self._key(key)
        prompts = [prompt for prompt in tuple(self._active.values()) if prompt.key == key]
        return sum(self._finish(prompt, None) for prompt in prompts)

    def close(self) -> int:
        self._closed = True
        return sum(self._finish(prompt, None) for prompt in tuple(self._active.values()))
