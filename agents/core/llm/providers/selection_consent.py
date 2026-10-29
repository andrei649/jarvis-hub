"""Private, revision-bound owner consent proof for one signed selection.

The selection row is an atomic carrier, not an authority source. Only the
owner service mints a proof after its Kernel and audit decisions. A raw B1 CAS
can carry bytes but cannot make them authenticate under this private key.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path

from .packages import ProviderPackageError, _secure_root

_KEY_NAME = 'selection-consent.key'
_DOMAIN = b'nerva:signed-provider-selection-consent:v1\0'
_ISSUED: dict[object, tuple] = {}
_ISSUED_LOCK = threading.Lock()


def _close(capability):
    if type(capability) is not object:
        return
    with _ISSUED_LOCK:
        _ISSUED.pop(capability, None)


def _issue(service, actor, action, decision, binding, revision, profile, policy):
    """Issue only inside the exact live selection receipt, after all audits."""
    from agents.core.kernel import Decision, Verdict

    from .install_service import (
        _SELECTION_AUDIT_DONE,
        _SELECTION_RECEIPT,
        selection_receipt_matches,
    )

    receipt = _SELECTION_RECEIPT.get()
    payload = getattr(action, 'payload', {})
    if (receipt is None or _SELECTION_AUDIT_DONE.get() is not action
            or receipt[0] is not service or receipt[1] is not action
            or receipt[2] is not actor or receipt[3] != threading.get_ident()
            or not selection_receipt_matches(action)
            or type(decision) is not Decision or decision.verdict is not Verdict.GRANT
            or decision.tier != 3 or action.kind != 'provider.selection'
            or payload.get('operation') != 'select'
            or payload.get('selected_revision') != revision
            or payload.get('current_revision') != revision - 1
            or payload.get('authority') != binding.authority
            or payload.get('home') != binding.home
            or payload.get('provider_id') != binding.provider_id
            or payload.get('source') != binding.source
            or payload.get('artifact_id') != binding.artifact_id
            or payload.get('package_hash') != binding.package_hash
            or payload.get('endpoint') != binding.endpoint
            or payload.get('auth_type') != binding.auth_type
            or payload.get('model') != binding.model
            or payload.get('credential_generation') != binding.credential_generation
            or payload.get('price_ack') is not True
            or binding.unknown_price_ack is not True
            or payload.get('data_ack') is not binding.data_policy_ack):
        raise ProviderPackageError('selection mint capability unavailable')
    capability = object()
    with _ISSUED_LOCK:
        _ISSUED[capability] = (service, actor, Path(service.root),
                               _message(binding, revision, profile, policy),
                               threading.get_ident())
    return capability


def _root_fd(root: Path):
    path, identity = _secure_root(root)
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != identity:
            raise ProviderPackageError('selection consent root changed')
        return fd, identity
    except OSError:
        if fd >= 0:
            os.close(fd)
        raise ProviderPackageError('selection consent root unavailable') from None
    except BaseException:
        if fd >= 0:
            os.close(fd)
        raise


def _check_root(root: Path, fd: int, identity: tuple[int, int]):
    opened = os.fstat(fd)
    if ((opened.st_dev, opened.st_ino) != identity
            or _secure_root(root)[1] != identity):
        raise ProviderPackageError('selection consent root changed')


def _read_key(fd: int, *, absent_ok: bool = False) -> bytes | None:
    try:
        child = os.open(_KEY_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                        dir_fd=fd)
    except FileNotFoundError:
        if absent_ok:
            return None
        raise ProviderPackageError('selection consent key unavailable') from None
    except OSError:
        raise ProviderPackageError('selection consent key unavailable') from None
    try:
        opened = os.fstat(child)
        named = os.stat(_KEY_NAME, dir_fd=fd, follow_symlinks=False)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                or opened.st_nlink != 1 or stat.S_IMODE(opened.st_mode) & 0o077
                or opened.st_size != 32
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise ProviderPackageError('selection consent key unsafe')
        key = os.read(child, 33)
        if len(key) != 32 or os.fstat(child).st_size != 32:
            raise ProviderPackageError('selection consent key changed')
        return key
    except OSError:
        raise ProviderPackageError('selection consent key unavailable') from None
    finally:
        os.close(child)


def _key(root: Path, *, create: bool) -> bytes:
    fd, identity = _root_fd(root)
    try:
        _check_root(root, fd, identity)
        key = _read_key(fd, absent_ok=create)
        if key is not None:
            return key
        temporary = '.selection-consent-' + secrets.token_hex(16)
        child = -1
        try:
            child = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600, dir_fd=fd)
            material = secrets.token_bytes(32)
            if os.write(child, material) != 32:
                raise ProviderPackageError('selection consent key write incomplete')
            os.fsync(child)
            os.close(child)
            child = -1
            _check_root(root, fd, identity)
            try:
                os.link(temporary, _KEY_NAME, src_dir_fd=fd, dst_dir_fd=fd,
                        follow_symlinks=False)
            except FileExistsError:
                # A concurrent first writer published its own durable key.
                _read_key(fd)
            os.fsync(fd)
            os.unlink(temporary, dir_fd=fd)
            temporary = None
            os.fsync(fd)
            _check_root(root, fd, identity)
            return _read_key(fd)
        except OSError:
            raise ProviderPackageError('selection consent key unavailable') from None
        finally:
            if child >= 0:
                os.close(child)
            if temporary is not None:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=fd)
    finally:
        os.close(fd)


def _message(binding, revision: int, profile, policy: str) -> bytes:
    if (type(revision) is not int or revision <= 0
            or profile.id != binding.provider_id
            or binding.model not in profile.fallback_models
            or profile.data_policy_for(binding.model)[0] != policy):
        raise ProviderPackageError('selection consent scope unavailable')
    fields = asdict(binding)
    fields.pop('consent_proof')
    payload = {'revision': revision, 'binding': fields, 'policy': policy,
               'declaration_policy': profile.data_policy,
               'declaration_models': profile.data_policy_models}
    return _DOMAIN + json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                ensure_ascii=True).encode('ascii')


def mint(root, binding, revision: int, profile, policy: str, *, capability=None) -> str:
    """Consume the exact post-audit capability before touching private key bytes."""
    if type(capability) is not object:
        raise ProviderPackageError('selection mint capability required')
    with _ISSUED_LOCK:
        issued = _ISSUED.pop(capability, None)
    if issued is None:
        raise ProviderPackageError('selection mint capability required')
    message = _message(binding, revision, profile, policy)
    from .install_service import _owner_current

    service, actor, issued_root, issued_message, issued_thread = issued
    if (issued_thread != threading.get_ident()
            or issued_root != Path(root) or service.root != Path(root)
            or not hmac.compare_digest(issued_message, message)
            or service.enabled() is not True or not _owner_current(actor)):
        raise ProviderPackageError('selection mint capability changed or expired')
    return hmac.new(_key(Path(root), create=True), message, hashlib.sha256).hexdigest()


def verify(root, selection, profile, policy: str) -> bool:
    """Refuse missing, altered and replayed proof without a fallback key."""
    binding = selection.binding
    if not binding.consent_proof:
        return False
    try:
        message = _message(binding, selection.revision, profile, policy)
        expected = hmac.new(_key(Path(root), create=False), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(binding.consent_proof, expected)
    except (ProviderPackageError, OSError, TypeError, ValueError):
        return False
