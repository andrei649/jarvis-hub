"""Inert, revisioned signed-provider selection metadata in the settings store.

This is a CAS and readback primitive, not owner authority or backend activation.
Task 10B2 must validate the actor, current signed record, credential generation,
model, endpoint and policy before calling it or using a returned binding.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .providers import selection_gates

_IDENTITY = re.compile(r'[a-z0-9][a-z0-9._:-]{0,127}\Z')
_ARTIFACT = re.compile(r'[0-9a-f]{32}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')


class SelectionInvalid(RuntimeError):
    """Persisted selection bytes or proposed metadata are not exact and safe."""


class SelectionConflict(RuntimeError):
    """The expected revision is no longer current."""


@dataclass(frozen=True, slots=True)
class SelectionBinding:
    authority: str
    home: str
    provider_id: str
    model: str
    source: str
    artifact_id: str
    package_hash: str
    endpoint: str
    auth_type: str
    credential_generation: int

    def __post_init__(self):
        try:
            url = urlsplit(self.endpoint)
            endpoint_ok = (url.scheme == 'https' and bool(url.hostname)
                           and url.username is None and url.password is None
                           and url.port != 0 and not url.query and not url.fragment
                           and all(33 <= ord(char) <= 126 for char in self.endpoint))
        except (TypeError, ValueError):
            endpoint_ok = False
        if (self.authority != 'local-owner-v1'
                or type(self.home) is not str or not 1 <= len(self.home) <= 2048
                or type(self.provider_id) is not str or not _IDENTITY.fullmatch(self.provider_id)
                or type(self.model) is not str or not 1 <= len(self.model) <= 256
                or any(ord(char) < 33 or ord(char) > 126 for char in self.model)
                or self.source not in {'user', 'legacy', 'bundled'}
                or type(self.artifact_id) is not str or not _ARTIFACT.fullmatch(self.artifact_id)
                or type(self.package_hash) is not str or not _HASH.fullmatch(self.package_hash)
                or type(self.endpoint) is not str or len(self.endpoint) > 2048 or not endpoint_ok
                or self.auth_type not in {'bearer', 'api-key', 'none'}
                or type(self.credential_generation) is not int
                or not 0 <= self.credential_generation < 2**63 - 1
                or (self.credential_generation == 0) != (self.auth_type == 'none')):
            raise SelectionInvalid('invalid signed selection metadata')


@dataclass(frozen=True, slots=True)
class SelectionRecord:
    revision: int
    binding: SelectionBinding


def _json(binding: SelectionBinding) -> str:
    return json.dumps(asdict(binding), sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _digest(revision: int, payload: str) -> str:
    return hashlib.sha256(f'{revision}\n{payload}'.encode('ascii')).hexdigest()


def _row(conn) -> tuple[int, SelectionBinding | None]:
    rows = conn.execute('SELECT singleton,revision,record_json,record_hash '
                        'FROM signed_provider_selection').fetchall()
    if len(rows) != 1 or rows[0][0] != 1 or type(rows[0][1]) is not int or rows[0][1] < 0:
        raise SelectionInvalid('selection revision unreadable')
    _, revision, payload, digest = rows[0]
    if payload is None and digest is None:
        return revision, None
    if (type(payload) is not str or type(digest) is not str
            or not _HASH.fullmatch(digest) or len(payload) > 8192):
        raise SelectionInvalid('selection record unreadable')
    try:
        fields = json.loads(payload)
        if type(fields) is not dict or set(fields) != set(SelectionBinding.__dataclass_fields__):
            raise ValueError('selection fields changed')
        binding = SelectionBinding(**fields)
        if _json(binding) != payload or _digest(revision, payload) != digest:
            raise ValueError('selection hash changed')
    except (TypeError, ValueError, SelectionInvalid) as exc:
        raise SelectionInvalid('selection readback failed') from exc
    return revision, binding


def _path(path: str | Path | None) -> Path:
    from agents.core import settings_db

    return settings_db.DB_PATH if path is None else Path(path)


def _read(path: Path) -> tuple[int, SelectionBinding | None]:
    from agents.core import settings_db

    conn = settings_db.get_conn()
    try:
        return _row(conn)
    except Exception as exc:
        if isinstance(exc, SelectionInvalid):
            raise
        raise SelectionInvalid('selection store unreadable') from exc
    finally:
        conn.close()


def current_revision(path: str | Path | None = None) -> int:
    from agents.core import settings_db

    target = _path(path)
    settings_db._ensure_init()
    with selection_gates.shared(target):
        return _read(target)[0]


def read_selection(path: str | Path | None = None) -> SelectionRecord | None:
    from agents.core import settings_db

    target = _path(path)
    settings_db._ensure_init()
    with selection_gates.shared(target):
        revision, binding = _read(target)
    return SelectionRecord(revision, binding) if binding is not None else None


def compare_and_swap(path: str | Path | None, binding: SelectionBinding,
                     *, expected_revision: int) -> SelectionRecord:
    """Persist exact metadata under CAS; a caller must separately prove authority."""
    from agents.core import settings_db

    if (type(binding) is not SelectionBinding or type(expected_revision) is not int
            or expected_revision < 0):
        raise SelectionInvalid('invalid signed selection CAS')
    target = _path(path)
    with selection_gates.exclusive(target, signed=True):
        settings_db._ensure_init()
        conn = settings_db.get_conn()
        next_revision = expected_revision + 1
        payload = _json(binding)
        try:
            with conn:
                revision, _old = _row(conn)
                if revision != expected_revision:
                    raise SelectionConflict('selection revision changed')
                cur = conn.execute(
                    'UPDATE signed_provider_selection SET revision=?,record_json=?,record_hash=? '
                    'WHERE singleton=1 AND revision=?',
                    (next_revision, payload, _digest(next_revision, payload), expected_revision))
                if cur.rowcount != 1 or _row(conn) != (next_revision, binding):
                    raise SelectionInvalid('selection CAS readback failed')
        finally:
            conn.close()
        if _read(target) != (next_revision, binding):
            raise SelectionInvalid('selection durable readback failed')
    return SelectionRecord(next_revision, binding)
