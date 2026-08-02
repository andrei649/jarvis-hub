"""Q5 — SEC-065 live guardrails-mode propagation + SEC-071 audit preview redaction.

SEC-065: the engine's mode was frozen at load_agents() time — flipping
`security.guardrails_mode` in the admin panel changed the posture screen but
not the running engine (posture said BLOCK, scans ran WARN). The engine now
exposes `apply_settings`, and the 30s settings watcher re-pushes the knob onto
the live object (bind() copies the mode per request, so it takes effect on the
next turn).

SEC-071: `content_preview` — the assistant reply's first 100 chars — was
persisted verbatim into audit.db. A reply that quoted a key put a durable
plaintext secret on disk, outside retention control. `AuditLogger.log()` now
redacts the preview with the same scanners and `[REDACTED:<pattern>]`
convention AUD-12 established for findings, before the chain hash.
"""

import sqlite3
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.security.audit import AuditLogger  # noqa: E402
from agents.core.security.guardrails import GuardrailsEngine  # noqa: E402
from agents.core.security.scanner import SecretScanner  # noqa: E402
from agents.core.security.types import (  # noqa: E402
    RedactionMode,
    SecurityEvent,
    SecurityEventType,
)

# ── SEC-065: the engine half — a live, name-keyed mode setter ───────────────

def test_apply_settings_updates_mode_by_name_and_bind_picks_it_up():
    engine = GuardrailsEngine(mode=RedactionMode.WARN)

    engine.apply_settings("BLOCK")

    assert engine._mode is RedactionMode.BLOCK
    assert engine.stats()["mode"] == "block"
    # bind() copies the mode per request — the next turn sees the new mode
    assert engine.bind(backend=None)._mode is RedactionMode.BLOCK


def test_apply_settings_ignores_garbage_and_keeps_the_current_mode():
    engine = GuardrailsEngine(mode=RedactionMode.REDACT)

    engine.apply_settings("BANANAS")
    assert engine._mode is RedactionMode.REDACT
    engine.apply_settings(None)
    assert engine._mode is RedactionMode.REDACT

    # scan flags ride along, independently of a bad mode value
    engine.apply_settings("BANANAS", scan_input=False, scan_output=False)
    assert engine._scan_input is False and engine._scan_output is False


# ── SEC-071: the audit half — preview masked at rest ────────────────────────

_PLANT = "AKIAIOSFODNN7EXAMPLE"  # classic AWS access-key shape


def _plant_is_scannable() -> bool:
    result = SecretScanner().scan(f"key {_PLANT} end")
    return any(f.matched_text == _PLANT for f in result.findings)


def test_content_preview_masked_at_rest(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    assert _plant_is_scannable(), "test invariant: the plant must match a scanner pattern"
    db = str(tmp_path / "audit.db")
    audit = AuditLogger(db_path=db)

    audit.log(SecurityEvent(
        event_type=SecurityEventType.LLM_CALL,
        timestamp=time.time(),
        content_preview=f"the reply quoted {_PLANT} verbatim",
        action_taken="logged",
    ))

    conn = sqlite3.connect(db)
    try:
        preview = conn.execute("SELECT content_preview FROM security_events").fetchone()[0]
    finally:
        conn.close()
    assert _PLANT not in preview, "a durable plaintext secret sat in audit.db (SEC-071)"
    assert "[REDACTED:" in preview
    assert "the reply quoted" in preview  # surrounding prose survives


def test_preview_redaction_is_idempotent_and_keeps_the_chain_valid(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    db = str(tmp_path / "audit.db")
    audit = AuditLogger(db_path=db)

    audit.log(SecurityEvent(
        event_type=SecurityEventType.LLM_CALL,
        timestamp=time.time(),
        content_preview="already [REDACTED:aws_access_key] masked",
        action_taken="logged",
    ))
    audit.log(SecurityEvent(
        event_type=SecurityEventType.LLM_CALL,
        timestamp=time.time() + 1,
        content_preview=f"fresh {_PLANT} plant",
        action_taken="logged",
    ))

    conn = sqlite3.connect(db)
    try:
        rows = [r[0] for r in conn.execute(
            "SELECT content_preview FROM security_events ORDER BY id"
        ).fetchall()]
    finally:
        conn.close()
    assert rows[0] == "already [REDACTED:aws_access_key] masked"  # no double-masking
    assert _PLANT not in rows[1]

    ok, detail = audit.verify_chain()
    assert ok, f"redaction must happen BEFORE the chain hash, not after: {detail}"


# ── SEC-065: the watcher half — the live engine hears the knob ──────────────


def _bare_orch():
    from agents.core import orchestrator as orch_mod

    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.lmstudio = None
    orch.llm_router = None
    orch.memory = None
    return orch_mod, orch


def test_guardrails_mode_resyncs_live_from_the_settings_watcher(monkeypatch):
    orch_mod, orch = _bare_orch()
    orch.security = GuardrailsEngine(mode=RedactionMode.WARN)

    monkeypatch.setattr(orch_mod, "_get_settings", lambda: {
        "security": [{"key": "guardrails_mode", "value": "BLOCK"}],
    })
    orch.load_runtime_settings()

    assert orch.security._mode is RedactionMode.BLOCK, (
        "SEC-065: posture said BLOCK while the live engine kept scanning in WARN"
    )


def test_guardrails_resync_ignores_garbage_and_survives_a_missing_engine(monkeypatch):
    orch_mod, orch = _bare_orch()
    orch.security = GuardrailsEngine(mode=RedactionMode.REDACT)

    monkeypatch.setattr(orch_mod, "_get_settings", lambda: {
        "security": [{"key": "guardrails_mode", "value": "BANANAS"}],
    })
    orch.load_runtime_settings()
    assert orch.security._mode is RedactionMode.REDACT  # garbage keeps current

    orch2_mod, orch2 = _bare_orch()  # no .security attribute at all
    monkeypatch.setattr(orch2_mod, "_get_settings", lambda: {
        "security": [{"key": "guardrails_mode", "value": "BLOCK"}],
    })
    orch2.load_runtime_settings()  # must not raise
    assert orch2.get_setting("security.guardrails_mode") == "BLOCK"


def test_preview_redacts_before_the_truncation_cap(tmp_path, monkeypatch):
    """Truncating first can split a key so no pattern matches — a raw prefix
    would land on disk. preview() redacts on the full text, then caps."""
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    # The key STRADDLES the cap: chars 90..110. Truncate-first keeps a 10-char
    # raw prefix ("AKIAIOSFOD") that no pattern can match afterwards.
    long_reply = ("x" * 90) + _PLANT + " tail"

    capped = audit.preview(long_reply, 100)

    assert "AKIA" not in capped, "truncate-first left a raw key prefix on disk"
    assert len(capped) <= 100
