"""
settings_db.py — SQLite-backed settings store for the admin panel.
Seeds defaults from agents.yaml on first init.
"""

import json
import logging
import sqlite3
import threading
from typing import Any

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
"""

# ── default settings — seed values ────────────────────────────────

DEFAULTS: list[dict[str, Any]] = [
    # general
    dict(category="general", key="timezone",         value="Europe/Bucharest",    label="Timezone",           kind="select",  opts=["Europe/Bucharest","UTC","US/Eastern"]),
    dict(category="general", key="wake_words",       value=["jarvis","hub"],      label="Wake words",         kind="tags"),
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
    dict(category="llm",     key="claude_model",     value="claude-sonnet-4-20250514", label="Claude model",   kind="text"),
    dict(category="llm",     key="control_enabled",  value=True,                  label="LM Studio control (start/load/unload)", kind="toggle"),
    dict(category="llm",     key="chat_control",     value=True,                  label="LM Studio control via chat",            kind="toggle"),
    dict(category="llm",     key="hybrid_local_max", value=131072,                 label="Local routing threshold — prompts up to N input tokens stay local (0 = unlimited)", kind="number"),
    dict(category="llm",     key="hybrid_flash_max", value=1000000,                label="Cloud Flash routing threshold — above N input tokens escalates to Pro (0 = unlimited)", kind="number"),
    dict(category="llm",     key="tool_loop_enabled", value=False,                  label="Agent tool loop (experimental)", kind="toggle"),
    dict(category="llm",     key="tool_loop_max_iterations", value=8,               label="Agent tool-loop model-turn cap", kind="number"),
    # voice
    dict(category="voice",   key="stt_model_size",   value="medium",              label="STT model size",     kind="select",  opts=["tiny","base","small","medium","large"]),
    dict(category="voice",   key="stt_language",     value="ro",                  label="STT language",       kind="text"),
    dict(category="voice",   key="tts_voice",        value="en-GB-RyanNeural",    label="TTS voice",          kind="text"),
    dict(category="voice",   key="persona_voice_consent", value=False,           label="Allow cloned/persona voice playback (owner consent)", kind="toggle"),
    dict(category="voice",   key="sentence_streaming", value=False,               label="Sentence-level TTS streaming (H5.16) — speak the reply sentence-by-sentence so audio starts sooner", kind="toggle"),
    # security
    dict(category="security",key="guardrails_mode",  value="WARN",                label="Guardrails mode",    kind="select",  opts=["WARN","REDACT","BLOCK"]),
    dict(category="security",key="scan_input",       value=True,                  label="Scan user input",    kind="toggle"),
    dict(category="security",key="scan_output",      value=True,                  label="Scan LLM output",    kind="toggle"),
    dict(category="security",key="sandbox_timeout",  value=30,                    label="Sandbox timeout (s)",kind="number"),
    dict(category="security",key="sandbox_memory",   value=256,                   label="Sandbox max memory (MB)",kind="number"),
    # memory
    dict(category="memory",  key="max_turns",        value=100,                   label="Max turns per session",kind="number"),
    dict(category="memory",  key="context_window",   value=6,                     label="Context window (turns)",kind="number"),
    dict(category="memory",  key="context_compression", value=False,              label="Compress long context (hot path)", kind="toggle"),
    dict(category="memory",  key="compression_max_tokens", value=2000,            label="Context compression budget (tokens)", kind="number"),
    dict(category="memory",  key="compression_summarizer", value=False,           label="LLM summarizer for evicted context (strict-local only)", kind="toggle"),
    dict(category="memory",  key="compression_keep_first", value=0,               label="Protect first N turns from compression", kind="number"),
    dict(category="memory",  key="compression_summary_max_tokens", value=256,     label="Compression summary budget (tokens)", kind="number"),
    dict(category="memory",  key="persist",          value=True,                  label="Persist to disk",    kind="toggle"),
    # O26-P0.3 (F2): long-term recall was read via get_setting but never seeded,
    # so it could not be enabled from the admin UI at all (put_category refuses
    # unknown keys). Default stays OFF — the Product Posture / onboarding
    # consent step (O26-P2.4) is what flips it deliberately.
    dict(category="memory",  key="recall_enabled",   value=False,                 label="Long-term recall in prompts", kind="toggle"),
    dict(category="memory",  key="recall_top_k",     value=5,                     label="Recall hits per prompt", kind="number"),
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
    # channels
    dict(category="channels",key="rate_limit",       value=10,                    label="Gateway rate limit (msg/min)", kind="number"),
    dict(category="channels",key="web_enabled",      value=True,                  label="Web channel",        kind="toggle"),
    # plugins (one per plugin, enabled toggle)
    dict(category="plugins", key="weather",          value=True,                  label="Weather",            kind="toggle"),
    dict(category="plugins", key="news",             value=True,                  label="News",               kind="toggle"),
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
    # stark — analytics
    dict(category="plugins", key="stark_ga4_service_account", value="", label="Stark – GA4 Service Account JSON", kind="text"),
    dict(category="plugins", key="stark_ga4_property_id",     value="", label="Stark – GA4 Property ID",          kind="text"),
    # skills
    dict(category="skills",  key="auto_generate",    value=True,                  label="Auto-generate skills",kind="toggle"),
    dict(category="skills",  key="sandbox_enabled",  value=True,                  label="Sandbox execution",  kind="toggle"),
    dict(category="skills",  key="max_skills",       value=50,                    label="Max stored skills",  kind="number"),
    dict(category="skills",  key="import_source",    value="hermes",              label="Import source",      kind="select", opts=["hermes","openclaw","none"]),
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
    # mcp
    dict(category="mcp",     key="servers",          value=[],                    label="MCP servers",        kind="json"),
    # autonomy — Proactive Cortex (ORIZONT 6)
    dict(category="autonomy", key="mode",            value="auto", label="Autonomy mode (AUTO/ASK/OFF)", kind="select", opts=["auto","ask","off"]),
    dict(category="autonomy", key="earned_autonomy_enabled", value=False, label="Earn autonomy from proven outcomes", kind="toggle"),
    dict(category="autonomy", key="owner_chat_id",   value="",     label="Owner Telegram chat ID", kind="text"),
    dict(category="autonomy", key="cap_per_action",  value=50,     label="Money cap per action", kind="number"),
    dict(category="autonomy", key="daily_ceiling",   value=200,    label="Money daily ceiling",  kind="number"),
    dict(category="autonomy", key="interrupt_budget",value=4,      label="Urgent pushes per day", kind="number"),
    dict(category="autonomy", key="night_shift",     value=False,  label="Night shift enabled",  kind="toggle"),
    dict(category="autonomy", key="night_start",     value=23,     label="Night window start (h)", kind="number"),
    dict(category="autonomy", key="night_end",       value=6,      label="Night window end (h)", kind="number"),
    dict(category="autonomy", key="priority_senders", value=["andrei"], label="Priority email senders", kind="tags"),
    dict(category="autonomy", key="finance_min_ron",  value=2000.0,   label="Minimum balance threshold (RON)", kind="number"),
    dict(category="autonomy", key="finance_min_eur",  value=400.0,    label="Minimum balance threshold (EUR)", kind="number"),
    dict(category="autonomy", key="health_min_sleep", value=5.0,     label="Minimum sleep hours", kind="number"),
    dict(category="autonomy", key="health_min_hrv",   value=30.0,    label="Minimum HRV threshold (ms)", kind="number"),
    dict(category="autonomy", key="calendar_lead_time", value=30,     label="Calendar event lead time (min)", kind="number"),
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
    dict(category="retention", key="enabled",               value=False, label="Enable data-retention sweeps", kind="toggle"),
    dict(category="retention", key="conversation_ttl_days", value=90,    label="Delete conversation transcripts older than (days; 0 = keep forever)", kind="number"),
    dict(category="retention", key="audit_ttl_days",        value=365,   label="Prune audit-log rows older than (days; 0 = keep forever)", kind="number"),
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
        
    conn.commit()
    conn.close()

def get_all() -> dict[str, list[dict]]:
    _ensure_init()
    conn = get_conn()
    rows = conn.execute("SELECT category, key, value, label, kind, opts FROM settings ORDER BY category, key").fetchall()
    conn.close()
    groups: dict[str, list[dict]] = {}
    for r in rows:
        cat = r["category"]
        if cat not in groups:
            groups[cat] = []
        groups[cat].append({
            "key": r["key"],
            "value": _decrypt_if_secret(json.loads(r["value"])),
            "label": r["label"],
            "kind": r["kind"],
            "opts": json.loads(r["opts"]),
        })
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


def get_category(cat: str) -> list[dict]:
    _ensure_init()
    conn = get_conn()
    rows = conn.execute(
        "SELECT key, value, label, kind, opts FROM settings WHERE category=? ORDER BY key",
        (cat,),
    ).fetchall()
    conn.close()
    return [{
        "key": r["key"],
        "value": _decrypt_if_secret(json.loads(r["value"])),
        "label": r["label"],
        "kind": r["kind"],
        "opts": json.loads(r["opts"]),
    } for r in rows]


# ── settings integrity (AUD-8 / F10) ──────────────────────────────
# Validate an admin settings write against each key's declared schema (its
# DEFAULTS entry) before it is persisted, so a malformed value (wrong type, or
# off the select allow-list) is rejected with 422 instead of corrupting a setting
# that the rest of the system then reads back and trusts. Unknown keys are not an
# error here — put_category already ignores them.
_SPEC: dict[tuple[str, str], dict[str, Any]] = {(d["category"], d["key"]): d for d in DEFAULTS}


def _validate_value(key: str, value: Any, kind: str, opts: list) -> str | None:
    """Return an error string if *value* violates the *kind*'s schema, else None."""
    if kind == "toggle":
        if not isinstance(value, bool):
            return f"{key}: expected a boolean (toggle)"
    elif kind in ("number", "slider"):
        # bool is an int subclass — exclude it so a toggle value can't pass as a number.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{key}: expected a number"
    elif kind == "select":
        if value not in opts:
            return f"{key}: {value!r} is not one of {opts}"
    elif kind in ("text", "model-select"):
        if not isinstance(value, str):
            return f"{key}: expected a string"
    elif kind == "tags":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return f"{key}: expected a list of strings (tags)"
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
        if err:
            errors.append(err)
    return errors


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
    return updated, skipped

# ── init on first use (via _ensure_init) — NOT at import ─────────
