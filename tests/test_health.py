"""Tests for the Health skill (H2.4) — Hercules telemetry analysis."""

import pytest
from httpx import AsyncClient, ASGITransport

from .conftest import make_app


@pytest.fixture
def app():
    return make_app("agents.core.skills.health", "health", prefix="/api/skills/health", fallback_routes={
        "POST /metrics": lambda p: {
            "status": "processed",
            "analysis": {"mean": 81.0, "max": 110.0, "min": 68.0},
        },
    })


async def test_health_analysis_calculation(app):
    payload = {"metric_type": "heart_rate", "values": [72, 75, 80, 110, 68], "unit": "count/min"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/skills/health/metrics", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "processed"
    assert "analysis" in r.json()
