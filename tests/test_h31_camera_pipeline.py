"""H31.3 — deterministic rules plus an on-demand, strict-local VLM seam."""

from __future__ import annotations

import io
from dataclasses import fields

import pytest
from PIL import Image

from agents.core.cameras.models import (
    CameraConfig,
    CameraEvent,
    HouseholdConsent,
    MaskedFrame,
    PrivacyMask,
)
from agents.core.cameras.pipeline import CameraPipeline
from agents.core.cameras.privacy import CameraPrivacyError, CameraPrivacyPolicy
from agents.core.cameras.rules import CameraRuleEngine, CameraZone, LineRule
from agents.core.cameras.vlm import LocalCameraVLM, LocalCameraVLMConfig


class _KillSwitch:
    def __init__(self) -> None:
        self.halted: set[str] = set()

    def is_halted(self, scope: str = "global") -> bool:
        return "global" in self.halted or scope in self.halted


class _SnapshotSource:
    def __init__(self, frame: MaskedFrame) -> None:
        self.frame = frame
        self.calls: list[tuple[str, str]] = []

    async def fetch_masked(self, lease, event_id: str) -> MaskedFrame:
        self.calls.append((lease.camera_id, event_id))
        return self.frame


def _event(
    event_id: str = "event-1",
    *,
    occurred_at: float = 100.0,
    label: str = "person",
    camera_id: str = "front-door",
) -> CameraEvent:
    return CameraEvent(
        event_id=event_id,
        camera_id=camera_id,
        label=label,
        occurred_at=occurred_at,
        confidence=0.91,
    )


def _frame(*, size: tuple[int, int] = (8, 8)) -> MaskedFrame:
    image = Image.new("RGB", size, (30, 80, 120))
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    return MaskedFrame(data=output.getvalue(), format="PNG", width=size[0], height=size[1])


def _policy(*, kill: _KillSwitch | None = None) -> CameraPrivacyPolicy:
    mask = PrivacyMask(points=((0.0, 0.0), (0.2, 0.0), (0.2, 1.0), (0.0, 1.0)))
    return CameraPrivacyPolicy(
        configs=(
            CameraConfig(
                camera_id="front-door",
                name="Front door",
                enabled=True,
                required_consent_version=2,
                masks=(mask,),
            ),
        ),
        consent=HouseholdConsent(
            version=2,
            generation=4,
            granted=True,
            camera_ids=("front-door",),
            accepted_at=1.0,
        ),
        kill_switch=kill or _KillSwitch(),
    )


def _engine() -> CameraRuleEngine:
    return CameraRuleEngine(
        zones=(
            CameraZone(
                camera_id="front-door",
                name="porch",
                points=((0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)),
            ),
        ),
        lines=(
            LineRule(
                camera_id="front-door",
                name="threshold",
                start=(0.5, 0.0),
                end=(0.5, 1.0),
            ),
        ),
        history_limit=8,
    )


def test_rules_are_deterministic_bounded_and_track_zone_and_line_crossing():
    engine = _engine()
    first = engine.evaluate(_event(), point=(0.25, 0.5))
    second = engine.evaluate(_event(occurred_at=101.0), point=(0.75, 0.5))
    duplicate = engine.evaluate(_event(occurred_at=101.0), point=(0.75, 0.5))

    assert first.zones == ("porch",)
    assert first.line_crossings == ()
    assert first.event.zone == "porch"
    assert first.qualifies is True
    assert second.zones == ()
    assert second.line_crossings == ("threshold",)
    assert second.qualifies is True
    assert duplicate.duplicate is True
    assert engine.history_size <= 8


def test_outside_configured_rules_is_filtered_without_mutating_the_event():
    engine = _engine()
    original = _event()
    result = engine.evaluate(original, point=(0.8, 0.5))
    assert result.qualifies is False
    assert result.event is original
    assert result.zones == ()
    assert result.line_crossings == ()


def test_crossing_the_infinite_line_outside_the_configured_segment_does_not_match():
    engine = CameraRuleEngine(
        lines=(
            LineRule(
                camera_id="front-door",
                name="short",
                start=(0.5, 0.25),
                end=(0.5, 0.75),
            ),
        )
    )
    engine.evaluate(_event(), point=(0.25, 0.9))
    result = engine.evaluate(_event(occurred_at=101.0), point=(0.75, 0.9))
    assert result.line_crossings == ()
    assert result.qualifies is False


def test_rules_are_scoped_to_their_explicit_camera():
    result = _engine().evaluate(_event(camera_id="garage"), point=(0.25, 0.5))
    assert result.zones == ()
    assert result.line_crossings == ()
    assert result.qualifies is True


@pytest.mark.asyncio
async def test_metadata_path_never_fetches_a_frame_or_calls_the_vlm():
    generated: list[dict] = []

    async def generate(**kwargs) -> str:
        generated.append(kwargs)
        return '{"description":"An anonymous person is at the door."}'

    source = _SnapshotSource(_frame())
    pipeline = CameraPipeline(
        rules=CameraRuleEngine(),
        privacy_policy=_policy(),
        snapshots=source,
        vlm=LocalCameraVLM(_vlm_config(), generate=generate),
    )
    result = await pipeline.process(_event(), describe=False)

    assert result.status == "metadata_only"
    assert result.event.description is None
    assert source.calls == []
    assert generated == []


def _vlm_config(**overrides) -> LocalCameraVLMConfig:
    values = {
        "endpoint": "http://127.0.0.1:8000/v1",
        "model": "qwen3-vl-local",
        "enabled": True,
    }
    values.update(overrides)
    return LocalCameraVLMConfig(**values)


@pytest.mark.asyncio
async def test_description_path_uses_one_masked_frame_and_returns_metadata_only():
    generated: list[dict] = []

    async def generate(**kwargs) -> str:
        generated.append(kwargs)
        assert kwargs["images"][0] == source.frame.data
        return '{"description":"An anonymous person left a package by the door."}'

    source = _SnapshotSource(_frame())
    pipeline = CameraPipeline(
        rules=CameraRuleEngine(),
        privacy_policy=_policy(),
        snapshots=source,
        vlm=LocalCameraVLM(_vlm_config(), generate=generate),
    )
    result = await pipeline.process(_event(), describe=True)

    assert result.status == "described"
    assert result.event.description == "An anonymous person left a package by the door."
    assert result.event.description_provenance == "local_vlm_on_demand"
    assert source.calls == [("front-door", "event-1")]
    assert len(generated) == 1
    assert "data" not in {field.name for field in fields(result)}
    assert source.frame.data not in repr(result).encode()


@pytest.mark.asyncio
async def test_private_snapshot_store_receives_only_masked_frame_and_returns_receipt_metadata():
    stored: list[tuple[CameraEvent, MaskedFrame]] = []

    async def generate(**_kwargs) -> str:
        return '{"description":"An anonymous person is at the door."}'

    class _Receipt:
        stored = True
        snapshot_stored = True

    async def store_masked(event: CameraEvent, frame: MaskedFrame):
        stored.append((event, frame))
        return _Receipt()

    source = _SnapshotSource(_frame())
    result = await CameraPipeline(
        rules=CameraRuleEngine(),
        privacy_policy=_policy(),
        snapshots=source,
        vlm=LocalCameraVLM(_vlm_config(), generate=generate),
        store_masked=store_masked,
    ).process(_event(), describe=True)

    assert result.status == "described"
    assert result.event_stored is True
    assert result.snapshot_stored is True
    assert stored == [(result.event, source.frame)]
    assert "data" not in {field.name for field in fields(result)}
    assert source.frame.data not in repr(result).encode()


@pytest.mark.asyncio
async def test_vlm_endpoint_and_image_bounds_fail_before_generation():
    for endpoint in (
        "https://api.example.com/v1",
        "http://user:pass@127.0.0.1:8000/v1",
        "http://127.0.0.1:8000/v1?token=bad",
        "http://camera.local:8000/v1",
        "http://192.168.1.44:8000/v1",
    ):
        with pytest.raises(ValueError, match="local VLM endpoint"):
            _vlm_config(endpoint=endpoint)

    calls = 0

    async def generate(**_kwargs) -> str:
        nonlocal calls
        calls += 1
        return "should not run"

    vlm = LocalCameraVLM(_vlm_config(max_image_bytes=8), generate=generate)
    assert await vlm.describe(_frame(), _event()) is None
    assert calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    (
        '{"description":"Alice is at the door.","identity":"Alice"}',
        '{"description":"Alice is at the door."}',
        '{"description":"The license plate is B-00-BAD."}',
        "Alice appears to be the identified person at the door.",
        "[VLM error]",
        "",
    ),
)
async def test_identity_plate_and_error_outputs_are_refused_but_event_survives(response: str):
    async def generate(**_kwargs) -> str:
        return response

    source = _SnapshotSource(_frame())
    pipeline = CameraPipeline(
        rules=CameraRuleEngine(),
        privacy_policy=_policy(),
        snapshots=source,
        vlm=LocalCameraVLM(_vlm_config(), generate=generate),
    )
    result = await pipeline.process(_event(), describe=True)

    assert result.status == "description_unavailable"
    assert result.event.description is None
    assert result.event.to_public()["anonymous"] is True


@pytest.mark.asyncio
async def test_vlm_exception_is_bounded_and_does_not_destroy_deterministic_result():
    async def generate(**_kwargs) -> str:
        raise RuntimeError("backend leaked a private transport detail")

    result = await CameraPipeline(
        rules=CameraRuleEngine(),
        privacy_policy=_policy(),
        snapshots=_SnapshotSource(_frame()),
        vlm=LocalCameraVLM(_vlm_config(), generate=generate),
    ).process(_event(), describe=True)
    assert result.status == "description_unavailable"
    assert "private transport" not in repr(result)


@pytest.mark.asyncio
async def test_revoke_during_inference_discards_description_and_raises_privacy_error():
    policy = _policy()

    async def generate(**_kwargs) -> str:
        policy.revoke("owner revoked camera consent")
        return '{"description":"An anonymous person is at the door."}'

    pipeline = CameraPipeline(
        rules=CameraRuleEngine(),
        privacy_policy=policy,
        snapshots=_SnapshotSource(_frame()),
        vlm=LocalCameraVLM(_vlm_config(), generate=generate),
    )
    with pytest.raises(CameraPrivacyError, match="stale_consent_generation"):
        await pipeline.process(_event(), describe=True)


@pytest.mark.asyncio
async def test_exact_duplicate_never_triggers_a_second_snapshot_or_vlm_call():
    calls = 0

    async def generate(**_kwargs) -> str:
        nonlocal calls
        calls += 1
        return '{"description":"A package is by the door."}'

    source = _SnapshotSource(_frame())
    pipeline = CameraPipeline(
        rules=CameraRuleEngine(),
        privacy_policy=_policy(),
        snapshots=source,
        vlm=LocalCameraVLM(_vlm_config(), generate=generate),
    )
    first = await pipeline.process(_event(), describe=True)
    second = await pipeline.process(_event(), describe=True)

    assert first.status == "described"
    assert second.status == "duplicate"
    assert source.calls == [("front-door", "event-1")]
    assert calls == 1
