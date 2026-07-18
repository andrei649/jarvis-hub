"""
iot_control.py — Ultron Tuya SmartHome IoT controller.

Toggles real Tuya smart sockets via the Tuya Cloud OpenAPI. When no credentials
are configured it returns a clearly-labelled *degraded* result (it does not touch
any device). When credentials ARE configured it performs the real, documented
Tuya request-signing flow (token grant + signed command) — previously this path
sent a hardcoded ``sign="MOCK_SIGNATURE"`` that Tuya always rejects, so it could
never actuate even with valid credentials.

Signing follows Tuya Cloud OpenAPI v1.0:
  sign = HMAC-SHA256( client_id [+ access_token] + t + nonce + stringToSign, secret ).hexUpper
  stringToSign = HTTPMethod + "\\n" + SHA256(body) + "\\n" + signHeaders + "\\n" + urlPathWithQuery
"""
import hashlib
import hmac
import json
import logging
import time
import uuid

from ..http_client import PluginHTTPClient
from ..resilience import resilient_call
from .degradation import degraded

logger = logging.getLogger("jarvis.plugins.iot")

TUYA_HOST = "https://openapi.tuya.com"
# SHA-256 of the empty string — the body hash used for bodyless (GET) requests.
_EMPTY_BODY_SHA256 = hashlib.sha256(b"").hexdigest()
# Access tokens are valid ~2h; refresh a little early.
_TOKEN_TTL_SECONDS = 6000


def _sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _string_to_sign(method: str, path: str, body: str = "") -> str:
    """Tuya canonical string: METHOD\\n Content-SHA256\\n SignHeaders\\n URL.

    SignHeaders is empty (we sign no custom headers), leaving the documented blank
    line between the content hash and the URL.
    """
    content_hash = _EMPTY_BODY_SHA256 if body == "" else _sha256(body)
    return f"{method}\n{content_hash}\n\n{path}"


def tuya_sign(secret: str, client_id: str, t: str, nonce: str,
              string_to_sign: str, access_token: str = "") -> str:
    """HMAC-SHA256 signature, upper-hex — the exact Tuya Cloud OpenAPI algorithm.

    For a token grant, ``access_token`` is empty; for a business request it is the
    granted token, inserted right after ``client_id`` per the spec.
    """
    message = f"{client_id}{access_token}{t}{nonce}{string_to_sign}"
    return hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest().upper()


class IoTControlPlugin:
    def __init__(self, client_id: str = "", secret: str = "", device_id: str = ""):
        self.client_id = client_id.strip()
        self.secret = secret.strip()
        self.device_id = device_id.strip()
        self.client = PluginHTTPClient.for_plugin("iot-control")
        self._access_token = ""  # nosec B105 — empty cache init, not a credential
        self._token_expiry = 0.0

    def configured(self) -> bool:
        return bool(self.client_id and self.secret and self.device_id)

    async def _ensure_token(self) -> str:
        """Fetch (and cache) a Tuya access token via a signed token grant."""
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token
        t = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        path = "/v1.0/token?grant_type=1"
        string_to_sign = _string_to_sign("GET", path, "")
        sign = tuya_sign(self.secret, self.client_id, t, nonce, string_to_sign)
        headers = {
            "client_id": self.client_id,
            "sign": sign,
            "t": t,
            "nonce": nonce,
            "sign_method": "HMAC-SHA256",
        }
        resp = await self.client.get(f"{TUYA_HOST}{path}", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success", False):
            raise RuntimeError(f"Tuya token grant failed: {data.get('msg') or data}")
        self._access_token = data["result"]["access_token"]
        self._token_expiry = time.time() + _TOKEN_TTL_SECONDS
        return self._access_token

    @resilient_call(
        max_retries=2,
        timeout=10.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:iot",
        circuit_breaker_threshold=3,
        metrics_agent_id="ultron",
        metrics_backend="tuya.com",
    )
    async def toggle_switch(self, state: bool) -> dict:
        """Toggle a smart socket. Real Tuya command when configured, else degraded."""
        if not self.configured():
            logger.warning("Tuya client_id/secret/device_id missing — degraded (no device touched)")
            return degraded(
                {"status": "not_configured", "device": self.device_id,
                 "state": "ON" if state else "OFF"},
                reason="Tuya credentials not configured — no device was toggled",
                needs=["plugins.tuya_client_id", "plugins.tuya_secret", "plugins.tuya_device_id"],
            )

        access_token = await self._ensure_token()

        t = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        path = f"/v1.0/devices/{self.device_id}/commands"
        # Body must be byte-identical to what we hash, so serialise once and send
        # the exact string (compact separators) via `content=`.
        body = json.dumps({"commands": [{"code": "switch_1", "value": state}]},
                          separators=(",", ":"))
        string_to_sign = _string_to_sign("POST", path, body)
        sign = tuya_sign(self.secret, self.client_id, t, nonce, string_to_sign,
                         access_token=access_token)
        headers = {
            "client_id": self.client_id,
            "access_token": access_token,
            "sign": sign,
            "t": t,
            "nonce": nonce,
            "sign_method": "HMAC-SHA256",
            "Content-Type": "application/json",
        }
        resp = await self.client.post(f"{TUYA_HOST}{path}", headers=headers, content=body)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success", False):
            raise RuntimeError(f"Tuya command failed: {data.get('msg') or data}")
        return {"status": "toggled", "device": self.device_id,
                "state": "ON" if state else "OFF"}

    async def close(self):
        await self.client.close()
