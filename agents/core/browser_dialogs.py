"""Ephemeral native-dialog evidence; it confers no actuation authority."""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urldefrag

_TYPES = frozenset({'alert', 'confirm', 'prompt', 'beforeunload'})
_TEXT_LIMIT = 1024


class DialogObservationRefused(ValueError):
    """A bounded native dialog could not be attributed to the armed main frame."""


@dataclass
class _PromptEntry:
    text: str
    agent: str
    args: dict
    expires: float
    task_id: int | None = None
    fingerprint: str | None = None


class _PromptLease:
    def __init__(self, store: DialogPromptStore, agent: str,
                 args: dict, ref: str | None) -> None:
        self.store = store
        self.agent = agent
        self.args = args
        self.ref = ref
        self.bound = False

    def bind(self, task_id: int) -> None:
        task = self.store.task_lookup(task_id)
        if (type(task_id) is not int or task_id <= 0 or task is None
                or task.kind != 'toolrpc.browser_dialog'
                or task.status != 'proposed'
                or task.payload != {'tool': 'browser_dialog', 'args': self.args}
                or task.agent != self.agent):
            raise ValueError('dialog_task_changed')
        fingerprint = self.store.task_fingerprint(task)
        if type(fingerprint) is not str or not fingerprint:
            raise ValueError('dialog_task_changed')
        if self.ref is not None:
            with self.store._lock:
                entry = self.store._entries.get(self.ref)
                if (entry is None or entry.task_id is not None
                        or entry.args != self.args or entry.expires <= time.monotonic()):
                    raise ValueError('dialog_task_changed')
                entry.task_id = task_id
                entry.fingerprint = fingerprint
        self.bound = True

    def release(self) -> None:
        if self.ref is not None and not self.bound:
            self.store.wipe(self.ref)


class DialogPromptStore:
    """Short-lived process-only prompt values bound to exact durable rows."""

    def __init__(self, *, task_lookup: Callable[[int], object],
                 task_fingerprint: Callable[[object], str]) -> None:
        self.task_lookup = task_lookup
        self.task_fingerprint = task_fingerprint
        self._key = secrets.token_bytes(32)
        self._entries: dict[str, _PromptEntry] = {}
        self._lock = threading.Lock()

    def seal(self, agent: str, raw: dict) -> _PromptLease:
        if (type(agent) is not str or not agent or type(raw) is not dict
                or set(raw) not in ({'opener_task_id', 'dialog_id', 'choice'},
                                    {'opener_task_id', 'dialog_id', 'choice', 'prompt_text'})
                or type(raw.get('opener_task_id')) is not int
                or raw['opener_task_id'] <= 0 or type(raw.get('dialog_id')) is not str
                or len(raw['dialog_id']) != 32
                or any(char not in '0123456789abcdef' for char in raw['dialog_id'])
                or raw.get('choice') not in {'accept', 'dismiss'}):
            raise ValueError('invalid_dialog_proposal')
        safe = {key: raw[key] for key in ('opener_task_id', 'dialog_id', 'choice')}
        if 'prompt_text' not in raw:
            return _PromptLease(self, agent, safe, None)
        value = raw['prompt_text']
        if (raw['choice'] != 'accept' or type(value) is not str
                or len(value) > _TEXT_LIMIT
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError('invalid_dialog_prompt')
        try:
            encoded = value.encode('utf-8')
        except UnicodeError:
            raise ValueError('invalid_dialog_prompt') from None
        ref = secrets.token_hex(16)
        proof = json.dumps([agent, safe['opener_task_id'], safe['dialog_id'],
                            safe['choice'], ref], separators=(',', ':')).encode() + encoded
        safe.update(prompt_ref=ref, prompt_digest=hmac.new(self._key, proof, hashlib.sha256).hexdigest(),
                    prompt_length=len(value))
        with self._lock:
            self._entries[ref] = _PromptEntry(value, agent, dict(safe), time.monotonic() + 60)
        return _PromptLease(self, agent, safe, ref)

    def _value(self, ref: str, *, task_id: int, fingerprint: str, agent: str,
               consume: bool) -> str | None:
        with self._lock:
            entry = self._entries.get(ref)
            if (entry is None or entry.expires <= time.monotonic()
                    or entry.task_id != task_id or entry.fingerprint != fingerprint
                    or entry.agent != agent):
                return None
            if consume:
                self._entries.pop(ref, None)
            return entry.text

    def peek(self, ref: str, *, task_id: int, fingerprint: str, agent: str) -> str | None:
        return self._value(ref, task_id=task_id, fingerprint=fingerprint,
                           agent=agent, consume=False)

    def consume(self, ref: str, *, task_id: int, fingerprint: str, agent: str) -> str | None:
        return self._value(ref, task_id=task_id, fingerprint=fingerprint,
                           agent=agent, consume=True)

    def wipe(self, ref: str) -> None:
        with self._lock:
            self._entries.pop(ref, None)


@dataclass(frozen=True)
class ObservedDialog:
    dialog: object
    frame_id: str
    loader_id: str
    document_epoch: int
    kind: str
    message: str
    default_value: str


class DialogFrameObserver:
    """Pair one Playwright dialog with one internal CDP Page event.

    A match is only evidence of the owned main frame during the armed browser
    operation. It cannot prove which page script produced the event.
    """

    def __init__(self, *, page: object) -> None:
        self.page = page
        self.root_frame_id = ''
        self.loader_id = ''
        self.frame_url = ''
        self.document_epoch = -1
        self.refused_reason = ''
        self._armed = False
        self._cdp: tuple[str, str, str] | None = None
        self._playwright: object | None = None
        self._paired: ObservedDialog | None = None
        self.ready = asyncio.Event()

    def arm(self, *, root_frame_id: str, loader_id: str,
            frame_url: str, document_epoch: int) -> None:
        if (not root_frame_id or not loader_id or not frame_url
                or type(document_epoch) is not int or document_epoch < 0):
            self.refuse('dialog_frame_unknown')
            return
        self.root_frame_id = root_frame_id
        self.loader_id = loader_id
        self.frame_url = urldefrag(frame_url).url
        self.document_epoch = document_epoch
        self.refused_reason = ''
        self._cdp = None
        self._playwright = None
        self._paired = None
        self._armed = True
        self.ready.clear()

    def refuse(self, reason: str = 'dialog_frame_unknown') -> None:
        self.refused_reason = reason
        self._armed = False
        self._cdp = None
        self._playwright = None
        self._paired = None
        self.ready.set()

    def invalidate(self) -> None:
        self.refuse('dialog_document_changed')

    def on_cdp_open(self, event: object) -> None:
        if not self._armed or self._cdp is not None or self._paired is not None:
            self.refuse()
            return
        if not isinstance(event, dict):
            self.refuse()
            return
        frame_id, url = event.get('frameId'), event.get('url')
        kind, message = event.get('type'), event.get('message')
        default = event.get('defaultPrompt', '')
        if (type(frame_id) is not str or frame_id != self.root_frame_id
                or type(url) is not str or urldefrag(url).url != self.frame_url
                or kind not in _TYPES or type(message) is not str
                or len(message) > _TEXT_LIMIT or type(default) is not str
                or len(default) > _TEXT_LIMIT):
            self.refuse()
            return
        self._cdp = (kind, message, default)
        self._try_pair()

    def on_playwright_dialog(self, dialog: object) -> None:
        if not self._armed or self._playwright is not None or self._paired is not None:
            self.refuse()
            return
        try:
            page, kind = dialog.page, dialog.type
            message, default = dialog.message, dialog.default_value
        except Exception:
            self.refuse()
            return
        if (page is not self.page or kind not in _TYPES
                or type(message) is not str or len(message) > _TEXT_LIMIT
                or type(default) is not str or len(default) > _TEXT_LIMIT):
            self.refuse()
            return
        self._playwright = dialog
        self._try_pair()

    def _try_pair(self) -> None:
        if self._cdp is None or self._playwright is None:
            return
        dialog = self._playwright
        if self._cdp != (dialog.type, dialog.message, dialog.default_value):
            self.refuse()
            return
        self._paired = ObservedDialog(
            dialog, self.root_frame_id, self.loader_id, self.document_epoch,
            dialog.type, dialog.message, dialog.default_value,
        )
        self.ready.set()

    def pending(self) -> ObservedDialog | None:
        return self._paired if self._armed and not self.refused_reason else None


async def run_with_dialog_supervisor[T](
    opening: Callable[[], Awaitable[T]], observer: DialogFrameObserver,
    respond: Callable[[ObservedDialog], Awaitable[None]],
) -> T:
    """Await the opening call in its original task and join an inert child.

    Parent completion is signalled inside the TaskGroup body, before joining
    its child; the child never waits for ``parent_task.done()``.
    """
    opening_complete = asyncio.Event()

    async def supervise() -> None:
        dialog_wait = asyncio.create_task(observer.ready.wait())
        done_wait = asyncio.create_task(opening_complete.wait())
        try:
            await asyncio.wait({dialog_wait, done_wait}, return_when=asyncio.FIRST_COMPLETED)
            pending = observer.pending()
            if pending is not None:
                await respond(pending)
            elif observer.refused_reason:
                raise DialogObservationRefused(observer.refused_reason)
        finally:
            dialog_wait.cancel()
            done_wait.cancel()
            await asyncio.gather(dialog_wait, done_wait, return_exceptions=True)

    async with asyncio.TaskGroup() as group:
        group.create_task(supervise(), context=contextvars.Context())
        try:
            result = await opening()
        finally:
            opening_complete.set()
    return result
