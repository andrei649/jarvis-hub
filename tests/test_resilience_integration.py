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
