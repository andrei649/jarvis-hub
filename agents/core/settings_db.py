"""
settings_db.py — SQLite-backed settings store for the admin panel.
Seeds defaults from agents.yaml on first init.
"""

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.settings")

DB_PATH = Path(__file__).parent.parent.parent / "memory_logs" / "settings.db"

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
    dict(category="general", key="addressing",       value="sir",                 label="Addressing mode",    kind="select",  opts=["sir","boss","none"]),
    dict(category="general", key="default_tts",      value="kokoro-en-british-male-1", label="Default TTS voice", kind="text"),
    dict(category="general", key="ui_density",       value="normal",              label="UI density",         kind="select",  opts=["normal","compact"]),
    dict(category="general", key="dev_mode",         value=False,                 label="Developer mode",     kind="toggle"),
    # llm
    dict(category="llm",     key="backend_type",     value="auto",                label="Backend type",       kind="select",  opts=["auto","lm-studio","ollama"]),
    dict(category="llm",     key="lm_studio_url",    value="http://localhost:1234",  label="LM Studio URL",    kind="text"),
    dict(category="llm",     key="ollama_url",       value="http://localhost:11434", label="Ollama URL",       kind="text"),
    dict(category="llm",     key="default_model",    value="google/gemma-4-31b-a4b", label="Default model",    kind="text"),
    dict(category="llm",     key="temperature",      value=0.7,                   label="Temperature",        kind="slider"),
    dict(category="llm",     key="max_tokens",       value=1024,                  label="Max tokens",         kind="number"),
    dict(category="llm",     key="cloud_fallback",   value="on-demand",           label="Cloud LLM fallback", kind="select",  opts=["never","on-demand","always"]),
    # voice
    dict(category="voice",   key="stt_model_size",   value="medium",              label="STT model size",     kind="select",  opts=["tiny","base","small","medium","large"]),
    dict(category="voice",   key="stt_language",     value="ro",                  label="STT language",       kind="text"),
    dict(category="voice",   key="tts_voice",        value="en-GB-RyanNeural",    label="TTS voice",          kind="text"),
    dict(category="voice",   key="wake_threshold",   value=0.5,                   label="Wake word threshold",kind="slider"),
    dict(category="voice",   key="silence_sec",      value=1.5,                   label="Silence timeout (s)",kind="number"),
    dict(category="voice",   key="max_recording",    value=15,                    label="Max recording (s)",   kind="number"),
    dict(category="voice",   key="volume_threshold", value=200,                   label="Volume threshold",    kind="number"),
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
    # agents
    dict(category="agents",  key="auto_scale",       value=False,                 label="Auto-scale agents",  kind="toggle"),
    dict(category="agents",  key="cardinality_cap",  value=18,                    label="Max agents",         kind="number"),
    dict(category="agents",  key="promote_on_use",   value=20,                    label="Promote after uses", kind="number"),
    dict(category="agents",  key="demote_on_inactive",value=2,                    label="Demote after months", kind="number"),
    # skills
    dict(category="skills",  key="auto_generate",    value=True,                  label="Auto-generate skills",kind="toggle"),
    dict(category="skills",  key="sandbox_enabled",  value=True,                  label="Sandbox execution",  kind="toggle"),
    dict(category="skills",  key="max_skills",       value=50,                    label="Max stored skills",  kind="number"),
    dict(category="skills",  key="import_source",    value="hermes",              label="Import source",      kind="select", opts=["hermes","openclaw","none"]),
    # system
    dict(category="system",  key="log_level",        value="INFO",                label="Log level",          kind="select", opts=["DEBUG","INFO","WARNING","ERROR"]),
    dict(category="system",  key="heartbeat_interval",value=60,                   label="Heartbeat interval (s)", kind="number"),
    dict(category="system",  key="poll_interval",    value=10,                    label="Poll interval (s)",  kind="number"),
    dict(category="system",  key="theme",            value="dark",                label="Theme",              kind="select", opts=["dark","light"]),
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
    conn = sqlite3.connect(str(DB_PATH))
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
    existing = conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
    if existing == 0:
        for row in DEFAULTS:
            conn.execute(
                "INSERT OR IGNORE INTO settings (category, key, value, label, kind, opts) VALUES (?,?,?,?,?,?)",
                (row["category"], row["key"], json.dumps(row["value"]), row["label"], row["kind"], json.dumps(row.get("opts", []))),
            )
        logger.info(f"Seeded {len(DEFAULTS)} default settings")
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

def put_category(cat: str, data: dict[str, Any]) -> int:
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
        logger.warning(f"put_category({cat}): ignored unknown keys: {skipped}")
    return updated

# ── init on first use (via _ensure_init) — NOT at import ─────────
