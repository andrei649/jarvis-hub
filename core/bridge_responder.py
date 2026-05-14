"""
Bridge Responder — File-based bridge between Jarvis Hub and opencode.
When Ollama is unavailable, prompts are written to data/bridge/ for
opencode to read and respond to.
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("bridge")

BRIDGE_DIR = Path(__file__).parent.parent / "data" / "bridge"
POLL_INTERVAL = 2.0
MAX_WAIT = 120.0


class BridgeResponder:
    def __init__(self, bridge_dir: Optional[str] = None):
        self._dir = Path(bridge_dir) if bridge_dir else BRIDGE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._history: list[dict] = []

    def ask(self, model: str, prompt: str, agent_id: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        prompt_file = self._dir / f"prompt_{timestamp}.json"
        response_file = self._dir / f"response_{timestamp}.json"

        payload = {
            "id": timestamp,
            "agent_id": agent_id,
            "model": model,
            "prompt": prompt,
            "created_at": datetime.now().isoformat(),
        }
        prompt_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info(f"[BRIDGE] Prompt written to {prompt_file.name}")
        print(f"\n{'='*60}")
        print(f"  ⚡ PROMPT for agent '{agent_id}' (model: {model})")
        print(f"  📄 {prompt_file}")
        print(f"{'='*60}")
        print(f"\n{prompt[:500]}")
        if len(prompt) > 500:
            print("... (trunchiat)")
        print(f"\n{'='*60}")
        print(f"  Scrie răspunsul în {response_file.name}")
        print(f"{'='*60}\n")

        elapsed = 0.0
        while elapsed < MAX_WAIT:
            if response_file.exists():
                try:
                    data = json.loads(response_file.read_text())
                    answer = data.get("response", "")
                    logger.info(f"[BRIDGE] Response received ({len(answer)} chars)")
                    self._history.append({"prompt": prompt, "response": answer, "agent": agent_id})
                    return answer
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"[BRIDGE] Invalid response file: {e}")
                    time.sleep(POLL_INTERVAL)
                    elapsed += POLL_INTERVAL
                    continue
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

        logger.warning(f"[BRIDGE] Timed out waiting for response ({MAX_WAIT}s)")
        return f"[Bridge timeout] No response received within {MAX_WAIT}s for agent '{agent_id}'."

    def get_history(self, agent_id: Optional[str] = None) -> list[dict]:
        if agent_id:
            return [h for h in self._history if h["agent"] == agent_id]
        return self._history

    def count_pending(self) -> int:
        return len(list(self._dir.glob("prompt_*.json")))

    def count_unanswered(self) -> int:
        prompts = set(f.stem.replace("prompt_", "") for f in self._dir.glob("prompt_*.json"))
        responses = set(f.stem.replace("response_", "") for f in self._dir.glob("response_*.json"))
        return len(prompts - responses)
