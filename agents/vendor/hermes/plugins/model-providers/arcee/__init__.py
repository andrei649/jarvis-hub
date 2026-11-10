"""Arcee AI provider profile."""

from agents.vendor.hermes_compat.providers import register_provider
from agents.vendor.hermes.providers.base import ProviderProfile

arcee = ProviderProfile(
    name="arcee", aliases=("arcee-ai", "arceeai"), env_vars=("ARCEEAI_API_KEY",),
    base_url="https://api.arcee.ai/api/v1",
)

register_provider(arcee)
