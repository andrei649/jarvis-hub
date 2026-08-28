"""T-0.37 — provenance for the DERIVED ingestion phases (knowledge + embeddings).

`provenance.py`'s own docstring already names `"knowledge"` and `"embed"` as
expected phases and documents `parent_id` as the link that lets a chain
"embedding ← message ← file" be walked with `lineage`. The pipeline only ever
recorded the `parse` phase, so the derived half of that design was never wired:
an extracted entity or an embedding had no auditable origin.

These tests pin the wiring *and* the two properties that make it worth having:
lineage actually resolves derived → source, and the whole thing stays opt-in
(no ledger ⇒ ingestion behaves byte-identically, which is the default install).
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.ingestion.normalizer import NormalizedMessage  # noqa: E402
from agents.core.ingestion.pipeline import IngestionPipeline  # noqa: E402
from agents.core.ingestion.provenance import ProvenanceLedger  # noqa: E402


def _msg(text, sender="alice", conv="c1", source="facebook", is_me=False):
    return NormalizedMessage(
        source=source, conversation_id=conv, sender=sender,
        text=text, timestamp=0.0, is_me=is_me,
    )


def _pipeline(tmp_path, ledger=None):
    return IngestionPipeline(
        data_root=str(tmp_path / "in"),
        output_root=str(tmp_path / "out"),
        ledger=ledger,
        clock=lambda: 1000.0,
    )


def _ledger(tmp_path):
    return ProvenanceLedger(path=str(tmp_path / "prov.json"))


# ── the derived recorder ──────────────────────────────────────────────────────

def test_derived_records_carry_the_phase_and_a_parent_link(tmp_path):
    ledger = _ledger(tmp_path)
    p = _pipeline(tmp_path, ledger)
    msgs = [_msg("Alice went to Berlin")]
    p._record_provenance(msgs, source="facebook", phase="parse", run_id="r1", now=1.0)
    parent = ledger.recent(limit=1000)[0]

    n = p._record_derived_provenance(
        [("Alice", {"kind": "entity"})],
        source="facebook", phase="knowledge", run_id="r1", now=2.0,
        parent_id=parent["id"],
    )

    assert n == 1
    derived = [r for r in ledger.recent(limit=1000) if r["phase"] == "knowledge"]
    assert len(derived) == 1
    assert derived[0]["parent_id"] == parent["id"]
    assert derived[0]["meta"]["kind"] == "entity"


def test_lineage_walks_from_a_derived_artifact_back_to_its_source(tmp_path):
    """The point of parent_id: an entity must be traceable to the message it
    came from, which is what makes the ledger auditable rather than decorative."""
    ledger = _ledger(tmp_path)
    p = _pipeline(tmp_path, ledger)
    p._record_provenance([_msg("Alice went to Berlin")],
                         source="facebook", phase="parse", run_id="r1", now=1.0)
    parent = ledger.recent(limit=1000)[0]
    p._record_derived_provenance(
        [("Alice", {"kind": "entity"})], source="facebook", phase="knowledge",
        run_id="r1", now=2.0, parent_id=parent["id"],
    )
    child = [r for r in ledger.recent(limit=1000) if r["phase"] == "knowledge"][0]

    chain = ledger.lineage(child["id"])
    phases = [r["phase"] for r in chain]
    assert "knowledge" in phases and "parse" in phases


def test_derived_recorder_is_a_no_op_without_a_ledger(tmp_path):
    p = _pipeline(tmp_path, ledger=None)
    assert p._record_derived_provenance(
        [("x", {})], source="s", phase="knowledge", run_id="r", now=1.0) == 0


def test_a_ledger_hiccup_never_breaks_ingestion(tmp_path):
    class Broken:
        def record(self, **kw):
            raise RuntimeError("disk full")

    p = _pipeline(tmp_path, ledger=Broken())
    # must not raise — provenance is best-effort by contract
    assert p._record_derived_provenance(
        [("x", {})], source="s", phase="knowledge", run_id="r", now=1.0) == 0


def test_blank_artifacts_are_skipped_not_recorded_as_empty(tmp_path):
    ledger = _ledger(tmp_path)
    p = _pipeline(tmp_path, ledger)
    n = p._record_derived_provenance(
        [("", {}), ("   ", {}), ("real", {})],
        source="s", phase="knowledge", run_id="r", now=1.0,
    )
    assert n == 1


# ── the run() wiring ──────────────────────────────────────────────────────────

def test_run_records_knowledge_and_embed_phases(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    p = _pipeline(tmp_path, ledger)

    msgs = [_msg("Alice went to Berlin"), _msg("Bob likes coffee", sender="bob")]
    monkeypatch.setattr(p.fb_parser, "parse_directory", lambda d: iter(msgs))
    monkeypatch.setattr(p.wa_parser, "parse_directory", lambda d: iter([]))
    monkeypatch.setattr(p.embedder, "embed_many", lambda m: None)
    # Populate the extractor deterministically instead of relying on its NLP:
    # this test covers the PROVENANCE wiring (whatever knowledge is extracted
    # gets recorded), not extraction quality. Verified against the real
    # extractor that plain sentences like these yield no entities at all, which
    # would otherwise make this assertion pass or fail for unrelated reasons.
    def _fake_extract(_messages):
        p.knowledge.entities["Alice"] = object()
        p.knowledge.relationships["Alice→Berlin"] = object()
    monkeypatch.setattr(p.knowledge, "extract", _fake_extract)
    monkeypatch.setattr(p.knowledge, "save", lambda: None)

    p.run()

    phases = {r["phase"] for r in ledger.recent(limit=1000)}
    assert "parse" in phases
    assert "knowledge" in phases, "extracted knowledge must carry provenance"
    assert "embed" in phases, "embeddings must carry provenance"


def test_decisions_are_recorded_with_their_trigger_text(tmp_path, monkeypatch):
    """Regression: the run() wiring must record REAL DecisionPattern objects.

    An earlier revision read `d.text`/`d.pattern` — attributes DecisionPattern
    has never had — so every decision mapped to "" and was skipped by the
    blank-content guard: zero decision records, silently. The faked-extractor
    test above never caught it because it only populated entities and
    relationships, so this test goes through a real DecisionPattern.
    """
    from agents.core.ingestion.knowledge import DecisionPattern
    from agents.core.ingestion.provenance import content_fingerprint

    ledger = _ledger(tmp_path)
    p = _pipeline(tmp_path, ledger)
    monkeypatch.setattr(p.fb_parser, "parse_directory",
                        lambda d: iter([_msg("I decided to move to Berlin", is_me=True)]))
    monkeypatch.setattr(p.wa_parser, "parse_directory", lambda d: iter([]))
    monkeypatch.setattr(p.embedder, "embed_many", lambda m: None)

    def _fake_extract(_messages):
        p.knowledge.decisions.append(DecisionPattern(
            trigger_text="I decided to move to Berlin", context="",
            timestamp=0.0, outcome="moved", topic="relocation",
        ))
    monkeypatch.setattr(p.knowledge, "extract", _fake_extract)
    monkeypatch.setattr(p.knowledge, "save", lambda: None)

    p.run()

    decisions = [r for r in ledger.recent(limit=1000)
                 if r["phase"] == "knowledge" and r["meta"].get("kind") == "decision"]
    assert decisions, "a DecisionPattern must produce a knowledge/decision record"
    assert decisions[0]["content_hash"] == content_fingerprint("I decided to move to Berlin")
    assert decisions[0]["meta"]["topic"] == "relocation"
    assert decisions[0]["meta"]["outcome"] == "moved"


def test_record_many_is_one_write_cycle_and_matches_record(tmp_path, monkeypatch):
    """The batch path must behave like N record() calls but write the file once."""
    from agents.core.ingestion import provenance as prov_mod

    ledger = _ledger(tmp_path)
    writes = []
    original = prov_mod.ProvenanceLedger._write_atomic

    def _counting_write(self, items):
        writes.append(len(items))
        return original(self, items)
    monkeypatch.setattr(prov_mod.ProvenanceLedger, "_write_atomic", _counting_write)

    stored = ledger.record_many([
        {"source": "s", "origin": "c1", "phase": "parse", "content": f"m{i}",
         "run_id": "r1", "now": float(i)}
        for i in range(5)
    ])
    assert len(stored) == 5
    assert writes == [5], "a 5-record batch must rewrite the ledger exactly once"
    assert [r["content_hash"] for r in ledger.by_run("r1")] \
        == [r["content_hash"] for r in stored]


def test_embed_records_link_back_to_their_source_message(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    p = _pipeline(tmp_path, ledger)
    monkeypatch.setattr(p.fb_parser, "parse_directory",
                        lambda d: iter([_msg("Alice went to Berlin")]))
    monkeypatch.setattr(p.wa_parser, "parse_directory", lambda d: iter([]))
    monkeypatch.setattr(p.embedder, "embed_many", lambda m: None)

    p.run()

    embed = [r for r in ledger.recent(limit=1000) if r["phase"] == "embed"]
    assert embed, "expected an embed provenance record"
    assert all(r["parent_id"] for r in embed), "an embedding must name its source message"
    parents = {r["id"] for r in ledger.recent(limit=1000) if r["phase"] == "parse"}
    assert all(r["parent_id"] in parents for r in embed)


def test_default_pipeline_without_a_ledger_records_nothing(tmp_path, monkeypatch):
    """Opt-in by construction: the default install writes no provenance at all."""
    p = _pipeline(tmp_path, ledger=None)
    monkeypatch.setattr(p.fb_parser, "parse_directory", lambda d: iter([_msg("hi")]))
    monkeypatch.setattr(p.wa_parser, "parse_directory", lambda d: iter([]))
    monkeypatch.setattr(p.embedder, "embed_many", lambda m: None)
    result = p.run()          # must simply not raise, and write no ledger file
    assert result
    assert not (tmp_path / "prov.json").exists()
