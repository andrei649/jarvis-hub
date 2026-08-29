"""House Brain contracts and strict-local adapters (ORIZONT 30)."""

from .actuation import (
    HOUSE_CONTROL_KIND,
    HOUSE_RECOVERY_KIND,
    HOUSE_SECURITY_KIND,
    HomeAssistantServiceDriver,
    HouseActuationError,
    HouseActuator,
    register_house_handlers,
)
from .camera_feed import HouseCameraFeedConsumer
from .confirmation import ConfirmationError, StrongConfirmationStore
from .contracts import HouseArea, HouseEntity, HouseEvent, HouseSnapshot
from .graph import HouseGraph
from .home_assistant import HAConfig, HAConfigError, HomeAssistantAdapter, load_ha_config
from .ingest import HousePresenceIngestor
from .presence import (
    LocalPresenceExplainer,
    PresenceDecision,
    PresenceEvidence,
    PresenceInference,
    PresenceOutcome,
)
from .private_store import PrivateHouseStore, PrivateStoreError

__all__ = [
    "ConfirmationError",
    "HAConfig",
    "HAConfigError",
    "HOUSE_CONTROL_KIND",
    "HOUSE_RECOVERY_KIND",
    "HOUSE_SECURITY_KIND",
    "HomeAssistantAdapter",
    "HomeAssistantServiceDriver",
    "HouseArea",
    "HouseCameraFeedConsumer",
    "HouseEntity",
    "HouseEvent",
    "HouseGraph",
    "HouseSnapshot",
    "HouseActuator",
    "HouseActuationError",
    "LocalPresenceExplainer",
    "PresenceDecision",
    "PresenceEvidence",
    "HousePresenceIngestor",
    "PresenceInference",
    "PresenceOutcome",
    "PrivateHouseStore",
    "PrivateStoreError",
    "StrongConfirmationStore",
    "load_ha_config",
    "register_house_handlers",
]
