"""B4 (handoff 2026-07-07) — the ci-small-model live eval lane.

`companion_eval --live-model` runs the golden-dialogue suite through a REAL
LLM endpoint (any OpenAI-compatible `/chat/completions` — Ollama and LM Studio
both serve one) and scores the replies with the existing deterministic rubric:
live *generation*, deterministic *scoring* — no LLM judge, no fabrication.
Semantics are honestly labeled `lane: ci-small-model` — this is the advisory
trend lane for CI runners with a tiny OSS model; the owner-box fidelity lane
(JARVIS_EVAL_LIVE on real hardware) is unchanged and still owner-gated.

Offline: the "endpoint" here is an in-process HTTP server double.
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

from agents.core.observability.companion_eval import (  # noqa: E402
    load_dialogues,
    run_live_model,
)


class _FakeOpenAI(BaseHTTPRequestHandler):
    """Minimal /chat/completions double: echoes a canned reply, records prompts."""

    prompts: list[dict] = []
    reply = "I hear you — let me actually check before claiming anything."

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).prompts.append(body)
        out = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": self.reply}}],
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


def test_live_model_lane_generates_scores_and_labels_honestly(tmp_path):
    server, base_url = _serve()
    _FakeOpenAI.prompts = []
    try:
        dialogues = load_dialogues()[:3]
        result = run_live_model(
            base_url=base_url,
            model="fake-small",
            store_root=str(tmp_path / "store"),
            dialogues=dialogues,
        )
    finally:
        server.shutdown()
    assert result["lane"] == "ci-small-model"
    assert result["model"] == "fake-small"
    assert result["total"] == 3
    assert 0.0 <= result["score"] <= 1.0
    assert "run_id" in result and "version" in result   # recorded to the store
    # 1 preflight probe + one real request per dialogue
    assert len(_FakeOpenAI.prompts) == 4
    assert _FakeOpenAI.prompts[0]["messages"][0]["content"] == "ping"
    assert _FakeOpenAI.prompts[1]["model"] == "fake-small"
    sent = json.dumps(_FakeOpenAI.prompts)
    assert dialogues[0]["id"] not in ("",) and len(sent) > 100


def test_non_http_scheme_is_rejected_before_any_request(tmp_path):
    result = run_live_model(
        base_url="file:///etc",   # the B310/semgrep concern — must never reach urlopen
        model="fake-small",
        store_root=str(tmp_path / "store"),
        dialogues=load_dialogues()[:1],
    )
    assert result["ok"] is False
    assert "http" in result["error"]


def test_live_model_lane_fails_cleanly_when_endpoint_unreachable(tmp_path):
    result = run_live_model(
        base_url="http://127.0.0.1:9",   # discard port — nothing listens
        model="fake-small",
        store_root=str(tmp_path / "store"),
        dialogues=load_dialogues()[:1],
    )
    assert result["ok"] is False
    assert "error" in result             # a reason, not a traceback


def test_cli_mode_exists_and_reports_json(tmp_path, capsys):
    server, base_url = _serve()
    try:
        from agents.core.observability.companion_eval import _main
        code = _main([
            "--live-model", "--base-url", base_url, "--model", "fake-small",
            "--store-root", str(tmp_path / "store"), "--limit", "2",
        ])
    finally:
        server.shutdown()
    out = json.loads(capsys.readouterr().out.strip())
    assert code == 0                     # advisory lane: infra ok → exit 0
    assert out["lane"] == "ci-small-model"
    assert out["total"] == 2
