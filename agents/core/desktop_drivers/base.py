"""base.py — what every real desktop driver has in common.

`WindowsDesktopDriver` (``desktop_host.py``) proved the shape: observe through the
accessibility tree first, act only on a named element, and never touch pixels when
the tree can answer. This module lifts that shape so macOS and Linux drivers are
thin platform adapters rather than three parallel implementations of the same
policy — three copies of a safety rule is three chances to get it wrong.

The rules every driver inherits, none of them platform-specific:

* **Accessibility first, pixels last.** ``observe`` / ``read`` / ``locate`` answer
  from the tree. A screenshot is a separate, explicitly requested action, and the
  visual locator is a *fallback* after the tree has failed to find the element.
* **A mutation needs a named element that exists right now.** ``click`` and
  ``type`` re-snapshot and match by exact name immediately before acting, so a
  stale coordinate from an earlier turn cannot click something else.
* **Every bound is enforced here.** Element counts, name lengths, typed text and
  screenshot bytes are capped by this class, so a platform adapter cannot widen
  them by forgetting to check.
* **`requires_kernel = True`, always.** A real driver may only be reached through
  ``DesktopActionExecutor`` and the Action Kernel. The attribute is set on the
  base class rather than per driver, so a new driver cannot omit it.
* **A missing dependency is a refusal, not a crash.** Adapters raise
  :class:`DriverUnavailable` with a reason from the host-probe vocabulary; the
  base turns that into a bounded ``{"ok": False, "reason": …}``.

Nothing here imports a platform library. Adapters import theirs lazily, inside the
call that needs them, so importing this package costs nothing on a CI runner.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from agents.core.host_probe import REFUSAL_REASONS

logger = logging.getLogger("jarvis.desktop_drivers")

OBSERVE_ACTIONS = frozenset({"observe", "read", "locate", "screenshot"})
# ``key``, ``scroll`` and ``focus`` are what turn "can click a named button" into
# "can actually use the machine": without a key press there is no saving a file
# or submitting a form, and without scrolling the accessibility snapshot only
# ever sees what already happens to be on screen.
#
# ``key`` is the one mutation with no named element, which is exactly why it is
# the most constrained: the chord must come from the allowlist in ``keys.py`` and
# a chord that closes, quits, hides or switches apps is refused by policy, since
# each of those makes every later step act on something the plan never observed.
#
# ``focus`` is a mutation even though nothing visibly happens: it changes where
# the next keystroke lands, and a gate that treated it as reading would be a gate
# on the wrong half of "focus this field, then type the password".
MUTATE_ACTIONS = frozenset({"click", "type", "key", "scroll", "focus"})
SUPPORTED_ACTIONS = OBSERVE_ACTIONS | MUTATE_ACTIONS

# Actions that act on the frontmost window rather than on a named element.
UNTARGETED_ACTIONS = frozenset({"key"})

# Scrolling is bounded in both directions. "Scroll to the bottom" of an infinite
# feed is a loop with a budget attached, so the amount is always a finite number
# of notches and the cap is here rather than per adapter.
MAX_SCROLL_NOTCHES = 20
SCROLL_DIRECTIONS = frozenset({"up", "down", "left", "right"})

# Bounds. Deliberately on the base class: an adapter that forgot to check would
# otherwise be the one place a screenshot or a paste could grow without limit.
MAX_ELEMENTS = 200
MAX_NAME_CHARS = 200
MAX_TYPE_CHARS = 4_000
MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024


class DriverError(RuntimeError):
    """A bounded driver failure. ``reason`` is a public, enumerable code."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "driver_error")
        super().__init__(self.reason)


class DriverUnavailable(DriverError):
    """This host cannot offer the driver. ``reason`` is host-probe vocabulary.

    Raised at construction or first use, never mid-action: a driver that becomes
    unavailable half way through a click would leave the desktop in a state
    nothing recorded.
    """

    def __init__(self, reason: str) -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError(f"refusal outside the host-probe vocabulary: {reason!r}")
        super().__init__(reason)


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def call_host(fn: Callable[..., Any], /, *args, **kwargs) -> Any:
    """Run a host call without blocking the loop, sync or async."""
    bound_call = type(fn).__call__ if not inspect.isfunction(fn) else None
    if inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(bound_call):
        return await fn(*args, **kwargs)
    return await maybe_await(await asyncio.to_thread(fn, *args, **kwargs))


def normalize_element(raw: Mapping[str, Any] | Any, index: int) -> dict[str, Any]:
    """One accessibility element, bounded and flattened to plain JSON.

    Everything a classifier or a model will read passes through here, so this is
    where untrusted UI text stops being arbitrarily long.
    """
    def _field(name: str) -> str:
        value = (
            raw.get(name) if isinstance(raw, Mapping) else getattr(raw, name, None)
        )
        return str(value)[:MAX_NAME_CHARS] if isinstance(value, (str, int, float)) else ""

    return {
        "index": index,
        "name": _field("name"),
        "role": _field("role"),
        "value": _field("value"),
        "text": _field("text"),
        "enabled": bool(
            raw.get("enabled", True) if isinstance(raw, Mapping)
            else getattr(raw, "enabled", True)
        ),
    }


class AccessibilityDriver:
    """The shared observe/act policy. Adapters implement the four seams below.

    A subclass provides:
      * ``_elements()`` → a sequence of ``(normalized_dict, native_handle)``
      * ``_click(handle)`` / ``_type(handle, text)``
      * ``_screenshot()`` → PNG bytes
    and may raise :class:`DriverUnavailable` from any of them.
    """

    # Set here, not per driver: a new adapter cannot forget it and thereby take
    # the legacy direct path that skips the kernel.
    requires_kernel = True
    platform = "unknown"

    def __init__(self, *, locator: Any = None, max_type_chars: int = MAX_TYPE_CHARS) -> None:
        self._locator = locator
        self.max_type_chars = max(1, min(int(max_type_chars), MAX_TYPE_CHARS))

    # ── the entry point ──────────────────────────────────────────────────

    async def perform(self, action: str, args: Mapping[str, Any]) -> dict[str, Any]:
        """One governed step. Never raises: a failure is a bounded refusal."""
        act = str(action or "").strip().lower()
        if act not in SUPPORTED_ACTIONS:
            return {"ok": False, "reason": "unsupported_action", "action": act}
        params = dict(args or {})
        try:
            if act == "screenshot":
                return await self._do_screenshot()
            if act in OBSERVE_ACTIONS:
                return await self._do_observe(act, params)
            return await self._do_mutate(act, params)
        except DriverUnavailable as exc:
            return {"ok": False, "reason": exc.reason, "action": act}
        except DriverError as exc:
            return {"ok": False, "reason": exc.reason, "action": act}
        except Exception:
            # Host exception text can carry window titles and paths; never surface it.
            logger.warning("desktop driver step failed: %s", act, exc_info=True)
            return {"ok": False, "reason": "driver_error", "action": act}

    # ── observing ────────────────────────────────────────────────────────

    async def _snapshot(self) -> tuple[list[tuple[dict, Any]], bool]:
        raw = await maybe_await(self._elements())
        rows = list(raw or ())
        truncated = len(rows) > MAX_ELEMENTS
        out: list[tuple[dict, Any]] = []
        for index, item in enumerate(rows[:MAX_ELEMENTS]):
            normalized, handle = item if isinstance(item, tuple) else (item, item)
            out.append((normalize_element(normalized, index), handle))
        return out, truncated

    async def _do_observe(self, action: str, args: Mapping[str, Any]) -> dict[str, Any]:
        snapshot, truncated = await self._snapshot()
        if action == "observe":
            return {
                "ok": True, "source": "accessibility", "platform": self.platform,
                "elements": [row for row, _handle in snapshot], "truncated": truncated,
            }
        query = str(args.get("query") or "").strip()[:MAX_NAME_CHARS]
        if not query:
            return {"ok": False, "reason": "query_required"}
        match = find_element(snapshot, query, exact=False)
        if match is not None:
            row, _handle = match
            if action == "read":
                return {
                    "ok": True, "source": "accessibility",
                    "text": row.get("value") or row.get("text") or row.get("name", ""),
                    "element": row,
                }
            return {"ok": True, "source": "accessibility", "element": row}
        if action == "read":
            return {"ok": False, "reason": "not_found"}
        # Only now — the tree could not answer — is the visual fallback allowed.
        return await self._locate_visually(query)

    async def _locate_visually(self, query: str) -> dict[str, Any]:
        """Ask the screen locator, and only if it is provably local.

        A cloud vision model here would ship the owner's screen off the box, so a
        locator that cannot prove it resolves to loopback is refused by name
        rather than quietly used.
        """
        if self._locator is None:
            return {"ok": False, "reason": "not_found", "source": "accessibility"}
        if not bool(getattr(self._locator, "proven_local", False)):
            return {"ok": False, "reason": "local_vlm_not_proven_local"}
        image = await self._capped_screenshot()
        result = await maybe_await(self._locator.locate(query, image))
        if not isinstance(result, Mapping) or not result.get("ok"):
            return {"ok": False, "reason": "not_found", "source": "visual"}
        point = result.get("point")
        if (not isinstance(point, Sequence) or isinstance(point, (str, bytes))
                or len(point) != 2):
            return {"ok": False, "reason": "invalid_locator_result"}
        return {
            "ok": True, "source": "visual", "platform": self.platform,
            "point": [int(point[0]), int(point[1])],
            "confidence": float(result.get("confidence") or 0.0),
        }

    async def _do_screenshot(self) -> dict[str, Any]:
        image = await self._capped_screenshot()
        return {
            "ok": True, "source": "screenshot", "platform": self.platform,
            "mime": "image/png", "bytes": len(image),
            "image_base64": base64.b64encode(image).decode("ascii"),
        }

    async def _capped_screenshot(self) -> bytes:
        image = await maybe_await(self._screenshot())
        if not isinstance(image, (bytes, bytearray)):
            raise DriverError("screenshot_failed")
        if len(image) > MAX_SCREENSHOT_BYTES:
            raise DriverError("screenshot_too_large")
        return bytes(image)

    # ── acting ───────────────────────────────────────────────────────────

    async def _do_mutate(self, action: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if action == "key":
            return await self._do_key(args)
        name = str(args.get("name") or "").strip()
        if not name:
            return {"ok": False, "reason": "named_element_required"}
        if len(name) > MAX_NAME_CHARS:
            return {"ok": False, "reason": "element_name_too_large"}
        text = ""
        if action == "type":
            raw = args.get("text")
            if not isinstance(raw, str):
                return {"ok": False, "reason": "text_required"}
            if len(raw) > self.max_type_chars:
                return {"ok": False, "reason": "text_too_large"}
            text = raw

        direction = ""
        notches = 0
        if action == "scroll":
            direction = str(args.get("direction") or "").strip().lower()
            if direction not in SCROLL_DIRECTIONS:
                return {"ok": False, "reason": "scroll_direction_required"}
            raw_notches = args.get("notches", 3)
            if isinstance(raw_notches, bool) or not isinstance(raw_notches, int):
                return {"ok": False, "reason": "scroll_notches_invalid"}
            if raw_notches < 1 or raw_notches > MAX_SCROLL_NOTCHES:
                # Refused rather than clamped: a step that asked for 500 notches
                # meant something different from one that asked for 20, and
                # silently doing the smaller thing hides that the plan was wrong.
                return {"ok": False, "reason": "scroll_notches_out_of_range"}
            notches = int(raw_notches)

        # Re-snapshot immediately before acting. A handle from an earlier turn may
        # now point at a different control, so a stale match must not be reused.
        snapshot, _truncated = await self._snapshot()
        match = find_element(snapshot, name, exact=True)
        if match is None:
            return {"ok": False, "reason": "element_not_found"}
        row, handle = match
        if not row.get("enabled", True):
            return {"ok": False, "reason": "element_disabled"}
        if action == "click":
            await maybe_await(self._click(handle))
        elif action == "focus":
            await maybe_await(self._focus(handle))
        elif action == "scroll":
            await maybe_await(self._scroll(handle, direction, notches))
        else:
            await maybe_await(self._type(handle, text))
        result = {"ok": True, "action": action, "platform": self.platform,
                  "element": row.get("name", "")}
        if action == "scroll":
            result["direction"] = direction
            result["notches"] = notches
        return result

    async def _do_key(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Press one allowlisted chord on the frontmost window.

        Deliberately has no element target and therefore no re-snapshot: there is
        nothing to match against. That is what makes the allowlist the whole of
        the safety story here, and why it refuses rather than falls back. There is
        no keycode path: a card that says "press Cmd+S" has a bounded set of
        meanings, and one that says "send keycode 0x1F" has none a person can check.
        """
        from agents.core.desktop_drivers.keys import KeyRefused, canonical_chord

        try:
            chord = canonical_chord(args.get("chord") or args.get("key") or "")
        except KeyRefused as exc:
            return {"ok": False, "reason": exc.reason, "action": "key",
                    "detail": exc.detail[:200]}
        await maybe_await(self._key(chord))
        return {"ok": True, "action": "key", "platform": self.platform, "chord": chord}

    # ── seams an adapter implements ──────────────────────────────────────

    def _elements(self) -> Any:  # pragma: no cover - abstract
        raise DriverUnavailable("desktop_dependency_unavailable")

    def _click(self, handle: Any) -> Any:  # pragma: no cover - abstract
        raise DriverUnavailable("desktop_dependency_unavailable")

    def _type(self, handle: Any, text: str) -> Any:  # pragma: no cover - abstract
        raise DriverUnavailable("desktop_dependency_unavailable")

    def _screenshot(self) -> Any:  # pragma: no cover - abstract
        raise DriverUnavailable("wayland_capture_unavailable")

    # These three default to "this adapter cannot" rather than being abstract: an
    # existing adapter keeps working unchanged and reports honestly on the actions
    # it has not implemented, instead of every adapter breaking the day the
    # vocabulary grew.
    #
    # DriverError, not DriverUnavailable: "this adapter has not implemented
    # scroll" is a fact about the adapter, while DriverUnavailable's vocabulary is
    # the host probe's — reasons a person can act on by changing their machine.
    # Borrowing that vocabulary here would tell the owner their host cannot do
    # something when the truth is that nobody wrote the code.
    def _key(self, chord: str) -> Any:
        raise DriverError("desktop_key_unsupported")

    def _scroll(self, handle: Any, direction: str, notches: int) -> Any:
        raise DriverError("desktop_scroll_unsupported")

    def _focus(self, handle: Any) -> Any:
        raise DriverError("desktop_focus_unsupported")


class UnavailableDriver:
    """Stands in when this host has no usable driver, and refuses every step.

    NOT a null driver: a null one records a step and answers "deferred", which
    reads like the work is pending. This one answers the host probe's own reason
    every time, so a caller learns *why* the desktop cannot be driven at the same
    place it would have learned that a step failed.

    It still carries ``requires_kernel``, so the ordering the product promises is
    preserved: the posture flags (`JARVIS_UNIFIED_ACTION_API`,
    `JARVIS_ACTION_KERNEL`) are checked by the executor BEFORE this driver is
    reached. The owner therefore sees "the feature is off" before "your machine
    cannot do it" — which is the right order, because turning it on is their
    first step and the host question only matters afterwards.
    """

    requires_kernel = True

    def __init__(self, reason: str, *, hint: str = "", platform: str = "") -> None:
        self.reason = str(reason or "desktop_platform_unsupported")
        self.hint = str(hint or "")
        self.platform = str(platform or "")

    async def perform(self, action: str, args: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "ok": False, "reason": self.reason, "hint": self.hint,
            "platform": self.platform, "action": str(action or ""),
        }


def find_element(
    snapshot: Sequence[tuple[dict, Any]], query: str, *, exact: bool
) -> tuple[dict, Any] | None:
    """Match by name, then by role/text. ``exact`` is required for a mutation.

    Exactness matters: a substring match is fine for "where is the Save button",
    and dangerous for "click Save" when the screen also holds "Save and delete".
    """
    needle = query.strip().lower()
    if not needle:
        return None
    for row, handle in snapshot:
        if row.get("name", "").strip().lower() == needle:
            return row, handle
    if exact:
        return None
    for row, handle in snapshot:
        haystack = " ".join(
            str(row.get(key, "")) for key in ("name", "role", "value", "text")
        ).lower()
        if needle in haystack:
            return row, handle
    return None


__all__ = [
    "MAX_ELEMENTS",
    "MAX_NAME_CHARS",
    "MAX_SCREENSHOT_BYTES",
    "MAX_TYPE_CHARS",
    "MUTATE_ACTIONS",
    "MAX_SCROLL_NOTCHES",
    "OBSERVE_ACTIONS",
    "SCROLL_DIRECTIONS",
    "UNTARGETED_ACTIONS",
    "SUPPORTED_ACTIONS",
    "AccessibilityDriver",
    "DriverError",
    "DriverUnavailable",
    "UnavailableDriver",
    "call_host",
    "find_element",
    "maybe_await",
    "normalize_element",
]
