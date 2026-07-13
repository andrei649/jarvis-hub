"""H31.4 — encrypted camera event storage, mandatory retention, and safe health."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from agents.core.cameras.health import CameraHealthMonitor, CameraRetentionScheduler
from agents.core.cameras.models import CameraConfig, CameraEvent, MaskedFrame, PrivacyMask
from agents.core.cameras.source import CameraSourceHealth
from agents.core.cameras.vault import CameraEventVault, CameraVaultError
from agents.core.security.secret_broker import SecretBroker
from agents.core.vault import VaultError

_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


class _Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _broker(*, with_key: bool = True) -> SecretBroker:
    broker = SecretBroker()
    if with_key:
        broker.put("camera.vault_key", _KEY)
    return broker


def _config() -> CameraConfig:
    return CameraConfig(
        camera_id="front-door",
        name="Front Door",
        enabled=True,
        required_consent_version=2,
        masks=(
            PrivacyMask(points=((0.0, 0.0), (0.1, 0.0), (0.1, 1.0), (0.0, 1.0))),
        ),
        snapshot_ttl_seconds=10,
        metadata_ttl_seconds=20,
    )


def _event(event_id: str = "event-1", *, occurred_at: float = 100.0) -> CameraEvent:
    return CameraEvent(
        event_id=event_id,
        camera_id="front-door",
        label="person",
        occurred_at=occurred_at,
        confidence=0.91,
        zone="porch",
        description="An anonymous person left a package.",
        description_provenance="local_vlm_on_demand",
    )


def _frame() -> MaskedFrame:
    image = Image.new("RGB", (8, 8), (0, 20, 40))
    for x in range(2):
        for y in range(8):
            image.putpixel((x, y), (0, 0, 0))
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    return MaskedFrame(data=output.getvalue(), format="PNG", width=8, height=8)


def _vault(tmp_path, *, clock=None, **kwargs) -> CameraEventVault:
    return CameraEventVault(
        tmp_path / "camera-vault",
        configs=(_config(),),
        secret_broker=_broker(),
        clock=clock or _Clock(100.0),
        **kwargs,
    )


def test_vault_requires_a_managed_secret_handle_and_never_accepts_a_raw_key(tmp_path):
    with pytest.raises(CameraVaultError, match="vault_key_unavailable"):
        CameraEventVault(
            tmp_path / "missing",
            configs=(_config(),),
            secret_broker=_broker(with_key=False),
        )
    with pytest.raises(ValueError, match="SecretBroker reference"):
        CameraEventVault(
            tmp_path / "raw",
            configs=(_config(),),
            secret_broker=_broker(),
            key_ref=_KEY,
        )
    with pytest.raises(ValueError, match="SecretBroker reference"):
        CameraEventVault(
            tmp_path / "decorated",
            configs=(_config(),),
            secret_broker=_broker(),
            key_ref="prefix {{secret:camera.vault_key}}",
        )


def test_event_and_masked_snapshot_are_ciphertext_at_rest_and_public_reads_have_no_internal_ids(
    tmp_path,
):
    vault = _vault(tmp_path)
    receipt = vault.store(_event(), frame=_frame())
    assert receipt.stored is True
    assert receipt.snapshot_stored is True
    assert "id" not in repr(receipt).lower()

    disk = b"".join(path.read_bytes() for path in vault.root.rglob("*") if path.is_file())
    assert b"event-1" not in disk
    assert b"front-door" not in disk
    assert b"anonymous person" not in disk
    assert _frame().data not in disk

    events = vault.list_events(now=100.0)
    assert events == (_event(),)
    projection = json.dumps(events[0].to_public()).lower()
    assert all(term not in projection for term in ("vault", ".blob", "path", "snapshot_ref"))
    restored = vault._load_masked_snapshot("front-door", "event-1", now=100.0)
    assert restored is not None
    assert restored.public_metadata()["format"] == "PNG"
    assert restored.public_metadata()["width"] == 8


def test_vault_reapplies_masks_instead_of_trusting_a_forged_masked_frame(tmp_path):
    image = Image.new("RGB", (8, 8), (200, 40, 20))
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    forged = MaskedFrame(data=output.getvalue(), format="PNG", width=8, height=8)
    vault = _vault(tmp_path)
    vault.store(_event(), frame=forged)

    restored = vault._load_masked_snapshot("front-door", "event-1", now=100.0)
    assert restored is not None
    with Image.open(io.BytesIO(restored.data)) as decoded:
        decoded.load()
        assert decoded.getpixel((0, 4)) == (0, 0, 0)
        assert decoded.getpixel((7, 4)) == (200, 40, 20)


def test_snapshot_and_metadata_expire_at_exact_mandatory_boundaries(tmp_path):
    vault = _vault(tmp_path)
    vault.store(_event(), frame=_frame())

    assert vault._load_masked_snapshot("front-door", "event-1", now=109.999) is not None
    assert vault._load_masked_snapshot("front-door", "event-1", now=110.0) is None
    assert vault.list_events(now=119.999) == (_event(),)
    assert vault.list_events(now=120.0) == ()
    assert vault.health()["items"] == 0


def test_retention_runs_on_reads_and_restart_even_when_general_retention_is_disabled(tmp_path):
    clock = _Clock(100.0)
    vault = _vault(tmp_path, clock=clock)
    vault.store(_event(), frame=_frame())
    assert len(list(vault.root.glob("*.blob"))) == 2

    clock.value = 121.0
    reopened = _vault(tmp_path, clock=clock)
    assert reopened.list_events() == ()
    assert list(reopened.root.glob("*.blob")) == []


def test_duplicate_store_is_idempotent_and_does_not_extend_retention(tmp_path):
    vault = _vault(tmp_path)
    first = vault.store(_event(), frame=_frame())
    duplicate = vault.store(_event(), frame=_frame())
    assert first.stored is True
    assert duplicate.stored is False
    assert duplicate.snapshot_stored is False
    assert vault.health()["items"] == 2
    assert vault.list_events(now=120.0) == ()


def test_failed_metadata_write_rolls_back_snapshot_and_quotas_never_evict(tmp_path):
    vault = _vault(tmp_path, max_items=1)
    with pytest.raises(CameraVaultError, match="store_failed"):
        vault.store(_event(), frame=_frame())
    assert vault.health()["items"] == 0
    assert list(vault.root.glob("*.blob")) == []

    bounded = _vault(tmp_path / "bounded", max_total_bytes=100)
    with pytest.raises(CameraVaultError, match="store_failed"):
        bounded.store(_event(), frame=_frame())
    assert bounded.health()["items"] == 0


def test_corruption_and_tampering_fail_closed_without_returning_partial_events(tmp_path):
    vault = _vault(tmp_path)
    vault.store(_event())
    blob = next(vault.root.glob("*.blob"))
    raw = blob.read_bytes()
    blob.write_bytes(raw[: len(raw) // 2] + b"tampered")

    with pytest.raises(CameraVaultError, match="vault_unavailable"):
        vault.list_events(now=101.0)


def test_sweep_removes_orphan_snapshots_and_purge_removes_every_camera_blob(tmp_path):
    vault = _vault(tmp_path)
    vault.store(_event(), frame=_frame())
    vault._vault.put(
        _frame().data,
        name="camera-snapshot",
        kind="camera-snapshot-v1",
        now=100.0,
        expires_at=109.0,
    )
    assert vault.health()["items"] == 3

    swept = vault.sweep(now=100.0)
    assert swept.removed_orphans == 1
    assert vault.health()["items"] == 2
    purged = vault.purge()
    assert purged.removed == 2
    assert vault.health()["items"] == 0
    assert list(vault.root.glob("*.blob")) == []


def test_invalid_frame_never_reaches_the_underlying_vault(tmp_path):
    vault = _vault(tmp_path)
    invalid = MaskedFrame(data=b"not-a-png", format="PNG", width=8, height=8)
    with pytest.raises(CameraVaultError, match="masked_snapshot_invalid"):
        vault.store(_event(), frame=invalid)
    assert vault.health()["items"] == 0


@pytest.mark.parametrize(
    "event",
    (
        CameraEvent(
            event_id="unsafe-name",
            camera_id="front-door",
            label="person",
            occurred_at=100.0,
            confidence=0.9,
            description="Alice is at the door.",
            description_provenance="local_vlm_on_demand",
        ),
        CameraEvent(
            event_id="unsafe-source",
            camera_id="front-door",
            label="person",
            occurred_at=100.0,
            confidence=0.9,
            description="An anonymous person is at the door.",
            description_provenance="cloud_vlm",
        ),
    ),
)
def test_forged_identity_or_nonlocal_description_is_refused_before_storage(tmp_path, event):
    vault = _vault(tmp_path)
    with pytest.raises(CameraVaultError, match="camera_event_unsafe"):
        vault.store(event)
    assert vault.health()["items"] == 0


def test_retention_scheduler_is_bounded_and_catches_up_once_after_delay(tmp_path):
    clock = _Clock(100.0)
    vault = _vault(tmp_path, clock=clock)
    vault.store(_event(), frame=_frame())
    scheduler = CameraRetentionScheduler(vault=vault, clock=clock, interval_seconds=5)
    assert scheduler.run_due() is None

    clock.value = 200.0
    report = scheduler.run_due()
    assert report is not None
    assert report.removed_metadata == 1
    assert scheduler.run_due() is None
    assert scheduler.to_public() == {"status": "scheduled", "next_sweep_at": 205.0}


class _Source:
    def health(self) -> CameraSourceHealth:
        return CameraSourceHealth(
            status="offline",
            camera_count=1,
            last_success_at="http://private-host/last-success",
            last_error="http://user:secret@192.168.1.2/private",
        )


def test_health_is_metadata_only_bounded_and_redacts_transport_details(tmp_path):
    vault = _vault(tmp_path)
    vault.store(_event())
    public = CameraHealthMonitor(source=_Source(), vault=vault).snapshot()
    encoded = json.dumps(public).lower()
    assert public["status"] == "degraded"
    assert public["source"]["last_error"] == "source_error"
    assert public["source"]["last_success_at"] is None
    assert public["storage"]["items"] == 1
    assert all(term not in encoded for term in ("secret", "192.168", "http", ".blob", str(tmp_path)))


def test_underlying_vault_errors_are_not_exposed_in_public_health(tmp_path, monkeypatch):
    vault = _vault(tmp_path)

    def broken():
        raise VaultError("C:/private/path/index.enc corrupt")

    monkeypatch.setattr(vault._vault, "stats", broken)
    assert vault.health() == {
        "status": "unavailable",
        "items": 0,
        "bytes": 0,
        "last_sweep_at": 100.0,
    }
