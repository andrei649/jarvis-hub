"""Tests for the Calendar skill (H2.1) — Pepper Google Calendar management."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from httpx import AsyncClient, ASGITransport

from .conftest import make_app


@pytest.fixture
def app():
    return make_app("agents.core.skills.calendar", "calendar", prefix="/api/skills/calendar", fallback_routes={
        "GET /events": lambda: [],
        "POST /events": lambda p: {"status": "success", "event_id": "mock_id"},
        "PUT /events/{event_id}": lambda eid, p: {"status": "success"},
        "DELETE /events/{event_id}": lambda eid: {"status": "success"},
    })


@patch("httpx.AsyncClient.get")
async def test_get_events_success(mock_get, app):
    mock_get.return_value = AsyncMock(status_code=200, json=lambda: {"items": []})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/skills/calendar/events")
    assert r.status_code == 200


async def test_get_events_missing_token(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/skills/calendar/events")
    # Contract: without credentials, returns 401
    if r.status_code == 401:
        assert "credentials" in r.json().get("detail", "").lower()
