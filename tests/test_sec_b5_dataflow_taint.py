"""SEC-B5 — taint by dataflow, not just declared origin.

The taint flag (``security.taint``) is only applied at the *declared ingestion
source*. Payloads REBUILT from tainted source material elsewhere — outside an
inbound turn — previously dropped the flag, so the derived content reached the
queue/kernel as if it were trusted. This file is the regression gate for the
first bounded slice of dataflow taint propagation: a derived payload must carry
the taint flag even though it was never marked at its origin.

Covered derived-content paths:

1. Proactive suggestions derived from tainted context — ``TechScout`` rebuilds a
   finding payload from taint-marked ``websearch`` results but submitted with
   ``origin="generated"``, so the derived task payload lost the ingress taint
   (``agents/core/autonomy/tech_scout.py``).
2. Ambient notes from tainted sources — ``AmbientProposalSink`` rebuilt a
   governed-intake payload from an ``AmbientEvent`` and dropped the event's
   ``tainted`` flag (``agents/core/ambient/proposals.py``). The decision ladder
   already downgrades tainted events to ASK; this slice makes the payload carry
   the flag as defense-in-depth so a bypassed/misconfigured ladder can never
   auto-execute untrusted material.
3. Recall from legacy tainted memory — the retired WorldView writer no longer
   runs, but previously stored OSINT entities must remain untrusted through
   graph recall and the RAG guard. These tests seed that historical shape directly.

"""

from __future__ import annotations

import hashlib

import pytest

from agents.core.ambient.contracts import (
    AmbientDecision,
    AmbientEvent,
    EventProvenance,
    MonitorDefinition,
    MonitorPredicate,
)
from agents.core.ambient.proposals import AmbientProposalSink
from agents.core.autonomy import AutonomyPolicy, AutonomyWorker, TaskQueue
from agents.core.autonomy.tech_scout import TechScout
from agents.core.memory.fusion import FusedHit
from agents.core.memory.manager import MemoryManager
from agents.core.security import taint
from agents.core.security.rag_guard import provenance_from_hit, wrap_memory

# ── 1. proactive suggestions derived from tainted (websearch) context ─────────


async def test_tech_scout_finding_keeps_websearch_taint_on_derived_payload():
    queue = TaskQueue(db_path=":memory:").initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())

    result = {
        "title": "New Local Inference Engine",
        "url": "https://example.com/a",
        "snippet": "fast local LLM runtime",
    }

    async def search(query, max_results=5):
        return [result]

    scout = TechScout(worker, search, queries=["q"])
    await scout.scan(enabled=True)

    tasks = queue.list()
    assert len(tasks) == 1
    task = tasks[0]
    assert task.kind == "tech_scout.finding"
    # The finding is DERIVED from websearch source material: the rebuilt payload
    # must carry the ingress taint instead of silently becoming "generated".
    assert taint.is_tainted(task.payload) is True
    assert task.payload["taint_source"] == "websearch"
    assert task.origin == "websearch"


# ── 2. ambient notes from tainted sources ─────────────────────────────────────


def _ambient_event(*, tainted: bool) -> AmbientEvent:
    return AmbientEvent(
        source="camera",
        schema="camera.event.v1",
        source_event_id="cam-1",
        subject_id="camera.front",
        occurred_at=1_000,
        observed_at=1_001,
        dedupe_key="camera:cam-1",
        provenance=EventProvenance(adapter="camera.feed", version=1),
        attributes=(("anonymous", True), ("confidence", 0.9), ("label", "person")),
        consent_generation=4,
        tainted=tainted,
    )


def _ambient_definition() -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="monitor.front.person",
        version=1,
        source="camera",
        schema="camera.event.v1",
        predicates=(MonitorPredicate("attributes.label", "eq", "person"),),
        alert_rung="ask",
        recovery_rung="monitor",
    )


def _ambient_decision(event: AmbientEvent) -> AmbientDecision:
    return AmbientDecision(
        decision_id="decision-abc",
        monitor_id="monitor.front.person",
        monitor_version=1,
        monitor_hash=hashlib.sha256(b"m").hexdigest(),
        event_fingerprint=event.fingerprint,
        transition="alert",
        matched=True,
        reason="predicate_matched",
        decided_at=1_001,
        consent_generation=4,
        rung="ask",
        attention_mode="digest",
    )


def test_ambient_proposal_payload_carries_tainted_event_flag():
    calls: list[tuple] = []

    def govern_enqueue(*args, **kwargs):
        calls.append((args, kwargs))
        return 1

    sink = AmbientProposalSink(govern_enqueue, generation_provider=lambda: 9)
    event = _ambient_event(tainted=True)
    sink(_ambient_decision(event), event, _ambient_definition())

    assert len(calls) == 1
    payload = calls[0][1]["payload"]
    # The proposal is DERIVED from a tainted ambient event: its payload must
    # carry the flag so a bypassed/misconfigured ladder can never auto-execute.
    assert taint.is_tainted(payload) is True
    assert payload["taint_source"] == "ambient:camera"


def test_ambient_proposal_payload_stays_clean_for_trusted_event():
    calls: list[tuple] = []

    def govern_enqueue(*args, **kwargs):
        calls.append((args, kwargs))
        return 1

    sink = AmbientProposalSink(govern_enqueue, generation_provider=lambda: 9)
    event = _ambient_event(tainted=False)
    sink(_ambient_decision(event), event, _ambient_definition())

    payload = calls[0][1]["payload"]
    assert taint.is_tainted(payload) is False


# ── 3. recall from tainted memory (WorldView → graph → RAG guard) ─────────────






async def test_legacy_worldview_graph_recall_remains_untrusted():
    mm = MemoryManager()
    await mm.add_fact("Hormuz legacy observation", entity_type="geo_event",
                      properties=taint.mark({}, source="worldview"))

    hits = mm.graph.search("Hormuz")
    ev = next(h for h in hits if h["type"] == "geo_event")
    props = ev["properties"]
    # OSINT (WorldView) source material stored into memory must carry the taint.
    assert taint.is_tainted(props) is True
    assert props["taint_source"] == "worldview"

    # A graph recall of that entity must be recognised as untrusted by the RAG
    # guard, so the fenced prompt block is flagged (never trusted memory).
    hit = FusedHit(id=ev["name"], score=1.0, sources=["graph"], payload=ev)
    snippet = provenance_from_hit(hit)
    assert snippet.source == "worldview"
    assert taint.is_untrusted_source(snippet.source) is True
    assert wrap_memory([snippet], datamark=False).tainted is True


async def test_trusted_facts_stay_untainted():
    mm = MemoryManager()
    await mm.add_fact("Hormuz legacy observation", entity_type="geo_event",
                      properties=taint.mark({}, source="worldview"))
    await mm.add_fact(
        "Home server",
        entity_type="server",
        properties={"location": "living room"},
    )

    trusted = mm.graph.search("Home")
    assert any(h["type"] == "server" for h in trusted)
    server = next(h for h in trusted if h["type"] == "server")
    assert taint.is_tainted(server["properties"]) is False
