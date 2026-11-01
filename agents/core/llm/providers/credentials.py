"""Private Fernet vault for one exact, owner-managed signed provider credential.

This store never decides admission. Its caller derives a binding from a freshly
runnable signed record while holding the package lock; the vault takes only its
own credential lock. Selected physical sends are a later integration slice.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from agents.core import secrets as secret_module

from .packages import ProviderPackageError, ProviderRecord, _secure_root, fcntl

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ARTIFACT = re.compile(r"[0-9a-f]{32}\Z")
_IDENTITY = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}\Z")
_MAX_FILE = 32_768


@dataclass(frozen=True, slots=True)
class CredentialBinding:
    authority: str
    home: str
    provider: str
    source: str
    artifact_id: str
    package_hash: str
    endpoint: str
    auth_type: str

    def __post_init__(self):
        try:
            url = urlsplit(self.endpoint)
            valid = (url.scheme == "https" and bool(url.hostname)
                     and url.port != 0 and url.username is None and url.password is None
                     and not url.query and not url.fragment
                     and not any(ord(char) < 33 or ord(char) > 126 for char in self.endpoint))
        except (TypeError, ValueError):
            valid = False
        if (self.authority != "local-owner-v1" or type(self.home) is not str
                or not self.home or len(self.home) > 2048
                or type(self.provider) is not str or not _IDENTITY.fullmatch(self.provider)
                or self.source not in {"user", "legacy", "bundled"}
                or type(self.artifact_id) is not str or not _ARTIFACT.fullmatch(self.artifact_id)
                or type(self.package_hash) is not str or not _HASH.fullmatch(self.package_hash)
                or type(self.endpoint) is not str or len(self.endpoint) > 2048
                or not valid or self.auth_type not in {"bearer", "api-key", "none"}):
            raise ProviderPackageError("invalid host credential binding")


def credential_binding(record: ProviderRecord, home: str) -> CredentialBinding:
    """Derive scope only from the signed record and service-owned home."""
    if (type(record) is not ProviderRecord or type(home) is not str
            or record.profile.id != record.provider_id
            or record.source == "user" and record.home != home
            or record.source != "user" and record.home is not None
            or record.profile.auth_env or record.profile.env_vars
            or record.profile.base_url_env):
        raise ProviderPackageError("signed credential scope is unavailable")
    return CredentialBinding("local-owner-v1", home, record.provider_id, record.source,
                             record.artifact_id, record.package_hash,
                             str(record.profile.default_base_url or ""), record.profile.auth_type)


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _key(value):
    if (type(value) is not str or not 1 <= len(value) <= 4096
            or any(ord(char) < 33 or ord(char) > 126 for char in value)):
        raise ProviderPackageError("invalid host credential value")
    return value


class ProviderCredentialStore:
    """Private, generation-monotone ciphertext and durable delete tombstones."""

    def __init__(self, root: str | Path):
        # Two first writers may both see the private directory absent. The
        # package helper safely validates an existing directory, so retry only
        # its create-race and keep every other root refusal fail-closed.
        for attempt in range(3):
            try:
                self.root, self._identity = _secure_root(Path(root))
                break
            except ProviderPackageError as exc:
                if not isinstance(exc.__cause__, FileExistsError) or attempt == 2:
                    raise

    def path(self, binding: CredentialBinding) -> Path:
        if type(binding) is not CredentialBinding:
            raise ProviderPackageError("exact host credential binding required")
        return self.root / (hashlib.sha256(_json(asdict(binding))).hexdigest() + ".enc")

    def anchor_path(self, binding: CredentialBinding) -> Path:
        return self.path(binding).with_suffix(".hwm")

    @staticmethod
    def _safe_file(path: Path, *, maximum: int = _MAX_FILE):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_size > maximum):
            raise ProviderPackageError("unsafe host credential file")
        return True

    @contextmanager
    def _locked(self):
        if fcntl is None or not hasattr(fcntl, "flock"):
            raise ProviderPackageError("host credential locking unavailable")
        if _secure_root(self.root)[1] != self._identity:
            raise ProviderPackageError("host credential root changed")
        lock = self.root / "credentials.lock"
        self._safe_file(lock)
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
                raise ProviderPackageError("unsafe host credential lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            if _secure_root(self.root)[1] != self._identity:
                raise ProviderPackageError("host credential root changed")
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _cipher(self):
        if not secret_module._HAS_CRYPTOGRAPHY or secret_module.Fernet is None:
            raise ProviderPackageError("provider credential Fernet unavailable")
        for name in ("cipher.json", "cipher.json.key", "cipher.json.salt"):
            self._safe_file(self.root / name, maximum=4096)
        try:
            cipher = secret_module.SecretStore(self.root / "cipher.json")
        except Exception:
            raise ProviderPackageError("provider credential cipher unavailable") from None
        for name in ("cipher.json", "cipher.json.key", "cipher.json.salt"):
            self._safe_file(self.root / name, maximum=4096)
        # SecretStore's first-writer key/salt creation is atomic but does not
        # fsync. Sync the material and its directory entry before either the
        # high-water anchor or a credential envelope can be committed.
        for name in ("cipher.json.key", "cipher.json.salt"):
            path = self.root / name
            if self._safe_file(path, maximum=4096):
                before = path.lstat()
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    info = os.fstat(fd)
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077
                            or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)
                            or info.st_size > 4096):
                        raise ProviderPackageError("unsafe host credential cipher material")
                    os.fsync(fd)
                finally:
                    os.close(fd)
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return cipher

    def _read_anchor(self, binding, cipher):
        path = self.anchor_path(binding)
        if not self._safe_file(path):
            if self._safe_file(self.path(binding)):
                raise ProviderPackageError("host credential high-water anchor unavailable")
            return None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError
                raw = source.read(_MAX_FILE + 1)
            if len(raw) > _MAX_FILE or not raw or raw.startswith(b"xhmacb1:"):
                raise ValueError
            anchor = json.loads(cipher.decrypt_bytes(raw))
            if (type(anchor) is not dict
                    or set(anchor) != {"schema", "binding", "generation", "configured", "digest"}
                    or type(anchor["schema"]) is not int or anchor["schema"] != 1
                    or anchor["binding"] != asdict(binding)
                    or type(anchor["generation"]) is not int
                    or not 1 <= anchor["generation"] < 2**63 - 1
                    or type(anchor["configured"]) is not bool
                    or type(anchor["digest"]) is not str
                    or not _HASH.fullmatch(anchor["digest"])):
                raise ValueError
            return anchor
        except Exception:
            raise ProviderPackageError("host credential high-water anchor refused") from None

    def _read_envelope(self, binding, cipher):
        path = self.path(binding)
        if not self._safe_file(path):
            return None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError
                raw = source.read(_MAX_FILE + 1)
            if len(raw) > _MAX_FILE or not raw or raw.startswith(b"xhmacb1:"):
                raise ValueError
            envelope = json.loads(cipher.decrypt_bytes(raw))
            if (type(envelope) is not dict
                    or set(envelope) != {"schema", "binding", "generation", "configured", "value"}
                    or envelope["schema"] != 1 or type(envelope["schema"]) is not int
                    or envelope["binding"] != asdict(binding)
                    or type(envelope["generation"]) is not int
                    or not 1 <= envelope["generation"] < 2**63 - 1
                    or type(envelope["configured"]) is not bool
                    or (not envelope["configured"] and envelope["value"] is not None)):
                raise ValueError
            if envelope["configured"]:
                _key(envelope["value"])
            return envelope, hashlib.sha256(raw).hexdigest()
        except Exception:
            raise ProviderPackageError("host credential envelope refused") from None

    def _read(self, binding, cipher):
        anchor = self._read_anchor(binding, cipher)
        if anchor is None:
            return None
        opened = self._read_envelope(binding, cipher)
        if (opened is None or opened[0]["generation"] != anchor["generation"]
                or opened[0]["configured"] != anchor["configured"]
                or opened[1] != anchor["digest"]):
            raise ProviderPackageError("host credential envelope differs from high-water anchor")
        return opened[0]

    def _mutation_generation(self, binding, cipher):
        """Advance a valid anchor; never read an old or forged value as authority."""
        anchor = self._read_anchor(binding, cipher)
        if anchor is None:
            return 0
        try:
            opened = self._read_envelope(binding, cipher)
        except ProviderPackageError:
            opened = None  # Torn/corrupt envelope; only the anchor can advance.
        if opened is not None and opened[0]["generation"] > anchor["generation"]:
            raise ProviderPackageError("host credential high-water anchor moved backward")
        if anchor["generation"] >= 2**63 - 2:
            raise ProviderPackageError("host credential generation exhausted")
        return anchor["generation"]

    def _write_file(self, path, content):
        self._safe_file(path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as target:
                temporary = target.name
                os.fchmod(target.fileno(), 0o600)
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    def _write(self, binding, generation, value, cipher):
        envelope = {"schema": 1, "binding": asdict(binding), "generation": generation,
                    "configured": value is not None, "value": value}
        ciphertext = cipher.encrypt_bytes(_json(envelope))
        if len(ciphertext) > _MAX_FILE or ciphertext.startswith(b"xhmacb1:"):
            raise ProviderPackageError("provider credential cipher unavailable")
        anchor = {"schema": 1, "binding": asdict(binding), "generation": generation,
                  "configured": value is not None,
                  "digest": hashlib.sha256(ciphertext).hexdigest()}
        token = cipher.encrypt_bytes(_json(anchor))
        if len(token) > _MAX_FILE or token.startswith(b"xhmacb1:"):
            raise ProviderPackageError("provider credential cipher unavailable")
        # Anchor first: a crash can leave the previous envelope unavailable,
        # never make it readable at a generation that was already superseded.
        self._write_file(self.anchor_path(binding), token)
        self._write_file(self.path(binding), ciphertext)

    def status(self, binding):
        with self._locked():
            if binding.auth_type == "none":
                return {"configured": False, "generation": 0}
            current = self._read(binding, self._cipher())
            return {"configured": bool(current and current["configured"]),
                    "generation": current["generation"] if current else 0}

    def high_water(self, binding):
        """Mutation-only generation; a torn envelope cannot supply a secret."""
        with self._locked():
            if binding.auth_type == "none":
                raise ProviderPackageError("provider does not accept host credentials")
            return self._mutation_generation(binding, self._cipher())

    def read(self, binding, generation):
        with self._locked():
            if binding.auth_type == "none":
                raise ProviderPackageError("host credential changed or unavailable")
            current = self._read(binding, self._cipher())
            if (type(generation) is not int
                    or not current or not current["configured"]
                    or current["generation"] != generation):
                raise ProviderPackageError("host credential changed or unavailable")
            return current["value"]

    def put(self, binding, value):
        _key(value)
        with self._locked():
            if binding.auth_type == "none":
                raise ProviderPackageError("provider does not accept host credentials")
            cipher = self._cipher()
            generation = self._mutation_generation(binding, cipher) + 1
            self._write(binding, generation, value, cipher)
            return {"configured": True, "generation": generation}

    def delete(self, binding):
        with self._locked():
            if binding.auth_type == "none":
                raise ProviderPackageError("provider does not accept host credentials")
            cipher = self._cipher()
            generation = self._mutation_generation(binding, cipher) + 1
            self._write(binding, generation, None, cipher)
            return {"configured": False, "generation": generation}
