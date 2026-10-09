"""Standalone generated IDs bind new PNGs to an expected digest sidecar."""

import hashlib
import json
import os
import struct
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents import web
from agents.core.media_backends import comfyui
from tests.test_local_image_backend import PNG, configured


def _paths(root, item_id):
    return root / f"{item_id}.png", root / f"{item_id}.sha256.json"


def _chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _variant(text):
    return PNG[:-12] + _chunk(b"tEXt", b"note\0" + text) + PNG[-12:]


def test_new_binding_roundtrip_and_same_size_valid_png_tamper(tmp_path):
    original, replacement = _variant(b"a"), _variant(b"b")
    assert len(original) == len(replacement)
    assert comfyui.validate_png(original) == comfyui.validate_png(replacement)
    result = comfyui.save_artifact(tmp_path, original, 1, 1)
    item_id = result["artifact_id"]
    png, sidecar = _paths(tmp_path, item_id)
    assert png.read_bytes() == original
    assert json.loads(sidecar.read_text()) == {
        "version": 1, "sha256": hashlib.sha256(original).hexdigest(),
    }
    assert result["sha256"] == hashlib.sha256(original).hexdigest()
    assert comfyui.artifact_bytes(item_id, tmp_path) == original
    # A fresh reader invocation sees the durable binding, not a process cache.
    assert comfyui.artifact_bytes(item_id, tmp_path) == original
    png.write_bytes(replacement)
    with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
        comfyui.artifact_bytes(item_id, tmp_path)


@pytest.mark.parametrize("content", [
    b"{}", b'{"version":true,"sha256":"' + b"a" * 64 + b'"}',
    b'{"version":1,"sha256":"' + b"A" * 64 + b'"}',
    b'{"version":1,"sha256":null}',
    b'{"version":1,"sha256":"' + b"a" * 64 + b'","other":1}',
    b'{"version":1,"sha256":"' + b"a" * 64 + b'","version":1}',
    b"x" * 256,
])
def test_malformed_or_oversized_sidecar_refuses_even_valid_png(tmp_path, content):
    result = comfyui.save_artifact(tmp_path, PNG, 1, 1)
    _png, sidecar = _paths(tmp_path, result["artifact_id"])
    sidecar.write_bytes(content)
    with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
        comfyui.artifact_bytes(result["artifact_id"], tmp_path)


def test_wrong_expected_digest_refuses(tmp_path):
    result = comfyui.save_artifact(tmp_path, PNG, 1, 1)
    _png, sidecar = _paths(tmp_path, result["artifact_id"])
    sidecar.write_text(json.dumps({"version": 1, "sha256": "a" * 64}))
    with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
        comfyui.artifact_bytes(result["artifact_id"], tmp_path)


def test_legacy_png_without_sidecar_remains_readable_and_orphan_is_unavailable(tmp_path):
    item_id = "a" * 32
    png, sidecar = _paths(tmp_path, item_id)
    png.write_bytes(PNG)
    assert comfyui.artifact_bytes(item_id, tmp_path) == PNG
    png.unlink()
    sidecar.write_text(json.dumps({"version": 1, "sha256": hashlib.sha256(PNG).hexdigest()}))
    with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
        comfyui.artifact_bytes(item_id, tmp_path)


def test_symlink_sidecar_including_dangling_is_not_legacy(tmp_path):
    item_id = "a" * 32
    png, sidecar = _paths(tmp_path, item_id)
    png.write_bytes(PNG)
    sidecar.symlink_to(tmp_path / "missing.json")
    with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
        comfyui.artifact_bytes(item_id, tmp_path)


def test_sidecar_replaced_by_symlink_between_stat_and_open_refuses(tmp_path, monkeypatch):
    result = comfyui.save_artifact(tmp_path, PNG, 1, 1)
    _png, sidecar = _paths(tmp_path, result["artifact_id"])
    target = tmp_path / "other.json"
    target.write_bytes(sidecar.read_bytes())
    original_open = os.open

    def replaced_open(path, flags, *args, **kwargs):
        if Path(path) == sidecar:
            sidecar.unlink()
            sidecar.symlink_to(target)
            flags &= ~getattr(os, "O_NOFOLLOW", 0)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(comfyui.os, "open", replaced_open)
    with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
        comfyui.artifact_bytes(result["artifact_id"], tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO required")
def test_fifo_sidecar_is_rejected_without_blocking(tmp_path):
    item_id = "a" * 32
    png, sidecar = _paths(tmp_path, item_id)
    png.write_bytes(PNG)
    os.mkfifo(sidecar)
    start = time.monotonic()
    with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
        comfyui.artifact_bytes(item_id, tmp_path)
    assert time.monotonic() - start < 1


@pytest.mark.parametrize("occupied", ["png", "sidecar", "dangling_png", "dangling_sidecar"])
def test_collision_refuses_without_touching_either_existing_path(tmp_path, monkeypatch, occupied):
    item_id = "a" * 32
    monkeypatch.setattr(comfyui.uuid, "uuid4", lambda: SimpleNamespace(hex=item_id))
    png, sidecar = _paths(tmp_path, item_id)
    target = png if occupied.endswith("png") else sidecar
    if occupied.startswith("dangling"):
        target.symlink_to(tmp_path / "missing")
    else:
        target.write_bytes(b"preexisting")
    with pytest.raises(comfyui.ImageGenerationError, match="artifact_write_failed"):
        comfyui.save_artifact(tmp_path, PNG, 1, 1)
    assert list(tmp_path.iterdir()) == [target]
    if target.is_symlink():
        assert target.readlink() == tmp_path / "missing"
    else:
        assert target.read_bytes() == b"preexisting"


def test_guard_sees_bound_sidecar_and_refusal_cleans_only_own_files(tmp_path, monkeypatch):
    item_id = "a" * 32
    monkeypatch.setattr(comfyui.uuid, "uuid4", lambda: SimpleNamespace(hex=item_id))
    png, sidecar = _paths(tmp_path, item_id)

    def guard():
        assert sidecar.exists() and not png.exists()
        raise comfyui.ImageGenerationError("kernel_denied")

    with pytest.raises(comfyui.ImageGenerationError, match="kernel_denied"):
        comfyui.save_artifact(tmp_path, PNG, 1, 1, guard=guard)
    assert list(tmp_path.iterdir()) == []


def test_mandatory_file_fsync_failure_leaves_no_published_file(tmp_path, monkeypatch):
    def failed_fsync(_fd):
        raise OSError("disk sync failed")

    monkeypatch.setattr(comfyui.os, "fsync", failed_fsync)
    with pytest.raises(comfyui.ImageGenerationError, match="artifact_write_failed"):
        comfyui.save_artifact(tmp_path, PNG, 1, 1)
    assert list(tmp_path.iterdir()) == []


def test_failure_after_png_link_keeps_binding_and_image(tmp_path, monkeypatch):
    item_id = "a" * 32
    monkeypatch.setattr(comfyui.uuid, "uuid4", lambda: SimpleNamespace(hex=item_id))
    calls = 0

    def fail_second_directory_sync(_root):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected post-link failure")

    monkeypatch.setattr(comfyui, "_fsync_dir", fail_second_directory_sync)
    with pytest.raises(comfyui.ImageGenerationError, match="artifact_write_failed"):
        comfyui.save_artifact(tmp_path, PNG, 1, 1)
    assert calls == 2
    png, sidecar = _paths(tmp_path, item_id)
    assert set(tmp_path.iterdir()) == {png, sidecar}
    assert comfyui.artifact_bytes(item_id, tmp_path) == PNG


@pytest.mark.parametrize("stat_unavailable", [False, True])
def test_ambiguous_png_link_error_retains_binding_when_own_or_uncertain(
    tmp_path, monkeypatch, stat_unavailable,
):
    item_id = "a" * 32
    monkeypatch.setattr(comfyui.uuid, "uuid4", lambda: SimpleNamespace(hex=item_id))
    png, sidecar = _paths(tmp_path, item_id)
    original_link, original_stat = os.link, Path.stat

    def ambiguous_link(src, dst, *args, **kwargs):
        original_link(src, dst, *args, **kwargs)
        if Path(dst) == png:
            raise OSError("link completed but caller lost acknowledgment")

    def uncertain_stat(path, *args, **kwargs):
        if stat_unavailable and path.suffix == ".tmp":
            raise OSError("staged inode cannot be inspected")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(comfyui.os, "link", ambiguous_link)
    monkeypatch.setattr(Path, "stat", uncertain_stat)
    with pytest.raises(comfyui.ImageGenerationError, match="artifact_write_failed"):
        comfyui.save_artifact(tmp_path, PNG, 1, 1)
    assert set(tmp_path.iterdir()) == {png, sidecar}
    assert comfyui.artifact_bytes(item_id, tmp_path) == PNG


@pytest.mark.asyncio
async def test_tampered_binding_is_opaque_http_404_and_edit_refuses_before_transport(tmp_path, monkeypatch):
    from agents.core.routers import multimodal

    monkeypatch.setattr(web, "USER_TOKEN", "digest-test-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    monkeypatch.setattr("agents.core.paths.data_path", lambda *_parts: tmp_path)
    result = comfyui.save_artifact(tmp_path, PNG, 1, 1)
    item_id = result["artifact_id"]
    app = FastAPI()
    app.include_router(multimodal.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app, client=("198.51.100.23", 5000)),
        base_url="http://test",
    ) as client:
        allowed = await client.get(
            "/api/media/generated/" + item_id,
            headers={"X-User-Token": "digest-test-user"},
        )
        assert allowed.status_code == 200 and allowed.content == PNG
        png, _sidecar = _paths(tmp_path, item_id)
        png.write_bytes(_variant(b"changed"))
        refused = await client.get(
            "/api/media/generated/" + item_id,
            headers={"X-User-Token": "digest-test-user"},
        )
        assert refused.status_code == 404
        assert refused.json() == {"ok": False, "reason": "artifact_not_found"}
    requests = []

    def forbidden(request):
        requests.append(request)
        raise AssertionError("tampered reference opened network transport")

    backend = comfyui.ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(forbidden))
    with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
        await backend.generate("edit boat", {"reference": item_id})
    assert requests == []


def test_same_id_concurrent_publication_is_serialized(tmp_path, monkeypatch):
    item_id = "a" * 32
    monkeypatch.setattr(comfyui.uuid, "uuid4", lambda: SimpleNamespace(hex=item_id))
    entered, release = Event(), Event()

    def paused_guard():
        entered.set()
        assert release.wait(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(comfyui.save_artifact, tmp_path, PNG, 1, 1, guard=paused_guard)
        assert entered.wait(2)
        try:
            with pytest.raises(comfyui.ImageGenerationError, match="artifact_write_failed"):
                comfyui.save_artifact(tmp_path, PNG, 1, 1)
        finally:
            release.set()
        result = first.result(timeout=2)
    assert comfyui.artifact_bytes(result["artifact_id"], tmp_path) == PNG
    assert sorted(path.suffix for path in tmp_path.iterdir()) == [".json", ".png"]


@pytest.mark.parametrize("cleanup_blocked", [False, True])
def test_noncooperating_publisher_collision_keeps_its_png_and_never_serves_mixed_bytes(
    tmp_path, monkeypatch, cleanup_blocked,
):
    item_id = "a" * 32
    monkeypatch.setattr(comfyui.uuid, "uuid4", lambda: SimpleNamespace(hex=item_id))
    png, sidecar = _paths(tmp_path, item_id)
    source, competing_bytes = _variant(b"a"), _variant(b"b")
    competitor = tmp_path / "competitor.tmp"
    competitor.write_bytes(competing_bytes)
    original_link, original_unlink = os.link, Path.unlink

    def competing_link(src, dst, *args, **kwargs):
        if Path(dst) == png:
            # A publisher outside this local reservation protocol links first.
            original_link(competitor, png)
        return original_link(src, dst, *args, **kwargs)

    def unavailable_cleanup(path, *args, **kwargs):
        if cleanup_blocked and path == sidecar:
            raise OSError("cleanup unavailable")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(comfyui.os, "link", competing_link)
    monkeypatch.setattr(Path, "unlink", unavailable_cleanup)
    with pytest.raises(comfyui.ImageGenerationError, match="artifact_write_failed"):
        comfyui.save_artifact(tmp_path, source, 1, 1)
    original_unlink(competitor)
    assert png.read_bytes() == competing_bytes
    assert sidecar.exists() is cleanup_blocked
    if cleanup_blocked:
        with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
            comfyui.artifact_bytes(item_id, tmp_path)
    else:
        # The other publisher's file remains available as legacy-unbound.
        assert comfyui.artifact_bytes(item_id, tmp_path) == competing_bytes
    assert set(tmp_path.iterdir()) == ({png, sidecar} if cleanup_blocked else {png})
