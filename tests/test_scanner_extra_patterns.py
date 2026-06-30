"""AUD-18 — configurable extra redaction patterns for SecretScanner.

A deployment can scrub its own secret formats via JARVIS_SCANNER_EXTRA_PATTERNS
(JSON {name: regex}) or the constructor arg. Default (no config) is unchanged; a
bad config (non-JSON / non-object / invalid regex) never breaks scanning.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.security.scanner import (  # noqa: E402
    SecretScanner,
    _extra_patterns_from_env,
)

CUSTOM = "MYCO-1234567890"   # a fake internal token format no built-in matches


def test_default_does_not_match_custom_format():
    # without any extra config, the custom format is not flagged → byte-identical
    assert SecretScanner().scan(CUSTOM).findings == []
    assert "REDACTED" not in SecretScanner().redact(CUSTOM)


def test_extra_pattern_via_constructor_redacts():
    s = SecretScanner(extra_patterns={"myco": r"MYCO-[0-9]{10}"})
    names = [f.pattern_name for f in s.scan(CUSTOM).findings]
    assert "myco" in names
    assert s.redact(CUSTOM) == "[REDACTED:myco]"


def test_extra_pattern_via_env(monkeypatch):
    monkeypatch.setenv("JARVIS_SCANNER_EXTRA_PATTERNS", '{"myco": "MYCO-[0-9]{10}"}')
    s = SecretScanner()
    assert "myco" in [f.pattern_name for f in s.scan(CUSTOM).findings]


def test_constructor_arg_wins_over_env(monkeypatch):
    monkeypatch.setenv("JARVIS_SCANNER_EXTRA_PATTERNS", '{"fromenv": "X"}')
    s = SecretScanner(extra_patterns={"fromarg": r"MYCO-[0-9]{10}"})
    names = {f.pattern_name for f in s.scan(CUSTOM).findings}
    assert "fromarg" in names and "fromenv" not in names


def test_invalid_regex_is_skipped_not_fatal():
    # a malformed regex must be ignored; the scanner still works for built-ins
    s = SecretScanner(extra_patterns={"bad": "([", "good": r"MYCO-[0-9]{10}"})
    names = [f.pattern_name for f in s.scan(CUSTOM).findings]
    assert "good" in names and "bad" not in names
    # built-in detection unaffected
    assert s.scan("sk-ant-abcdefghij0123456789").findings


def test_builtin_patterns_still_fire_with_extras():
    s = SecretScanner(extra_patterns={"myco": r"MYCO-[0-9]{10}"})
    assert any(f.pattern_name == "anthropic_key"
               for f in s.scan("token sk-ant-abcdefghij0123456789").findings)


# ── env parsing ────────────────────────────────────────────────────────────

def test_env_parse_empty_and_missing():
    assert _extra_patterns_from_env({}) == {}
    assert _extra_patterns_from_env({"JARVIS_SCANNER_EXTRA_PATTERNS": "   "}) == {}


def test_env_parse_non_json_and_non_object():
    assert _extra_patterns_from_env({"JARVIS_SCANNER_EXTRA_PATTERNS": "not json"}) == {}
    assert _extra_patterns_from_env({"JARVIS_SCANNER_EXTRA_PATTERNS": '["a","b"]'}) == {}


def test_env_parse_valid_object():
    out = _extra_patterns_from_env({"JARVIS_SCANNER_EXTRA_PATTERNS": '{"a": "x", "b": "y"}'})
    assert out == {"a": "x", "b": "y"}
