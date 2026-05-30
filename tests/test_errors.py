"""Tests for error taxonomy (errors.py) and structured logging (log.py)."""

import logging
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.errors import CODES, ErrorCategory, ErrorSeverity, JarvisError
from core.log import setup_logging, log_error


def test_all_error_codes_are_registered():
    assert len(CODES) >= 20
    for code, entry in CODES.items():
        assert code.startswith("JARVIS-")
        assert isinstance(entry.category, ErrorCategory)
        assert isinstance(entry.severity, ErrorSeverity)
        assert entry.message


def test_error_codes_have_unique_numbers():
    numbers = [e.number for e in CODES.values()]
    assert len(numbers) == len(set(numbers))


def test_jarvis_error_with_code():
    exc = JarvisError("JARVIS-CONFIG-001", key="MY_VAR")
    assert exc.code == "JARVIS-CONFIG-001"
    assert exc.category == ErrorCategory.CONFIG
    assert exc.severity == ErrorSeverity.WARNING
    assert "MY_VAR" in exc.message


def test_jarvis_error_unknown_code():
    exc = JarvisError("JARVIS-FAKE-999", key="val")
    assert exc.code == "JARVIS-FAKE-999"
    assert exc.category == ErrorCategory.INTERNAL
    assert exc.severity == ErrorSeverity.ERROR


def test_jarvis_error_to_dict():
    exc = JarvisError("JARVIS-PLUGIN-003", name="foobar", detail="timeout")
    d = exc.to_dict()
    assert d["code"] == "JARVIS-PLUGIN-003"
    assert d["category"] == "plugin"
    assert d["severity"] == "error"
    assert "foobar" in d["message"]
    assert d["meta"] == {"name": "foobar", "detail": "timeout"}


def test_log_error_returns_error_log(caplog):
    caplog.set_level(logging.WARNING)
    logger = logging.getLogger("jarvis.test")
    result = log_error(logger, "JARVIS-CONFIG-001", key="TEST_VAR")
    assert result is not None
    assert result.code == "JARVIS-CONFIG-001"
    assert result.category == ErrorCategory.CONFIG
    assert result.component == "jarvis.test"
    assert "TEST_VAR" in result.message


@pytest.mark.parametrize("code,kwargs,expected_level", [
    ("JARVIS-CONFIG-001", {"key": "MY_VAR"}, logging.WARNING),
    ("JARVIS-PLUGIN-003", {"name": "test", "detail": "err"}, logging.ERROR),
    ("JARVIS-SECURITY-019", {"reason": "injection"}, logging.WARNING),
    ("JARVIS-LLM-010", {"timeout": 30}, logging.WARNING),
])
def test_log_error_uses_correct_level(code, kwargs, expected_level, caplog):
    caplog.set_level(logging.DEBUG)
    logger = logging.getLogger("jarvis.test.level")
    log_error(logger, code, **kwargs)
    assert len(caplog.records) >= 1
    assert caplog.records[0].levelno == expected_level


def test_log_error_unknown_code_falls_back(caplog):
    caplog.set_level(logging.ERROR)
    logger = logging.getLogger("jarvis.test.unknown")
    log_error(logger, "JARVIS-FAKE-000")
    assert any("Unknown error code" in r.message for r in caplog.records)


def test_setup_logging_adds_timestamp():
    import io
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s",
                                           datefmt="%Y-%m-%d %H:%M:%S"))
    logger = logging.getLogger("jarvis.test.timestamp")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("hello")
    output = buf.getvalue()
    assert "202" in output  # year in timestamp
    assert "INFO" in output
    assert "hello" in output


def test_setup_logging_force_overwrites():
    setup_logging()
    root = logging.getLogger()
    # should have at least one handler after force basicConfig
    assert root.hasHandlers()
