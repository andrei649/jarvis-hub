"""ORIZONT-24 V3 — cross-agent interface-contract drift guard.

The kernel ``Action`` / ``Decision`` / ``Capability`` / ``Budget`` dataclasses are THE
shared contract every privileged action crosses — Gate-K routes all 11 action kinds
through ``authorize(Action) -> Decision`` — and the A2A pydantic bodies are the
agent-to-agent wire schema. If a field is added / removed / renamed / retyped, or an
enum value changes, N parallel agents (and the brokers/routes/MCP tools that build these
objects) can silently break each other.

This snapshots those structured contracts and fails CI on any drift, so a contract change
must be **conscious** — exactly like the route-auth / action-auth snapshot gates. It is
the "multiplier-risk" half of V3 (interface-contract drift across the fleet).

Regenerate after an INTENTIONAL change:
    python tests/test_interface_contract_drift.py --update
"""
import dataclasses
import json
from enum import Enum
from pathlib import Path

SNAP = Path(__file__).parent / "_snapshots" / "interface_contracts.json"


def _type_str(ann) -> str:
    """Stable, readable type label. Dataclass annotations are strings (the kernel uses
    ``from __future__ import annotations``); pydantic annotations are live types."""
    if isinstance(ann, str):
        return ann
    return getattr(ann, "__name__", None) or str(ann).replace("typing.", "")


def _schema_of(obj):
    """A canonical schema for a contract: enum → sorted values; model/dataclass → field map."""
    if isinstance(obj, type) and issubclass(obj, Enum):
        return sorted(m.value for m in obj)
    if hasattr(obj, "model_fields"):                       # pydantic BaseModel
        return {n: _type_str(f.annotation) for n, f in obj.model_fields.items()}
    if dataclasses.is_dataclass(obj):
        return {f.name: _type_str(f.type) for f in dataclasses.fields(obj)}
    raise TypeError(f"unsupported contract object {obj!r}")


def _live_contracts() -> dict:
    from agents.core.kernel import Action, Budget, Capability, Decision, Verdict
    from agents.core.kernel.registry import Mediation
    from agents.core.routers.a2a import A2ACardBody, A2ADecisionBody, A2APeerBody

    classes = {
        "kernel.Action": Action,
        "kernel.Decision": Decision,
        "kernel.Capability": Capability,
        "kernel.Budget": Budget,
        "kernel.Verdict": Verdict,
        "kernel.registry.Mediation": Mediation,
        "a2a.A2APeerBody": A2APeerBody,
        "a2a.A2ACardBody": A2ACardBody,
        "a2a.A2ADecisionBody": A2ADecisionBody,
    }
    return {k: _schema_of(v) for k, v in classes.items()}


def test_contracts_cover_the_expected_surface():
    """A contract silently disappearing (e.g. a refactor drops the import) is itself drift."""
    live = _live_contracts()
    snap = json.loads(SNAP.read_text())
    missing = sorted(set(snap) - set(live))
    added = sorted(set(live) - set(snap))
    assert not missing, f"contract(s) vanished from the live surface: {missing}"
    assert not added, (
        f"NEW contract(s) not in the snapshot: {added}. If intended, regenerate "
        "with: python tests/test_interface_contract_drift.py --update")


def test_interface_contracts_match_snapshot():
    live = _live_contracts()
    snap = json.loads(SNAP.read_text())
    problems = []
    for name in sorted(set(live) & set(snap)):
        lo, sn = live[name], snap[name]
        if isinstance(sn, list):                          # enum value set
            if sorted(lo) != sorted(sn):
                problems.append(f"{name}: enum values {sn} -> {lo}")
            continue
        gone = sorted(set(sn) - set(lo))
        new = sorted(set(lo) - set(sn))
        retyped = sorted(f"{f} ({sn[f]}->{lo[f]})" for f in lo if f in sn and lo[f] != sn[f])
        if gone:
            problems.append(f"{name}: removed/renamed field(s) {gone}")
        if new:
            problems.append(f"{name}: new field(s) {new}")
        if retyped:
            problems.append(f"{name}: retyped {retyped}")
    assert not problems, (
        "Cross-agent interface contract changed. If intended, regenerate "
        "tests/_snapshots/interface_contracts.json with:\n"
        "  python tests/test_interface_contract_drift.py --update\n" + "\n".join(problems))


def test_introspection_actually_resolves_fields():
    """Guard the guard: a broken introspector that returns {} would make drift invisible."""
    live = _live_contracts()
    assert live["kernel.Action"].get("kind") == "str"
    assert "grant" in live["kernel.Verdict"]
    assert live["a2a.A2ADecisionBody"] == {"approve": "bool"}


if __name__ == "__main__":
    import sys

    if "--update" in sys.argv:
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(_live_contracts(), indent=2, sort_keys=True) + "\n")
        print(f"wrote {SNAP}")
    else:
        print(json.dumps(_live_contracts(), indent=2, sort_keys=True))
