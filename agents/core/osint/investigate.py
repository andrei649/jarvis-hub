"""osint/investigate.py — 0.40 OSINT Investigator Pack (offline investigation planner).

Builds on ``osint/correlate.py``: takes correlated evidence and produces an *investigation
plan* — prioritized leads + suggested pivots (what to look up next) + honest caveats. It

* **never performs a live lookup or enrichment** — that is an owner-gated plugin/network step;
  this pack only reasons over the evidence you provide (``live_lookups_performed: False``), and
* **keeps taint visible** — a lead derived from an untrusted source stays flagged, so any
  downstream write-back is approval-gated, not auto-actioned.

Pure, deterministic, offline (no clocks / randomness / network).
"""

from __future__ import annotations

from agents.core.osint.correlate import correlate

# Pivot rules: from an indicator KIND, the kinds you'd deterministically pivot to next. These
# are *suggestions* of what to look up (via an owner-gated tool), never lookups performed here.
PIVOTS: dict[str, tuple[str, ...]] = {
    "email": ("domain", "username"),
    "domain": ("ip", "url", "email"),
    "ip": ("domain", "asn"),
    "url": ("domain",),
    "username": ("email", "url"),
    "phone": ("username",),
    "hash": ("domain", "url"),
}

_MAX_PIVOTS = 50


def _limit(value, default: int = 8) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def suggest_pivots(findings) -> list[dict]:
    """From correlated *findings*, suggest next-lookup pivots (deterministic, deduped, bounded).

    Each pivot: ``{from_kind, from_value, to_kind, reason, tainted}``. Nothing is fetched — a
    pivot is a *suggestion* for an owner-gated enrichment step. Tainted origins propagate the
    flag so a followed pivot inherits approval-gating.
    """
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for f in findings or []:
        f = f if isinstance(f, dict) else {}
        kind = str(f.get("kind") or "")
        value = str(f.get("value") or "")
        tainted = bool(f.get("tainted"))
        for to_kind in PIVOTS.get(kind, ()):
            key = (kind, value, to_kind)
            if not value or key in seen:
                continue
            seen.add(key)
            out.append({
                "from_kind": kind, "from_value": value, "to_kind": to_kind,
                "reason": f"pivot {kind} → {to_kind}",
                "tainted": tainted,
            })
            if len(out) >= _MAX_PIVOTS:
                return out
    return out


def build_investigation(evidence, *, top: int = 8) -> dict:
    """Correlate *evidence* into a prioritized investigation plan (offline).

    Leads are the drawer's findings (already sorted by confidence/corroboration); pivots suggest
    the next owner-gated lookups; caveats state honestly that nothing was enriched live and how
    much intel is untrusted.
    """
    drawer = correlate(evidence)
    findings = drawer["findings"]
    leads = findings[:_limit(top)]
    pivots = suggest_pivots(findings)
    c = drawer["counts"]
    caveats = ["No live lookup/enrichment was performed — pivots are suggestions for an "
               "owner-gated tool; act on nothing automatically."]
    if c.get("tainted"):
        caveats.append(f"{c['tainted']} finding(s) come from untrusted source(s) — any write-back "
                       "is approval-gated (taint carried).")
    headline = (
        f"{c['findings']} lead(s) · {c['corroborated']} corroborated · "
        f"{len(pivots)} pivot(s) suggested"
    ) if c["findings"] else "no leads correlated"
    return {
        "headline": headline,
        "leads": leads,
        "pivots": pivots,
        "caveats": caveats,
        "counts": c,
        "live_lookups_performed": False,   # honest: this pack never enriches
        "untrusted_ingestion": drawer["untrusted_ingestion"],
    }
