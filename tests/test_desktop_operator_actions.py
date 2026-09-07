"""The actions that turn "can click a named button" into "can use the machine".

Clicking and typing by exact element name is not enough to do work: without a key
press there is no saving a file or submitting a form, and without scrolling the
accessibility snapshot only ever sees what already happens to be on screen.

`key` is the interesting one, and every test about it comes from the same fact:
it is the ONLY mutation with no named element. `Cmd+S` acts on whatever is
frontmost, so the owner reading the approval card cannot see from the step what
it will touch. That is why the chord comes from a finite allowlist, why there is
no keycode passthrough, and why chords that quit / close / hide / switch apps are
refused BY POLICY — each of those makes every later step act on something the
plan never observed.

Hermetic: a fake adapter recording what reached each seam. No AT-SPI, no Quartz,
no host.
"""

from __future__ import annotations

import pytest

from agents.core.desktop_drivers.base import (
    MAX_SCROLL_NOTCHES,
    MUTATE_ACTIONS,
    OBSERVE_ACTIONS,
    SCROLL_DIRECTIONS,
    SUPPORTED_ACTIONS,
    AccessibilityDriver,
    DriverError,
    DriverUnavailable,
)
from agents.core.desktop_drivers.keys import (
    ALLOWED_KEYS,
    MAX_MODIFIERS,
    REFUSED_CHORDS,
    KeyRefused,
    canonical_chord,
    describe_chord,
    parse_chord,
)

pytestmark = pytest.mark.asyncio


class _Driver(AccessibilityDriver):
    """One button and one text field, plus a record of what each seam got."""

    platform = "test"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.pressed: list[str] = []
        self.scrolled: list[tuple[str, int]] = []
        self.focused: list[str] = []
        self.clicked: list[str] = []
        self.typed: list[tuple[str, str]] = []

    def _elements(self):
        return [
            ({"name": "Save", "role": "button", "enabled": True}, "h-save"),
            ({"name": "Title", "role": "text", "enabled": True}, "h-title"),
            ({"name": "Greyed", "role": "button", "enabled": False}, "h-grey"),
        ]

    def _click(self, handle):
        self.clicked.append(handle)

    def _type(self, handle, text):
        self.typed.append((handle, text))

    def _screenshot(self):
        return b"\x89PNG"

    def _key(self, chord):
        self.pressed.append(chord)

    def _scroll(self, handle, direction, notches):
        self.scrolled.append((direction, notches))

    def _focus(self, handle):
        self.focused.append(handle)


class _Bare(_Driver):
    """An adapter written before the vocabulary grew. It must keep working."""

    _key = AccessibilityDriver._key
    _scroll = AccessibilityDriver._scroll
    _focus = AccessibilityDriver._focus


# ── the vocabulary ───────────────────────────────────────────────────────────

def test_the_new_actions_are_all_mutations():
    """`focus` looks like reading and is not: it changes where the next keystroke
    lands, so a gate that treated it as a read would gate the wrong half of
    "focus this field, then type the password"."""
    for action in ("key", "scroll", "focus"):
        assert action in MUTATE_ACTIONS
        assert action not in OBSERVE_ACTIONS


def test_the_desktop_operator_already_treats_them_as_tier_two():
    from agents.core.desktop_operator import GovernedDesktop

    for action in ("key", "scroll", "focus"):
        assert GovernedDesktop.is_mutating(action) is True


async def test_an_unknown_action_is_still_refused_by_name():
    result = await _Driver().perform("teleport", {})
    assert result == {"ok": False, "reason": "unsupported_action", "action": "teleport"}
    assert "teleport" not in SUPPORTED_ACTIONS


# ── key: an allowlist, never a passthrough ───────────────────────────────────

async def test_an_allowlisted_chord_is_pressed_in_its_canonical_spelling():
    driver = _Driver()
    result = await driver.perform("key", {"chord": "Cmd+Shift+S"})
    assert result["ok"] is True
    assert result["chord"] == "cmd+shift+s"
    assert driver.pressed == ["cmd+shift+s"]


@pytest.mark.parametrize(
    ("spelling", "canonical"),
    [("cmd+s", "cmd+s"), ("command+s", "cmd+s"), ("meta+s", "cmd+s"),
     ("super+s", "cmd+s"), ("win+s", "cmd+s"), ("CTRL+C", "ctrl+c"),
     ("option+a", "alt+a"), ("Control+Shift+P", "ctrl+shift+p")],
)
async def test_modifier_synonyms_canonicalise_to_one_spelling(spelling, canonical):
    """A chord allowlisted under one spelling and refused under another is a gate
    with a hole in it shaped exactly like a synonym."""
    assert canonical_chord(spelling) == canonical


@pytest.mark.parametrize("chord", sorted(REFUSED_CHORDS))
async def test_a_chord_refused_by_policy_is_never_pressed(chord):
    """These all work perfectly. That is the problem: quitting the app the owner
    was using is the plan failing, not a step in it."""
    driver = _Driver()
    result = await driver.perform("key", {"chord": chord})
    assert result["ok"] is False
    assert result["reason"] == "chord_refused_by_policy"
    assert driver.pressed == []


async def test_a_policy_refusal_says_why_rather_than_unsupported():
    """"Unsupported" invites somebody to add support. A reason can be argued with."""
    result = await _Driver().perform("key", {"chord": "cmd+q"})
    assert "the plan failing" in result["detail"]


@pytest.mark.parametrize(
    ("chord", "reason"),
    [
        ("", "no_key"),
        ("cmd+", "no_base_key"),
        ("cmd+shift", "no_base_key"),
        ("hyper+s", "unknown_modifier"),
        ("cmd+shift+alt+ctrl+s", "too_many_modifiers"),
        ("cmd+eject", "key_not_allowed"),
        ("0x1f", "key_not_allowed"),
        ("x" * 100, "key_too_long"),
    ],
)
async def test_a_chord_outside_the_allowlist_is_refused_by_name(chord, reason):
    driver = _Driver()
    result = await driver.perform("key", {"chord": chord})
    assert result["ok"] is False
    assert result["reason"] == reason
    assert driver.pressed == []


async def test_there_is_no_keycode_passthrough():
    """A card that says "press Cmd+S" has a bounded set of meanings. A card that
    says "send keycode 0x1F" has none the owner can check."""
    for attempt in ({"keycode": 31}, {"scancode": "0x1f"}, {"raw": "\\x1b[A"}):
        result = await _Driver().perform("key", attempt)
        assert result["ok"] is False
        assert result["reason"] == "no_key"


async def test_a_trailing_modifier_never_leaves_one_stuck_down():
    """"cmd+" does nothing and, pressed, leaves a modifier held for every key the
    owner presses afterwards."""
    with pytest.raises(KeyRefused) as exc:
        parse_chord("cmd+")
    assert exc.value.reason == "no_base_key"


async def test_a_chord_is_one_step_never_a_sequence():
    """Eleven Tabs is eleven steps against eleven budget entries. Folding them
    into one hides how much a plan is actually doing."""
    for attempt in ("tab tab", "cmd+s,cmd+w", "tab;tab"):
        assert (await _Driver().perform("key", {"chord": attempt}))["ok"] is False


async def test_the_key_alias_is_accepted_because_a_caller_will_use_it():
    driver = _Driver()
    assert (await driver.perform("key", {"key": "enter"}))["ok"] is True
    assert driver.pressed == ["enter"]


async def test_at_most_three_modifiers():
    assert MAX_MODIFIERS == 3
    assert canonical_chord("cmd+shift+alt+p") == "alt+cmd+shift+p"


async def test_every_allowed_key_actually_parses():
    """An allowlist with an entry that cannot be parsed is a promise the code
    does not keep."""
    for key in sorted(ALLOWED_KEYS):
        assert parse_chord(key)[1] == key


async def test_describe_never_raises_because_a_card_must_render():
    assert describe_chord("cmd+q").startswith("cmd+q (refused:")
    assert describe_chord("") .startswith(" (refused:") or "refused" in describe_chord("")
    assert describe_chord("cmd+s") == "cmd+s"


# ── scroll: bounded in both directions ───────────────────────────────────────

async def test_scrolling_a_named_element_records_direction_and_amount():
    driver = _Driver()
    result = await driver.perform("scroll", {"name": "Save", "direction": "down", "notches": 5})
    assert result["ok"] is True
    assert (result["direction"], result["notches"]) == ("down", 5)
    assert driver.scrolled == [("down", 5)]


async def test_scrolling_defaults_to_a_small_amount():
    driver = _Driver()
    await driver.perform("scroll", {"name": "Save", "direction": "down"})
    assert driver.scrolled == [("down", 3)]


@pytest.mark.parametrize("notches", [0, -1, MAX_SCROLL_NOTCHES + 1, 500])
async def test_an_out_of_range_scroll_is_refused_not_clamped(notches):
    """A step that asked for 500 notches meant something different from one that
    asked for 20; silently doing the smaller thing hides that the plan was wrong."""
    driver = _Driver()
    result = await driver.perform(
        "scroll", {"name": "Save", "direction": "down", "notches": notches}
    )
    assert result["reason"] == "scroll_notches_out_of_range"
    assert driver.scrolled == []


@pytest.mark.parametrize("notches", [True, "3", 3.5, None])
async def test_a_scroll_amount_that_is_not_a_whole_number_is_refused(notches):
    driver = _Driver()
    result = await driver.perform(
        "scroll", {"name": "Save", "direction": "down", "notches": notches}
    )
    assert result["reason"] == "scroll_notches_invalid"
    assert driver.scrolled == []


@pytest.mark.parametrize("direction", ["", "sideways", "to the bottom", "DOWNWARD"])
async def test_an_unknown_scroll_direction_is_refused(direction):
    result = await _Driver().perform("scroll", {"name": "Save", "direction": direction})
    assert result["reason"] == "scroll_direction_required"


async def test_the_scroll_directions_are_the_four_a_person_would_name():
    assert frozenset({"up", "down", "left", "right"}) == SCROLL_DIRECTIONS


async def test_scrolling_still_needs_a_named_element():
    result = await _Driver().perform("scroll", {"direction": "down"})
    assert result["reason"] == "named_element_required"


# ── focus ────────────────────────────────────────────────────────────────────

async def test_focusing_is_not_clicking():
    """On a control that acts on press, a click to focus also does the thing."""
    driver = _Driver()
    assert (await driver.perform("focus", {"name": "Title"}))["ok"] is True
    assert driver.focused == ["h-title"]
    assert driver.clicked == []


async def test_focusing_a_disabled_element_is_refused_like_any_mutation():
    result = await _Driver().perform("focus", {"name": "Greyed"})
    assert result["reason"] == "element_disabled"


async def test_focusing_re_snapshots_and_matches_by_exact_name():
    result = await _Driver().perform("focus", {"name": "Titl"})
    assert result["reason"] == "element_not_found"


# ── an adapter written before the vocabulary grew ────────────────────────────

@pytest.mark.parametrize(
    ("action", "args", "reason"),
    [
        ("key", {"chord": "cmd+s"}, "desktop_key_unsupported"),
        ("scroll", {"name": "Save", "direction": "down"}, "desktop_scroll_unsupported"),
        ("focus", {"name": "Save"}, "desktop_focus_unsupported"),
    ],
)
async def test_an_older_adapter_reports_honestly_instead_of_breaking(action, args, reason):
    """The seams default to "this adapter cannot" rather than being abstract, so
    growing the vocabulary does not break every adapter on the day it grows."""
    result = await _Bare().perform(action, args)
    assert result == {"ok": False, "reason": reason, "action": action}


async def test_an_older_adapter_still_clicks_and_types():
    driver = _Bare()
    assert (await driver.perform("click", {"name": "Save"}))["ok"] is True
    assert (await driver.perform("type", {"name": "Title", "text": "hi"}))["ok"] is True


# ── failures stay bounded ────────────────────────────────────────────────────

async def test_a_seam_that_raises_never_surfaces_host_text():
    """Host exception text carries window titles and file paths."""

    class _Leaky(_Driver):
        def _key(self, chord):
            raise RuntimeError("failed pressing in /Users/andrei/Private/taxes.xlsx")

    result = await _Leaky().perform("key", {"chord": "cmd+s"})
    assert result == {"ok": False, "reason": "driver_error", "action": "key"}
    assert "taxes" not in str(result)


async def test_a_named_driver_error_keeps_its_name():
    class _Mapped(_Driver):
        def _key(self, chord):
            raise DriverError("key_not_mapped")

    assert (await _Mapped().perform("key", {"chord": "f7"}))["reason"] == "key_not_mapped"


async def test_an_unavailable_dependency_keeps_its_reason():
    """A missing Quartz/pyatspi is a HOST fact, and the closed host-probe
    vocabulary already has the word for it — widening that set for a synonym
    would give the owner two hints for one problem."""
    class _NoDep(_Driver):
        def _scroll(self, handle, direction, notches):
            raise DriverUnavailable("desktop_dependency_unavailable")

    result = await _NoDep().perform("scroll", {"name": "Save", "direction": "up"})
    assert result["reason"] == "desktop_dependency_unavailable"


async def test_an_adapter_gap_is_never_reported_as_a_host_problem():
    """"This adapter has not implemented scroll" and "your machine cannot scroll"
    are different facts. Only the second is something the owner can act on."""
    from agents.core.host_probe import REFUSAL_REASONS

    result = await _Bare().perform("scroll", {"name": "Save", "direction": "down"})
    assert result["reason"] not in REFUSAL_REASONS


# ── the platform keycode tables ──────────────────────────────────────────────

def test_every_allowed_key_has_a_macos_keycode():
    """A key that parses but has no code would be refused at runtime on a real
    Mac — better to find that here than in front of an owner."""
    from agents.core.desktop_drivers.macos import _MAC_KEYCODES

    assert not (ALLOWED_KEYS - set(_MAC_KEYCODES))


def test_every_allowed_key_has_an_x_keysym():
    from agents.core.desktop_drivers.linux import _X_KEYSYMS

    assert not (ALLOWED_KEYS - set(_X_KEYSYMS))


def test_every_canonical_modifier_maps_on_both_platforms():
    from agents.core.desktop_drivers.keys import MODIFIERS
    from agents.core.desktop_drivers.linux import _X_MODIFIER_KEYSYMS
    from agents.core.desktop_drivers.macos import _MAC_MODIFIER_FLAGS

    canonical = set(MODIFIERS.values())
    assert canonical <= set(_MAC_MODIFIER_FLAGS)
    assert canonical <= set(_X_MODIFIER_KEYSYMS)


def test_the_mac_scroll_vectors_cover_every_direction():
    from agents.core.desktop_drivers.macos import _SCROLL_VECTORS

    assert set(_SCROLL_VECTORS) == set(SCROLL_DIRECTIONS)


def test_the_linux_scroll_table_covers_every_direction():
    from agents.core.desktop_drivers.linux import _ATSPI_SCROLL

    assert set(_ATSPI_SCROLL) == set(SCROLL_DIRECTIONS)


# ── all three platforms answer to the same vocabulary ────────────────────────

def test_windows_accepts_the_same_mutations_as_the_cross_platform_base():
    """A plan that works on macOS and silently does nothing on Windows is worse
    than one that refuses on both, because only the owner finds out."""
    from agents.core.desktop_host import _MUTATE_ACTIONS as WINDOWS_MUTATIONS

    missing = MUTATE_ACTIONS - WINDOWS_MUTATIONS
    assert not missing, f"Windows cannot do: {sorted(missing)}"


def test_windows_observations_match_too():
    from agents.core.desktop_host import _OBSERVE_ACTIONS as WINDOWS_OBSERVE

    assert WINDOWS_OBSERVE == OBSERVE_ACTIONS


def test_the_one_windows_only_action_is_named_deliberately():
    """`launch` has no cross-platform twin yet. Pinned so it stays a decision
    rather than becoming an unnoticed second asymmetry."""
    from agents.core.desktop_host import _MUTATE_ACTIONS as WINDOWS_MUTATIONS

    assert sorted(WINDOWS_MUTATIONS - MUTATE_ACTIONS) == ["launch"]


def test_windows_shares_the_one_chord_allowlist():
    """A chord refused on one platform and pressed on another would make the
    policy a per-platform accident instead of a decision."""
    from agents.core.desktop_host import _PYWINAUTO_KEYS, _pywinauto_chord

    for key in sorted(ALLOWED_KEYS):
        assert _pywinauto_chord(key)  # every allowlisted key translates
    assert set(_PYWINAUTO_KEYS) >= (ALLOWED_KEYS - set("abcdefghijklmnopqrstuvwxyz0123456789"))


def test_windows_bounds_match_the_cross_platform_ones():
    from agents.core.desktop_host import _MAX_SCROLL_NOTCHES, _SCROLL_DIRECTIONS

    assert _MAX_SCROLL_NOTCHES == MAX_SCROLL_NOTCHES
    assert _SCROLL_DIRECTIONS == SCROLL_DIRECTIONS


@pytest.mark.parametrize(
    ("chord", "expected"),
    [
        ("ctrl+c", "^c"),
        ("alt+f5", "%{F5}"),
        ("ctrl+shift+p", "^+p"),
        ("enter", "{ENTER}"),
        ("a", "a"),
    ],
)
def test_a_chord_translates_to_pywinauto_syntax(chord, expected):
    from agents.core.desktop_host import _pywinauto_chord

    assert _pywinauto_chord(chord) == expected


def test_the_win_key_is_held_and_released_rather_than_tapped():
    """`{VK_LWIN}` on its own presses AND releases, so a naive prefix would tap
    Win and then send the rest without it — a different chord than the card named."""
    from agents.core.desktop_host import _pywinauto_chord

    assert _pywinauto_chord("cmd+s") == "{VK_LWIN down}s{VK_LWIN up}"
    assert _pywinauto_chord("cmd+shift+s") == "{VK_LWIN down}+s{VK_LWIN up}"


def test_windows_refuses_a_policy_chord_before_reaching_a_backend():
    import asyncio

    from agents.core.desktop_host import WindowsDesktopDriver

    class _Backend:
        def __init__(self):
            self.pressed = []

        def accessibility_elements(self):
            return []

        def key(self, chord):
            self.pressed.append(chord)

    backend = _Backend()
    driver = WindowsDesktopDriver(
        host_enabled=True, isolated=True, backend_factory=lambda: backend
    )
    result = asyncio.run(driver.perform("key", {"chord": "cmd+q"}))
    assert result["reason"] == "chord_refused_by_policy"
    assert backend.pressed == []


def test_windows_reports_a_backend_gap_as_a_backend_gap():
    import asyncio

    from agents.core.desktop_host import WindowsDesktopDriver
    from agents.core.host_probe import REFUSAL_REASONS

    class _Old:
        def accessibility_elements(self):
            return []

    driver = WindowsDesktopDriver(
        host_enabled=True, isolated=True, backend_factory=_Old
    )
    result = asyncio.run(driver.perform("key", {"chord": "ctrl+s"}))
    assert result["reason"] == "desktop_key_unsupported"
    assert result["reason"] not in REFUSAL_REASONS
