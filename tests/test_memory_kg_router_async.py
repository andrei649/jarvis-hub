"""Request-path hygiene for the memory/KG router: blocking store calls must run
off the event-loop thread (asyncio.to_thread), mirroring the admin-router audit
pattern. Two deterministic proof styles:

* thread-identity-at-seam — every graph/bitemporal/decay/consolidation call
  records a thread id that must differ from the loop's;
* block-until-freed interleaving — while a graph write is pinned mid-flight by
  an event only the test coroutine can set, the loop must keep scheduling.
"""
import asyncio
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web
from agents.core.memory.bitemporal import BiTemporalKG
from agents.core.memory.consolidation import ConsolidationEngine
from agents.core.memory.decay import DecayMemory
from agents.core.memory.entity import EntityStore
from agents.core.memory.graph import InMemoryGraph
from agents.core.routers import memory_kg


class _Req:
    def __init__(self, body=None, headers=None):
        self._body = body or {}
        self.headers = headers or {}

    async def json(self):
        return self._body


class _Mem:
    pass


class SpyGraph(InMemoryGraph):
    """InMemoryGraph that records which OS thread each op ran on."""

    def __init__(self):
        super().__init__()
        self.call_threads: dict[str, list[int]] = {}

    def _record(self, op):
        self.call_threads.setdefault(op, []).append(threading.get_ident())

    def add_entity(self, name, entity_type, properties=None):
        self._record("add_entity")
        return super().add_entity(name, entity_type, properties)

    def add_relation(self, source, relation, target, properties=None):
        self._record("add_relation")
        return super().add_relation(source, relation, target, properties)

    def get_entity(self, name):
        self._record("get_entity")
        return super().get_entity(name)

    def get_relations(self, name, direction="both"):
        self._record("get_relations")
        return super().get_relations(name, direction)

    def search(self, keyword):
        self._record("search")
        return super().search(keyword)

    def list_entities(self, limit=100):
        self._record("list_entities")
        return super().list_entities(limit)

    def delete_entity(self, name):
        self._record("delete_entity")
        return super().delete_entity(name)

    def delete_relation(self, source, relation, target):
        self._record("delete_relation")
        return super().delete_relation(source, relation, target)


class SpyBiTemporal(BiTemporalKG):
    def __init__(self, path):
        super().__init__(path)
        self.call_threads: dict[str, list[int]] = {}

    def _record(self, op):
        self.call_threads.setdefault(op, []).append(threading.get_ident())

    def add_fact(self, subject, predicate, obj, valid_from=None,
                 ingested_at=None, multi=False):
        self._record("add_fact")
        return super().add_fact(subject, predicate, obj, valid_from=valid_from,
                                ingested_at=ingested_at, multi=multi)

    def as_of(self, at=None, subject="", predicate=""):
        self._record("as_of")
        return super().as_of(at, subject, predicate)

    def history(self, subject, predicate=""):
        self._record("history")
        return super().history(subject, predicate)


class SpyDecay(DecayMemory):
    def __init__(self, path):
        super().__init__(path)
        self.call_threads: dict[str, list[int]] = {}

    def _record(self, op):
        self.call_threads.setdefault(op, []).append(threading.get_ident())

    def ranking(self, now=None, limit=100):
        self._record("ranking")
        return super().ranking(now, limit=limit)

    def forget_candidates(self, threshold, now=None):
        self._record("forget_candidates")
        return super().forget_candidates(threshold, now=now)

    def forget(self, item_id):
        self._record("forget")
        return super().forget(item_id)


class SpyConsolidation(ConsolidationEngine):
    def __init__(self):
        super().__init__()
        self.call_threads: dict[str, list[int]] = {}

    def plan(self, candidates, existing):
        self.call_threads.setdefault("plan", []).append(threading.get_ident())
        return super().plan(candidates, existing)


def _orch(tmp_path, graph=None, bitemporal=None, decay=None, consolidation=None):
    from agents.core.memory.incremental import IncrementalKGUpdater

    graph = graph if graph is not None else InMemoryGraph()
    mem = _Mem()
    mem.graph = graph
    bt = bitemporal if bitemporal is not None else BiTemporalKG(tmp_path / "bt.json")
    return SimpleNamespace(
        memory=mem,
        entities=EntityStore(tmp_path / "entities.json"),
        bitemporal=bt,
        decay=decay if decay is not None else DecayMemory(tmp_path / "decay.json"),
        kg_updater=IncrementalKGUpdater(graph, bt),
        consolidation=consolidation if consolidation is not None else ConsolidationEngine(),
    )


def _off_loop_ids(call_threads):
    """Thread ids recorded at the seams, flattened."""
    return {tid for ids in call_threads.values() for tid in ids}


# ── liveness: the loop keeps scheduling while a graph write is pinned ────────

async def test_kg_write_keeps_loop_responsive_while_graph_call_blocks(
        tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    graph = InMemoryGraph()
    started = threading.Event()
    release = threading.Event()

    def slow_add_entity(name, entity_type, properties=None):
        started.set()
        # Held until the TEST coroutine (loop thread) lets go — impossible if
        # the handler runs this on the loop itself.
        assert release.wait(timeout=10)
        return True

    monkeypatch.setattr(graph, "add_entity", slow_add_entity)
    monkeypatch.setattr(web, "orch", _orch(tmp_path, graph=graph))

    # Watchdog: even if the fix regresses and the loop stalls, free the worker
    # so this fails fast instead of hanging to the 30s suite backstop.
    timer = threading.Timer(2.0, release.set)
    timer.start()
    try:
        task = asyncio.ensure_future(memory_kg.kg_upsert_entity(
            _Req({"name": "Probe", "type": "person"})))

        ticks_while_waiting = 0
        while not started.is_set() and ticks_while_waiting < 1000:
            await asyncio.sleep(0.001)  # each tick proves the loop is free
            ticks_while_waiting += 1

        ticks_during_block = 0
        if not release.is_set():
            # We beat the watchdog: the call is pinned mid-flight and only the
            # loop can free it. Every one of these ticks is a scheduling slice
            # that happens WHILE the blocking call has not returned.
            for _ in range(10):
                await asyncio.sleep(0.001)
                assert not release.is_set()
                ticks_during_block += 1

        release.set()
        resp = await asyncio.wait_for(task, timeout=5)
    finally:
        timer.cancel()

    assert getattr(resp, "status_code", 200) == 200
    # The loop demonstrably kept scheduling before AND during the blocked call.
    # (A regressed handler stalls the loop, so the watchdog fires first and
    # ticks_during_block stays 0 — this assert is what catches the regression.)
    assert ticks_while_waiting >= 1
    assert ticks_during_block == 10


# ── thread identity at every seam ─────────────────────────────────────────────

async def test_kg_graph_ops_run_off_the_loop_thread(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    loop_tid = threading.get_ident()
    graph = SpyGraph()
    bt = BiTemporalKG(tmp_path / "bt.json")
    orch = _orch(tmp_path, graph=graph, bitemporal=bt)
    monkeypatch.setattr(web, "orch", orch)
    graph.add_entity("A", "person")  # seed
    graph.call_threads.clear()       # only handler-reached ops count

    await memory_kg.kg_entities(q="", limit=100)
    await memory_kg.kg_entities(q="A", limit=100)   # search arm
    await memory_kg.kg_entity("A")
    await memory_kg.kg_upsert_entity(_Req({"name": "B", "type": "person"}))
    await memory_kg.kg_add_relation(_Req({"source": "A", "relation": "KNOWS", "target": "B"}))
    await memory_kg.kg_delete_relation(source="A", relation="KNOWS", target="B", req=_Req())
    await memory_kg.kg_delete_entity("B")
    await memory_kg.kg_ingest(_Req({"text": "Alice works at ExampleCo."}))

    seen = _off_loop_ids(graph.call_threads)
    assert seen, "no graph ops were observed"
    assert all(tid != loop_tid for tid in seen), (
        f"graph ops ran on the event-loop thread: "
        f"{ {op: [t == loop_tid for t in ids] for op, ids in graph.call_threads.items()} }")


async def test_bitemporal_ops_run_off_the_loop_thread(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    loop_tid = threading.get_ident()
    graph = InMemoryGraph()
    bt = SpyBiTemporal(tmp_path / "bt.json")
    monkeypatch.setattr(web, "orch", _orch(tmp_path, graph=graph, bitemporal=bt))

    await memory_kg.kg_add_fact(_Req({"subject": "A", "predicate": "likes", "object": "B"}))
    await memory_kg.kg_facts_as_of(subject="A")
    await memory_kg.kg_facts_history(subject="A")

    seen = _off_loop_ids(bt.call_threads)
    assert {"add_fact", "as_of", "history"} <= set(bt.call_threads), bt.call_threads
    assert all(tid != loop_tid for tid in seen), (
        f"bitemporal ops ran on the event-loop thread: {bt.call_threads}")


async def test_decay_routes_run_off_the_loop_thread(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    loop_tid = threading.get_ident()
    decay = SpyDecay(tmp_path / "decay.json")
    monkeypatch.setattr(web, "orch", _orch(tmp_path, decay=decay))
    decay.add("item-1", label="probe")

    ranked = await memory_kg.memory_decay_ranking(limit=10)
    cands = await memory_kg.memory_decay_candidates(threshold=999.0)
    await memory_kg.memory_decay_forget(_Req({"id": "item-1"}))

    assert json.loads(ranked.body)["ranking"], "expected at least one ranked item"
    assert json.loads(cands.body)["candidates"], "expected threshold above every activation"
    seen = _off_loop_ids(decay.call_threads)
    assert {"ranking", "forget_candidates", "forget"} <= set(decay.call_threads), decay.call_threads
    assert all(tid != loop_tid for tid in seen), (
        f"decay ops ran on the event-loop thread: {decay.call_threads}")


async def test_structured_recall_tool_runs_off_the_loop_thread(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    loop_tid = threading.get_ident()
    graph = SpyGraph()
    monkeypatch.setattr(web, "orch", _orch(tmp_path, graph=graph))
    graph.add_entity("Alpha", "person")  # seed
    graph.call_threads.clear()           # only handler-reached ops count

    resp = await memory_kg.memory_search_tool(_Req({"query": "Alpha"}))

    assert resp.body and b"Alpha" in resp.body
    assert "search" in graph.call_threads, "graph.search was never reached"
    assert all(tid != loop_tid for tid in _off_loop_ids(graph.call_threads)), (
        f"structured recall ran on the event-loop thread: {graph.call_threads}")


async def test_consolidation_plan_runs_off_the_loop_thread(monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    loop_tid = threading.get_ident()
    engine = SpyConsolidation()
    monkeypatch.setattr(web, "orch", type("O", (), {"consolidation": engine})())

    resp = await memory_kg.memory_consolidate(
        _Req({"candidates": [{"text": "Owner lives in Cluj"}],
              "existing": [{"id": "m1", "text": "Owner lives in Cluj"}]}))

    assert getattr(resp, "status_code", 200) == 200
    assert "plan" in engine.call_threads, engine.call_threads
    assert all(tid != loop_tid for tid in _off_loop_ids(engine.call_threads)), (
        f"consolidation plan ran on the event-loop thread: {engine.call_threads}")
