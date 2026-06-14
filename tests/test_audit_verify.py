"""The audit log's Merkle chain is only tamper-EVIDENT if something verifies it.

Found 2026-06-10: AuditLogger.verify_chain() existed with zero callers — no
endpoint, no test. This adds both: unit coverage for the chain math (including
an actual tamper) and the new GET /api/security/audit/verify endpoint.
"""

import json
import sys
import time
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.security.audit import AuditLogger
from agents.core.security.types import SecurityEvent, SecurityEventType


def _logger_with_events(tmp_path, n=3) -> AuditLogger:
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    for i in range(n):
        audit.log(SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG,
            timestamp=time.time() + i,
            content_preview=f"event {i}",
            action_taken="logged",
        ))
    return audit


def test_chain_verifies_clean(tmp_path):
    audit = _logger_with_events(tmp_path)
    valid, first_bad = audit.verify_chain()
    assert valid is True and first_bad is None
    assert audit.count() == 3


def test_chain_detects_tampering(tmp_path):
    audit = _logger_with_events(tmp_path)
    # Tamper with a mid-chain row the way an attacker with file access would.
    audit._conn.execute(
        "UPDATE security_events SET content_preview='REWRITTEN HISTORY' WHERE id=2"
    )
    audit._conn.commit()
    valid, first_bad = audit.verify_chain()
    assert valid is False and first_bad == 2


def test_chain_detects_relinking(tmp_path):
    """Recomputing one row's hash without fixing successors still breaks the chain."""
    audit = _logger_with_events(tmp_path)
    audit._conn.execute("UPDATE security_events SET prev_hash='deadbeef' WHERE id=3")
    audit._conn.commit()
    valid, first_bad = audit.verify_chain()
    assert valid is False and first_bad == 3


async def test_verify_endpoint(tmp_path, monkeypatch):
    import agents.web as web
    from agents.core.routers.security import audit_verify

    class _Orch:
        audit = _logger_with_events(tmp_path)

    monkeypatch.setattr(web, "orch", _Orch())
    resp = await audit_verify()
    body = json.loads(resp.body)
    assert body == {"valid": True, "first_invalid_id": None, "entries": 3}


async def test_verify_endpoint_unavailable(monkeypatch):
    import agents.web as web
    from agents.core.routers.security import audit_verify

    monkeypatch.setattr(web, "orch", None)
    resp = await audit_verify()
    assert resp.status_code == 503
