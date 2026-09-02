"""An unconnected Google account must not log an ERROR on every autonomy tick.

From a real three-hour server log: from the moment the browser went quiet until
the process was stopped, this pair repeated every ~75s and never stopped —

    ERROR jarvis.plugins.gmail            Gmail list error: Gmail not authenticated …
    ERROR jarvis.plugins.google_calendar  Calendar list error: Google Calendar not authenticated …

The cadence is `system.autonomy_tick` (default 60s, `autonomy_coordinator.py`),
which runs `EventWatcher.observe()` → `EmailProbe`/`CalendarProbe` → these two
read paths. Nothing was wrong: the owner had simply never connected a Google
account. Two properties made it permanent:

1. The credential check raises inside `_request()`, *before* the breaker-decorated
   `_do_request()`, so the circuit breaker never saw the failures, never opened,
   and could never damp them.
2. The read path caught it as a generic exception and logged at ERROR.

Those ERROR lines feed `log_scanner.quick_scan` (every 900s), which counts new
ERROR/CRITICAL entries into `memory_logs/diagnostics.md` — so a disconnected
account manufactured a permanent, growing diagnostics signal about itself.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.plugins import oauth  # noqa: E402
from agents.core.plugins.gmail_plugin import GmailPlugin  # noqa: E402
from agents.core.plugins.google_calendar import GoogleCalendarPlugin  # noqa: E402

# (module under test, plugin factory, the read method the probes poll, log name)
POLLED_READS = [
    ("agents.core.plugins.gmail_plugin", GmailPlugin, "list_messages", "jarvis.plugins.gmail"),
    (
        "agents.core.plugins.google_calendar",
        GoogleCalendarPlugin,
        "list_events",
        "jarvis.plugins.google_calendar",
    ),
]


@pytest.fixture(autouse=True)
def _no_stored_token(monkeypatch):
    """No Google credential anywhere — the exact state the log was recorded in."""
    for module, _, _, _ in POLLED_READS:
        monkeypatch.setattr(f"{module}.load_token", lambda _service: None)
    oauth._unauthenticated_reported.clear()
    yield
    oauth._unauthenticated_reported.clear()


@pytest.mark.parametrize("module,factory,read,log_name", POLLED_READS)
def test_repeated_polling_of_an_unconnected_account_logs_once(
    caplog, module, factory, read, log_name
):
    plugin = factory()

    with caplog.at_level(logging.DEBUG, logger=log_name):
        for _ in range(20):  # ~25 minutes of autonomy ticks
            asyncio.run(getattr(plugin, read)())

    above_debug = [r for r in caplog.records if r.levelno > logging.DEBUG]
    assert len(above_debug) == 1, (
        f"{log_name} logged {len(above_debug)} lines for 20 polls of an "
        f"unconnected account: {[r.message for r in above_debug]}"
    )
    assert above_debug[0].levelno == logging.INFO, "not connected is not an error"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("module,factory,read,log_name", POLLED_READS)
def test_the_caller_still_sees_the_error_payload(module, factory, read, log_name):
    """Quieting the log must not change what the probes are handed.

    `EmailProbe`/`CalendarProbe` branch on `"error" in result[0]` and return no
    signals. That contract predates this fix and has to survive it.
    """
    result = asyncio.run(getattr(factory(), read)())

    assert isinstance(result, list) and len(result) == 1
    assert "error" in result[0]
    assert "not authenticated" in result[0]["error"]


@pytest.mark.parametrize("module,factory,read,log_name", POLLED_READS)
def test_reconnecting_then_disconnecting_reports_again(
    caplog, monkeypatch, module, factory, read, log_name
):
    """The latch is per-provider state, not a permanent gag."""
    plugin = factory()

    with caplog.at_level(logging.INFO, logger=log_name):
        asyncio.run(getattr(plugin, read)())  # reported
        asyncio.run(getattr(plugin, read)())  # suppressed

        # The owner connects the account: `_ensure_token` finds a token and
        # clears the latch.
        monkeypatch.setattr(
            f"{module}.load_token", lambda _service: {"access_token": "tok"}
        )
        asyncio.run(plugin._ensure_token())

        # …and later revokes it.
        plugin.access_token = ""
        monkeypatch.setattr(f"{module}.load_token", lambda _service: None)
        asyncio.run(getattr(plugin, read)())

    not_connected = [r for r in caplog.records if "is not connected" in r.message]
    assert len(not_connected) == 2, [r.message for r in caplog.records]


def test_the_credential_check_bypasses_the_circuit_breaker_by_construction():
    """Why the log fix is the right one: the breaker cannot help here.

    `NotAuthenticated` is raised by `_request()` before `_do_request()` — the
    method the `resilient_call` decorator wraps — so no amount of breaker tuning
    would ever have suppressed these lines. Pinning it stops someone "fixing"
    this later by lowering a threshold.
    """
    from agents.core.resilience import _circuit_breakers

    for key in ("plugin:gmail", "plugin:calendar"):
        _circuit_breakers.pop(key, None)

    for _, factory, read, _ in POLLED_READS:
        for _ in range(10):
            asyncio.run(getattr(factory(), read)())

    assert "plugin:gmail" not in _circuit_breakers
    assert "plugin:calendar" not in _circuit_breakers


def test_not_authenticated_is_still_a_runtime_error():
    """Existing `except RuntimeError` handlers around these plugins keep working."""
    assert issubclass(oauth.NotAuthenticated, RuntimeError)
