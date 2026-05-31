# tests/test_resilience_integration.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, Mock
from agents.core.plugins.cloud_llm import CloudLLMPlugin
from agents.core.plugins.weather import WeatherPlugin


@pytest.mark.asyncio
async def test_cloud_llm_plugin_retries_on_5xx():
    """Test that CloudLLMPlugin retries on HTTP 5xx errors."""
    plugin = CloudLLMPlugin(
        anthropic_key="test-key",
        openai_key="",
        gemini_key=""
    )
    
    call_count = 0
    
    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            # Simulate 500 error
            response = Mock()
            response.status_code = 500
            response.raise_for_status = Mock(side_effect=Exception("500 Server Error"))
            return response
        # Success on second call
        response = Mock()
        response.status_code = 200
        response.raise_for_status = Mock()
        response.json = Mock(return_value={"content": [{"text": "Success"}]})
        return response
    
    with patch('httpx.AsyncClient.post', side_effect=mock_post):
        result = await plugin._call_anthropic("Test prompt", "Test system", "claude-sonnet-4-20250514", 1024)
    
    assert "Success" in result
    assert call_count == 2


@pytest.mark.asyncio
async def test_weather_plugin_retries_on_timeout():
    """Test that WeatherPlugin retries on timeout."""
    plugin = WeatherPlugin()
    
    call_count = 0
    
    async def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise asyncio.TimeoutError("Simulated timeout")
        response = Mock()
        response.status_code = 200
        response.raise_for_status = Mock()
        response.text = "Bucharest: 20°C, Sunny, 60% humidity, 15 km/h wind"
        return response
    
    with patch('httpx.AsyncClient.get', side_effect=mock_get):
        result = await plugin.get_weather("Bucharest")
    
    assert "20" in result or "Sunny" in result
    assert call_count == 2


# ── Task 7: /api/admin/stats resilience metrics ──

ADMIN_HEADERS = {"X-Admin-Token": "test-secret"}


def _admin_response(path):
    """Make a GET request to an admin endpoint with auth set up."""
    import agents.web as web
    from unittest.mock import MagicMock
    
    # Mock orch thoroughly so admin_stats endpoint works
    mock_orch = MagicMock()
    mock_orch.learning.interactions = []
    mock_orch.bench.samples = []
    mock_orch.bench.get_results.return_value = []
    mock_orch.learning.get_failure_patterns.return_value = []
    mock_orch.learning.get_route_counts.return_value = {}
    web.orch = mock_orch
    
    old_token = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    try:
        from fastapi.testclient import TestClient
        client = TestClient(web.app)
        return client.get(path, headers=ADMIN_HEADERS)
    finally:
        web.ADMIN_TOKEN = old_token


def test_admin_stats_includes_resilience():
    """Test that /api/admin/stats includes resilience metrics."""
    from core.resilience import get_metrics

    metrics = get_metrics()
    metrics.reset()
    metrics.record_success("test-agent", "test-backend", 1.5)
    metrics.record_failure("test-agent", "test-backend", "timeout")
    
    response = _admin_response("/api/admin/stats")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "resilience" in data
    assert "test-agent:test-backend" in data["resilience"]
    
    stats = data["resilience"]["test-agent:test-backend"]
    assert stats["success"] == 1
    assert stats["failure"] == 1
    assert stats["avg_latency"] == 1.5


def test_admin_stats_includes_circuit_breaker_state():
    """Test that /api/admin/stats includes circuit breaker states."""
    from core.resilience import get_circuit_breaker

    cb = get_circuit_breaker("test-circuit")
    cb.reset()
    for _ in range(5):
        cb.record_failure()
    
    response = _admin_response("/api/admin/stats")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "circuit_breakers" in data
    assert "test-circuit" in data["circuit_breakers"]
    assert data["circuit_breakers"]["test-circuit"]["state"] == "open"


@pytest.mark.asyncio
async def test_weather_plugin_retries_on_timeout():
    """Test that WeatherPlugin retries on timeout."""
    plugin = WeatherPlugin()
    
    call_count = 0
    
    async def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise asyncio.TimeoutError("Simulated timeout")
        response = Mock()
        response.status_code = 200
        response.raise_for_status = Mock()
        response.text = "Bucharest: 20°C, Sunny, 60% humidity, 15 km/h wind"
        return response
    
    with patch('httpx.AsyncClient.get', side_effect=mock_get):
        result = await plugin.get_weather("Bucharest")
    
    assert "20" in result or "Sunny" in result
    assert call_count == 2
