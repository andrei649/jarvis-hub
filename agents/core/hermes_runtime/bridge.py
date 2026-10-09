"""Private, generation-bound authorization channel; also usable by standalone worker."""

from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_FRAME = 1024 * 1024
MAX_OUTCOME_BYTES = 8192
_PRIVATE_FIELDS = ("token", "secret", "password", "credential", "authorization", "cookie", "api_key", "apikey")


def bounded_outcome(outcome, *, token: str = "") -> dict:
    """Keep only small JSON values, redacting private keys before publication."""
    try:
        if type(outcome) is not dict or outcome.get("state") not in {"result", "error", "unknown"}:
            raise ValueError
        if outcome["state"] == "unknown":
            if set(outcome) != {"state"}:
                raise ValueError
            return {"state": "unknown"}
        if set(outcome) != {"state", "value"}:
            raise ValueError

        def clean(value, depth=0):
            if depth > 6:
                raise ValueError
            if value is None or type(value) in {bool, int, float}:
                return value
            if type(value) is str:
                if len(value) > 2048:
                    raise ValueError
                return value.replace(token, "[redacted]") if token else value
            if type(value) is list:
                if len(value) > 64:
                    raise ValueError
                return [clean(item, depth + 1) for item in value]
            if type(value) is dict:
                if len(value) > 64:
                    raise ValueError
                answer = {}
                for key, item in value.items():
                    if type(key) is not str or len(key) > 128:
                        raise ValueError
                    answer[key] = ("[redacted]" if any(part in key.lower() for part in _PRIVATE_FIELDS)
                                   else clean(item, depth + 1))
                return answer
            raise ValueError

        safe = {"state": outcome["state"], "value": clean(outcome["value"])}
        if len(json.dumps(safe, allow_nan=False, ensure_ascii=False).encode("utf-8")) > MAX_OUTCOME_BYTES:
            raise ValueError
        return safe
    except (ValueError, TypeError, RecursionError, OverflowError):
        return {"state": "unknown"}


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
                    basic = {"generation", "nonce", "kind", "target", "args"}
                    continuation = basic | {"request_id", "phase", "task_id", "original_nonce"}
                    completion = {"generation", "nonce", "phase", "task_id", "completion_id", "ok", "outcome"}
                    if (not isinstance(frame, dict)
                            or set(frame) not in (basic, basic | {"request_id"}, continuation, completion)
                            or ("request_id" in frame and (not isinstance(frame["request_id"], str)
                                or not 0 < len(frame["request_id"]) <= 128))
                            or (set(frame) == continuation and (frame["phase"] != "continue"
                                or type(frame["task_id"]) is not int or frame["task_id"] <= 0
                                or not isinstance(frame["original_nonce"], str)
                                or not 0 < len(frame["original_nonce"]) <= 128))
                            or (set(frame) == completion and (frame["phase"] != "complete"
                                or type(frame["task_id"]) is not int or frame["task_id"] <= 0
                                or type(frame["ok"]) is not bool
                                or bounded_outcome(frame["outcome"]) != frame["outcome"]
                                or (frame["ok"] and frame["outcome"]["state"] != "result")
                                or not isinstance(frame["completion_id"], str)
                                or not 0 < len(frame["completion_id"]) <= 128))):
                        raise ValueError("invalid bridge frame")
                    nonce = frame["nonce"]
                    if (frame["generation"] != bridge.generation or bridge.generation is None
                            or not isinstance(nonce, str) or not 0 < len(nonce) <= 128
                            or (set(frame) != completion and not isinstance(frame["args"], dict))):
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

    def _request(self, frame: dict) -> dict:
        try:
            body = json.dumps(frame, allow_nan=False).encode()
            if len(body) > MAX_FRAME:
                raise ValueError("frame too large")
            request = urllib.request.Request(self.url, data=body,
                        headers={"Content-Type": "application/json", "X-Jarvis-Bridge-Token": self.token}, method="POST")
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with self._opener.open(request, timeout=10) as response:  # nosec B310 - fixed loopback endpoint; no redirects
                answer = json.loads(response.read(MAX_FRAME))
            if not isinstance(answer, dict) or answer.get("verdict") not in {"grant", "deny", "queue"}:
                raise ValueError("invalid authority response")
            return answer
        except Exception:
            return {"verdict": "deny", "reason": "Jarvis authorization bridge unavailable"}

    def authorize(self, kind: str, target: str, args: dict, *, request_id: str | None = None) -> dict:
        frame = {"generation": self.generation, "nonce": secrets.token_hex(24),
                 "kind": kind, "target": target, "args": args}
        if request_id is not None:
            frame["request_id"] = request_id
        answer = self._request(frame)
        if kind != "tool" or answer["verdict"] != "queue" or type(answer.get("task_id")) is not int:
            return answer
        task_id, original_nonce = answer["task_id"], frame["nonce"]
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            time.sleep(0.5)
            continuation = {"generation": self.generation, "nonce": secrets.token_hex(24),
                            "kind": kind, "target": target, "args": args,
                            "request_id": "hermes-tool-" + secrets.token_hex(24),
                            "phase": "continue", "task_id": task_id,
                            "original_nonce": original_nonce}
            answer = self._request(continuation)
            if answer["verdict"] != "queue":
                return answer
        return {"verdict": "deny", "reason": "Hermes tool approval expired", "task_id": task_id}

    def run(self, kind: str, target: str, args: dict, execute):
        decision = self.authorize(kind, target, args)
        if decision["verdict"] != "grant":
            return {"error": decision.get("reason", "Jarvis refused operation"), "jarvis_verdict": decision["verdict"]}
        try:
            result = execute()
        except BaseException:
            self.complete(decision, ok=False, outcome={"state": "unknown"})
            raise
        self.complete(decision, ok=True, outcome={"state": "result", "value": result})
        return result

    def complete(self, decision: dict, *, ok: bool, outcome: dict | None = None) -> bool:
        task_id, completion_id = decision.get("task_id"), decision.get("completion_id")
        if type(task_id) is not int or not isinstance(completion_id, str):
            return False
        safe = bounded_outcome(outcome or {"state": "unknown"}, token=self.token)
        ok = ok is True and safe["state"] == "result"
        answer = self._request({"generation": self.generation, "nonce": secrets.token_hex(24),
                                "phase": "complete", "task_id": task_id,
                                "completion_id": completion_id, "ok": ok, "outcome": safe})
        return answer.get("verdict") == "grant"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
