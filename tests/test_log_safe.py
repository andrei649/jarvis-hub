"""log_safe — neutralize CR/LF before logging (py/log-injection guard)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.log_safe import log_safe


def test_strips_crlf():
    assert log_safe("a\nb\r\nc") == "a b  c"          # CR and LF → spaces
    assert "\n" not in log_safe("forged\nINFO: fake log line")
    assert "\r" not in log_safe("x\ry")


def test_truncates_and_stringifies():
    assert len(log_safe("x" * 500)) == 200
    assert log_safe(12345) == "12345"
    assert log_safe(None) == "None"
