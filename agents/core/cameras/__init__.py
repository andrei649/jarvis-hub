"""Local-only camera intelligence contracts.

H31 keeps camera sources behind a privacy boundary.  Importing this package
does not start discovery, polling, decoding, or inference.
"""

from .health import CameraHealthMonitor, CameraRetentionScheduler
from .models import (
    MAX_METADATA_TTL_SECONDS,
    MAX_SNAPSHOT_TTL_SECONDS,
    CameraConfig,
    CameraEvent,
    HouseholdConsent,
    MaskedFrame,
    PrivacyLease,
    PrivacyMask,
    PrivacyPollingGrant,
)
from .pipeline import CameraPipeline, CameraPipelineResult, SnapshotSource
from .privacy import CameraPrivacyError, CameraPrivacyPolicy, apply_masks
from .retrieval import CameraEventRetrieval, CameraFilter, CameraSearchError, CameraSearchResult
from .rules import CameraRuleEngine, CameraZone, LineRule, RuleOutcome
from .vault import (
    CameraEventVault,
    CameraPurgeReport,
    CameraStoreReceipt,
    CameraSweepReport,
    CameraVaultError,
)
from .vlm import LocalCameraVLM, LocalCameraVLMConfig

__all__ = [
    "MAX_METADATA_TTL_SECONDS",
    "MAX_SNAPSHOT_TTL_SECONDS",
    "CameraConfig",
    "CameraEvent",
    "CameraEventVault",
    "CameraEventRetrieval",
    "CameraFilter",
    "CameraHealthMonitor",
    "CameraPrivacyError",
    "CameraPrivacyPolicy",
    "CameraPurgeReport",
    "CameraPipeline",
    "CameraPipelineResult",
    "CameraRuleEngine",
    "CameraSearchError",
    "CameraSearchResult",
    "CameraRetentionScheduler",
    "CameraStoreReceipt",
    "CameraSweepReport",
    "CameraVaultError",
    "CameraZone",
    "HouseholdConsent",
    "MaskedFrame",
    "LineRule",
    "LocalCameraVLM",
    "LocalCameraVLMConfig",
    "PrivacyLease",
    "PrivacyMask",
    "PrivacyPollingGrant",
    "RuleOutcome",
    "SnapshotSource",
    "apply_masks",
]
