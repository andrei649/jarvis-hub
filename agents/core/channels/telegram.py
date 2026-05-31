"""
telegram.py — Telegram channel adapter.

Long-polls Telegram for incoming messages and forwards
responses back as Telegram replies.
Uses the PermissionGate to enforce domain restrictions.
"""

import logging
from typing import Callable, Optional

import httpx

from .base import ChannelAdapter

logger = logging.getLogger("jarvis.channels.telegram")


class TelegramChannel(ChannelAdapter):
    def __init__(self, token: str, handler: Optional[Callable] = None,
                 allowed_user_ids: Optional[list[int]] = None):
        super().__init__("telegram", handler)
        self.token = token
        self.api_base = f"https://api.telegram.org/bot{token}"
        self.client = httpx.AsyncClient(timeout=15.0)
        self.allowed_users = allowed_user_ids or []
        self._offset = 0
        self._poll_task = None
        # Decision-inbox callback: on_callback(task_id, action, chat_id=..., user_id=...)
        self.on_callback: Optional[Callable] = None

    async def start(self):
        self._running = True
        me = await self._get_me()
        if me:
            logger.info(f"Telegram bot connected: {me.get('username', '?')}")
        self._poll_task = __import__("asyncio").create_task(self._poll_loop())
        logger.info("Telegram channel started")

    async def stop(self):
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
        await self.client.aclose()
        logger.info("Telegram channel stopped")

    async def send(self, message: str, chat_id: int = None, **kwargs) -> bool:
        cid = chat_id or kwargs.get("chat_id")
        if not cid:
            logger.warning("No chat_id provided for Telegram send")
            return False
        try:
            resp = await self.client.post(
                f"{self.api_base}/sendMessage",
                json={"chat_id": cid, "text": message, "parse_mode": "Markdown"},
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    async def send_card(self, chat_id: int, card: dict) -> bool:
        """Send a decision-inbox card (text + inline keyboard) built by inbox.py."""
        try:
            body = {"chat_id": chat_id, **card}
            resp = await self.client.post(f"{self.api_base}/sendMessage", json=body)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram send_card error: {e}")
            return False

    async def _answer_callback(self, callback_id: str, text: str = ""):
        try:
            await self.client.post(
                f"{self.api_base}/answerCallbackQuery",
                json={"callback_query_id": callback_id, "text": text},
            )
        except Exception:
            pass

    async def send_action(self, chat_id: int, action: str = "typing"):
        try:
            await self.client.post(
                f"{self.api_base}/sendChatAction",
                json={"chat_id": chat_id, "action": action},
            )
        except Exception:
            pass

    async def _poll_loop(self):
        while self._running:
            try:
                updates = await self._get_updates()
                for up in updates:
                    self._offset = up["update_id"] + 1
                    # Decision-inbox button taps arrive as callback_query updates.
                    cb = up.get("callback_query")
                    if cb:
                        await self._handle_callback(cb)
                        continue
                    msg = up.get("message") or up.get("edited_message")
                    if not msg:
                        continue
                    uid = msg["from"]["id"]
                    if self.allowed_users and uid not in self.allowed_users:
                        logger.info(f"Ignored message from user {uid}")
                        continue
                    text = msg.get("text", "")
                    chat_id = msg["chat"]["id"]
                    if not text:
                        continue
                    await self.receive(text, chat_id=chat_id)
            except Exception as e:
                logger.warning(f"Telegram poll error: {e}")
                await __import__("asyncio").sleep(3)

    async def _handle_callback(self, cb: dict):
        """Parse an inline-button tap and dispatch to on_callback."""
        from ..autonomy.inbox import parse_callback_data
        uid = (cb.get("from") or {}).get("id")
        if self.allowed_users and uid not in self.allowed_users:
            return
        parsed = parse_callback_data(cb.get("data", ""))
        if not parsed or not self.on_callback:
            await self._answer_callback(cb.get("id", ""))
            return
        task_id, action = parsed
        chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
        try:
            await self.on_callback(task_id, action, chat_id=chat_id, user_id=uid)
            await self._answer_callback(cb.get("id", ""), f"OK: {action}")
        except Exception as e:
            logger.warning(f"Telegram callback dispatch error: {e}")
            await self._answer_callback(cb.get("id", ""))

    async def _get_me(self) -> Optional[dict]:
        try:
            resp = await self.client.get(f"{self.api_base}/getMe")
            resp.raise_for_status()
            return resp.json().get("result")
        except Exception:
            return None

    async def _get_updates(self) -> list:
        try:
            resp = await self.client.get(
                f"{self.api_base}/getUpdates",
                params={"offset": self._offset, "timeout": 25},
            )
            resp.raise_for_status()
            return resp.json().get("result", [])
        except Exception:
            return []
