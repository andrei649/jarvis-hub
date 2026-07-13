"""House Brain contracts and strict-local adapters (ORIZONT 30)."""

from .contracts import HouseArea, HouseEntity, HouseEvent, HouseSnapshot
from .graph import HouseGraph
from .home_assistant import HAConfig, HAConfigError, HomeAssistantAdapter, load_ha_config
from .presence import (
    LocalPresenceExplainer,
    PresenceDecision,
    PresenceEvidence,
    PresenceInference,
    PresenceOutcome,
)
from .private_store import PrivateHouseStore, PrivateStoreError

__all__ = [
    "HAConfig",
    "HAConfigError",
    "HomeAssistantAdapter",
    "HouseArea",
    "HouseEntity",
    "HouseEvent",
    "HouseGraph",
    "HouseSnapshot",
    "LocalPresenceExplainer",
    "PresenceDecision",
    "PresenceEvidence",
    "PresenceInference",
    "PresenceOutcome",
    "PrivateHouseStore",
    "PrivateStoreError",
    "load_ha_config",
]
