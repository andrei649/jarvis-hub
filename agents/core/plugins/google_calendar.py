"""
google_calendar.py — Google Calendar API v3 plugin with OAuth refresh.

Reads and manages calendar events via Google Calendar API.
Agents served: pepper (agenda, meetings, scheduling).
Data scope: PROCESSED — sensitive event data is processed locally.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from .oauth import refresh_google_token, load_token
from ..resilience import resilient_call

logger = logging.getLogger("jarvis.plugins.google_calendar")


class GoogleCalendarPlugin:
    def __init__(self, access_token: str = "", calendar_id: str = "primary"):
        self.access_token = access_token
        self.calendar_id = calendar_id
        self.api_base = "https://www.googleapis.com/calendar/v3"
        self.client = httpx.AsyncClient(timeout=15.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _ensure_token(self):
        if self.access_token:
            return
        token_data = load_token("google")
        if token_data and token_data.get("access_token"):
            self.access_token = token_data["access_token"]
            logger.info("Calendar: token restored from persistent store")

    @resilient_call(
        max_retries=2,
        timeout=15.0,
        backoff_base=1.0,
        backoff_max=3.0,
        circuit_breaker_key="plugin:calendar",
        circuit_breaker_threshold=3,
        metrics_agent_id="calendar",
        metrics_backend="google-api",
    )
    async def _request(self, method: str, path: str, **kwargs):
        await self._ensure_token()
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

    async def list_events(
        self,
        max_results: int = 10,
        days_ahead: int = 1,
        include_today: bool = True,
    ) -> list[dict]:
        try:
            now = datetime.now(timezone.utc)
            time_min = now.isoformat()
            time_max = (now + timedelta(days=days_ahead)).isoformat()

            params = {
                "calendarId": self.calendar_id,
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            resp = await self._request(
                "GET", f"/calendars/{self.calendar_id}/events",
                params=params,
            )
            data = resp.json()
            items = data.get("items", [])

            result = []
            for ev in items:
                start = ev.get("start", {})
                end = ev.get("end", {})
                now_ts = datetime.now(timezone.utc).timestamp()
                event_start_ts = self._parse_ts(start.get("dateTime", start.get("date", "")))

                if event_start_ts is None:
                    continue

                if event_start_ts < now_ts:
                    state = "past"
                elif event_start_ts - now_ts < 3600:
                    state = "next"
                else:
                    state = "upcoming"

                result.append({
                    "ts": start.get("dateTime", start.get("date", "")),
                    "title": ev.get("summary", "(no title)"),
                    "owner": ev.get("organizer", {}).get("displayName", ev.get("creator", {}).get("email", "system")),
                    "state": state,
                    "duration_min": self._calc_duration_min(start, end),
                    "location": ev.get("location", ""),
                    "description": ev.get("description", ""),
                    "hangout": ev.get("hangoutLink", ""),
                })
            return result
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error("Google Calendar auth expired — need re-auth")
                return [{"error": "Calendar auth expired — please re-authenticate"}]
            logger.error(f"Calendar list error: {e}")
            return [{"error": f"Calendar error: {e.response.status_code}"}]
        except Exception as e:
            logger.error(f"Calendar list error: {e}")
            return [{"error": f"Calendar error: {e}"}]

    async def create_event(
        self,
        summary: str,
        start_dt: str,
        end_dt: str,
        description: str = "",
        location: str = "",
        timezone_str: str = "Europe/Bucharest",
    ) -> Optional[dict]:
        try:
            body = {
                "summary": summary,
                "start": {"dateTime": start_dt, "timeZone": timezone_str},
                "end": {"dateTime": end_dt, "timeZone": timezone_str},
            }
            if description:
                body["description"] = description
            if location:
                body["location"] = location

            resp = await self._request(
                "POST", f"/calendars/{self.calendar_id}/events",
                json=body,
            )
            ev = resp.json()
            logger.info(f"Event created: {summary} at {start_dt}")
            return {"id": ev.get("id"), "htmlLink": ev.get("htmlLink")}
        except Exception as e:
            logger.error(f"Calendar create error: {e}")
            return None

    async def update_event(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start_dt: Optional[str] = None,
        end_dt: Optional[str] = None,
    ) -> bool:
        try:
            body = {}
            if summary:
                body["summary"] = summary
            if start_dt:
                body["start"] = {"dateTime": start_dt, "timeZone": "Europe/Bucharest"}
            if end_dt:
                body["end"] = {"dateTime": end_dt, "timeZone": "Europe/Bucharest"}

            resp = await self._request(
                "PATCH", f"/calendars/{self.calendar_id}/events/{event_id}",
                json=body,
            )
            logger.info(f"Event updated: {event_id}")
            return True
        except Exception as e:
            logger.error(f"Calendar update error: {e}")
            return False

    async def delete_event(self, event_id: str) -> bool:
        try:
            await self._request("DELETE", f"/calendars/{self.calendar_id}/events/{event_id}")
            logger.info(f"Event deleted: {event_id}")
            return True
        except Exception as e:
            logger.error(f"Calendar delete error: {e}")
            return False

    async def get_today_events(self) -> list[dict]:
        return await self.list_events(days_ahead=1)

    async def close(self):
        await self.client.aclose()

    @staticmethod
    def _parse_ts(ts_str: str) -> Optional[float]:
        if not ts_str:
            return None
        try:
            if "T" in ts_str:
                dt = datetime.fromisoformat(ts_str)
            else:
                dt = datetime.fromisoformat(ts_str).replace(hour=0, minute=0, tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _calc_duration_min(start: dict, end: dict) -> int:
        try:
            s = start.get("dateTime", start.get("date", ""))
            e = end.get("dateTime", end.get("date", ""))
            if s and e:
                s_dt = datetime.fromisoformat(s)
                e_dt = datetime.fromisoformat(e)
                return int((e_dt - s_dt).total_seconds() / 60)
        except (ValueError, TypeError):
            pass
        return 0
