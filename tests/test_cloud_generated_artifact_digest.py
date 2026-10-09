"""Signed cloud completions bind standalone generated IDs through shared publication."""

import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from agents.core import cloud_image_runtime
from agents.core.media_backends import comfyui
from tests.test_cloud_image import cloud, finish


def _generated(task, root):
    item = task.result["result"]["result"]
    base = root / "media" / "generated"
    return item, base / (item["artifact_id"] + ".png"), base / (item["artifact_id"] + ".sha256.json")


def _other_png():
    output = io.BytesIO()
    Image.new("RGB", (1024, 1024), "red").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_signed_cloud_completion_binds_raw_id_and_restart_without_replay(cloud):
    task = await finish(cloud)
    assert task.result["status"] == "ok", task.result
    artifact, png, sidecar = _generated(task, cloud.root)
    expected = hashlib.sha256(png.read_bytes()).hexdigest()
    done = json.loads(cloud.runtime._path(task, "complete").read_text())
    assert json.loads(sidecar.read_text()) == {"version": 1, "sha256": expected}
    assert done["sha256"] == expected
    assert done["artifact"] == artifact
    assert artifact["bytes"] == png.stat().st_size
    assert (artifact["width"], artifact["height"]) == (1024, 1024)
    assert comfyui.artifact_bytes(artifact["artifact_id"], png.parent) == png.read_bytes()
    restarted = cloud_image_runtime.CloudImageRuntime(
        cloud.worker, kernel=cloud.kernel, redact=lambda value: value, root=cloud.root,
    )
    assert restarted.recover(task) == cloud.runtime.recover(task)
    assert (await cloud.runtime.execute(task))["status"] == "refused"
    assert len(cloud.requests) == 1


@pytest.mark.asyncio
async def test_tampered_new_cloud_png_refuses_raw_read_and_recovery_even_after_sidecar_loss(cloud):
    task = await finish(cloud)
    assert task.result["status"] == "ok"
    artifact, png, sidecar = _generated(task, cloud.root)
    png.write_bytes(_other_png())
    with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
        comfyui.artifact_bytes(artifact["artifact_id"], png.parent)
    with pytest.raises(comfyui.ImageGenerationError, match="reference_not_found"):
        cloud.runtime.recover(task)
    sidecar.unlink()
    assert comfyui.artifact_bytes(artifact["artifact_id"], png.parent) == png.read_bytes()
    with pytest.raises(ValueError, match="cloud image artifact changed"):
        cloud.runtime.recover(task)
    assert len(cloud.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["sidecar", "png"])
async def test_shared_publication_failure_is_unknown_and_never_replays(cloud, monkeypatch, failure):
    original_link = os.link

    def failed_link(source, destination, *args, **kwargs):
        name = Path(destination).name
        if (failure == "sidecar" and name.endswith(".sha256.json")) or (
            failure == "png" and name.endswith(".png")
        ):
            raise OSError("local publication unavailable")
        return original_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(comfyui.os, "link", failed_link)
    task = await finish(cloud)
    assert task.result["status"] == "unknown", task.result
    assert cloud.runtime._path(task, "attempt").exists()
    assert not cloud.runtime._path(task, "complete").exists()
    root = cloud.root / "media" / "generated"
    assert list(root.iterdir()) == []
    assert (await cloud.runtime.execute(task))["status"] == "refused"
    assert len(cloud.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["declined", "machinery", "state_unavailable"])
async def test_final_live_guard_preserves_withheld_or_recheck_failure(cloud, monkeypatch, failure):
    from agents.core import estop
    from agents.core.autonomy.queue import MediationStateUnavailable

    real_save = comfyui.save_artifact
    entered = []

    def guarded_save(output_root, data, width, height, *, guard):
        def final_guard():
            entered.append(list(output_root.glob("*.sha256.json")))
            assert len(entered[-1]) == 1 and list(output_root.glob("*.png")) == []
            if failure == "declined":
                monkeypatch.setattr(estop, "is_engaged", lambda: True)
            elif failure == "machinery":
                cloud.runtime.kernel = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("policy store unreadable")
                )
            else:
                cloud.queue.validate_mediated_execution = lambda *_args: (_ for _ in ()).throw(
                    MediationStateUnavailable("mediation store unreadable")
                )
            guard()

        return real_save(output_root, data, width, height, guard=final_guard)

    monkeypatch.setattr(cloud_image_runtime, "save_artifact", guarded_save, raising=False)
    task = await finish(cloud)
    assert len(entered) == 1 and len(cloud.requests) == 1
    expected = (
        {"status": "failed", "reason": "withheld_after_generation", "detail": "estop_engaged"}
        if failure == "declined" else {"status": "failed", "reason": (
            "mediation_state_unavailable" if failure == "state_unavailable"
            else "cloud_image_recheck_failed"
        )}
    )
    assert task.result == expected
    assert list((cloud.root / "media" / "generated").iterdir()) == []
    assert not cloud.runtime._path(task, "complete").exists()


@pytest.mark.asyncio
async def test_final_root_safety_failure_after_sidecar_is_publication_unknown(cloud, monkeypatch):
    real_save = comfyui.save_artifact
    real_safe = cloud_image_runtime._safe
    entered = []

    def guarded_save(output_root, data, width, height, *, guard):
        def final_guard():
            entered.append(list(output_root.glob("*.sha256.json")))
            assert len(entered[-1]) == 1 and list(output_root.glob("*.png")) == []
            monkeypatch.setattr(
                cloud_image_runtime, "_safe",
                lambda _root: (_ for _ in ()).throw(ValueError("unsafe cloud image storage")),
            )
            try:
                guard()
            finally:
                monkeypatch.setattr(cloud_image_runtime, "_safe", real_safe)

        return real_save(output_root, data, width, height, guard=final_guard)

    monkeypatch.setattr(cloud_image_runtime, "save_artifact", guarded_save)
    task = await finish(cloud)
    assert len(entered) == 1 and len(cloud.requests) == 1
    assert task.result["status"] == "unknown"
    assert list((cloud.root / "media" / "generated").iterdir()) == []
    assert not cloud.runtime._path(task, "complete").exists()


@pytest.mark.asyncio
async def test_generated_root_symlink_still_refuses_publication(cloud, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    media = cloud.root / "media"
    media.mkdir(exist_ok=True)
    (media / "generated").symlink_to(target, target_is_directory=True)
    task = await finish(cloud)
    assert task.result["status"] == "unknown"
    assert len(cloud.requests) == 1
    assert list(target.iterdir()) == []
    assert not cloud.runtime._path(task, "complete").exists()


def test_cloud_configuration_refuses_changed_loaded_shared_publisher(cloud, tmp_path, monkeypatch):
    fake = tmp_path / "changed-comfyui.py"
    fake.write_text("# changed shared publication implementation\n")
    monkeypatch.setattr(comfyui, "__file__", str(fake))
    with pytest.raises(comfyui.ImageGenerationError, match="backend_source_changed"):
        cloud.runtime.submit("blue square", {}, "user")
    assert cloud.queue.list() == [] and cloud.requests == []


@pytest.mark.asyncio
async def test_occupied_sidecar_id_never_publishes_png_or_overwrites_binding(cloud, monkeypatch):
    task_id = cloud.runtime.submit("blue square", {}, "user")
    await cloud.worker.apply_decision(task_id, "accept", decided_by="test owner")
    item_id = "a" * 32
    root = cloud.root / "media" / "generated"
    root.mkdir(parents=True)
    sidecar = root / (item_id + ".sha256.json")
    sidecar.write_bytes(b"preexisting")
    real_save = comfyui.save_artifact

    def forced_id_save(*args, **kwargs):
        # Queue/worker identities still need real UUIDs during the tick.
        with monkeypatch.context() as scoped:
            scoped.setattr(comfyui.uuid, "uuid4", lambda: SimpleNamespace(hex=item_id))
            return real_save(*args, **kwargs)

    monkeypatch.setattr(cloud_image_runtime, "save_artifact", forced_id_save)
    await cloud.worker.tick()
    task = cloud.queue.get(task_id)
    assert task.result["status"] == "unknown"
    assert sidecar.read_bytes() == b"preexisting"
    assert set(root.iterdir()) == {sidecar}
    assert not cloud.runtime._path(task, "complete").exists()
    assert len(cloud.requests) == 1
