"""Tests for the Brief skill (H2.3) — Friday Morning consolidated dashboard."""

import pytest
from httpx import AsyncClient, ASGITransport

from .conftest import make_app


@pytest.fixture
def app():
    def _handler():
        return {
            "weather": {"temp": 20.0, "condition": "Clear"},
            "news": [],
            "market": {},
            "degraded_mode": False,
        }
    return make_app("agents.core.skills.brief", "brief", prefix="/api/skills/brief", fallback_routes={
        "GET /generate": _handler,
    })


async def test_generate_brief_success(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/skills/brief/generate")
    assert r.status_code == 200
    data = r.json()
    assert "weather" in data
    assert "news" in data
    assert "market" in data


async def test_generate_brief_degraded_flag(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/skills/brief/generate")
    assert r.status_code == 200
    data = r.json()
    # degraded_mode is a boolean present in the response
    assert isinstance(data.get("degraded_mode"), bool)
