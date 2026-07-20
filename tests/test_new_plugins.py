import pytest
from agents.core.plugins.sms_alerts import SMSAlertsPlugin
from agents.core.plugins.crm_sync import CRMSyncPlugin
from agents.core.plugins.iot_control import IoTControlPlugin
from agents.core.plugin_gate import PermissionGate, NetworkAccess


@pytest.mark.anyio
async def test_sms_alerts_mock_fallback():
    # If twilio keys are unconfigured, plugin should fallback to mock mode seamlessly
    plugin = SMSAlertsPlugin(account_sid="", auth_token="", from_number="")
    try:
        res = await plugin.send_alert(to_number="+40700000000", message="Steve Alert: CPU resource limit exceeded!")
        assert res["status"] == "mock_sent"
        assert res["to"] == "+40700000000"
        assert "MOCK_SMS" in res["sid"]
        # honesty contract: a mock fallback must self-report so the HUD can badge it
        assert res["_mock"] is True
        assert "plugins.twilio_auth_token" in res["_degraded"]["needs"]
    finally:
        await plugin.close()


@pytest.mark.anyio
async def test_crm_sync_mock_fallback():
    # If Notion integration keys are omitted, should run fallback mock sync
    plugin = CRMSyncPlugin(integration_token="", database_id="")
    try:
        res = await plugin.add_lead(name="Andrei", company="Bonobo", email="andrei@bonobo.ro", status="Lead")
        assert res["status"] == "mock_saved"
        assert res["name"] == "Andrei"
        assert res["id"] == "MOCK_NOTION_LEAD"
        # honesty contract: a mock fallback must self-report so the HUD can badge it
        assert res["_mock"] is True
        assert "plugins.notion_integration_token" in res["_degraded"]["needs"]
    finally:
        await plugin.close()


@pytest.mark.anyio
async def test_iot_control_degraded_fallback():
    # If Tuya credentials are missing, the plugin must NOT pretend to toggle a
    # device — it returns an honest, degraded result (no device touched). The old
    # "mock_toggled" success label was misleading; the real signing path only runs
    # when credentials are present (covered in test_live_remediation.py).
    plugin = IoTControlPlugin(client_id="", secret="", device_id="")
    try:
        res = await plugin.toggle_switch(state=True)
        assert res["status"] == "not_configured"
        assert res["state"] == "ON"
        assert res["_mock"] is True
        assert res["_degraded"]["needs"]  # names the settings the owner must supply

        res_off = await plugin.toggle_switch(state=False)
        assert res_off["status"] == "not_configured"
        assert res_off["state"] == "OFF"
    finally:
        await plugin.close()


def test_permission_gate_scopes_for_new_plugins():
    gate = PermissionGate()
    
    # Assert that gate successfully loaded our 3 new plugins manifests
    assert "sms-alerts" in gate.plugins
    assert "crm-sync" in gate.plugins
    assert "iot-control" in gate.plugins

    # Verify that sms-alerts only serves allowed domains and allowed agents
    sms = gate.plugins["sms-alerts"]
    assert sms.network_access == NetworkAccess.RESTRICTED
    assert "api.twilio.com" in sms.allowed_domains
    
    # Allowed agent "steve" calling sms-alerts with Twilio domain should be permitted
    assert gate.check_call("sms-alerts", agent_id="steve", target_domain="api.twilio.com") is True
    # Non-allowed agent "frigga" calling sms-alerts should be blocked
    assert gate.check_call("sms-alerts", agent_id="frigga", target_domain="api.twilio.com") is False
    # Allowed agent calling unauthorized domain should be blocked
    assert gate.check_call("sms-alerts", agent_id="steve", target_domain="malicious.org") is False

    # Verify that crm-sync permissions restrict access correctly
    crm = gate.plugins["crm-sync"]
    assert crm.network_access == NetworkAccess.RESTRICTED
    assert "api.notion.com" in crm.allowed_domains
    
    assert gate.check_call("crm-sync", agent_id="stark", target_domain="api.notion.com") is True
    assert gate.check_call("crm-sync", agent_id="hercules", target_domain="api.notion.com") is False

    # Verify that iot-control restricts access correctly
    iot = gate.plugins["iot-control"]
    assert gate.check_call("iot-control", agent_id="jarvis", target_domain="openapi.tuya.com") is True
    assert gate.check_call("iot-control", agent_id="athena", target_domain="openapi.tuya.com") is False
