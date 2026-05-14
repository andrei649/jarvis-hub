#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load .env file
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("'\"")
        if key not in os.environ:
            os.environ[key] = val

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

from core.orchestrator import Orchestrator
from voice.audio_manager import VoiceManager
from core.router import IntentRouter


async def main():
    parser = argparse.ArgumentParser(description="JARVIS HUB — Personal AI Agent System")
    parser.add_argument("--cli", action="store_true", help="CLI mode (no voice, no web)")
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("JARVIS HUB — Personal AI Agent System")
    logger.info("=" * 50)

    orch = Orchestrator(agents_dir="agents", plugins_dir="plugins")
    voice = VoiceManager()
    router = IntentRouter()
    router.setup_defaults()

    await orch.start()
    voice.load_all()

    async def handle_command(text: str):
        logger.info(f"Command: {text}")
        best = router.best_match(text)
        if best and best != "jarvis":
            logger.info(f"Routing directly to: {best}")
            result = await orch.route(best, text)
        else:
            result = await orch.route_to_cns(text)
        response_text = result.text
        if result.escalated_to and result.specialized:
            response_text += f"\n\n[Specialist {result.escalated_to}]: {result.specialized}"
        logger.info(f"Response: {response_text[:200]}")
        audio = await voice.speak(response_text)
        return {"text": response_text, "audio": audio is not None}

    coros = []

    if not args.cli:
        await voice.start_listening(handle_command)
        from web.server import start_web_server
        coros.append(start_web_server(orch, voice, router, handle_command))
        coros.append(_keep_alive())
        logger.info("JARVIS HUB is ready. Say 'Jarvis' or visit http://localhost:8765")
    else:
        coros.append(_cli_loop(orch, router, voice, handle_command))

    await asyncio.gather(*coros)


async def _keep_alive():
    print("\n" + "=" * 50)
    print("  JARVIS HUB — Online")
    print("  Voice: Say 'Jarvis' + command")
    print("  Web:   http://localhost:8765")
    print("  API:   http://localhost:8765/api")
    print("=" * 50 + "\n")
    while True:
        await asyncio.sleep(1)


async def _cli_loop(orch, router, voice, handle_command):
    print("\nJARVIS HUB — CLI Mode. Type 'exit' to quit.\n")
    while True:
        try:
            text = await asyncio.get_event_loop().run_in_executor(None, input, "> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in ("exit", "quit", "q"):
            break
        result = await handle_command(text)
        print(f"\n{result['text']}\n")

    await orch.stop()


if __name__ == "__main__":
    asyncio.run(main())
