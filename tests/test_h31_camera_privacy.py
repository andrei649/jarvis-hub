"""H31.1 — camera privacy is the prerequisite for every frame operation."""

from __future__ import annotations

import hashlib
import io
from dataclasses import FrozenInstanceError

import pytest
from PIL import Image, PngImagePlugin

from agents.core.cameras.models import (
    MAX_METADATA_TTL_SECONDS,
    MAX_SNAPSHOT_TTL_SECONDS,
    CameraConfig,
    CameraEvent,
    HouseholdConsent,
    PrivacyMask,
)
from agents.core.cameras.privacy import (
    CameraPrivacyError,
    CameraPrivacyPolicy,
    apply_masks,
)


class _KillSwitch:
    def __init__(self) -> None:
        self.halted: set[str] = set()

    def is_halted(self, scope: str = "global") -> bool:
        return "global" in self.halted or scope in self.halted


def _mask() -> PrivacyMask:
    return PrivacyMask(points=((0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)))


def _config(**overrides) -> CameraConfig:
    values = {
        "camera_id": "front-door",
        "name": "Front door",
        "enabled": True,
        "required_consent_version": 2,
        "masks": (_mask(),),
        "snapshot_ttl_seconds": MAX_SNAPSHOT_TTL_SECONDS,
        "metadata_ttl_seconds": MAX_METADATA_TTL_SECONDS,
    }
    values.update(overrides)
    return CameraConfig(**values)


def _consent(**overrides) -> HouseholdConsent:
    values = {
        "version": 2,
        "generation": 7,
        "granted": True,
        "camera_ids": ("front-door",),
        "accepted_at": 100.0,
    }
    values.update(overrides)
    return HouseholdConsent(**values)


def _png(*, size=(8, 8), color=(240, 20, 30), metadata=True) -> bytes:
    image = Image.new("RGB", size, color)
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text("GPS", "44.4268,26.1025")
        info.add_text("raw-owner", "Alice Example")
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=info)
    image.close()
    return output.getvalue()


def _policy(*, config=None, consent=None, kill=None, callbacks=None) -> CameraPrivacyPolicy:
    callbacks = callbacks or {}
    return CameraPrivacyPolicy(
        configs=(config or _config(),),
        consent=consent,
        kill_switch=kill or _KillSwitch(),
        stop_polling=callbacks.get("stop_polling"),
        detach_publishers=callbacks.get("detach_publishers"),
        purge_records=callbacks.get("purge_records"),
    )


def test_camera_contracts_are_immutable_bounded_and_default_off():
    config = CameraConfig(camera_id="front-door", name="Front door")
    assert config.enabled is False
    assert config.masks == ()
    assert config.snapshot_ttl_seconds <= MAX_SNAPSHOT_TTL_SECONDS
    assert config.metadata_ttl_seconds <= MAX_METADATA_TTL_SECONDS
    with pytest.raises(FrozenInstanceError):
        config.enabled = True

    with pytest.raises(ValueError, match="snapshot retention"):
        _config(snapshot_ttl_seconds=MAX_SNAPSHOT_TTL_SECONDS + 1)
    with pytest.raises(ValueError, match="metadata retention"):
        _config(metadata_ttl_seconds=MAX_METADATA_TTL_SECONDS + 1)
    with pytest.raises(ValueError, match="camera_id"):
        _config(camera_id="../secret")


@pytest.mark.parametrize(
    ("consent", "reason"),
    [
        (None, "consent_required"),
        (_consent(granted=False), "consent_required"),
        (_consent(version=1), "consent_version_mismatch"),
        (_consent(camera_ids=("garage",)), "camera_not_consented"),
    ],
)
def test_begin_requires_exact_versioned_household_consent(consent, reason):
    policy = _policy(consent=consent)
    with pytest.raises(CameraPrivacyError, match=reason):
        policy.begin("front-door")


def test_disabled_and_killed_cameras_fail_before_fetch():
    with pytest.raises(CameraPrivacyError, match="camera_disabled"):
        _policy(config=_config(enabled=False), consent=_consent()).begin("front-door")

    kill = _KillSwitch()
    policy = _policy(consent=_consent(), kill=kill)
    kill.halted.add("camera:front-door")
    with pytest.raises(CameraPrivacyError, match="camera_halted"):
        policy.begin("front-door")
    kill.halted.clear()
    kill.halted.add("global")
    with pytest.raises(CameraPrivacyError, match="camera_halted"):
        policy.begin("front-door")


def test_missing_invalid_and_out_of_bounds_masks_are_refused():
    policy = _policy(config=_config(masks=()), consent=_consent())
    lease = policy.begin("front-door")
    with pytest.raises(CameraPrivacyError, match="privacy_mask_required"):
        policy.mask_frame(lease, _png())

    with pytest.raises(ValueError, match="normalized"):
        PrivacyMask(points=((-0.1, 0.0), (0.5, 0.0), (0.5, 0.5)))
    with pytest.raises(ValueError, match="area"):
        PrivacyMask(points=((0.0, 0.0), (0.1, 0.1), (0.2, 0.2)))
    with pytest.raises(ValueError, match="simple"):
        PrivacyMask(points=((0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.75, 0.0)))


def test_masking_is_pixel_complete_lossless_and_strips_all_input_metadata():
    raw = _png()
    raw_before = bytes(raw)
    raw_digest = hashlib.sha256(raw).hexdigest()
    policy = _policy(consent=_consent())
    lease = policy.begin("front-door")
    masked = policy.mask_frame(lease, raw)

    assert raw == raw_before
    assert masked.data is not raw
    assert masked.format == "PNG"
    assert raw_digest not in repr(masked)
    assert raw_digest not in str(masked.public_metadata())

    with Image.open(io.BytesIO(masked.data)) as image:
        assert image.info == {}
        assert image.getexif() == {}
        pixels = image.convert("RGB")
        for y in range(pixels.height):
            for x in range(pixels.width // 2):
                assert pixels.getpixel((x, y)) == (0, 0, 0)
        assert pixels.getpixel((pixels.width - 1, pixels.height - 1)) == (240, 20, 30)


def test_transform_rejects_animated_malformed_truncated_unsafe_and_oversized_images():
    first = Image.new("RGB", (4, 4), "red")
    second = Image.new("RGB", (4, 4), "blue")
    animated = io.BytesIO()
    first.save(animated, format="GIF", save_all=True, append_images=[second])
    first.close()
    second.close()

    for payload, reason in (
        (animated.getvalue(), "animated"),
        (b"not-an-image", "decode"),
        (_png()[:20], "decode"),
    ):
        with pytest.raises(CameraPrivacyError, match=reason):
            apply_masks(payload, (_mask(),))

    palette = Image.new("P", (4, 4))
    palette_bytes = io.BytesIO()
    palette.save(palette_bytes, format="PNG")
    palette.close()
    with pytest.raises(CameraPrivacyError, match="mode"):
        apply_masks(palette_bytes.getvalue(), (_mask(),))

    with pytest.raises(CameraPrivacyError, match="dimensions"):
        apply_masks(_png(size=(4097, 1), metadata=False), (_mask(),))
    with pytest.raises(CameraPrivacyError, match="encoded input"):
        apply_masks(b"x" * 100, (_mask(),), max_input_bytes=64)
    with pytest.raises(CameraPrivacyError, match="encoded output"):
        apply_masks(_png(size=(64, 64), metadata=False), (_mask(),), max_output_bytes=32)


def test_camera_events_reject_identity_biometrics_plates_and_unbounded_classes():
    base = {
        "event_id": "event-1",
        "camera_id": "front-door",
        "label": "person",
        "occurred_at": 100.0,
        "confidence": 0.9,
    }
    event = CameraEvent.from_payload(base)
    assert event.label == "person"
    assert event.to_public()["anonymous"] is True

    for key in ("face", "identity", "person_name", "license_plate", "sub_label"):
        with pytest.raises(ValueError, match="sensitive camera field"):
            CameraEvent.from_payload({**base, key: "forbidden"})
    with pytest.raises(ValueError, match="event label"):
        CameraEvent.from_payload({**base, "label": "unknown-object"})


def test_revoke_orders_stop_detach_generation_and_purge_and_stales_every_lease():
    calls: list[tuple[str, int]] = []
    policy = _policy(
        consent=_consent(),
        callbacks={
            "stop_polling": lambda: calls.append(("stop", policy.generation)),
            "detach_publishers": lambda: calls.append(("detach", policy.generation)),
            "purge_records": lambda generation: calls.append(("purge", generation)),
        },
    )
    lease = policy.begin("front-door")
    old_generation = policy.generation

    result = policy.revoke("owner revoked camera consent")

    assert result["generation"] == old_generation + 1
    assert calls == [
        ("stop", old_generation),
        ("detach", old_generation),
        ("purge", old_generation + 1),
    ]
    with pytest.raises(CameraPrivacyError, match="stale_consent_generation"):
        policy.recheck(lease, "store")
    with pytest.raises(CameraPrivacyError, match="consent_required"):
        policy.begin("front-door")


def test_revoke_during_mask_discards_the_transformed_frame(monkeypatch):
    policy = _policy(consent=_consent())
    lease = policy.begin("front-door")
    transformed = apply_masks(_png(), (_mask(),))

    def _race(*_args, **_kwargs):
        policy.revoke("race")
        return transformed

    monkeypatch.setattr("agents.core.cameras.privacy.apply_masks", _race)
    with pytest.raises(CameraPrivacyError, match="stale_consent_generation"):
        policy.mask_frame(lease, _png())


def test_every_stage_rechecks_kill_and_consent_before_store_or_publish():
    kill = _KillSwitch()
    policy = _policy(consent=_consent(), kill=kill)
    lease = policy.begin("front-door")
    policy.recheck(lease, "fetch")
    kill.halted.add("camera:front-door")
    for stage in ("inference", "store", "publish"):
        with pytest.raises(CameraPrivacyError, match="camera_halted"):
            policy.recheck(lease, stage)
