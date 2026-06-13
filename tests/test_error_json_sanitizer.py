"""Lock the CWE-209 sanitizer (web_helpers.error_json).

Error responses must expose only a controlled, static message to the client and
keep the raw exception detail server-side (logs). This guards the fix for the
CodeQL "information exposure through an exception" finding so it can't regress.
"""

import json
import logging
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.web_helpers import error_json  # noqa: E402


def _body(resp) -> dict:
    return json.loads(bytes(resp.body).decode())


def test_error_json_hides_exception_detail_from_client():
    exc = FileNotFoundError("/home/user/secret/path/skill.py missing")
    resp = error_json(exc, 404, "skill not found")
    body = _body(resp)
    assert resp.status_code == 404
    assert body == {"error": "skill not found"}
    # the sensitive detail (a filesystem path) never reaches the client
    raw = bytes(resp.body).decode()
    assert "secret" not in raw and "skill.py" not in raw


def test_error_json_preserves_extra_contract_keys():
    resp = error_json(ValueError("internal boom"), 200, "memory search failed",
                      extra={"results": [], "query": "q", "total": 0})
    body = _body(resp)
    assert body == {"results": [], "query": "q", "total": 0, "error": "memory search failed"}
    assert "boom" not in bytes(resp.body).decode()


def test_error_json_logs_the_detail_server_side(caplog):
    with caplog.at_level(logging.WARNING, logger="jarvis.web"):
        error_json(RuntimeError("trace: /opt/app/x.py line 42"), 500, "internal error")
    # the full detail is logged (for ops), even though the client never sees it
    assert any("trace: /opt/app/x.py line 42" in r.getMessage() for r in caplog.records)


def test_error_json_sets_no_store_headers():
    resp = error_json(ValueError("x"), 400, "bad request")
    assert "no-store" in resp.headers.get("Cache-Control", "")
