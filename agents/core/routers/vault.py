"""vault.py router — 0.53's sibling theme T-0.20: the encrypted personal blob vault
surface (list/put/get/delete) over `agents/core/vault.py`.

The vault module (crypto, atomic index commits, cross-process locking, quota
enforcement) already existed with zero live callers — this is the HTTP surface
that actually reaches it. `user_guard`, not `admin_guard`: this is the owner's
own content (documents, secrets, notes), meant to be retrievable like memory/
notes (HF-1's rule), not admin-only credential material like `secrets.py`'s
JIT broker (values never come back out there; here they explicitly do, to the
owner who put them there).

Every handler wraps the synchronous `Vault` (disk I/O + crypto) in
`asyncio.to_thread` so a vault operation never blocks the event loop — the
same discipline already enforced for memory/KG/house I/O elsewhere in this
router package.

Erasure: the vault root is NOT in `data_purge.KEEP_DIRS`, so `forget`'s
KEEP-inverted sweep already deletes it wholesale — no extra purge wiring
needed here (verified against `agents/core/data_purge.py`). Export needs the
decrypt-and-embed step in `agents/core/data_export.py`, since a raw copy of
the vault directory would just be inspectable ciphertext.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import threading
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.vault import Vault, VaultError
from agents.core.web_helpers import error_json, nocache_json

router = APIRouter(tags=["vault"])

# HTTP-layer cap, deliberately far below Vault's own generous internal
# per-item ceiling (1 GiB, meant for future non-HTTP callers): a JSON body is
# not how anyone should move gigabytes, and an unbounded body here is a DoS
# surface. 25 MiB covers documents/notes/small attachments comfortably.
_MAX_HTTP_ITEM_BYTES = 25 * 1024 * 1024

_VAULT_LOCK = threading.Lock()
_VAULT_SINGLETON: Vault | None = None


def _get_vault() -> Vault:
    global _VAULT_SINGLETON
    with _VAULT_LOCK:
        if _VAULT_SINGLETON is None:
            _VAULT_SINGLETON = Vault()
        return _VAULT_SINGLETON


class VaultPutBody(BaseModel):
    name: str = Field("", max_length=200)
    kind: str = Field("blob", max_length=40)
    data_base64: str = Field(..., min_length=1)
    expires_at: float | None = None


def _list_and_stats(vault: Vault) -> tuple[list[dict], dict]:
    return vault.list(), vault.stats()


@router.get("/api/vault", dependencies=[Depends(user_guard)])
async def vault_list():
    vault = _get_vault()
    try:
        items, stats = await asyncio.to_thread(_list_and_stats, vault)
    except VaultError as exc:
        return error_json(exc, 500, "vault is unavailable", extra={"items": [], "stats": None})
    return nocache_json({"items": items, "stats": stats})


@router.post("/api/vault", dependencies=[Depends(user_guard)])
async def vault_put(body: VaultPutBody):
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        return error_json(exc, 400, "data_base64 is not valid base64")
    if len(data) > _MAX_HTTP_ITEM_BYTES:
        return error_json(
            ValueError("item too large"), 413,
            f"item exceeds the {_MAX_HTTP_ITEM_BYTES // (1024 * 1024)} MiB HTTP upload cap",
        )
    vault = _get_vault()
    try:
        entry = await asyncio.to_thread(
            vault.put, data, name=body.name, kind=body.kind,
            now=time.time(), expires_at=body.expires_at,
        )
    except VaultError as exc:
        return error_json(exc, 400, "vault refused the item")
    return nocache_json({"ok": True, "entry": entry})


@router.get("/api/vault/{vault_id}", dependencies=[Depends(user_guard)])
async def vault_get(vault_id: str):
    vault = _get_vault()
    try:
        entry, data = await asyncio.to_thread(_read_entry_and_data, vault, vault_id)
    except VaultError as exc:
        return error_json(exc, 404, "no such vault item")
    return nocache_json({**entry, "data_base64": base64.b64encode(data).decode("ascii")})


def _read_entry_and_data(vault: Vault, vault_id: str) -> tuple[dict, bytes]:
    """Metadata + plaintext for one item, read as one unit off the event loop."""
    items = vault.list()
    entry = next((e for e in items if e["id"] == vault_id), None)
    if entry is None:
        raise VaultError(f"no such vault item: {vault_id}")
    return entry, vault.get(vault_id)


@router.delete("/api/vault/{vault_id}", dependencies=[Depends(user_guard)])
async def vault_delete(vault_id: str):
    vault = _get_vault()
    try:
        removed = await asyncio.to_thread(vault.remove, vault_id)
    except VaultError as exc:
        return error_json(exc, 400, "vault refused the delete")
    return nocache_json({"ok": True, "removed": removed})
