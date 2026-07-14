"""Explicit child-pytest probe for process-local Jarvis data isolation."""

import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_pytest_data_root_contains_lifespan_and_autonomy_writes():
    operator_root = Path(os.environ["JARVIS_TEST_OPERATOR_SENTINEL"]).resolve()
    test_root = Path(os.environ["JARVIS_HOME"]).resolve()
    key_root = Path(os.environ["JARVIS_KEY_DIR"]).resolve()

    assert test_root != operator_root
    assert not test_root.is_relative_to(operator_root)
    assert not operator_root.is_relative_to(test_root)
    assert key_root.is_relative_to(test_root)

    from agents.core.autonomy import queue as autonomy_queue
    from agents.core.paths import data_root

    assert data_root().resolve().is_relative_to(test_root)
    assert Path(autonomy_queue.DEFAULT_DB).resolve().is_relative_to(test_root)

    from agents import web

    previous_token = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "pytest-data-root-probe"
    try:
        with TestClient(web.app) as client:
            response = client.post(
                "/autonomy/tasks",
                json={
                    "agent": "jarvis",
                    "kind": "draft_email",
                    "title": "Verify isolated pytest autonomy storage",
                },
                headers={"X-Admin-Token": "pytest-data-root-probe"},
            )
            assert response.status_code == 200, response.text
            assert Path(web.orch.autonomy_queue.db_path).resolve().is_relative_to(test_root)
    finally:
        web.ADMIN_TOKEN = previous_token

    assert not (operator_root / "autonomy.db").exists()
