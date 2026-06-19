"""
telegram_bot.py — Telegram bot plugin.

Provides programmatic send_message, send_photo, and parse_updates
for agents that need Telegram integration (e.g. Stark, Pepper).
Uses the PermissionGate to enforce domain restrictions.
"""

import logging

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.plugins.telegram_bot")


class TelegramBotPlugin:
    def __init__(self, token: str = ""):
        self.token = token
        self.api_base = f"https://api.telegram.org/bot{token}" if token else ""
        self.client = PluginHTTPClient.for_plugin("telegram_bot")

    async def send_message(self, chat_id: int, text: str,
                           parse_mode: str = "Markdown",
                           disable_preview: bool = True) -> bool:
        if not self.token:
            logger.warning("Telegram token not configured")
            return False
        try:
            resp = await self.client.post(
                f"{self.api_base}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": disable_preview,
                },
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    async def send_photo(self, chat_id: int, photo_url: str,
                         caption: str = "") -> bool:
        if not self.token:
            return False
        try:
            resp = await self.client.post(
                f"{self.api_base}/sendPhoto",
                json={
                    "chat_id": chat_id,
                    "photo": photo_url,
                    "caption": caption,
                },
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram photo error: {e}")
            return False

    async def send_document(self, chat_id: int, document_url: str,
                            caption: str = "") -> bool:
        if not self.token:
            return False
        try:
            resp = await self.client.post(
                f"{self.api_base}/sendDocument",
                json={
                    "chat_id": chat_id,
                    "document": document_url,
                    "caption": caption,
                },
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram document error: {e}")
            return False

    async def close(self):
        await self.client.close()
