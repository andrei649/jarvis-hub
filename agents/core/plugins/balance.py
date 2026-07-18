"""
balance.py — Gecko Balance Reader Plugin.
Aggregates balances from ING API, Libra API, or CSV import.
Returns realistic mock data when no source is configured.
"""
import csv
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from ..http_client import PluginHTTPClient
from .degradation import degraded

logger = logging.getLogger("jarvis.gecko.balance")


def _parse_date(value: str):
    """Best-effort date parse for transaction rows; None if unparseable."""
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:19] if "T" in s else s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None

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


def _mask_account(value: str) -> str:
    """Mask all but the last 4 characters of an account / IBAN for display.

    The reader only needs to *show* which account a balance belongs to, never the
    full number — so even when real ING/Libra data is wired in, the HUD and Gecko
    summaries never broadcast a full IBAN (which the PII scanner flags as HIGH).
    """
    s = str(value or "")
    return s if len(s) <= 4 else "…" + s[-4:]


def _mask_accounts(data: dict) -> dict:
    """Copy a balances dict with every account number masked (keeps flags like 'mock')."""
    masked: dict = {}
    for source, accounts in data.items():
        if isinstance(accounts, list):
            masked[source] = [
                {**a, "account": _mask_account(a.get("account", ""))} if isinstance(a, dict) else a
                for a in accounts
            ]
        else:
            masked[source] = accounts
    return masked


class BalanceReaderPlugin:
    def __init__(self, ing_client_id: str = "", ing_client_secret: str = "",
                 libra_token: str = "", csv_path: str = "", tx_csv_path: str = ""):
        self.client = PluginHTTPClient.for_plugin("balance")
        self.ing_client_id = ing_client_id
        self.ing_client_secret = ing_client_secret
        self.libra_token = libra_token
        self.csv_path = csv_path
        # Transactions CSV (date, amount, category[, currency]); amount<0 = spend,
        # amount>0 = income. Source for the real burn-rate computation.
        self.tx_csv_path = tx_csv_path

    def available(self) -> bool:
        return bool(self.ing_client_id or self.libra_token or self.csv_path)

    async def get_balances(self) -> dict:
        """Aggregated balances, with account numbers masked for display safety."""
        return _mask_accounts(await self._raw_balances())

    async def _raw_balances(self) -> dict:
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
        if self.tx_csv_path or self.available():
            try:
                return await self._compute_burn_rate(days)
            except Exception:
                logger.warning("Burn rate computation failed — returning degraded data", exc_info=True)
        return degraded(
            dict(MOCK_BURN_RATE),
            reason="burn-rate needs a transactions source",
            needs=["plugins.gecko_tx_csv_path"],
        )

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

    def _load_transactions(self) -> list[dict]:
        """Parse the transactions CSV (columns: date, amount, category[, currency]).

        ``amount`` < 0 is spend, > 0 is income. Rows with an unparseable amount are
        skipped; an unparseable date keeps the row (counted in totals, not windowed).
        Returns ``[]`` when no transactions source is configured.
        """
        if not self.tx_csv_path:
            return []
        path = Path(self.tx_csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Transactions CSV not found: {self.tx_csv_path}")
        txns: list[dict] = []
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                raw_amt = row.get("amount", row.get("value", ""))
                try:
                    amount = float(str(raw_amt).replace(",", "").strip())
                except (TypeError, ValueError):
                    continue
                txns.append({
                    "date": _parse_date(row.get("date") or row.get("timestamp") or ""),
                    "amount": amount,
                    "category": (row.get("category") or row.get("type") or "other").strip().lower() or "other",
                })
        return txns

    async def _total_balance(self) -> float:
        """Best-effort sum of numeric balances across sources (currency-agnostic)."""
        try:
            raw = await self._raw_balances()
        except Exception:
            return 0.0
        total = 0.0
        for accounts in raw.values():
            if not isinstance(accounts, list):
                continue
            for acct in accounts:
                if isinstance(acct, dict):
                    try:
                        total += float(acct.get("balance", 0) or 0)
                    except (TypeError, ValueError):
                        pass
        return round(total, 2)

    async def _compute_burn_rate(self, days: int = 30) -> dict:
        """Real burn-rate from transactions: monthly spend/income, top categories,
        and runway (only when real balances are available). Degrades honestly when
        no transactions source is configured."""
        txns = self._load_transactions()
        if not txns:
            return degraded(
                dict(MOCK_BURN_RATE),
                reason="no transactions source configured",
                needs=["plugins.gecko_tx_csv_path"],
            )

        # Window relative to the most recent transaction (deterministic + offline).
        dated = [t["date"] for t in txns if t["date"] is not None]
        if dated:
            cutoff = max(dated) - timedelta(days=days)
            window = [t for t in txns if t["date"] is None or t["date"] >= cutoff]
        else:
            window = txns

        spend = sum(-t["amount"] for t in window if t["amount"] < 0)
        income = sum(t["amount"] for t in window if t["amount"] > 0)
        scale = 30.0 / days if days else 1.0
        monthly_spend = round(spend * scale, 2)
        monthly_income = round(income * scale, 2)

        cats: dict = defaultdict(float)
        for t in window:
            if t["amount"] < 0:
                cats[t["category"]] += -t["amount"]
        top_categories = {
            k: round(v, 2)
            for k, v in sorted(cats.items(), key=lambda kv: kv[1], reverse=True)[:4]
        }

        have_real_balances = bool(self.ing_client_id or self.libra_token or self.csv_path)
        total_balance = await self._total_balance() if have_real_balances else 0.0
        runway = (round(total_balance / monthly_spend, 1)
                  if have_real_balances and monthly_spend > 0 else None)

        return {
            "monthly_spend": monthly_spend,
            "monthly_income": monthly_income,
            "runway_months": runway,
            "top_categories": top_categories,
            "mock": False,
            "window_days": days,
            "transactions": len(window),
            "source": "csv",
        }

    async def close(self):
        await self.client.close()
