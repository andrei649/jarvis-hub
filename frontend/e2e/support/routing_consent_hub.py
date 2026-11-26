"""Disposable full-hub fixture for the two-turn Ledger routing/consent journey.

The local model and direct Gemini protocol each have a separate loopback HTTP
responder.  GeminiBackend still builds and validates its canonical Google URL;
only this fixture's httpx transport carries that request to the loopback
responder.  No external cloud socket or personal owner credential is used.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "support"))

from fake_openai_server import FakeOpenAIServer, compose_reply, split_messages  # noqa: E402
from workspace_hub import scrubbed  # noqa: E402

LOCAL_MODEL = "nerva-routing-local"
ADMIN_TOKEN = "route-proof-admin"
USER_TOKEN = "route-proof-user"
CANONICAL_HOST = "generativelanguage.googleapis.com"
_GEMINI_PATH = re.compile(r"^/v1beta/models/([A-Za-z0-9_.-]+):(streamGenerateContent|generateContent)$")


def _text_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _text_values(item)


class GeminiLoopback:
    """A protocol responder; its ledger contains requests that reached its socket."""

    def __init__(self, port: int) -> None:
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                parsed = urlsplit(self.path)
                matched = _GEMINI_PATH.fullmatch(parsed.path)
                if matched is None:
                    self.send_error(404)
                    return
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2_000_000:
                    self.send_error(413)
                    return
                try:
                    payload = json.loads(self.rfile.read(size))
                except (ValueError, UnicodeDecodeError):
                    self.send_error(400)
                    return
                with owner.lock:
                    owner.requests.append({"model": matched.group(1), "path": parsed.path, "body": payload})
                answer = "Cloud route receipt from the direct Gemini responder."
                result = {
                    "responseId": "route-proof-gemini",
                    "candidates": [{"content": {"role": "model", "parts": [{"text": answer}]}, "finishReason": "STOP", "index": 0}],
                    "usageMetadata": {"promptTokenCount": 18, "candidatesTokenCount": 10, "totalTokenCount": 28},
                }
                streamed = matched.group(2) == "streamGenerateContent"
                raw = (("data: " + json.dumps(result, separators=(",", ":")) + "\n\n").encode()
                       if streamed else json.dumps(result, separators=(",", ":")).encode())
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if streamed else "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def snapshot(self, prior_replies: list[str]) -> dict:
        with self.lock:
            requests = list(self.requests)
        texts = [text for row in requests for text in _text_values(row["body"])]
        return {
            "count": len(requests),
            "model": requests[-1]["model"] if requests else "",
            "paths": [r["path"] for r in requests],
            "prior_user_seen": any("Synthetic local route proof, first turn." in text for text in texts),
            "prior_reply_seen": any(
                len(reply) >= 24 and reply in text
                for reply in prior_replies for text in texts
            ),
            "current_turn_seen": any("Synthetic consented cloud route proof, second turn." in text for text in texts),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hub_port", type=int)
    parser.add_argument("--local-port", type=int, default=46792)
    parser.add_argument("--cloud-port", type=int, default=46793)
    args = parser.parse_args()
    if len({args.hub_port, args.local_port, args.cloud_port}) != 3:
        parser.error("hub, local, and cloud ports must be distinct")

    import httpx
    import uvicorn
    from fastapi import Depends

    with tempfile.TemporaryDirectory(prefix="nerva-routing-consent-") as temp:
        run_dir = Path(temp)
        home = run_dir / "home"
        keys = run_dir / "keys"
        home.mkdir()
        keys.mkdir()
        environ = scrubbed(dict(os.environ))
        environ.update({
            "PYTHON_DOTENV_DISABLED": "1", "PYTHONUNBUFFERED": "1",
            "HOME": str(home), "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home), "APPDATA": str(home),
            "JARVIS_USER_HOME": str(home),
            "JARVIS_HOME": str(home), "JARVIS_KEY_DIR": str(keys),
            "JARVIS_PORT": str(args.hub_port), "JARVIS_ADMIN_TOKEN": ADMIN_TOKEN,
            "JARVIS_USER_TOKEN": USER_TOKEN, "JARVIS_LOG_LEVEL": "warning",
            "JARVIS_LLM_WARMUP": "0", "JARVIS_MCP_AUTOCONNECT": "0",
            "JARVIS_LM_STUDIO_URL": f"http://127.0.0.1:{args.local_port}",
            "JARVIS_OLLAMA_URL": "http://127.0.0.1:9", "NERVA_WORKSPACE_SCHEDULER": "0",
            "MEMORY_EMBED_TURNS": "0",
        })
        os.environ.clear()
        os.environ.update(environ)

        local = FakeOpenAIServer(port=args.local_port, model=LOCAL_MODEL).start()
        cloud = GeminiLoopback(args.cloud_port)
        cloud.start()
        try:
            from agents import web
            from agents.core.llm import gemini as gemini_module
            from agents.core.llm.egress import llm_async_client as real_client

            async def direct_loopback(request: httpx.Request) -> httpx.Response:
                # The backend and egress hooks saw the canonical provider URL.  This
                # boundary allows only that exact provider and never opens its host.
                if request.url.scheme != "https" or request.url.host != CANONICAL_HOST:
                    raise RuntimeError("fixture refused a noncanonical Gemini destination")
                if _GEMINI_PATH.fullmatch(request.url.path) is None:
                    raise RuntimeError("fixture refused an unexpected Gemini operation")
                local_url = f"http://127.0.0.1:{args.cloud_port}{request.url.raw_path.decode()}"
                async with httpx.AsyncClient(trust_env=False, timeout=10) as relay:
                    received = await relay.request(
                        request.method, local_url, content=request.content,
                        headers={"content-type": request.headers.get("content-type", "application/json")},
                    )
                return httpx.Response(received.status_code, headers=received.headers, content=received.content)

            def fixture_client(backend: str, **kwargs):
                if backend == "gemini":
                    kwargs["transport"] = httpx.MockTransport(direct_loopback)
                    kwargs["trust_env"] = False
                return real_client(backend, **kwargs)

            # Only the transport factory at Gemini construction is replaced. The
            # real integration write triggers router re-detection after consent.
            gemini_module.llm_async_client = fixture_client

            async def routing_snapshot() -> dict:
                with local._lock:
                    requests = list(local.requests)
                completions = [r for r in requests if r["path"] == "/v1/chat/completions"]
                prior_replies = [
                    compose_reply(*split_messages(row["body"].get("messages")))
                    for row in completions
                ]
                return {
                    "local": {"count": len(completions), "model": LOCAL_MODEL if completions else ""},
                    "cloud": cloud.snapshot(prior_replies),
                }

            web.app.add_api_route(
                "/__test/routing", routing_snapshot, methods=["GET"],
                dependencies=[Depends(web._admin_guard)], include_in_schema=False,
            )
            uvicorn.run(web.app, host="127.0.0.1", port=args.hub_port, log_level="warning")
        finally:
            cloud.stop()
            local.stop()


if __name__ == "__main__":
    main()
