"""Fast install smoke for ORIZONT 26 P2.5.

Default path: boot a real Orchestrator with one fake local LLM backend, verify
``/readyz`` through the FastAPI app, and run one deterministic chat turn. The
optional ``--dev`` flag runs the full pytest suite after the smoke succeeds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_ROOT = REPO_ROOT / "agents"
FAKE_MODEL = "install-smoke-fake-model"
FAKE_BACKEND_NAME = "install-smoke-fake-local"
DEFAULT_REPLY = "Install smoke reply: Nerva is alive."
DEFAULT_USER_TEXT = "Install smoke: please answer from the fake local model."


def _ensure_paths() -> None:
    for path in (REPO_ROOT, AGENTS_ROOT):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _quiet_optional_cli_warnings() -> None:
    """Keep the install smoke output focused on pass/fail.

    The orchestrator may warn about optional host capabilities (Docker/wasmtime)
    or locally-broken unsigned skills. Those are useful during normal debugging,
    but they are not install-smoke failures when `/readyz` and the fake turn pass.
    """
    import logging

    for name in ("jarvis.sandbox", "jarvis.skills", "jarvis.skills.loader"):
        logging.getLogger(name).setLevel(logging.ERROR)
    warnings.filterwarnings(
        "ignore",
        message=r".*starlette\.testclient.*deprecated.*",
        category=Warning,
    )


@contextmanager
def _temporary_env(updates: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@dataclass
class SmokeResult:
    ok: bool
    ready_status: int
    agents: int
    channels: int
    model: str
    reply: str
    elapsed_seconds: float


async def _build_fake_orchestrator(state_dir: Path, reply: str):
    _ensure_paths()
    from agents.core.config import JarvisConfig
    from agents.core.llm.base import LLMBackend
    from agents.core.orchestrator import Orchestrator

    class FakeBackend(LLMBackend):
        def __init__(self, text: str):
            self.reply = text
            self.calls: list[dict] = []

        async def generate(
            self,
            model: str,
            prompt: str,
            system: str = "",
            max_tokens: int = 1024,
            temperature: float = 0.7,
        ) -> str:
            self.calls.append({
                "model": model,
                "prompt": prompt,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
            })
            return self.reply

    fake = FakeBackend(reply)
    with _temporary_env({
        "JARVIS_HOME": str(state_dir),
        "JARVIS_LLM_WARMUP": "0",
        "JARVIS_TESTING": "1",
    }):
        orch = Orchestrator(JarvisConfig())

        async def _fake_detect() -> None:
            router = orch.llm_router
            router._backend = fake
            router._backend_name = FAKE_BACKEND_NAME
            router._detected_model = FAKE_MODEL
            router._local_model = FAKE_MODEL
            router._local_available = True
            router._ollama_available = False
            router._cloud_available = False
            router._claude_available = False

        orch.llm_router.detect = _fake_detect
        await orch.load_agents()
    return orch, fake


async def run_install_smoke(
    *,
    state_dir: Path | None = None,
    reply: str = DEFAULT_REPLY,
    user_text: str = DEFAULT_USER_TEXT,
) -> SmokeResult:
    started = time.perf_counter()
    owned_tmp: tempfile.TemporaryDirectory[str] | None = None
    if state_dir is None:
        owned_tmp = tempfile.TemporaryDirectory(
            prefix="jarvis-install-smoke-",
            ignore_cleanup_errors=True,
        )
        state_dir = Path(owned_tmp.name)
    else:
        state_dir.mkdir(parents=True, exist_ok=True)

    orch = None
    try:
        orch, fake = await _build_fake_orchestrator(state_dir, reply)
        from fastapi.testclient import TestClient

        from agents import web

        previous_orch = web.orch
        web.orch = orch
        try:
            client = TestClient(web.app)
            ready = client.get("/readyz")
            if ready.status_code != 200:
                raise RuntimeError(f"/readyz returned {ready.status_code}: {ready.text}")

            session_id = await orch.memory.new_session("install_smoke")
            actual_reply = await orch.handle_input(
                user_text,
                channel="web",
                session_id=session_id,
            )
            if actual_reply != reply:
                raise RuntimeError("fake LLM reply did not reach the chat turn")
            if not fake.calls or fake.calls[-1]["model"] != FAKE_MODEL:
                raise RuntimeError("chat turn did not use the fake local model")

            data = ready.json()
            return SmokeResult(
                ok=True,
                ready_status=ready.status_code,
                agents=int(data["checks"]["agents_loaded"]),
                channels=int(data["checks"]["channels"]),
                model=FAKE_MODEL,
                reply=actual_reply,
                elapsed_seconds=round(time.perf_counter() - started, 3),
            )
        finally:
            web.orch = previous_orch
    finally:
        if orch is not None:
            await orch.aclose()
        if owned_tmp is not None:
            owned_tmp.cleanup()


def run_dev_suite() -> int:
    import pytest

    return pytest.main([
        "tests/",
        "-n",
        "auto",
        "--dist",
        "loadfile",
        "--timeout=90",
        "-q",
        "--tb=short",
    ])


async def _async_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Nerva install smoke.")
    parser.add_argument("--state-dir", type=Path, default=None,
                        help="Optional smoke state directory; defaults to a temp dir.")
    parser.add_argument("--dev", action="store_true",
                        help="After the fast smoke, run the full pytest suite.")
    parser.add_argument("--json", action="store_true",
                        help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    _quiet_optional_cli_warnings()
    result = await run_install_smoke(state_dir=args.state_dir)
    payload = asdict(result)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "Install smoke passed: "
            f"{result.agents} agents, /readyz {result.ready_status}, "
            f"fake turn via {result.model} in {result.elapsed_seconds}s"
        )

    if args.dev:
        return run_dev_suite()
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(_async_main(argv))
    except Exception as exc:
        print(f"Install smoke failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
