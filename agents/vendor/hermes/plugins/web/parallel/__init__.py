"""Parallel.ai web search + extract plugin — bundled, auto-loaded; async-native ``extract``."""
from __future__ import annotations
from agents.vendor.hermes.plugins.web.parallel.provider import ParallelWebSearchProvider


def register(ctx) -> None:
    ctx.register_web_search_provider(ParallelWebSearchProvider())
