"""Authenticated bounded attachment intake and shared media delivery."""
from email import policy
from email.parser import BytesParser

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from ..artifact_store import BinaryArtifactStore, MAX_UPLOAD, resolve_blob
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
