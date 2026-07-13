"""Explicitly provisioned, encrypted-at-rest acquisition signing keys."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError


class SigningError(RuntimeError):
    pass


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ManagedSignature:
    algorithm: str
    key_id: str
    key_version: int
    manifest_hash: str
    signature: str


class ManagedSigningKeyStore:
    def __init__(self, root: str | Path | None = None, *, max_versions: int = 8) -> None:
        self.root = Path(root) if root is not None else data_path("acquisition", "signing")
        if self.root.is_symlink():
            raise SigningError("signing root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self.path = self.root / "keys.enc"
        self._cipher = SecretStore(self.root / "key-cipher.json")
        self._max_versions = max(2, min(32, int(max_versions)))
        self._lock = threading.RLock()
        self._state: dict | None = None

    def provision(self, *, key_id: str, version: int, key: bytes) -> None:
        token = self._validate_key_id(key_id)
        number = self._validate_version(version)
        material = self._validate_key(key)
        with self._lock:
            state = self._load()
            existing = next(
                (
                    row
                    for row in state["keys"]
                    if row["key_id"] == token and row["version"] == number
                ),
                None,
            )
            encoded = base64.b64encode(material).decode("ascii")
            if existing is not None and not hmac.compare_digest(existing["key"], encoded):
                raise SigningError("signing key version already exists with different material")
            keys = list(state["keys"])
            if existing is None:
                keys.append({"key_id": token, "version": number, "key": encoded})
            keys = sorted(keys, key=lambda row: row["version"], reverse=True)[: self._max_versions]
            self._commit({"schema": 1, "active": [token, number], "keys": keys})

    def rotate(self, *, key_id: str, version: int, key: bytes) -> None:
        state = self._load()
        active = state.get("active")
        if active and int(version) <= int(active[1]):
            raise SigningError("signing key rotation version must increase")
        self.provision(key_id=key_id, version=version, key=key)

    def active_identity(self) -> tuple[str, int]:
        state = self._load()
        active = state.get("active")
        if not isinstance(active, list) or len(active) != 2:
            raise SigningError("managed signing key is not provisioned")
        return str(active[0]), int(active[1])

    def sign(self, manifest: dict) -> ManagedSignature:
        if not isinstance(manifest, dict):
            raise SigningError("canonical manifest required")
        key_id, version = self.active_identity()
        key = self._key(key_id, version)
        raw = _canonical(manifest)
        digest = hashlib.sha256(raw).hexdigest()
        tag = hmac.new(key, raw, hashlib.sha256).hexdigest()
        return ManagedSignature("hmac-sha256", key_id, version, digest, tag)

    def verify(self, manifest: dict, signature: ManagedSignature | dict) -> bool:
        try:
            value = (
                signature
                if isinstance(signature, ManagedSignature)
                else ManagedSignature(**dict(signature))
            )
            if value.algorithm != "hmac-sha256":
                return False
            raw = _canonical(manifest)
            if value.manifest_hash != hashlib.sha256(raw).hexdigest():
                return False
            key = self._key(value.key_id, value.key_version)
            expected = hmac.new(key, raw, hashlib.sha256).hexdigest()
            return hmac.compare_digest(value.signature, expected)
        except (SigningError, TypeError, ValueError, KeyError):
            return False

    def _key(self, key_id: str, version: int) -> bytes:
        state = self._load()
        row = next(
            (
                item
                for item in state["keys"]
                if item["key_id"] == key_id and int(item["version"]) == int(version)
            ),
            None,
        )
        if row is None:
            raise SigningError("managed signing key version unavailable")
        try:
            return base64.b64decode(row["key"], validate=True)
        except (ValueError, TypeError) as exc:
            raise SigningError("managed signing key is corrupted") from exc

    def _load(self) -> dict:
        with self._lock:
            if self._state is not None:
                return self._state
            if not self.path.exists():
                self._state = {"schema": 1, "active": None, "keys": []}
                return self._state
            if self.path.is_symlink():
                raise SigningError("signing key store cannot be a symlink")
            try:
                state = json.loads(self._cipher.decrypt_bytes(self.path.read_bytes()).decode("utf-8"))
                if state.get("schema") != 1 or not isinstance(state.get("keys"), list):
                    raise ValueError("invalid signing key schema")
                if len(state["keys"]) > self._max_versions:
                    raise ValueError("signing key store exceeds capacity")
                for row in state["keys"]:
                    self._validate_key_id(row["key_id"])
                    self._validate_version(row["version"])
                    self._validate_key(base64.b64decode(row["key"], validate=True))
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                SecretStoreError,
                ValueError,
                TypeError,
                KeyError,
            ) as exc:
                raise SigningError("cannot decrypt or validate managed signing keys") from exc
            self._state = state
            return state

    def _commit(self, state: dict) -> None:
        raw = _canonical(state)
        token = self._cipher.encrypt_bytes(raw)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".keys-", delete=False) as handle:
                temporary = handle.name
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise SigningError("cannot atomically commit managed signing keys") from exc
        finally:
            if temporary:
                with suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)
        self._state = state

    @staticmethod
    def _validate_key_id(value: str) -> str:
        token = str(value or "").strip()
        if not token or len(token) > 64 or any(not (char.isalnum() or char in "._-") for char in token):
            raise SigningError("managed signing key id is invalid")
        return token

    @staticmethod
    def _validate_version(value: int) -> int:
        if type(value) is not int or value <= 0 or value > 1_000_000:
            raise SigningError("managed signing key version is invalid")
        return value

    @staticmethod
    def _validate_key(value: bytes) -> bytes:
        if not isinstance(value, bytes) or len(value) < 32 or len(value) > 128:
            raise SigningError("managed signing key must be 32-128 bytes")
        return bytes(value)


__all__ = ["ManagedSignature", "ManagedSigningKeyStore", "SigningError"]
