import logging
from ..http_client import PluginHTTPClient
from ..resilience import resilient_call
from .degradation import degraded

logger = logging.getLogger("jarvis.plugins.sms")


_NEEDS = ["plugins.twilio_account_sid", "plugins.twilio_auth_token", "plugins.twilio_from_number"]


class SMSAlertsPlugin:
    def __init__(self, account_sid: str = "", auth_token: str = "", from_number: str = ""):
        self.account_sid = account_sid.strip()
        self.auth_token = auth_token.strip()
        self.from_number = from_number.strip()
        self.client = PluginHTTPClient.for_plugin("sms-alerts")

    def degradation_info(self) -> "dict | None":
        """None when live; otherwise why results will be mock + what config fixes it."""
        if self.account_sid and self.auth_token:
            return None
        return {"reason": "twilio_not_configured", "needs": list(_NEEDS)}

    @resilient_call(
        max_retries=2,
        timeout=10.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:sms",
        circuit_breaker_threshold=3,
        metrics_agent_id="steve",
        metrics_backend="twilio.com",
    )
    async def send_alert(self, to_number: str, message: str) -> dict:
        """Send urgent SMS alert. Falls back to mock sync if credentials missing."""
        if not self.account_sid or not self.auth_token:
            logger.warning("Twilio credentials missing — running in mock offline preview mode")
            return degraded(
                {"status": "mock_sent", "to": to_number, "message": message, "sid": "MOCK_SMS_123456"},
                reason="twilio_not_configured",
                needs=_NEEDS,
            )

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        auth = (self.account_sid, self.auth_token)
        data = {
            "To": to_number,
            "From": self.from_number,
            "Body": message,
        }
        
        resp = await self.client.post(url, auth=auth, data=data)
        resp.raise_for_status()
        res = resp.json()
        return {"status": "sent", "to": to_number, "sid": res.get("sid")}

    async def close(self):
        await self.client.close()
