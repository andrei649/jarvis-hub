"""0.37 wiring — IngestionPipeline records provenance per parsed message (opt-in).

The full pipeline.run() needs real Facebook/WhatsApp export dirs, so this exercises
the wired seam directly: the _record_provenance helper against a real
ProvenanceLedger, proving (a) per-message records carry the right source/origin/
content-hash, (b) it's a no-op with no ledger attached, and (c) a ledger hiccup
never breaks ingestion.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.ingestion.normalizer import NormalizedMessage  # noqa: E402
from agents.core.ingestion.pipeline import IngestionPipeline  # noqa: E402
from agents.core.ingestion.provenance import ProvenanceLedger, content_fingerprint  # noqa: E402


def _msg(text="hello", source="facebook", conv="conv-1", sender="Andrei", is_me=True):
    return NormalizedMessage(source=source, conversation_id=conv, sender=sender,
                             is_me=is_me, text=text, timestamp=1.0, metadata={})


def _pipeline(tmp_path, **kw):
    # output_root in a tmp dir so constructing the pipeline touches no real data root
    return IngestionPipeline(output_root=str(tmp_path / "out"), **kw)


def test_record_provenance_writes_one_entry_per_message(tmp_path):
    led = ProvenanceLedger(tmp_path / "prov.json")
    pipe = _pipeline(tmp_path, ledger=led)
    msgs = [_msg("first", conv="A"), _msg("second", conv="B", is_me=False)]

    n = pipe._record_provenance(msgs, source="facebook", phase="parse", run_id="run-9", now=1000.0)
    assert n == 2

    recs = led.by_run("run-9")
    assert [r["source"] for r in recs] == ["facebook", "facebook"]
    assert [r["origin"] for r in recs] == ["A", "B"]
    assert recs[0]["content_hash"] == content_fingerprint("first")
    assert recs[0]["phase"] == "parse" and recs[0]["produced_at"] == 1000.0
    assert recs[0]["meta"] == {"sender": "Andrei", "is_me": True}
    assert recs[1]["meta"]["is_me"] is False


def test_no_ledger_is_a_noop(tmp_path):
    pipe = _pipeline(tmp_path)  # no ledger attached → default behaviour
    assert pipe._record_provenance([_msg(), _msg()], source="whatsapp",
                                   phase="parse", run_id="r", now=1.0) == 0


def test_message_source_overrides_phase_source(tmp_path):
    # a message carrying its own source wins over the batch-level source label
    led = ProvenanceLedger(tmp_path / "prov.json")
    pipe = _pipeline(tmp_path, ledger=led)
    pipe._record_provenance([_msg(source="whatsapp")], source="facebook",
                            phase="parse", run_id="r", now=1.0)
    assert led.by_run("r")[0]["source"] == "whatsapp"


def test_ledger_hiccup_never_breaks_ingestion(tmp_path):
    class _BrokenLedger:
        def record(self, **kw):
            raise RuntimeError("disk full")

    pipe = _pipeline(tmp_path, ledger=_BrokenLedger())
    # the helper swallows the error and simply records nothing
    assert pipe._record_provenance([_msg(), _msg()], source="facebook",
                                   phase="parse", run_id="r", now=1.0) == 0
