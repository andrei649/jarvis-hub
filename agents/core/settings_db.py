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
    # voice
    dict(category="voice",   key="stt_model_size",   value="medium",              label="STT model size",     kind="select",  opts=["tiny","base","small","medium","large"]),
    dict(category="voice",   key="stt_language",     value="ro",                  label="STT language",       kind="text"),
    dict(category="voice",   key="tts_voice",        value="en-GB-RyanNeural",    label="TTS voice",          kind="text"),
    # security
    dict(category="security",key="guardrails_mode",  value="WARN",                label="Guardrails mode",    kind="select",  opts=["WARN","REDACT","BLOCK"]),
    dict(category="security",key="scan_input",       value=True,                  label="Scan user input",    kind="toggle"),
    dict(category="security",key="scan_output",      value=True,                  label="Scan LLM output",    kind="toggle"),
    dict(category="security",key="sandbox_timeout",  value=30,                    label="Sandbox timeout (s)",kind="number"),
    dict(category="security",key="sandbox_memory",   value=256,                   label="Sandbox max memory (MB)",kind="number"),
    # memory
    dict(category="memory",  key="max_turns",        value=100,                   label="Max turns per session",kind="number"),
    dict(category="memory",  key="context_window",   value=6,                     label="Context window (turns)",kind="number"),
    dict(category="memory",  key="persist",          value=True,                  label="Persist to disk",    kind="toggle"),
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
    # system
    dict(category="system",  key="log_level",        value="INFO",                label="Log level",          kind="select", opts=["DEBUG","INFO","WARNING","ERROR"]),
    dict(category="system",  key="poll_interval",    value=10,                    label="Poll interval (s)",  kind="number"),
    # mcp
    dict(category="mcp",     key="servers",          value=[],                    label="MCP servers",        kind="json"),
    # autonomy — Proactive Cortex (ORIZONT 6)
    dict(category="autonomy", key="mode",            value="auto", label="Autonomy mode (AUTO/ASK/OFF)", kind="select", opts=["auto","ask","off"]),
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
    dict(category="system",  key="error_backlog_sync_enabled", value=True, label="Error backlog sync enabled", kind="toggle"),
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
            "value": json.loads(r["value"]),
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
        return json.loads(row["value"])
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
        "value": json.loads(r["value"]),
        "label": r["label"],
        "kind": r["kind"],
        "opts": json.loads(r["opts"]),
    } for r in rows]

def put_category(cat: str, data: dict[str, Any]) -> tuple[int, list[str]]:
    _ensure_init()
    conn = get_conn()
    updated = 0
    skipped = []
    for key, value in data.items():
        cur = conn.execute("SELECT key FROM settings WHERE category=? AND key=?", (cat, key))
        if cur.fetchone():
            conn.execute("UPDATE settings SET value=? WHERE category=? AND key=?", (json.dumps(value), cat, key))
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
