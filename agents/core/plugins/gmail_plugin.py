"""
gmail_plugin.py — Gmail API plugin with OAuth refresh support.

Reads and composes emails via Gmail API.
Agents served: stark (corporate), pepper (calendar/meetings), veronica (comms).
Data scope: PROCESSED — data is processed locally, only metadata/results sent.
"""

import logging
import base64
from email.mime.text import MIMEText
from typing import Optional

from ..http_client import PluginHTTPClient
from .oauth import refresh_google_token, load_token
from ..resilience import resilient_call

logger = logging.getLogger("jarvis.plugins.gmail")


class GmailPlugin:
    def __init__(self, access_token: str = ""):
        self.access_token = access_token
        self.api_base = "https://gmail.googleapis.com/gmail/v1/users/me"
        self.client = PluginHTTPClient.for_plugin("gmail")
        self._refresh_attempted = False

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _ensure_token(self):
        if self.access_token:
            return
        token_data = load_token("google")
        if token_data and token_data.get("access_token"):
            self.access_token = token_data["access_token"]
            logger.info("Gmail: token restored from persistent store")

    async def _request(self, method: str, path: str, **kwargs):
        await self._ensure_token()
        if not self.access_token:
            raise RuntimeError(
                "Gmail not authenticated — connect your Google account in Settings"
            )
        return await self._do_request(method, path, **kwargs)

    @resilient_call(
        max_retries=2,
        timeout=15.0,
        backoff_base=1.0,
        backoff_max=3.0,
        circuit_breaker_key="plugin:gmail",
        circuit_breaker_threshold=3,
        metrics_agent_id="gmail",
        metrics_backend="google-api",
    )
    async def _do_request(self, method: str, path: str, **kwargs):
        url = f"{self.api_base}{path}"
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        for attempt in range(2):
            resp = await self.client.request(method, url, headers=headers, **kwargs)
            if resp.status_code == 401 and attempt == 0:
                new_token = await refresh_google_token()
                if new_token:
                    self.access_token = new_token
                    headers.update(self._headers())
                    continue
            resp.raise_for_status()
            return resp
        return resp

    async def list_messages(self, max_results: int = 10,
                            query: str = "") -> list[dict]:
        try:
            params = {"maxResults": max_results}
            if query:
                params["q"] = query
            resp = await self._request("GET", "/messages", params=params)
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
            resp = await self._request(
                "GET", f"/messages/{message_id}",
                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
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
        try:
            msg = MIMEText(body)
            msg["To"] = to
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            await self._request("POST", "/messages/send", json={"raw": raw})
            logger.info(f"Email sent to {to}: {subject}")
            return True
        except Exception as e:
            logger.error(f"Gmail send error: {e}")
            return False

    async def close(self):
        await self.client.close()
