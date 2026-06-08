"""Tests for the pure windowed-keyed CEP engine (worldview_ingest.cep.engine).

No Kafka / asyncio: exercises the watermark/lateness/window-firing semantics and
per-key isolation directly against :class:`WindowedKeyedEngine`. The rule used
here is a trivial collector so the tests assert on the engine's *driving*
behaviour, not on a specific detector.
"""

from __future__ import annotations

import math

from worldview_ingest.cep.engine import Event, WindowedKeyedEngine, WindowResult

# A wide epoch base so window boundaries land on round multiples of window_s.
# 1_700_000_000 / 100 == 17_000_000 exactly, so windows align at ...000/...100.
BASE = 1_700_000_000.0


def _count_rule(key: str, start: float, end: float, events: list[Event]) -> int:  # noqa: ARG001
    """Trivial rule: return the number of buffered events (truthy => recorded)."""
    return len(events)


def _make(window_s: float = 100.0, lateness_s: float = 30.0):
    """An engine over `_count_rule` with the given window / lateness widths."""
    return WindowedKeyedEngine(window_s=window_s, allowed_lateness_s=lateness_s, rule=_count_rule)


# --------------------------------------------------------------------------- #
# construction / validation
# --------------------------------------------------------------------------- #


def test_rejects_nonpositive_window() -> None:
    for bad in (0.0, -1.0):
        try:
            WindowedKeyedEngine(window_s=bad, allowed_lateness_s=0.0, rule=_count_rule)
        except ValueError:
            pass
        else:  # pragma: no cover - guard
            raise AssertionError("expected ValueError for window_s <= 0")


def test_rejects_negative_lateness() -> None:
    try:
        WindowedKeyedEngine(window_s=10.0, allowed_lateness_s=-1.0, rule=_count_rule)
    except ValueError:
        pass
    else:  # pragma: no cover - guard
        raise AssertionError("expected ValueError for negative lateness")


def test_empty_engine_watermark_is_neg_inf() -> None:
    """Before any event there is no time basis, so nothing is ever 'late'."""
    eng = _make()
    assert eng.watermark == -math.inf
    assert eng.dropped_late == 0
    assert eng.open_window_count() == 0


# --------------------------------------------------------------------------- #
# watermark
# --------------------------------------------------------------------------- #


def test_watermark_tracks_max_event_ts_minus_lateness() -> None:
    eng = _make(window_s=100.0, lateness_s=30.0)
    eng.push(Event("k", BASE + 10.0, "a"))
    assert eng.watermark == BASE + 10.0 - 30.0
    # A later event raises the watermark.
    eng.push(Event("k", BASE + 50.0, "b"))
    assert eng.watermark == BASE + 50.0 - 30.0


def test_watermark_is_monotonic_under_out_of_order() -> None:
    """An older (out-of-order) event must never lower the watermark."""
    eng = _make(window_s=100.0, lateness_s=30.0)
    eng.push(Event("k", BASE + 80.0, "late-arriver-high-ts"))
    wm = eng.watermark
    eng.push(Event("k", BASE + 60.0, "older"))  # ts below the current max
    assert eng.watermark == wm  # unchanged


# --------------------------------------------------------------------------- #
# window firing at watermark crossing
# --------------------------------------------------------------------------- #


def test_window_fires_exactly_when_watermark_passes_close() -> None:
    """Window [BASE, BASE+100) must fire iff watermark >= BASE+100."""
    eng = _make(window_s=100.0, lateness_s=30.0)
    # Event in the first window; watermark = (BASE+10)-30 < BASE+100 => no fire yet.
    out = eng.push(Event("k", BASE + 10.0, "a"))
    assert out == []
    assert eng.open_window_count() == 1

    # Push an event whose ts pulls the watermark to exactly BASE+100 (close edge).
    # watermark = ts - 30 == BASE+100  =>  ts == BASE+130.
    out = eng.push(Event("k", BASE + 130.0, "b"))
    # The first window [BASE, BASE+100) closes now (end <= watermark).
    assert len(out) == 1
    res = out[0]
    assert isinstance(res, WindowResult)
    assert res.key == "k"
    assert res.window_start == BASE
    assert res.window_end == BASE + 100.0
    assert res.output == 1  # exactly the one event "a"
    # The event "b" lives in window [BASE+100, BASE+200), still open.
    assert eng.fired == 1
    assert eng.open_window_count() == 1


def test_window_does_not_fire_one_tick_early() -> None:
    """At watermark == close - epsilon the window stays open."""
    eng = _make(window_s=100.0, lateness_s=30.0)
    eng.push(Event("k", BASE + 10.0, "a"))
    # ts == BASE+129 => watermark == BASE+99 < BASE+100: no close.
    out = eng.push(Event("k", BASE + 129.0, "b"))
    assert out == []
    assert eng.fired == 0


# --------------------------------------------------------------------------- #
# out-of-order within / beyond allowed lateness
# --------------------------------------------------------------------------- #


def test_out_of_order_within_lateness_is_included() -> None:
    """An out-of-order event with ts >= watermark joins its window, not dropped."""
    eng = _make(window_s=100.0, lateness_s=30.0)
    # Advance the watermark with a high-ts event in window [BASE, BASE+100).
    eng.push(Event("k", BASE + 80.0, "a"))
    assert eng.watermark == BASE + 50.0
    # An older event at BASE+55 is still >= watermark (BASE+50): accepted into the
    # SAME window [BASE, BASE+100).
    out = eng.push(Event("k", BASE + 55.0, "b"))
    assert out == []
    assert eng.dropped_late == 0
    assert eng.open_window_count() == 1
    # When the window finally closes, BOTH events are counted.
    out = eng.push(Event("k", BASE + 230.0, "c"))  # watermark -> BASE+200
    (res,) = [r for r in out if r.window_start == BASE]
    assert res.output == 2  # "a" and "b"


def test_event_older_than_watermark_is_dropped_and_counted() -> None:
    """An event with ts < watermark is later than allowed lateness => dropped."""
    eng = _make(window_s=100.0, lateness_s=30.0)
    eng.push(Event("k", BASE + 80.0, "a"))  # watermark = BASE+50
    # BASE+40 < watermark (BASE+50): too late.
    out = eng.push(Event("k", BASE + 40.0, "too-late"))
    assert out == []
    assert eng.dropped_late == 1
    # It joined no window: only "a" remains buffered.
    out = eng.push(Event("k", BASE + 230.0, "c"))
    (res,) = [r for r in out if r.window_start == BASE]
    assert res.output == 1  # just "a"


def test_dropped_event_does_not_change_watermark() -> None:
    eng = _make(window_s=100.0, lateness_s=30.0)
    eng.push(Event("k", BASE + 80.0, "a"))
    wm = eng.watermark
    eng.push(Event("k", BASE + 10.0, "drop"))
    assert eng.dropped_late == 1
    assert eng.watermark == wm


# --------------------------------------------------------------------------- #
# per-key isolation
# --------------------------------------------------------------------------- #


def test_keys_do_not_bleed_into_each_other() -> None:
    """Two keys keep independent buffers; one's events never enter the other's window."""
    eng = _make(window_s=100.0, lateness_s=30.0)
    eng.push(Event("alpha", BASE + 10.0, "a1"))
    eng.push(Event("alpha", BASE + 20.0, "a2"))
    eng.push(Event("beta", BASE + 30.0, "b1"))
    assert eng.key_count() == 2
    # Close everyone's first window by advancing the watermark to >= BASE+100.
    results = eng.push(Event("alpha", BASE + 130.0, "a3"))
    # We may close alpha's first window here; advance beta too with its own event.
    results += eng.push(Event("beta", BASE + 130.0, "b2"))
    by_key = {(r.key, r.window_start): r.output for r in results}
    # alpha's first window had exactly a1+a2 = 2 events; beta's had exactly b1 = 1.
    assert by_key[("alpha", BASE)] == 2
    assert by_key[("beta", BASE)] == 1


def test_one_key_does_not_close_anothers_window_prematurely() -> None:
    """The global watermark closes a key's window only when that window's edge is passed."""
    eng = _make(window_s=100.0, lateness_s=30.0)
    eng.push(Event("alpha", BASE + 10.0, "a"))  # window [BASE, BASE+100)
    # A beta event with a high ts advances the GLOBAL watermark past BASE+100.
    out = eng.push(Event("beta", BASE + 130.0, "b"))
    # alpha's window [BASE, BASE+100) closes from the watermark advance, with only "a".
    alpha_res = [r for r in out if r.key == "alpha"]
    assert len(alpha_res) == 1
    assert alpha_res[0].output == 1
    # beta's own window [BASE+100, BASE+200) is still open (no other key affects it).
    assert eng.open_window_count() == 1
    assert eng.key_count() == 1  # only beta remains


# --------------------------------------------------------------------------- #
# memory release
# --------------------------------------------------------------------------- #


def test_closed_windows_release_memory() -> None:
    """Firing a window evicts it; a key with no open windows is dropped entirely."""
    eng = _make(window_s=100.0, lateness_s=30.0)
    eng.push(Event("k", BASE + 10.0, "a"))
    assert eng.open_window_count() == 1
    assert eng.key_count() == 1
    # Close the window AND avoid opening a new one for "k": route the advancing
    # event under a DIFFERENT key so "k" empties out completely.
    eng.push(Event("other", BASE + 130.0, "x"))
    # k's only window fired and was evicted; k is gone, only `other` remains open.
    assert "k" not in eng._windows  # noqa: SLF001 - whitebox memory check
    assert eng.key_count() == 1
    assert eng.open_window_count() == 1  # `other`'s window


def test_flush_force_closes_all_remaining_windows() -> None:
    """flush() fires every still-open window regardless of the watermark."""
    # Large lateness so the watermark stays far behind: no window auto-closes on push.
    eng = _make(window_s=100.0, lateness_s=10_000.0)
    eng.push(Event("alpha", BASE + 10.0, "a"))
    eng.push(Event("beta", BASE + 210.0, "b"))
    # Both windows remain open (watermark is well below either close edge).
    assert eng.fired == 0
    assert eng.open_window_count() == 2
    assert eng.key_count() == 2
    flushed = eng.flush()
    keys = {r.key for r in flushed}
    assert keys == {"alpha", "beta"}
    # Nothing left after a flush.
    assert eng.open_window_count() == 0
    assert eng.key_count() == 0


def test_empty_window_fires_silently_without_result() -> None:
    """A window whose rule returns a falsey output still evicts but yields no result."""

    def _none_rule(key, start, end, events):  # noqa: ARG001
        return None

    eng = WindowedKeyedEngine(window_s=100.0, allowed_lateness_s=30.0, rule=_none_rule)
    eng.push(Event("k", BASE + 10.0, "a"))
    out = eng.push(Event("k", BASE + 130.0, "b"))
    assert out == []  # rule returned None => no WindowResult
    assert eng.fired == 1  # but the window was still counted + evicted
    assert "k" in eng._windows  # only the new window for "b" remains  # noqa: SLF001
    assert eng.open_window_count() == 1


def test_multiple_windows_close_in_time_order() -> None:
    """When several windows for a key close at once they fire in start order."""
    # Lateness 200 keeps the watermark behind both windows after the first two
    # pushes, so neither closes early and both are buffered when the jump lands.
    eng = _make(window_s=100.0, lateness_s=200.0)
    eng.push(Event("k", BASE + 10.0, "w0"))  # window [BASE, BASE+100)
    eng.push(Event("k", BASE + 150.0, "w1"))  # window [BASE+100, BASE+200)
    assert eng.open_window_count() == 2  # neither closed yet
    # Jump the watermark past both windows' closes at once: wm = ts-200 >= BASE+200.
    out = eng.push(Event("k", BASE + 450.0, "w3"))
    starts = [r.window_start for r in out]
    assert starts == sorted(starts)  # earlier window fires before later
    assert BASE in starts and BASE + 100.0 in starts
