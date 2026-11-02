"""H448 — heap trimming after a turn (Hermes ``context.memory_trim``).

A long-lived hub returns freed allocator pages to the OS with glibc's ``malloc_trim(0)``
after a turn: probed once, rate-limited by a cooldown, a no-op off Linux/glibc, and read
from the runtime settings snapshot without copying it (agents/core/mem_trim.py).
"""
from __future__ import annotations

import asyncio
import copy
import ctypes
import io
import threading
import tracemalloc
from types import SimpleNamespace

import pytest

from agents.core import mem_trim, settings_db
from agents.core.orchestrator import Orchestrator

HERMES_DEFAULTS = {"enabled": True, "cooldown_seconds": 60.0, "log_every_n": 1, "info_log_min_delta_mb": 0.0}


@pytest.fixture(autouse=True)
def fresh():
    mem_trim._reset_for_tests()
    yield
    mem_trim._reset_for_tests()


class _Trim:
    """A stand-in for libc's malloc_trim: records each pad and the thread it ran on."""

    def __init__(self, *, result=1, raises=None, gate=None):
        self.calls: list[int] = []
        self.threads: list[int] = []
        self.result, self.raises, self.gate = result, raises, gate
        self.argtypes = None
        self.restype = None

    def __call__(self, pad):
        self.threads.append(threading.get_ident())
        if self.gate is not None:
            self.gate.wait(5)
        if self.raises:
            raise self.raises
        self.calls.append(pad)
        return self.result


@pytest.fixture
def glibc(monkeypatch):
    """A Linux/glibc host whose libc exports a fake malloc_trim; counts the libc loads."""
    host = SimpleNamespace(trim=_Trim(), loads=0, platform="linux")

    def libc():
        host.loads += 1
        return SimpleNamespace(malloc_trim=host.trim)

    monkeypatch.setattr(mem_trim, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(mem_trim.os, "confstr", lambda name: "glibc 2.39")
    monkeypatch.delenv("LD_PRELOAD", raising=False)
    monkeypatch.setattr(mem_trim, "_libc", libc)
    return host


class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def monotonic(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(mem_trim, "time", c)
    return c


def _settings(**fields):
    return mem_trim.read_settings(None)._replace(**fields)


# ── the one-time symbol probe ────────────────────────────────────────────────


def test_the_probe_finds_malloc_trim_once_and_every_trim_calls_it_with_zero(glibc):
    always = _settings(cooldown_seconds=0.0)
    assert [mem_trim.maybe_trim(settings=always) for _ in range(3)] == [True, True, True]
    assert glibc.trim.calls == [0, 0, 0]
    assert glibc.loads == 1                       # the libc was looked up once, not per trim
    assert glibc.trim.argtypes == [ctypes.c_size_t] and glibc.trim.restype is ctypes.c_int
    assert mem_trim.probe_reason == "glibc 2.39 malloc_trim"


def test_a_failed_probe_is_remembered_and_never_retried(glibc, monkeypatch):
    def broken():
        glibc.loads += 1
        raise OSError("no libc")

    monkeypatch.setattr(mem_trim, "_libc", broken)
    always = _settings(cooldown_seconds=0.0)
    assert [mem_trim.maybe_trim(settings=always) for _ in range(3)] == [False, False, False]
    assert glibc.loads == 1 and mem_trim.probe_reason == "probe failed: OSError"


def test_the_real_host_answers_honestly():
    """On this machine: a real trim on Linux/glibc, a quiet no-op anywhere else."""
    import os
    import sys

    try:
        glibc_host = sys.platform.startswith("linux") and (os.confstr("CS_GNU_LIBC_VERSION") or "").startswith("glibc")
    except (AttributeError, ValueError, OSError):
        glibc_host = False
    preloaded = any(n in os.environ.get("LD_PRELOAD", "").lower() for n in mem_trim._FOREIGN_ALLOCATORS)
    assert mem_trim.maybe_trim(settings=_settings(cooldown_seconds=0.0)) is (glibc_host and not preloaded)
    assert mem_trim.probe_reason != "not probed"


# ── a safe no-op on other platforms and allocators ───────────────────────────


@pytest.mark.parametrize("platform", ["darwin", "win32", "cygwin", "freebsd14", "emscripten"])
def test_other_platforms_never_touch_ctypes(glibc, monkeypatch, platform):
    monkeypatch.setattr(mem_trim, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(mem_trim.os, "confstr", lambda name: pytest.fail("confstr asked off Linux"))
    assert mem_trim.maybe_trim(settings=_settings(cooldown_seconds=0.0)) is False
    assert glibc.loads == 0 and glibc.trim.calls == []
    assert mem_trim.probe_reason == f"unsupported platform {platform}"


@pytest.mark.parametrize("answer", [ValueError("unrecognized configuration name"), None, ""])
def test_musl_is_a_no_op(glibc, monkeypatch, answer):
    def confstr(name):
        assert name == "CS_GNU_LIBC_VERSION"
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(mem_trim.os, "confstr", confstr)
    assert mem_trim.maybe_trim(settings=_settings(cooldown_seconds=0.0)) is False
    assert glibc.loads == 0 and mem_trim.probe_reason == "not glibc (musl or another C library)"


@pytest.mark.parametrize("preload", ["/usr/lib/x86_64-linux-gnu/libjemalloc.so.2",
                                     "libfoo.so:/opt/lib/libtcmalloc_minimal.so.4", "/usr/lib/libmimalloc.so"])
def test_a_preloaded_allocator_is_a_no_op(glibc, monkeypatch, preload):
    monkeypatch.setenv("LD_PRELOAD", preload)
    assert mem_trim.maybe_trim(settings=_settings(cooldown_seconds=0.0)) is False
    assert glibc.loads == 0 and "is preloaded" in mem_trim.probe_reason


def test_a_libc_without_the_symbol_is_a_no_op(glibc, monkeypatch):
    monkeypatch.setattr(mem_trim, "_libc", lambda: SimpleNamespace())
    assert mem_trim.maybe_trim(settings=_settings(cooldown_seconds=0.0)) is False
    assert mem_trim.probe_reason == "glibc 2.39 has no malloc_trim"


def test_switched_off_it_never_probes(glibc):
    assert mem_trim.maybe_trim(settings=_settings(enabled=False, cooldown_seconds=0.0)) is False
    assert glibc.loads == 0 and mem_trim.probe_reason == "not probed"


# ── the cooldown ─────────────────────────────────────────────────────────────


def test_the_cooldown_spaces_trims(glibc, clock):
    s = _settings()                                     # 60 s, the Hermes default
    assert mem_trim.maybe_trim(settings=s) is True
    clock.now += 30
    assert mem_trim.maybe_trim(settings=s) is False
    clock.now += 29.9
    assert mem_trim.maybe_trim(settings=s) is False
    clock.now += 0.1
    assert mem_trim.maybe_trim(settings=s) is True
    assert len(glibc.trim.calls) == 2
    assert mem_trim.maybe_trim(settings=_settings(cooldown_seconds=0.0)) is True   # 0 = every turn
    assert mem_trim.maybe_trim(settings=_settings(cooldown_seconds=5.0)) is False


def test_a_failed_trim_waits_out_the_cooldown_and_never_raises(glibc, clock):
    glibc.trim.raises = OSError("boom")
    assert mem_trim.maybe_trim(settings=_settings()) is False
    glibc.trim.raises = None
    assert mem_trim.maybe_trim(settings=_settings()) is False      # still cooling down
    assert mem_trim._trim_running is False and glibc.trim.calls == []
    clock.now += 60
    assert mem_trim.maybe_trim(settings=_settings()) is True


def test_a_running_trim_is_never_joined_by_a_second(glibc):
    gate = threading.Event()
    glibc.trim.gate = gate
    always = _settings(cooldown_seconds=0.0)
    first = threading.Thread(target=mem_trim.maybe_trim, kwargs={"settings": always})
    first.start()
    for _ in range(500):
        if glibc.trim.threads:
            break
        threading.Event().wait(0.01)
    assert mem_trim.maybe_trim(settings=always) is False           # one is running
    gate.set()
    first.join(5)
    assert glibc.trim.calls == [0]
    assert mem_trim.maybe_trim(settings=always) is True


def test_log_every_n_and_the_delta_threshold_pick_the_info_lines(glibc, monkeypatch, caplog):
    # MB before / after each trim: 1 odd, 2 even and 100 MB freed, 3 odd, 4 even but 1 MB.
    sizes = iter([300, 200, 300, 200, 300, 200, 300, 299])
    monkeypatch.setattr(mem_trim, "_rss_bytes", lambda: next(sizes) * 1_048_576)
    s = _settings(cooldown_seconds=0.0, log_every_n=2, info_log_min_delta_mb=50.0)
    with caplog.at_level("DEBUG", logger="jarvis.mem_trim"):
        for _ in range(4):
            assert mem_trim.maybe_trim(settings=s) is True
    lines = [(r.levelname, r.getMessage()) for r in caplog.records if "heap trim #" in r.getMessage()]
    assert [level for level, _ in lines] == ["DEBUG", "INFO", "DEBUG", "DEBUG"]
    assert lines[1][1] == "heap trim #2 after turn: RSS 300.0 -> 200.0 MB (-100.0 MB), pages released"


def test_the_defaults_log_every_trim_that_did_not_grow_at_info(glibc, monkeypatch, caplog):
    sizes = iter([300, 300, 300, 301])
    monkeypatch.setattr(mem_trim, "_rss_bytes", lambda: next(sizes) * 1_048_576)
    glibc.trim.result = 0
    with caplog.at_level("DEBUG", logger="jarvis.mem_trim"):
        mem_trim.maybe_trim(settings=_settings(cooldown_seconds=0.0))
        mem_trim.maybe_trim(settings=_settings(cooldown_seconds=0.0))
    lines = [(r.levelname, r.getMessage()) for r in caplog.records if "heap trim #" in r.getMessage()]
    assert lines == [("INFO", "heap trim #1 after turn: RSS 300.0 -> 300.0 MB (+0.0 MB), nothing to release"),
                     ("DEBUG", "heap trim #2 after turn: RSS 300.0 -> 301.0 MB (+1.0 MB), nothing to release")]


# ── the settings: declared, shape-checked, read in place ─────────────────────


def test_the_setting_is_declared_with_the_hermes_defaults():
    row = next(d for d in settings_db.DEFAULTS if (d["category"], d["key"]) == ("context", "memory_trim"))
    assert row["kind"] == "json" and row["value"] == HERMES_DEFAULTS == mem_trim.DEFAULT_SETTINGS
    assert mem_trim.SETTING == "context.memory_trim"
    assert tuple(mem_trim.read_settings(lambda key, default: row["value"])) == (True, 60.0, 1, 0.0)


def test_a_write_is_shape_checked():
    ok = settings_db.validate_category
    assert ok("context", {"memory_trim": dict(HERMES_DEFAULTS)}) == []
    assert ok("context", {"memory_trim": {"enabled": False}}) == []            # the rest default
    assert ok("context", {"memory_trim": {"cooldown_seconds": 0, "log_every_n": 10,
                                          "info_log_min_delta_mb": 2.5}}) == []
    for bad in ([], "on", {"enabeld": True}, {"enabled": "yes"}, {"enabled": 1},
                {"cooldown_seconds": -1}, {"cooldown_seconds": 1e9}, {"cooldown_seconds": "60"},
                {"cooldown_seconds": True}, {"cooldown_seconds": float("nan")},
                {"log_every_n": 0}, {"log_every_n": 1.5}, {"log_every_n": True},
                {"info_log_min_delta_mb": -0.1}, {"info_log_min_delta_mb": float("inf")}):
        assert ok("context", {"memory_trim": bad}), bad


def test_every_read_fails_open_field_by_field():
    def reader(value):
        return lambda key, default: value

    def broken(key, default):
        raise RuntimeError("store gone")

    defaults = (True, 60.0, 1, 0.0)
    assert tuple(mem_trim.read_settings(broken)) == defaults
    for value in (None, [], "off", 0, {}):
        assert tuple(mem_trim.read_settings(reader(value))) == defaults
    assert tuple(mem_trim.read_settings(reader({"enabled": "no", "cooldown_seconds": -1,
                                                "log_every_n": 0, "info_log_min_delta_mb": "x"}))) == defaults
    assert tuple(mem_trim.read_settings(reader({"cooldown_seconds": float("nan"), "log_every_n": True}))) == defaults
    assert tuple(mem_trim.read_settings(reader({"enabled": False, "cooldown_seconds": 5}))) == (False, 5.0, 1, 0.0)


class _NoCopy(dict):
    """The stored value: anything but a key lookup — a copy, a walk — fails the test."""

    def _refuse(self, *a, **kw):
        raise AssertionError("the trim copied or walked its settings")

    __copy__ = __deepcopy__ = __reduce__ = __reduce_ex__ = __iter__ = _refuse
    copy = keys = items = values = _refuse


def test_the_turn_hook_reads_one_key_in_place_and_never_the_store(glibc, monkeypatch):
    seen = []
    stored = _NoCopy(enabled=True, cooldown_seconds=0.0, log_every_n=1, info_log_min_delta_mb=0.0)
    snapshot = {"context.memory_trim": stored, "llm.model": "x"}

    def get_setting(key, default=None):
        seen.append((key, default))
        return snapshot.get(key, default)

    def forbidden(*a, **kw):
        raise AssertionError("the trim read the settings store")

    for name in ("get_all", "get_value", "read_setting", "get_category", "_read_persisted_values"):
        monkeypatch.setattr(settings_db, name, forbidden)
    monkeypatch.setattr(copy, "deepcopy", forbidden)
    monkeypatch.setattr(copy, "copy", forbidden)

    assert mem_trim.after_turn(SimpleNamespace(get_setting=get_setting)) is None   # no loop: inline
    assert glibc.trim.calls == [0]
    assert seen == [("context.memory_trim", None)]                 # one lookup per attempt


def test_the_settings_read_allocates_far_less_than_a_snapshot_copy(glibc):
    """Hermes: "never let the settings read allocate more than the trim frees"."""
    settings_db.ensure_initialized()
    snapshot = {f"{c}.{r['key']}": r["value"] for c, rows in settings_db.get_all().items() for r in rows}
    orch = SimpleNamespace(get_setting=lambda key, default=None: snapshot.get(key, default))
    assert mem_trim.after_turn(orch) is None and glibc.trim.calls == [0]     # now cooling down
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        for _ in range(100):
            assert mem_trim.after_turn(orch) is None
        attempt = tracemalloc.get_traced_memory()[1] - base
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        copy.deepcopy(snapshot)
        snapshot_copy = tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    assert attempt < 4096 and attempt * 8 < snapshot_copy, (attempt, snapshot_copy)
    assert glibc.trim.calls == [0]


# ── the setting through the product: store, runtime snapshot, CLI ────────────


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    return tmp_path


def _snapshot_orch():
    orch = SimpleNamespace(_runtime_settings={})
    Orchestrator.load_runtime_settings(orch)
    orch.get_setting = lambda key, default=None: Orchestrator.get_setting(orch, key, default)
    return orch


def test_the_seeded_setting_reaches_the_runtime_snapshot_and_the_owner_can_switch_it_off(temp_settings, glibc):
    orch = _snapshot_orch()
    assert orch.get_setting("context.memory_trim") == HERMES_DEFAULTS
    assert mem_trim.after_turn(orch) is None and glibc.trim.calls == [0]

    settings_db.put_category("context", {"memory_trim": {**HERMES_DEFAULTS, "enabled": False,
                                                         "cooldown_seconds": 0.0}})
    orch = _snapshot_orch()
    mem_trim._reset_for_tests()
    assert mem_trim.after_turn(orch) is None
    assert glibc.trim.calls == [0] and mem_trim.probe_reason == "not probed"


def _cli(argv):
    from agents.cli.nerva import Context, main

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: None)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


def test_the_cli_addresses_the_hermes_dotted_keys(temp_settings):
    from agents.cli.nerva import EXIT_FAILED, EXIT_OK

    code, out, _ = _cli(["config", "get", "context.memory_trim.cooldown_seconds"])
    assert code == EXIT_OK and out.strip() == "60.0"
    code, _, _ = _cli(["config", "set", "context.memory_trim.enabled", "false"])
    assert code == EXIT_OK
    assert settings_db.get_value("context", "memory_trim") == {**HERMES_DEFAULTS, "enabled": False}
    code, _, err = _cli(["config", "set", "context.memory_trim.cooldown_seconds", "-5"])
    assert code == EXIT_FAILED and "cooldown_seconds" in err
    code, _, err = _cli(["config", "set", "context.memory_trim.cooldown_secs", "5"])
    assert code == EXIT_FAILED
    assert settings_db.get_value("context", "memory_trim") == {**HERMES_DEFAULTS, "enabled": False}


# ── the real turn path ───────────────────────────────────────────────────────


def _turn_orch(trim, *, fail=None, value=None, seen=None):
    value = {**HERMES_DEFAULTS, "cooldown_seconds": 0.0} if value is None else value

    async def body(*a, **kw):
        if seen is not None:
            seen.append(len(trim.calls))       # what had been trimmed when the turn ran
        if fail:
            raise fail
        return "reply"

    async def parallel(*a, **kw):
        await body()
        return {"jarvis": "done"}

    return SimpleNamespace(_handle_input=body, _handle_input_stream=body,
                           _start_title_upgrades=lambda titles: None, agents={"jarvis": object()},
                           _call_agents_parallel=parallel,
                           get_setting=lambda key, default=None: value if key == mem_trim.SETTING else default)


@pytest.mark.parametrize("entry", ["handle_input", "handle_input_stream", "process"])
def test_every_turn_entry_trims_after_the_turn(glibc, entry):
    seen = []
    orch = _turn_orch(glibc.trim, seen=seen)
    reply = asyncio.run(getattr(Orchestrator, entry)(orch, "hi"))  # asyncio.run drains the executor
    assert reply in ("reply", "done")
    assert seen == [0] and glibc.trim.calls == [0]


@pytest.mark.parametrize("fail", [ValueError("boom"), asyncio.CancelledError()])
@pytest.mark.parametrize("entry", ["handle_input", "handle_input_stream"])
def test_a_turn_that_raises_or_is_cancelled_still_trims(glibc, entry, fail):
    orch = _turn_orch(glibc.trim, fail=fail)
    with pytest.raises(type(fail)):
        asyncio.run(getattr(Orchestrator, entry)(orch, "hi"))
    assert glibc.trim.calls == [0]


@pytest.mark.parametrize("entry", ["handle_input", "handle_input_stream", "process"])
def test_switched_off_no_turn_trims(glibc, entry):
    orch = _turn_orch(glibc.trim, value={**HERMES_DEFAULTS, "enabled": False})
    asyncio.run(getattr(Orchestrator, entry)(orch, "hi"))
    assert glibc.trim.calls == [] and glibc.loads == 0


def test_turns_inside_the_cooldown_do_not_trim(glibc):
    orch = _turn_orch(glibc.trim, value=dict(HERMES_DEFAULTS))

    async def three_turns():
        for _ in range(3):
            await Orchestrator.handle_input(orch, "hi")

    asyncio.run(three_turns())
    assert glibc.trim.calls == [0]


def test_the_trim_runs_off_the_event_loop_and_the_reply_does_not_wait_for_it(glibc):
    gate = threading.Event()
    glibc.trim.gate = gate
    orch = _turn_orch(glibc.trim)

    async def turn():
        loop_thread = threading.get_ident()
        reply = await Orchestrator.handle_input(orch, "hi")
        returned_before_trim_finished = glibc.trim.calls == []
        gate.set()
        return reply, loop_thread, returned_before_trim_finished

    reply, loop_thread, early = asyncio.run(turn())
    assert reply == "reply" and early is True
    assert glibc.trim.calls == [0] and glibc.trim.threads and glibc.trim.threads[0] != loop_thread


def test_a_stand_in_without_settings_is_never_trimmed_for(glibc):
    orch = _turn_orch(glibc.trim)
    del orch.get_setting
    asyncio.run(Orchestrator.handle_input(orch, "hi"))
    assert glibc.trim.calls == [] and glibc.loads == 0


def test_the_hub_orchestrator_trims_after_a_real_turn(glibc, monkeypatch):
    """The hub's own Orchestrator: its seeded runtime snapshot and its turn wrapper."""
    from agents.core.config import JarvisConfig

    orch = Orchestrator(JarvisConfig())
    orch.load_runtime_settings()                  # what Orchestrator.initialize does at boot
    assert orch.get_setting("context.memory_trim") == HERMES_DEFAULTS

    async def body(*a, **kw):
        return "reply"

    monkeypatch.setattr(orch, "_handle_input", body)
    assert asyncio.run(orch.handle_input("hi", channel="web")) == "reply"
    assert glibc.trim.calls == [0]
