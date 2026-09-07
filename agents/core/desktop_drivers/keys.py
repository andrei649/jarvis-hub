"""keys.py — what a governed key press is allowed to be.

Typing text has an obvious target: the control it goes into. A key press does
not. `Cmd+S` acts on whatever is frontmost, and that is exactly what makes it the
most dangerous action in the operator's vocabulary — it is the only one where the
owner reading the approval card cannot see, from the step alone, what it will
touch. Every rule below follows from that.

* **An allowlist, never a passthrough.** A finite, enumerable set of named keys
  and chords. There is no raw keycode, no scancode, no "send this string to the
  OS". A card that says "press Cmd+S" has a bounded set of meanings; a card that
  says "send keycode 0x1F" has none the owner can check.
* **Some chords are refused by policy, not by omission.** `Cmd+Q`, `Alt+F4`,
  `Ctrl+Alt+Del`, `Cmd+Shift+Q` and their relatives all work perfectly — that is
  the problem. Quitting the app the owner was using, or locking their machine, is
  never a step in a plan; it is the plan having failed. They are named here with
  a reason, so a refusal reads as a decision rather than a gap somebody will
  helpfully fill in later.
* **One chord, one step.** No sequences, no repeat counts. "Press Tab eleven
  times" is eleven steps against eleven budget entries, which is the honest
  accounting; folding it into one hides how much a plan is actually doing.
* **Modifiers are canonical.** `cmd`/`command`/`meta`/`super` are the same
  modifier under different names on different platforms, and normalising them
  here is what stops the same chord being allowlisted under one spelling and
  refused under another.

The adapter still has to implement the press. This module only decides what may
be asked for.
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = [
    "ALLOWED_KEYS",
    "MAX_MODIFIERS",
    "MODIFIERS",
    "REFUSED_CHORDS",
    "KeyRefused",
    "canonical_chord",
    "describe_chord",
    "parse_chord",
]

# Modifier spellings that mean the same physical key. Platforms disagree, and a
# chord allowlisted under one spelling and refused under another would be a gate
# with a hole in it shaped exactly like a synonym.
MODIFIERS: Mapping[str, str] = {
    "cmd": "cmd", "command": "cmd", "meta": "cmd", "super": "cmd", "win": "cmd",
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "option": "alt", "opt": "alt",
    "shift": "shift",
}

# The base keys a step may name. Letters and digits are included because the
# useful chords are Cmd+S / Ctrl+C / Cmd+1; bare letters are how a keyboard
# shortcut in a web app is triggered. Anything not here is refused by name.
_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyz")
_DIGITS = frozenset("0123456789")
_NAMED = frozenset({
    "enter", "return", "tab", "escape", "space", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
})
ALLOWED_KEYS = _LETTERS | _DIGITS | _NAMED

# At most this many modifiers. Three is every real shortcut (Cmd+Shift+P); more
# is a sign the caller is enumerating chords rather than naming one.
MAX_MODIFIERS = 3

# Chords refused because of what they DO, not because nobody implemented them.
# Each maps to the sentence a refusal should say — a reason a person can argue
# with beats "unsupported", which invites someone to add support.
#
# Written here in the order a person says them ("ctrl+alt+delete"), and
# normalised at import to the same canonical form lookups use. Writing them by
# hand in canonical order would be exactly the hole the canonicaliser exists to
# close: a chord refused under one spelling and pressed under another. The guard
# below proves every entry is expressible, so a typo fails at import rather than
# at 3am on the owner's machine.
_REFUSED_SOURCE: Mapping[str, str] = {
    "cmd+q": "quitting the frontmost app is the plan failing, not a step in it",
    "cmd+shift+q": "logging the owner out is never a step in a plan",
    "alt+f4": "closing the frontmost window is the plan failing, not a step in it",
    "ctrl+alt+delete": "the OS security screen is the owner's, not an operator's",
    "cmd+alt+escape": "force-quit is a recovery tool for a person, not a step",
    "ctrl+shift+escape": "the task manager is a recovery tool for a person",
    "cmd+ctrl+q": "locking the machine ends the owner's session mid-work",
    "cmd+space": "the system launcher opens a surface nothing here can observe",
    "cmd+tab": "switching apps changes what every later step targets, unobserved",
    "alt+tab": "switching apps changes what every later step targets, unobserved",
    "cmd+h": "hiding the frontmost app leaves later steps acting on something else",
    "cmd+m": "minimising leaves later steps acting on something else",
    "cmd+w": "closing the window discards what the plan was working in",
    "ctrl+w": "closing the window discards what the plan was working in",
}


class KeyRefused(ValueError):
    """A chord that will not be pressed, and the reason it will not be."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = str(reason)
        self.detail = str(detail or "")
        super().__init__(self.detail or self.reason)


def parse_chord(chord: str) -> tuple[tuple[str, ...], str]:
    """Split ``"Cmd+Shift+S"`` into canonical modifiers and a base key.

    Raises :class:`KeyRefused` with a named reason rather than returning a
    sentinel: a caller that forgot to check a sentinel would press something.
    """
    raw = str(chord or "").strip().lower()
    if not raw:
        raise KeyRefused("no_key", "a key press must name a key")
    if len(raw) > 64:
        raise KeyRefused("key_too_long", "a chord that long is not a chord")
    parts = [p.strip() for p in raw.split("+") if p.strip()]
    if not parts:
        raise KeyRefused("no_key", "a key press must name a key")

    *mod_parts, base = parts
    mods: list[str] = []
    for part in mod_parts:
        canon = MODIFIERS.get(part)
        if canon is None:
            raise KeyRefused("unknown_modifier", f"{part!r} is not a modifier")
        if canon not in mods:
            mods.append(canon)
    if len(mods) > MAX_MODIFIERS:
        raise KeyRefused("too_many_modifiers", f"at most {MAX_MODIFIERS} modifiers")

    # A trailing modifier with no base key ("cmd+") is a chord that does nothing
    # and, pressed, leaves a modifier stuck down.
    if base in MODIFIERS:
        raise KeyRefused("no_base_key", "a chord needs a key, not only modifiers")
    if base not in ALLOWED_KEYS:
        raise KeyRefused("key_not_allowed", f"{base!r} is not in the allowed set")
    return tuple(sorted(mods)), base


def _canonical_form(chord: str) -> str:
    """The canonical spelling, with no policy check — used to build the table."""
    mods, base = parse_chord(chord)
    return "+".join([*mods, base])


def _normalise_refusals() -> dict[str, str]:
    """The refusal table, keyed the way lookups key it.

    Raises at import if an entry cannot be expressed at all: a policy refusal
    that silently never matches is worse than no refusal, because it reads as
    protection that is not there.
    """
    table: dict[str, str] = {}
    for chord, reason in _REFUSED_SOURCE.items():
        table[_canonical_form(chord)] = reason
    return table


REFUSED_CHORDS: Mapping[str, str] = _normalise_refusals()


def canonical_chord(chord: str) -> str:
    """The one spelling of a chord. Refuses anything the policy will not press."""
    canon = _canonical_form(chord)
    reason = REFUSED_CHORDS.get(canon)
    if reason is not None:
        raise KeyRefused("chord_refused_by_policy", reason)
    return canon


def describe_chord(chord: str) -> str:
    """What the approval card says. Never raises — a card must render.

    A chord that will be refused still describes itself, because the card is also
    where a person reads *why* something did not happen.
    """
    try:
        return canonical_chord(chord)
    except KeyRefused as exc:
        return f"{str(chord or '').strip().lower()} (refused: {exc.reason})"
