"""Credential-backed plugins must fail closed in the runtime honesty layer."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.plugins.gmail_plugin import GmailPlugin  # noqa: E402
from agents.core.plugins.google_calendar import GoogleCalendarPlugin  # noqa: E402
from agents.core.plugins.homebridge import HomebridgePlugin  # noqa: E402
from agents.core.plugins.honesty import honesty_for, runtime_configuration  # noqa: E402
from agents.core.plugins.spotify_plugin import SpotifyPlugin  # noqa: E402


@pytest.mark.parametrize(
    ("plugin_id", "plugin"),
    [
        ("gmail", GmailPlugin()),
        ("google-calendar", GoogleCalendarPlugin()),
        ("spotify", SpotifyPlugin()),
        ("homebridge", HomebridgePlugin()),
    ],
)
def test_credential_backed_plugins_are_not_live_when_only_constructed(plugin_id, plugin):
    configured, source = runtime_configuration(plugin)
    assert configured is False
    assert source == "configured()"
    assert honesty_for(plugin_id, configured, source)["status"] == "needs_config"


@pytest.mark.parametrize(
    "plugin",
    [
        GmailPlugin(access_token="test-token"),
        GoogleCalendarPlugin(access_token="test-token"),
        SpotifyPlugin(access_token="test-token"),
        HomebridgePlugin(bridge_url="http://homebridge.test", api_token="test-token"),
    ],
)
def test_credential_backed_plugins_report_configured_with_required_runtime_material(plugin):
    configured, source = runtime_configuration(plugin)
    assert configured is True
    assert source == "configured()"
