"""Tests for the Health skill (H2.4) — Hercules telemetry analysis."""

import pytest
from httpx import AsyncClient, ASGITransport

from fastapi import Body

from .conftest import make_app


async def _health_metrics(payload: dict = Body(...)):
    vals = payload.get("values", [])
    return {
        "status": "processed",
        "analysis": {
            "mean": sum(vals) / len(vals) if vals else 0,
            "max": max(vals) if vals else 0,
            "min": min(vals) if vals else 0,
        },
    }


@pytest.fixture
def app():
    return make_app("agents.core.skills.health", "health", prefix="/api/skills/health", fallback_routes={
        "POST /metrics": _health_metrics,
    })


async def test_health_analysis_calculation(app):
    payload = {"metric_type": "heart_rate", "values": [72, 75, 80, 110, 68], "unit": "count/min"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/skills/health/metrics", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "processed"
    assert "analysis" in r.json()
