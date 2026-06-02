import logging
from ..http_client import PluginHTTPClient
from ..resilience import resilient_call

logger = logging.getLogger("jarvis.plugins.crm")


class CRMSyncPlugin:
    def __init__(self, integration_token: str = "", database_id: str = ""):
        self.integration_token = integration_token.strip()
        self.database_id = database_id.strip()
        self.client = PluginHTTPClient.for_plugin("crm")

    @resilient_call(
        max_retries=2,
        timeout=12.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:crm",
        circuit_breaker_threshold=3,
        metrics_agent_id="stark",
        metrics_backend="notion.so",
    )
    async def add_lead(self, name: str, company: str, email: str, status: str = "Lead") -> dict:
        """Add new lead record to Notion database. Fallbacks to mock offline sync if unconfigured."""
        if not self.integration_token or not self.database_id:
            logger.warning("Notion Integration Token or Database ID missing — running in mock mode")
            return {"status": "mock_saved", "name": name, "company": company, "email": email, "id": "MOCK_NOTION_LEAD"}

        url = "https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {self.integration_token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": {
                "Name": {"title": [{"text": {"content": name}}]},
                "Company": {"rich_text": [{"text": {"content": company}}]},
                "Email": {"email": email},
                "Status": {"select": {"name": status}}
            }
        }
        resp = await self.client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        res = resp.json()
        return {"status": "synced", "id": res.get("id"), "url": res.get("url")}

    async def close(self):
        await self.client.close()
