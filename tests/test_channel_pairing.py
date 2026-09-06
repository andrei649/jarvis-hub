"""Channel pairing: the deeplink routes, and the guards that make them safe.

`tests/test_telegram_deeplink_pairing.py` covers the token's own behaviour (one
use, short TTL, indistinguishable failures). This file covers the HTTP surface
around it, where the interesting property is *who may mint one*: the token is the
credential — whoever holds it pairs — so minting is admin-guarded and the value is
returned exactly once rather than being readable back later.

Revoking is narrowing, so it needs no approval; it is the button for "I pasted
that link in the wrong window".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents"))


# ── deeplink routes (the 60-second path) ─────────────────────────────────────

def test_minting_a_link_is_admin_guarded_and_returns_the_token_once():
    """The token IS the credential — whoever holds it pairs — so minting is
    admin-guarded and the value is returned exactly once, never stored back."""
    from tests.test_route_auth_matrix import _runtime_guards

    guards = _runtime_guards()
    assert guards["POST /api/channels/pairing/link"] == "admin"
    assert guards["POST /api/channels/pairing/link/revoke"] == "admin"


def test_the_link_route_builds_a_telegram_url_when_given_the_bot_username(tmp_path):
    import asyncio

    from agents.core.channels.pairing import SenderPairing
    from agents.core.routers import pairing as pairing_routes

    store = SenderPairing(tmp_path / "p.json")
    original = pairing_routes._get_sender_pairing
    pairing_routes._get_sender_pairing = lambda: store
    try:
        body = pairing_routes.PairingLinkBody(channel="telegram", bot_username="@nervabot")
        response = asyncio.run(pairing_routes.pairing_mint_link(body))
        payload = json.loads(response.body)
    finally:
        pairing_routes._get_sender_pairing = original

    assert payload["single_use"] is True
    assert payload["url"].startswith("https://t.me/nervabot?start=")
    assert payload["token"] in payload["url"]
    assert payload["ttl_seconds"] > 0
    # the token really is live in the store it was minted from
    assert store.redeem_deeplink(payload["token"], "telegram", "42")["ok"] is True


def test_the_link_route_omits_the_url_rather_than_guessing_a_bot_name(tmp_path):
    import asyncio

    from agents.core.channels.pairing import SenderPairing
    from agents.core.routers import pairing as pairing_routes

    store = SenderPairing(tmp_path / "p.json")
    original = pairing_routes._get_sender_pairing
    pairing_routes._get_sender_pairing = lambda: store
    try:
        body = pairing_routes.PairingLinkBody(channel="telegram")
        payload = json.loads(asyncio.run(pairing_routes.pairing_mint_link(body)).body)
    finally:
        pairing_routes._get_sender_pairing = original

    assert payload["url"] == ""       # no invented username
    assert payload["token"]           # but the token is still usable


def test_revoking_links_reports_how_many_it_killed(tmp_path):
    import asyncio

    from agents.core.channels.pairing import SenderPairing
    from agents.core.routers import pairing as pairing_routes

    store = SenderPairing(tmp_path / "p.json")
    store.mint_deeplink()
    store.mint_deeplink()
    original = pairing_routes._get_sender_pairing
    pairing_routes._get_sender_pairing = lambda: store
    try:
        payload = json.loads(asyncio.run(pairing_routes.pairing_revoke_links()).body)
    finally:
        pairing_routes._get_sender_pairing = original

    assert payload == {"ok": True, "revoked": 2}
    assert store.outstanding_deeplinks() == 0
