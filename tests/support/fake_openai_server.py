"""A small, deterministic OpenAI-compatible model server for tests and the e2e journey.

The workspace talks to a local model through the hub's ``lm-studio`` backend
(``JARVIS_LM_STUDIO_URL=http://127.0.0.1:PORT``, no ``/v1``). This server speaks just
enough of that protocol for the real backend to work against it:

* ``GET /v1/models`` → ``{"data": [{"id": <model>}]}`` (the backend's probe);
* ``POST /v1/chat/completions`` — streamed (``data: {...}`` chunks, then
  ``data: [DONE]``) or not;
* ``POST /v1/embeddings`` — deterministic hashed bag-of-words vectors.

Answers are deterministic and citation-aware, like ``FakeEngine``: with a
``<source id="1" …>`` in the prompt the answer quotes that source's first sentence
and cites ``[1]``; without sources it says it found nothing. The language follows the
question (the text after "Întrebarea utilizatorului:" / "User question:", else after
the last ``</source>``): Romanian when it has Romanian diacritics or at least two common
Romanian words. When the system prompt is about a report ("raport" / "report"), the
answer is a well-formed Markdown report: title, executive summary, findings, a table
of the sources and a sources section.

Trigger phrases anywhere in the prompt simulate trouble: :data:`SLOW_TRIGGER` waits
``slow_seconds`` before answering (timeout tests), :data:`ERROR_TRIGGER` answers HTTP
500, :data:`EMPTY_TRIGGER` answers an empty completion.

Two ways to run it — stdlib only, so it also works as a plain script::

    with FakeOpenAIServer() as server:       # in a test; binds 127.0.0.1 only
        monkeypatch.setenv("JARVIS_LM_STUDIO_URL", server.url)

    python tests/support/fake_openai_server.py --port 18080   # prints READY when serving
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import signal
import socket
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HOST = "127.0.0.1"
DEFAULT_MODEL = "nerva-fake-model"
SLOW_TRIGGER = "nerva-fake-slow"
ERROR_TRIGGER = "nerva-fake-error"
EMPTY_TRIGGER = "nerva-fake-empty"
EMBEDDING_DIMENSIONS = 64
MAX_BODY_BYTES = 8 * 1024 * 1024
QUESTION_MARKERS = ("Întrebarea utilizatorului:", "User question:")

_SOURCE = re.compile(r'<source\s+id="(\d+)"(?:\s+title="([^"]*)")?[^>]*>(.*?)</source>',
                     re.DOTALL)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_ROMANIAN_CHARS = re.compile(r"[ăâîșşțţĂÂÎȘŞȚŢ]")
_ROMANIAN_WORDS = re.compile(
    r"\b(care|este|sunt|pentru|cum|cât|câte|unde|când|despre|vreau|să|și|din|ce|avem|"
    r"politica|raport|lunar|vânzări|vanzari)\b",
    re.IGNORECASE,
)
_REPORT = re.compile(r"\b(raport|report)", re.IGNORECASE)
#: The label the workspace's report prompt puts before the report's name ("Raport: Zilnic"),
#: stripped from the subject so the heading never reads "Raport: Raport: Zilnic".
_REPORT_LABEL = re.compile(r"^\s*(?:raport|report)\s*:\s*", re.IGNORECASE)
_SAY_OK = re.compile(r"\breply with (?:the single word )?ok\b", re.IGNORECASE)
_WORD = re.compile(r"\w+", re.UNICODE)


# ── answers (pure functions, unit-tested on their own) ───────────────────────────────

def split_messages(messages: Any) -> tuple[str, str]:
    """``(system, prompt)`` of an OpenAI ``messages`` array (last user turn = prompt)."""
    system_parts: list[str] = []
    prompt = ""
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        if message.get("role") == "system":
            system_parts.append(text)
        elif message.get("role") == "user":
            prompt = text
    return "\n".join(system_parts), prompt


def question_of(prompt: str) -> str:
    """The question part of a workspace prompt (after its marker, else after the sources)."""
    for marker in QUESTION_MARKERS:
        if marker in prompt:
            return prompt.rsplit(marker, 1)[-1].strip()
    return prompt.rsplit("</source>", 1)[-1].strip()


def looks_romanian(text: str) -> bool:
    """Romanian diacritics, or at least two common Romanian words."""
    return bool(_ROMANIAN_CHARS.search(text) or len(_ROMANIAN_WORDS.findall(text)) >= 2)


def sources_of(prompt: str) -> dict[int, tuple[str, str]]:
    """``{n: (title, body)}`` of every ``<source>`` fence in *prompt*."""
    found: dict[int, tuple[str, str]] = {}
    for number, title, body in _SOURCE.findall(prompt):
        found.setdefault(int(number), (title or f"#{number}", " ".join(body.split())))
    return found


def first_sentence(text: str, limit: int = 240) -> str:
    """The first sentence of *text*, at most *limit* characters."""
    cleaned = " ".join(text.split())
    sentence = _SENTENCE_END.split(cleaned, maxsplit=1)[0] if cleaned else ""
    return sentence[:limit].rstrip()


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "/")[:120]


def compose_report(question: str, sources: dict[int, tuple[str, str]], *, romanian: bool) -> str:
    """A well-formed Markdown report built only from *sources*."""
    first_line = next((line for line in question.splitlines() if line.strip()), "")
    subject = first_sentence(_REPORT_LABEL.sub("", first_line, count=1), 80).rstrip(".:")
    heading = ("Raport" if romanian else "Report") + (f": {subject}" if subject else "")
    words = {
        "summary": "Rezumat executiv" if romanian else "Executive summary",
        "findings": "Constatări" if romanian else "Findings",
        "data": "Date cheie" if romanian else "Key data",
        "sources": "Surse" if romanian else "Sources",
        "document": "Document",
        "excerpt": "Extras" if romanian else "Excerpt",
        "none": ("Nu am găsit date în documentele selectate." if romanian
                 else "No data was found in the selected documents."),
        "no_sources": "Nicio sursă disponibilă." if romanian else "No sources available.",
    }
    lines = [f"# {heading}", "", f"## {words['summary']}"]
    if not sources:
        lines += [words["none"], "", f"## {words['sources']}", f"- {words['no_sources']}"]
        return "\n".join(lines)
    first = min(sources)
    lines += [f"{first_sentence(sources[first][1])} [{first}]", "", f"## {words['findings']}"]
    lines += [f"- {first_sentence(body)} [{n}]" for n, (_, body) in sorted(sources.items())]
    lines += ["", f"## {words['data']}", "",
              f"| Nr. | {words['document']} | {words['excerpt']} |", "| --- | --- | --- |"]
    lines += [f"| [{n}] | {_cell(title)} | {_cell(first_sentence(body, 100))} |"
              for n, (title, body) in sorted(sources.items())]
    lines += ["", f"## {words['sources']}"]
    lines += [f"{n}. [{n}] {_cell(title)}" for n, (title, _) in sorted(sources.items())]
    return "\n".join(lines)


def compose_reply(system: str, prompt: str) -> str:
    """The deterministic answer to one chat completion request."""
    question = question_of(prompt)
    if _SAY_OK.search(prompt):
        return "OK"
    romanian = looks_romanian(question)
    sources = sources_of(prompt)
    if _REPORT.search(system):
        return compose_report(question, sources, romanian=romanian)
    if 1 in sources:
        sentence = first_sentence(sources[1][1])
        if romanian:
            return f"Conform documentelor companiei: {sentence} [1]"
        return f"According to the company documents: {sentence} [1]"
    if romanian:
        return "Nu am găsit această informație în documentele companiei."
    return "I could not find this in the company documents."


def pieces(text: str) -> list[str]:
    """Word-sized stream chunks whose concatenation is exactly *text*."""
    return re.findall(r"\S+\s*|\s+", text) or [text]


def embed(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    """A unit vector from hashed, case-folded words: equal texts embed equally."""
    vector = [0.0] * dimensions
    for word in _WORD.findall(text.casefold()):
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        vector[0] = 1.0
        return vector
    return [value / norm for value in vector]


# ── the HTTP server ──────────────────────────────────────────────────────────────────

class _Server(ThreadingHTTPServer):
    """Tracks open connections, so stopping drops kept-alive ones too (a real outage)."""

    daemon_threads = True
    block_on_close = False

    def __init__(self, port: int, owner: FakeOpenAIServer) -> None:
        self.owner = owner
        self._open: set[socket.socket] = set()
        self._open_lock = threading.Lock()
        super().__init__((HOST, port), _Handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        with self._open_lock:
            self._open.add(request)
        super().process_request(request, client_address)

    def shutdown_request(self, request: Any) -> None:
        with self._open_lock:
            self._open.discard(request)
        super().shutdown_request(request)

    def drop_connections(self) -> None:
        with self._open_lock:
            connections, self._open = list(self._open), set()
        for connection in connections:
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                connection.close()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Server

    def log_message(self, fmt: str, *args: Any) -> None:
        """Silent: stdout carries only the READY line."""

    # ── plumbing ──
    def _send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict | None:
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or int(length) > MAX_BODY_BYTES:
            self._send_json(413 if length.isdigit() else 411, {"error": {"message": "bad body"}})
            return None
        try:
            data = json.loads(self.rfile.read(int(length)).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send_json(400, {"error": {"message": "invalid JSON"}})
            return None
        if not isinstance(data, dict):
            self._send_json(400, {"error": {"message": "expected an object"}})
            return None
        return data

    def _write_chunk(self, text: str) -> None:
        data = text.encode("utf-8")
        self.wfile.write(f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n")
        self.wfile.flush()

    # ── routes ──
    def do_GET(self) -> None:
        owner = self.server.owner
        if self.path.split("?", 1)[0] == "/v1/models":
            self._send_json(200, {"object": "list",
                                  "data": [{"id": owner.model, "object": "model"}]})
        elif self.path in ("/", "/health"):
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in ("/v1/chat/completions", "/v1/embeddings"):
            self._send_json(404, {"error": {"message": "not found"}})
            return
        payload = self._read_json()
        if payload is None:
            return
        self.server.owner.record(path, payload)
        try:
            if path == "/v1/embeddings":
                self._embeddings(payload)
            else:
                self._chat(payload)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # the client went away mid-answer

    def _embeddings(self, payload: dict) -> None:
        raw = payload.get("input")
        inputs = [raw] if isinstance(raw, str) else [t for t in raw or [] if isinstance(t, str)]
        data = [{"object": "embedding", "index": i, "embedding": embed(text)}
                for i, text in enumerate(inputs)]
        tokens = sum(len(_WORD.findall(text)) for text in inputs)
        self._send_json(200, {"object": "list", "data": data, "model": self.server.owner.model,
                              "usage": {"prompt_tokens": tokens, "total_tokens": tokens}})

    def _chat(self, payload: dict) -> None:
        owner = self.server.owner
        system, prompt = split_messages(payload.get("messages"))
        if SLOW_TRIGGER in prompt and owner.stopping.wait(owner.slow_seconds):
            self.close_connection = True
            return
        if ERROR_TRIGGER in prompt:
            self._send_json(500, {"error": {"message": "simulated model failure",
                                            "type": "server_error"}})
            return
        reply = "" if EMPTY_TRIGGER in prompt else compose_reply(system, prompt)
        model = str(payload.get("model") or owner.model)
        if payload.get("stream"):
            self._stream(reply, model)
            return
        words = len(_WORD.findall(prompt))
        self._send_json(200, {
            "id": owner.next_id(), "object": "chat.completion", "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": reply},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": words, "completion_tokens": len(pieces(reply)),
                      "total_tokens": words + len(pieces(reply))},
        })

    def _stream(self, reply: str, model: str) -> None:
        owner = self.server.owner
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        completion_id = owner.next_id()
        for chunk in _stream_chunks(reply, model, completion_id):
            self._write_chunk(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n")
            if owner.token_delay:
                time.sleep(owner.token_delay)
        self._write_chunk("data: [DONE]\n\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


def _stream_chunks(reply: str, model: str, completion_id: str) -> Iterator[dict]:
    base = {"id": completion_id, "object": "chat.completion.chunk", "created": int(time.time()),
            "model": model}
    if reply:
        for piece in pieces(reply):
            yield {**base, "choices": [{"index": 0, "delta": {"content": piece},
                                        "finish_reason": None}]}
    yield {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}


class FakeOpenAIServer:
    """The server as a context manager; ``url`` is ``http://127.0.0.1:<port>`` (no ``/v1``).

    ``requests`` records every completion and embedding request (path and JSON body)
    so a test can check what the backend really sent.
    """

    def __init__(self, *, port: int = 0, model: str = DEFAULT_MODEL, slow_seconds: float = 2.0,
                 token_delay: float = 0.0) -> None:
        self.model = model
        self.slow_seconds = slow_seconds
        self.token_delay = token_delay
        self.requests: list[dict] = []
        self.stopping = threading.Event()
        self._lock = threading.Lock()
        self._counter = 0
        self._port = port
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("the fake model server is not running")
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def record(self, path: str, payload: dict) -> None:
        with self._lock:
            self.requests.append({"path": path, "body": payload})

    def next_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"chatcmpl-fake-{self._counter}"

    def start(self) -> FakeOpenAIServer:
        self.stopping.clear()
        self._server = _Server(self._port, self)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05},
                                        name="fake-openai-server", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop serving; slow answers in flight are released at once."""
        self.stopping.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server.drop_connections()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def __enter__(self) -> FakeOpenAIServer:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


def main(argv: list[str] | None = None) -> int:
    """Serve until SIGTERM or Ctrl-C; prints ``READY`` on stdout once listening."""
    parser = argparse.ArgumentParser(description="Deterministic OpenAI-compatible test server")
    parser.add_argument("--port", type=int, default=0, help="TCP port on 127.0.0.1 (0 = any)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="model id to advertise")
    parser.add_argument("--slow-seconds", type=float, default=2.0,
                        help=f"delay for prompts containing {SLOW_TRIGGER!r}")
    parser.add_argument("--token-delay", type=float, default=0.0,
                        help="seconds between streamed chunks")
    args = parser.parse_args(argv)
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    server = FakeOpenAIServer(port=args.port, model=args.model, slow_seconds=args.slow_seconds,
                              token_delay=args.token_delay).start()
    print("READY", flush=True)
    print(f"fake OpenAI-compatible server listening on {server.url}", file=sys.stderr,
          flush=True)
    try:
        while not done.wait(0.5):
            continue
    except KeyboardInterrupt:
        done.set()
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
