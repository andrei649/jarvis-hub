"""Private, generation-bound authorization channel; also usable by standalone worker."""

from __future__ import annotations

import hmac
import json
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_FRAME = 1024 * 1024


class AuthorizationBridge:
    def __init__(self, authorize):
        self.token = secrets.token_urlsafe(32)
        self.generation = None
        self._authorize, self._server, self._thread = authorize, None, None
        self._seen, self._lock = set(), threading.Lock()
        self.url = None

    def start(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # never log credentials or arguments

            def do_POST(self):
                try:
                    supplied = self.headers.get("X-Jarvis-Bridge-Token", "")
                    if self.path != "/authorize" or not hmac.compare_digest(supplied, bridge.token):
                        raise ValueError("bridge authentication failed")
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= MAX_FRAME:
                        raise ValueError("invalid frame size")
                    frame = json.loads(self.rfile.read(size))
                    if not isinstance(frame, dict) or set(frame) != {"generation", "nonce", "kind", "target", "args"}:
                        raise ValueError("invalid bridge frame")
                    nonce = frame["nonce"]
                    if (frame["generation"] != bridge.generation or bridge.generation is None
                            or not isinstance(nonce, str) or not 0 < len(nonce) <= 128
                            or not isinstance(frame["args"], dict)):
                        raise ValueError("stale or invalid bridge frame")
                    with bridge._lock:
                        if nonce in bridge._seen or len(bridge._seen) >= 100_000:
                            raise ValueError("replayed or exhausted bridge generation")
                        bridge._seen.add(nonce)
                    try:
                        answer = bridge._authorize(frame)
                    except Exception as exc:
                        answer = {"verdict": getattr(exc, "verdict", "deny"),
                                  "reason": getattr(exc, "reason", "authorization unavailable")}
                    if bridge.generation != frame["generation"]:
                        answer = {"verdict": "deny", "reason": "runtime generation revoked"}
                    status = 200
                except Exception:
                    status, answer = 403, {"verdict": "deny", "reason": "invalid bridge authority"}
                body = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_port}/authorize"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.generation = None
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._server = self._thread = None
        self._seen.clear()


class BrokerClient:
    def __init__(self, url: str, token: str, generation: str):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
                or parsed.path != "/authorize" or parsed.query or parsed.fragment or parsed.username
                or not token or not generation):
            raise ValueError("private loopback bridge is required")
        self.url, self.token, self.generation = url, token, generation
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def authorize(self, kind: str, target: str, args: dict) -> dict:
        frame = {"generation": self.generation, "nonce": secrets.token_hex(24),
                 "kind": kind, "target": target, "args": args}
        try:
            body = json.dumps(frame, allow_nan=False).encode()
            if len(body) > MAX_FRAME:
                raise ValueError("frame too large")
            request = urllib.request.Request(self.url, data=body,
                        headers={"Content-Type": "application/json", "X-Jarvis-Bridge-Token": self.token}, method="POST")
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with self._opener.open(request, timeout=10) as response:  # nosec B310 - constructor fixes HTTP loopback + port/path; redirects disabled
                answer = json.loads(response.read(MAX_FRAME))
            if not isinstance(answer, dict) or answer.get("verdict") not in {"grant", "deny", "queue"}:
                raise ValueError("invalid authority response")
            return answer
        except Exception:
            return {"verdict": "deny", "reason": "Jarvis authorization bridge unavailable"}

    def run(self, kind: str, target: str, args: dict, execute):
        decision = self.authorize(kind, target, args)
        if decision["verdict"] != "grant":
            return {"error": decision.get("reason", "Jarvis refused operation"), "jarvis_verdict": decision["verdict"]}
        return execute()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
