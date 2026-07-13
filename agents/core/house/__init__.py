"""House Brain contracts and strict-local adapters (ORIZONT 30)."""

from .contracts import HouseArea, HouseEntity, HouseEvent, HouseSnapshot
from .home_assistant import HAConfig, HAConfigError, HomeAssistantAdapter, load_ha_config

__all__ = [
    "HAConfig",
    "HAConfigError",
    "HomeAssistantAdapter",
    "HouseArea",
    "HouseEntity",
    "HouseEvent",
    "HouseSnapshot",
    "load_ha_config",
]
