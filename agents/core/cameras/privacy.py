"""Fail-closed camera consent and in-memory privacy-mask enforcement."""

from __future__ import annotations

import io
import threading
import warnings
from collections.abc import Callable, Sequence
from typing import Any

from PIL import Image, ImageDraw, ImageFile, UnidentifiedImageError

from .models import (
    CameraConfig,
    HouseholdConsent,
    MaskedFrame,
    PrivacyLease,
    PrivacyMask,
    PrivacyPollingGrant,
)

_ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
_ALLOWED_IMAGE_MODES = frozenset({"L", "LA", "RGB", "RGBA"})
_ALLOWED_STAGES = frozenset({"fetch", "inference", "mask", "publish", "store"})
_DEFAULT_MAX_INPUT_BYTES = 8 * 1024 * 1024
_DEFAULT_MAX_OUTPUT_BYTES = 5 * 1024 * 1024
_DEFAULT_MAX_DIMENSION = 4096
_DEFAULT_MAX_PIXELS = 12_000_000
_DECODE_LOCK = threading.Lock()


class CameraPrivacyError(RuntimeError):
    """A stable, non-sensitive refusal at the camera privacy boundary."""


def _validate_limit(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _open_verified_image(
    encoded: bytes,
    *,
    max_dimension: int,
    max_pixels: int,
) -> Image.Image:
    """Decode completely in memory, rejecting animation, truncation, and unsafe modes."""

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(encoded)) as probe:
                if int(getattr(probe, "n_frames", 1)) != 1:
                    raise CameraPrivacyError("animated_image_refused")
                if probe.format not in _ALLOWED_IMAGE_FORMATS:
                    raise CameraPrivacyError("image_format_not_allowed")
                if probe.mode not in _ALLOWED_IMAGE_MODES:
                    raise CameraPrivacyError("image_mode_not_allowed")
                width, height = probe.size
                if (
                    width < 1
                    or height < 1
                    or width > max_dimension
                    or height > max_dimension
                    or width * height > max_pixels
                ):
                    raise CameraPrivacyError("image_dimensions_exceeded")
                probe.verify()

            with Image.open(io.BytesIO(encoded)) as decoded:
                if int(getattr(decoded, "n_frames", 1)) != 1:
                    raise CameraPrivacyError("animated_image_refused")
                if decoded.format not in _ALLOWED_IMAGE_FORMATS:
                    raise CameraPrivacyError("image_format_not_allowed")
                if decoded.mode not in _ALLOWED_IMAGE_MODES:
                    raise CameraPrivacyError("image_mode_not_allowed")
                decoded.load()
                return decoded.convert("RGB")
    except CameraPrivacyError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise CameraPrivacyError("image_dimensions_exceeded") from exc
    except (OSError, SyntaxError, UnidentifiedImageError, ValueError) as exc:
        raise CameraPrivacyError("image_decode_failed") from exc


def _rasterize_masks(
    masks: Sequence[PrivacyMask],
    *,
    width: int,
    height: int,
) -> Image.Image:
    coverage = Image.new("L", (width, height), 0)
    drawer = ImageDraw.Draw(coverage)
    for mask in masks:
        points = [
            (round(x * (width - 1)), round(y * (height - 1))) for x, y in mask.points
        ]
        drawer.polygon(points, fill=255)
    return coverage


def _prove_output(
    encoded: bytes,
    *,
    coverage: Image.Image,
    width: int,
    height: int,
) -> None:
    try:
        with Image.open(io.BytesIO(encoded)) as proof:
            proof.load()
            if proof.format != "PNG" or proof.size != (width, height):
                raise CameraPrivacyError("privacy_mask_verification_failed")
            if proof.info or proof.getexif():
                raise CameraPrivacyError("privacy_metadata_strip_failed")
            rgb = proof.convert("RGB")
            try:
                mask_pixels = _flattened_pixels(coverage)
                output_pixels = _flattened_pixels(rgb)
                if any(
                    mask_value and pixel != (0, 0, 0)
                    for mask_value, pixel in zip(mask_pixels, output_pixels, strict=True)
                ):
                    raise CameraPrivacyError("privacy_mask_verification_failed")
            finally:
                rgb.close()
    except CameraPrivacyError:
        raise
    except (OSError, SyntaxError, UnidentifiedImageError, ValueError) as exc:
        raise CameraPrivacyError("privacy_mask_verification_failed") from exc


def _flattened_pixels(image: Image.Image) -> Any:
    """Use Pillow's warning-free API while retaining the supported 11.x fallback."""

    getter = getattr(image, "get_flattened_data", None)
    return getter() if getter is not None else image.getdata()


def apply_masks(
    raw: bytes | bytearray | memoryview,
    masks: Sequence[PrivacyMask],
    *,
    max_input_bytes: int = _DEFAULT_MAX_INPUT_BYTES,
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
    max_dimension: int = _DEFAULT_MAX_DIMENSION,
    max_pixels: int = _DEFAULT_MAX_PIXELS,
) -> MaskedFrame:
    """Return a new metadata-free PNG after proving every mask pixel is black."""

    max_input_bytes = _validate_limit(max_input_bytes, "max_input_bytes")
    max_output_bytes = _validate_limit(max_output_bytes, "max_output_bytes")
    max_dimension = _validate_limit(max_dimension, "max_dimension")
    max_pixels = _validate_limit(max_pixels, "max_pixels")
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise CameraPrivacyError("encoded input must be bytes")
    encoded = bytes(raw)
    if not encoded or len(encoded) > max_input_bytes:
        raise CameraPrivacyError("encoded input exceeds limit")
    if not isinstance(masks, Sequence) or isinstance(masks, (str, bytes)) or not masks:
        raise CameraPrivacyError("privacy_mask_required")
    if len(masks) > 16 or any(not isinstance(mask, PrivacyMask) for mask in masks):
        raise CameraPrivacyError("privacy_mask_invalid")

    image: Image.Image | None = None
    coverage: Image.Image | None = None
    try:
        # Pillow's truncated-image switch is process-global. Serialize the bounded decode so
        # concurrent camera work cannot observe our temporary fail-closed setting.
        with _DECODE_LOCK:
            previous_truncated_setting = ImageFile.LOAD_TRUNCATED_IMAGES
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            try:
                image = _open_verified_image(
                    encoded,
                    max_dimension=max_dimension,
                    max_pixels=max_pixels,
                )
            finally:
                ImageFile.LOAD_TRUNCATED_IMAGES = previous_truncated_setting
        width, height = image.size
        coverage = _rasterize_masks(masks, width=width, height=height)
        image.paste((0, 0, 0), box=(0, 0, width, height), mask=coverage)

        output = io.BytesIO()
        image.save(output, format="PNG", optimize=False, compress_level=9)
        sanitized = output.getvalue()
        output.close()
        if len(sanitized) > max_output_bytes:
            raise CameraPrivacyError("encoded output exceeds limit")
        _prove_output(
            sanitized,
            coverage=coverage,
            width=width,
            height=height,
        )
        return MaskedFrame(data=sanitized, width=width, height=height)
    finally:
        if coverage is not None:
            coverage.close()
        if image is not None:
            image.close()


class CameraPrivacyPolicy:
    """Checks consent and kill state at every stage of a camera operation."""

    def __init__(
        self,
        *,
        configs: Sequence[CameraConfig],
        consent: HouseholdConsent | None,
        kill_switch: Any,
        stop_polling: Callable[[], None] | None = None,
        detach_publishers: Callable[[], None] | None = None,
        purge_records: Callable[[int], None] | None = None,
    ) -> None:
        if not isinstance(configs, Sequence) or not configs or len(configs) > 128:
            raise ValueError("camera configs must be a non-empty bounded collection")
        config_map: dict[str, CameraConfig] = {}
        for config in configs:
            if not isinstance(config, CameraConfig):
                raise ValueError("camera configs must contain CameraConfig values")
            if config.camera_id in config_map:
                raise ValueError("camera ids must be unique")
            config_map[config.camera_id] = config
        if consent is not None and not isinstance(consent, HouseholdConsent):
            raise ValueError("consent must be a HouseholdConsent value")
        if not callable(getattr(kill_switch, "is_halted", None)):
            raise ValueError("kill_switch must provide is_halted")
        callbacks = (stop_polling, detach_publishers, purge_records)
        if any(callback is not None and not callable(callback) for callback in callbacks):
            raise ValueError("camera privacy callbacks must be callable")

        self._configs = config_map
        self._consent = consent
        self._generation = consent.generation if consent is not None else 0
        self._kill_switch = kill_switch
        self._stop_polling = stop_polling or (lambda: None)
        self._detach_publishers = detach_publishers or (lambda: None)
        self._purge_records = purge_records or (lambda _generation: None)
        self._lock = threading.RLock()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def begin(self, camera_id: str) -> PrivacyLease:
        with self._lock:
            config = self._require_config(camera_id)
            self._require_enabled_not_halted(config)
            consent = self._require_consent(config)
            return PrivacyLease(
                camera_id=config.camera_id,
                consent_version=consent.version,
                generation=self._generation,
            )

    def begin_polling(self) -> PrivacyPollingGrant:
        """Mint a metadata-poll allowlist bound to the current consent generation."""

        with self._lock:
            consent = self._consent
            if consent is None or not consent.granted:
                raise CameraPrivacyError("consent_required")
            candidates = [
                config
                for config in sorted(self._configs.values(), key=lambda item: item.camera_id)
                if config.enabled and config.camera_id in consent.camera_ids
            ]
            if not candidates:
                raise CameraPrivacyError("camera_not_consented")
            if any(config.required_consent_version != consent.version for config in candidates):
                raise CameraPrivacyError("consent_version_mismatch")
            camera_ids: list[str] = []
            for config in candidates:
                try:
                    halted = self._kill_switch.is_halted(f"camera:{config.camera_id}")
                except Exception as exc:
                    raise CameraPrivacyError("camera_halt_state_unavailable") from exc
                if not halted:
                    camera_ids.append(config.camera_id)
            if not camera_ids:
                raise CameraPrivacyError("camera_halted")
            return PrivacyPollingGrant(
                camera_ids=tuple(camera_ids),
                consent_version=consent.version,
                generation=self._generation,
            )

    def recheck_polling(self, grant: PrivacyPollingGrant) -> None:
        if not isinstance(grant, PrivacyPollingGrant):
            raise CameraPrivacyError("invalid_polling_grant")
        with self._lock:
            if grant.generation != self._generation:
                raise CameraPrivacyError("stale_consent_generation")
            if self.begin_polling() != grant:
                raise CameraPrivacyError("stale_consent_generation")

    def recheck(self, lease: PrivacyLease, stage: str) -> None:
        if not isinstance(lease, PrivacyLease):
            raise CameraPrivacyError("invalid_privacy_lease")
        if stage not in _ALLOWED_STAGES:
            raise ValueError("unknown camera privacy stage")
        with self._lock:
            config = self._require_config(lease.camera_id)
            if lease.generation != self._generation:
                raise CameraPrivacyError("stale_consent_generation")
            self._require_enabled_not_halted(config)
            consent = self._require_consent(config)
            if lease.consent_version != consent.version:
                raise CameraPrivacyError("stale_consent_generation")

    def mask_frame(
        self,
        lease: PrivacyLease,
        raw: bytes | bytearray | memoryview,
    ) -> MaskedFrame:
        self.recheck(lease, "mask")
        with self._lock:
            masks = self._configs[lease.camera_id].masks
        if not masks:
            raise CameraPrivacyError("privacy_mask_required")
        sanitized = apply_masks(raw, masks)
        self.recheck(lease, "mask")
        return sanitized

    def revoke(self, reason: str) -> dict[str, Any]:
        reason_text = str(reason).strip()[:256]
        failures: list[str] = []
        with self._lock:
            for name, callback in (
                ("stop_polling", self._stop_polling),
                ("detach_publishers", self._detach_publishers),
            ):
                try:
                    callback()
                except Exception:  # revocation must continue through every fail-closed step
                    failures.append(name)

            self._generation += 1
            self._consent = None
            try:
                self._purge_records(self._generation)
            except Exception:  # the caller receives an explicit incomplete-purge signal
                failures.append("purge_records")
            return {
                "revoked": True,
                "generation": self._generation,
                "reason": reason_text,
                "callback_failures": failures,
                "purge_complete": "purge_records" not in failures,
            }

    def _require_config(self, camera_id: str) -> CameraConfig:
        config = self._configs.get(camera_id)
        if config is None:
            raise CameraPrivacyError("camera_unknown")
        return config

    def _require_enabled_not_halted(self, config: CameraConfig) -> None:
        if not config.enabled:
            raise CameraPrivacyError("camera_disabled")
        if self._kill_switch.is_halted(f"camera:{config.camera_id}"):
            raise CameraPrivacyError("camera_halted")

    def _require_consent(self, config: CameraConfig) -> HouseholdConsent:
        consent = self._consent
        if consent is None or not consent.granted:
            raise CameraPrivacyError("consent_required")
        if consent.version != config.required_consent_version:
            raise CameraPrivacyError("consent_version_mismatch")
        if config.camera_id not in consent.camera_ids:
            raise CameraPrivacyError("camera_not_consented")
        return consent
