"""Authenticated bounded attachment intake and shared media delivery."""
from email import policy
from email.parser import BytesParser

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from ..artifact_store import MAX_UPLOAD, BinaryArtifactStore, resolve_blob
from ..env_config import env_flag
from ._deps import user_guard

router = APIRouter(dependencies=[Depends(user_guard)])


def enabled():
    return env_flag('JARVIS_BINARY_ARTIFACTS')


def require_enabled():
    if not enabled():
        raise HTTPException(409, 'Binary attachments disabled; enable JARVIS_BINARY_ARTIFACTS')


@router.get('/api/artifacts')
async def artifacts_list():
    return {'enabled': enabled(), 'items': BinaryArtifactStore().all() if enabled() else [],
            'max_upload_bytes': MAX_UPLOAD}


@router.post('/api/artifacts', status_code=201)
async def artifacts_upload(request: Request):
    require_enabled()
    # Guard executes before we consume bytes. No UploadFile: its multipart parser
    # may spool an unlimited body to disk before the endpoint can enforce quota.
    content_type = request.headers.get('content-type', '')
    if not content_type.startswith('multipart/form-data;') or len(content_type) > 512:
        raise HTTPException(415, 'multipart file required')
    limit = MAX_UPLOAD + 65536
    length = request.headers.get('content-length')
    if length is not None and (not length.isdigit() or int(length) > limit):
        raise HTTPException(413, 'upload_too_large')
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise HTTPException(413, 'upload_too_large')
        body.extend(chunk)
    parsed = BytesParser(policy=policy.default).parsebytes(
        b'Content-Type: ' + content_type.encode('ascii', errors='replace') + b'\r\nMIME-Version: 1.0\r\n\r\n' + body)
    parts = list(parsed.iter_parts())
    if len(parts) != 1 or parts[0].get_param('name', header='content-disposition') != 'file' or parts[0].is_multipart():
        raise HTTPException(422, 'one file required')
    data = parts[0].get_payload(decode=True)
    try:
        return BinaryArtifactStore().put(data, agent='owner')
    except ValueError as exc:
        reason = str(exc)
        raise HTTPException(413 if 'too_large' in reason else 409 if 'quota' in reason else 415, reason) from None


@router.get('/api/artifacts/{artifact_id}/blob', response_class=Response)
async def artifacts_blob(artifact_id: str):
    if artifact_id.startswith('ba-'):
        require_enabled()
    try:
        meta, data = resolve_blob(artifact_id)
    except (ValueError, OSError):
        raise HTTPException(404, 'artifact_not_found') from None
    disposition = 'inline' if meta['mime'].startswith('image/') else 'attachment'
    return Response(data, media_type=meta['mime'], headers={
        'Content-Disposition': f'{disposition}; filename="{artifact_id}"',
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
        'Content-Security-Policy': "sandbox; default-src 'none'",
    })


@router.delete('/api/artifacts/{artifact_id}')
async def artifacts_delete(artifact_id: str):
    require_enabled()
    try:
        removed = BinaryArtifactStore().remove(artifact_id)
    except ValueError:
        removed = False
    if not removed:
        raise HTTPException(404, 'artifact_not_found')
    return {'ok': True}


@router.post('/api/artifacts/{artifact_id}/pin')
async def artifacts_pin(artifact_id: str, pinned: bool = True):
    require_enabled()
    try:
        row = BinaryArtifactStore().pin(artifact_id, pinned)
    except ValueError:
        row = None
    if row is None:
        raise HTTPException(404, 'artifact_not_found')
    return row


from pydantic import BaseModel, Field


class MediaExportBody(BaseModel):
    model_config = {'extra': 'forbid'}
    ids: list[str] = Field(min_length=1, max_length=200)


@router.post('/api/media/export', response_class=Response)
def media_export(body: MediaExportBody):
    """In-memory portable bundle; no host path or arbitrary file-write surface."""
    import hashlib
    import io
    import json
    import zipfile

    from ..media_library import catalog_snapshot
    from ..paths import data_root

    needs_catalog = any(item_id.startswith('md-') for item_id in body.ids)
    if needs_catalog and not env_flag('JARVIS_MEDIA_CATALOG'):
        raise HTTPException(409, 'Media catalog disabled')
    records = catalog_snapshot(data_root())[0] if needs_catalog else None
    buffer = io.BytesIO()
    manifest, missing, total = [], [], 0
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        for item_id in dict.fromkeys(body.ids):
            if item_id.startswith('ba-'):
                require_enabled()
            elif not env_flag('JARVIS_MEDIA_CATALOG'):
                raise HTTPException(409, 'Media catalog disabled')
            try:
                meta, data = resolve_blob(item_id, catalog_records=records)
            except (ValueError, OSError):
                missing.append(item_id[:80])
                continue
            total += len(data)
            if total > 128 * 1024 * 1024:
                raise HTTPException(413, 'bundle_too_large')
            archive.writestr('media/' + item_id, data)
            manifest.append({**meta, 'kind': meta['mime'].split('/')[0], 'sha256': hashlib.sha256(data).hexdigest()})
        archive.writestr('manifest.json', json.dumps({'items': manifest, 'missing': missing}))
    return Response(buffer.getvalue(), media_type='application/zip', headers={
        'Content-Disposition': 'attachment; filename="nerva-media.zip"',
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
    })
