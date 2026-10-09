"""Nous result invariants survive dependency faults and Python optimization."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import json
import sys
from contextlib import contextmanager

import httpx

from agents.core.llm.nous_auth import NousAuthError
from tests.test_h277_nous_auth import _Store, _jwt, _service

scenario = sys.argv[1]
now = [1_000]
requests = []
store = _Store()
old = _jwt(now[0] + 1_000 if scenario == "cached_formatter" else now[0] - 1)
fresh = _jwt(now[0] + 500)
store.rows["default"] = {
    "access_token": old, "refresh_token": "synthetic-old-grant",
    "scope": "inference:invoke", "portal_base_url": "https://portal.nousresearch.com",
    "client_id": "nerva-test-public-client",
}

def respond(request):
    requests.append(request)
    return httpx.Response(200, json={
        "access_token": fresh, "refresh_token": "synthetic-rotated-grant",
        "scope": "inference:invoke", "expires_in": 500,
    })

if scenario == "suppressed_store_error":
    class SuppressingStore(_Store):
        @contextmanager
        def transaction(self, profile="default"):
            try:
                with super().transaction(profile) as state:
                    yield state
            except NousAuthError:
                pass
    store = SuppressingStore()

service = _service(store, respond, now)
service._credentials = lambda *args: None
try:
    if scenario == "suppressed_store_error":
        result = service.poll_login("default", "synthetic-absent-login")
    else:
        result = service.prepare_credentials(force_refresh=scenario == "rotated_formatter")
except NousAuthError as exc:
    result = {
        "reason": exc.reason, "optimized": bool(sys.flags.optimize),
        "requests": len(requests),
        "rotation_preserved": store.read().get("refresh_token") == "synthetic-rotated-grant",
    }
else:
    result = {"returned_null": result is None}
print(json.dumps(result))
'''


@pytest.mark.parametrize('optimized', [False, True])
@pytest.mark.parametrize('scenario,requests,rotated', [
    ('cached_formatter', 0, False),
    ('rotated_formatter', 1, True),
    ('suppressed_store_error', 0, False),
])
def test_missing_result_is_typed_failure_even_without_assertions(optimized, scenario, requests, rotated):
    env = {**os.environ, 'PYTHONPATH': str(REPO), 'JARVIS_TESTING': '1'}
    command = [sys.executable, *(['-O'] if optimized else []), '-c', PROBE, scenario]
    result = subprocess.run(command, cwd=REPO, env=env, capture_output=True,
                            text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        'reason': 'temporarily_unavailable', 'optimized': optimized,
        'requests': requests, 'rotation_preserved': rotated,
    }
