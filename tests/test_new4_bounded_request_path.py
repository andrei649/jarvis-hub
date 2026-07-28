"""NEW-4 — nothing on the request path may block or hang without a deadline.

A manual QA run against a live box found four HUD routes that never returned when
the memory/graph backends were down: `GET /api/agents`, `GET /memory`,
`GET /memory/stats` and `GET /api/voice/capabilities`. The HUD spinner span
forever with no error, which is the worst failure mode — indistinguishable from
"still loading".

Two distinct defects produced that one symptom:

1. Unbounded awaits. `/memory` and `/memory/stats` awaited the memory store with
   no timeout, so a wedged Qdrant/Neo4j held the request open indefinitely.

2. Event-loop blocking. `/api/voice/capabilities` imported `core.voice.stt`
   INSIDE the async handler; that module does `from faster_whisper import
   WhisperModel` at module scope, dragging in ctranslate2 and the CUDA runtime.
   On a host where those are installed that is seconds of synchronous work on the
   event loop, during which nothing else runs — which is why `/api/agents`, whose
   own handler does no I/O at all, was seen hanging too.

The second one is invisible in CI: `faster_whisper` is not installed here, so the
ImportError returns in milliseconds. The test below therefore asserts the
STRUCTURE (the import happens off the loop, once) rather than trying to time it.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core.web_helpers import BackendTimeout, bounded, degraded

# ── the helper itself ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bounded_returns_the_value_when_the_backend_answers_in_time():
    async def quick():
        return {"turns": [1, 2]}

    assert await bounded(quick(), what="x", seconds=5) == {"turns": [1, 2]}


@pytest.mark.asyncio
async def test_bounded_raises_backend_timeout_not_a_generic_timeout():
    """The distinction has to survive an existing broad `except Exception`.

    If this raised bare TimeoutError, a handler that already wraps its body in
    `except Exception: return zeros` would silently reclassify a dead backend as
    an empty one — exactly the fabrication this is meant to prevent.
    """
    async def never():
        await asyncio.sleep(30)

    with pytest.raises(BackendTimeout) as caught:
        await bounded(never(), what="memory.get_history", seconds=0.05)
    assert caught.value.what == "memory.get_history"


@pytest.mark.asyncio
async def test_bounded_cancels_the_wedged_call_rather_than_leaking_it():
    """A timed-out backend call must not keep running behind the response."""
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def wedged():
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(BackendTimeout):
        await bounded(wedged(), what="wedged", seconds=0.05)
    assert started.is_set()
    await asyncio.sleep(0)  # let the cancellation land
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_bounded_finishes_fast_and_does_not_wait_out_the_budget():
    async def quick():
        return 1

    t0 = time.monotonic()
    await bounded(quick(), what="x", seconds=10)
    assert time.monotonic() - t0 < 1.0


def test_degraded_body_says_unavailable_rather_than_zero():
    """The keys stay so a panel does not crash, but they are marked not-readings."""
    import json

    body = json.loads(degraded({"entities": 0}, what="graph", reason="timeout").body)
    assert body["available"] is False
    assert body["degraded"] == {"source": "graph", "reason": "timeout"}


# ── /memory and /memory/stats ─────────────────────────────────────────────────

class _WedgedMemory:
    """A memory store that accepts calls and never answers — a down backend."""

    agent_contexts: dict = {}
    graph = None

    async def get_history(self, *a, **k):
        await asyncio.sleep(30)

    async def get_session_stats(self, *a, **k):
        await asyncio.sleep(30)

    async def get_agent_context(self, *a, **k):
        await asyncio.sleep(30)


@pytest.fixture
def wedged_orch(monkeypatch):
    """An orchestrator whose memory backend is up but never responds."""
    from agents.core import web_helpers

    orch = SimpleNamespace(
        memory=_WedgedMemory(),
        session_id="s1",
        agents={"jarvis": object()},
        channels={},
    )
    monkeypatch.setattr(web, "orch", orch)
    # Shrink the budget so the test is fast; the point is that a budget EXISTS.
    monkeypatch.setattr(web_helpers, "BACKEND_TIMEOUT_S", 0.1)
    return orch


def test_memory_returns_503_instead_of_hanging(wedged_orch):
    t0 = time.monotonic()
    resp = TestClient(web.app).get("/memory")
    elapsed = time.monotonic() - t0

    assert elapsed < 10, "the request hung instead of hitting its deadline"
    assert resp.status_code == 503
    body = resp.json()
    assert body["available"] is False
    assert body["degraded"]["reason"] == "timeout"


def test_memory_stats_reports_unavailable_and_not_a_body_of_zeros(wedged_orch):
    """The regression that mattered most here.

    The old handler wrapped everything in `except Exception` and returned zeros,
    so a dead memory store rendered in the SystemsPanel as "0 vectors, 0 entities"
    — a confident wrong answer, with nothing logged.
    """
    resp = TestClient(web.app).get("/memory/stats")
    assert resp.status_code == 200
    body = resp.json()

    assert body["available"] is False
    assert body["degraded"]["reason"] == "timeout"
    # The shape survives so the panel does not crash on a missing key...
    assert body["vectors"]["stored"] == 0
    # ...but `available: false` is what tells it not to draw those as readings.


def test_memory_stats_with_no_orchestrator_is_a_real_zero_not_a_degraded_read(monkeypatch):
    """The distinction runs both ways: an absent orchestrator genuinely HAS no
    memory, so that must NOT be reported as an unavailable backend."""
    monkeypatch.setattr(web, "orch", None)
    body = TestClient(web.app).get("/memory/stats").json()
    assert "available" not in body
    assert body["vectors"]["stored"] == 0


def test_per_agent_memory_returns_503_instead_of_hanging(wedged_orch):
    resp = TestClient(web.app).get("/memory/jarvis")
    assert resp.status_code == 503
    assert resp.json()["degraded"]["reason"] == "timeout"


def test_per_agent_memory_503s_before_boot_instead_of_500(monkeypatch):
    """Its sibling routes guarded `orch is None`; this one did not, so a request
    arriving mid-boot raised AttributeError on `None.agents` and returned 500."""
    monkeypatch.setattr(web, "orch", None)
    resp = TestClient(web.app).get("/memory/jarvis")
    assert resp.status_code == 503
    assert resp.json()["error"] == "not initialized"


# ── /api/voice/capabilities ───────────────────────────────────────────────────

def test_voice_capabilities_imports_the_ml_stack_off_the_event_loop(monkeypatch):
    """The heavy import must go through a worker thread, not the loop.

    Timing this in CI proves nothing — `faster_whisper` is absent here, so the
    ImportError is instant. So assert the structure: the probe runs on a thread
    other than the one running the event loop.
    """
    import threading

    from agents.core.routers import voice

    monkeypatch.setattr(voice, "_caps_cache", None)
    seen = {}
    real = voice._probe_voice_engines

    def spy():
        seen["thread"] = threading.current_thread().name
        return real()

    monkeypatch.setattr(voice, "_probe_voice_engines", spy)

    loop_thread = {}

    async def _record():
        loop_thread["name"] = threading.current_thread().name
    asyncio.run(_record())

    resp = TestClient(web.app).get("/api/voice/capabilities")
    assert resp.status_code == 200
    assert "thread" in seen, "the probe never ran"
    assert seen["thread"] != loop_thread["name"], (
        "the ML import ran on the event loop thread — it will stall every other "
        "in-flight request while ctranslate2/CUDA load"
    )


def test_voice_capabilities_probes_once_and_serves_the_rest_from_cache(monkeypatch):
    """Import cost is paid once per process. The flags come from module imports,
    so they cannot change while the process runs."""
    from agents.core.routers import voice

    monkeypatch.setattr(voice, "_caps_cache", None)
    calls = []
    real = voice._probe_voice_engines
    monkeypatch.setattr(voice, "_probe_voice_engines",
                        lambda: (calls.append(1), real())[1])

    client = TestClient(web.app)
    for _ in range(4):
        assert client.get("/api/voice/capabilities").status_code == 200
    assert len(calls) == 1, f"probed {len(calls)} times; the cache is not holding"


def test_voice_capabilities_reads_consent_fresh_every_time(monkeypatch):
    """Consent IS revocable, so it must not be frozen into the engine cache."""
    from agents.core.routers import voice

    answers = iter([
        {"required": True, "granted": True, "allowed": True},
        {"required": True, "granted": False, "allowed": False},
    ])
    monkeypatch.setattr(voice, "_caps_cache", {
        "has_whisper": False, "has_edge": False, "has_kokoro": False,
        "consent_fn": lambda: next(answers),
    })
    client = TestClient(web.app)
    assert client.get("/api/voice/capabilities").json()["persona_voice"]["granted"] is True
    assert client.get("/api/voice/capabilities").json()["persona_voice"]["granted"] is False


# ── standing gate: no heavy import may sit on the event loop ──────────────────

# Importing any of these pulls a native/ML stack (torch, CUDA, ctranslate2, ...).
# Doing it inside an `async def` runs it ON the event loop, freezing every other
# in-flight request for the length of the import. That is what made routes with
# no I/O of their own — `/api/agents` — appear to hang.
_HEAVY_ROOTS = frozenset({
    "faster_whisper", "torch", "ctranslate2", "transformers", "sentence_transformers",
    "cv2", "numpy", "scipy", "pandas", "sklearn", "onnxruntime", "llama_cpp",
    "whisper", "matplotlib", "PIL", "tensorflow", "chromadb", "qdrant_client",
    "neo4j", "spacy", "edge_tts", "kokoro", "librosa", "soundfile", "ultralytics",
})
# Local modules that import one of the above at module scope, so importing THEM
# costs the same.
_HEAVY_LOCAL = frozenset({
    "core.voice.stt", "core.voice.tts",
    "agents.core.voice.stt", "agents.core.voice.tts",
})

# Async functions allowed to do it anyway, each with the reason. These are the
# three voice handlers that genuinely need the module to do their work; they call
# `await _voice_engines()` first, which pays the import in a worker thread, so by
# the time these lines run the module is already in sys.modules.
_WARMED_FIRST = {
    ("agents/core/routers/voice.py", "tts_endpoint"),
    ("agents/core/routers/voice.py", "tts_stream_endpoint"),
    ("agents/core/routers/voice.py", "stt_endpoint"),
}


def _heavy_imports_in_async_functions():
    import ast
    import pathlib

    found = []
    for path in sorted(pathlib.Path("agents").rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Import):
                    names = [a.name for a in inner.names]
                elif isinstance(inner, ast.ImportFrom):
                    names = [inner.module or ""]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] in _HEAVY_ROOTS or name in _HEAVY_LOCAL:
                        found.append((str(path), node.name, name, inner.lineno))
    return found


def test_no_unwarmed_heavy_import_runs_on_the_event_loop():
    offenders = [
        f"{path}:{line} async {fn}() imports {mod}"
        for path, fn, mod, line in _heavy_imports_in_async_functions()
        if (path, fn) not in _WARMED_FIRST
    ]
    assert not offenders, (
        "heavy import inside an async function — it will block the event loop:\n  "
        + "\n  ".join(offenders)
        + "\nEither hoist it to module scope, or pay it in a worker thread "
          "(asyncio.to_thread) and add the function to _WARMED_FIRST with a reason."
    )


def test_the_warmed_first_allowlist_has_not_gone_stale():
    """An entry that no longer imports anything heavy should be deleted, or the
    allowlist quietly grants permission nobody is using."""
    actual = {(path, fn) for path, fn, _, _ in _heavy_imports_in_async_functions()}
    stale = _WARMED_FIRST - actual
    assert not stale, f"remove these from _WARMED_FIRST, they no longer apply: {stale}"


def test_the_allowlisted_handlers_actually_warm_before_importing():
    """The allowlist claims these call `_voice_engines()` first. Verify it, so the
    exemption cannot survive someone deleting the warm-up."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("agents/core/routers/voice.py").read_text())
    by_name = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    for _, fn_name in _WARMED_FIRST:
        fn = by_name[fn_name]
        warm_lines = [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_voice_engines"
        ]
        heavy_lines = [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, (ast.Import, ast.ImportFrom))
            and (
                (getattr(n, "module", "") or "") in _HEAVY_LOCAL
                or any(a.name.split(".")[0] in _HEAVY_ROOTS
                       for a in getattr(n, "names", []) or [])
            )
        ]
        assert warm_lines, f"{fn_name} is allowlisted but never calls _voice_engines()"
        assert min(warm_lines) < min(heavy_lines), (
            f"{fn_name} imports the heavy module before warming it off the loop"
        )
