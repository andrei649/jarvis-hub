"""Bounded named speech approvals, separate from generic settings authority.

Lookup never creates the database or table. Empty records remain revisioned
tombstones, so clearing a name cannot revive an old pending approval.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing

RESERVED_IDS = frozenset({'auto', 'command', 'whisper', 'faster-whisper', 'piper', 'edge',
                         'edge-tts', 'kokoro', 'xtts', 'elevenlabs', 'fish', 'fish-audio',
                         'openai', 'minimax', 'mistral', 'gemini', 'xai', 'neutts',
                         'kittentts', 'local', 'provider'})
MAX_ACTIVE = 16
MAX_NAMES = 128
MAX_JSON_BYTES = 300000
MAX_REVISION = 2**63 - 1


class ProviderStoreError(RuntimeError):
    """Unavailable or malformed approval storage: refuse rather than fall back."""


class ProviderConflict(ProviderStoreError):
    """The owner changed this exact named approval since the request."""


class ProviderLimit(ProviderStoreError):
    """The bounded named-provider catalog is full."""


def valid_provider_id(value) -> bool:
    return (isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', value) is not None
            and value not in RESERVED_IDS)


def _identity(side, provider_id) -> None:
    if side not in ('tts', 'stt') or not valid_provider_id(provider_id):
        raise ProviderStoreError('invalid_provider_id')


def _path():
    from agents.core import settings_db
    return settings_db.DB_PATH


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate field')
        value[key] = item
    return value


def _valid_value(value):
    return isinstance(value, dict) and (not value or (
        isinstance(value.get('argv'), list) and 0 < len(value['argv']) <= 64
        and all(isinstance(v, str) and v and len(v) <= 4000 for v in value['argv'])))


def _decode(row) -> dict:
    name, revision, raw = row
    if not valid_provider_id(name) or type(revision) is not int or not 1 <= revision <= MAX_REVISION:
        raise ProviderStoreError('invalid_provider_record')
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_JSON_BYTES:
        raise ProviderStoreError('invalid_provider_record')
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, RecursionError) as exc:
        raise ProviderStoreError('invalid_provider_record') from exc
    if not _valid_value(value):
        raise ProviderStoreError('invalid_provider_record')
    return {**value, 'provider_id': name, 'provider_revision': revision}


def _read(side) -> list[dict]:
    if side not in ('tts', 'stt'):
        raise ProviderStoreError('invalid_side')
    path = _path()
    if not path.exists():
        return []
    try:
        with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            try:
                rows = conn.execute('SELECT provider_id, revision, approved_json FROM voice_command_providers WHERE side=? ORDER BY provider_id LIMIT ?', (side, MAX_NAMES + 1)).fetchall()
            except sqlite3.OperationalError as exc:
                if 'no such table: voice_command_providers' in str(exc):
                    return []
                raise
            if len(rows) > MAX_NAMES:
                raise ProviderStoreError('invalid_provider_count')
            records = [_decode(row) for row in rows]
            if sum(bool(r.get('argv')) for r in records) > MAX_ACTIVE:
                raise ProviderStoreError('invalid_provider_count')
            return records
    except (sqlite3.Error, OSError, UnicodeError) as exc:
        raise ProviderStoreError('provider_store_unavailable') from exc


def load(side, provider_id) -> dict:
    _identity(side, provider_id)
    return next((r for r in _read(side) if r['provider_id'] == provider_id),
                {'provider_id': provider_id, 'provider_revision': 0})


def list_records(side) -> list[dict]:
    return [r for r in _read(side) if r.get('argv')]


def _write(side, provider_id, value, expected_revision) -> tuple[int, dict | None]:
    """Write one named record; returns the new revision and the record it replaced, as
    read inside this write's own transaction (``None`` when the name was never
    written)."""
    _identity(side, provider_id)
    if expected_revision is not None and (type(expected_revision) is not int or not 0 <= expected_revision < MAX_REVISION):
        raise ProviderStoreError('invalid_provider_revision')
    if not _valid_value(value):
        raise ProviderStoreError('invalid_provider_record')
    if expected_revision is not None and expected_revision > 0 and load(side, provider_id)['provider_revision'] != expected_revision:
        raise ProviderConflict('provider_revision_conflict')
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        if len(raw.encode('utf-8')) > MAX_JSON_BYTES:
            raise ProviderStoreError('provider_record_too_large')
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(path), timeout=5)) as conn:
            try:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute('CREATE TABLE IF NOT EXISTS voice_command_providers (side TEXT NOT NULL, provider_id TEXT NOT NULL, approved_json TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(side, provider_id))')
                rows = conn.execute('SELECT provider_id, revision, approved_json FROM voice_command_providers WHERE side=? LIMIT ?', (side, MAX_NAMES + 1)).fetchall()
                records = [_decode(row) for row in rows]
                if len(records) > MAX_NAMES or sum(bool(r.get('argv')) for r in records) > MAX_ACTIVE:
                    raise ProviderStoreError('invalid_provider_count')
                previous = next((r for r in records if r['provider_id'] == provider_id), None)
                revision = previous['provider_revision'] if previous else 0
                if expected_revision is not None and revision != expected_revision:
                    raise ProviderConflict('provider_revision_conflict')
                if revision >= MAX_REVISION:
                    raise ProviderStoreError('provider_revision_overflow')
                if previous is None and len(records) >= MAX_NAMES:
                    raise ProviderLimit('provider_history_full')
                if value and not (previous or {}).get('argv') and sum(bool(r.get('argv')) for r in records) >= MAX_ACTIVE:
                    raise ProviderLimit('provider_capacity_full')
                revision += 1
                conn.execute('INSERT INTO voice_command_providers(side, provider_id, approved_json, revision) VALUES(?,?,?,?) ON CONFLICT(side,provider_id) DO UPDATE SET approved_json=excluded.approved_json,revision=excluded.revision', (side, provider_id, raw, revision))
                conn.commit()
                return revision, previous
            except BaseException:
                conn.rollback()
                raise
    except (sqlite3.Error, OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ProviderStoreError('provider_store_unavailable') from exc


def save_approved(side, provider_id, value, *, expected_revision) -> int:
    if type(expected_revision) is not int or not value:
        raise ProviderStoreError('invalid_provider_revision')
    return _write(side, provider_id, value, expected_revision)[0]


def clear(side, provider_id) -> int:
    return clear_in_force(side, provider_id)[0]


def clear_in_force(side, provider_id) -> tuple[int, dict | None]:
    """Clear one name; returns the tombstone's revision and the approval this clear
    revoked — the record that was in force, read inside the clear's own write — or
    ``None`` when nothing was in force (never approved, or already cleared)."""
    revision, previous = _write(side, provider_id, {}, None)
    return revision, (previous if previous and previous.get('argv') else None)
