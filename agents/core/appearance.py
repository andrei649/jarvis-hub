"""Instance-owner display preferences; no arbitrary settings or styling inputs."""
from __future__ import annotations

import json
import uuid

from agents.core import settings_db

OPTIONS = {
    'font': ('theme', 'system-sans', 'system-serif', 'system-mono', 'jetbrains-mono'),
    'accent': ('cyan', 'amber', 'green', 'violet'),
    'look': ('obsidian', 'graphite'),
    'density': ('normal', 'compact', 'comfy'),
    'motion': ('system', 'calm', 'lively'),
    'scanline': ('on', 'off'),
    'dotgrid': ('off', 'on'),
}
DEFAULTS = {key: values[0] for key, values in OPTIONS.items()}


def _document(row) -> dict:
    try:
        value = json.loads(row['value']) if row else {}
    except (ValueError, TypeError):
        value = {}
    if not isinstance(value, dict):
        return {}
    return {key: value[key] if value[key] in choices else choices[0]
            for key, choices in OPTIONS.items() if key in value}


class RevisionConflict(Exception):
    """The shared appearance changed since the client read it."""


def _revision(row) -> str:
    try:
        value = json.loads(row['value']) if row else {}
        revision = value.get('_revision', '0') if isinstance(value, dict) else '0'
        return revision if isinstance(revision, str) else '0'
    except (ValueError, TypeError):
        return '0'


def _response(document: dict, revision: str) -> dict:
    return {'revision': revision, 'configured': bool(document), 'preferences': {**DEFAULTS, **document}}


def read_appearance() -> dict:
    # Unlike general fallback getters, a DB failure must remain visible to this
    # sync client. It must not replace cached owner choices with invented defaults.
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    try:
        row = conn.execute("SELECT value FROM settings WHERE category='appearance' AND key='preferences'").fetchone()
        return _response(_document(row), _revision(row))
    finally:
        conn.close()


def update_appearance(patch: dict, expected_revision: str | None = None) -> dict:
    if not patch.keys() <= OPTIONS.keys():
        raise ValueError('unknown appearance field')
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    try:
        # Serialize read/merge/write across processes: different devices changing
        # different fields cannot clobber each other's preferences.
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT value FROM settings WHERE category='appearance' AND key='preferences'").fetchone()
        if expected_revision is not None and expected_revision != _revision(row):
            raise RevisionConflict()
        document = _document(row)
        revision = uuid.uuid4().hex
        document.update({key: value if value in OPTIONS[key] else DEFAULTS[key] for key, value in patch.items()})
        conn.execute("""INSERT INTO settings(category,key,value,label,kind,opts)
                        VALUES('appearance','preferences',?,'Appearance preferences','json','[]')
                        ON CONFLICT(category,key) DO UPDATE SET value=excluded.value""", (json.dumps({**document, '_revision': revision}),))
        conn.commit()
        return _response(document, revision)
    finally:
        conn.close()
