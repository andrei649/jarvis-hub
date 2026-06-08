"""Cross-language pinning + behavior tests for the WorldView MCP capability minter (H19.3.2).

`agents/core/security/worldview_mcp.py` mints the HMAC capability token the standalone WorldView
MCP server (`worldview/mcp/src/auth.ts`) gates its WRITE tools (`watch_aoi`, `reconstruct_event`)
on. The two implementations live in different languages and runtimes, so they're pinned to a
SHARED fixture (`worldview/mcp/test/fixtures/capability-vectors.json`): minting the fixture's
claims must reproduce its frozen `token` byte-for-byte, and our verifier must accept it. The TS
suite (`worldview/mcp/test/capabilityVectors.test.ts`) asserts the same fixture from the other
side, so neither token format can silently drift without one side's CI going red.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.core.security.worldview_mcp import mint_capability, verify_capability

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "worldview"
    / "mcp"
    / "test"
    / "fixtures"
    / "capability-vectors.json"
)


def _load_fixture() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


_FIXTURE = _load_fixture()
_SECRET = _FIXTURE["secret"]
_VECTORS = _FIXTURE["vectors"]
_IDS = [v["name"] for v in _VECTORS]


@pytest.mark.parametrize("vec", _VECTORS, ids=_IDS)
def test_mint_reproduces_frozen_token(vec: dict) -> None:
    """Minting the vector's claims must reproduce the exact cross-language token.

    We pin issuance time so ``exp = issued + ttl`` lands on the vector's frozen ``exp``: with
    ``ttl_s=0`` and ``now=exp`` the minter emits the same claims dict (same key order, compact JSON,
    base64url-no-pad, HMAC over the payload string) the TS ``signCapability`` produced.
    """
    token = mint_capability(
        vec["claims"]["scopes"],
        _SECRET,
        ttl_s=0,
        sub=vec["claims"].get("sub"),
        now=vec["claims"]["exp"],
    )
    assert token == vec["token"], "Python-minted token diverged from the shared cross-language vector"


@pytest.mark.parametrize("vec", _VECTORS, ids=_IDS)
def test_verify_grants_then_denies(vec: dict) -> None:
    """Our verifier accepts the frozen token for every granted scope and denies the rest."""
    unexpired = vec["claims"]["exp"] - 1
    for scope in vec["grants"]:
        res = verify_capability(vec["token"], scope, _SECRET, now=unexpired)
        assert res.ok, f"expected scope {scope!r} granted, got {res.reason!r}"
        assert res.claims is not None
        assert res.claims["scopes"] == vec["claims"]["scopes"]
        assert res.claims["exp"] == vec["claims"]["exp"]
    for scope in vec["denies"]:
        res = verify_capability(vec["token"], scope, _SECRET, now=unexpired)
        assert not res.ok
        assert res.reason == "missing-scope"


@pytest.mark.parametrize("vec", _VECTORS, ids=_IDS)
def test_verify_rejects_expired_and_bad_secret(vec: dict) -> None:
    """Fail-closed: an expired token and a wrong secret both deny (no exception)."""
    expired = verify_capability(vec["token"], vec["grants"][0], _SECRET, now=vec["claims"]["exp"])
    assert not expired.ok and expired.reason == "expired"

    wrong = verify_capability(vec["token"], vec["grants"][0], "not-the-shared-secret", now=vec["claims"]["exp"] - 1)
    assert not wrong.ok and wrong.reason == "bad-signature"


def test_mint_then_verify_roundtrip() -> None:
    """A freshly-minted token verifies for its scope and is denied for an un-granted one."""
    token = mint_capability(["worldview:watch"], _SECRET, ttl_s=300, sub="argus", now=1_000_000)
    granted = verify_capability(token, "worldview:watch", _SECRET, now=1_000_100)
    assert granted.ok and granted.claims is not None and granted.claims["sub"] == "argus"

    denied = verify_capability(token, "worldview:reconstruct", _SECRET, now=1_000_100)
    assert not denied.ok and denied.reason == "missing-scope"


def test_wildcard_scope_grants_everything() -> None:
    """A ``worldview:*`` token authorizes any worldview scope."""
    token = mint_capability(["worldview:*"], _SECRET, ttl_s=300, now=1_000_000)
    for scope in ("worldview:watch", "worldview:reconstruct", "worldview:anything"):
        assert verify_capability(token, scope, _SECRET, now=1_000_100).ok


def test_fail_closed_on_empty_secret_and_malformed_token() -> None:
    """No-secret, missing, and malformed tokens all deny rather than raising."""
    assert not verify_capability("a.b", "worldview:watch", "", now=0).ok
    assert verify_capability("a.b", "worldview:watch", "", now=0).reason == "no-secret-configured"
    assert not verify_capability(None, "worldview:watch", _SECRET, now=0).ok
    assert not verify_capability("only-one-segment", "worldview:watch", _SECRET, now=0).ok
    assert not verify_capability("tampered.payload", "worldview:watch", _SECRET, now=0).ok

    with pytest.raises(ValueError):
        mint_capability(["worldview:watch"], "", ttl_s=300)


def test_exp_is_always_integral_even_from_a_float_now() -> None:
    """``exp`` must render as an integer (``1900000000``), never a float (``1900000000.0``).

    TS ``JSON.stringify(1900000000.0)`` yields ``1900000000``; an un-coerced Python float would
    yield ``1900000000.0`` and diverge. A fractional ``now`` must not leak a float ``exp`` into the
    payload — the minter floors to an int. We decode the payload segment and assert the raw JSON
    carries an int (the cross-language byte-identity in the fixtures already pins the integer case).
    """
    import base64
    import json as _json

    token = mint_capability(["worldview:watch"], _SECRET, ttl_s=0, now=1_900_000_000.75)
    payload_seg = token.split(".")[0]
    raw = base64.urlsafe_b64decode(payload_seg + "=" * (-len(payload_seg) % 4))
    claims = _json.loads(raw)
    assert claims["exp"] == 1_900_000_000
    assert isinstance(claims["exp"], int)
    assert ".0" not in raw.decode("utf-8"), "exp leaked a float representation into the payload"
