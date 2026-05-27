"""
run.py — Jarvis main entry point.
Initializes orchestrator, detects LLM backends, loads agents,
skills, checkpointing, and starts an interactive REPL.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import JarvisConfig
from core.orchestrator import Orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(name)s  %(message)s",
)


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


if __name__ == "__main__":
    asyncio.run(main())
