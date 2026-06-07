"""Tipping-and-cueing detector (WorldView ticket H19.2.4).

"Tipping and cueing" (a.k.a. Sidhu's *passes stacking*) is the situation where
several independent satellite passes converge on the same Area of Interest within
a short span of time — one sensor's detection effectively *tips* the others. A
dense cluster of recon windows over one AOI is a strong signal that the AOI is
worth a closer look.

This module turns a ``list[ReconWindow]`` into discrete :class:`TippingEvent`
detections, one per maximal qualifying cluster.

Clustering rule
---------------
Per ``aoi_id``, sort the windows by ``t_ingress``. Slide a left/right pointer so
that every window in ``[left, right]`` has ``t_ingress`` within ``delta_s`` of the
left-most window in the cluster (i.e. the whole cluster spans ``Δ ≤ delta_s``).

A *maximal qualifying cluster* is a run of windows that:

1. spans at most ``delta_s`` seconds (``t_end - t_start ≤ delta_s``), and
2. contains at least ``min_count`` windows,

and that cannot be extended on the right without breaking rule (1). Once a
maximal cluster is emitted, scanning resumes *after* its last contributing
window, so clusters never overlap and each window contributes to at most one
event. Different AOIs are detected fully independently.

Pure stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass

from worldview_ingest.recon.windows import ReconWindow


@dataclass(frozen=True)
class TippingEvent:
    """A cluster of recon-window ingress times stacking over one AOI.

    Times are UNIX-seconds floats (UTC), matching :class:`ReconWindow`.

    - ``t_start`` / ``t_end``: ingress of the first / last contributing window.
    - ``window_count``: number of contributing recon windows (``≥ min_count``).
    - ``norad_ids``: the contributing satellites' NORAD ids, in cluster order.
    """

    aoi_id: str
    t_start: float
    t_end: float
    window_count: int
    norad_ids: tuple[int, ...]


def detect_tipping(
    windows: list[ReconWindow], delta_s: float, min_count: int
) -> list[TippingEvent]:
    """Detect tipping-and-cueing clusters per AOI.

    For each ``aoi_id``, find every maximal time-span ``Δ ≤ delta_s`` that
    contains ``≥ min_count`` recon-window ingress times (see the module
    docstring for the precise clustering rule), emitting one
    :class:`TippingEvent` per maximal qualifying cluster.

    Returns the events sorted by ``(aoi_id, t_start)``. With ``min_count ≤ 1``
    or an empty ``windows`` list the result may be empty / trivial accordingly;
    a non-positive ``min_count`` is treated as ``1``.
    """
    min_count = max(1, min_count)

    by_aoi: dict[str, list[ReconWindow]] = {}
    for w in windows:
        by_aoi.setdefault(w.aoi_id, []).append(w)

    events: list[TippingEvent] = []
    for aoi_id, group in by_aoi.items():
        group.sort(key=lambda w: w.t_ingress)
        n = len(group)
        left = 0
        while left < n:
            # Extend the cluster as far right as the delta_s span allows.
            right = left
            while (
                right + 1 < n
                and group[right + 1].t_ingress - group[left].t_ingress <= delta_s
            ):
                right += 1

            count = right - left + 1
            if count >= min_count:
                cluster = group[left : right + 1]
                events.append(
                    TippingEvent(
                        aoi_id=aoi_id,
                        t_start=cluster[0].t_ingress,
                        t_end=cluster[-1].t_ingress,
                        window_count=count,
                        norad_ids=tuple(w.norad_id for w in cluster),
                    )
                )
                # Resume after the emitted (non-overlapping) cluster.
                left = right + 1
            else:
                # No qualifying cluster anchored at `left`; advance by one.
                left += 1

    events.sort(key=lambda e: (e.aoi_id, e.t_start))
    return events
