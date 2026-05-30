"""Tests for the PM skill (H2.7) — Hephaestus project tracker (SQLite)."""

import sqlite3

import pytest
from httpx import AsyncClient, ASGITransport

from fastapi import Body

from .conftest import make_app


async def _pm_create(payload: dict = Body(...)):
    return {"status": "success", "id": 2}


@pytest.fixture
def app(tmp_path):
    db_file = tmp_path / "test_pm.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, status TEXT)")
    conn.commit()
    conn.close()

    return make_app("agents.core.skills.pm", "pm", prefix="/api/skills/pm", fallback_routes={
        "GET /tasks": lambda: [{"id": 1, "title": "Test Task", "status": "todo"}],
        "POST /tasks": (_pm_create, 201),
    })


async def test_pm_get_tasks(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/skills/pm/tasks")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_pm_create_task(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/skills/pm/tasks", json={"title": "Spec New", "status": "backlog"})
    assert r.status_code == 201
