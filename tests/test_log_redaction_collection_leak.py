"""The out-of-test half of the log-redactor isolation contract.

`agents/run.py` calls `setup_logging()` at MODULE level, so importing it installs
a process-wide `SecretRedactionFilter` while pytest is still COLLECTING — before
any fixture has run. Eight test files import it. `agents/web.py` does the same
from its FastAPI lifespan, so any test that drives the app installs it again.

A snapshot-and-restore fixture cannot see that: the filter is already there when
it takes its "before" picture, so it is preserved for the rest of the worker's
life. `tests/conftest.py::_isolate_log_redaction` therefore strips BEFORE each
test as well as after, and this module pins that half.

**Why a module-scoped fixture rather than an install at import.** The first
version of this file did install at import, which is the literal shape — and
adversarial review showed the assertion was VACUOUS in every realistic run. The
conftest fixture's *teardown* strip removes the collection-time filter as soon as
any other test finishes, and under `pytest tests/ -n auto --dist loadfile` this
file is never the first on its worker. So the filter was always already gone and
the assertion passed no matter what the fixture did: reverting the setup strip
left the suite green.

A module-scoped autouse fixture fixes that without weakening the claim. Fixtures
run highest-scope-first, so it installs immediately before this module's first
test and *after* any previous test's teardown — the same "installed outside any
test's own scope" condition, but reachable in every ordering.
"""

import logging

import pytest

from agents.core.security import log_redaction as lr


def _count_redactors() -> int:
    """By class name — the two import paths give two distinct classes.

    `agents/` is on `sys.path`, so `core.security.log_redaction` and
    `agents.core.security.log_redaction` are separate modules over one file. An
    `isinstance` check against one reports a handler carrying the other as clean;
    that is exactly how the first attempt at this cleanup silently did nothing.
    """

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


def _isolate_fixture_body(request):
    """The conftest fixture's own generator function, driven by hand.

    Found through pytest's plugin manager, which is where a conftest module lives
    once pytest has loaded it — importing `conftest` by name does not work here,
    and importing it by path would re-run its module-level side effects (it
    mkdtemps a data root and registers an atexit cleanup).

    Driving the generator is the only way to observe the fixture's SETUP
    separately from its teardown, and setup is the half that matters here.
    """
    for plugin in request.config.pluginmanager.get_plugins():
        fn = getattr(plugin, "_isolate_log_redaction", None)
        if fn is None:
            continue
        path = str(getattr(plugin, "__file__", "") or "")
        if path.endswith("conftest.py"):
            return getattr(fn, "__wrapped__", fn)
    pytest.fail(
        "could not find tests/conftest.py::_isolate_log_redaction through the "
        "plugin manager; if it was renamed or moved, re-point this pin rather "
        "than deleting it — it is the only check that the fixture strips at SETUP"
    )


def test_the_fixture_strips_before_the_test_and_not_only_after(request):
    """The pin, and it fails the moment conftest goes back to teardown-only.

    Installs process-wide the way `agents/run.py` does at import, then drives one
    fresh instance of `_isolate_log_redaction` and checks the filter is gone by the
    time its SETUP has returned — i.e. by the time a test body would run.

    An ordering-based version of this test cannot work, and the first one did not:
    whatever test ran before this file already triggered the fixture's teardown
    strip, so the collection-time filter was always gone before the assertion and
    the assertion passed no matter what the fixture did. Adversarial review caught
    that; reverting the setup strip had left the suite green.
    """
    installed = lr.install_log_redaction_everywhere()
    assert installed > 0 and _count_redactors() > 0, (
        "premise: nothing was installed, so this proves nothing — either redaction "
        "is disabled here (JARVIS_LOG_REDACTION) or no handler existed to attach to"
    )

    gen = _isolate_fixture_body(request)()
    next(gen)                                   # setup only
    try:
        assert _count_redactors() == 0, (
            "a `SecretRedactionFilter` installed outside any test survived the "
            "fixture's SETUP, so it reaches the test body; conftest is restoring a "
            "snapshot or stripping only on teardown, and every test in this worker "
            "downstream of an `agents/run.py` import or a `setup_logging()` call is "
            "reading records the secret scanner has rewritten"
        )
    finally:
        with pytest.raises(StopIteration):
            next(gen)                           # teardown


def test_the_fixture_also_strips_on_the_way_out(request):
    """The other half, so a fixture that strips at setup and leaks afterwards is
    still caught. Cheap, and it keeps the contract symmetric."""
    gen = _isolate_fixture_body(request)()
    next(gen)
    lr.install_log_redaction_everywhere()
    assert _count_redactors() > 0, "premise: the install did nothing"
    with pytest.raises(StopIteration):
        next(gen)
    assert _count_redactors() == 0, (
        "the fixture left behind a redactor installed during the test"
    )
