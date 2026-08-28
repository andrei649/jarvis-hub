"""T-0.41 tail — world signals reach the morning brief.

The routing layer + its HTTP/HUD surface landed earlier, but the row asks for the
feed to reach per-agent *digests* and `digest.py` consumed none of it (the
HUD-parity caller gate caught that `/api/signals/brief/{domain}` had no consumer
at all). This closes it, following the exact `runtime_health` convention already
in this module: the CALLER reads the external data and passes it in, so the
builder stays pure and network-free.

The honesty rules under test: omitting the data leaves the brief byte-identical
to before, an unavailable sidecar adds nothing (rather than an alarming empty
section), and a domain with no signals is not rendered as if it had some.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy.digest import build_morning_brief  # noqa: E402
from agents.core.autonomy.queue import TaskQueue  # noqa: E402


def _queue(tmp_path):
    return TaskQueue(str(tmp_path / "tasks.db")).initialize()


def _brief(domain, count, titles):
    """The shape `signal_routing.build_domain_brief` returns."""
    return {
        "domain": domain,
        "known_domain": True,
        "count": count,
        "top": [{"title": t, "severity": 3} for t in titles],
        "headline": f"{count} {domain} signal(s)",
    }


def test_omitting_signal_briefs_leaves_the_brief_byte_identical(tmp_path):
    """The default path must not change for anyone without a sidecar."""
    q = _queue(tmp_path)
    assert build_morning_brief(q) == build_morning_brief(q, signal_briefs=None)


def test_empty_or_unavailable_briefs_add_no_section(tmp_path):
    """An unreachable sidecar must add nothing — not an empty, alarming heading."""
    q = _queue(tmp_path)
    base = build_morning_brief(q)
    assert build_morning_brief(q, signal_briefs=[]) == base
    # a brief with zero signals is not worth a line either
    assert build_morning_brief(q, signal_briefs=[_brief("cyber", 0, [])]) == base


def test_signal_briefs_render_domain_headlines_and_top_titles(tmp_path):
    q = _queue(tmp_path)
    text = build_morning_brief(q, signal_briefs=[
        _brief("cyber", 2, ["Ransomware breach at bank", "CVE exploited in the wild"]),
        _brief("conflict", 1, ["Missile strike near border"]),
    ])
    assert "Semnale" in text or "Signals" in text
    assert "cyber" in text and "conflict" in text
    assert "Ransomware breach at bank" in text
    assert "Missile strike near border" in text


def test_signal_section_is_bounded_per_domain(tmp_path):
    """A noisy day must not turn the brief into a wall of text."""
    q = _queue(tmp_path)
    titles = [f"signal number {i}" for i in range(20)]
    text = build_morning_brief(q, signal_briefs=[_brief("cyber", 20, titles)])
    # the count is honest even though the listing is capped
    assert "20" in text
    assert text.count("signal number") <= 5


def test_malformed_briefs_never_break_the_brief(tmp_path):
    """Digest building must never raise — a bad payload degrades to no section."""
    q = _queue(tmp_path)
    base = build_morning_brief(q)
    for junk in ("not-a-list", [None], [{"no": "domain"}], [{"domain": "x", "top": "nope"}]):
        text = build_morning_brief(q, signal_briefs=junk)
        assert isinstance(text, str)
        assert text.startswith("☀️")
    # a wholly unusable payload adds nothing at all
    assert build_morning_brief(q, signal_briefs="not-a-list") == base


# ── the caller half: the sidecar read that feeds the builder ──────────────────

def _orch_with(signals_payload):
    from types import SimpleNamespace

    async def signals(**kwargs):
        return signals_payload

    return SimpleNamespace(plugins={"signal-layer": SimpleNamespace(signals=signals)})


def test_caller_returns_none_without_a_sidecar():
    import asyncio
    from types import SimpleNamespace

    from agents.core.scheduler_service import _signal_briefs_or_none

    assert asyncio.run(_signal_briefs_or_none(SimpleNamespace(plugins={}))) is None


def test_caller_returns_none_when_the_sidecar_is_unavailable():
    import asyncio

    from agents.core.scheduler_service import _signal_briefs_or_none

    orch = _orch_with({"status": "unavailable", "detail": "refused"})
    assert asyncio.run(_signal_briefs_or_none(orch)) is None


def test_caller_returns_none_on_a_quiet_day_rather_than_empty_briefs():
    import asyncio

    from agents.core.scheduler_service import _signal_briefs_or_none

    orch = _orch_with({"status": "ok", "signals": []})
    assert asyncio.run(_signal_briefs_or_none(orch)) is None


def test_caller_routes_one_fetch_into_per_domain_briefs():
    """One sidecar read, routed into every reported domain — not one fetch each."""
    import asyncio
    from types import SimpleNamespace

    from agents.core.scheduler_service import _signal_briefs_or_none

    calls = []

    async def signals(**kwargs):
        calls.append(kwargs)
        return {"status": "ok", "signals": [
            {"title": "Ransomware breach", "summary": "malware", "severity": 5},
            {"title": "Missile strike", "summary": "artillery", "severity": 4},
            {"title": "Totally unclassifiable", "summary": "nothing", "severity": 1},
        ]}

    orch = SimpleNamespace(plugins={"signal-layer": SimpleNamespace(signals=signals)})
    briefs = asyncio.run(_signal_briefs_or_none(orch))

    assert len(calls) == 1, "must read the sidecar once, not once per domain"
    domains = {b["domain"] for b in briefs}
    assert domains == {"cyber", "conflict"}      # only domains with hits are kept
    assert all(b["count"] > 0 for b in briefs)


def test_caller_never_raises_when_the_sidecar_explodes():
    import asyncio
    from types import SimpleNamespace

    from agents.core.scheduler_service import _signal_briefs_or_none

    async def boom(**kwargs):
        raise RuntimeError("sidecar down")

    orch = SimpleNamespace(plugins={"signal-layer": SimpleNamespace(signals=boom)})
    assert asyncio.run(_signal_briefs_or_none(orch)) is None
