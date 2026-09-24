"""
run.py — Jarvis main entry point.
Initializes orchestrator, detects LLM backends, loads agents,
skills, checkpointing, and starts an interactive REPL.
"""

import asyncio
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.core.config import JarvisConfig
from agents.core.log import setup_logging
from agents.core.orchestrator import Orchestrator

setup_logging()


async def main():
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
            text = input("> ")
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip().lower() in ("exit", "quit"):
            break
        response = await orch.handle_input(text)
        print(f"\n{response}\n")
        await _flush_embeddings(orch)
    await _flush_embeddings(orch, exiting=True)


async def _flush_embeddings(orch, timeout: float = 30.0, *, exiting: bool = False) -> None:
    """Let this turn's background turn embeddings land (H428).

    input() blocks the event loop, so queued writes would otherwise wait for the
    next turn, or be lost when the REPL exits. The reply is already on screen.
    """
    flush = getattr(getattr(orch, "memory", None), "flush_embeddings", None)
    if flush is None:
        return
    try:
        await asyncio.wait_for(flush(), timeout=timeout)
    except TimeoutError:
        print("(long-term memory did not finish writing; the last turns may not be remembered)" if exiting
              else "(long-term memory is still being written; it continues after your next message)")


if __name__ == "__main__":
    asyncio.run(main())
