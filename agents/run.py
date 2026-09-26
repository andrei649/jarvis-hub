"""
run.py — Jarvis main entry point.
Initializes orchestrator, detects LLM backends, loads agents,
skills, checkpointing, and starts an interactive REPL.
"""

import asyncio
import contextlib
import sys
import threading
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# H273: the .env files load before anything reads them: the log file and level
# (setup_logging) and the scanner's extra patterns (read when the orchestrator's
# modules are imported) included, as serve.py does.
from agents.core.env_provenance import load_hub_env  # noqa: E402

load_hub_env()

from agents.core.config import JarvisConfig  # noqa: E402
from agents.core.log import setup_logging  # noqa: E402
from agents.core.orchestrator import Orchestrator  # noqa: E402

setup_logging()


async def main():
    load_hub_env()                     # once per process: the import above already loaded
    config = JarvisConfig()
    orch = Orchestrator(config)
    await orch.load_agents()
    print(f"LLM backend: {orch.llm_router.name}")
    print(f"Agents loaded: {list(orch.agents.keys())}")
    print(f"Skills loaded: {list(orch.skills.skills.keys())}")
    print(f"Checkpoints: {orch.checkpoints.info().get('checkpoints', 0)}")
    print(f"Sessions tracked: {orch.checkpoints.info().get('sessions_recorded', 0)}")

    print("\nJarvis v0.2.0 ready. Type your query (or 'exit' to quit).\n")
    print("Tip: End messages with '[learn: desc|step1,step2|cmd]' to save skills.")
    print("     Use '[handoff:agent_id]' to delegate between agents.\n")

    while True:
        try:
            text = await _prompt("> ")
        except asyncio.CancelledError:  # Ctrl-C while waiting for input
            break
        if text is None or text.strip().lower() in ("exit", "quit"):
            break
        response = await orch.handle_input(text)
        print(f"\n{response}\n")
    await _flush_embeddings(orch)


async def _prompt(text: str) -> str | None:
    """input() on a daemon thread; None at the end of input (H428).

    A plain input() would block the event loop, and with it every background turn
    embedding, until the next message. A daemon thread never holds the process
    open on exit, where an executor thread blocked in input() would.
    """
    loop = asyncio.get_running_loop()
    line = loop.create_future()

    def read() -> None:
        try:
            value = input(text)
        except (EOFError, KeyboardInterrupt):
            value = None
        with contextlib.suppress(RuntimeError):  # the REPL already exited
            loop.call_soon_threadsafe(lambda: line.done() or line.set_result(value))

    threading.Thread(target=read, name="repl-input", daemon=True).start()
    return await line


async def _flush_embeddings(orch, timeout: float = 30.0) -> None:
    """Let the last turns' background embeddings land before the REPL exits (H428)."""
    flush = getattr(getattr(orch, "memory", None), "flush_embeddings", None)
    if flush is None:
        return
    try:
        await asyncio.wait_for(flush(), timeout=timeout)
    except TimeoutError:
        print("(long-term memory did not finish writing; the last turns may not be remembered)")


if __name__ == "__main__":
    asyncio.run(main())
