"""SEC-B5 (final leg) — recall outside a turn must not leak its taint mark.

``mark_turn_recall_tainted`` raises the ambient ``action_origin`` to ``recall:untrusted``
so a turn's later actions escalate to QUEUE. On a turn that is the whole point and the
turn's own ``finally`` bounds it. The HTTP route ``POST /api/memory/search-tool`` has no
turn: it recalls, serialises hits, and returns. Nothing downstream of it wants the mark,
and nothing there was arranged to clear it.

Until now what cleared it was an accident of dispatch. ``_kg_call`` is
``asyncio.to_thread``, which runs the sync tool in a **copy** of the context, so a mark
raised in the worker thread dies with the copy. Real isolation, but a property of the
offload rather than of the recall code — remove the offload and the mark escapes. These
tests pin the confinement itself, so it survives that refactor.
"""

from __future__ import annotations

import asyncio

import pytest

from agents.core.action_origin import (
    DEFAULT_ACTION_ORIGIN,
    bind_action_origin,
    current_action_origin,
    reset_action_origin,
)
from agents.core.security.recall_taint import (
    bounded_recall_taint,
    mark_turn_recall_tainted,
)
from agents.core.security.taint import TAINTED_RECALL_ORIGIN


def test_scope_confines_the_mark():
    """The mark is visible inside the block and gone after it."""
    before = current_action_origin()
    with bounded_recall_taint():
        assert mark_turn_recall_tainted() == TAINTED_RECALL_ORIGIN
        assert current_action_origin() == TAINTED_RECALL_ORIGIN
    assert current_action_origin() == before


def test_scope_confines_the_mark_on_an_exception_path():
    """A raising recall must not leave the mark behind either."""
    before = current_action_origin()
    with pytest.raises(RuntimeError), bounded_recall_taint():
        mark_turn_recall_tainted()
        raise RuntimeError("graph backend blew up mid-recall")
    assert current_action_origin() == before


def test_scope_does_not_downgrade_an_inbound_parent():
    """Entering and leaving the scope restores whatever origin was in force, not a default."""
    token = bind_action_origin("inbound")
    try:
        with bounded_recall_taint():
            # escalate-only: `inbound` is already untrusted, so the mark leaves it alone
            assert mark_turn_recall_tainted() == "inbound"
        assert current_action_origin() == "inbound"
    finally:
        reset_action_origin(token)


def test_inline_dispatch_would_leak_without_the_scope():
    """The failure this guards against is real, not hypothetical.

    Called inline — which is what the route becomes if the `to_thread` offload is ever
    dropped — an unscoped mark escapes into the caller's context and stays. This is the
    red proof for the scope: it is the same call, and the only difference is the guard.
    """
    before = current_action_origin()

    def recall_that_marks():                      # stands in for MemorySearchTool.search
        mark_turn_recall_tainted()

    # Unscoped. The token is taken *before* the call so resetting it undoes the leak the
    # call causes — this test must not itself leave the mark behind for the next test.
    token = bind_action_origin(before)
    try:
        recall_that_marks()
        leaked = current_action_origin()
    finally:
        reset_action_origin(token)
    assert current_action_origin() == before, "the test's own cleanup must be sound"

    with bounded_recall_taint():                   # the same call, scoped
        recall_that_marks()
    contained = current_action_origin()

    assert leaked == TAINTED_RECALL_ORIGIN, "unscoped inline recall should leak the mark"
    assert contained == before, "the scope must contain what the unscoped call leaked"


def test_to_thread_dispatch_is_isolation_but_not_the_guarantee():
    """Documents *why* the guard reads as a no-op today, so nobody deletes it as dead code.

    `asyncio.to_thread` runs the callable in a copy of the context. The mark therefore
    never reaches the caller even without the scope — which is exactly why the scope must
    not be justified by today's observable behaviour.
    """
    def recall_that_marks():
        mark_turn_recall_tainted()
        return current_action_origin()

    async def drive():
        before = current_action_origin()
        inside = await asyncio.to_thread(recall_that_marks)
        return before, inside, current_action_origin()

    before, inside, after = asyncio.run(drive())
    assert inside == TAINTED_RECALL_ORIGIN, "the mark is really raised inside the thread"
    assert after == before, "and the context copy discards it on the way out"


def test_default_origin_is_the_clean_one():
    """Guards the premise: these assertions mean nothing if the default were untrusted."""
    assert DEFAULT_ACTION_ORIGIN == "generated"
    assert TAINTED_RECALL_ORIGIN != DEFAULT_ACTION_ORIGIN
