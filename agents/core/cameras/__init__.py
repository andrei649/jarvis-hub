"""Local-only camera intelligence contracts.

H31 keeps camera sources behind a privacy boundary.  Importing this package
does not start discovery, polling, decoding, or inference.
"""

from .models import (
    MAX_METADATA_TTL_SECONDS,
    MAX_SNAPSHOT_TTL_SECONDS,
    CameraConfig,
    CameraEvent,
    HouseholdConsent,
    MaskedFrame,
    PrivacyLease,
    PrivacyMask,
)
from .privacy import CameraPrivacyError, CameraPrivacyPolicy, apply_masks

__all__ = [
    "MAX_METADATA_TTL_SECONDS",
    "MAX_SNAPSHOT_TTL_SECONDS",
    "CameraConfig",
    "CameraEvent",
    "CameraPrivacyError",
    "CameraPrivacyPolicy",
    "HouseholdConsent",
    "MaskedFrame",
    "PrivacyLease",
    "PrivacyMask",
    "apply_masks",
]
