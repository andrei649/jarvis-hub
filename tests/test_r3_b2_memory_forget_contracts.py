"""R3-B2: live contract gates for KG writes and destructive forget."""

import asyncio
import sqlite3
from pathlib import Path

import pytest

import agents.web as web
from agents.core import data_purge as dp
from agents.core.automation_contracts import ContractDecision
from agents.core.memory.bitemporal import BiTemporalKG
from agents.core.memory.graph import InMemoryGraph
from agents.core.memory.incremental import IncrementalKGUpdater
from agents.core.routers import backup, memory_kg


class _DenyContract:
    def __init__(self, reason: str = "contract_blocked"):
        self.reason = reason
        self.calls: list[dict] = []

    def evaluate(self, payload, **kwargs):
        self.calls.append(dict(payload or {}))
        return ContractDecision(
            kind=str((payload or {}).get("kind") or "test"),
            admissible=False,
            requires_approval=True,
            reason=self.reason,
        )


class _Req:
    def __init__(self, body, headers=None):
        self._body = body
        self.headers = headers or {}

    async def json(self):
        return self._body


def _run(coro):
    return asyncio.run(coro)


def _status(resp):
    return getattr(resp, "status_code", 200)


def _orch(tmp_path):
    graph = InMemoryGraph()

    class _Mem:
        pass

    mem = _Mem()
    mem.graph = graph

    class _Orch:
        memory = mem
        bitemporal = BiTemporalKG(tmp_path / "bt.json")
        kg_updater = IncrementalKGUpdater(graph)
        capabilities = None
        autonomy_policy = None
        intent_log = None

    return _Orch(), graph


def _seed_db(path: Path, table: str, rows: int) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany(f"INSERT INTO {table} (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
        conn.commit()
    finally:
        conn.close()


def _count(path: Path, table: str) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_kg_contract_denial_blocks_entity_write_before_mutation(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, graph = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    contract = _DenyContract()
    monkeypatch.setattr(memory_kg, "KG_WRITE_CONTRACT", contract, raising=False)

    resp = _run(memory_kg.kg_upsert_entity(_Req({"name": "Probe", "type": "person"})))

    assert _status(resp) == 403
    assert graph.get_entity("Probe") is None
    assert contract.calls[0]["op"] == "add_entity"


def test_kg_contract_denial_blocks_relation_fact_and_ingest(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, graph = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    contract = _DenyContract()
    monkeypatch.setattr(memory_kg, "KG_WRITE_CONTRACT", contract, raising=False)
    graph.add_entity("A", "person")
    graph.add_entity("B", "person")

    rel = _run(memory_kg.kg_add_relation(_Req({"source": "A", "relation": "KNOWS", "target": "B"})))
    fact = _run(memory_kg.kg_add_fact(_Req({"subject": "A", "predicate": "likes", "object": "B"})))
    ingest = _run(memory_kg.kg_ingest(_Req({"text": "Alice works at ExampleCo."})))

    assert [_status(rel), _status(fact), _status(ingest)] == [403, 403, 403]
    assert graph.get_relations("A") == []
    assert orch.bitemporal.history("A") == []
    assert {call["op"] for call in contract.calls} == {"add_relation", "add_fact", "ingest"}


def test_purge_data_contract_denial_preserves_files(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    _seed_db(root / "missions.db", "missions", 2)
    (root / "notes.json").write_text('{"private": true}', encoding="utf-8")
    contract = _DenyContract()
    monkeypatch.setattr(dp, "DATA_PURGE_CONTRACT", contract, raising=False)

    with pytest.raises(dp.PurgeError, match="contract_blocked"):
        dp.purge_data(source_root=str(root), backup_first=False)

    assert _count(root / "missions.db", "missions") == 2
    assert (root / "notes.json").read_text(encoding="utf-8") == '{"private": true}'
    assert contract.calls[0]["action"] == "purge_data"


def test_forget_route_contract_denial_precedes_live_clear_and_purge(monkeypatch):
    calls = {"clear": 0, "purge": 0}
    contract = _DenyContract()
    monkeypatch.setattr(backup._purge, "DATA_PURGE_CONTRACT", contract, raising=False)

    class _Conv:
        sessions = {"sess-1": []}

    class _Mem:
        conversation = _Conv()

    class _Orch:
        memory = _Mem()

    async def _clear(_orch):
        calls["clear"] += 1
        return ["conversation"]

    def _purge_data(**kwargs):
        calls["purge"] += 1
        return {"ok": True}

    monkeypatch.setattr(backup, "get_orch", lambda: _Orch())
    monkeypatch.setattr(backup._purge, "clear_live_memory", _clear)
    monkeypatch.setattr(backup._purge, "purge_data", _purge_data)

    resp = _run(backup.forget_data(_Req({"confirm": "FORGET"})))

    assert _status(resp) == 403
    assert calls == {"clear": 0, "purge": 0}
    assert contract.calls[0]["action"] == "purge_data"
