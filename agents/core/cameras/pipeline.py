"""Privacy-bound orchestration for deterministic camera events and optional VLM text."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from .models import CameraEvent, MaskedFrame, PrivacyLease
from .privacy import CameraPrivacyError, CameraPrivacyPolicy
from .rules import CameraRuleEngine
from .vlm import LocalCameraVLM


class SnapshotSource(Protocol):
    """Private seam that may return only an already-masked, in-memory frame."""

    async def fetch_masked(self, lease: PrivacyLease, event_id: str) -> MaskedFrame: ...


@dataclass(frozen=True, slots=True)
class CameraPipelineResult:
    """Metadata-only pipeline output. Frame bytes have no result field."""

    event: CameraEvent
    zones: tuple[str, ...]
    line_crossings: tuple[str, ...]
    status: str


class CameraPipeline:
    """Run cheap rules first and touch one masked frame only when explicitly requested."""

    def __init__(
        self,
        *,
        rules: CameraRuleEngine,
        privacy_policy: CameraPrivacyPolicy,
        snapshots: SnapshotSource,
        vlm: LocalCameraVLM,
    ) -> None:
        if not isinstance(rules, CameraRuleEngine):
            raise ValueError("camera rules are required")
        if not isinstance(privacy_policy, CameraPrivacyPolicy):
            raise ValueError("camera privacy policy is required")
        if not callable(getattr(snapshots, "fetch_masked", None)):
            raise ValueError("masked camera snapshot source is required")
        if not isinstance(vlm, LocalCameraVLM):
            raise ValueError("local camera VLM is required")
        self._rules = rules
        self._privacy = privacy_policy
        self._snapshots = snapshots
        self._vlm = vlm

    async def process(
        self,
        event: CameraEvent,
        *,
        point: tuple[float, float] | None = None,
        describe: bool = False,
    ) -> CameraPipelineResult:
        if not isinstance(event, CameraEvent):
            raise ValueError("camera pipeline input must be a CameraEvent")
        if not isinstance(describe, bool):
            raise ValueError("camera describe flag must be a boolean")
        outcome = self._rules.evaluate(event, point=point)
        if outcome.duplicate:
            return self._result(outcome.event, outcome.zones, outcome.line_crossings, "duplicate")
        if not outcome.qualifies:
            return self._result(outcome.event, outcome.zones, outcome.line_crossings, "filtered")
        if not describe:
            return self._result(outcome.event, outcome.zones, outcome.line_crossings, "metadata_only")
        if not self._vlm.enabled:
            return self._result(
                outcome.event,
                outcome.zones,
                outcome.line_crossings,
                "description_unavailable",
            )

        lease = self._privacy.begin(outcome.event.camera_id)
        frame: MaskedFrame | None = None
        try:
            self._privacy.recheck(lease, "fetch")
            frame = await self._snapshots.fetch_masked(lease, outcome.event.event_id)
            self._privacy.recheck(lease, "inference")
            description = await self._vlm.describe(frame, outcome.event)
            self._privacy.recheck(lease, "inference")
        except CameraPrivacyError:
            raise
        except Exception:
            return self._result(
                outcome.event,
                outcome.zones,
                outcome.line_crossings,
                "description_unavailable",
            )
        finally:
            frame = None

        self._privacy.recheck(lease, "publish")
        if description is None:
            return self._result(
                outcome.event,
                outcome.zones,
                outcome.line_crossings,
                "description_unavailable",
            )
        described = replace(
            outcome.event,
            description=description,
            description_provenance="local_vlm_on_demand",
        )
        self._privacy.recheck(lease, "publish")
        return self._result(described, outcome.zones, outcome.line_crossings, "described")

    @staticmethod
    def _result(
        event: CameraEvent,
        zones: tuple[str, ...],
        line_crossings: tuple[str, ...],
        status: str,
    ) -> CameraPipelineResult:
        return CameraPipelineResult(
            event=event,
            zones=zones,
            line_crossings=line_crossings,
            status=status,
        )


__all__ = ["CameraPipeline", "CameraPipelineResult", "SnapshotSource"]
