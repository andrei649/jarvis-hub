"""G12 (H560 / H614) — Nerva's OpenAI-compatible API.

Other chat apps (Open WebUI, LibreChat, LobeChat, the ``openai`` SDKs …) can use Nerva as
their backend: ``/v1/chat/completions``, ``/v1/responses`` and ``/v1/models`` start ordinary
Nerva turns. Off until the owner turns ``openai_api.enabled`` on; every request needs a key
the owner issued (``python -m agents.core.openai_api keys issue NAME [--owner]``).

- ``store``    — issued keys (hashes only), known conversations, stored responses
- ``policy``   — the owner's switch (managed-pinnable) and the per-key limits
- ``protocol`` — the OpenAI wire shapes (pure)
- ``turn``     — who the key makes the speaker, and the orchestrator turn itself
- ``cli``      — issue, list and revoke keys on the box

Routes: ``agents/core/routers/openai_compat.py``. Owner guide: ``docs/OPENAI_COMPATIBLE_API.md``.
"""
