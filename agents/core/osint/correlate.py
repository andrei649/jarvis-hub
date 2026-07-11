"""osint/correlate.py — P2 OSINT pack: governed correlation over untrusted evidence.

ORIZONT 24 Track P (P2 — OSINT / WorldView). The investigator's core: take *evidence
items* gathered from untrusted external sources (WorldView/Argus, web, RSS, news), mark
them tainted at the **ingestion boundary** (``security.taint``), correlate them by shared
indicators into findings carrying a provenance chain + a corroboration-based confidence,
and assemble an evidence-drawer "world brief".

Two properties make this the *governance* surface P2 is meant to be:

* **Taint propagates evidence → finding → action.** A finding supported by any tainted
  (untrusted-source) evidence is itself tainted; :func:`writeback_payload` carries that
  flag onto the action payload, so the Action Kernel escalates a GRANT to QUEUE
  (``kernel.authorize``, H23.6) — untrusted intel can **never auto-execute**.
* **Honest, never fabricated.** Confidence is a transparent function of corroboration
  (how many *distinct* sources agree) and volume — not a model guess. Zero evidence →
  zero findings (no invented intel; OSINT degrades to silence, like the WorldView plugin).

Offline by design: this correlates the evidence the caller hands it. *Live* collection
(SpiderFoot modules, the WorldView REST, a real news feed) is a separate, owner-gated
wiring — the engine here is the deterministic, hermetically-verifiable rail.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents.core.security import taint

# Indicator kinds whose value is a case-insensitive token (normalised by lower+strip).
# Anything else (free-text, coords) is correlated on its exact trimmed value.
_CASEFOLD_KINDS = frozenset({"ip", "domain", "host", "email", "handle", "url", "hash", "asn"})
_TRUSTED_EVIDENCE_SOURCES = frozenset({"manual", "operator"})


def _source_label(source: str | None) -> str:
    return (str(source or "").strip() or "osint:unknown").lower()


def _is_untrusted_evidence_source(source: str | None) -> bool:
    label = _source_label(source).lower()
    return (
        label not in _TRUSTED_EVIDENCE_SOURCES
        or taint.is_untrusted_source(label)
    )


@dataclass(frozen=True)
class Evidence:
    """One observation from a (usually untrusted) source.

    ``source`` drives the taint decision (``security.taint.is_untrusted_source``):
    web/osint/worldview/rss/news/inbound/... are untrusted; ``manual``/``operator`` are not.
    ``kind`` + ``value`` form the correlation key (e.g. ``("domain", "evil.example")``).
    """

    source: str
    kind: str
    value: str
    observed_at: str = ""
    detail: str = ""
    url: str = ""

    def as_dict(self) -> dict:
        source = _source_label(self.source)
        return {
            "source": source, "kind": self.kind, "value": self.value,
            "observed_at": self.observed_at, "detail": self.detail, "url": self.url,
            "tainted": _is_untrusted_evidence_source(source),
        }


@dataclass
class Finding:
    """A correlated indicator: one entity (``kind``/``value``) + every observation of it."""

    kind: str
    value: str
    provenance: list[dict] = field(default_factory=list)   # the supporting evidence dicts
    sources: list[str] = field(default_factory=list)       # distinct source labels, sorted
    tainted: bool = False                                    # any supporting evidence untrusted
    confidence: float = 0.0                                  # corroboration-based, 0..1

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "value": self.value, "confidence": self.confidence,
            "tainted": self.tainted, "sources": self.sources,
            "count": len(self.provenance), "provenance": self.provenance,
        }


def _coerce(item) -> Evidence | None:
    """Accept an :class:`Evidence` or a loose dict; drop anything without kind+value."""
    if isinstance(item, Evidence):
        ev = item
    elif isinstance(item, dict):
        kind = str(item.get("kind") or "").strip()
        value = str(item.get("value") or "").strip()
        if not kind or not value:
            return None
        ev = Evidence(
            source=_source_label(item.get("source")),
            kind=kind, value=value,
            observed_at=str(item.get("observed_at") or ""),
            detail=str(item.get("detail") or ""),
            url=str(item.get("url") or ""),
        )
    else:
        return None
    if ev.source != _source_label(ev.source):
        ev = Evidence(
            source=_source_label(ev.source),
            kind=ev.kind,
            value=ev.value,
            observed_at=ev.observed_at,
            detail=ev.detail,
            url=ev.url,
        )
    return ev if ev.kind and ev.value else None


def _norm_value(kind: str, value: str) -> str:
    """Correlation key for an indicator value — casefold the token kinds, trim the rest."""
    v = value.strip()
    return v.lower() if kind.strip().lower() in _CASEFOLD_KINDS else v


def _confidence(distinct_sources: int, total: int, any_trusted: bool) -> float:
    """Transparent corroboration score in [0, 1]:

    a base for existing at all, a strong bonus per *distinct* corroborating source
    (independent agreement is the real signal), a small bonus for repeat volume, and a
    bump when at least one *trusted* (operator/manual) source backs it. Capped at 0.95
    for all-untrusted findings — pure OSINT is never certain (it routes through approval).
    """
    score = 0.30 + 0.22 * max(0, distinct_sources - 1) + 0.05 * max(0, total - 1)
    if any_trusted:
        score += 0.15
    score = min(score, 1.0 if any_trusted else 0.95)
    return round(score, 2)


def correlate(evidence) -> dict:
    """Correlate *evidence* (an iterable of :class:`Evidence` or dicts) into findings.

    Each item is tainted at ingestion per its source; findings group every observation of
    the same indicator and inherit taint from their evidence. Returns the evidence-drawer:
    findings sorted by (confidence desc, count desc, value), plus honest roll-up counts.
    Empty / all-malformed input → an empty drawer (never invented findings).
    """
    groups: dict[tuple[str, str], list[Evidence]] = {}
    for raw in evidence or []:
        ev = _coerce(raw)
        if ev is None:
            continue
        groups.setdefault((ev.kind, _norm_value(ev.kind, ev.value)), []).append(ev)

    findings: list[Finding] = []
    for (kind, _key), evs in groups.items():
        prov = [e.as_dict() for e in evs]
        sources = sorted({_source_label(e.source) for e in evs})
        any_untrusted = any(_is_untrusted_evidence_source(e.source) for e in evs)
        any_trusted = any(
            not _is_untrusted_evidence_source(e.source) for e in evs
        )
        findings.append(Finding(
            kind=kind,
            value=evs[0].value,  # display the first-seen casing
            provenance=prov,
            sources=sources,
            tainted=any_untrusted,
            confidence=_confidence(len(sources), len(evs), any_trusted),
        ))

    findings.sort(key=lambda f: (-f.confidence, -len(f.provenance), f.value.lower()))
    drawer = [f.as_dict() for f in findings]
    return {
        "findings": drawer,
        "counts": {
            "evidence": sum(len(f.provenance) for f in findings),
            "findings": len(findings),
            "tainted": sum(1 for f in findings if f.tainted),
            "corroborated": sum(1 for f in findings if len(f.sources) > 1),
        },
        "untrusted_ingestion": any(f.tainted for f in findings),
    }


def _limit(value, default: int = 8) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def build_brief(evidence, *, top: int = 8) -> dict:
    """A compact "world brief" view of the drawer — the top-N findings by confidence.

    The honest headline a digest/agent can read: how much corroborated intel there is and
    whether any of it is untrusted (so the reader knows it is approval-gated, not actioned).
    """
    drawer = correlate(evidence)
    findings = drawer["findings"][:_limit(top)]
    c = drawer["counts"]
    headline = (
        f"{c['findings']} indicator(s) · {c['corroborated']} corroborated · "
        f"{c['tainted']} from untrusted source(s)"
    ) if c["findings"] else "no intel correlated"
    return {
        "headline": headline,
        "top": findings,
        "counts": c,
        "untrusted_ingestion": drawer["untrusted_ingestion"],
    }


def writeback_payload(finding: dict | Finding, *, base: dict | None = None) -> dict:
    """Build a kernel-action payload from a finding, **carrying its taint**.

    A finding derived from untrusted OSINT yields a tainted payload, so a write-back
    (e.g. ``kg.write`` to persist the indicator) is escalated GRANT→QUEUE by
    ``kernel.authorize`` — the trust boundary the P2 reality case proves. A finding backed
    only by trusted (operator) sources stays untainted and follows normal policy.
    """
    f = finding.as_dict() if isinstance(finding, Finding) else dict(finding or {})
    payload = dict(base or {})
    payload.update({
        "indicator": f.get("value"),
        "kind": f.get("kind"),
        "confidence": f.get("confidence"),
        "sources": f.get("sources", []),
    })
    if f.get("tainted"):
        # Record an actually untrusted origin, not merely the first sorted source.
        provenance = f.get("provenance") or []
        src = next(
            (
                _source_label(item.get("source"))
                for item in provenance
                if isinstance(item, dict)
                and item.get("tainted")
                and item.get("source")
            ),
            None,
        )
        if src is None:
            src = next(
                (
                    _source_label(source)
                    for source in f.get("sources") or []
                    if _is_untrusted_evidence_source(source)
                ),
                "osint:unknown",
            )
        payload = taint.mark(payload, source=src)
    return payload
