"""H127 — Matrix end-to-end encryption: trust layer, no plaintext downgrade, proxy mode.

The Olm/Megolm ratchets themselves are not built (no backend is pinned); these tests pin
what is: encrypted rooms are detected and never get plaintext unless the owner says so,
encrypted inbound is counted instead of dropped, device keys are checked against their
Ed25519 self-signatures and through cross-signing, and the owner's trust decisions live
in an encrypted store under the data dir.
"""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402

from agents.core.channels import matrix_e2ee as e2ee  # noqa: E402
from agents.core.channels.webhook_channels import MatrixChannel  # noqa: E402
from agents.core.secrets import SecretStore  # noqa: E402

USER = "@alice:hs.example"
ROOM = "!room:hs.example"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode().rstrip("=")


def _pub(key: Ed25519PrivateKey) -> str:
    return _b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def _sign(obj: dict, key: Ed25519PrivateKey, user: str, key_id: str) -> dict:
    sig = _b64(key.sign(e2ee.canonical_json(e2ee._signable(obj))))
    obj.setdefault("signatures", {}).setdefault(user, {})[key_id] = sig
    return obj


def _device(device_id="DEV1", key=None, user=USER):
    key = key or Ed25519PrivateKey.generate()
    obj = {"user_id": user, "device_id": device_id,
           "algorithms": ["m.olm.v1.curve25519-aes-sha2", "m.megolm.v1.aes-sha2"],
           "keys": {f"ed25519:{device_id}": _pub(key), f"curve25519:{device_id}": _b64(b"c" * 32)}}
    return _sign(obj, key, user, f"ed25519:{device_id}"), key


@pytest.fixture(autouse=True)
def _reset():
    e2ee.reset_for_tests()
    yield
    e2ee.reset_for_tests()


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Transport:
    def __init__(self, state_status=404, state_body=None, fail=False):
        self.calls = []
        self.state_status = state_status
        self.state_body = state_body
        self.fail = fail

    async def request(self, method, url, headers=None, json=None):
        self.calls.append((method, url, json))
        if "/state/m.room.encryption" in url:
            if self.fail:
                raise OSError("down")
            return _Resp(self.state_status, self.state_body)
        return _Resp(200, {"event_id": "$e"})


def _channel(transport, **extra):
    config = {"homeserver": "https://hs.example", "token": "T", "default_room": ROOM, **extra}
    return MatrixChannel(config=config, transport=transport)


def _sent(transport):
    return [c for c in transport.calls if c[0] == "POST"]


# ── no plaintext downgrade ───────────────────────────────────────────────────

def test_unencrypted_room_sends_as_before():
    t = _Transport(404)
    assert asyncio.run(_channel(t).send("hello")) is True
    assert _sent(t) and _sent(t)[0][2]["body"] == "hello"


def test_encrypted_room_is_refused_while_nerva_cannot_encrypt():
    t = _Transport(200, {"algorithm": "m.megolm.v1.aes-sha2"})
    assert asyncio.run(_channel(t).send("secret plans")) is False
    assert _sent(t) == []
    assert e2ee.can_encrypt() is False


def test_unknown_encryption_state_fails_closed():
    for t in (_Transport(500), _Transport(fail=True)):
        assert asyncio.run(_channel(t).send("x")) is False
        assert _sent(t) == []
    # Even the owner's plaintext opt-in does not cover a room whose state is unknown.
    t = _Transport(503)
    assert asyncio.run(_channel(t, encrypted_rooms="allow_plaintext").send("x")) is False


def test_owner_may_allow_plaintext_into_encrypted_rooms():
    t = _Transport(200, {"algorithm": "m.megolm.v1.aes-sha2"})
    assert asyncio.run(_channel(t, encrypted_rooms="allow_plaintext").send("ok")) is True
    assert len(_sent(t)) == 1


def test_proxy_mode_only_for_a_loopback_homeserver():
    enc = _Transport(200, {"algorithm": "m.megolm.v1.aes-sha2"})
    local = MatrixChannel(config={"homeserver": "http://127.0.0.1:8009", "token": "T",
                                  "default_room": ROOM, "encrypted_rooms": "proxy"}, transport=enc)
    assert asyncio.run(local.send("via pantalaimon")) is True
    remote = _Transport(200, {"algorithm": "m.megolm.v1.aes-sha2"})
    assert asyncio.run(_channel(remote, encrypted_rooms="proxy").send("x")) is False
    assert _sent(remote) == []


def test_encrypted_state_is_cached_and_never_expires():
    t = _Transport(200, {"algorithm": "m.megolm.v1.aes-sha2"})
    state = asyncio.run(e2ee.room_encryption(t, "https://hs", "T", ROOM, now=0))
    t.state_status = 404
    again = asyncio.run(e2ee.room_encryption(t, "https://hs", "T", ROOM, now=10**9))
    assert state.encrypted and again.encrypted
    assert sum("/state/" in c[1] for c in t.calls) == 1


def test_bad_room_id_is_never_sent():
    t = _Transport(404)
    assert asyncio.run(_channel(t).send("x", room_id="not-a-room")) is False
    assert t.calls == []


def test_unverified_devices_refused_once_encryption_exists(monkeypatch):
    monkeypatch.setattr(e2ee, "can_encrypt", lambda: True)
    state = e2ee.RoomEncryption(True, "m.megolm.v1.aes-sha2")
    refused = e2ee.send_decision(state, {}, devices_verified=False)
    assert not refused.allowed and refused.reason == "unverified_devices"
    allowed = e2ee.send_decision(state, {"allow_unverified_devices": True}, devices_verified=False)
    assert allowed.allowed and allowed.encrypt
    assert e2ee.send_decision(state, {}, devices_verified=True).encrypt


# ── encrypted inbound is visible, never answered ─────────────────────────────

def test_encrypted_inbound_is_counted_not_answered():
    seen = []

    async def handler(text, **kw):
        seen.append(text)
        return "reply"

    ch = MatrixChannel(handler=handler, config={"default_room": ROOM})
    payload = {"events": [{"type": "m.room.encrypted", "sender": USER, "room_id": ROOM,
                           "content": {"algorithm": "m.megolm.v1.aes-sha2", "ciphertext": "AwgA"}}]}
    assert asyncio.run(ch.handle_inbound(payload)) is None
    assert asyncio.run(ch.handle_inbound(payload)) is None
    assert seen == [] and e2ee.status()["undecryptable"] == {ROOM: 2}


# ── device keys, signatures and cross-signing ────────────────────────────────

def test_device_keys_self_signature_is_checked():
    device, key = _device()
    assert e2ee.verify_device_keys(device, USER, "DEV1") == _pub(key)
    # Wrong user/device id, a tampered field, a forged signature: all refused.
    assert e2ee.verify_device_keys(device, "@mallory:hs.example", "DEV1") is None
    assert e2ee.verify_device_keys(device, USER, "DEV2") is None
    tampered = {**device, "algorithms": ["m.olm.v1.curve25519-aes-sha2"]}
    assert e2ee.verify_device_keys(tampered, USER, "DEV1") is None
    other, _ = _device(key=Ed25519PrivateKey.generate())
    forged = {**device, "signatures": other["signatures"]}
    assert e2ee.verify_device_keys(forged, USER, "DEV1") is None
    # The unsigned section is not covered by the signature (spec).
    assert e2ee.verify_device_keys({**device, "unsigned": {"device_display_name": "x"}}, USER, "DEV1")


def _cross_signing(user=USER):
    master_key, ssk_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    master = {"user_id": user, "usage": ["master"], "keys": {f"ed25519:{_pub(master_key)}": _pub(master_key)}}
    ssk = {"user_id": user, "usage": ["self_signing"], "keys": {f"ed25519:{_pub(ssk_key)}": _pub(ssk_key)}}
    _sign(ssk, master_key, user, f"ed25519:{_pub(master_key)}")
    return master, ssk, master_key, ssk_key


def test_cross_signed_device_needs_the_owner_verified_master():
    master, ssk, master_key, ssk_key = _cross_signing()
    device, _ = _device()
    _sign(device, ssk_key, USER, f"ed25519:{_pub(ssk_key)}")
    assert e2ee.verify_cross_signed(device, USER, "DEV1", master, ssk, _pub(master_key))
    # Another master (not the one the owner verified) proves nothing.
    assert not e2ee.verify_cross_signed(device, USER, "DEV1", master, ssk,
                                        _pub(Ed25519PrivateKey.generate()))
    # A self-signing key the master did not sign proves nothing.
    rogue = {**ssk, "signatures": {}}
    assert not e2ee.verify_cross_signed(device, USER, "DEV1", master, rogue, _pub(master_key))
    # A device the self-signing key did not sign proves nothing.
    plain, _ = _device("DEV2")
    assert not e2ee.verify_cross_signed(plain, USER, "DEV2", master, ssk, _pub(master_key))


def test_trust_store_is_encrypted_under_the_data_dir_and_tracks_key_changes(tmp_path):
    path = tmp_path / "matrix" / "crypto_store.enc"
    path.parent.mkdir()
    store = e2ee.DeviceTrustStore(store=SecretStore(path))
    device, key = _device()
    out = store.verify_device(USER, "DEV1", e2ee.fingerprint(_pub(key)))
    assert out["fingerprint"] == e2ee.fingerprint(_pub(key))
    assert store.device_state(USER, "DEV1", _pub(key)) == "verified"
    assert store.device_state(USER, "DEV1", _pub(Ed25519PrivateKey.generate())) == "changed"
    assert store.device_state(USER, "DEV9", "x") == "unverified"
    assert _pub(key).encode() not in path.read_bytes()         # encrypted at rest
    # A fresh store on the same file sees the decision (persistent).
    again = e2ee.DeviceTrustStore(store=SecretStore(path))
    assert again.device_state(USER, "DEV1", _pub(key)) == "verified"
    assert again.revoke(USER, "DEV1") and again.device_state(USER, "DEV1", _pub(key)) == "unverified"


def test_trust_store_cross_signing_path(tmp_path):
    store = e2ee.DeviceTrustStore(store=SecretStore(tmp_path / "c.enc"))
    master, ssk, master_key, ssk_key = _cross_signing()
    device, dkey = _device()
    _sign(device, ssk_key, USER, f"ed25519:{_pub(ssk_key)}")
    kw = {"master": master, "self_signing": ssk, "device": device}
    assert store.device_state(USER, "DEV1", _pub(dkey), **kw) == "unverified"
    store.verify_master(USER, _pub(master_key))
    assert store.device_state(USER, "DEV1", _pub(dkey), **kw) == "cross_signed"
    assert [m["user_id"] for m in store.listing()["masters"]] == [USER]


def test_trust_store_refuses_malformed_input(tmp_path):
    store = e2ee.DeviceTrustStore(store=SecretStore(tmp_path / "c.enc"))
    key = _pub(Ed25519PrivateKey.generate())
    for args in (("alice", "DEV1", key), (USER, "bad device id", key), (USER, "DEV1", "short")):
        with pytest.raises(ValueError):
            store.verify_device(*args)


def test_status_reports_no_backend_and_the_cli_works(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    status = e2ee.status({"encrypted_rooms": "proxy"})
    assert status["can_encrypt"] is False and status["encrypted_rooms"] == "proxy"
    key = _pub(Ed25519PrivateKey.generate())
    assert e2ee.main(["verify", USER, "DEV1", key]) == 0
    assert e2ee.main(["devices"]) == 0
    assert "DEV1" in capsys.readouterr().out
    assert e2ee.main(["verify", "nobody", "DEV1", key]) == 2
