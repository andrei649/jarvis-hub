"""signal_routing.py — 0.41 World Signal Packs (per-domain signal routing, offline).

The Signal Layer plugin (`plugins/signal_layer.py`) fetches `world_brief` / `country_assessment`
when the owner has the sidecar running. This pack is the **pure routing layer on top**: it
classifies provided signals into domains (conflict / cyber / economy / aerospace / maritime /
energy / health) and routes each domain to the cabinet agents that care, so a brief lands with
Argus/Friday/Stark/Gecko/Ultron instead of one undifferentiated feed.

Honest by construction: it routes only the signals you pass in (no fetching), an unclassifiable
signal is surfaced in ``unrouted`` (never silently dropped, never force-labeled), and matched
terms are reported so a routing decision is inspectable. Pure, deterministic, bounded.
"""

from __future__ import annotations

# Domain → keyword rules (matched case-insensitively against title/summary/tags). Deliberately
# small and inspectable — a signal matching no domain is *unrouted*, not guessed.
DOMAINS: dict[str, tuple[str, ...]] = {
    "conflict": ("military", "missile", "strike", "troops", "conflict", "war", "border",
                 "artillery", "offensive", "ceasefire"),
    "cyber": ("cyber", "ransomware", "breach", "malware", "botnet", "phishing", "cve",
              "exploit", "ddos"),
    "economy": ("sanction", "inflation", "market", "trade", "tariff", "currency", "gdp",
                "default", "debt"),
    "aerospace": ("aircraft", "airspace", "satellite", "launch", "drone", "uav", "notam",
                  "airport"),
    "maritime": ("vessel", "ship", "port", "naval", "strait", "tanker", "ais", "blockade"),
    "energy": ("pipeline", "oil", "gas", "grid", "refinery", "nuclear", "power plant",
               "electricity"),
    "health": ("outbreak", "epidemic", "pandemic", "virus", "vaccine", "who alert"),
}

# Which cabinet agents subscribe to which domains (Argus is the geoint bridge → all of them).
AGENT_INTERESTS: dict[str, tuple[str, ...]] = {
    "argus": ("conflict", "cyber", "economy", "aerospace", "maritime", "energy", "health"),
    "friday": ("conflict", "economy", "health"),          # daily-brief context
    "stark": ("economy", "cyber"),                        # corporate intel
    "gecko": ("economy", "energy"),                       # markets / capital
    "ultron": ("cyber",),                                 # security shield
}

_MAX_SIGNALS = 500


def _text_of(signal: dict) -> str:
    s = signal if isinstance(signal, dict) else {}
    tags = s.get("tags") or []
    parts = [str(s.get("title") or ""), str(s.get("summary") or "")]
    parts += [str(t) for t in tags if str(t).strip()]
    return " ".join(parts).lower()


def classify_signal(signal: dict) -> dict:
    """Classify one signal into zero-or-more domains, with the matched terms shown.

    Returns ``{domains: [...], matched: {domain: [terms]}}``. No match → empty domains —
    honesty over coverage; the router surfaces it as unrouted rather than guessing.
    """
    text = _text_of(signal)
    matched: dict[str, list[str]] = {}
    for domain, terms in DOMAINS.items():
        hits = [t for t in terms if t in text]
        if hits:
            matched[domain] = hits
    return {"domains": sorted(matched), "matched": matched}


def route_signals(signals) -> dict:
    """Route *signals* to domains and interested agents (bounded, deterministic).

    Returns ``{by_domain, by_agent, unrouted, counts}``. Every unclassifiable signal is kept in
    ``unrouted`` (surfaced, never dropped); ``by_agent`` holds per-agent signal indexes so an
    agent's digest can pull exactly its slice.
    """
    items = [s for s in list(signals or [])[:_MAX_SIGNALS] if isinstance(s, dict)]
    by_domain: dict[str, list[int]] = {d: [] for d in DOMAINS}
    unrouted: list[int] = []
    classifications: list[dict] = []
    for i, sig in enumerate(items):
        c = classify_signal(sig)
        classifications.append(c)
        if not c["domains"]:
            unrouted.append(i)
            continue
        for d in c["domains"]:
            by_domain[d].append(i)
    by_agent = {
        agent: sorted({i for d in interests for i in by_domain.get(d, ())})
        for agent, interests in AGENT_INTERESTS.items()
    }
    return {
        "signals": items,
        "classifications": classifications,
        "by_domain": {d: idx for d, idx in by_domain.items() if idx},
        "by_agent": {a: idx for a, idx in by_agent.items() if idx},
        "unrouted": unrouted,
        "counts": {"signals": len(items), "routed": len(items) - len(unrouted),
                   "unrouted": len(unrouted)},
    }


def build_domain_brief(signals, domain: str, *, top: int = 5) -> dict:
    """A compact, honest per-domain brief: the top-N routed signals for *domain*.

    Ordering is by the provided ``severity`` (desc, missing → 0) then stable input order —
    no invented ranking. Unknown domain → an explicitly empty brief.
    """
    routed = route_signals(signals)
    idx = routed["by_domain"].get(domain, [])
    ranked = sorted(idx, key=lambda i: (-float(routed["signals"][i].get("severity") or 0), i))
    picked = [routed["signals"][i] for i in ranked[: max(0, int(top))]]
    return {
        "domain": domain,
        "known_domain": domain in DOMAINS,
        "top": picked,
        "count": len(idx),
        "headline": (f"{len(idx)} {domain} signal(s)" if domain in DOMAINS and idx
                     else "no signals" if domain in DOMAINS else "unknown domain"),
    }
