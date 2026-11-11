"""SMS channel webhook (H098, G16) — Twilio calls this; it authenticates by signature.

``POST /api/channels/sms/webhook`` carries no hub token (Twilio cannot present one). Its
credential is Twilio's ``X-Twilio-Signature`` over the full URL and the sorted POST
parameters, checked in the handler with the account's auth token (``channels/sms.py``).
The route answers 404 while SMS is off or not configured, 413 over 65,536 bytes, 403 for
a missing or wrong signature or another account, and otherwise empty TwiML at once — the
turn runs in the background and any reply waits for the owner's approval.
"""

from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter(tags=["channels"])

_FORM = "application/x-www-form-urlencoded"


def _twiml() -> Response:
    from agents.core.channels.sms import EMPTY_TWIML

    return Response(content=EMPTY_TWIML, media_type="application/xml",
                    headers={"Cache-Control": "no-store"})


async def _bounded_body(request: Request, limit: int) -> bytes | None:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                return None
        except ValueError:
            return None
    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > limit:
            return None
    return bytes(body)


@router.post("/api/channels/sms/webhook")
async def sms_webhook(request: Request):
    """Inbound SMS from Twilio: signature, account, replay and sender checks, then the turn."""
    from agents.core.app_state import get_orch
    from agents.core.channels import sms
    from agents.core.env_config import env_str

    orch = get_orch()
    channel = (getattr(orch, "channels", None) or {}).get(sms.CHANNEL_ID) if orch is not None else None
    if channel is None or not sms.configured():
        return JSONResponse({"error": "not found"}, status_code=404)
    body = await _bounded_body(request, sms.MAX_BODY_BYTES)
    if body is None:
        return JSONResponse({"error": "body too large"}, status_code=413)
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != _FORM:
        return JSONResponse({"error": "unsigned request"}, status_code=403)
    try:
        params = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=False,
                          max_num_fields=128)
    except (UnicodeDecodeError, ValueError):
        return JSONResponse({"error": "unsigned request"}, status_code=403)
    url = env_str(sms.WEBHOOK_URL_ENV).strip() or str(request.url)
    if not sms.valid_signature(sms.auth_token(), url, params,
                               request.headers.get("x-twilio-signature")):
        return JSONResponse({"error": "invalid signature"}, status_code=403)
    if (params.get("AccountSid") or [""])[0] != sms.account_sid():
        return JSONResponse({"error": "invalid signature"}, status_code=403)
    channel.accept_in_background(params)
    return _twiml()
