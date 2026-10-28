"""Signed, inert model-provider package quarantine and owner admission.

The store captures an exact directory snapshot. It never imports or executes
candidate code. Execution uses only freshly decrypted, signature-checked bytes
returned by :meth:`require_runnable` after a live kernel decision.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import asdict, dataclass, fields
from pathlib import Path

try:  # Windows must still import the inert provider catalog and kernel action metadata.
    import fcntl
except ImportError:  # pragma: no cover - exercised by the import-hook portability test
    fcntl = None

from agents.core.acquisition.managed_signing import (
    ManagedSignature,
    ManagedSigningKeyStore,
    SigningError,
)
from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile
from agents.core.kernel import Action, Decision, Verdict, kernel_enabled
from agents.core.secrets import SecretStore, SecretStoreError

from . import BUILTIN_PROFILES, ProviderProfile
from .admission_contract import PROVIDER_LOAD_CONTRACT, provider_sandbox_profile
from .candidates import MAX_MANIFEST_BYTES, _manifest_fields, _open_directory

KIND = "plugin.load"
MAX_DEPTH = 8
MAX_FILES = 256
MAX_FILE_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_PROFILE_BYTES = 32 * 1024
MAX_REGISTRY_BYTES = 32 * 1024 * 1024
MAX_ARTIFACTS = 64
MAX_PROPOSALS = 128
_HOOK = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_SOURCES = frozenset({"user", "legacy", "bundled"})
_RANK = {"bundled": 1, "legacy": 2, "user": 3}
_BUILTIN_BY_ID = {profile.id: profile for profile in BUILTIN_PROFILES}
_BUILTIN_IDENTITIES = frozenset(
    identity for profile in BUILTIN_PROFILES for identity in (profile.id, *profile.aliases)
)
_DISPATCH_GUARD = threading.Lock()
_DISPATCH_TASKS: dict[tuple[int, int], dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Task]]]] = {}


class ProviderPackageError(RuntimeError):
    """Provider bytes or admission authority cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    artifact_id: str
    provider_id: str
    package_hash: str
    manifest: dict
    signature: ManagedSignature
    profile: ProviderProfile
    hooks: tuple[str, ...]
    members: tuple[tuple[str, bytes], ...]
    source: str
    home: str | None
    replacement_target: str | None


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, (frozenset, set)):
        return sorted((_plain(item) for item in value), key=_canonical)
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _plain(item) for key, item in value.items()}
    if type(value) in (str, int, float, bool) or value is None:
        return value
    raise ProviderPackageError("profile contains an unsupported value")


def _profile_payload(profile: ProviderProfile) -> dict:
    return {item.name: _plain(getattr(profile, item.name)) for item in fields(ProviderProfile)}


def _fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _snapshot(directory: Path) -> tuple[tuple[tuple[str, bytes], ...], tuple[str, ...]]:
    """Walk through directory descriptors; reject special files before opening them."""
    try:
        root_fd = _open_directory(directory)
    except (OSError, ValueError) as exc:
        raise ProviderPackageError("candidate directory is not a secure real directory") from exc
    files: list[tuple[str, bytes]] = []
    directories: list[str] = []
    total = 0
    entries = 0

    def walk(fd: int, prefix: str, depth: int) -> None:
        nonlocal total, entries
        if depth > MAX_DEPTH:
            raise ProviderPackageError("provider package exceeds directory depth")
        before = _fingerprint(os.fstat(fd))
        with os.scandir(fd) as scanner:
            names = sorted(entry.name for entry in scanner)
        entries += len(names)
        if entries > MAX_FILES * 2:
            raise ProviderPackageError("provider package exceeds entry count")
        for name in names:
            if (not name or name in {".", ".."} or "/" in name or "\\" in name
                    or "\x00" in name or len(name.encode("utf-8")) > 255):
                raise ProviderPackageError("invalid provider package member path")
            relative = f"{prefix}{name}"
            if len(relative.encode("utf-8")) > 1024:
                raise ProviderPackageError("provider package member path exceeds limit")
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                directories.append(relative)
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=fd)
                try:
                    walk(child, relative + "/", depth + 1)
                finally:
                    os.close(child)
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ProviderPackageError("provider package contains a link or special file")
            if info.st_size > MAX_FILE_BYTES or total + info.st_size > MAX_PACKAGE_BYTES:
                raise ProviderPackageError("provider package exceeds byte limit")
            if len(files) >= MAX_FILES:
                raise ProviderPackageError("provider package exceeds file count")
            child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=fd)
            try:
                first = os.fstat(child)
                if not stat.S_ISREG(first.st_mode) or first.st_nlink != 1:
                    raise ProviderPackageError("provider package member changed type")
                chunks = []
                remaining = min(MAX_FILE_BYTES, MAX_PACKAGE_BYTES - total) + 1
                while remaining:
                    chunk = os.read(child, min(remaining, 64 * 1024))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                raw = b"".join(chunks)
                if len(raw) > MAX_FILE_BYTES or total + len(raw) > MAX_PACKAGE_BYTES:
                    raise ProviderPackageError("provider package exceeds byte limit")
                if _fingerprint(first) != _fingerprint(os.fstat(child)) or len(raw) != first.st_size:
                    raise ProviderPackageError("provider package member changed during snapshot")
                files.append((relative, raw))
                total += len(raw)
            finally:
                os.close(child)
        with os.scandir(fd) as scanner:
            after_names = sorted(entry.name for entry in scanner)
        if names != after_names or before != _fingerprint(os.fstat(fd)):
            raise ProviderPackageError("provider package directory changed during snapshot")

    try:
        walk(root_fd, "", 0)
    except (OSError, UnicodeError) as exc:
        raise ProviderPackageError("provider package cannot be read safely") from exc
    finally:
        os.close(root_fd)
    return tuple(sorted(files)), tuple(sorted(directories))


def _secure_root(path: Path) -> tuple[Path, tuple[int, int]]:
    """Open every ancestor without links; make only an owned final root private.

    Another process with the same filesystem owner's rights remains outside this
    boundary. A sticky root/user-owned temporary ancestor is allowed.
    """
    if not path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
        raise ProviderPackageError("provider store root must be an absolute child path")
    if (fcntl is None or not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW")
            or not callable(getattr(os, "getuid", None))):
        raise ProviderPackageError("secure provider store root is unavailable")
    uid = os.getuid()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def safe_ancestor(info: os.stat_result) -> bool:
        mode = stat.S_IMODE(info.st_mode)
        return (stat.S_ISDIR(info.st_mode)
                and (not mode & 0o022 or mode & stat.S_ISVTX and info.st_uid in (0, uid)))

    try:
        current_fd = os.open(path.anchor, flags)
        try:
            if not safe_ancestor(os.fstat(current_fd)):
                raise ProviderPackageError("provider store has an unsafe ancestor")
            for index, part in enumerate(path.parts[1:]):
                final = index == len(path.parts) - 2
                try:
                    child_fd = os.open(part, flags, dir_fd=current_fd)
                except FileNotFoundError:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                    child_fd = os.open(part, flags, dir_fd=current_fd)
                info = os.fstat(child_fd)
                mode = stat.S_IMODE(info.st_mode)
                if (not stat.S_ISDIR(info.st_mode)
                        or final and (info.st_uid != uid or mode & 0o022)
                        or not final and not safe_ancestor(info)):
                    os.close(child_fd)
                    raise ProviderPackageError("provider store root or ancestor is unsafe")
                if final:
                    os.fchmod(child_fd, 0o700)
                    identity = (info.st_dev, info.st_ino)
                os.close(current_fd)
                current_fd = child_fd
        finally:
            os.close(current_fd)
    except ProviderPackageError:
        raise
    except OSError as exc:
        raise ProviderPackageError("provider store root cannot be opened safely") from exc
    return path, identity


class ProviderPackageStore:
    def __init__(
        self, root: str | Path, *, signing: ManagedSigningKeyStore,
        authorizer: Callable[[Action], Decision] | None = None,
        enabled: Callable[[], bool] = lambda: False,
        owner_authorizer: Callable[[str, ProviderRecord, str], bool] | None = None,
    ) -> None:
        self.root, self._root_identity = _secure_root(Path(root))
        if not isinstance(signing, ManagedSigningKeyStore):
            raise ProviderPackageError("managed signing store required")
        self.signing = signing
        self.authorizer = authorizer
        self.enabled = enabled
        self.owner_authorizer = owner_authorizer
        self.path = self.root / "registry.enc"
        self._journal_path = self.root / "revocations.enc"
        self._cipher = SecretStore(self.root / "registry-cipher.json")
        self._lock_path = self.root / "registry.lock"

    @contextmanager
    def _locked(self):
        if fcntl is None or not hasattr(fcntl, "flock"):
            raise ProviderPackageError("safe provider registry locking is unavailable")
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ProviderPackageError("provider registry lock is not regular")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _empty() -> dict:
        return {"schema": 1, "artifacts": {}, "proposals": {}, "active": {}, "revoked": []}

    @staticmethod
    def _active_key(record: ProviderRecord) -> str:
        return _canonical([record.source, record.home, record.provider_id]).decode("utf-8")

    def _active_records(self, state: dict, provider_id: str) -> list[ProviderRecord]:
        records = []
        for key, artifact_id in state["active"].items():
            try:
                record = self._record(state["artifacts"][artifact_id])
            except (KeyError, TypeError) as exc:
                raise ProviderPackageError("provider active index is invalid") from exc
            if key != self._active_key(record):
                raise ProviderPackageError("provider active scope binding changed")
            if record.provider_id == provider_id:
                records.append(record)
        return records

    def _load(self) -> dict:
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return self._empty()
        except OSError as exc:
            raise ProviderPackageError("provider registry is not a regular file") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REGISTRY_BYTES * 2:
                raise ProviderPackageError("provider registry exceeds capacity")
            raw = os.read(fd, MAX_REGISTRY_BYTES * 2 + 1)
            if len(raw) > MAX_REGISTRY_BYTES * 2:
                raise ProviderPackageError("provider registry exceeds capacity")
        finally:
            os.close(fd)
        try:
            clear = self._cipher.decrypt_bytes(raw)
            if len(clear) > MAX_REGISTRY_BYTES:
                raise ValueError("oversized registry")
            state = json.loads(clear.decode("utf-8"))
            if (type(state) is not dict or set(state) !=
                    {"schema", "artifacts", "proposals", "active", "revoked"}
                    or state["schema"] != 1 or type(state["artifacts"]) is not dict
                    or type(state["proposals"]) is not dict or type(state["active"]) is not dict
                    or type(state["revoked"]) is not list
                    or len(state["artifacts"]) > MAX_ARTIFACTS
                    or len(state["proposals"]) > MAX_PROPOSALS):
                raise ValueError("invalid registry schema")
            return state
        except (SecretStoreError, ValueError, TypeError, UnicodeError) as exc:
            raise ProviderPackageError("provider registry cannot be decrypted or validated") from exc

    def _commit(self, state: dict) -> None:
        raw = _canonical(state)
        if len(raw) > MAX_REGISTRY_BYTES:
            raise ProviderPackageError("provider registry capacity reached")
        token = self._cipher.encrypt_bytes(raw)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".registry-", delete=False) as out:
                temporary = out.name
                out.write(token)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            dir_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError as exc:
            raise ProviderPackageError("provider registry could not be committed") from exc
        finally:
            if temporary:
                with suppress(OSError):
                    os.unlink(temporary)

    def _journal(self) -> dict:
        try:
            fd = os.open(self._journal_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError as exc:
            if self.path.exists():
                raise ProviderPackageError("provider revocation journal is missing") from exc
            return {"schema": 1, "revoked_artifacts": []}
        except OSError as exc:
            raise ProviderPackageError("provider revocation journal is unreadable") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 128 * 1024:
                raise ProviderPackageError("provider revocation journal exceeds capacity")
            raw = os.read(fd, 128 * 1024 + 1)
            if len(raw) > 128 * 1024:
                raise ProviderPackageError("provider revocation journal exceeds capacity")
        finally:
            os.close(fd)
        try:
            sealed = json.loads(self._cipher.decrypt_bytes(raw).decode("utf-8"))
            journal = sealed["manifest"]
            signature = ManagedSignature(**sealed["signature"])
            ids = journal["revoked_artifacts"]
            if (set(journal) != {"schema", "revoked_artifacts"} or journal["schema"] != 1
                    or type(ids) is not list or len(ids) > MAX_ARTIFACTS
                    or len(set(ids)) != len(ids)
                    or any(type(item) is not str or re.fullmatch(r"[0-9a-f]{32}", item) is None
                           for item in ids)
                    or not self.signing.verify(journal, signature)):
                raise ValueError("invalid signed revocation journal")
            return journal
        except (SecretStoreError, ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise ProviderPackageError("provider revocation journal failed verification") from exc

    def _commit_journal(self, journal: dict) -> None:
        try:
            sealed = {"manifest": journal, "signature": asdict(self.signing.sign(journal))}
            token = self._cipher.encrypt_bytes(_canonical(sealed))
        except (SigningError, ValueError) as exc:
            raise ProviderPackageError("provider revocation journal signing failed") from exc
        if len(token) > 128 * 1024:
            raise ProviderPackageError("provider revocation journal capacity reached")
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".revocations-", delete=False) as out:
                temporary = out.name
                out.write(token)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._journal_path)
            dir_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError as exc:
            raise ProviderPackageError("provider revocation journal could not be committed") from exc
        finally:
            if temporary:
                with suppress(OSError):
                    os.unlink(temporary)

    def _record(self, row: dict) -> ProviderRecord:
        try:
            manifest = row["manifest"]
            if len(_canonical(manifest["profile"])) > MAX_PROFILE_BYTES:
                raise ValueError("oversized signed profile")
            signature = ManagedSignature(**row["signature"])
            if not self.signing.verify(manifest, signature):
                raise ValueError("invalid managed signature")
            profile = ProviderProfile(**manifest["profile"])
            if _profile_payload(profile) != manifest["profile"]:
                raise ValueError("profile changed during reconstruction")
            members = tuple(
                (item["path"], base64.b64decode(item["data"], validate=True))
                for item in row["members"]
            )
            if len(members) > MAX_FILES or sum(len(raw) for _, raw in members) > MAX_PACKAGE_BYTES:
                raise ValueError("oversized stored package")
            expected = manifest["files"]
            actual = [
                {"path": path, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                for path, raw in members
            ]
            if actual != expected or len({path for path, _ in members}) != len(members):
                raise ValueError("signed package bytes changed")
            if manifest["package_hash"] != row["package_hash"]:
                raise ValueError("package hash changed")
            seed = {key: value for key, value in manifest.items()
                    if key not in {"artifact_id", "package_hash"}}
            if hashlib.sha256(_canonical(seed)).hexdigest() != row["package_hash"]:
                raise ValueError("package digest changed")
            return ProviderRecord(
                artifact_id=manifest["artifact_id"], provider_id=manifest["provider_id"],
                package_hash=row["package_hash"], manifest=json.loads(_canonical(manifest)),
                signature=signature, profile=profile, hooks=tuple(manifest["hooks"]),
                members=tuple((path, bytes(raw)) for path, raw in members),
                source=manifest["source"], home=manifest["home"],
                replacement_target=manifest["replacement_target"],
            )
        except (KeyError, TypeError, ValueError, SigningError, OverflowError) as exc:
            raise ProviderPackageError("signed provider package failed verification") from exc

    def stage(
        self, directory: str | Path, *, profile: ProviderProfile,
        hooks: tuple[str, ...], source: str, home: str | None = None,
        replacement_target: str | None = None,
        sandbox_profile: AcquisitionSandboxProfile,
    ) -> ProviderRecord:
        if fcntl is None or not hasattr(fcntl, "flock"):
            raise ProviderPackageError("safe provider registry locking is unavailable")
        try:
            self.signing.active_identity()
        except SigningError as exc:
            raise ProviderPackageError("explicit managed signing key required") from exc
        if not isinstance(profile, ProviderProfile) or not isinstance(sandbox_profile, AcquisitionSandboxProfile):
            raise ProviderPackageError("host profile and pinned sandbox profile required")
        sandbox_profile = provider_sandbox_profile(sandbox_profile)
        if (source not in _SOURCES or (source == "user") != (home is not None)
                or home is not None and (type(home) is not str or not home or len(home) > 256)):
            raise ProviderPackageError("invalid provider source or home")
        if (type(hooks) not in (tuple, list) or len(hooks) > 16
                or any(type(hook) is not str or not _HOOK.fullmatch(hook) for hook in hooks)
                or len(set(hooks)) != len(hooks)):
            raise ProviderPackageError("invalid native hook declaration")
        if (not profile.is_user_defined or profile.auth_type in {"subscription", "oauth"}
                or profile.backend_kind in {"hermes-model-ipc"}
                or any(alias in _BUILTIN_IDENTITIES for alias in profile.aliases)):
            raise ProviderPackageError("package cannot claim a managed provider identity")
        if profile.id in _BUILTIN_IDENTITIES:
            builtin = _BUILTIN_BY_ID.get(profile.id)
            if (builtin is None or builtin.auth_type in {"subscription", "oauth"}
                    or replacement_target != profile.id):
                raise ProviderPackageError("built-in replacement needs its exact target")
        elif replacement_target is not None:
            raise ProviderPackageError("replacement target does not match a built-in identity")
        profile_payload = _profile_payload(profile)
        if len(_canonical(profile_payload)) > MAX_PROFILE_BYTES:
            raise ProviderPackageError("host provider profile exceeds signed byte limit")
        members, directories = _snapshot(Path(directory))
        names = {name for name, _ in members}
        if not {"provider.json", "main.py"}.issubset(names):
            raise ProviderPackageError("provider metadata and main.py are required")
        if len(dict(members)["provider.json"]) > MAX_MANIFEST_BYTES:
            raise ProviderPackageError("provider metadata exceeds discovery byte limit")
        try:
            declared_id, aliases, declared_target = _manifest_fields(dict(members)["provider.json"])
        except ValueError as exc:
            raise ProviderPackageError("provider metadata is invalid") from exc
        if (declared_id != profile.id or aliases != profile.aliases
                or declared_target != replacement_target):
            raise ProviderPackageError("provider metadata differs from host declaration")
        artifact_id = secrets.token_hex(16)
        seed = {
            "schema": 1, "provider_id": profile.id, "profile": profile_payload,
            "hooks": list(hooks), "source": source, "home": home,
            "replacement_target": replacement_target,
            "sandbox": _plain({item.name: getattr(sandbox_profile, item.name)
                               for item in fields(AcquisitionSandboxProfile)}),
            "runtime_image": sandbox_profile.image,
            "runtime_config_hash": sandbox_profile.config_hash,
            "directories": list(directories),
            "files": [{"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                      for name, raw in members],
        }
        package_hash = hashlib.sha256(_canonical(seed)).hexdigest()
        manifest = {**seed, "artifact_id": artifact_id, "package_hash": package_hash}
        try:
            signature = self.signing.sign(manifest)
        except SigningError as exc:
            raise ProviderPackageError("managed signing failed") from exc
        row = {
            "manifest": manifest, "signature": asdict(signature),
            "package_hash": package_hash,
            "members": [{"path": name, "data": base64.b64encode(raw).decode("ascii")}
                        for name, raw in members],
        }
        with self._locked():
            state = self._load()
            journal = self._journal()
            if len(state["artifacts"]) >= MAX_ARTIFACTS:
                raise ProviderPackageError("provider quarantine capacity reached")
            if not self._journal_path.exists():
                self._commit_journal(journal)
            state["artifacts"][artifact_id] = row
            self._commit(state)
        return self._record(row)

    def propose(self, artifact_id: str) -> str:
        with self._locked():
            state = self._load()
            if artifact_id not in state["artifacts"]:
                raise ProviderPackageError("unknown provider artifact")
            self._record(state["artifacts"][artifact_id])
            if len(state["proposals"]) >= MAX_PROPOSALS:
                raise ProviderPackageError("provider proposal capacity reached")
            proposal_id = secrets.token_hex(16)
            state["proposals"][proposal_id] = {"artifact_id": artifact_id, "status": "pending"}
            self._commit(state)
            return proposal_id

    def decide(self, proposal_id: str, *, approved: bool, actor: str,
               permanent: bool, expected_artifact_id: str | None = None,
               expected_package_hash: str | None = None) -> str:
        if type(approved) is not bool or type(permanent) is not bool:
            raise ProviderPackageError("literal approval and permanence required")
        if approved and (actor != "owner" or permanent is not True):
            raise ProviderPackageError("permanent literal owner approval required")
        with self._locked():
            state = self._load()
            proposal = state["proposals"].get(proposal_id)
            if not proposal or proposal["status"] != "pending":
                raise ProviderPackageError("provider proposal is stale")
            record = self._record(state["artifacts"][proposal["artifact_id"]])
            scoped = expected_artifact_id is not None or expected_package_hash is not None
            if scoped and (actor != "owner" or permanent is not True):
                raise ProviderPackageError("permanent literal owner decision required")
            if scoped and (record.artifact_id != expected_artifact_id
                           or record.package_hash != expected_package_hash):
                raise ProviderPackageError("provider decision scope changed")
            if approved or scoped:
                if not callable(self.owner_authorizer):
                    raise ProviderPackageError("authenticated owner authority unavailable")
                try:
                    permitted = self.owner_authorizer(proposal_id, record, actor)
                except Exception as exc:
                    raise ProviderPackageError("authenticated owner authority failed") from exc
                if permitted is not True:
                    raise ProviderPackageError("authenticated owner authority denied approval")
            proposal["status"] = "approved" if approved else "denied"
            proposal["actor"] = actor
            proposal["permanent"] = permanent
            self._commit(state)
            return proposal_id

    def _authorize(self, record: ProviderRecord, *, phase: str) -> None:
        if (self.enabled() is not True or not kernel_enabled()
                or not callable(self.authorizer)):
            raise ProviderPackageError("provider runtime or kernel authority unavailable")
        payload = {
            "provider_id": record.provider_id, "artifact_id": record.artifact_id,
            "package_hash": record.package_hash, "source": record.source,
            "home": record.home, "replacement_target": record.replacement_target,
            "profile": _profile_payload(record.profile), "hooks": list(record.hooks),
            "sandbox": record.manifest["sandbox"], "risk_tier": 3,
            "irreversible": True, "permanent": True, "phase": phase,
        }
        payload = json.loads(_canonical(payload))
        if not PROVIDER_LOAD_CONTRACT.evaluate(payload).admissible:
            raise ProviderPackageError("provider load contract denied package")
        action = Action(
            kind=KIND, agent="jarvis", title=f"{phase} provider {record.provider_id}",
            scope=f"provider:{record.provider_id}",
            payload=payload,
        )
        try:
            decision = self.authorizer(action)
        except Exception as exc:
            raise ProviderPackageError("provider kernel authority failed") from exc
        if (type(decision) is not Decision or decision.verdict is not Verdict.GRANT
                or decision.tier != 3):
            raise ProviderPackageError("provider kernel did not grant permanent load")

    def promote(self, proposal_id: str) -> ProviderRecord:
        with self._locked():
            state = self._load()
            proposal = state["proposals"].get(proposal_id)
            if (not proposal or proposal["status"] != "approved"
                    or proposal.get("actor") != "owner" or proposal.get("permanent") is not True):
                raise ProviderPackageError("permanent owner approval unavailable")
            record = self._record(state["artifacts"][proposal["artifact_id"]])
            if record.artifact_id in self._journal()["revoked_artifacts"]:
                raise ProviderPackageError("provider artifact was revoked")
            active_key = self._active_key(record)
            if active_key in state["active"]:
                raise ProviderPackageError("provider scope already promoted")
            self._authorize(record, phase="promote")
            proposal["status"] = "promoted"
            state["active"][active_key] = record.artifact_id
            state["revoked"] = [value for value in state["revoked"] if value != record.provider_id]
            self._commit(state)
            return record

    def revoke(self, provider_id: str) -> None:
        with _DISPATCH_GUARD:
            active = tuple(_DISPATCH_TASKS.get(self._root_identity, {}).get(provider_id, ()))
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if active and any(loop is current_loop for loop, _ in active):
            raise ProviderPackageError("in-flight provider revocation requires revoke_async")
        for loop, task in active:
            loop.call_soon_threadsafe(task.cancel)
        with self._locked():
            state = self._load()
            records = self._active_records(state, provider_id)
            if not records:
                raise ProviderPackageError("provider identity is not active")
            journal = self._journal()
            for record in records:
                if record.artifact_id not in journal["revoked_artifacts"]:
                    journal["revoked_artifacts"].append(record.artifact_id)
            self._commit_journal(journal)
            for record in records:
                state["active"].pop(self._active_key(record))
            if provider_id not in state["revoked"]:
                state["revoked"].append(provider_id)
            for proposal in state["proposals"].values():
                if self._record(state["artifacts"][proposal["artifact_id"]]).provider_id == provider_id:
                    proposal["status"] = "revoked"
            self._commit(state)

    async def revoke_async(self, provider_id: str) -> None:
        """Cancel in-flight sends, then persist revocation behind their leases."""
        with _DISPATCH_GUARD:
            active = tuple(_DISPATCH_TASKS.get(self._root_identity, {}).get(provider_id, ()))
        for loop, task in active:
            loop.call_soon_threadsafe(task.cancel)
        worker = asyncio.create_task(asyncio.to_thread(self.revoke, provider_id))
        cancelled = False
        while True:
            try:
                await asyncio.shield(worker)
                break
            except asyncio.CancelledError:
                cancelled = True
                if worker.done():
                    worker.result()  # Surface an unsuccessful revoke, never imply success.
                    break
        if cancelled:
            raise asyncio.CancelledError

    def _require_runnable_locked(self, provider_id: str, expected_hash: str | None,
                                 home: str | None) -> ProviderRecord:
        state = self._load()
        if provider_id in state["revoked"]:
            raise ProviderPackageError("provider is not admitted")
        records = [record for record in self._active_records(state, provider_id)
                   if record.source != "user" or home is not None and record.home == home]
        if expected_hash is not None:
            records = [record for record in records if record.package_hash == expected_hash]
        if not records:
            raise ProviderPackageError("provider package or home scope is not admitted")
        record = max(records, key=lambda item: _RANK[item.source])
        if record.artifact_id in self._journal()["revoked_artifacts"]:
            raise ProviderPackageError("provider artifact was revoked")
        self._authorize(record, phase="execute")
        return record

    @asynccontextmanager
    async def dispatch_lease(self, provider_id: str, *, expected_hash: str, home=None):
        """Keep revocation serialized through async transport completion."""
        if fcntl is None or not hasattr(fcntl, "flock"):
            raise ProviderPackageError("safe provider registry locking is unavailable")
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        locked = False
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ProviderPackageError("provider registry lock is not regular")
            while not locked:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except BlockingIOError:
                    await asyncio.sleep(0.01)
            record = self._require_runnable_locked(provider_id, expected_hash, home)
            with _DISPATCH_GUARD:
                _DISPATCH_TASKS.setdefault(self._root_identity, {}).setdefault(provider_id, set()).add((loop, task))
            try:
                yield record
            finally:
                with _DISPATCH_GUARD:
                    by_provider = _DISPATCH_TASKS[self._root_identity]
                    current = by_provider[provider_id]
                    current.discard((loop, task))
                    if not current:
                        by_provider.pop(provider_id, None)
                    if not by_provider:
                        _DISPATCH_TASKS.pop(self._root_identity, None)
        finally:
            if locked:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def require_runnable(self, provider_id: str, *, expected_hash: str | None = None,
                         home: str | None = None) -> ProviderRecord:
        with self._locked():
            return self._require_runnable_locked(provider_id, expected_hash, home)

    def inspect(self, artifact_id: str) -> ProviderRecord:
        """Verify a quarantined artifact without granting execution authority."""
        with self._locked():
            artifact = self._load()["artifacts"].get(artifact_id)
            if artifact is None:
                raise ProviderPackageError("provider artifact is unknown")
            return self._record(artifact)

    def list_active(self, *, home: str | None = None) -> tuple[ProviderRecord, ...]:
        """Return signed, owner-promoted records in the requested home scope."""
        with self._locked():
            state = self._load()
            revoked = set(self._journal()["revoked_artifacts"])
            records = []
            for key, artifact_id in state["active"].items():
                try:
                    record = self._record(state["artifacts"][artifact_id])
                except (KeyError, TypeError) as exc:
                    raise ProviderPackageError("provider active index is invalid") from exc
                if key != self._active_key(record):
                    raise ProviderPackageError("provider active scope binding changed")
                approved = any(
                    proposal.get("artifact_id") == artifact_id
                    and proposal.get("status") == "promoted"
                    and proposal.get("actor") == "owner"
                    and proposal.get("permanent") is True
                    for proposal in state["proposals"].values()
                )
                if (approved and artifact_id not in revoked
                        and record.provider_id not in state["revoked"]
                        and (record.source != "user" or record.home == home)):
                    records.append(record)
            return tuple(records)


__all__ = ["KIND", "ProviderPackageError", "ProviderPackageStore", "ProviderRecord"]
