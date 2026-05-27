"""
gmail_plugin.py — Gmail API plugin.

Reads and composes emails via Gmail API.
Agents served: stark (corporate), pepper (calendar/meetings), veronica (comms).
Data scope: PROCESSED — data is processed locally, only metadata/results sent.
"""

import logging
import base64
from email.mime.text import MIMEText
from typing import Optional

import httpx

logger = logging.getLogger("jarvis.plugins.gmail")


class GmailPlugin:
    def __init__(self, access_token: str = ""):
        self.access_token = access_token
        self.api_base = "https://gmail.googleapis.com/gmail/v1/users/me"
        self.client = httpx.AsyncClient(timeout=15.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def list_messages(self, max_results: int = 10,
                            query: str = "") -> list[dict]:
        if not self.access_token:
            return [{"error": "Gmail not authenticated"}]
        try:
            params = {"maxResults": max_results}
            if query:
                params["q"] = query
            resp = await self.client.get(
                f"{self.api_base}/messages",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            messages = data.get("messages", [])
            result = []
            for m in messages[:max_results]:
                detail = await self.get_message(m["id"])
                if detail:
                    result.append(detail)
            return result
        except Exception as e:
            logger.error(f"Gmail list error: {e}")
            return [{"error": f"Gmail error: {e}"}]

    async def get_message(self, message_id: str) -> Optional[dict]:
        try:
            resp = await self.client.get(
                f"{self.api_base}/messages/{message_id}",
                headers=self._headers(),
                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
            resp.raise_for_status()
            data = resp.json()
            headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
            return {
                "id": message_id,
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": data.get("snippet", ""),
            }
        except Exception as e:
            logger.error(f"Gmail get error: {e}")
            return None

    async def send_email(self, to: str, subject: str,
                         body: str, cc: str = "") -> bool:
        if not self.access_token:
            return False
        try:
            msg = MIMEText(body)
            msg["To"] = to
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

            resp = await self.client.post(
                f"{self.api_base}/messages/send",
                headers=self._headers(),
                json={"raw": raw},
            )
            resp.raise_for_status()
            logger.info(f"Email sent to {to}: {subject}")
            return True
        except Exception as e:
            logger.error(f"Gmail send error: {e}")
            return False

    async def close(self):
        await self.client.aclose()
