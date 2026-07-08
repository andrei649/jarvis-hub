"""
email.py — Email channel adapter (SMTP send + IMAP idle receive).

Port of OpenJarvis's email channel to pure Python.
"""

import asyncio
import email
import logging
import imaplib
import smtplib
from email.mime.text import MIMEText
from typing import Optional

from .base import ChannelAdapter

logger = logging.getLogger("jarvis.channels.email")


class EmailChannel(ChannelAdapter):
    def __init__(self, handler=None, smtp_config: dict = None, imap_config: dict = None):
        super().__init__("email", handler)
        self.smtp = smtp_config or {}
        self.imap = imap_config or {}
        self._poll_task: Optional[asyncio.Task] = None

    async def start(self):
        if not self.smtp.get("host"):
            logger.info("Email channel: no SMTP configured, send disabled")
        if not self.imap.get("host"):
            logger.info("Email channel: no IMAP configured, receive disabled")
        else:
            self._running = True
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()

    async def send(self, message: str, **kwargs) -> bool:
        if not self.smtp.get("host"):
            logger.warning("SMTP not configured for email channel")
            return False

        to_addr = kwargs.get("to") or self.smtp.get("default_recipient", "")
        subject = kwargs.get("subject", "Jarvis Message")

        try:
            msg = MIMEText(message)
            msg["Subject"] = subject
            msg["From"] = self.smtp.get("from", "cabinet@localhost")
            msg["To"] = to_addr

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._smtp_send, msg, to_addr)
            logger.info(f"Email sent to {to_addr}")
            return True
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False

    def _smtp_send(self, msg: MIMEText, to_addr: str):
        with smtplib.SMTP(
            self.smtp["host"],
            self.smtp.get("port", 587),
            timeout=10,
        ) as server:
            if self.smtp.get("tls", True):
                server.starttls()
            if self.smtp.get("user"):
                server.login(self.smtp["user"], self.smtp.get("password", ""))
            server.send_message(msg)

    async def _poll_loop(self):
        while self._running:
            try:
                await self._check_imap()
            except Exception as e:
                logger.warning(f"IMAP poll error: {e}")
            await asyncio.sleep(self.imap.get("poll_interval", 60))

    async def _check_imap(self):
        loop = asyncio.get_event_loop()
        messages = await loop.run_in_executor(None, self._imap_fetch)

        for sender, subject, body in messages:
            if self.handler:
                text = body or subject
                await self.handler(text, channel="email", sender=sender,
                                   from_addr=sender, subject=subject)

    def _imap_fetch(self) -> list[tuple[str, str, str]]:

        mail = imaplib.IMAP4_SSL(self.imap["host"], self.imap.get("port", 993))
        mail.login(self.imap["user"], self.imap.get("password", ""))
        mail.select("INBOX")

        status, data = mail.search(None, "UNSEEN")
        messages = []
        if status == "OK":
            for num in data[0].split():
                status, msg_data = mail.fetch(num, "(RFC822)")
                if status == "OK":
                    raw = email.message_from_bytes(msg_data[0][1])
                    sender = raw.get("From", "")
                    subject = raw.get("Subject", "")
                    body = ""
                    if raw.is_multipart():
                        for part in raw.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(errors="replace")
                                break
                    else:
                        body = raw.get_payload(decode=True).decode(errors="replace")
                    messages.append((sender, subject, body))

        mail.logout()
        return messages
