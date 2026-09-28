"""H161 — warn when the box is running out of memory or disk.

Hermes ranks five conditions and shows only the worst one the owner has not
dismissed: disk critical, memory critical, a suspected OOM restart, disk elevated,
memory elevated. A condition clears only on confirmed recovery (a few samples in a
row under the line, with a margin), a dismissal lasts for this boot, and the watch
does not depend on autonomy being on. Nerva had the thresholds (the autonomy
observer's) but surfaced them only as ticker lines and alert tasks, cleared on the
first good sample, never suspected an OOM restart, had no dismissal, watched only
``/`` and stopped sampling with autonomy off or ESTOP engaged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from agents.core import resource_pressure as rp  # noqa: E402
from agents.core.resource_pressure import PressureMonitor, Sample  # noqa: E402


def _monitor(tmp_path, boot="boot-a", **kw):
    return PressureMonitor(tmp_path / "pressure.json", boot_id=boot, **kw)


def _conditions(snap):
    return [c["condition"] for c in snap["conditions"]]


def test_the_thresholds_are_the_observers():
    from agents.core.autonomy.observer import DEFAULT_THRESHOLDS

    observer = {k: DEFAULT_THRESHOLDS[k] for k in ("ram_warn", "ram_critical", "disk_warn", "disk_critical")}
    assert observer == rp.DEFAULT_THRESHOLDS
    assert rp.RECOVERY_SAMPLES == 3 and rp.RECOVERY_MARGIN == 5.0


def test_nothing_to_say_on_a_healthy_box(tmp_path):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=40.0, disks={"/": 30.0}))
    assert m.snapshot() == {"boot_id": "boot-a", "conditions": [], "worst": None, "sampled_at": m.sampled_at}


@pytest.mark.parametrize(("memory", "disk", "expected"), [
    (86, 10, ["memory_elevated"]),
    (96, 10, ["memory_critical"]),
    (10, 85, ["disk_elevated"]),
    (10, 95, ["disk_critical"]),
    (96, 96, ["disk_critical", "memory_critical"]),
    (90, 97, ["disk_critical", "memory_elevated"]),
    (97, 88, ["memory_critical", "disk_elevated"]),
    (84.9, 84.9, []),
])
def test_conditions_are_ranked_in_hermes_order(tmp_path, memory, disk, expected):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=memory, disks={"/": disk}))
    snap = m.snapshot()
    assert _conditions(snap) == expected
    assert snap["worst"] == (snap["conditions"][0] if expected else None)


def test_each_volume_is_watched_and_named(tmp_path):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=10, disks={"/": 40.0, "/srv/jarvis": 96.4}))
    (disk,) = m.snapshot()["conditions"]
    assert disk["condition"] == "disk_critical" and disk["percent"] == 96.4
    assert disk["paths"] == [{"path": "/srv/jarvis", "percent": 96.4}]


def test_a_condition_clears_only_on_confirmed_recovery(tmp_path):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=90, disks={}))
    for value in (84, 79, 90, 79, 79):                   # 84 is under 85 but not under 85 - 5
        m.observe(Sample(memory=value, disks={}))
        assert _conditions(m.snapshot()) == ["memory_elevated"], value
    m.observe(Sample(memory=79, disks={}))               # the third quiet sample in a row
    assert _conditions(m.snapshot()) == []


def test_a_reading_just_under_the_line_is_not_recovery(tmp_path):
    """Under 85 but not under 85 - 5: never counted, and it restarts the count."""
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=90, disks={}))
    for _ in range(6):
        m.observe(Sample(memory=84, disks={}))
    assert _conditions(m.snapshot()) == ["memory_elevated"]
    for value in (79, 79, 84, 79, 79):
        m.observe(Sample(memory=value, disks={}))
    assert _conditions(m.snapshot()) == ["memory_elevated"], "the near reading restarted the count"


def test_critical_steps_down_to_elevated_on_recovery_and_back_up_at_once(tmp_path):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=97, disks={}))
    for _ in range(3):
        m.observe(Sample(memory=88, disks={}))           # under 95 - 5, still elevated
    assert _conditions(m.snapshot()) == ["memory_elevated"]
    m.observe(Sample(memory=96, disks={}))
    assert _conditions(m.snapshot()) == ["memory_critical"], "rising is never delayed"


def test_a_sample_that_could_not_be_read_changes_nothing(tmp_path):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=90, disks={"/": 90}))
    for _ in range(5):
        m.observe(Sample(memory=None, disks={}))
    assert _conditions(m.snapshot()) == ["disk_elevated", "memory_elevated"]


def test_only_the_worst_undismissed_condition_is_shown(tmp_path):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=96, disks={"/": 88}))
    assert m.snapshot()["worst"]["condition"] == "memory_critical"
    assert m.dismiss("memory_critical", "boot-a") is True
    snap = m.snapshot()
    assert snap["worst"]["condition"] == "disk_elevated"
    assert [c["dismissed"] for c in snap["conditions"]] == [True, False]
    assert m.dismiss("disk_elevated", "boot-a") is True and m.snapshot()["worst"] is None


def test_a_dismissal_names_this_boot_and_a_real_condition(tmp_path):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=96, disks={}))
    assert m.dismiss("memory_critical", "boot-old") is False, "a stale page cannot dismiss for this boot"
    assert m.dismiss("swap_full", "boot-a") is False
    assert m.dismiss("disk_critical", "boot-a") is False, "nothing to dismiss"
    assert m.snapshot()["worst"]["condition"] == "memory_critical"


def test_a_dismissal_lasts_the_boot_and_a_new_boot_re_arms_it(tmp_path):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=10, disks={"/": 96}))
    m.dismiss("disk_critical", "boot-a")
    m.stop()
    again = _monitor(tmp_path)                           # a restart on the same boot
    again.start()
    again.observe(Sample(memory=10, disks={"/": 96}))
    assert again.snapshot()["worst"] is None, "the owner already said so this boot"
    rebooted = _monitor(tmp_path, boot="boot-b")
    rebooted.start()
    rebooted.observe(Sample(memory=10, disks={"/": 96}))
    assert rebooted.snapshot()["worst"]["condition"] == "disk_critical"


def test_recovery_re_arms_a_dismissal(tmp_path):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=90, disks={}))
    m.dismiss("memory_elevated", "boot-a")
    for _ in range(3):
        m.observe(Sample(memory=50, disks={}))
    m.observe(Sample(memory=90, disks={}))
    assert m.snapshot()["worst"]["condition"] == "memory_elevated", "a new episode is a new warning"


def test_an_unclean_restart_after_memory_pressure_is_a_suspected_oom(tmp_path):
    first = _monitor(tmp_path)
    first.start()
    first.observe(Sample(memory=93, disks={}))
    # ... the process is killed here: no stop(), so no clean-shutdown marker.
    second = _monitor(tmp_path)
    second.start()
    second.observe(Sample(memory=40, disks={}))
    (oom,) = second.snapshot()["conditions"]
    assert oom["condition"] == "oom_restart_suspected" and oom["memory_level"] == "elevated"
    assert second.dismiss("oom_restart_suspected", "boot-a") is True
    assert second.snapshot()["worst"] is None


def test_a_suspected_oom_restart_outranks_an_elevated_disk(tmp_path):
    first = _monitor(tmp_path)
    first.start()
    first.observe(Sample(memory=96, disks={}))
    second = _monitor(tmp_path)
    second.start()
    second.observe(Sample(memory=40, disks={"/": 90}))
    assert _conditions(second.snapshot()) == ["oom_restart_suspected", "disk_elevated"]
    assert second.snapshot()["conditions"][0]["memory_level"] == "critical"


@pytest.mark.parametrize("case", ["clean_stop", "calm_memory", "other_boot", "no_state"])
def test_no_oom_suspicion_without_all_three_signs(tmp_path, case):
    first = _monitor(tmp_path)
    if case != "no_state":
        first.start()
        first.observe(Sample(memory=40 if case == "calm_memory" else 96, disks={}))
        if case == "clean_stop":
            first.stop()
    second = _monitor(tmp_path, boot="boot-b" if case == "other_boot" else "boot-a")
    second.start()
    second.observe(Sample(memory=40, disks={}))
    assert _conditions(second.snapshot()) == []


def test_the_state_file_is_small_and_written_atomically(tmp_path):
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=90, disks={}))
    state = json.loads((tmp_path / "pressure.json").read_text())
    assert state == {"boot_id": "boot-a", "clean_shutdown": False, "memory_level": 1, "dismissed": [],
                     "pid": state["pid"]}
    assert not list(tmp_path.glob("*.tmp")), "no temporary file left behind"


def test_a_dismissal_the_file_names_that_is_no_condition_is_dropped(tmp_path):
    (tmp_path / "pressure.json").write_text(json.dumps(
        {"boot_id": "boot-a", "clean_shutdown": True, "memory_level": 0, "dismissed": ["swap_full", "disk_critical"]}))
    m = _monitor(tmp_path)
    m.start()
    assert m.dismissed == {"disk_critical"}
    assert json.loads((tmp_path / "pressure.json").read_text())["dismissed"] == ["disk_critical"]


def test_a_failed_replace_leaves_the_old_state_and_no_temporary_file(monkeypatch, tmp_path):
    m = _monitor(tmp_path)
    m.start()
    before = (tmp_path / "pressure.json").read_text()

    def refuse(*_args):
        raise OSError("read-only file system")

    monkeypatch.setattr(rp.os, "replace", refuse)
    m.observe(Sample(memory=90, disks={}))
    assert (tmp_path / "pressure.json").read_text() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_a_damaged_state_file_is_ignored_and_replaced(tmp_path):
    (tmp_path / "pressure.json").write_text("{not json")
    m = _monitor(tmp_path)
    m.start()
    m.observe(Sample(memory=40, disks={}))
    assert m.snapshot()["conditions"] == []
    assert json.loads((tmp_path / "pressure.json").read_text())["boot_id"] == "boot-a"


def test_an_unwritable_state_file_never_breaks_the_watch(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    m = PressureMonitor(blocker / "pressure.json", boot_id="boot-a")
    m.start()
    m.observe(Sample(memory=96, disks={}))
    assert m.snapshot()["worst"]["condition"] == "memory_critical"
    m.stop()


def test_the_boot_id_comes_from_the_kernel_then_the_boot_time(monkeypatch, tmp_path):
    boot_file = tmp_path / "boot_id"
    boot_file.write_text("  4f1c-uuid \n")
    monkeypatch.setattr(rp, "BOOT_ID_PATH", boot_file)
    assert rp.current_boot_id() == "4f1c-uuid"
    monkeypatch.setattr(rp, "BOOT_ID_PATH", tmp_path / "missing")
    monkeypatch.setattr(rp, "_boot_time", lambda: 1_700_000_000.4)
    assert rp.current_boot_id() == "boot-1700000000"
    monkeypatch.setattr(rp, "_boot_time", lambda: None)
    assert rp.current_boot_id() == "unknown"


def test_a_sample_reads_memory_and_each_distinct_volume_once(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    calls = []

    def disk_usage(path):
        calls.append(path)
        return SimpleNamespace(percent={"/": 40.0}.get(path, 88.0))

    fake = SimpleNamespace(virtual_memory=lambda: SimpleNamespace(percent=71.5), disk_usage=disk_usage)
    monkeypatch.setattr(rp, "_psutil", lambda: fake)
    sample = rp.take_sample(["/", str(data), str(data)])
    assert sample.memory == 71.5 and sample.disks == {"/": 40.0, str(data): 88.0}
    assert calls == ["/", str(data)]

    def broken():
        raise OSError("no /proc/meminfo")

    fake.virtual_memory = broken
    assert rp.take_sample(["/"]).memory is None, "an unreadable reading is not a healthy 0 %"
    monkeypatch.setattr(rp, "_psutil", lambda: None)
    assert rp.take_sample(["/"]) == Sample(memory=None, disks={})


def test_the_root_and_the_data_home_are_both_watched(monkeypatch, tmp_path):
    import os

    from agents.core import paths

    monkeypatch.setattr(paths, "data_root", lambda: tmp_path / "home")
    assert rp.watched_paths() == [os.path.abspath(os.sep), str(tmp_path / "home")]


def test_fresh_samples_only_when_the_last_is_stale(tmp_path):
    clock = [1000.0]
    samples = []

    def sampler():
        samples.append(1)
        return Sample(memory=10, disks={})

    m = PressureMonitor(tmp_path / "p.json", boot_id="b", sampler=sampler, clock=lambda: clock[0])
    m.start()
    m.fresh(max_age=60)
    m.fresh(max_age=60)
    assert len(samples) == 1
    clock[0] += 61
    m.fresh(max_age=60)
    assert len(samples) == 2 and m.sampled_at == 1061.0


def test_samples_from_two_threads_are_folded_in_one_at_a_time(tmp_path):
    """The route (on a worker thread) and the scheduler tick can sample at once."""
    import threading

    m = _monitor(tmp_path)
    m.start()
    inside, overlaps = [0], []
    real = m.memory.update

    def slow_update(*args):
        inside[0] += 1
        overlaps.append(inside[0])
        threading.Event().wait(0.01)
        inside[0] -= 1
        return real(*args)

    m.memory.update = slow_update
    threads = [threading.Thread(target=m.observe, args=(Sample(memory=90, disks={}),)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert max(overlaps) == 1


# ── the hub ──────────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from agents import web

    monitor = _monitor(tmp_path)
    monitor.start()
    monitor.sampler = lambda: Sample(memory=96, disks={"/": 88})
    monkeypatch.setattr(rp, "_MONITOR", monitor)
    return TestClient(web.app), monitor


def test_the_route_answers_the_ranked_conditions(client):
    http, _monitor_ = client
    body = http.get("/api/system/pressure").json()
    assert body["boot_id"] == "boot-a"
    assert [c["condition"] for c in body["conditions"]] == ["memory_critical", "disk_elevated"]
    assert body["worst"]["condition"] == "memory_critical"


def test_dismissal_through_the_route(client):
    http, _monitor_ = client
    http.get("/api/system/pressure")
    refused = http.post("/api/system/pressure/dismiss", json={"condition": "memory_critical", "boot_id": "other"})
    assert refused.status_code == 409
    ok = http.post("/api/system/pressure/dismiss", json={"condition": "memory_critical", "boot_id": "boot-a"})
    assert ok.status_code == 200 and ok.json()["worst"]["condition"] == "disk_elevated"
    assert http.post("/api/system/pressure/dismiss", json={"condition": 5, "boot_id": "boot-a"}).status_code == 422


def test_the_routes_are_user_guarded():
    snapshot = json.loads((ROOT / "tests" / "_snapshots" / "route_auth.json").read_text(encoding="utf-8"))
    assert snapshot["GET /api/system/pressure"] == "user"
    assert snapshot["POST /api/system/pressure/dismiss"] == "user"
    from agents import web
    from tests._route_introspect import iter_effective_routes

    paths = ("/api/system/pressure", "/api/system/pressure/dismiss")
    found = {r.path: r for r in iter_effective_routes(web.app)
             if getattr(r, "path", "") in paths and hasattr(r, "dependant")}
    assert set(found) == set(paths)
    for r in found.values():
        assert "user_guard" in {getattr(d.call, "__name__", "") for d in r.dependant.dependencies}


def test_sampling_is_scheduled_apart_from_autonomy(monkeypatch):
    """The watch runs on the hub's scheduler every minute — autonomy off or ESTOP
    engaged does not stop it (the observer's samples stop in both)."""
    from agents.core.scheduler_service import SchedulerService

    jobs = []
    sched = SimpleNamespace(add_job=lambda fn, *a, **k: jobs.append((fn, k)))
    service = SchedulerService.__new__(SchedulerService)
    service._orch = SimpleNamespace(heartbeat_scheduler=SimpleNamespace(scheduler=sched))
    monkeypatch.delenv("JARVIS_TESTING", raising=False)
    service.schedule_pressure_monitor()
    ((fn, kwargs),) = jobs
    assert kwargs["id"] == "pressure-monitor" and kwargs["seconds"] == 60
    monkeypatch.setenv("JARVIS_TESTING", "1")
    jobs.clear()
    service.schedule_pressure_monitor()
    assert jobs == []


def test_the_lifespan_starts_and_stops_the_watch_cleanly():
    import inspect

    from agents import web

    src = inspect.getsource(web.lifespan)
    assert "resource_pressure.monitor().start()" in src
    after = [line.strip() for line in src.split("    yield\n", 1)[1].splitlines()
             if line.strip() and not line.strip().startswith("#")]
    assert after[0] == "resource_pressure.monitor().stop()", "the very first teardown step"
    assert src.index("yield") < src.index("resource_pressure.monitor().stop()") < src.index("await orch.stop_channels()"), \
        "the clean-shutdown mark is written first, before any step that could hang"
