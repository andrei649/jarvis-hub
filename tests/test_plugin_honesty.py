"""
tests/test_plugin_honesty.py — per-plugin runtime honesty verdict + configured() fix.

The HUD honesty badges read a single per-plugin verdict (live vs needs_config).
This covers the resolver, the `configured()`-detection regression fix (iot_control
used `configured()`, which the /plugins runtime check ignored → it falsely reported
configured), and the keyless-plugin path.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.plugins.balance import BalanceReaderPlugin
from agents.core.plugins.honesty import honesty_for
from agents.core.plugins.iot_control import IoTControlPlugin
from agents.core.plugins.weather import WeatherPlugin
from agents.core.routers.plugins import _plugin_runtime_configuration


class TestHonestyFor:
    def test_keyless_live(self):
        v = honesty_for("weather", True, "loaded")
        assert v["status"] == "live"
        assert v["reason"] == "no setup required"
        assert v["needs"] == []

    def test_configured_live(self):
        v = honesty_for("balance", True, "available()")
        assert v["status"] == "live" and v["reason"] == "configured"

    def test_needs_config_lists_requirements(self):
        v = honesty_for("iot-control", False)
        assert v["status"] == "needs_config"
        assert "plugins.tuya_secret" in v["needs"]

    def test_unknown_plugin_needs_empty(self):
        assert honesty_for("mystery", False)["needs"] == []


class TestConfiguredDetection:
    def test_iot_configured_method_now_honored(self):
        # Regression: configured() (no underscore) was ignored, so an unconfigured
        # Tuya plugin reported configured/"loaded". It must now read as unconfigured.
        configured, source = _plugin_runtime_configuration(IoTControlPlugin())
        assert configured is False and source == "configured()"
        configured2, _ = _plugin_runtime_configuration(
            IoTControlPlugin(client_id="c", secret="s", device_id="d"))
        assert configured2 is True

    def test_balance_available_still_honored(self):
        configured, source = _plugin_runtime_configuration(BalanceReaderPlugin())
        assert configured is False and source == "available()"

    def test_keyless_plugin_reports_loaded(self):
        configured, source = _plugin_runtime_configuration(WeatherPlugin())
        assert configured is True and source == "loaded"

    def test_not_loaded(self):
        assert _plugin_runtime_configuration(None) == (False, "not-loaded")

    def test_end_to_end_iot_needs_config(self):
        configured, source = _plugin_runtime_configuration(IoTControlPlugin())
        v = honesty_for("iot-control", configured, source)
        assert v["status"] == "needs_config"
        assert "plugins.tuya_secret" in v["needs"]
