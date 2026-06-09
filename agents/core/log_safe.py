"""
log_safe.py — neutralize untrusted values before they enter a log entry.

CodeQL `py/log-injection`: a value that reaches a log entry and contains CR/LF
lets an attacker forge or split log lines. `log_safe` strips those (and truncates)
so inbound/request-derived values can be logged safely.
"""

from __future__ import annotations


def log_safe(value, limit: int = 200) -> str:
    """Strip CR/LF (forged-log-line vector) and truncate a value for safe logging."""
    return str(value).replace("\r", " ").replace("\n", " ")[:limit]
