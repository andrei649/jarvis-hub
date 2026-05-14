"""
Calendar Bridge Plugin — Read-only access to Google Calendar.
Requires: CALENDAR_CREDENTIALS_PATH in .env pointing to OAuth2 JSON
Permission scope: read-only
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from core.permission_gate import PermissionGate

logger = logging.getLogger("plugins.calendar")

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class CalendarBridge:
    def __init__(self, permission_gate: PermissionGate):
        self._service = None
        self.permission_gate = permission_gate

    async def start(self, credentials_path: Optional[str] = None) -> bool:
        if not GOOGLE_AVAILABLE:
            logger.error("google-api-python-client not installed")
            return False
        path = Path(credentials_path or os.getenv("CALENDAR_CREDENTIALS_PATH", ""))
        if not path.exists():
            logger.error(f"Calendar credentials not found at {path}")
            return False
        try:
            creds = None
            token_path = path.with_name("calendar_token.json")
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
                    creds = flow.run_local_server(port=0)
                token_path.write_text(creds.to_json())
            self._service = build("calendar", "v3", credentials=creds)
            logger.info("Calendar bridge started (read-only)")
            return True
        except Exception as e:
            logger.error(f"Calendar auth failed: {e}")
            return False

    async def list_events(
        self, max_results: int = 20, days_ahead: int = 7
    ) -> list[dict]:
        if not self._service:
            return []
        try:
            now = datetime.utcnow().isoformat() + "Z"
            later = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + "Z"
            events_result = (
                self._service.events()
                .list(
                    calendarId="primary",
                    timeMin=now,
                    timeMax=later,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = []
            for ev in events_result.get("items", []):
                start = ev["start"].get("dateTime", ev["start"].get("date"))
                events.append({
                    "id": ev["id"],
                    "summary": ev.get("summary", ""),
                    "start": start,
                    "end": ev["end"].get("dateTime", ev["end"].get("date")),
                    "location": ev.get("location", ""),
                    "description": ev.get("description", ""),
                })
            return events
        except Exception as e:
            logger.error(f"Calendar list error: {e}")
            return []

    async def get_event(self, event_id: str) -> Optional[dict]:
        if not self._service:
            return None
        try:
            ev = (
                self._service.events()
                .get(calendarId="primary", eventId=event_id)
                .execute()
            )
            return ev
        except Exception as e:
            logger.error(f"Calendar get error: {e}")
            return None

    async def stop(self):
        self._service = None


def create(permission_gate: PermissionGate) -> CalendarBridge:
    return CalendarBridge(permission_gate)
