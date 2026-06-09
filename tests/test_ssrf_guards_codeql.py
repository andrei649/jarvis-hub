"""SSRF host-allowlist guards on the governed outbound clients (CodeQL hardening)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.writeback import _assert_allowed_host as wb_host
from agents.core.social import _assert_allowed_host as soc_host
from agents.core.autonomy.call_broker import _assert_allowed_host as call_host


def test_writeback_host_allowlist():
    assert wb_host("https://api.github.com/repos/a/b/issues") == "api.github.com"
    assert wb_host("https://api.notion.com/v1/pages") == "api.notion.com"
    assert wb_host("https://www.googleapis.com/calendar/v3/calendars/primary/events") == "www.googleapis.com"
    with pytest.raises(ValueError):
        wb_host("https://evil.example.com/x")
    with pytest.raises(ValueError):
        wb_host("http://169.254.169.254/latest/meta-data/")   # cloud-metadata SSRF target


def test_social_host_allowlist():
    assert soc_host("https://api.twitter.com/2/tweets") == "api.twitter.com"
    with pytest.raises(ValueError):
        soc_host("https://attacker.test/2/tweets")


def test_call_host_allowlist():
    assert call_host("https://api.twilio.com/2010-04-01/Accounts/AC/Calls.json") == "api.twilio.com"
    assert call_host("https://api.telnyx.com/v2/calls") == "api.telnyx.com"
    with pytest.raises(ValueError):
        call_host("https://127.0.0.1/x")
