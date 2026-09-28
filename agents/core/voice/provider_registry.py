"""Typed named speech providers; registration alone grants no command authority."""
from dataclasses import dataclass

from ..media_providers import ProviderBase, ProviderRegistry
from . import local_providers, provider_store


@dataclass(frozen=True)
class CommandProvider(ProviderBase):
    side: str
    provider_id: str
    provider_revision: int

    @property
    def name(self):
        return self.provider_id

    @property
    def kind(self):
        return self.side

    def get_setup_schema(self):
        return {"name": self.name, "badge": "approved-command",
                "tag": "Register through owner-approved Voice command settings.", "env_vars": []}

    def is_available(self):
        return local_providers.command_ready(
            self.side, provider_id=self.provider_id, verify_content=False,
        ).ok

    async def synthesize(self, text, language, *, temp_dir, default_lang="en"):
        if self.side != "tts":
            return None
        return await local_providers.speak_command(
            text, language, temp_dir=temp_dir, default_lang=default_lang, provider_id=self.provider_id,
        )

    async def transcribe(self, audio, language, *, temp_dir, default_lang="en"):
        if self.side != "stt":
            return "[STT unavailable]"
        return await local_providers.transcribe_command(
            audio, language, temp_dir=temp_dir, default_lang=default_lang, provider_id=self.provider_id,
        )


def speech_registry(kind=None):
    """Fresh read-only registration view; no model loads, subprocesses or probes."""
    sides = (kind,) if kind is not None else local_providers.SIDES
    providers = []
    for side in sides:
        if side not in local_providers.SIDES:
            continue
        for value in provider_store.list_records(side):
            providers.append(CommandProvider(side, value["provider_id"], value["provider_revision"]))
    return ProviderRegistry(providers)
