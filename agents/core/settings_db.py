"""
settings_db.py — SQLite-backed settings store for the admin panel.
Seeds defaults from agents.yaml on first init.
"""

import json
import logging
import math
import re
import sqlite3
import threading
import time
from typing import Any

from agents.core.llm import provider_routing as _routing
from agents.core.llm.model_config import (
    DEFAULT_CLAUDE_MODEL,
    RETIRED_CLAUDE_DEFAULT,
)
from agents.core.llm.reasoning_effort import LADDER as REASONING_EFFORT_LADDER
from agents.core.paths import data_path

logger = logging.getLogger("jarvis.settings")


def _logsafe(value: object) -> str:
    """Neutralize newlines so untrusted values can't forge log records (CWE-117).

    The admin settings category + keys come straight from the request; a value
    containing CR/LF could otherwise inject fake log lines. Stripping the line
    breaks is the standard log-injection remediation.
    """
    return str(value).replace("\r", " ").replace("\n", " ")

DB_PATH = data_path("settings.db")

# ── secret-field encryption at rest (AUD-1 / F2) ──────────────────
# Credential-bearing settings must never sit in settings.db as plaintext. These
# keys are envelope-encrypted at the write boundary (put_category) and decrypted
# transparently on read (get_value / get_category / get_all), reusing the single
# key-managed cipher in agents.core.secrets (Fernet, or its pure-Python fallback
# when 'cryptography' is unavailable). The key lives outside settings.db.
SECRET_KEYS: frozenset[str] = frozenset({
    "twilio_auth_token",
    "notion_integration_token",
    "tuya_secret",
    "gecko_ing_client_secret",
    "gecko_libra_token",
    "stark_ga4_service_account",
})

_ENC_PREFIX = "enc::v1::"  # marks an encrypted settings value (always a JSON string)

_field_cipher = None
_field_cipher_lock = threading.Lock()


def _get_field_cipher():
    """Lazily build the shared at-rest cipher.

    Constructed only when a secret value is actually read or written, so the
    common case (no secrets set) never touches the secret store or its keyfile.
    """
    global _field_cipher
    if _field_cipher is None:
        with _field_cipher_lock:
            if _field_cipher is None:
                from agents.core.secrets import SecretStore
                # Re-resolve data_path at call time so $JARVIS_HOME is honored.
                _field_cipher = SecretStore(path=data_path("security", "secrets.enc"))
    return _field_cipher


def _encrypt_if_secret(key: str, value: Any) -> Any:
    """Encrypt secret-keyed, non-empty string values; pass everything else through.

    Idempotent: an already-encrypted token is returned unchanged. Fails closed —
    if encryption raises we refuse to fall back to storing plaintext.
    """
    if key in SECRET_KEYS and isinstance(value, str) and value:
        if value.startswith(_ENC_PREFIX):
            return value
        return _ENC_PREFIX + _get_field_cipher().encrypt_value(value)
    return value


def _decrypt_if_secret(value: Any) -> Any:
    """Decrypt an encrypted settings token; pass non-encrypted values through.

    On decrypt failure (e.g. a rotated/lost key) returns "" rather than leaking
    ciphertext or crashing the admin panel — the field then reads as unset.
    """
    if isinstance(value, str) and value.startswith(_ENC_PREFIX):
        try:
            return _get_field_cipher().decrypt_value(value[len(_ENC_PREFIX):])
        except Exception:
            logger.warning("Could not decrypt a secret setting (wrong/lost key); returning empty")
            return ""
    return value

# ── schema ────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    category TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL DEFAULT '""',
    label    TEXT NOT NULL DEFAULT '',
    kind     TEXT NOT NULL DEFAULT 'text',
    opts     TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (category, key)
);
CREATE TABLE IF NOT EXISTS settings_migrations (
    name       TEXT PRIMARY KEY,
    applied_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings_resets (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        REAL NOT NULL,
    scope     TEXT NOT NULL,
    before    TEXT NOT NULL,
    after     TEXT NOT NULL,
    undone_at REAL
);
"""

#: Shipped defaults a later build changed: (name, category, key, the old shipped value,
#: the new one). A store still holding the old value gets the new one the first time a
#: build that knows the change starts on it, once: ``settings_migrations`` records it,
#: so an owner who chooses the old value afterwards keeps it. A store holding anything
#: else is the owner's choice and is left alone.
_CHANGED_DEFAULTS: tuple[tuple[str, str, str, Any, Any], ...] = (
    # H315 review: the guest allowlist gained todo (a guest's own plan on its own chat).
    ("llm.guest_tools+todo", "llm", "guest_tools", ["echo", "time"], ["echo", "time", "todo"]),
)

# ── default settings — seed values ────────────────────────────────

DEFAULTS: list[dict[str, Any]] = [
    # H135: only explicit owner choices; empty preserves device motion defaults.
    dict(category="appearance", key="preferences", value={}, label="Appearance preferences", kind="json"),
    # general
    dict(category="general", key="timezone",         value="Europe/Bucharest",    label="Timezone",           kind="select",  opts=["Europe/Bucharest","UTC","US/Eastern"]),
    dict(category="general", key="wake_words",       value=["nerva","jarvis","hub"], label="Wake words",      kind="tags"),
    # product — owner-consented posture, default OFF. O26-P2.4 wave 1 wakes the
    # "knows you" stack only after the onboarding/product setting selects it.
    dict(category="product", key="posture", value="off", label="Product posture", kind="select", opts=["off", "companion_wave1", "design_partner"]),
    # llm
    dict(category="llm",     key="backend_type",     value="auto",                label="Backend type",       kind="select",  opts=["auto","lm-studio","ollama"]),
    dict(category="llm",     key="lm_studio_url",    value="http://localhost:1234",  label="LM Studio URL",    kind="text"),
    dict(category="llm",     key="ollama_url",       value="http://localhost:11434", label="Ollama URL",       kind="text"),
    dict(category="llm",     key="default_model",    value="google/gemma-4-12b",  label="Default local model", kind="model-select"),
    dict(category="llm",     key="temperature",      value=0.7,                   label="Temperature",        kind="slider"),
    dict(category="llm",     key="max_tokens",       value=0,                     label="Max tokens (0 = auto: use the model's loaded context)", kind="number"),
    dict(category="llm",     key="deep_max_tokens",  value=0,                     label="Deep-slot max tokens (0 = auto)", kind="number"),
    dict(category="llm",     key="cloud_fallback",   value="on-demand",           label="Cloud LLM fallback", kind="select",  opts=["never","on-demand","always"]),
    dict(category="llm",     key="gemini_model",     value="gemini-2.5-flash",     label="Gemini model",       kind="select",  opts=["gemini-2.5-flash","gemini-2.5-pro","gemini-3.1-pro"]),
    dict(category="llm",     key="claude_model",     value=DEFAULT_CLAUDE_MODEL,      label="Claude model",   kind="text"),
    # H364 — one ladder rung for cloud reasoning, clamped per model at send time.
    # "" (the default) asks for nothing, which is what every install did before.
    dict(category="llm",     key="reasoning_effort", value="",                    label="Cloud reasoning effort (empty = ask for nothing; clamped to what each model accepts)", kind="select", opts=["", *REASONING_EFFORT_LADDER]),
    dict(category="llm", key="ollama_num_ctx", value=0, label="Ollama context tokens (0 = probe model parameters)", kind="number"),
    dict(category="llm", key="gemini_effort_declarations", value="", label='Gemini effort vocabularies: JSON {"exact-model": ["low", "high"]}', kind="text"),
    dict(category="llm", key="compatible_provider", value="", label="Compatible cloud provider (empty = Gemini)", kind="select", opts=["", "openrouter", "openai-compatible", "openai-responses", "xai"]),
    # H583 — which upstream provider may serve an OpenRouter request (sent as its
    # `provider` object, to OpenRouter only). data_collection is a privacy control:
    # seeded "deny" so a cloud turn never lands on a provider that stores or trains
    # on prompts unless the owner opts in. Slug lists are validated on write.
    dict(category="llm", key="openrouter_sort", value="", label="OpenRouter: rank upstream providers by (empty = OpenRouter's own balance)", kind="select", opts=["", *_routing.SORTS]),
    dict(category="llm", key="openrouter_only", value=[], label="OpenRouter: only these upstream providers (slugs; empty = any)", kind="tags"),
    dict(category="llm", key="openrouter_ignore", value=[], label="OpenRouter: never these upstream providers (slugs)", kind="tags"),
    dict(category="llm", key="openrouter_order", value=[], label="OpenRouter: try these upstream providers first, the rest as fallbacks (slugs)", kind="tags"),
    dict(category="llm", key="openrouter_require_parameters", value=False, label="OpenRouter: refuse upstream providers that would drop a request parameter (tools, temperature)", kind="toggle"),
    dict(category="llm", key="openrouter_data_collection", value=_routing.DEFAULT_DATA_COLLECTION, label="OpenRouter: upstream providers that store or train on prompts (deny = never used)", kind="select", opts=list(_routing.DATA_COLLECTION)),
    dict(category="llm", key="responses_cache_retention", value="in_memory", label="OpenAI Responses GPT-4.1 cache retention", kind="select", opts=["in_memory", "24h"]),
    dict(category="llm", key="compatible_model", value="", label="Compatible provider model ID", kind="text"),
    dict(category="llm", key="compatible_prompt_cache_key", value=False, label="Compatible endpoint explicitly supports prompt_cache_key", kind="toggle"),
    dict(category="llm", key="compatible_reasoning_enabled", value=False, label="Compatible endpoint explicitly supports reasoning effort", kind="toggle"),
    dict(category="llm", key="compatible_effort_declarations", value="", label='Compatible effort vocabularies: JSON {"exact-model": ["low", "high"]}', kind="text"),
    dict(category="llm",     key="reasoning_effort_overrides", value="",          label="Reasoning-effort overrides — JSON {\"model-prefix\": [\"low\",\"high\"]}; an empty list silences the parameter for that model", kind="text"),
    dict(category="llm",     key="control_enabled",  value=True,                  label="LM Studio control (start/load/unload)", kind="toggle"),
    dict(category="llm",     key="chat_control",     value=True,                  label="LM Studio control via chat",            kind="toggle"),
    dict(category="llm",     key="hybrid_local_max", value=131072,                 label="Local routing threshold — prompts up to N input tokens stay local (0 = unlimited)", kind="number"),
    dict(category="llm",     key="daily_cost_cap_usd", value=0,                 label="Daily cloud spend cap (USD, 0 = no cap) — over it, routing degrades to local", kind="number"),
    dict(category="llm",     key="hybrid_flash_max", value=1000000,                label="Cloud Flash routing threshold — above N input tokens escalates to Pro (0 = unlimited)", kind="number"),
    dict(category="llm",     key="tool_loop_enabled", value=False,                  label="Agent tool loop (experimental)", kind="toggle"),
    dict(category="llm",     key="tool_loop_max_iterations", value=8,               label="Agent tool-loop model-turn cap", kind="number"),
    dict(category="llm",     key="tool_loop_context_tokens", value=0,               label="Agent tool-loop context budget (tokens; 0 = 75% of the model window)", kind="number"),
    dict(category="llm",     key="tool_loop_per_tool_cap", value=0,                 label="Agent tool-loop calls per tool per turn (0 = no cap; todo is not capped)", kind="number"),
    dict(category="llm",     key="skills_in_prompt", value=True,                    label="List skill commands in the model prompt", kind="toggle"),
    # H594: read the project's AGENTS.md / CLAUDE.md / .cursorrules into the turn (scanned, bounded, tainting).
    # H218: the project the agent works in by default (a folder inside the file roots; empty = the first root).
    dict(category="llm",     key="project_dir",      value="",                      label="Default project directory (inside the file roots)", kind="text"),
    dict(category="llm",     key="project_context_files", value=True,               label="Read the project's convention files (AGENTS.md, CLAUDE.md, .cursorrules)", kind="toggle"),
    dict(category="llm",     key="guest_tools", value=["echo", "time", "todo"],      label="Tools offered to a guest on an inbound channel (never a gated one)", kind="tags"),
    dict(category="llm",     key="inbound_actuation", value=False,                  label="Offer gated (approval-bound) tools to the owner on inbound channels", kind="toggle"),
    dict(category="llm",     key="internal_actuation", value=False,                 label="Offer gated (approval-bound) tools to unattended turns (heartbeats, jobs)", kind="toggle"),
    dict(category="llm",     key="model_pull_max_gb", value=20,                    label="Local model pull size cap (GB) — a governed Ollama pull whose layers exceed it is refused", kind="number"),
    # agents — per-agent model-call ceilings (Hermes absorption 5c). The flat ceiling
    # was read by the orchestrator but never seeded, so the HUD could not see it; the
    # reasoning ceiling is the floor a thinking model gets on the local deep route.
    # Both stay finite: the orchestrator clamps them to 1..3600 s (containment).
    dict(category="agents",  key="agent_timeout_seconds",     value=120, label="Per-agent model-call ceiling (s)", kind="number"),
    dict(category="agents",  key="reasoning_timeout_seconds", value=600, label="Ceiling for the local deep / thinking route (s); 0 = default 600", kind="number"),
    # voice
    dict(category="voice",   key="stt_model_size",   value="medium",              label="STT model size",     kind="select",  opts=["tiny","base","small","medium","large"]),
    dict(category="voice",   key="stt_language",     value="ro",                  label="STT language",       kind="text"),
    dict(category="voice",   key="tts_voice",        value="en-GB-RyanNeural",    label="TTS voice",          kind="text"),
    dict(category="voice",   key="persona_voice_consent", value=False,           label="Allow cloned/persona voice playback (owner consent)", kind="toggle"),
    dict(category="voice",   key="sentence_streaming", value=False,               label="Sentence-level TTS streaming (H5.16) — speak the reply sentence-by-sentence so audio starts sooner", kind="toggle"),
    dict(category="voice",   key="dictation_cleanup", value=False,                label="Dictation cleanup (0.24) — strip fillers/stutters + spoken punctuation from STT transcripts", kind="toggle"),
    dict(category="voice",   key="stt_echo_transcripts", value=False,             label="Echo voice-note transcripts on chat channels (H071) — say back what was heard before answering it", kind="toggle"),
    # security
    dict(category="security",key="guardrails_mode",  value="WARN",                label="Guardrails mode",    kind="select",  opts=["WARN","REDACT","BLOCK"]),
    dict(category="security",key="scan_input",       value=True,                  label="Scan user input",    kind="toggle"),
    dict(category="security",key="scan_output",      value=True,                  label="Scan LLM output",    kind="toggle"),
    # H507: warn-only; code the agent writes is checked for known-dangerous patterns.
    dict(category="security",key="code_guidance",    value=True,                  label="Warn when code the agent writes has a known-dangerous pattern", kind="toggle"),
    dict(category="security",key="sandbox_timeout",  value=30,                    label="Sandbox timeout (s)",kind="number"),
    dict(category="security",key="sandbox_memory",   value=256,                   label="Sandbox max memory (MB)",kind="number"),
    dict(category="security",key="sandbox_temp_dir", value="",                    label="Sandbox work directory root (absolute path; empty = the managed cache under the data root, pruned after the age below; a directory you choose here or in JARVIS_EXEC_TEMP_DIR is yours and never pruned; to keep a pruned cache on a bigger disk, move the data root (JARVIS_HOME) or bind-mount cache/exec, since a linked cache is not pruned; restart to apply)", kind="text"),
    dict(category="security",key="sandbox_temp_max_age_hours", value=72,          label="Prune the managed sandbox cache's idle run directories after (hours, 1-8760)", kind="number"),
    # memory
    dict(category="memory",  key="max_turns",        value=100,                   label="Max turns per session",kind="number"),
    # H413: name a session from its first message (then once by the local model).
    dict(category="memory",  key="session_titles",   value=True,                  label="Title sessions from their first message", kind="toggle"),
    # H218: archive chats idle for this many days (0 = never), daily at 03:40.
    dict(category="memory",  key="auto_archive_days", value=0,                    label="Archive chats idle for this many days (0 = never)", kind="number"),
    dict(category="memory",  key="context_window",   value=6,                     label="Context window (turns)",kind="number"),
    dict(category="memory",  key="context_compression", value=False,              label="Compress long context (hot path)", kind="toggle"),
    dict(category="memory",  key="compression_max_tokens", value=2000,            label="Context compression budget (tokens)", kind="number"),
    # H427: fail closed when the pre-compression checkpoint did not land (Hermes compression.checkpoint_required).
    dict(category="memory",  key="compression_checkpoint_required", value=False, label="Keep the transcript uncompressed unless its evicted turns were archived", kind="toggle"),
    dict(category="memory",  key="compression_summarizer", value=False,           label="LLM summarizer for evicted context (strict-local only)", kind="toggle"),
    dict(category="memory",  key="compression_keep_first", value=0,               label="Protect first N turns from compression", kind="number"),
    # Two-tier compaction. Fractions of the MODEL's own window rather than a
    # token count, because 32k and 200k are different products and one number
    # would be wrong for both. Only consulted on the compaction path
    # (ContextCompressor.compact); the older token-budget path is unchanged.
    dict(category="memory",  key="compaction_soft",  value=0.6,                   label="Compaction: drop images above this fraction of the model window", kind="slider"),
    dict(category="memory",  key="compaction_hard",  value=0.85,                  label="Compaction: summarize older turns above this fraction", kind="slider"),
    # 4 is the value the hot path has always used (ContextCompressor.keep_recent).
    # Named here rather than borrowed from memory.context_window, which answers a
    # different question — how many turns to FETCH, not how many to protect.
    dict(category="memory",  key="compaction_protect_last", value=4,               label="Compaction: protect the last N turns from summarization", kind="number"),
    # H12.15 — one local backup a night, pruned to a week. ON by default, unlike
    # every other scheduled capability, because the failure directions differ:
    # retention DELETES (a wrong default loses data) while a backup PRESERVES (a
    # wrong default costs disk, and the prune bounds that).
    dict(category="memory",  key="backup_auto_enabled", value=True,                label="Nightly local backup", kind="toggle"),
    dict(category="memory",  key="backup_keep",     value=7,                     label="Backups to keep", kind="number"),
    dict(category="memory",  key="compression_summary_max_tokens", value=256,     label="Compression summary budget (tokens)", kind="number"),
    # H674 — a compaction summary never holds a turn past this; the summarizer is cut after this long quiet.
    dict(category="memory",  key="compression_max_turn_hold_seconds", value=10,   label="Wait at most this many seconds for a conversation summary before answering (0 = never wait)", kind="number"),
    dict(category="memory",  key="compression_summary_idle_seconds", value=60,    label="Stop a conversation summary that sends nothing for this many seconds", kind="number"),
    dict(category="memory",  key="persist",          value=True,                  label="Persist to disk",    kind="toggle"),
    # O26-P0.3 (F2): long-term recall was read via get_setting but never seeded,
    # so it could not be enabled from the admin UI at all (put_category refuses
    # unknown keys). Default stays OFF — the Product Posture / onboarding
    # consent step (O26-P2.4) is what flips it deliberately.
    dict(category="memory",  key="recall_enabled",   value=False,                 label="Long-term recall in prompts", kind="toggle"),
    dict(category="memory",  key="recall_top_k",     value=5,                     label="Recall hits per prompt", kind="number"),
    # H428 — the hard bound on the pre-turn recall (embedding + fused search), as
    # Hermes bounds a memory prefetch at 8 s. Validated in Orchestrator._recall_timeout_s.
    dict(category="memory",  key="recall_timeout_s", value=8,                     label="Recall time limit (seconds)", kind="number"),
    # H433 — rewrite the message into one grounded retrieval question with the
    # strict-local model before recall. Off by default: it costs a model call.
    dict(category="memory",  key="recall_query_rewrite", value=False,              label="Rewrite the recall query with the local model", kind="toggle"),
    # O26-P0.3 (F2): the H21 cognition subsystem read cognition.* flags that were
    # never seeded — un-toggleable from the product. Master OFF (default-off
    # discipline); sub-flags ON so flipping the single master wakes the layer
    # (sub_enabled = master AND sub, agents/core/cognition/facade.py).
    dict(category="cognition", key="enabled",             value=False, label="Cognition master switch (H21)", kind="toggle"),
    dict(category="cognition", key="honesty_enabled",     value=True,  label="Honesty / anti-sycophancy axis", kind="toggle"),
    dict(category="cognition", key="affect_enabled",      value=True,  label="Persona mood (affect)",          kind="toggle"),
    dict(category="cognition", key="memory_enabled",      value=True,  label="Living memory",                  kind="toggle"),
    dict(category="cognition", key="learning_enabled",    value=True,  label="Cognition learning loop",        kind="toggle"),
    dict(category="cognition", key="personality_enabled", value=True,  label="Personality ensemble",           kind="toggle"),
    # review_enabled (H20 learning loop) was read via cog.sub_enabled("review_enabled")
    # everywhere but had no DEFAULTS row, so it was invisible/unsettable from the admin
    # settings API. Adding it here is additive only: get_setting already defaulted
    # missing keys to False, so this row changes nothing at runtime — it just makes
    # the existing gate visible and toggleable.
    dict(category="cognition", key="review_enabled",      value=False, label="Per-turn background review (H20 learning loop)", kind="toggle"),
    # learning — the H20 review loop's knobs, read by BackgroundReviewer and the review's
    # local model call. They had no rows, so the admin API skipped them and
    # `nerva config set` refused them, while /refine's replies named them (review-H465c
    # m-2). The values are the ones the code already defaulted to: seeding changes nothing.
    dict(category="learning", key="review_max_tokens", value=512, label="Review answer budget in tokens (1–32768; a cut-off review names this)", kind="number"),
    dict(category="learning", key="review_daily_budget", value=20, label="Reviews a day, per-turn and /refine together (0 = none)", kind="number"),
    dict(category="learning", key="review_cadence", value="every_turn", label="Per-turn review cadence", kind="select", opts=["every_turn", "every_n_turns", "idle_gap"]),
    dict(category="learning", key="review_every_n", value=3, label="Review every N turns (cadence every_n_turns)", kind="number"),
    dict(category="learning", key="review_idle_gap_s", value=90, label="Seconds between reviews (cadence idle_gap)", kind="number"),
    dict(category="learning", key="review_max_facts", value=3, label="Facts a review may keep, per ring (0 = none; corrections are capped apart)", kind="number"),
    # Owner-authored media reminders: one deadline for the complete delivery.
    dict(category="jobs", key="media_send_timeout_seconds", value=300, label="Scheduled media total delivery deadline (1–300 seconds)", kind="number"),
    # channels
    dict(category="channels",key="rate_limit",       value=10,                    label="Gateway rate limit (msg/min)", kind="number"),
    dict(category="channels",key="web_enabled",      value=True,                  label="Web channel",        kind="toggle"),
    dict(category="channels",key="streaming_replies", value=True,                 label="Write chat replies in place as they are produced (channels that can edit a message)", kind="toggle"),
    # webhooks — H153: the platform-level receiver switch. Off, every inbound delivery
    # is refused with 503 before its body is read; hooks keep their credentials.
    dict(category="webhooks", key="receiver_enabled", value=True, label="Inbound webhook receiver (off: every delivery is refused; hooks keep their credentials)", kind="toggle"),
    # plugins (one per plugin, enabled toggle)
    dict(category="plugins", key="weather",          value=True,                  label="Weather",            kind="toggle"),
    dict(category="plugins", key="news",             value=True,                  label="News",               kind="toggle"),
    dict(category="plugins", key="stock-quotes",     value=True,                  label="Stock Quotes (Stooq)", kind="toggle"),
    dict(category="plugins", key="cloud-llm",        value=True,                  label="Cloud LLM",          kind="toggle"),
    dict(category="plugins", key="telegram",         value=True,                  label="Telegram",           kind="toggle"),
    dict(category="plugins", key="gmail",            value=True,                  label="Gmail",              kind="toggle"),
    dict(category="plugins", key="google-calendar",  value=True,                  label="Google Calendar",    kind="toggle"),
    dict(category="plugins", key="whatsapp-bridge",  value=True,                  label="WhatsApp Bridge",    kind="toggle"),
    dict(category="plugins", key="spotify",          value=True,                  label="Spotify",            kind="toggle"),
    dict(category="plugins", key="apple-health",     value=True,                  label="Apple Health",       kind="toggle"),
    dict(category="plugins", key="homebridge",       value=True,                  label="Homebridge",         kind="toggle"),
    dict(category="plugins", key="sms-alerts",       value=True,                  label="SMS Alerts & Notifications", kind="toggle"),
    dict(category="plugins", key="crm-sync",         value=True,                  label="Notion CRM Sync", kind="toggle"),
    dict(category="plugins", key="iot-control",       value=True,                  label="Tuya SmartHome IoT", kind="toggle"),
    dict(category="plugins", key="revenuecat",       value=True,                  label="RevenueCat Revenue", kind="toggle"),
    dict(category="plugins", key="meta-ads",         value=True,                  label="Meta Ads Insights",  kind="toggle"),
    dict(category="plugins", key="postiz",           value=True,                  label="Postiz Social Scheduler", kind="toggle"),
    # twilio — sms alerts
    dict(category="plugins", key="twilio_account_sid",  value="",    label="Twilio Account SID",                kind="text"),
    dict(category="plugins", key="twilio_auth_token",   value="",    label="Twilio Auth Token",                 kind="text"),
    dict(category="plugins", key="twilio_from_number",  value="",    label="Twilio From Number",                kind="text"),
    # notion — crm sync
    dict(category="plugins", key="notion_integration_token", value="", label="Notion Integration Token",          kind="text"),
    dict(category="plugins", key="notion_database_id",       value="", label="Notion CRM Database ID",          kind="text"),
    # tuya — iot control
    dict(category="plugins", key="tuya_client_id",      value="",    label="Tuya Client ID",                    kind="text"),
    dict(category="plugins", key="tuya_secret",         value="",    label="Tuya Client Secret",                kind="text"),
    dict(category="plugins", key="tuya_device_id",      value="",    label="Tuya Target Device ID",             kind="text"),
    # gecko — balance reader
    dict(category="plugins", key="gecko_ing_client_id",    value="",    label="Gecko – ING Client ID",            kind="text"),
    dict(category="plugins", key="gecko_ing_client_secret", value="",   label="Gecko – ING Client Secret",        kind="text"),
    dict(category="plugins", key="gecko_libra_token",       value="",   label="Gecko – Libra API Token",          kind="text"),
    dict(category="plugins", key="gecko_csv_path",          value="",   label="Gecko – CSV export path",          kind="text"),
    dict(category="plugins", key="gecko_tx_csv_path",       value="",   label="Gecko – transactions CSV (burn-rate)", kind="text"),
    # stark — analytics
    dict(category="plugins", key="stark_ga4_service_account", value="", label="Stark – GA4 Service Account JSON", kind="text"),
    dict(category="plugins", key="stark_ga4_property_id",     value="", label="Stark – GA4 Property ID",          kind="text"),
    # skills
    dict(category="skills",  key="auto_generate",    value=True,                  label="Auto-generate skills",kind="toggle"),
    dict(category="skills",  key="sandbox_enabled",  value=True,                  label="Sandbox execution",  kind="toggle"),
    dict(category="skills",  key="max_skills",       value=50,                    label="Max stored skills",  kind="number"),
    dict(category="skills",  key="import_source",    value="hermes",              label="Import source",      kind="select", opts=["hermes","openclaw","none"]),
    # H340 — literal text a skill body may name as ${key} (skill_view renders it); never a
    # secret or an environment variable: a value holding "$", "env:" or "secret:" is ignored.
    dict(category="skills",  key="template_vars",    value={},                    label="Skill template variables — JSON {\"name\": \"literal text\"}, used as ${name} in a skill body", kind="json"),
    # H329: switched off, not uninstalled (skills/switches.py); the skill switch route writes them.
    dict(category="skills",  key="disabled",         value=[],                    label="Skills switched off everywhere (kept installed)", kind="tags"),
    dict(category="skills",  key="channel_disabled", value={},                    label="Skills switched off on one channel — JSON {\"telegram\": [\"Spotify\"]}", kind="json"),
    # H32 governed acquisition — an independent owner switch. Product Posture
    # intentionally does not enable this capability.
    dict(category="acquisition", key="enabled", value=False, label="Governed capability acquisition", kind="toggle"),
    # system
    dict(category="system",  key="log_level",        value="INFO",                label="Log level",          kind="select", opts=["DEBUG","INFO","WARNING","ERROR"]),
    dict(category="system",  key="poll_interval",    value=10,                    label="Poll interval (s)",  kind="number"),
    # H23.11 — operability: opt-in rotating file log (default off; stderr only, so a
    # supervisor like systemd/journald rotates). $JARVIS_LOG_FILE / *_MAX_MB / *_BACKUPS override.
    # NB: root-logger records at the active level may include request-derived content
    # (e.g. a voice transcript preview); the file persists it on disk, bounded only by
    # log_max_mb × log_backups. Prefer WARNING level for privacy-sensitive deployments.
    dict(category="system",  key="log_to_file",      value=False,                 label="Log to rotating file (may persist content)", kind="toggle"),
    dict(category="system",  key="log_max_mb",       value=10,                    label="Log file size cap (MB)", kind="number"),
    dict(category="system",  key="log_backups",      value=5,                     label="Rotated log backups", kind="number"),
    # H182: on battery below this percent, the heavy background jobs skip their run (0 = never, 100 = always).
    dict(category="system",  key="battery_defer_percent", value=50,               label="On battery below this %, defer heavy background jobs (0 = never)", kind="number"),
    dict(category="system",  key="startup_warmup_timeout_seconds", value=20,      label="At start, wait up to this many seconds for the local model to warm up before accepting messages (0 = don't wait)", kind="number"),
    # mcp
    dict(category="mcp",     key="servers",          value=[],                    label="MCP servers",        kind="json"),
    # H285 — the owner's load set: comma lists of names read at boot (agents/core/load_set.py).
    # A "disabled" name does not load; a non-empty "only" list loads only what it names.
    # They only narrow: a name that is not installed is reported, never installed.
    dict(category="loadset", key="skills_disabled",  value="", label="Skills that do not load (comma list)", kind="text"),
    dict(category="loadset", key="skills_only",      value="", label="Load only these skills (comma list; empty = all)", kind="text"),
    dict(category="loadset", key="plugins_disabled", value="", label="Plugins switched off (comma list; the plugin toggle writes it)", kind="text"),
    dict(category="loadset", key="plugins_only",     value="", label="Enable only these plugins (comma list; empty = all)", kind="text"),
    dict(category="loadset", key="mcp_disabled",     value="", label="Saved MCP servers that do not load (comma list; their config is kept)", kind="text"),
    dict(category="loadset", key="mcp_only",         value="", label="Load only these saved MCP servers (comma list; empty = all)", kind="text"),
    # autonomy — Proactive Cortex (ORIZONT 6)
    dict(category="autonomy", key="mode",            value="auto", label="Autonomy mode (AUTO/ASK/OFF)", kind="select", opts=["auto","ask","off"]),
    dict(category="autonomy", key="earned_autonomy_enabled", value=False, label="Earn autonomy from proven outcomes", kind="toggle"),
    dict(category="autonomy", key="owner_chat_id",   value="",     label="Owner Telegram chat ID", kind="text"),
    dict(category="autonomy", key="cap_per_action",  value=50,     label="Money cap per action", kind="number"),
    dict(category="autonomy", key="daily_ceiling",   value=200,    label="Money daily ceiling",  kind="number"),
    dict(category="autonomy", key="interrupt_budget",value=4,      label="Urgent pushes per day", kind="number"),
    dict(category="autonomy", key="running_ttl_seconds", value=3600, label="Stuck-running reaper TTL (s)", kind="number"),
    dict(category="autonomy", key="night_shift",     value=False,  label="Night shift enabled",  kind="toggle"),
    dict(category="autonomy", key="night_start",     value=23,     label="Night window start (h)", kind="number"),
    dict(category="autonomy", key="night_end",       value=6,      label="Night window end (h)", kind="number"),
    dict(category="autonomy", key="max_subagent_spawns_per_boot", value=50, label="Max sub-agent spawns per boot (0 = unbounded)", kind="number"),
    dict(category="autonomy", key="priority_senders", value=["andrei"], label="Priority email senders", kind="tags"),
    dict(category="autonomy", key="finance_min_ron",  value=2000.0,   label="Minimum balance threshold (RON)", kind="number"),
    dict(category="autonomy", key="finance_min_eur",  value=400.0,    label="Minimum balance threshold (EUR)", kind="number"),
    dict(category="autonomy", key="health_min_sleep", value=5.0,     label="Minimum sleep hours", kind="number"),
    dict(category="autonomy", key="health_min_hrv",   value=30.0,    label="Minimum HRV threshold (ms)", kind="number"),
    dict(category="autonomy", key="calendar_lead_time", value=30,     label="Calendar event lead time (min)", kind="number"),
    # Proactive Technology Scout — default-off, read-only awareness scan (websearch
    # only; no fetch/exec). Findings land as RiskTier.READ_ONLY autonomy tasks
    # ("observations inform, decisions interrupt" — same posture as the observer).
    dict(category="autonomy", key="tech_scout_enabled", value=False, label="Proactive Technology Scout", kind="toggle"),
    dict(category="autonomy", key="tech_scout_interval_hours", value=168, label="Tech scout scan interval (hours)", kind="number"),
    dict(category="autonomy", key="tech_scout_queries", value=[
        "new open-source local LLM inference engine release",
        "new personal AI agent framework or assistant launch",
        "on-device speech recognition or wake-word breakthrough",
        "self-hosted AI operating system competitor",
    ], label="Tech scout search queries", kind="tags"),
    dict(category="system",  key="autonomy_tick",    value=60,     label="Autonomy tick (s)",    kind="number"),
    dict(category="system",  key="observer_enabled", value=True,   label="Resource Observer enabled", kind="toggle"),
    dict(category="system",  key="watchers_enabled", value=True,   label="Event Watchers enabled", kind="toggle"),
    # H33 ambient intelligence is a separate explicit owner opt-in. Product
    # Posture never enables it implicitly; generation revokes queued work.
    dict(category="ambient", key="enabled", value=False, label="Ambient intelligence", kind="toggle"),
    dict(category="ambient", key="generation", value=1, label="Ambient consent generation", kind="number"),
    dict(category="ambient", key="quiet_hours_start", value=22, label="Ambient quiet-hours start", kind="number"),
    dict(category="ambient", key="quiet_hours_end", value=7, label="Ambient quiet-hours end", kind="number"),
    dict(category="system",  key="error_backlog_sync_enabled", value=True, label="Error backlog sync enabled", kind="toggle"),
    # retention — data lifecycle (H23.10). A daily sweep prunes data older than the
    # TTL. OFF by default so nothing is ever surprise-deleted; a TTL of 0 means keep
    # forever even when enabled.
    dict(category="retention", key="artifact_ttl_days", value=0, label="Delete unpinned binary attachments older than (days; 0 = keep forever)", kind="number"),
    dict(category="retention", key="enabled",               value=False, label="Enable data-retention sweeps", kind="toggle"),
    dict(category="retention", key="conversation_ttl_days", value=90,    label="Delete conversation transcripts older than (days; 0 = keep forever)", kind="number"),
    dict(category="retention", key="audit_ttl_days",        value=365,   label="Prune audit-log rows older than (days; 0 = keep forever)", kind="number"),
    dict(category="retention", key="ingestion_ttl_days",   value=0,     label="Delete stale Howard imports/archive after (days; 0 = keep forever)", kind="number"),
]

# ── lazy init — called on first use, not at import time ───────────

_initialized = False
_init_lock = threading.Lock()
_wal_set = False

def _ensure_init():
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if not _initialized:
            init_db()
            _initialized = True


def ensure_initialized() -> None:
    """Create and seed the settings schema on first use, safely across threads."""
    _ensure_init()

# ── helpers ───────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    global _wal_set
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: settings reads/writes may be dispatched via
    # asyncio.to_thread from the async hot path; a threading.Lock (_init_lock)
    # serialises schema init. Individual callers close the connection promptly.
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL is a persistent database property — setting it once per process
    # is enough; re-issuing the PRAGMA on every connection is wasted work.
    if not _wal_set:
        conn.execute("PRAGMA journal_mode=WAL")
        _wal_set = True
    return conn

def _migrate_retired_claude_default(conn: sqlite3.Connection) -> bool:
    """Replace only the shipped retired Claude default, preserving owner pins."""

    cursor = conn.execute(
        """
        UPDATE settings
           SET value = ?
         WHERE category = 'llm'
           AND key = 'claude_model'
           AND value = ?
        """,
        (
            json.dumps(DEFAULT_CLAUDE_MODEL),
            json.dumps(RETIRED_CLAUDE_DEFAULT),
        ),
    )
    return cursor.rowcount > 0


def init_db(force: bool = False):
    conn = get_conn()
    conn.executescript(SCHEMA)
    if force:
        conn.execute("DELETE FROM settings")
    
    # Run INSERT OR IGNORE for all default settings to guarantee new updates are seeded dynamically
    inserted = 0
    for row in DEFAULTS:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO settings (category, key, value, label, kind, opts) VALUES (?,?,?,?,?,?)",
            (row["category"], row["key"], json.dumps(row["value"]), row["label"], row["kind"], json.dumps(row.get("opts", []))),
        )
        if cursor.rowcount > 0:
            inserted += 1
            
    if inserted > 0:
        logger.info(f"Seeded {inserted} new default settings (total {len(DEFAULTS)})")

    _migrate_retired_claude_default(conn)
    _migrate_changed_defaults(conn)
    _refresh_labels(conn)
    conn.commit()
    conn.close()
    if force:
        _changed(None, None)


def _refresh_labels(conn: sqlite3.Connection) -> int:
    """A label is the build's own words, never the owner's (every write takes the
    declaration's): a declared row keeps its value and takes this build's label, so a
    reworded label reaches an install seeded by an earlier build. Returns how many moved."""
    moved = 0
    for row in DEFAULTS:
        cursor = conn.execute(
            "UPDATE settings SET label=? WHERE category=? AND key=? AND label<>?",
            (row["label"], row["category"], row["key"], row["label"]),
        )
        moved += cursor.rowcount
    return moved


def _migrate_changed_defaults(conn: sqlite3.Connection) -> list[str]:
    """Apply each :data:`_CHANGED_DEFAULTS` entry once per store; the names it changed."""
    changed: list[str] = []
    for name, category, key, old, new in _CHANGED_DEFAULTS:
        if conn.execute("SELECT 1 FROM settings_migrations WHERE name=?", (name,)).fetchone():
            continue
        cursor = conn.execute(
            "UPDATE settings SET value=? WHERE category=? AND key=? AND value=?",
            (json.dumps(new), category, key, json.dumps(old)),
        )
        conn.execute("INSERT INTO settings_migrations (name, applied_at) VALUES (?, ?)", (name, time.time()))
        if cursor.rowcount > 0:
            changed.append(name)
            logger.info("settings: %s.%s had the old shipped default and now has the new one", category, key)
    return changed

def value_source(category: str, key: str, value, raw=None) -> str:
    """H273 — where a stored value stands against its declaration: ``default`` when
    it equals the declared default, ``set`` when it differs (an owner write or a
    migration), ``undeclared`` for a stored key with no declaration, and
    ``unreadable`` for an encrypted secret whose key is lost (it reads as empty, which
    must not pass for the default). ``raw`` is the stored value before decryption."""
    spec = _SPEC.get((category, key))
    if spec is None:
        return "undeclared"
    if isinstance(raw, str) and raw.startswith(_ENC_PREFIX) and value == "":
        return "unreadable"
    return "default" if value == spec.get("value") else "set"


_NO_OVERLAY = object()


def _posture_overlay(stored) -> tuple[str, dict]:
    """The selected product posture and the settings it forces while selected (the
    runtime applies them over the stored rows: product_posture.apply_to_runtime_settings).
    ``stored`` is the raw ``product.posture`` row value (or None), read by the caller in
    the connection it already has open; an unknown name is normalised to off."""
    from agents.core import product_posture

    try:
        raw = product_posture.OFF if stored is None else json.loads(stored)
    except (TypeError, ValueError):
        raw = product_posture.OFF
    name = product_posture.normalize(raw)
    return name, dict(product_posture.POSTURES[name].get("applies", {}))


def _mark_overlay(category: str, row: dict, posture: tuple[str, dict]) -> dict:
    """H273 review — the stored row says ``default``, but a selected posture may put
    another value in effect: name it, so ``source`` is never the whole story.
    H259 — a declared setting that is not a secret also carries its ``default``, so
    the HUD can mark a changed one and put it back."""
    spec = _SPEC.get((category, row["key"]))
    if spec is not None and not is_secret_setting(category, row["key"]):
        row["default"] = spec["value"]
    name, applies = posture
    forced = applies.get(f"{category}.{row['key']}", _NO_OVERLAY)
    if forced is not _NO_OVERLAY:
        row["in_effect"] = forced
        row["overlay"] = f"product.posture:{name}"
    return row


def get_all() -> dict[str, list[dict]]:
    _ensure_init()
    conn = get_conn()
    rows = conn.execute("SELECT category, key, value, label, kind, opts FROM settings ORDER BY category, key").fetchall()
    conn.close()
    groups: dict[str, list[dict]] = {}
    posture = _posture_overlay(next((r["value"] for r in rows
                                     if r["category"] == "product" and r["key"] == "posture"), None))
    for r in rows:
        cat = r["category"]
        if cat not in groups:
            groups[cat] = []
        raw = json.loads(r["value"])
        value = _decrypt_if_secret(raw)
        groups[cat].append(_mark_overlay(cat, {
            "key": r["key"],
            "value": value,
            "label": r["label"],
            "kind": r["kind"],
            "opts": json.loads(r["opts"]),
            "source": value_source(cat, r["key"], value, raw),
        }, posture))
    return groups

def get_value(category: str, key: str, default=None):
    """Return a single setting value, or `default` if missing / DB unavailable.

    Safe to call before init or without a DB (returns default) so callers like the
    LLM router can read admin config without a hard dependency."""
    try:
        _ensure_init()
        conn = get_conn()
        row = conn.execute(
            "SELECT value FROM settings WHERE category=? AND key=?",
            (category, key),
        ).fetchone()
        conn.close()
        if row is None:
            return default
        return _decrypt_if_secret(json.loads(row["value"]))
    except Exception:
        return default


class SettingsUnreadable(RuntimeError):
    """The settings store could not be read (corrupt, locked, no table)."""


def read_setting(category: str, key: str) -> tuple[bool, Any]:
    """``(found, value)`` for one setting, raising :class:`SettingsUnreadable` when the
    store cannot be read. For a guard that must fail closed: ``get_value`` turns every
    error into the default, which for an "on by default" switch means on."""
    try:
        _ensure_init()
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE category=? AND key=?",
                (category, key),
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        raise SettingsUnreadable(f"{type(exc).__name__}: {exc}") from exc
    if row is None:
        return False, None
    try:
        return True, _decrypt_if_secret(json.loads(row["value"]))
    except Exception as exc:
        raise SettingsUnreadable(f"{type(exc).__name__}: {exc}") from exc


_change_listeners: list = []


def on_change(listener) -> None:
    """Call ``listener(category, values)`` after a write in this process: a category
    write passes what it wrote, a reseed passes ``(None, None)``. A listener that raises
    is logged and skipped; it never fails the write."""
    if listener not in _change_listeners:
        _change_listeners.append(listener)


def _changed(category, values) -> None:
    for listener in list(_change_listeners):
        try:
            listener(category, values)
        except Exception:
            logger.warning("a settings change listener failed", exc_info=True)


def get_category(cat: str) -> list[dict]:
    _ensure_init()
    conn = get_conn()
    rows = conn.execute(
        "SELECT key, value, label, kind, opts FROM settings WHERE category=? ORDER BY key",
        (cat,),
    ).fetchall()
    stored = conn.execute("SELECT value FROM settings WHERE category='product' AND key='posture'").fetchone()
    conn.close()
    out = []
    posture = _posture_overlay(stored["value"] if stored is not None else None)
    for r in rows:
        raw = json.loads(r["value"])
        value = _decrypt_if_secret(raw)
        out.append(_mark_overlay(cat, {
            "key": r["key"],
            "value": value,
            "label": r["label"],
            "kind": r["kind"],
            "opts": json.loads(r["opts"]),
            "source": value_source(cat, r["key"], value, raw),
        }, posture))
    return out


# ── settings integrity (AUD-8 / F10) ──────────────────────────────
# Validate an admin settings write against each key's declared schema (its
# DEFAULTS entry) before it is persisted, so a malformed value (wrong type, or
# off the select allow-list) is rejected with 422 instead of corrupting a setting
# that the rest of the system then reads back and trusts. Unknown keys are not an
# error here — put_category already ignores them.
_SPEC: dict[tuple[str, str], dict[str, Any]] = {(d["category"], d["key"]): d for d in DEFAULTS}


# H583 — the OpenRouter provider-slug lists refuse anything that is not a slug.
_ROUTING_SLUG_KEYS = frozenset(_routing.SETTINGS_KEYS[name] for name in _routing.SLUG_LISTS)


#: The learning loop's integer knobs and their bounds (review-H465c m-2): a
#: review_max_tokens of 0 would mean "until the context is full" to a local backend.
_LEARNING_INT_BOUNDS = {
    "review_max_tokens": (1, 32768), "review_daily_budget": (0, 1000), "review_every_n": (1, 100),
    "review_idle_gap_s": (0, 86400), "review_max_facts": (0, 20),
}


def bounded_learning_int(key: str, raw: Any, default: int) -> int:
    """A learning knob as its readers use it: an integer within its declared bounds, else
    ``default``. The bounds are enforced on write; this holds them for a row written
    before them, restored from a backup or edited by hand (review-H465d nit 4)."""
    low, high = _LEARNING_INT_BOUNDS[key]
    if isinstance(raw, bool):
        return default
    try:
        value = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return default
    return value if low <= value <= high else default


def _validate_value(key: str, value: Any, kind: str, opts: list) -> str | None:
    """Return an error string if *value* violates the *kind*'s schema, else None."""
    if key == "media_send_timeout_seconds" and (type(value) is not int or not 1 <= value <= 300):
        return f"{key}: expected an integer between 1 and 300 seconds"
    if key == "sandbox_temp_dir":
        from .exec_cache import choice_problem

        problem = choice_problem(value)
        if problem:
            return f"{key}: {problem}"
    if key == "sandbox_temp_max_age_hours" and (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not (isinstance(value, int) or math.isfinite(value)) or not 1 <= value <= 8760):
        return f"{key}: expected a number of hours between 1 and 8760"
    if key == "artifact_ttl_days" and (type(value) is not int or not 0 <= value <= 36500):
        return f"{key}: expected an integer between 0 and 36500 days"
    if key in _LEARNING_INT_BOUNDS:
        low, high = _LEARNING_INT_BOUNDS[key]
        if type(value) is not int or not low <= value <= high:
            return f"{key}: expected an integer between {low} and {high}"
    if kind == "toggle":
        if not isinstance(value, bool):
            return f"{key}: expected a boolean (toggle)"
    elif kind in ("number", "slider"):
        # bool is an int subclass — exclude it so a toggle value can't pass as a number.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{key}: expected a number"
        # NaN and the infinities are JSON-storable but no setting means them (H428:
        # a NaN recall timeout silently switched recall off).
        if isinstance(value, float) and not math.isfinite(value):
            return f"{key}: expected a finite number"
    elif kind == "select":
        if value not in opts:
            return f"{key}: {value!r} is not one of {opts}"
    elif kind in ("text", "model-select"):
        if not isinstance(value, str):
            return f"{key}: expected a string"
    elif kind == "tags":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return f"{key}: expected a list of strings (tags)"
        if key in _ROUTING_SLUG_KEYS:
            problem = _routing.slug_list_problem(key, value)
            if problem:
                return problem
    # 'json' and any unknown kind accept any JSON-serializable value.
    return None


def validate_category(cat: str, data: dict[str, Any]) -> list[str]:
    """Validate a settings write; return a list of human-readable errors (empty = ok).

    Only keys known in DEFAULTS for *cat* are checked (unknown keys are ignored on
    write). Values must be JSON-serializable so they can be stored.
    """
    errors: list[str] = []
    for key, value in data.items():
        spec = _SPEC.get((cat, key))
        if spec is None:
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            errors.append(f"{key}: value is not JSON-serializable")
            continue
        err = _validate_value(key, value, spec.get("kind", "text"), spec.get("opts", []) or [])
        if err is None and (cat, key) == ("skills", "template_vars"):
            err = _template_vars_problem(value)
        if err is None and (cat, key) == ("skills", "channel_disabled"):
            from .skills.switches import channel_map_problem
            err = channel_map_problem(value)
        if err is None and (cat, key) == ("mcp", "servers"):
            err = _mcp_servers_problem(value)
        if err:
            errors.append(err)
    return errors


def _mcp_servers_problem(value: Any) -> str | None:
    """``mcp.servers`` is a list of server objects, each with a non-empty string name:
    an entry the loader cannot read would stop it at start (review-H157 m2)."""
    if not isinstance(value, list):
        return "servers: expected a list of server objects"
    for n, server in enumerate(value):
        if not isinstance(server, dict) or not isinstance(server.get("name"), str) \
                or not server["name"].strip():
            return f"servers: entry {n + 1} needs an object with a non-empty name"
    return None


def _template_vars_problem(value: Any) -> str | None:
    """H340 review: ``skills.template_vars`` is refused on write unless every entry is one
    ``skill_view`` would render, so an owner never saves a variable that silently does
    nothing (a string, an env pointer, a too-long value)."""
    from .skills.template_vars import MAX_VALUE, MAX_VARS, clean_template_vars

    if not isinstance(value, dict) or clean_template_vars(value) != value:
        return (f"template_vars: a JSON map of names to plain text — a name is an identifier, a value "
                f"one line of at most {MAX_VALUE} characters with no '$', env: or secret:, at most "
                f"{MAX_VARS} entries, and no fixed name (NERVA_/HERMES_SKILL_DIR, _SESSION_ID)")
    return None


def put_category(cat: str, data: dict[str, Any]) -> tuple[int, list[str]]:
    _ensure_init()
    conn = get_conn()
    updated = 0
    skipped = []
    for key, value in data.items():
        cur = conn.execute("SELECT key FROM settings WHERE category=? AND key=?", (cat, key))
        if cur.fetchone():
            stored = _encrypt_if_secret(key, value)
            conn.execute("UPDATE settings SET value=? WHERE category=? AND key=?", (json.dumps(stored), cat, key))
            updated += 1
            continue
        # O26-P0.3 (F2): a key that is part of the shipped DEFAULTS spec but has
        # no row yet (e.g. a DB created before the key existed and not re-inited)
        # is UPSERTED with the spec's kind/label — never lost. Keys outside the
        # spec stay rejected (no arbitrary-row injection through the admin API).
        spec = next((r for r in DEFAULTS if r["category"] == cat and r["key"] == key), None)
        if spec is not None:
            stored = _encrypt_if_secret(key, value)
            conn.execute(
                "INSERT INTO settings (category, key, value, label, kind, opts) VALUES (?,?,?,?,?,?)",
                (cat, key, json.dumps(stored), spec["label"], spec["kind"],
                 json.dumps(spec.get("opts", []))),
            )
            updated += 1
        else:
            skipped.append(key)
    conn.commit()
    conn.close()
    if skipped:
        logger.warning("put_category(%s): ignored unknown keys: %s",
                       _logsafe(cat), _logsafe(skipped))
    written = {key: value for key, value in data.items() if key not in skipped}
    if written:
        _changed(cat, written)
    return updated, skipped

# ── init on first use (via _ensure_init) — NOT at import ─────────


# ── H157: export, import, per-category reset ──────────────────────

EXPORT_FORMAT = "nerva-settings/1"
MAX_IMPORT_KEYS = 1000
#: Declared settings an export never carries: they hold credentials by design (an MCP
#: server's headers and env), even when the value scan finds nothing it recognises.
EXPORT_EXCLUDED = frozenset({("mcp", "servers")})
#: Kinds whose value is a pick (a switch, a list choice, a number): never a credential.
_CHOICE_KINDS = frozenset({"toggle", "select", "number", "slider"})
_CREDENTIAL_NAME = re.compile(r"(token|secret|password|passwd|client_id|api_key|apikey)$")


def is_secret_setting(category: str, key: str) -> bool:
    """A setting whose value is a credential: encrypted at rest, or named like one."""
    return key in SECRET_KEYS or bool(_CREDENTIAL_NAME.search(key))


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def _url_password(value: Any) -> bool:
    """Whether any string in the value is a URL carrying a password (``http://u:pw@h``),
    which the secret scanner recognises only for database URLs (review-H157 M2)."""
    from urllib.parse import urlsplit

    for text in _strings(value):
        if "@" not in text or "://" not in text:
            continue
        try:
            if urlsplit(text.strip()).password:
                return True
        except ValueError:
            return True                          # unparseable, with an @: leave it out
    return False


def _looks_like_credential(value: Any) -> bool:
    """Whether the value holds a credential: a URL with a password, or anything the
    secret scanner masks (a token in a template variable, a key pasted into free text)."""
    if value in (None, "", [], {}) or isinstance(value, (bool, int, float)):
        return False
    if _url_password(value):
        return True
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        from .security.log_redaction import SecretRedactionFilter

        return SecretRedactionFilter().redact_text(text) != text
    except Exception:  # noqa: BLE001 (no scanner: leave it out rather than risk it)
        return True


def _stored_values(conn: sqlite3.Connection) -> dict[tuple[str, str], Any]:
    rows = conn.execute("SELECT category, key, value FROM settings").fetchall()
    return {(r["category"], r["key"]): _decrypt_if_secret(json.loads(r["value"])) for r in rows}


def export_settings() -> dict:
    """The declared settings as a document another box can import: ``settings`` by
    category, and ``excluded`` naming what was left out and why (a secret, a value that
    looks like a credential, a setting that holds credentials by design)."""
    _ensure_init()
    conn = get_conn()
    try:
        stored = _stored_values(conn)
    finally:
        conn.close()
    settings: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, str]] = []
    for spec in DEFAULTS:
        cat, key = spec["category"], spec["key"]
        value = stored.get((cat, key), spec["value"])
        reason = None
        if (cat, key) in EXPORT_EXCLUDED:
            reason = "holds credentials by design"
        elif is_secret_setting(cat, key):
            reason = "a secret"
        elif spec.get("kind") not in _CHOICE_KINDS and _looks_like_credential(value):
            reason = "the value looks like it holds a credential"
        if reason:
            excluded.append({"setting": f"{cat}.{key}", "reason": reason})
            continue
        settings.setdefault(cat, {})[key] = value
    return {"format": EXPORT_FORMAT, "exported_at": int(time.time()), "settings": settings,
            "excluded": excluded}


def plan_import(doc: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """``(changes, errors)`` for an import document: every key declared and validated
    exactly as a single write would be, and only the keys whose value differs. Any error
    means nothing may be written."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return {}, ["the document: expected an object with a 'settings' object"]
    if "format" in doc and doc["format"] != EXPORT_FORMAT:
        errors.append(f"format: expected {EXPORT_FORMAT!r}")
    settings = doc.get("settings")
    if not isinstance(settings, dict):
        return {}, errors + ["settings: expected an object of categories"]
    total = sum(len(v) for v in settings.values() if isinstance(v, dict))
    if total > MAX_IMPORT_KEYS:
        return {}, errors + [f"too many settings ({total}; at most {MAX_IMPORT_KEYS})"]
    wanted: dict[str, dict[str, Any]] = {}
    for cat, values in settings.items():
        if not isinstance(values, dict):
            errors.append(f"{cat}: expected an object of settings")
            continue
        for key, value in values.items():
            if (cat, key) not in _SPEC:
                errors.append(f"{cat}.{key}: unknown setting")
                continue
            try:                                 # NaN, Infinity or a nesting too deep to store
                json.dumps(value, allow_nan=False)
            except (ValueError, TypeError, RecursionError):
                errors.append(f"{cat}.{key}: not a finite JSON value (NaN, Infinity or nested too deep)")
                continue
            wanted.setdefault(cat, {})[key] = value
        errors.extend(f"{cat}.{err}" for err in validate_category(cat, wanted.get(cat, {})))
    if errors:
        return {}, errors
    _ensure_init()
    conn = get_conn()
    try:
        stored = _stored_values(conn)
    finally:
        conn.close()
    changes: dict[str, dict[str, Any]] = {}
    for cat, values in wanted.items():
        for key, value in values.items():
            current = stored.get((cat, key), _SPEC[(cat, key)]["value"])
            if not _same_value(value, current):
                changes.setdefault(cat, {})[key] = value
    return changes, []


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same_value(a: Any, b: Any) -> bool:
    """Equal as a setting: 2000 and 2000.0 are the same number (a browser writes one for
    the other, review-H157 m4), but a bool is never a number."""
    if _is_number(a) and _is_number(b):
        return a == b
    return a == b and type(a) is type(b)


def describe_changes(changes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """``[{setting, from, to}]`` for a preview; a secret's values are never shown."""
    _ensure_init()
    conn = get_conn()
    try:
        stored = _stored_values(conn)
    finally:
        conn.close()
    out = []
    for cat in sorted(changes):
        for key in sorted(changes[cat]):
            if is_secret_setting(cat, key):
                out.append({"setting": f"{cat}.{key}", "from": "(secret)", "to": "(secret)"})
                continue
            free = _SPEC[(cat, key)].get("kind") not in _CHOICE_KINDS

            def shown(value, free=free):
                # the export's rule: a value that holds a credential is never echoed
                return "(hidden)" if free and _looks_like_credential(value) else value

            out.append({"setting": f"{cat}.{key}",
                        "from": shown(stored.get((cat, key), _SPEC[(cat, key)]["value"])),
                        "to": shown(changes[cat][key])})
    return out


def apply_import(changes: dict[str, dict[str, Any]]) -> int:
    """Write *changes* (already planned) in one transaction: all of it or none of it.
    Returns how many settings were written."""
    _ensure_init()
    conn = get_conn()
    try:
        with conn:
            written = _write_values(conn, changes)
    finally:
        conn.close()
    for cat, values in changes.items():
        if values:
            _changed(cat, dict(values))
    return written


def reset_kept(cat: str) -> list[str]:
    """The settings of *cat* a reset leaves alone: its secrets (stored credentials an
    export never carries could not be got back, review-H157 m5)."""
    return sorted(spec["key"] for spec in DEFAULTS
                  if spec["category"] == cat and is_secret_setting(cat, spec["key"]))


def posture_overridden(cat: str) -> list[str]:
    """The settings of *cat* the selected product posture forces while it is selected:
    a reset puts the stored value back, but this one stays in effect (review-H157 n5)."""
    try:
        from agents.core import product_posture

        name = product_posture.normalize(get_value("product", "posture", product_posture.OFF))
        applies = product_posture.POSTURES[name].get("applies", {})
    except Exception:  # noqa: BLE001
        return []
    return sorted(k.split(".", 1)[1] for k in applies if k.startswith(cat + "."))


def _reset_specs(cat: str | None) -> list[dict[str, Any]] | None:
    """The declared settings a reset of *cat* (every category when None) may move: all
    but the secrets. None for a category nothing declares."""
    if cat is not None and not any(spec["category"] == cat for spec in DEFAULTS):
        return None
    return [spec for spec in DEFAULTS
            if (cat is None or spec["category"] == cat)
            and not is_secret_setting(spec["category"], spec["key"])]


def plan_reset(cat: str | None) -> dict[str, dict[str, Any]] | None:
    """H259 — what a reset of *cat* (every category when None) would write: each declared
    setting but a secret whose stored value is not its default, as ``{category: {key:
    default}}``. None for a category nothing declares."""
    specs = _reset_specs(cat)
    if specs is None:
        return None
    _ensure_init()
    conn = get_conn()
    try:
        stored = _stored_values(conn)
    finally:
        conn.close()
    plan: dict[str, dict[str, Any]] = {}
    for spec in specs:
        where = (spec["category"], spec["key"])
        if where not in stored or not _same_value(stored[where], spec["value"]):
            plan.setdefault(spec["category"], {})[spec["key"]] = spec["value"]
    return plan


#: How many resets are kept to undo; the oldest goes first.
RESETS_KEPT = 20


def _write_values(conn: sqlite3.Connection, changes: dict[str, dict[str, Any]]) -> int:
    written = 0
    for cat, values in changes.items():
        for key, value in values.items():
            spec = _SPEC[(cat, key)]
            stored = json.dumps(_encrypt_if_secret(key, value))
            cur = conn.execute("UPDATE settings SET value=? WHERE category=? AND key=?", (stored, cat, key))
            if cur.rowcount == 0:
                conn.execute("INSERT INTO settings (category, key, value, label, kind, opts) VALUES (?,?,?,?,?,?)",
                             (cat, key, stored, spec["label"], spec["kind"], json.dumps(spec.get("opts", []))))
            written += 1
    return written


def reset_settings(cat: str | None) -> tuple[dict[str, dict[str, Any]], int | None] | None:
    """H259 — reset *cat* (every category when None) to its declared values, secrets
    kept. The values it replaces are recorded in the same transaction, so
    :func:`undo_last_reset` can put them back. Returns ``(what moved, the record's id)``
    — ``({}, None)`` when nothing moved — or None for a category nothing declares."""
    plan = plan_reset(cat)
    if plan is None:
        return None
    if not plan:
        return {}, None
    conn = get_conn()
    try:
        with conn:
            stored = _stored_values(conn)
            before = {c: {k: stored.get((c, k), _SPEC[(c, k)]["value"]) for k in keys} for c, keys in plan.items()}
            _write_values(conn, plan)
            cur = conn.execute("INSERT INTO settings_resets (at, scope, before, after) VALUES (?,?,?,?)",
                               (time.time(), cat or "all", json.dumps(before), json.dumps(plan)))
            snap = cur.lastrowid
            conn.execute("DELETE FROM settings_resets WHERE id NOT IN "
                         "(SELECT id FROM settings_resets ORDER BY id DESC LIMIT ?)", (RESETS_KEPT,))
    finally:
        conn.close()
    for c, values in plan.items():
        _changed(c, dict(values))
    return plan, snap


def reset_category(cat: str) -> list[str] | None:
    """Put every declared setting of *cat* but its secrets back to its declared value;
    the keys that moved (``[]`` when none did), or None for a category nothing declares."""
    done = reset_settings(cat)
    if done is None:
        return None
    return sorted(done[0].get(cat, {}))


def _names(changes: dict[str, dict[str, Any]]) -> list[str]:
    return [f"{c}.{k}" for c in sorted(changes) for k in sorted(changes[c])]


def list_resets() -> list[dict[str, Any]]:
    """The recorded resets, newest first: when, what scope, which settings (never their
    values), and whether it was undone."""
    _ensure_init()
    conn = get_conn()
    try:
        rows = conn.execute("SELECT id, at, scope, after, undone_at FROM settings_resets ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "at": r["at"], "scope": r["scope"], "settings": _names(json.loads(r["after"])),
             "undone": r["undone_at"] is not None} for r in rows]


def undo_last_reset() -> dict[str, Any] | None:
    """H259 — put back what the latest reset not yet undone replaced. A setting changed
    since that reset is left as it is, and so is a value its declaration no longer
    accepts; both are named in ``skipped``. None when there is nothing to undo."""
    _ensure_init()
    conn = get_conn()
    try:
        with conn:
            row = conn.execute("SELECT id, scope, before, after FROM settings_resets "
                               "WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return None
            before, after = json.loads(row["before"]), json.loads(row["after"])
            stored = _stored_values(conn)
            restore: dict[str, dict[str, Any]] = {}
            skipped: list[dict[str, str]] = []
            for cat in sorted(before):
                for key in sorted(before[cat]):
                    name = f"{cat}.{key}"
                    if (cat, key) not in _SPEC:
                        skipped.append({"setting": name, "reason": "no longer declared"})
                    elif not _same_value(stored.get((cat, key)), after.get(cat, {}).get(key)):
                        skipped.append({"setting": name, "reason": "changed since the reset"})
                    elif errors := validate_category(cat, {key: before[cat][key]}):
                        skipped.append({"setting": name, "reason": "no longer valid: " + "; ".join(errors)})
                    else:
                        restore.setdefault(cat, {})[key] = before[cat][key]
            _write_values(conn, restore)
            conn.execute("UPDATE settings_resets SET undone_at=? WHERE id=?", (time.time(), row["id"]))
    finally:
        conn.close()
    for cat, values in restore.items():
        _changed(cat, dict(values))
    return {"id": row["id"], "scope": row["scope"], "restored": _names(restore), "skipped": skipped}


def reset_kept_all() -> list[str]:
    """Every secret setting, as ``category.key``: what a reset of every category leaves."""
    return sorted(f"{spec['category']}.{spec['key']}" for spec in DEFAULTS
                  if is_secret_setting(spec["category"], spec["key"]))


def posture_overridden_all() -> list[str]:
    """Every setting the selected product posture forces while it is selected."""
    try:
        from agents.core import product_posture

        name = product_posture.normalize(get_value("product", "posture", product_posture.OFF))
        return sorted(product_posture.POSTURES[name].get("applies", {}))
    except Exception:  # noqa: BLE001
        return []
