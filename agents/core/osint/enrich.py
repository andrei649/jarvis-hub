"""osint/enrich.py — 0.40 OSINT enrichment scaffold (DRA-05/DRA-10).

``investigate.build_investigation`` suggests pivots and, by design, follows none of them.
This module is the layer that *follows* one — the governed seam between "what would you
look up next" and an actual lookup — without becoming a network client itself.

Three properties keep it honest:

* **Injectable client, never an implicit provider.** Network lookups go through a
  duck-typed :class:`PivotLookupClient` (``supports`` + ``lookup``). With no client
  injected — the default — every network pivot is *refused by name*
  (``enrichment_client_not_configured``); nothing is ever fabricated to fill the gap.
  The one live implementation is ``plugins/osint_enrich.py``, itself default-off.
* **Offline derivations still work.** ``url → domain`` and ``email → domain`` are pure
  string/URL decompositions of a value we already hold, so they resolve locally with no
  provider at all. That is why this is a scaffold and not a refusal stub.
* **Enrichment output is untrusted.** Every emitted record carries
  ``source="osint:enrich"``, which ``security.taint`` classifies untrusted. Fed back
  through :func:`osint.correlate.correlate` the finding stays tainted, so
  :func:`osint.correlate.writeback_payload` still escalates a GRANT to QUEUE — enriched
  intel can no more auto-execute than the evidence it came from.

No clocks, no randomness, and no network of its own.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from agents.core.osint.correlate import correlate
from agents.core.osint.investigate import _limit, build_investigation
from agents.core.security import taint

#: Source label stamped on every enriched record. Contains "osint", so
#: ``taint.is_untrusted_source`` classifies it untrusted (``security/taint.py``).
ENRICH_SOURCE = "osint:enrich"

#: Pivots that are a pure decomposition of a value we already hold — no provider needed.
OFFLINE_DERIVATIONS = frozenset({("url", "domain"), ("email", "domain")})

_MAX_DETAIL = 400
_MAX_URL = 500


@runtime_checkable
class PivotLookupClient(Protocol):
    """The seam an OSINT provider plugs into (duck-typed: tests inject a fake).

    ``supports`` must be cheap and side-effect free — it is consulted *before* any
    budget is spent, so an unsupported pair costs nothing and is reported as
    ``provider_not_configured`` rather than silently dropped.
    """

    def supports(self, from_kind: str, to_kind: str) -> bool:
        """True when this client can answer this pivot pair right now."""

    async def lookup(self, *, from_kind: str, from_value: str, to_kind: str) -> list[dict]:
        """Return ``{"kind", "value", "detail", "url"}`` records; ``[]`` when nothing is known."""


def _derive_offline(from_kind: str, from_value: str, to_kind: str) -> str:
    """The local, deterministic half of the pivot table. ``""`` means "cannot derive"."""
    if (from_kind, to_kind) == ("url", "domain"):
        try:
            host = urlparse(from_value).hostname or ""
        except ValueError:
            return ""
        return host.strip().lower().rstrip(".")
    if (from_kind, to_kind) == ("email", "domain"):
        text = from_value.strip()
        if "@" not in text:
            return ""
        return text.rsplit("@", 1)[-1].strip().lower().rstrip(".")
    return ""


async def enrich_pivots(pivots, *, client: PivotLookupClient | None = None,
                        max_lookups: int = 8) -> dict:
    """Follow *pivots* as far as the injected client honestly allows.

    Returns ``{"evidence", "performed", "refused", "live_lookups_performed"}``. ``evidence``
    is a list of loose evidence dicts ready to hand straight back to :func:`correlate`;
    ``refused`` names every pivot that was *not* followed and why, so the caller can show
    the gap instead of mistaking silence for "nothing out there".

    Never raises for a misbehaving client: an exception from ``lookup`` becomes a
    ``lookup_failed`` refusal. Client calls are capped at *max_lookups* (junk coerces to
    the documented default via ``investigate._limit``); offline derivations are free and do
    not consume the budget.
    """
    budget = _limit(max_lookups)
    evidence: list[dict] = []
    refused: list[dict] = []
    seen: set[tuple[str, str]] = set()
    performed = 0

    def _refuse(from_kind: str, from_value: str, to_kind: str, reason: str) -> None:
        refused.append({"from_kind": from_kind, "from_value": from_value,
                        "to_kind": to_kind, "reason": reason})

    def _emit(from_kind: str, from_value: str, to_kind: str,
              record: dict, pivot_tainted: bool) -> None:
        kind = (str(record.get("kind") or to_kind)).strip().lower()
        value = str(record.get("value") or "").strip()
        if not kind or not value:
            return
        key = (kind, value.lower())
        if key in seen:
            return
        seen.add(key)
        evidence.append({
            "source": ENRICH_SOURCE,
            "kind": kind,
            "value": value,
            "observed_at": "",
            "detail": (str(record.get("detail") or "")
                       or f"enriched from {from_kind} {from_value} → {kind}")[:_MAX_DETAIL],
            "url": str(record.get("url") or "")[:_MAX_URL],
            # Enrichment output is untrusted by its source alone; an untrusted *origin*
            # pivot cannot make it any less so. Both are recorded rather than collapsed,
            # so the drawer can show which leads inherited taint and which merely have it.
            "tainted": taint.is_untrusted_source(ENRICH_SOURCE) or pivot_tainted,
            "pivot_tainted": pivot_tainted,
            "derived_from": {"kind": from_kind, "value": from_value},
        })

    for raw in pivots or []:
        pivot = raw if isinstance(raw, dict) else {}
        from_kind = str(pivot.get("from_kind") or "").strip().lower()
        from_value = str(pivot.get("from_value") or "").strip()
        to_kind = str(pivot.get("to_kind") or "").strip().lower()
        pivot_tainted = bool(pivot.get("tainted"))
        if not from_kind or not from_value or not to_kind:
            continue

        if (from_kind, to_kind) in OFFLINE_DERIVATIONS:
            derived = _derive_offline(from_kind, from_value, to_kind)
            if not derived:
                _refuse(from_kind, from_value, to_kind, "offline_derivation_failed")
                continue
            _emit(from_kind, from_value, to_kind,
                  {"kind": to_kind, "value": derived,
                   "detail": f"derived offline from {from_kind} {from_value}"}, pivot_tainted)
            continue

        if client is None:
            _refuse(from_kind, from_value, to_kind, "enrichment_client_not_configured")
            continue
        try:
            supported = bool(client.supports(from_kind, to_kind))
        except Exception:
            supported = False
        if not supported:
            _refuse(from_kind, from_value, to_kind, "provider_not_configured")
            continue
        if performed >= budget:
            _refuse(from_kind, from_value, to_kind, "lookup_budget_exhausted")
            continue

        performed += 1
        try:
            records = await client.lookup(from_kind=from_kind, from_value=from_value,
                                          to_kind=to_kind)
        except Exception:
            _refuse(from_kind, from_value, to_kind, "lookup_failed")
            continue
        for record in records or []:
            if isinstance(record, dict):
                _emit(from_kind, from_value, to_kind, record, pivot_tainted)

    return {
        "evidence": evidence,
        "performed": performed,
        "refused": refused,
        "live_lookups_performed": performed > 0,
    }


async def investigate_and_enrich(evidence, *, client: PivotLookupClient | None = None,
                                 top: int = 8, max_lookups: int = 8) -> dict:
    """Plan an investigation, follow its pivots, and re-correlate with what came back.

    The plan half is :func:`investigate.build_investigation` verbatim — its offline
    contract is untouched — plus a ``drawer`` re-correlated over the original evidence and
    the enriched records, an ``enrichment`` report, and caveats that state honestly how
    many pivots were followed and how many were not.
    """
    plan = build_investigation(evidence, top=top)
    enrichment = await enrich_pivots(plan["pivots"], client=client, max_lookups=max_lookups)
    drawer = correlate(list(evidence or []) + enrichment["evidence"])

    caveats = list(plan["caveats"])
    if enrichment["live_lookups_performed"]:
        # plan's first caveat ("No live lookup … was performed") is now false — replace it
        # rather than leave a contradiction in the same list.
        caveats[0] = (
            f"{enrichment['performed']} live lookup(s) were performed through the injected "
            "client; every enriched record is untrusted (tainted), so any write-back stays "
            "approval-gated."
        )
    if enrichment["refused"]:
        reasons = sorted({r["reason"] for r in enrichment["refused"]})
        caveats.append(
            f"{len(enrichment['refused'])} pivot(s) were not followed ({', '.join(reasons)}) "
            "— treat those branches as unexplored, not as cleared."
        )
    return {
        **plan,
        "drawer": drawer,
        "enrichment": enrichment,
        "caveats": caveats,
        "live_lookups_performed": enrichment["live_lookups_performed"],
    }
