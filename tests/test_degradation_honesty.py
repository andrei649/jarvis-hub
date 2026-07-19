"""Live-vs-Plumbing honesty layer — degraded() markers + degradation_info().

Every plugin whose calls silently fell back to mock data must (1) stamp those
results with the shared `_degraded {reason, needs}` marker and (2) expose the
`degradation_info()` contract so the /plugins surface can badge it BEFORE any
call is made. All offline — no credentials configured is exactly the case
under test.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.plugins.balance import BalanceReaderPlugin  # noqa: E402
from agents.core.plugins.crm_sync import CRMSyncPlugin  # noqa: E402
from agents.core.plugins.degradation import is_degraded  # noqa: E402
from agents.core.plugins.sms_alerts import SMSAlertsPlugin  # noqa: E402

# ── the mock results carry the marker ───────────────────────────────

async def test_sms_mock_result_is_stamped_degraded():
    plugin = SMSAlertsPlugin()  # no Twilio credentials
    result = await plugin.send_alert("+40700000000", "test")
    assert result["status"] == "mock_sent"
    assert is_degraded(result)
    assert result["_degraded"]["reason"] == "twilio_not_configured"
    assert "plugins.twilio_account_sid" in result["_degraded"]["needs"]
    await plugin.close()


async def test_crm_mock_result_is_stamped_degraded():
    plugin = CRMSyncPlugin()  # no Notion credentials
    result = await plugin.add_lead("Ada", "ACME", "ada@example.com")
    assert result["status"] == "mock_saved"
    assert is_degraded(result)
    assert result["_degraded"]["reason"] == "notion_not_configured"
    assert "plugins.notion_integration_token" in result["_degraded"]["needs"]
    await plugin.close()


async def test_mock_balances_are_stamped_degraded():
    plugin = BalanceReaderPlugin()  # no source configured
    result = await plugin.get_balances()
    assert is_degraded(result)
    assert "plugins.gecko_csv_path" in result["_degraded"]["needs"]


# ── degradation_info(): badgeable BEFORE any call ───────────────────

def test_degradation_info_contract_unconfigured():
    assert SMSAlertsPlugin().degradation_info()["reason"] == "twilio_not_configured"
    assert CRMSyncPlugin().degradation_info()["reason"] == "notion_not_configured"
    assert BalanceReaderPlugin().degradation_info()["reason"] == "no balance source configured"


def test_degradation_info_contract_configured_is_live():
    assert SMSAlertsPlugin(account_sid="AC1", auth_token="tk", from_number="+1").degradation_info() is None
    assert CRMSyncPlugin(integration_token="secret", database_id="db").degradation_info() is None
    assert BalanceReaderPlugin(csv_path="balances.csv").degradation_info() is None


# ── the /plugins surface exposes the badge fields ──────────────────

def test_plugins_router_exposes_degraded_fields():
    from agents.core.routers.plugins import _plugin_degradation

    degraded_plugin = SMSAlertsPlugin()
    info = _plugin_degradation(degraded_plugin)
    assert info == {"reason": "twilio_not_configured",
                    "needs": ["plugins.twilio_account_sid", "plugins.twilio_auth_token",
                              "plugins.twilio_from_number"]}

    live_plugin = SMSAlertsPlugin(account_sid="AC1", auth_token="tk")
    assert _plugin_degradation(live_plugin) is None

    class NoContract:
        pass

    assert _plugin_degradation(NoContract()) is None
    assert _plugin_degradation(None) is None

    class Broken:
        def degradation_info(self):
            raise RuntimeError("boom")

    assert _plugin_degradation(Broken())["reason"] == "degradation-introspection-error"
