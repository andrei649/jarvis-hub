"""
tests/test_live_remediation.py — Live-vs-Plumbing remediation (2026-07-18).

Covers the first tranche of "mock → real" builds from the capability audit
(docs/research/2026-07-18-live-vs-plumbing-capability-audit.md):
  * the degradation honesty helper (mock fallbacks self-report consistently),
  * real Tuya Cloud OpenAPI request-signing (replaces hardcoded MOCK_SIGNATURE),
  * real balance burn-rate computed from a transactions CSV.

All offline — no network. Signing is checked against pinned vectors so the
algorithm can't silently drift.
"""
import sys, os, hmac, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.plugins.degradation import degraded, is_degraded
from agents.core.plugins.iot_control import (
    IoTControlPlugin, tuya_sign, _string_to_sign, _EMPTY_BODY_SHA256,
)
from agents.core.plugins.balance import BalanceReaderPlugin


# ── degradation helper ──────────────────────────────────────────────────────

class TestDegradation:
    def test_degraded_preserves_real_keys_and_stamps_markers(self):
        out = degraded({"monthly_spend": 10}, reason="no source", needs=["plugins.x"])
        assert out["monthly_spend"] == 10          # real keys survive
        assert out["_mock"] is True and out["mock"] is True
        assert out["_degraded"] == {"reason": "no source", "needs": ["plugins.x"]}

    def test_degraded_empty_payload(self):
        out = degraded(reason="r")
        assert out["_degraded"]["needs"] == []

    def test_is_degraded(self):
        assert is_degraded(degraded({}, reason="r")) is True
        assert is_degraded({"mock": True}) is True
        assert is_degraded({"real": 1}) is False
        assert is_degraded("nope") is False


# ── Tuya Cloud OpenAPI signing ──────────────────────────────────────────────

def _independent_sign(secret, client_id, t, nonce, sts, token=""):
    """Re-derives the Tuya signature from the spec, independently of the plugin."""
    msg = f"{client_id}{token}{t}{nonce}{sts}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest().upper()


class TestTuyaSigning:
    def test_empty_body_hash_constant(self):
        assert _EMPTY_BODY_SHA256 == hashlib.sha256(b"").hexdigest()

    def test_string_to_sign_shape(self):
        sts = _string_to_sign("GET", "/v1.0/token?grant_type=1", "")
        assert sts == f"GET\n{_EMPTY_BODY_SHA256}\n\n/v1.0/token?grant_type=1"

    def test_token_sign_pinned_vector(self):
        sts = _string_to_sign("GET", "/v1.0/token?grant_type=1", "")
        sig = tuya_sign("secret", "client", "1700000000000", "", sts)
        assert sig == "AF2D781BBC570A91B529BBFF7CFE5C2BBA595904016B31D6BD47EEB5ED2CB62B"
        assert sig == _independent_sign("secret", "client", "1700000000000", "", sts)

    def test_command_sign_pinned_vector(self):
        sts = _string_to_sign(
            "POST", "/v1.0/devices/dev1/commands",
            '{"commands":[{"code":"switch_1","value":true}]}',
        )
        sig = tuya_sign("secret", "client", "1700000000000", "n1", sts, access_token="tok123")
        assert sig == "8C653B08E6F25DDF40AAA6BA9A35874F62D605402BBD54B67AB6BF5A7C153AC4"

    def test_sign_is_real_not_mock(self):
        sts = _string_to_sign("GET", "/v1.0/token?grant_type=1", "")
        sig = tuya_sign("s", "c", "1", "", sts)
        assert sig != "MOCK_SIGNATURE"
        assert len(sig) == 64 and sig == sig.upper()

    async def test_unconfigured_toggle_is_degraded(self):
        plugin = IoTControlPlugin()
        out = await plugin.toggle_switch(True)
        assert is_degraded(out) is True
        assert out["status"] == "not_configured"
        assert "plugins.tuya_secret" in out["_degraded"]["needs"]
        assert plugin.configured() is False
        await plugin.close()

    def test_configured_flag(self):
        assert IoTControlPlugin(client_id="c", secret="s", device_id="d").configured() is True


# ── balance burn-rate from transactions ─────────────────────────────────────

class TestBurnRate:
    async def test_real_burn_rate_from_csv(self, tmp_path):
        csv_file = tmp_path / "tx.csv"
        csv_file.write_text(
            "date,amount,category\n"
            "2026-07-01,-1200,food\n"
            "2026-07-05,-800,utilities\n"
            "2026-07-10,-600,transport\n"
            "2026-07-15,5000,salary\n"
            "2026-07-20,-400,food\n",
            encoding="utf-8",
        )
        plugin = BalanceReaderPlugin(tx_csv_path=str(csv_file))
        br = await plugin.get_burn_rate(days=30)
        assert br["mock"] is False and br["source"] == "csv"
        assert br["transactions"] == 5
        assert br["monthly_spend"] == 3000.0      # 1200+800+600+400
        assert br["monthly_income"] == 5000.0
        assert list(br["top_categories"])[0] == "food"   # 1200+400 = 1600
        assert br["top_categories"]["food"] == 1600.0
        assert br["runway_months"] is None        # no real balances configured
        await plugin.close()

    async def test_runway_uses_real_balance(self, tmp_path):
        (tmp_path / "tx.csv").write_text(
            "date,amount,category\n2026-07-01,-1000,food\n", encoding="utf-8")
        (tmp_path / "bal.csv").write_text(
            "account,balance,currency\nACC1,3000,RON\n", encoding="utf-8")
        plugin = BalanceReaderPlugin(
            csv_path=str(tmp_path / "bal.csv"), tx_csv_path=str(tmp_path / "tx.csv"))
        br = await plugin.get_burn_rate(days=30)
        assert br["mock"] is False
        assert br["monthly_spend"] == 1000.0
        assert br["runway_months"] == 3.0         # 3000 / 1000
        await plugin.close()

    async def test_no_tx_source_degrades_honestly(self):
        plugin = BalanceReaderPlugin()
        br = await plugin.get_burn_rate()
        assert is_degraded(br) is True and br["mock"] is True
        assert "monthly_spend" in br              # keeps the mock shape for callers
        assert "plugins.gecko_tx_csv_path" in br["_degraded"]["needs"]
        await plugin.close()

    async def test_missing_tx_file_degrades(self):
        plugin = BalanceReaderPlugin(tx_csv_path="/nonexistent/tx.csv")
        br = await plugin.get_burn_rate()
        assert is_degraded(br) is True
        await plugin.close()
