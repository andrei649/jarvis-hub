"""One path-free gallery and bounded reader for generated media and local cache."""
import hashlib
import os
import re
import stat
from pathlib import Path

from .artifact_store import MAX_UPLOAD, BinaryArtifactStore, sniff
from .media_catalog import MediaCatalog
from .paths import data_root

CATALOG_ID = re.compile(r'md-[a-f0-9]{12}')


def catalog_snapshot(root):
    """Load and validate one bounded snapshot; never silently certify bad rows."""
    root = Path(root)
    BinaryArtifactStore(root)._safe_root()
    catalog_file = root / 'media' / 'catalog.json'
    if catalog_file.is_symlink() or (root / 'media').is_symlink():
        raise ValueError('artifact_not_found')
    catalog = MediaCatalog(catalog_file)
    try:
        raw = catalog._load_rows(strict=True)
    except ValueError:
        return {}, 1
    invalid = max(0, len(raw) - catalog._max_keep)
    rows = {}
    for value in raw[-catalog._max_keep:]:
        try:
            row = catalog._validated_record(value)
            if (not CATALOG_ID.fullmatch(row.get('id', ''))
                    or row.get('kind') not in {'image', 'thumbnail', 'video'}
                    or not row.get('path') or row['id'] in rows):
                raise ValueError('invalid_catalog_row')
            rows[row['id']] = row
        except ValueError:
            invalid += 1
    rows = dict(sorted(rows.items(), key=lambda pair: pair[1].get('created_at', 0), reverse=True))
    return rows, invalid


def catalog_path(item_id, root, *, records=None):
    if not isinstance(item_id, str) or not CATALOG_ID.fullmatch(item_id):
        raise ValueError('artifact_not_found')
    root = Path(root)
    BinaryArtifactStore(root)._safe_root()
    if (root / 'media').is_symlink() or (root / 'media' / 'catalog.json').is_symlink():
        raise ValueError('artifact_not_found')
    if records is None:
        records, _ = catalog_snapshot(root)
    row = records.get(item_id)
    if not row or row.get('id') != item_id:
        raise ValueError('artifact_not_found')
    path = Path(row.get('path', ''))
    # Recheck paths even with a snapshot: validation never grants a later symlink.
    allowed = (root / 'media' / 'generated', root / 'media' / 'cache')
    if not path.is_absolute() or path.resolve() != path or not any(path.is_relative_to(base) for base in allowed):
        raise ValueError('artifact_not_found')
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('artifact_not_found')
    return path


def _read_bytes(path, limit, *, header_only=False):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_UPLOAD
                or (not header_only and info.st_size > limit)):
            raise ValueError('artifact_not_found')
        data = stream.read(limit if header_only else limit + 1)
    if len(data) != min(info.st_size, limit) or len(data) > limit:
        raise ValueError('artifact_not_found')
    return data, info.st_size


def _mime_hint(data):
    """Bounded listing hint only. Full MIME/content validation stays in delivery."""
    for prefix, mime in ((b'\x89PNG\r\n\x1a\n', 'image/png'), (b'\xff\xd8\xff', 'image/jpeg'),
                         (b'GIF87a', 'image/gif'), (b'GIF89a', 'image/gif'),
                         (b'%PDF-', 'application/pdf'), (b'OggS\x00', 'audio/ogg'), (b'ID3', 'audio/mpeg')):
        if data.startswith(prefix):
            return mime
    if data[:4] == b'RIFF' and data[8:12] in {b'WEBP', b'WAVE'}:
        return 'image/webp' if data[8:12] == b'WEBP' else 'audio/wav'
    if len(data) >= 4 and data[0] == 255 and data[1] & 0xe0 == 0xe0:
        return 'audio/mpeg'
    if len(data) >= 16 and data[4:8] == b'ftyp' and data[8:12] in {b'isom', b'iso2', b'mp41', b'mp42', b'avc1', b'M4V '}:
        return 'video/mp4'
    if data.startswith(b'\x1a\x45\xdf\xa3') and b'webm' in data:
        return 'video/webm'
    raise ValueError('unsupported_media')


def read_catalog_blob(item_id, root=None, *, records=None, max_bytes=MAX_UPLOAD):
    root = Path(root) if root is not None else data_root()
    path = catalog_path(item_id, root, records=records)
    try:
        data, _ = _read_bytes(path, min(MAX_UPLOAD, max_bytes))
        mime = sniff(data)
    except (OSError, ValueError):
        raise ValueError('artifact_not_found') from None
    return {'id': item_id, 'mime': mime, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}, data


def gallery(root=None, *, generated=False, attached=False):
    root = Path(root) if root is not None else data_root()
    rows = []
    if generated:
        records, _ = catalog_snapshot(root)
        for row in list(records.values())[:200]:
            public = {key: row[key] for key in ('id', 'kind', 'prompt', 'backend', 'cloud', 'created_at', 'tags') if key in row}
            public.update(source='generated', available=False)
            try:
                path = catalog_path(row['id'], root, records=records)
                header, size = _read_bytes(path, 4096, header_only=True)
                public.update(mime=_mime_hint(header), size=size, available=True, validation='on_download')
            except (ValueError, OSError):
                pass
            rows.append(public)
    if attached:
        for row in BinaryArtifactStore(root).all():
            rows.append({**row, 'source': 'attachment', 'prompt': '', 'available': True})
    return sorted(rows, key=lambda row: row.get('created_at', 0), reverse=True)[:200]


def export_generated(root):
    """Portable byte export using the same allowlisted resolver as gallery delivery."""
    import base64
    items, missing, total = [], [], 0
    records, invalid_count = catalog_snapshot(root)
    for row in records.values():
        try:
            meta, data = read_catalog_blob(row['id'], root, records=records, max_bytes=128 * 1024 * 1024 - total)
            if total + len(data) > 128 * 1024 * 1024:
                raise ValueError('export_size_limit')
            total += len(data)
            items.append({**meta, 'kind': row['kind'], 'base64': base64.b64encode(data).decode('ascii')})
        except ValueError:
            missing.append(row['id'])
    return {'items': items, 'missing': missing, 'invalid_count': invalid_count, 'complete': not missing and invalid_count == 0}


def _gallery_key(row):
    return (row.get('created_at', 0), row['source'], row['id'])


def _page_cursor(value, filters):
    """Bounded position token, never a path or authorization capability."""
    import base64
    import json
    import math

    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 1024 or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
            raise ValueError
        payload = json.loads(base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True))
        if not isinstance(payload, dict) or set(payload) != {'v', 'filters', 'upper', 'after'}:
            raise ValueError
        if type(payload['v']) is not int or payload['v'] != 1 or payload['filters'] != filters:
            raise ValueError
        for name in ('upper', 'after'):
            key = payload[name]
            if not isinstance(key, list) or len(key) != 3:
                raise ValueError
            timestamp, source, item_id = key
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
                raise ValueError
            if not isinstance(source, str) or not isinstance(item_id, str):
                raise ValueError
            pattern = {'generated': r'md-[a-f0-9]{12}', 'attachment': r'ba-[a-f0-9]{32}'}.get(source)
            if pattern is None or not re.fullmatch(pattern, item_id):
                raise ValueError
        upper, after = tuple(payload['upper']), tuple(payload['after'])
        if after > upper:
            raise ValueError
        return upper, after
    except (ValueError, TypeError, OverflowError, UnicodeError) as exc:
        raise ValueError('invalid_gallery_cursor') from exc


def gallery_page(root=None, *, generated=False, attached=False, q='', kind='', limit=200, cursor=None):
    """Scan <=200 candidates, preserving continuation through zero-match pages.

    The upper key excludes newer appends, not later backdated insertions. Metadata
    loads remain bounded by existing stores; only candidate headers are opened.
    """
    import base64
    import json

    if not isinstance(q, str) or len(q) > 256 or not isinstance(kind, str) or len(kind) > 32:
        raise ValueError('invalid_gallery_filter')
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('invalid_gallery_limit')
    q = q.lower()
    filters = hashlib.sha256(json.dumps([q, kind, bool(generated), bool(attached)]).encode()).hexdigest()
    upper, after = _page_cursor(cursor, filters) if cursor is not None else (None, None)
    root = Path(root) if root is not None else data_root()
    records, invalid = catalog_snapshot(root) if generated else ({}, 0)
    candidates = [dict(row, source='generated') for row in records.values()]
    if attached:
        candidates.extend(dict(row, source='attachment') for row in BinaryArtifactStore(root).all())
    candidates.sort(key=_gallery_key, reverse=True)
    total = len(candidates)
    if upper is None and candidates:
        upper = _gallery_key(candidates[0])
    remaining = [row for row in candidates if _gallery_key(row) <= upper and (after is None or _gallery_key(row) < after)]
    items, scanned, last = [], 0, None
    for row in remaining[:200]:
        scanned += 1
        last = _gallery_key(row)
        if row['source'] == 'generated':
            public = {key: row[key] for key in ('id', 'kind', 'prompt', 'backend', 'cloud', 'created_at', 'tags') if key in row}
            public.update(source='generated', available=False)
            try:
                path = catalog_path(row['id'], root, records=records)
                header, size = _read_bytes(path, 4096, header_only=True)
                public.update(mime=_mime_hint(header), size=size, available=True, validation='on_download')
            except (ValueError, OSError):
                pass
        else:
            public = dict(row, prompt='', available=True)
        text = f"{public.get('prompt', '')} {public.get('mime', '')} {public['id']}".lower()
        if (not q or q in text) and (not kind or public['kind'] == kind):
            items.append(public)
            if len(items) == limit:
                break
    has_more = scanned < len(remaining)
    next_cursor = None
    if has_more:
        payload = {'v': 1, 'filters': filters, 'upper': upper, 'after': last}
        next_cursor = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
    by_kind = {}
    for item in items:
        by_kind[item['kind']] = by_kind.get(item['kind'], 0) + 1
    return {'items': items, 'stats': {'total': len(items), 'cloud': sum(bool(r.get('cloud')) for r in items), 'by_kind': by_kind},
            'page': {'catalog_total': total, 'scanned': scanned, 'matches': len(items), 'has_more': has_more,
                     'next_cursor': next_cursor, 'invalid_count': invalid}}
