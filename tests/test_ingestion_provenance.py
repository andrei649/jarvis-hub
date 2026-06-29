"""0.37 — auditable provenance ledger for ingested memory.

Covers agents/core/ingestion/provenance.py: the content fingerprint, record
shape + required fields, query helpers (by_run/by_source), lineage chain walk
(incl. unknown id + cycle guard), tamper-evidence (verify), durable persistence
across instances, corrupt/missing-file safety, bounded oldest-first pruning, and
stats. Pure/offline — an injected ``now`` keeps timestamps deterministic.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.ingestion.provenance import (  # noqa: E402
    ProvenanceLedger,
    content_fingerprint,
)


def _ledger(tmp_path, **kw):
    return ProvenanceLedger(tmp_path / "prov.json", **kw)


def _rec(ledger, *, source="facebook", origin="inbox/x.json", phase="parse",
         content="hello", run_id="run-1", now=1000.0, parent_id=None, meta=None):
    return ledger.record(source=source, origin=origin, phase=phase, content=content,
                         run_id=run_id, now=now, parent_id=parent_id, meta=meta)


# ── fingerprint ───────────────────────────────────────────────────────────────

def test_fingerprint_is_stable_and_str_bytes_equivalent():
    assert content_fingerprint("hello") == content_fingerprint("hello")
    assert content_fingerprint("hello") == content_fingerprint(b"hello")
    assert content_fingerprint("a") != content_fingerprint("b")
    # known sha-256 of "hello"
    assert content_fingerprint("hello") == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


# ── record ────────────────────────────────────────────────────────────────────

def test_record_fields(tmp_path):
    led = _ledger(tmp_path)
    r = _rec(led, content="payload", meta={"k": "v"})
    assert r["id"].startswith("pv-")
    assert r["source"] == "facebook" and r["run_id"] == "run-1"
    assert r["origin"] == "inbox/x.json" and r["phase"] == "parse"
    assert r["content_hash"] == content_fingerprint("payload")
    assert r["produced_at"] == 1000.0 and r["parent_id"] is None
    assert r["meta"] == {"k": "v"}


def test_record_requires_source_and_run_id(tmp_path):
    led = _ledger(tmp_path)
    with pytest.raises(ValueError):
        _rec(led, source="  ")
    with pytest.raises(ValueError):
        _rec(led, run_id="")


# ── queries ─────────────────────────────────────────────────────────────────

def test_get_by_run_by_source(tmp_path):
    led = _ledger(tmp_path)
    a = _rec(led, source="facebook", run_id="r1", now=1)
    b = _rec(led, source="whatsapp", run_id="r1", now=2)
    c = _rec(led, source="facebook", run_id="r2", now=3)

    assert led.get(a["id"])["id"] == a["id"]
    assert led.get("missing") is None
    assert [x["id"] for x in led.by_run("r1")] == [a["id"], b["id"]]
    assert [x["id"] for x in led.by_source("facebook")] == [a["id"], c["id"]]


# ── lineage ───────────────────────────────────────────────────────────────────

def test_lineage_walks_parent_chain_to_root(tmp_path):
    led = _ledger(tmp_path)
    file_rec = _rec(led, phase="parse", content="raw", now=1)
    msg = _rec(led, phase="normalize", content="msg", now=2, parent_id=file_rec["id"])
    emb = _rec(led, phase="embed", content="vec", now=3, parent_id=msg["id"])

    chain = led.lineage(emb["id"])
    assert [c["id"] for c in chain] == [emb["id"], msg["id"], file_rec["id"]]
    # root has no parent
    assert chain[-1]["parent_id"] is None


def test_lineage_unknown_id_is_empty(tmp_path):
    led = _ledger(tmp_path)
    _rec(led)
    assert led.lineage("nope") == []


def test_lineage_is_cycle_safe(tmp_path):
    # craft a malformed self-cycle directly on disk; lineage must terminate
    led = _ledger(tmp_path)
    r = _rec(led)
    raw = (tmp_path / "prov.json")
    import json
    data = json.loads(raw.read_text())
    data[0]["parent_id"] = data[0]["id"]   # point at itself
    raw.write_text(json.dumps(data))
    chain = led.lineage(r["id"])
    assert [c["id"] for c in chain] == [r["id"]]   # visited-set stops the loop


# ── tamper-evidence ───────────────────────────────────────────────────────────

def test_verify_detects_tampering(tmp_path):
    led = _ledger(tmp_path)
    r = _rec(led, content="original")
    assert led.verify(r["id"], "original") is True
    assert led.verify(r["id"], "ALTERED") is False
    assert led.verify("unknown", "original") is False


# ── persistence + safety ───────────────────────────────────────────────────────

def test_persists_across_instances(tmp_path):
    led = _ledger(tmp_path)
    r = _rec(led, content="x")
    # a fresh ledger over the same path sees the record
    led2 = ProvenanceLedger(tmp_path / "prov.json")
    assert led2.get(r["id"])["content_hash"] == content_fingerprint("x")


def test_corrupt_file_degrades_to_empty(tmp_path):
    p = tmp_path / "prov.json"
    p.write_text("}{ not json")
    led = ProvenanceLedger(p)
    assert led.stats()["total"] == 0
    # and it can still record afterwards (overwrites the garbage atomically)
    r = _rec(led)
    assert led.get(r["id"]) is not None


def test_bounded_prunes_oldest_first(tmp_path):
    led = _ledger(tmp_path, max_keep=3)
    ids = [_rec(led, content=str(i), now=float(i))["id"] for i in range(5)]
    kept = {r["id"] for r in led.by_run("run-1")}
    # only the 3 newest (now=2,3,4) survive; the 2 oldest are evicted
    assert ids[0] not in kept and ids[1] not in kept
    assert ids[2] in kept and ids[3] in kept and ids[4] in kept


def test_stats(tmp_path):
    led = _ledger(tmp_path)
    _rec(led, source="facebook", run_id="r1", now=1)
    _rec(led, source="facebook", run_id="r1", now=2)
    _rec(led, source="whatsapp", run_id="r2", now=3)
    s = led.stats()
    assert s["total"] == 3
    assert s["runs"] == 2
    assert s["by_source"] == {"facebook": 2, "whatsapp": 1}
