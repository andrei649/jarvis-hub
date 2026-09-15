"""Bounded local binary artifacts. No client path, MIME trust, or in-memory index.

SQLite serializes quota decisions across HTTP workers. Metadata is always read
from disk, so a live instance cannot resurrect an index after forget.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .paths import data_root

MAX_UPLOAD = 16 * 1024 * 1024
ID = re.compile(r"ba-[a-f0-9]{32}")


def sniff(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        from .media_backends.comfyui import validate_png
        validate_png(data)
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'):
        return 'image/jpeg'
    if data[:6] in (b'GIF87a', b'GIF89a') and len(data) >= 14:
        return 'image/gif'
    if data[:4] == b'RIFF' and len(data) >= 12:
        if data[8:12] == b'WEBP':
            return 'image/webp'
        if data[8:12] == b'WAVE':
            return 'audio/wav'
    if data.startswith(b'%PDF-') and b'%%EOF' in data[-1024:]:
        return 'application/pdf'
    if data.startswith(b'OggS\x00') and len(data) >= 27:
        return 'audio/ogg'
    if (data.startswith(b'ID3') and len(data) >= 10) or (len(data) >= 4 and data[0] == 255 and data[1] & 0xe0 == 0xe0):
        return 'audio/mpeg'
    if len(data) >= 16 and data[4:8] == b'ftyp' and data[8:12] in (b'isom', b'iso2', b'mp41', b'mp42', b'avc1', b'M4V '):
        return 'video/mp4'
    if data.startswith(b'\x1a\x45\xdf\xa3') and b'webm' in data[:4096]:
        return 'video/webm'
    raise ValueError('unsupported_media')


class BinaryArtifactStore:
    def __init__(self, root=None, *, max_upload=MAX_UPLOAD, max_bytes=128 * 1024 * 1024, max_items=200):
        self.root = Path(root) if root is not None else data_root()
        self.directory = self.root / 'artifacts'
        self.index = self.root / 'artifacts.db'
        self.max_upload, self.max_bytes, self.max_items = max_upload, max_bytes, max_items

    def _safe_root(self):
        # Refuse symlinked data-root components as well as blob/index symlinks.
        for path in (self.root, *self.root.parents, self.directory, self.index):
            if path.is_symlink():
                raise ValueError('unsafe_artifact_store')

    @contextmanager
    def _upload_lock(self):
        """Exclude uploads through the whole forget/backup operation.

        This non-content sidecar is outside the purged tree and is never unlinked:
        replacing a locked inode would let another process escape the lock.
        """
        self._safe_root()
        path = self.root.parent / ('.' + self.root.name + '-artifacts.lock')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError('unsafe_artifact_store')
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'r+b') as handle:
            try:
                if os.name == 'nt':
                    import msvcrt
                    if os.fstat(handle.fileno()).st_size == 0:
                        handle.write(b'\0')
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError('artifact_store_busy') from None
            try:
                yield
            finally:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _db(self):
        self._safe_root()
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.index, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, kind TEXT, mime TEXT, size INTEGER, sha256 TEXT, agent TEXT, created_at REAL, pinned INTEGER)')
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _row(self, row):
        return {**dict(row), 'pinned': bool(row['pinned'])}

    def all(self):
        self._safe_root()
        if not self.index.exists():
            return []
        with self._db() as db:
            return [self._row(r) for r in db.execute('SELECT * FROM artifacts ORDER BY created_at DESC')]

    def get_meta(self, item_id):
        return next((r for r in self.all() if r['id'] == item_id), None)

    def _path(self, item_id):
        self._safe_root()
        if not isinstance(item_id, str) or not ID.fullmatch(item_id):
            raise ValueError('artifact_not_found')
        return self.directory / item_id

    def put(self, data, mime=None, agent='owner', *, now=None):
        if not isinstance(data, bytes) or len(data) > self.max_upload:
            raise ValueError('upload_too_large')
        detected = sniff(data)  # Client MIME intentionally ignored.
        if len(data) > self.max_bytes:
            raise ValueError('store_quota_exceeded')
        if not isinstance(agent, str) or not 1 <= len(agent) <= 80:
            raise ValueError('invalid_agent')
        row = {'id': 'ba-' + uuid.uuid4().hex, 'kind': detected.split('/')[0], 'mime': detected,
               'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'agent': agent,
               'created_at': time.time() if now is None else now, 'pinned': False}
        with self._upload_lock(), self._db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM artifacts ORDER BY created_at ASC')]
            # Recover the only crash window: blob fsynced, metadata uncommitted.
            # Reclaim orphan files before another quota decision can accumulate them.
            self._remove_unindexed({r['id'] for r in rows})
            victims = []
            while len(rows) >= self.max_items or sum(r['size'] for r in rows) + len(data) > self.max_bytes:
                victim = next((r for r in rows if not r['pinned']), None)
                if victim is None:
                    raise ValueError('store_quota_exceeded')
                rows.remove(victim)
                victims.append(victim)
            self.directory.mkdir(mode=0o700, exist_ok=True)
            path = self._path(row['id'])
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, 'wb') as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                db.execute('INSERT INTO artifacts VALUES (:id,:kind,:mime,:size,:sha256,:agent,:created_at,:pinned)', row)
                for victim in victims:
                    self._path(victim['id']).unlink(missing_ok=True)
                    db.execute('DELETE FROM artifacts WHERE id=?', (victim['id'],))
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        return row

    def read(self, item_id):
        path = self._path(item_id)
        row = self.get_meta(item_id)
        if row is None:
            raise ValueError('artifact_not_found')
        try:
            if path.is_symlink():
                raise ValueError('artifact_not_found')
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('artifact_not_found')
                data = stream.read(self.max_upload + 1)
            if len(data) != row['size'] or len(data) > self.max_upload or hashlib.sha256(data).hexdigest() != row['sha256'] or sniff(data) != row['mime']:
                raise ValueError('artifact_not_found')
            return row, data
        except OSError:
            raise ValueError('artifact_not_found') from None

    def remove(self, item_id):
        path = self._path(item_id)
        if not self.index.exists():
            return False
        with self._db() as db:
            existed = db.execute('SELECT id FROM artifacts WHERE id=?', (item_id,)).fetchone()
            path.unlink(missing_ok=True)  # unlink symlink itself, never its target
            db.execute('DELETE FROM artifacts WHERE id=?', (item_id,))
            return bool(existed)

    def pin(self, item_id, pinned):
        self._path(item_id)
        with self._db() as db:
            db.execute('UPDATE artifacts SET pinned=? WHERE id=?', (bool(pinned), item_id))
        return self.get_meta(item_id)

    def _remove_unindexed(self, keep):
        self._safe_root()
        if self.directory.exists():
            for path in self.directory.iterdir():
                if path.name in keep:
                    continue
                if path.is_symlink() or not path.is_dir():
                    path.unlink(missing_ok=True)
                else:
                    shutil.rmtree(path)

    def _clear_locked(self):
        with self._db() as db:
            self._remove_unindexed(set())
            db.execute('DELETE FROM artifacts')

    def clear(self):
        with self._upload_lock():
            self._clear_locked()

    @contextmanager
    def forget(self):
        with self._upload_lock():
            self._clear_locked()
            yield

    def clear_memory(self, persist=False):
        # No cached metadata. persist is accepted for the common store protocol.
        if persist:
            self.clear()

    def retain(self, ttl_days, *, now=None):
        deleted = []
        if ttl_days > 0:
            cutoff = (time.time() if now is None else now) - ttl_days * 86400
            for row in self.all():
                if not row['pinned'] and row['created_at'] < cutoff:
                    with self._db() as db:
                        current = db.execute('SELECT id FROM artifacts WHERE id=? AND pinned=0 AND created_at<?', (row['id'], cutoff)).fetchone()
                        if current is not None:
                            self._path(row['id']).unlink(missing_ok=True)
                            db.execute('DELETE FROM artifacts WHERE id=?', (row['id'],))
                            deleted.append(row['id'])
        return {'deleted': deleted}

    def export(self):
        items, missing = [], []
        for row in self.all():
            try:
                meta, data = self.read(row['id'])
                items.append({**meta, 'base64': base64.b64encode(data).decode('ascii')})
            except ValueError:
                missing.append(row['id'])
        return {'items': items, 'missing': missing}


def resolve_blob(item_id, root=None, *, catalog_records=None):
    """Shared delivery contract for attachments and existing generated PNGs."""
    root = Path(root) if root is not None else data_root()
    if isinstance(item_id, str) and ID.fullmatch(item_id):
        return BinaryArtifactStore(root).read(item_id)
    if isinstance(item_id, str) and item_id.startswith('md-'):
        from .media_library import read_catalog_blob
        return read_catalog_blob(item_id, root, records=catalog_records)
    from .media_backends.comfyui import artifact_bytes
    data = artifact_bytes(item_id, root / 'media' / 'generated')
    return {'id': item_id, 'mime': 'image/png', 'size': len(data)}, data
