"""H672 — the compaction commit as the one safe migration point for a live session.

Nerva's autonomy story is sessions that do not end, and today enabling a plugin
or approving a capability changes nothing in a conversation already running. The
boundary already exists; it just was not used.

The security half is the half that matters. A refresh that only ADDS would mean
a capability revoked mid-session stays live in every running conversation —
strictly worse than today's "nothing changes until restart". Most of these tests
are about removal.
"""

from agents.core.session_refresh import (
    boundary_note,
    refresh_prompt,
    refresh_tools,
)


def _t(*names):
    return [{"name": n, "input_schema": {}} for n in names]


# ── removal: the reason this row is not just a convenience ───────────────────

def test_a_revoked_tool_actually_disappears():
    """The whole security point. If this only added, a withdrawn consent would
    stay live for the life of a session that never ends."""
    out = refresh_tools(lambda: _t("file_read"), _t("file_read", "shell"))
    assert out.removed == ("shell",)
    assert [t["name"] for t in out.tools] == ["file_read"]


def test_a_resolver_that_cannot_answer_withdraws_everything():
    """Fails CLOSED. Refusing everything is recoverable at the next boundary; a
    silently retained capability is not."""
    def unreadable():
        raise RuntimeError("allowlist unreadable")

    out = refresh_tools(unreadable, _t("file_read", "shell"))
    assert out.tools == ()
    assert set(out.removed) == {"file_read", "shell"}
    assert out.reason == "failed-closed"


def test_an_empty_resolution_is_a_revocation_not_a_no_op():
    """"The profile offers nothing now" must not read as "nothing changed"."""
    out = refresh_tools(lambda: [], _t("file_read"))
    assert out.removed == ("file_read",) and out.tools == ()
    assert out.changed


def test_additions_and_removals_are_reported_separately():
    out = refresh_tools(lambda: _t("file_read", "web_search"), _t("file_read", "shell"))
    assert out.added == ("web_search",) and out.removed == ("shell",)


def test_an_unchanged_tool_set_reports_no_movement():
    out = refresh_tools(lambda: _t("a", "b"), _t("a", "b"))
    assert not out.changed and out.reason == "identical"


def test_reordering_alone_is_not_a_change():
    """Order is not authority; treating it as one would cry wolf every boundary."""
    out = refresh_tools(lambda: _t("b", "a"), _t("a", "b"))
    assert not out.changed


# ── the prompt fails in the OTHER direction ──────────────────────────────────

def test_a_broken_plugin_section_cannot_break_the_prompt():
    """Fails OPEN. The worst case is a stale section — which is what the owner
    already had before this row existed."""
    def broken():
        raise RuntimeError("plugin render failed")

    out = refresh_prompt(broken, "SOUL IN FORCE")
    assert out.text == "SOUL IN FORCE"
    assert out.reason == "failed-open" and out.kept


def test_a_failed_rebuild_prefers_explicit_last_good_bytes():
    def broken():
        raise RuntimeError("nope")

    out = refresh_prompt(broken, "CURRENT", last_good="LAST GOOD")
    assert out.text == "LAST GOOD"


def test_the_keep_path_is_gated_on_byte_equality_not_a_flag():
    """A flag is a claim about the world that drifts from it; the bytes are the
    world. A missed flag pins a session to a stale prompt forever, invisibly."""
    out = refresh_prompt(lambda: "SOUL", "SOUL")
    assert out.reason == "identical" and out.kept


def test_a_single_byte_of_difference_is_a_rebuild():
    out = refresh_prompt(lambda: "SOUL ", "SOUL")
    assert out.changed and out.text == "SOUL "


def test_a_builder_returning_nothing_is_an_empty_prompt_not_a_crash():
    out = refresh_prompt(lambda: None, "SOUL")
    assert out.text == "" and out.changed


# ── the lineage note ─────────────────────────────────────────────────────────

def test_nothing_changed_writes_no_note():
    """A note on every compaction trains a reader to skip it. This line exists to
    be read on the day a capability vanished and somebody asks when."""
    note = boundary_note(refresh_prompt(lambda: "S", "S"),
                         refresh_tools(lambda: _t("a"), _t("a")))
    assert note == ""


def test_a_removal_is_named_in_the_note():
    note = boundary_note(refresh_prompt(lambda: "S", "S"),
                         refresh_tools(lambda: _t(), _t("shell")))
    assert "tools removed: shell" in note


def test_a_failed_closed_resolver_is_visible_in_the_note():
    def boom():
        raise RuntimeError("x")

    note = boundary_note(refresh_prompt(lambda: "S", "S"), refresh_tools(boom, _t("a")))
    assert "failed closed" in note


def test_a_failed_open_prompt_is_visible_in_the_note():
    def boom():
        raise RuntimeError("x")

    note = boundary_note(refresh_prompt(boom, "S"), refresh_tools(lambda: _t("a"), _t("a")))
    assert "rebuild failed" in note


def test_a_rebuilt_prompt_is_named():
    note = boundary_note(refresh_prompt(lambda: "S2", "S"),
                         refresh_tools(lambda: _t("a"), _t("a")))
    assert "prompt rebuilt" in note


# ── the returned set is the caller's own ─────────────────────────────────────

def test_the_refreshed_tools_are_copies_so_a_caller_cannot_mutate_the_registry():
    live = _t("file_read")
    out = refresh_tools(lambda: live, [])
    out.tools[0]["name"] = "tampered"
    assert live[0]["name"] == "file_read"
