"""The collection-time half of the log-redactor isolation contract.

`agents/run.py` calls `setup_logging()` at MODULE level, so importing it installs
a process-wide `SecretRedactionFilter` while pytest is still COLLECTING — before
any fixture has run. Eight test files import it. `agents/web.py` does the same
from its FastAPI lifespan, so any test that drives the app installs it again.

A snapshot-and-restore fixture cannot see that: the filter is already there when
it takes its "before" picture, so it is preserved for the rest of the worker's
life. `tests/conftest.py::_isolate_log_redaction` therefore strips BEFORE each
test as well as after, and this module pins that half by reproducing the exact
shape — an install at import time, in a module pytest collects.

Without it the only coverage is of installs that happen *inside* a test, which
teardown alone would handle, and the CI failure this was written for
(`test_soul_injection_guard.py::test_a_truncated_soul_logs_a_warning_naming_the_path`,
red on gw0 with the path arriving as `[REDACTED:high_entropy_secret].md`) would
come back unnoticed.
"""

import logging

from agents.core.security import log_redaction as lr

# Deliberately at import: this is the `agents/run.py` shape, not an oversight.
_INSTALLED_AT_COLLECTION = lr.install_log_redaction_everywhere()


def _count_redactors() -> int:
    """By class name — the two import paths give two distinct classes."""

    def is_redactor(obj) -> bool:
        cls = type(obj)
        return (cls.__name__ == "SecretRedactionFilter"
                and cls.__module__.endswith("security.log_redaction"))

    loggers = [logging.getLogger()]
    loggers += [obj for obj in list(logging.Logger.manager.loggerDict.values())
                if isinstance(obj, logging.Logger)]
    return sum(
        is_redactor(f)
        for lg in loggers
        for handler in (getattr(lg, "handlers", ()) or ())
        for f in (getattr(handler, "filters", ()) or ())
    )


def test_a_redactor_installed_at_collection_does_not_reach_a_test():
    assert _count_redactors() == 0, (
        "a `SecretRedactionFilter` installed while this module was being imported "
        "survived into the test body; tests/conftest.py::_isolate_log_redaction is "
        "restoring a snapshot instead of stripping before the test, so every test "
        "in this worker is reading records the secret scanner has rewritten"
    )


def test_the_install_at_import_actually_happened():
    """Premise check. If this goes to zero the test above proves nothing.

    It reads the return value captured at import rather than re-counting, because
    by the time any test body runs the fixture has already stripped the filter —
    which is the whole point of the test above.
    """
    assert _INSTALLED_AT_COLLECTION > 0, (
        "nothing was installed at import, so the isolation pin above is vacuous — "
        "either redaction is disabled in this environment (JARVIS_LOG_REDACTION) "
        "or no handler existed yet at collection time"
    )
