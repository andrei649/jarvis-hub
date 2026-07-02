"""ORIZONT-24 K1 wave-3/4b (kg.write slice) — externally-driven KG writes route through
the Action Kernel with a MANDATORY capability token; the high-frequency *internal*
ingestion path does NOT.

The whole point of this slice is the boundary: the `/api/kg/*` mutating HTTP handlers are
mediated (a halt blocks them), while the internal per-turn path (`IncrementalKGUpdater.ingest`
called from `orchestrator._record_interactions`, `seed_graph`, reflection) writes the graph
methods DIRECTLY and is never frozen. `test_boundary_internal_ingestion_alive_while_halted`
pins exactly that. Since wave-4b, a clean/no-token call mints its own short-lived operator
token (the caller already passed user_guard) so the real capability nucleus runs instead of
tolerating an empty token. Default-off behind `JARVIS_ACTION_KERNEL`.
"""
import asyncio

import agents.web as web
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import Decision, Verdict
from agents.core.memory.bitemporal import BiTemporalKG
from agents.core.memory.graph import InMemoryGraph
from agents.core.memory.incremental import IncrementalKGUpdater
from agents.core.routers import memory_kg as memkg
from agents.core.security.capability import CapabilityBroker, KillSwitch


def _orch(tmp_path, name="a"):
    graph = InMemoryGraph()

    class _Mem:
        pass
    mem = _Mem()
    mem.graph = graph

    class _Orch:
        memory = mem
        bitemporal = BiTemporalKG(tmp_path / f"{name}_bt.json")
        kg_updater = IncrementalKGUpdater(graph)
        kill_switch = KillSwitch(tmp_path / f"{name}_kill.json")
        capabilities = CapabilityBroker()
        autonomy_policy = AutonomyPolicy()
        intent_log = None
    return _Orch(), graph


class _Req:
    def __init__(self, body, headers=None):
        self._b, self.headers = body, (headers or {})

    async def json(self):
        return self._b


def _status(resp):
    return getattr(resp, "status_code", 200)


def _run(coro):
    return asyncio.run(coro)


# ── default-off: byte-identical (mediation skipped even with a bound DENY) ──────────
def test_flag_off_kg_writes_unmediated(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch, graph = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    # a bound DENY would block — but flag off means the gate never consults it
    monkeypatch.setattr("agents.core.kernel.binding.make_action_kernel",
                        lambda o: (lambda a, capability=None, budget=None: Decision(Verdict.DENY, reason="x")))
    assert _status(_run(memkg.kg_upsert_entity(_Req({"name": "Probe", "type": "person"})))) == 200
    assert graph.get_entity("Probe") is not None


# ── flag on, clean: mints its own operator token → real cross-check → allow ──────────
def test_flag_on_clean_allows_through(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch, graph = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)        # real bound kernel over the stub orch
    assert not orch.capabilities.list()
    assert _status(_run(memkg.kg_upsert_entity(_Req({"name": "Probe", "type": "person"})))) == 200
    assert graph.get_entity("Probe") is not None
    # wave-4b: the router minted its own kg:write operator token (no token was
    # presented) — proves the real capability nucleus ran, not a tolerated-empty skip.
    minted = orch.capabilities.list()
    assert len(minted) == 1 and minted[0]["capabilities"] == ["kg:write"]


# ── flag on, halted: every external KG-write handler is denied ──────────────────────
def test_flag_on_halt_denies_all_external_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch, graph = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    orch.kill_switch.engage("global", "test")
    assert _status(_run(memkg.kg_upsert_entity(_Req({"name": "X", "type": "person"})))) == 403
    assert _status(_run(memkg.kg_add_relation(_Req({"source": "A", "relation": "KNOWS", "target": "B"})))) == 403
    assert _status(_run(memkg.kg_add_fact(_Req({"subject": "A", "predicate": "likes", "object": "B"})))) == 403
    assert _status(_run(memkg.kg_ingest(_Req({"text": "A knows B"})))) == 403
    assert _status(_run(memkg.kg_delete_entity("X"))) == 403            # no-Request handler
    assert _status(_run(memkg.kg_delete_relation("A", "KNOWS", "B"))) == 403
    assert graph.list_entities(10) == []                               # nothing was written


# ── THE boundary proof: internal ingestion still writes while the external API is halted ──
def test_boundary_internal_ingestion_alive_while_halted(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch, graph = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    orch.kill_switch.engage("global", "emergency stop")

    # external /api/kg/ingest → blocked
    assert _status(_run(memkg.kg_ingest(_Req({"text": "external write"})))) == 403

    # internal path (what orchestrator._record_interactions calls) → STILL writes: it uses
    # kg_updater.ingest / graph.add_entity directly and never crosses the gated handler.
    orch.kg_updater.ingest("Andrei works at TestCo")
    graph.add_entity("DirectEntity", "person")
    assert graph.get_entity("DirectEntity") is not None
    assert graph.list_entities(50)                    # internal ingestion is not frozen


# ── recovery + the real capability cross-check ─────────────────────────────────────
def test_release_allows_external_write(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch, graph = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    orch.kill_switch.engage("global", "halt")
    assert _status(_run(memkg.kg_upsert_entity(_Req({"name": "X", "type": "person"})))) == 403
    orch.kill_switch.disengage("global")
    assert _status(_run(memkg.kg_upsert_entity(_Req({"name": "X", "type": "person"})))) == 200


def test_invalid_capability_token_denied(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch, _ = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    r = _run(memkg.kg_upsert_entity(
        _Req({"name": "Probe", "type": "person"}, headers={"x-capability-token": "bogus"})))
    assert _status(r) == 403   # nucleus: "no valid capability token for this action"


def test_explicitly_presented_valid_token_is_accepted_no_extra_mint(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch, graph = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    tok = orch.capabilities.issue(["kg:write"])["id"]
    r = _run(memkg.kg_upsert_entity(
        _Req({"name": "Probe", "type": "person"}, headers={"x-capability-token": tok})))
    assert _status(r) == 200
    # the presented token wins — no operator token was minted for this call.
    assert [t["id"] for t in orch.capabilities.list()] == [tok]


# ── wave-4b closed the structural gap: delete_entity/delete_relation now carry Request ──
def test_delete_entity_and_delete_relation_accept_request_and_mint(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch, graph = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    graph.add_entity("X", "person")
    graph.add_entity("A", "person")
    graph.add_entity("B", "person")
    graph.add_relation("A", "KNOWS", "B")   # independent of X, so deleting X leaves it intact

    # called with no Request at all (direct/non-HTTP call, e.g. this test) — still
    # works: the kernel helper mints its own operator token when none is presented.
    assert _status(_run(memkg.kg_delete_entity("X"))) == 200
    assert graph.get_entity("X") is None
    assert _status(_run(memkg.kg_delete_relation("A", "KNOWS", "B"))) == 200
    minted = orch.capabilities.list()
    assert len(minted) == 2 and all(t["capabilities"] == ["kg:write"] for t in minted)

    # called WITH a Request carrying an explicit token — that token wins.
    graph.add_entity("Z", "person")
    tok = orch.capabilities.issue(["kg:write"])["id"]
    r = _run(memkg.kg_delete_entity("Z", req=_Req({}, headers={"x-capability-token": tok})))
    assert _status(r) == 200
    assert graph.get_entity("Z") is None


# ── deny precedes the existence lookup (don't leak existence while halted) ──────────
def test_halt_missing_target_is_403_not_404(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch, _ = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    orch.kill_switch.engage("global", "halt")
    # the entity does not exist → would be 404 if looked up; the kernel deny precedes it
    assert _status(_run(memkg.kg_delete_entity("does-not-exist"))) == 403


# ── the Action the gate builds: right kind/origin, keys-only payload ────────────────
def test_action_kind_origin_and_payload_keys_only(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch, _ = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    seen = []

    def _spy(action, capability=None, budget=None):
        seen.append(action)
        return Decision(Verdict.GRANT, reason="spy")

    monkeypatch.setattr("agents.core.kernel.binding.make_action_kernel", lambda o: _spy)
    _run(memkg.kg_upsert_entity(_Req({"name": "Probe", "type": "person", "properties": {"secret": "PII"}})))
    assert seen and seen[-1].kind == "kg.write" and seen[-1].origin == "external"
    # payload carries keys/ids only — never the property VALUES
    assert seen[-1].payload == {"op": "add_entity", "name": "Probe", "type": "person"}
    assert "PII" not in str(seen[-1].payload)
