"""Tests for N8NPlugin (H4.6 — Oracle n8n Workflow Designer).

All HTTP calls are mocked — no real n8n instance required.
Updated for H7.3: mocking is now via PluginHTTPClient instead of httpx.AsyncClient
context manager (the plugin no longer creates per-call context managers).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.plugins.n8n import N8NPlugin, _NOT_CONFIGURED
from agents.core.http_client import _clients as _http_registry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:5678"
API_KEY = "test-api-key-abc123"


@pytest.fixture(autouse=True)
def clear_http_registry():
    """Ensure a fresh PluginHTTPClient for every test."""
    _http_registry.pop("n8n", None)
    yield
    _http_registry.pop("n8n", None)


@pytest.fixture
def plugin():
    """Configured N8NPlugin instance (no real n8n)."""
    return N8NPlugin(base_url=BASE_URL, api_key=API_KEY)


@pytest.fixture
def unconfigured_plugin():
    """N8NPlugin with no base_url / api_key."""
    return N8NPlugin(base_url="", api_key="")


def _mock_response(status_code: int = 200, json_data: dict = None) -> MagicMock:
    """Build a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()  # no-op by default
    return resp


def _inject_mock_client(plugin: N8NPlugin, method: str, response: MagicMock):
    """Inject an AsyncMock into the plugin's PluginHTTPClient._client for *method*."""
    mock_httpx = MagicMock()
    mock_httpx.is_closed = False
    setattr(mock_httpx, method, AsyncMock(return_value=response))
    plugin._client._client = mock_httpx
    return mock_httpx


def _inject_error_client(plugin: N8NPlugin, method: str, exc):
    """Inject an AsyncMock that raises *exc* for *method*."""
    mock_httpx = MagicMock()
    mock_httpx.is_closed = False
    setattr(mock_httpx, method, AsyncMock(side_effect=exc))
    plugin._client._client = mock_httpx
    return mock_httpx


# ---------------------------------------------------------------------------
# not-configured guard
# ---------------------------------------------------------------------------

async def test_list_workflows_not_configured(unconfigured_plugin):
    result = await unconfigured_plugin.list_workflows()
    assert result["ok"] is False
    assert "not configured" in result["error"]


async def test_create_workflow_not_configured(unconfigured_plugin):
    result = await unconfigured_plugin.create_workflow("wf", [], {})
    assert result["ok"] is False
    assert _NOT_CONFIGURED in result["error"]


async def test_activate_not_configured(unconfigured_plugin):
    result = await unconfigured_plugin.activate_workflow("123")
    assert result["ok"] is False


async def test_daily_weather_not_configured(unconfigured_plugin):
    result = await unconfigured_plugin.create_daily_weather_workflow("Cluj")
    assert result["ok"] is False
    assert "not configured" in result["error"]


# ---------------------------------------------------------------------------
# list_workflows
# ---------------------------------------------------------------------------

async def test_list_workflows_hits_correct_url(plugin):
    workflows_data = {"data": [{"id": "wf-1", "name": "Test WF"}]}
    resp = _mock_response(200, workflows_data)
    mock_httpx = _inject_mock_client(plugin, "get", resp)

    result = await plugin.list_workflows()

    assert result["ok"] is True
    assert result["data"] == workflows_data
    mock_httpx.get.assert_called_once()
    call_args = mock_httpx.get.call_args
    assert call_args[0][0] == f"{BASE_URL}/api/v1/workflows"
    headers = call_args[1]["headers"]
    assert headers["X-N8N-API-KEY"] == API_KEY


# ---------------------------------------------------------------------------
# get_workflow
# ---------------------------------------------------------------------------

async def test_get_workflow_hits_correct_url(plugin):
    wf_data = {"id": "wf-42", "name": "My Workflow"}
    resp = _mock_response(200, wf_data)
    mock_httpx = _inject_mock_client(plugin, "get", resp)

    result = await plugin.get_workflow("wf-42")

    assert result["ok"] is True
    url = mock_httpx.get.call_args[0][0]
    assert url == f"{BASE_URL}/api/v1/workflows/wf-42"


# ---------------------------------------------------------------------------
# get_executions
# ---------------------------------------------------------------------------

async def test_get_executions_passes_workflow_id(plugin):
    exec_data = {"data": [{"id": "exec-1", "status": "success"}]}
    resp = _mock_response(200, exec_data)
    mock_httpx = _inject_mock_client(plugin, "get", resp)

    result = await plugin.get_executions("wf-99", limit=5)

    assert result["ok"] is True
    url = mock_httpx.get.call_args[0][0]
    assert url == f"{BASE_URL}/api/v1/executions"
    params = mock_httpx.get.call_args[1]["params"]
    assert params["workflowId"] == "wf-99"
    assert params["limit"] == 5


# ---------------------------------------------------------------------------
# create_workflow
# ---------------------------------------------------------------------------

async def test_create_workflow_posts_to_correct_url(plugin):
    created = {"id": "new-wf", "name": "Test Create"}
    resp = _mock_response(200, created)
    mock_httpx = _inject_mock_client(plugin, "post", resp)

    nodes = [{"id": "n1", "name": "Node1", "type": "n8n-nodes-base.scheduleTrigger"}]
    connections = {"Node1": {"main": []}}

    result = await plugin.create_workflow("Test Create", nodes, connections)

    assert result["ok"] is True
    assert result["data"] == created
    mock_httpx.post.assert_called_once()
    url = mock_httpx.post.call_args[0][0]
    assert url == f"{BASE_URL}/api/v1/workflows"
    headers = mock_httpx.post.call_args[1]["headers"]
    assert headers["X-N8N-API-KEY"] == API_KEY
    body = mock_httpx.post.call_args[1]["json"]
    assert body["name"] == "Test Create"
    assert body["nodes"] == nodes
    assert body["connections"] == connections


# ---------------------------------------------------------------------------
# activate_workflow / deactivate_workflow
# ---------------------------------------------------------------------------

async def test_activate_workflow_patches_correct_url(plugin):
    resp = _mock_response(200, {"id": "wf-7", "active": True})
    mock_httpx = _inject_mock_client(plugin, "patch", resp)

    result = await plugin.activate_workflow("wf-7")

    assert result["ok"] is True
    url = mock_httpx.patch.call_args[0][0]
    assert url == f"{BASE_URL}/api/v1/workflows/wf-7"
    body = mock_httpx.patch.call_args[1]["json"]
    assert body == {"active": True}


async def test_deactivate_workflow_sends_active_false(plugin):
    resp = _mock_response(200, {"id": "wf-7", "active": False})
    mock_httpx = _inject_mock_client(plugin, "patch", resp)

    result = await plugin.deactivate_workflow("wf-7")

    assert result["ok"] is True
    body = mock_httpx.patch.call_args[1]["json"]
    assert body == {"active": False}


# ---------------------------------------------------------------------------
# build_daily_weather_workflow — pure unit test, no HTTP
# ---------------------------------------------------------------------------

def test_build_daily_weather_workflow_structure(plugin):
    wf = plugin.build_daily_weather_workflow("Bucharest")

    assert "Daily Weather" in wf["name"]
    assert "Bucharest" in wf["name"]
    assert len(wf["nodes"]) == 2

    # Schedule node
    schedule = next(n for n in wf["nodes"] if "schedule" in n["type"].lower())
    assert schedule["type"] == "n8n-nodes-base.scheduleTrigger"
    assert "cronExpression" in schedule["parameters"]

    # HTTP Request node
    http = next(n for n in wf["nodes"] if "httpRequest" in n["type"])
    assert "wttr.in/Bucharest" in http["parameters"]["url"]
    assert http["parameters"]["method"] == "GET"

    # Connections wire schedule → http
    assert "Daily Schedule" in wf["connections"]
    targets = wf["connections"]["Daily Schedule"]["main"][0]
    assert any(t["node"] == "Fetch Weather" for t in targets)


def test_build_daily_weather_workflow_custom_city(plugin):
    wf = plugin.build_daily_weather_workflow("Cluj")
    http = next(n for n in wf["nodes"] if "httpRequest" in n["type"])
    assert "Cluj" in http["parameters"]["url"]
    assert "Cluj" in wf["name"]


# ---------------------------------------------------------------------------
# create_daily_weather_workflow — integration path (mocked HTTP)
# ---------------------------------------------------------------------------

async def test_create_daily_weather_workflow_calls_post(plugin):
    created = {"id": "wf-weather-1", "name": "Daily Weather — Bucharest", "active": False}
    resp = _mock_response(200, created)
    mock_httpx = _inject_mock_client(plugin, "post", resp)

    result = await plugin.create_daily_weather_workflow("Bucharest")

    assert result["ok"] is True
    assert result["data"]["id"] == "wf-weather-1"
    body = mock_httpx.post.call_args[1]["json"]
    assert "Daily Weather" in body["name"]
    assert "Bucharest" in body["name"]
    # Must have exactly 2 nodes
    assert len(body["nodes"]) == 2


# ---------------------------------------------------------------------------
# n8n down / connection error → friendly error, no crash
# ---------------------------------------------------------------------------

async def test_list_workflows_n8n_down(plugin):
    import httpx as httpx_mod
    _inject_error_client(plugin, "get", httpx_mod.ConnectError("Connection refused"))

    result = await plugin.list_workflows()

    assert result["ok"] is False
    assert "unreachable" in result["error"] or "Connection refused" in result["error"]


async def test_create_workflow_generic_exception(plugin):
    _inject_error_client(plugin, "post", Exception("unexpected"))

    result = await plugin.create_workflow("WF", [], {})

    assert result["ok"] is False
    assert "unexpected" in result["error"]


# ---------------------------------------------------------------------------
# env-var based configuration
# ---------------------------------------------------------------------------

async def test_plugin_reads_env_vars(monkeypatch):
    monkeypatch.setenv("N8N_BASE_URL", "http://n8n.local:5678")
    monkeypatch.setenv("N8N_API_KEY", "env-key-xyz")

    p = N8NPlugin()
    assert p.base_url == "http://n8n.local:5678"
    assert p.api_key == "env-key-xyz"
    assert p._configured() is True


async def test_plugin_missing_env_vars(monkeypatch):
    monkeypatch.delenv("N8N_BASE_URL", raising=False)
    monkeypatch.delenv("N8N_API_KEY", raising=False)

    p = N8NPlugin()
    assert p._configured() is False
    result = await p.list_workflows()
    assert result["ok"] is False
    assert "not configured" in result["error"]
