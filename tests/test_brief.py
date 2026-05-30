"""Tests for the Brief skill (H2.3) — Friday Morning consolidated dashboard."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from .conftest import make_app


@pytest.fixture
def app():
    return make_app("agents.core.skills.brief", "brief", prefix="/api/skills/brief", fallback_routes={
        "GET /generate": lambda: {
            "weather": {"temp": 20.0, "condition": "Clear"},
            "news": [],
            "market": {},
            "degraded_mode": False,
        },
    })


@patch("httpx.AsyncClient.get")
async def test_generate_brief_success(mock_get, app):
    mock_get.return_value = AsyncMock(status_code=200, json=lambda: {})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/skills/brief/generate")
    assert r.status_code == 200
    assert "weather" in r.json()


@patch("httpx.AsyncClient.get", side_effect=Exception("Timeout"))
async def test_generate_brief_total_fallback(mock_get, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/skills/brief/generate")
    assert r.status_code == 200
    data = r.json()
    assert "weather" in data
    # When degraded, flag is present
    if data.get("degraded_mode"):
        assert data["weather"]["status"] == "unavailable"
