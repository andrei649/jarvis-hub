"""P26 evidence harness: one bounded local generation, or offline raw-wire replay.

Run from the repository with its Python environment. The default replays the
saved NDJSON; --live makes the one synthetic request and refreshes the evidence.
No model installation, cloud request, or owner content is involved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from agents.core.llm.base import (  # noqa: E402
    THINKING_EXHAUSTED_REPLY,
    OllamaBackend,
    is_degraded_reply,
)

HERE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:11434"
MODEL = "qwen3.5:0.8b"
PROMPT = "Calculate 17 multiplied by 23."
READER_PATH = Path(sys.modules[OllamaBackend.__module__].__file__).resolve()
READER_IMPORTED_SHA256 = hashlib.sha256(READER_PATH.read_bytes()).hexdigest()


def reader_provenance():
    """Identify the actual reader file; HEAD alone does not attest dirty source."""
    relative_path = READER_PATH.relative_to(ROOT).as_posix()
    head = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True,
    ).strip()
    committed = subprocess.check_output(
        ["git", "-C", str(ROOT), "show", f"{head}:{relative_path}"],
    )
    source_hash = hashlib.sha256(READER_PATH.read_bytes()).hexdigest()
    assert source_hash == READER_IMPORTED_SHA256, "Reader source changed after import"
    return {
        "base_sha": head,
        "reader_source_path": relative_path,
        "reader_source_sha256": source_hash,
        "reader_source_dirty": source_hash != hashlib.sha256(committed).hexdigest(),
    }


class CaptureStream(httpx.AsyncByteStream):
    def __init__(self, stream, chunks):
        self.stream = stream
        self.chunks = chunks

    async def __aiter__(self):
        async for chunk in self.stream:
            self.chunks.append(chunk)
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class CaptureTransport(httpx.AsyncBaseTransport):
    """Change only bounded request controls; tee response body bytes unchanged."""

    def __init__(self):
        self.transport = httpx.AsyncHTTPTransport(trust_env=False)
        self.chunks = []
        self.request_payload = None

    async def handle_async_request(self, request):
        assert str(request.url) == BASE + "/api/generate"
        payload = json.loads(request.content)
        assert payload["model"] == MODEL and payload["prompt"] == PROMPT
        assert payload["stream"] is True and payload["options"]["num_predict"] == 8
        payload.update(keep_alive=0, think=True)
        payload["options"]["num_ctx"] = 2048
        self.request_payload = payload
        headers = dict(request.headers)
        headers.pop("content-length", None)
        outbound = httpx.Request(
            request.method, request.url, headers=headers,
            json=payload, extensions=request.extensions,
        )
        response = await self.transport.handle_async_request(outbound)
        response.stream = CaptureStream(response.stream, self.chunks)
        return response

    async def aclose(self):
        await self.transport.aclose()


async def consume(transport):
    backend = OllamaBackend.__new__(OllamaBackend)
    backend.base_url = BASE
    backend.client = httpx.AsyncClient(
        base_url=BASE, transport=transport, trust_env=False,
        timeout=httpx.Timeout(60.0, connect=5.0),
    )
    tokens = []
    started = time.perf_counter()
    try:
        answer = await backend.generate_stream(
            MODEL, PROMPT, max_tokens=8, temperature=0, on_token=tokens.append,
        )
    finally:
        await backend.aclose()
    return answer, tokens, round(time.perf_counter() - started, 3)


def inspect_wire(raw, answer, tokens):
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    reasoning = "".join(row.get("thinking", "") for row in records)
    visible = "".join(row.get("response", "") for row in records)
    final = records[-1]
    assert final["done"] is True and final["done_reason"] == "length"
    assert final["eval_count"] == 8 and reasoning and not visible
    assert answer == THINKING_EXHAUSTED_REPLY and is_degraded_reply(answer)
    assert tokens == [] and reasoning not in answer
    return {
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw), "records": len(records),
        "thinking_chars": len(reasoning), "response_chars": len(visible),
        "done": final["done"], "done_reason": final["done_reason"],
        "eval_count": final["eval_count"], "user_token_callbacks": len(tokens),
        "returned_named_degraded_reply": True, "reasoning_in_returned_reply": False,
        "returned_reply": answer,
    }


async def live():
    provenance = reader_provenance()
    async with httpx.AsyncClient(base_url=BASE, trust_env=False, timeout=10) as client:
        version = (await client.get("/api/version")).json()["version"]
        tags = (await client.get("/api/tags")).json()["models"]
        installed = next(row for row in tags if row["name"] == MODEL)
        before = (await client.get("/api/ps")).json()["models"]
        assert before == [], "Refusing to interrupt an already resident model"
        transport = CaptureTransport()
        try:
            answer, tokens, wall_seconds = await consume(transport)
        finally:
            unload = await client.post("/api/generate", json={
                "model": MODEL, "keep_alive": 0, "stream": False,
            })
            unload.raise_for_status()
            after = (await client.get("/api/ps")).json()["models"]
        assert after == [], "The probe model remains resident"
    assert reader_provenance() == provenance, "Reader provenance changed during capture"
    raw = b"".join(transport.chunks)
    (HERE / "ollama-generate.ndjson").write_bytes(raw)
    evidence = inspect_wire(raw, answer, tokens)
    evidence.update({
        "captured_at_utc": datetime.now(UTC).isoformat(),
        **provenance,
        "endpoint": BASE + "/api/generate", "ollama_version": version,
        "model": MODEL, "model_digest": installed["digest"],
        "model_size_bytes": installed["size"],
        "wire_request": transport.request_payload,
        "wall_seconds": wall_seconds,
        "resident_models_before": [], "resident_models_after": [],
        "unload_response": unload.json(),
        "scope": "Ollama raw stream and backend reader; not full hub/memory or LM Studio",
    })
    (HERE / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=True))


async def replay():
    raw = (HERE / "ollama-generate.ndjson").read_bytes()
    saved = json.loads((HERE / "evidence.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == saved["raw_sha256"]
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, content=raw, headers={"content-type": "application/x-ndjson"},
    ))
    answer, tokens, _wall = await consume(transport)
    print(json.dumps(inspect_wire(raw, answer, tokens), ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(live() if sys.argv[1:] == ["--live"] else replay())
