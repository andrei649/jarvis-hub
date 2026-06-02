"""
balance.py — Gecko Balance Reader Plugin.
Aggregates balances from ING API, Libra API, or CSV import.
Returns realistic mock data when no source is configured.
"""
import csv
import json
import logging
from pathlib import Path
from typing import Optional

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.gecko.balance")

MOCK_BALANCES = {
    "ing": [
        {"account": "RO12INGB1234567890", "balance": 12450.32, "currency": "RON"},
        {"account": "RO12INGB0987654321", "balance": 350.00, "currency": "EUR"},
    ],
    "libra": [
        {"account": "LIBRA123456", "balance": 3200.00, "currency": "RON"},
    ],
    "mock": True,
}

MOCK_BURN_RATE = {
    "monthly_spend": 4200.00,
    "monthly_income": 8500.00,
    "runway_months": 4.5,
    "top_categories": {"food": 1200, "utilities": 800, "transport": 600, "subscriptions": 350},
    "mock": True,
}


class BalanceReaderPlugin:
    def __init__(self, ing_client_id: str = "", ing_client_secret: str = "",
                 libra_token: str = "", csv_path: str = ""):
        self.client = PluginHTTPClient.for_plugin("balance")
        self.ing_client_id = ing_client_id
        self.ing_client_secret = ing_client_secret
        self.libra_token = libra_token
        self.csv_path = csv_path

    def available(self) -> bool:
        return bool(self.ing_client_id or self.libra_token or self.csv_path)

    async def get_balances(self) -> dict:
        if self.ing_client_id:
            try:
                return await self._fetch_ing()
            except Exception as e:
                logger.warning(f"ING API failed: {e}")
        if self.libra_token:
            try:
                return await self._fetch_libra()
            except Exception as e:
                logger.warning(f"Libra API failed: {e}")
        if self.csv_path:
            try:
                return self._parse_csv()
            except Exception as e:
                logger.warning(f"CSV import failed: {e}")
        return dict(MOCK_BALANCES)

    async def get_summary(self) -> str:
        data = await self.get_balances()
        lines = []
        for source, accounts in data.items():
            if source == "mock":
                continue
            lines.append(f"**{source.upper()}:**")
            for acct in accounts:
                lines.append(f"  {acct['account']}: {acct['balance']:,.2f} {acct['currency']}")
        if data.get("mock"):
            lines.append("_(mock data — configurează ING/Libra API în Admin → Plugins)_")
        return "\n".join(lines) if lines else "No balance data available."

    async def get_burn_rate(self, days: int = 30) -> dict:
        if self.available():
            try:
                return await self._compute_burn_rate(days)
            except Exception:
                logger.warning("Burn rate computation failed — returning mock data", exc_info=True)
        return dict(MOCK_BURN_RATE)

    async def _fetch_ing(self) -> dict:
        url = "https://api.ing.com/v2/accounts"
        headers = {"Authorization": f"Bearer {self.ing_client_secret}"}
        resp = await self.client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        accounts = []
        for acct in data.get("accounts", []):
            accounts.append({
                "account": acct.get("iban", acct.get("id", "")),
                "balance": acct.get("balance", {}).get("amount", 0),
                "currency": acct.get("balance", {}).get("currency", "RON"),
            })
        return {"ing": accounts}

    async def _fetch_libra(self) -> dict:
        url = "https://api.libra.ro/v1/accounts"
        headers = {"Authorization": f"Bearer {self.libra_token}"}
        resp = await self.client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        accounts = []
        for acct in data.get("data", []):
            accounts.append({
                "account": acct.get("id", ""),
                "balance": acct.get("balance", 0),
                "currency": acct.get("currency", "RON"),
            })
        return {"libra": accounts}

    def _parse_csv(self) -> dict:
        path = Path(self.csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {self.csv_path}")
        accounts = []
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                accounts.append({
                    "account": row.get("account", row.get("iban", "")),
                    "balance": float(row.get("balance", row.get("amount", 0))),
                    "currency": row.get("currency", "RON"),
                })
        return {"csv": accounts}

    async def _compute_burn_rate(self, days: int = 30) -> dict:
        return dict(MOCK_BURN_RATE)

    async def close(self):
        await self.client.close()
