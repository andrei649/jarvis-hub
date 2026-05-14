"""
Plugin Base — Abstract base for all Jarvis Hub plugins.
"""

from abc import ABC, abstractmethod
from typing import Optional


class PluginBase(ABC):
    @abstractmethod
    async def start(self, **kwargs) -> bool:
        ...

    @abstractmethod
    async def stop(self):
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__
