"""H23.4 — the owner-box live eval fidelity gate, and live-lane separation.

The eval harness only becomes a *pre-release* gate when three things hold:

1. Live-model runs are recorded on their own per-model dataset lanes, so a
   live run can never become (or read) the deterministic drift gate's
   baseline — before this, ``run_live_model`` wrote into the same
   ``companion_v1`` history that ``run_ci_gate`` baselines against.
2. ``run_live_gate`` actually runs when requested and **fails closed**: no
   configured model, or an unreachable endpoint, is a red gate with a reason —
   never a silent skip, never a fabricated score.
3. ``JARVIS_EVAL_LIVE=1`` makes the CI gate itself carry the live verdict, so
   a self-hosted owner runner cannot get a green gate from the deterministic
   half alone.

Offline: the "endpoint" is an in-process HTTP server double.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.observability import companion_eval as ce  # noqa: E402
from agents.core.observability.datasets import DatasetStore, _dataset_name  # noqa: E402


class _FakeOpenAI(BaseHTTPRequestHandler):
    """Minimal /chat/completions double with a swappable canned reply."""

    reply = "I hear you — let me actually check before claiming anything."

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        out = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": type(self).reply}}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):  # silence
        pass


def _serve():
    server = HTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


def _one_dialogue():
    return [ce.load_dialogues()[0]]


# ── lane separation ─────────────────────────────────────────────────


def test_live_dataset_name_is_disjoint_sanitized_and_bounded():
    name = ce.live_dataset_name("qwen2.5:0.5b")
    assert name.startswith(ce.LIVE_DATASET_PREFIX + "-")
    assert name != ce.DATASET_NAME
    assert _dataset_name(name) == name          # valid for the store contract
    hostile = ce.live_dataset_name("../" * 40 + "x/../../etc:passwd " + "y" * 200)
    assert _dataset_name(hostile) == hostile
    assert len(hostile) <= 64
    assert ce.live_dataset_name("") == ce.LIVE_DATASET_PREFIX + "-model"


def test_live_run_cannot_become_the_deterministic_baseline(tmp_path):
    """The defect this slice closes: shared history between the two lanes."""
    server, base_url = _serve()
    _FakeOpenAI.reply = "definitely not the golden reply, short"
    try:
        live = ce.run_live_model(
            base_url=base_url, model="fake-small",
            store_root=str(tmp_path), dialogues=_one_dialogue(),
        )
    finally:
        server.shutdown()
    assert live["ok"] is True
    assert live["dataset"] == ce.live_dataset_name("fake-small")

    store = DatasetStore(root=tmp_path)
    assert store.runs(ce.DATASET_NAME) == []     # deterministic lane untouched
    first_ci = ce.run_ci_gate(store=store)
    assert first_ci["ok"] is True
    assert first_ci["baseline_compare"] is None  # live run was never its baseline


def test_live_model_lane_carries_its_own_baseline_compare(tmp_path):
    server, base_url = _serve()
    _FakeOpenAI.reply = "a reply long enough to be substantive, checked honestly."
    try:
        first = ce.run_live_model(base_url=base_url, model="fake-small",
                                  store_root=str(tmp_path), dialogues=_one_dialogue())
        second = ce.run_live_model(base_url=base_url, model="fake-small",
                                   store_root=str(tmp_path), dialogues=_one_dialogue())
    finally:
        server.shutdown()
    assert first["baseline_compare"] is None
    assert second["baseline_compare"]["dataset"] == ce.live_dataset_name("fake-small")


# ── the fidelity gate ───────────────────────────────────────────────


def test_live_gate_records_compares_and_passes_on_its_own_lane(tmp_path):
    dialogue = _one_dialogue()
    server, base_url = _serve()
    _FakeOpenAI.reply = dialogue[0]["golden"]
    store = DatasetStore(root=tmp_path)
    try:
        first = ce.run_live_gate(base_url=base_url, model="owner-model",
                                 store=store, dialogues=dialogue, min_score=0.0)
        second = ce.run_live_gate(base_url=base_url, model="owner-model",
                                  store=store, dialogues=dialogue, min_score=0.0)
    finally:
        server.shutdown()
    assert first["ok"] is True and first["infra_failure"] is False
    assert first["dataset"] == ce.live_dataset_name("owner-model")
    assert first["baseline_compare"] is None
    assert second["ok"] is True
    assert second["baseline_compare"]["regression"] is False
    assert len(store.runs(first["dataset"])) == 2


def test_live_gate_fails_on_regression_against_its_own_baseline(tmp_path):
    dialogue = _one_dialogue()
    server, base_url = _serve()
    store = DatasetStore(root=tmp_path)
    try:
        _FakeOpenAI.reply = dialogue[0]["golden"]
        good = ce.run_live_gate(base_url=base_url, model="owner-model",
                                store=store, dialogues=dialogue, min_score=0.0)
        _FakeOpenAI.reply = "no."
        bad = ce.run_live_gate(base_url=base_url, model="owner-model",
                               store=store, dialogues=dialogue, min_score=0.0)
    finally:
        server.shutdown()
    assert good["ok"] is True
    assert bad["ok"] is False
    assert bad["baseline_compare"]["regression"] is True
    assert bad["failed_cases"] == [dialogue[0]["id"]]


def test_live_gate_enforces_the_absolute_floor(tmp_path):
    dialogue = _one_dialogue()
    server, base_url = _serve()
    _FakeOpenAI.reply = "no."
    try:
        result = ce.run_live_gate(base_url=base_url, model="owner-model",
                                  store=DatasetStore(root=tmp_path),
                                  dialogues=dialogue, min_score=0.9)
    finally:
        server.shutdown()
    assert result["ok"] is False
    assert result["infra_failure"] is False      # the model ran; it just scored low
    assert result["score"] < 0.9


def test_live_gate_fails_closed_without_a_configured_model(tmp_path, monkeypatch):
    monkeypatch.delenv(ce.LIVE_MODEL_ENV, raising=False)
    summary = tmp_path / "summary.md"
    result = ce.run_live_gate(store=DatasetStore(root=tmp_path), summary_path=summary)
    assert result["ok"] is False
    assert result["infra_failure"] is True
    assert ce.LIVE_MODEL_ENV in result["error"]
    assert "NOT RUN" in summary.read_text(encoding="utf-8")


def test_live_gate_fails_closed_on_unreachable_endpoint(tmp_path):
    result = ce.run_live_gate(base_url="http://127.0.0.1:9", model="owner-model",
                              store=DatasetStore(root=tmp_path),
                              dialogues=_one_dialogue(), min_score=0.0)
    assert result["ok"] is False
    assert result["infra_failure"] is True
    assert "error" in result                     # a reason, not a traceback


# ── the CI gate carries the live verdict when requested ─────────────


def test_ci_gate_is_unchanged_when_live_is_off(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_EVAL_LIVE", raising=False)
    result = ce.run_ci_gate(store=DatasetStore(root=tmp_path))
    assert result["ok"] is True
    assert result["live_eval_requested"] is False
    assert "live" not in result


def test_ci_gate_ands_in_the_live_verdict_when_requested(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_EVAL_LIVE", "1")
    seen = {}

    def red_gate(**kwargs):
        seen.update(kwargs)
        return {"ok": False, "gate": "live-fidelity", "infra_failure": True, "error": "down"}

    result = ce.run_ci_gate(store=DatasetStore(root=tmp_path), live_gate=red_gate)
    assert result["live_eval_requested"] is True
    assert result["live"]["ok"] is False
    assert result["ok"] is False                 # deterministic green cannot mask live red
    assert isinstance(seen.get("store"), DatasetStore)

    green = ce.run_ci_gate(
        store=DatasetStore(root=tmp_path / "second"),
        live_gate=lambda **kwargs: {"ok": True, "gate": "live-fidelity"},
    )
    assert green["ok"] is True and green["live"]["ok"] is True


# ── CLI ─────────────────────────────────────────────────────────────


def test_live_gate_cli_exit_codes(tmp_path, capsys, monkeypatch):
    dialogue_golden = _one_dialogue()[0]["golden"]
    server, base_url = _serve()
    _FakeOpenAI.reply = dialogue_golden
    try:
        code = ce._main([
            "--live-gate", "--base-url", base_url, "--model", "fake-small",
            "--store-root", str(tmp_path / "store"), "--min-score", "0.0",
        ])
    finally:
        server.shutdown()
    out = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert out["gate"] == "live-fidelity"

    monkeypatch.delenv(ce.LIVE_MODEL_ENV, raising=False)
    code = ce._main(["--live-gate", "--store-root", str(tmp_path / "store2")])
    unconfigured = json.loads(capsys.readouterr().out.strip())
    assert code == 1                             # explicitly requested → red, not skip
    assert unconfigured["infra_failure"] is True
