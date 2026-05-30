"""Tests for the Content skill (H2.10) — Veronica social media drafts."""

from unittest.mock import mock_open, patch

import pytest
from httpx import AsyncClient, ASGITransport

from .conftest import make_app


@pytest.fixture
def app():
    return make_app("agents.core.skills.content", "content", prefix="/api/skills/content", fallback_routes={
        "POST /draft": lambda p: {"status": "success", "draft_id": "d1"},
        "GET /draft/{platform}": lambda plat: [],
    })


@patch("pathlib.Path.mkdir")
@patch("builtins.open", new_callable=mock_open)
async def test_create_draft_success(mock_file, mock_mkdir, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/skills/content/draft", json={"platform": "linkedin", "title": "Hello", "body": "World"})
    assert r.status_code == 200
    assert r.json()["status"] == "success"
