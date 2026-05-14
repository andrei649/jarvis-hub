import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("claude")

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096
TIMEOUT = 120.0


class ClaudeResponder:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._model = model or os.getenv("CLAUDE_MODEL", DEFAULT_MODEL)
        self._client: Optional[httpx.AsyncClient] = None
        self._disabled = False

    async def start(self):
        self._client = httpx.AsyncClient(timeout=TIMEOUT)

    async def stop(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def is_available(self) -> bool:
        return bool(self._api_key) and self._client is not None and not self._disabled

    async def ask(self, model: str, prompt: str, agent_id: str = "unknown") -> str:
        if not self.is_available():
            return ""
        system_prompt, user_message = self._split_prompt(prompt)
        try:
            resp = await self._client.post(
                API_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": API_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": MAX_TOKENS,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = "".join(
                block["text"] for block in data.get("content", []) if block.get("type") == "text"
            )
            logger.info(f"[Claude] Response ({len(text)} chars) for '{agent_id}'")
            return text or "(no response)"
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            body = e.response.text[:200]
            logger.error(f"[Claude] HTTP {status}: {body}")
            if status in (400, 401, 403):
                logger.warning("[Claude] Permanent auth/billing error — disabling Claude backend")
                self._disabled = True
        except httpx.TimeoutException:
            logger.error("[Claude] Request timed out")
        except Exception as e:
            logger.error(f"[Claude] Error: {e}")
        return ""

    @staticmethod
    def _split_prompt(full_prompt: str) -> tuple[str, str]:
        parts = full_prompt.split("\n[User]:", 1)
        if len(parts) == 2:
            system = parts[0].strip()
            user = "[User]:" + parts[1].strip()
        else:
            system = ""
            user = full_prompt
        user = user.replace("\n[You]:", "").strip()
        return system, user
