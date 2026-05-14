"""
Gmail Bridge Plugin — Read-only access to Gmail inbox.
Requires: GMAIL_CREDENTIALS_PATH in .env pointing to OAuth2 JSON
Permission scope: read-only
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from core.permission_gate import PermissionGate

logger = logging.getLogger("plugins.gmail")

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailBridge:
    def __init__(self, permission_gate: PermissionGate):
        self._service = None
        self.permission_gate = permission_gate

    async def start(self, credentials_path: Optional[str] = None) -> bool:
        if not GOOGLE_AVAILABLE:
            logger.error("google-api-python-client not installed")
            return False
        path = Path(credentials_path or os.getenv("GMAIL_CREDENTIALS_PATH", ""))
        if not path.exists():
            logger.error(f"Gmail credentials not found at {path}")
            return False
        try:
            creds = None
            token_path = path.with_name("gmail_token.json")
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
                    creds = flow.run_local_server(port=0)
                token_path.write_text(creds.to_json())
            self._service = build("gmail", "v1", credentials=creds)
            logger.info("Gmail bridge started (read-only)")
            return True
        except Exception as e:
            logger.error(f"Gmail auth failed: {e}")
            return False

    async def list_unread(self, max_results: int = 10) -> list[dict]:
        if not self._service:
            return []
        try:
            results = (
                self._service.users()
                .messages()
                .list(userId="me", q="is:unread", maxResults=max_results)
                .execute()
            )
            messages = []
            for msg in results.get("messages", []):
                full = (
                    self._service.users()
                    .messages()
                    .get(userId="me", id=msg["id"], format="metadata")
                    .execute()
                )
                headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
                messages.append({
                    "id": msg["id"],
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "snippet": full.get("snippet", ""),
                    "date": headers.get("Date", ""),
                })
            return messages
        except Exception as e:
            logger.error(f"Gmail list error: {e}")
            return []

    async def get_message(self, message_id: str) -> Optional[str]:
        if not self._service:
            return None
        try:
            msg = (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            payload = msg.get("payload", {})
            parts = [payload] + payload.get("parts", [])
            body = ""
            for p in parts:
                data = p.get("body", {}).get("data", "")
                if data:
                    import base64
                    body += base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            return body or msg.get("snippet", "")
        except Exception as e:
            logger.error(f"Gmail get error: {e}")
            return None

    async def stop(self):
        self._service = None


def create(permission_gate: PermissionGate) -> GmailBridge:
    return GmailBridge(permission_gate)
