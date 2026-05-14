"""
Telegram Bot Plugin — Example plugin for Jarvis Hub.

Requires: TELEGRAM_BOT_TOKEN in .env or environment
Permission scope: read-write (can send and receive messages)
"""

from __future__ import annotations

import logging
from core.permission_gate import PermissionGate

logger = logging.getLogger("plugins.telegram")

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


class TelegramBotPlugin:
    def __init__(self, permission_gate: PermissionGate):
        self.app = None
        self.permission_gate = permission_gate
        self._message_queue = []
        self._on_message = None

    async def start(self, token: str, on_message_callback=None):
        if not TELEGRAM_AVAILABLE:
            logger.error("python-telegram-bot not installed")
            return False
        self._on_message = on_message_callback
        self.app = Application.builder().token(token).build()
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle))
        await self.app.initialize()
        await self.app.start()
        logger.info("Telegram bot started")
        return True

    async def _handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        text = update.message.text
        chat_id = update.effective_chat.id
        logger.info(f"Telegram message from {chat_id}: {text[:60]}")
        if self._on_message:
            response = await self._on_message(text, channel="telegram")
            if response:
                await update.message.reply_text(response[:4096])
        self._message_queue.append({"chat_id": chat_id, "text": text})

    async def send(self, chat_id: int, text: str):
        if self.app:
            await self.app.bot.send_message(chat_id=chat_id, text=text[:4096])

    async def stop(self):
        if self.app:
            await self.app.stop()
            await self.app.shutdown()


def create(permission_gate: PermissionGate) -> TelegramBotPlugin:
    return TelegramBotPlugin(permission_gate)
