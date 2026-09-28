"""H689 — one durable identity per install, one hub per data root, profiles that isolate.

``install_id()`` mints one 32-hex id under the data root once — under an in-process and a
cross-process lock, written atomically and read back — and returns None (never a fresh
value) when it cannot read or keep one. The activation clock, node grants, channel
deeplinks and satellite pairings carry it; a deeplink or pairing minted by another
install is refused. ``hub.lock`` refuses a second hub on the same root. ``JARVIS_PROFILE``
gives a profile its own data root.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import install_identity as ii
from agents.core import paths

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh():
    ii.forget_cache()
    ii.release_hub_lock()
    yield
    ii.forget_cache()
    ii.release_hub_lock()


# ── the id ───────────────────────────────────────────────────────────────────────

def test_the_id_is_minted_once_and_kept(tmp_path):
    first = ii.install_id(tmp_path)
    assert ii.ID_RE.match(first)
    assert (tmp_path / "install_id").read_text(encoding="ascii") == first + "\n"
    ii.forget_cache()
    assert ii.install_id(tmp_path) == first
    assert list(tmp_path.glob(".install_id-*")) == []


def test_the_id_is_cached_per_root(tmp_path, monkeypatch):
    first = ii.install_id(tmp_path)
    monkeypatch.setattr(ii, "_read", lambda path: (_ for _ in ()).throw(AssertionError("read again")))
    assert ii.install_id(tmp_path) == first
    other = tmp_path / "other"
    monkeypatch.undo()
    assert ii.install_id(other) != first


def test_the_default_root_is_the_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    value = ii.install_id()
    assert (tmp_path / "install_id").read_text(encoding="ascii").strip() == value


@pytest.mark.parametrize("content", [b"not-an-id\n", b"ABCDEF" * 6, b"\xff\xfe", b"", b"a" * 31])
def test_a_file_that_holds_anything_else_is_none_and_kept(tmp_path, content):
    (tmp_path / "install_id").write_bytes(content)
    assert ii.install_id(tmp_path) is None
    assert (tmp_path / "install_id").read_bytes() == content          # never re-minted over
    assert ii._cache == {}


def test_an_unreadable_file_is_none(tmp_path):
    (tmp_path / "install_id").mkdir()
    assert ii.install_id(tmp_path) is None


def test_a_write_that_fails_is_none_and_leaves_no_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(ii.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    assert ii.install_id(tmp_path) is None
    assert not (tmp_path / "install_id").exists()
    assert list(tmp_path.glob(".install_id-*")) == []


def test_a_root_that_cannot_be_made_is_none(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert ii.install_id(blocker / "root") is None


def test_the_directory_is_fsynced_after_the_write(tmp_path, monkeypatch):
    seen = []
    real = ii._fsync_dir
    monkeypatch.setattr(ii, "_fsync_dir", lambda folder: (seen.append(folder), real(folder)))
    ii.install_id(tmp_path)
    assert seen == [tmp_path]


def _mint(root, barrier, queue):
    import time

    from agents.core import install_identity

    minted = []
    write = install_identity._write

    def slow_write(path, value):          # a mint that takes long enough to race
        minted.append(value)
        time.sleep(0.5)
        write(path, value)

    install_identity._write = slow_write
    barrier.wait(timeout=60)              # every child reads at the same moment
    queue.put((install_identity.install_id(root), len(minted)))


def test_racing_processes_agree_on_one_id(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    queue, barrier = ctx.Queue(), ctx.Barrier(4)
    procs = [ctx.Process(target=_mint, args=(str(tmp_path), barrier, queue)) for _ in range(4)]
    for p in procs:
        p.start()
    got = [queue.get(timeout=60) for _ in procs]
    for p in procs:
        p.join(timeout=60)
    ids = {value for value, _ in got}
    assert len(ids) == 1 and ii.ID_RE.match(ids.pop())
    assert sum(mints for _, mints in got) == 1          # the lock let exactly one child mint


def test_the_lock_guards_the_mint(tmp_path, monkeypatch):
    calls = []
    real_lock, real_unlock = ii._file_lock, ii._file_unlock
    monkeypatch.setattr(ii, "_file_lock", lambda h, blocking: (calls.append(("lock", blocking)), real_lock(h, blocking=blocking)))
    monkeypatch.setattr(ii, "_file_unlock", lambda h: (calls.append(("unlock",)), real_unlock(h)))
    ii.install_id(tmp_path)
    assert calls == [("lock", True), ("unlock",)]
    assert (tmp_path / "install_id.lock").exists()


# ── one hub per root ─────────────────────────────────────────────────────────────

def _second_hub(root) -> str:
    """What another process gets when it asks for the hub lock on *root*."""
    code = (f"import sys; sys.path.insert(0, {str(REPO)!r})\n"
            "from agents.core import install_identity as ii\n"
            f"try:\n    ii.acquire_hub_lock({str(root)!r})\nexcept ii.HubAlreadyRunning as e:\n"
            "    print('REFUSED', e.pid)\nelse:\n    print('GOT')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def test_a_second_hub_on_the_same_root_is_refused(tmp_path):
    handle = ii.acquire_hub_lock(tmp_path)
    assert ii.acquire_hub_lock(tmp_path) is handle                        # idempotent in-process
    assert (tmp_path / "hub.lock").read_text(encoding="ascii") == str(os.getpid())
    assert _second_hub(tmp_path) == f"REFUSED {os.getpid()}"
    ii.release_hub_lock()
    assert _second_hub(tmp_path) == "GOT"


def test_the_refusal_names_the_holder():
    err = ii.HubAlreadyRunning(Path("/x"), "")
    assert "pid unknown" in str(err) and "/x" in str(err)
    assert "pid 42" in str(ii.HubAlreadyRunning(Path("/x"), "42"))


def test_serve_takes_the_lock_before_starting():
    src = (REPO / "serve.py").read_text(encoding="utf-8")
    main = src[src.index("def main():"):]
    assert main.index("install_identity.acquire_hub_lock()") < main.index("NotifyingServer(config, readiness_snapshot).run()")
    assert "raise SystemExit(f\"Nerva is already running on this data root: {exc}\")" in main


def test_serve_stops_on_a_bad_profile_before_importing_the_hub(tmp_path):
    env = {**os.environ, "JARVIS_HOME": str(tmp_path), "JARVIS_PROFILE": "Bad"}
    out = subprocess.run([sys.executable, str(REPO / "serve.py")], capture_output=True, text=True,
                         cwd=str(REPO), env=env, timeout=120)
    assert out.returncode == 1 and "Traceback" not in out.stderr
    assert "JARVIS_PROFILE='Bad' is not a profile name" in out.stderr
    assert list(tmp_path.iterdir()) == []


# ── profiles ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,name", [
    ("", None), ("default", None), ("work", "work"), ("a-b_1", "a-b_1"), (" work ", "work"),
    ("Work", None), ("../x", None), ("-x", None), ("x" * 33, None), ("x" * 32, "x" * 32),
])
def test_the_profile_name(monkeypatch, value, name):
    monkeypatch.setenv("JARVIS_PROFILE", value)
    assert paths.profile_name() == name
    assert (paths.profile_error() is None) == (name is not None or value.strip() in ("", "default"))


def test_a_profile_is_its_own_data_root(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    assert paths.data_root() == home
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert paths.data_root() == tmp_path / "home-profiles" / "work"
    assert paths.data_path("settings.db") == tmp_path / "home-profiles" / "work" / "settings.db"
    monkeypatch.setenv("JARVIS_PROFILE", "Bad Name")
    with pytest.raises(RuntimeError, match="not a profile name"):
        paths.data_root()
    assert "not a profile name" in paths.profile_error()


def test_a_profile_without_a_home_sits_beside_the_default_root(monkeypatch):
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    monkeypatch.delenv("JARVIS_USER_HOME", raising=False)
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    assert paths.data_root() == paths._REPO_ROOT / "memory_logs-profiles" / "work"


def test_two_profiles_have_two_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_PROFILE", "one")
    one = ii.install_id()
    monkeypatch.setenv("JARVIS_PROFILE", "two")
    assert ii.install_id() != one


def test_the_secret_store_resolves_under_the_profile_root(tmp_path):
    env = {**os.environ, "JARVIS_HOME": str(tmp_path / "home"), "JARVIS_PROFILE": "work"}
    code = "from agents.core import secrets; print(secrets.DEFAULT_STORE)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO), env=env, timeout=120)
    assert out.stdout.strip() == str(tmp_path / "home-profiles" / "work" / "security" / "secrets.enc")


def test_children_keep_the_profile():
    from agents.core.environments import JARVIS_CHILD_ALLOWED_ENV

    assert "JARVIS_PROFILE" in JARVIS_CHILD_ALLOWED_ENV


# ── consumers ────────────────────────────────────────────────────────────────────

def test_the_activation_clock_carries_the_install_id(tmp_path, monkeypatch):
    from agents.core import first_action

    monkeypatch.setattr(ii, "install_id", lambda root=None: "a" * 32)
    store = tmp_path / "clock.json"
    assert first_action.mark_installed(store, now=0.0)["install_id"] == "a" * 32
    monkeypatch.setattr(ii, "install_id", lambda root=None: None)
    other = tmp_path / "clock2.json"
    assert first_action.mark_installed(other, now=0.0)["install_id"] is None


def test_an_unreadable_clock_is_never_written_over(tmp_path):
    from agents.core import first_action

    store = tmp_path / "clock.json"
    store.write_text("{broken", encoding="utf-8")
    assert first_action.infer_install_at_boot(store, now=5.0)["unreadable"] is True
    task = SimpleNamespace(id=1, kind="k", decided_by="owner", decision="accept")
    assert first_action.record_first_action(task, store, now=9.0) is None
    assert store.read_text(encoding="utf-8") == "{broken"
    other = tmp_path / "foreign.json"
    other.write_text(json.dumps({"schema": "else"}), encoding="utf-8")
    assert first_action.mark_installed(other, now=1.0)["unreadable"] is True


def test_a_node_grant_is_scoped_to_this_install(monkeypatch):
    from agents.core.node_mesh import NodeMesh

    issued = []
    broker = SimpleNamespace(issue=lambda caps, **kw: (issued.append(kw), {"id": "tok"})[1], revoke=lambda t: None)
    monkeypatch.setattr(ii, "install_id", lambda root=None: "b" * 32)
    mesh = NodeMesh(capability_broker=broker)
    rec = mesh.register_node("pi", ["camera"])
    assert issued[0]["source"] == f"node:pi@{'b' * 32}" and issued[0]["task_id"] == "pi"
    assert mesh._nodes["pi"]["hub_id"] == "b" * 32 and rec["token_issued"] is True
    monkeypatch.setattr(ii, "install_id", lambda root=None: None)
    mesh.register_node("pi2", ["camera"])
    assert issued[1]["source"] == "node:pi2" and mesh._nodes["pi2"]["hub_id"] == ""


def test_a_deeplink_minted_by_another_install_is_refused(tmp_path, monkeypatch):
    from agents.core.channels.pairing import SenderPairing as PairingStore

    monkeypatch.setattr(ii, "install_id", lambda root=None: "c" * 32)
    store = PairingStore(tmp_path / "pairing.json")
    minted = store.mint_deeplink("telegram", now=0.0)
    assert next(iter(store._deeplinks.values()))["hub"] == "c" * 32
    monkeypatch.setattr(ii, "install_id", lambda root=None: "d" * 32)
    got = store.redeem_deeplink(minted["token"], "telegram", "u1", now=1.0)
    assert got == {"ok": False, "reason": "other_install"}
    monkeypatch.setattr(ii, "install_id", lambda root=None: "c" * 32)
    again = store.mint_deeplink("telegram", now=2.0)
    assert store.redeem_deeplink(again["token"], "telegram", "u1", now=3.0)["ok"] is True


def test_a_deeplink_without_an_install_id_still_works(tmp_path, monkeypatch):
    from agents.core.channels.pairing import SenderPairing as PairingStore

    monkeypatch.setattr(ii, "install_id", lambda root=None: None)
    store = PairingStore(tmp_path / "pairing.json")
    minted = store.mint_deeplink("telegram", now=0.0)
    monkeypatch.setattr(ii, "install_id", lambda root=None: "e" * 32)
    assert store.redeem_deeplink(minted["token"], "telegram", "u1", now=1.0)["ok"] is True


def _pairing(hub_id=""):
    from agents.core.satellite_hub import SatellitePairing

    return SatellitePairing.from_token(satellite_id="kitchen", room_id="kitchen", token="secret-token",
                                       allowed_peer="10.0.0.5", allowed_transport="http",
                                       expires_at=10_000.0, hub_id=hub_id)


def test_a_pairing_carries_a_valid_hub_id():
    assert _pairing("F" * 32).hub_id == "f" * 32
    assert _pairing().hub_id == ""
    for bad in ("x" * 32, "a" * 31, "g" * 32):
        with pytest.raises(ValueError, match="install id"):
            _pairing(bad)


@pytest.mark.parametrize("pinned,own,refused", [
    ("", "a" * 32, False), ("a" * 32, "a" * 32, False), ("a" * 32, "b" * 32, True), ("a" * 32, "", True),
])
def test_a_pairing_from_another_install_is_refused(pinned, own, refused):
    from agents.core.satellite_hub import SatelliteHub

    hub = SatelliteHub(pairings=(_pairing(pinned),), clock=lambda: 100.0, hub_id=own)
    claim = SimpleNamespace(transport="http", peer="10.0.0.5", timestamp=100.0, credential="secret-token")
    got = hub._pairing_refusal(_pairing(pinned), claim, 100.0)
    assert (got == "other_install") is refused and (got == "" or refused)


def test_the_hub_reads_its_own_id_lazily(monkeypatch):
    from agents.core.satellite_hub import SatelliteHub

    calls = []
    monkeypatch.setattr(ii, "install_id", lambda root=None: (calls.append(1), "a" * 32)[1])
    hub = SatelliteHub()
    assert calls == []
    assert hub._own_hub_id() == "a" * 32 and hub._own_hub_id() == "a" * 32 and calls == [1]
    assert SatelliteHub(hub_id=lambda: "z")._own_hub_id() == "z"
    monkeypatch.setattr(ii, "install_id", lambda root=None: None)
    assert SatelliteHub()._own_hub_id() == ""


# ── review round ─────────────────────────────────────────────────────────────────

def test_a_forget_keeps_the_id_and_the_held_hub_lock(tmp_path):
    """F1: the forget sweep erases everything but its keep list; the id, its lock and the
    hub's own lock are on it, so the id survives and a second hub is still refused."""
    from agents.core import data_purge

    before = ii.install_id(tmp_path)
    ii.acquire_hub_lock(tmp_path)
    (tmp_path / "notes.json").write_text('{"a": 1}', encoding="utf-8")
    report = data_purge.purge_data(source_root=str(tmp_path), backup_first=False)
    assert report["ok"] is True
    assert json.loads((tmp_path / "notes.json").read_text(encoding="utf-8")) == {}
    for name in (ii.ID_FILE, ii.LOCK_FILE, ii.HUB_LOCK_FILE):
        assert (tmp_path / name).is_file(), name
    assert _second_hub(tmp_path) == f"REFUSED {os.getpid()}"
    ii.forget_cache()
    assert ii.install_id(tmp_path) == before


def test_a_profile_root_is_a_sibling_of_the_default_root(tmp_path, monkeypatch):
    """F2: never inside it, so nothing that walks the default root reaches a profile."""
    home = tmp_path / "home"
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert paths.data_root() == tmp_path / "home-profiles" / "work"


def test_the_default_hubs_forget_and_backup_never_reach_a_profile(tmp_path, monkeypatch):
    import tarfile

    from agents.core import backup, data_purge

    home = tmp_path / "home"
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    work = paths.data_root()
    (work / "security").mkdir(parents=True)
    (work / "security" / "secrets.enc").write_bytes(b"WORK-SECRET")
    (work / "security" / "secrets.enc.key").write_bytes(b"WORK-KEY")
    (work / "notes.json").write_text('{"w": 1}', encoding="utf-8")
    monkeypatch.delenv("JARVIS_PROFILE")
    home.mkdir(exist_ok=True)
    (home / "notes.json").write_text('{"a": 1}', encoding="utf-8")

    snap = backup.create_backup(source_root=str(home), out_dir=str(tmp_path / "out"), encrypt=False)
    with tarfile.open(snap["archive"]) as tar:
        names = tar.getnames()
    assert "notes.json" in names and not [n for n in names if "secrets.enc" in n]
    data_purge.purge_data(source_root=str(home), backup_first=False)
    assert json.loads((home / "notes.json").read_text(encoding="utf-8")) == {}
    assert (work / "security" / "secrets.enc").read_bytes() == b"WORK-SECRET"
    assert (work / "security" / "secrets.enc.key").read_bytes() == b"WORK-KEY"
    assert json.loads((work / "notes.json").read_text(encoding="utf-8")) == {"w": 1}


def test_a_bad_profile_name_never_falls_back_to_the_default_root(tmp_path, monkeypatch):
    """F4: a typo is refused wherever the data root is asked for, not only in serve.py."""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_PROFILE", "Work")
    with pytest.raises(RuntimeError, match="not a profile name"):
        paths.data_root()
    with pytest.raises(RuntimeError, match="not a profile name"):
        ii.acquire_hub_lock()


def test_a_forget_under_a_bad_profile_erases_nothing(tmp_path):
    (tmp_path / "notes.json").write_text('{"a": 1}', encoding="utf-8")
    env = {**os.environ, "JARVIS_HOME": str(tmp_path), "JARVIS_PROFILE": "Work"}
    out = subprocess.run([sys.executable, "-m", "agents.core.data_purge", "--confirm", "--no-backup"],
                         capture_output=True, text=True, cwd=str(REPO), env=env, timeout=120)
    assert out.returncode != 0 and "not a profile name" in out.stderr
    assert json.loads((tmp_path / "notes.json").read_text(encoding="utf-8")) == {"a": 1}


def _hold_hub_lock(root) -> subprocess.Popen:
    """Another process holding the hub lock on *root* until its stdin closes."""
    code = (f"import sys; sys.path.insert(0, {str(REPO)!r})\n"
            "from agents.core import install_identity as ii\n"
            f"ii.acquire_hub_lock({str(root)!r}); print('HELD', flush=True); sys.stdin.read()\n")
    holder = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "HELD"
    return holder


def test_the_app_lifespan_is_refused_on_a_held_root(tmp_path, monkeypatch):
    """F5: ``uvicorn agents.web:app`` (docker-compose, CI) takes the same lock as serve.py."""
    from fastapi.testclient import TestClient

    from agents import web

    holder = _hold_hub_lock(tmp_path)
    try:
        monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
        with pytest.raises(ii.HubAlreadyRunning), TestClient(web.app):
            pass
    finally:
        holder.stdin.close()
        holder.wait(timeout=60)


def test_the_app_lifespan_holds_the_lock_until_it_stops():
    from fastapi.testclient import TestClient

    from agents import web

    with TestClient(web.app):
        assert _second_hub(paths.data_root()) == f"REFUSED {os.getpid()}"
    assert _second_hub(paths.data_root()) == "GOT"


class _LockedRead:
    """A handle whose read fails as a mandatory (Windows) lock makes it fail."""

    def __init__(self, handle) -> None:
        self.handle = handle

    def __getattr__(self, name):
        return getattr(self.handle, name)

    def read(self, *args):
        raise PermissionError(13, "lock violation")


def test_a_refused_hub_that_cannot_read_the_pid_is_still_refused(tmp_path, monkeypatch):
    """F6: the refusal is HubAlreadyRunning even when the pid cannot be read, and the
    handle is closed."""
    opened = []

    def locked_open(*args, **kwargs):
        opened.append(open(*args, **kwargs))  # noqa: SIM115 - closed by the code under test
        return _LockedRead(opened[-1])

    monkeypatch.setattr(ii, "_file_lock", lambda handle, blocking: (_ for _ in ()).throw(OSError("held")))
    monkeypatch.setattr(ii, "open", locked_open, raising=False)
    with pytest.raises(ii.HubAlreadyRunning) as err:
        ii.acquire_hub_lock(tmp_path)
    assert err.value.pid == "" and opened[0].closed


def test_the_windows_lock_sits_past_the_pid(tmp_path, monkeypatch):
    """F6: msvcrt locks are mandatory, so the byte locked is not one the pid is read from."""
    seen = []

    class _NT:
        name = "nt"

        def __getattr__(self, attr):
            return getattr(os, attr)

    fake = SimpleNamespace(LK_LOCK=1, LK_NBLCK=2, LK_UNLCK=0,
                           locking=lambda fd, mode, n: seen.append((mode, n, os.lseek(fd, 0, os.SEEK_CUR))))
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    with open(tmp_path / "hub.lock", "a+", encoding="ascii") as handle:
        handle.write("4194304")
        handle.flush()
        monkeypatch.setattr(ii, "os", _NT())
        ii._file_lock(handle, blocking=False)
        ii._file_unlock(handle)
        monkeypatch.undo()
    assert seen == [(2, 1, ii._NT_LOCK_BYTE), (0, 1, ii._NT_LOCK_BYTE)] and ii._NT_LOCK_BYTE > 16


def test_a_forgotten_clock_starts_again(tmp_path):
    """F8: a forget resets activation.json to ``{}``; that is no record, not an unreadable one."""
    from agents.core import data_purge, first_action

    store = tmp_path / "activation.json"
    first_action.mark_installed(store, now=1.0)
    data_purge.purge_data(source_root=str(tmp_path), backup_first=False)
    assert json.loads(store.read_text(encoding="utf-8")) == {}
    task = SimpleNamespace(id=7, kind="k", decided_by="owner", decision="accept")
    got = first_action.record_first_action(task, store, now=9.0)
    assert got is not None and got["activated"]["task_id"] == 7
    assert first_action.activation_state(store, now=9.0)["activated"] is True


def test_the_hub_reads_its_own_id_again_after_a_failure(monkeypatch):
    """F9: only an id is cached; a failed read is asked again."""
    from agents.core.satellite_hub import SatelliteHub

    answers = iter([None, "a" * 32])
    monkeypatch.setattr(ii, "install_id", lambda root=None: next(answers))
    hub = SatelliteHub()
    assert hub._own_hub_id() == "" and hub._own_hub_id() == "a" * 32


def test_a_readable_id_is_read_without_the_lock(tmp_path):
    """F10: the id file is written atomically, so a lock file that cannot be opened does
    not hide it."""
    first = ii.install_id(tmp_path)
    ii.forget_cache()
    (tmp_path / "install_id.lock").unlink()
    (tmp_path / "install_id.lock").mkdir()
    assert ii.install_id(tmp_path) == first


@pytest.mark.parametrize("old", ["0123456789abcdef", None])
def test_an_older_clock_takes_on_the_durable_id(tmp_path, monkeypatch, old):
    """F12: a clock from before H689 (16 hex) or from while the id was unavailable (null)
    takes on the install id; nothing else in it changes."""
    from agents.core import first_action

    monkeypatch.setattr(ii, "install_id", lambda root=None: "a" * 32)
    store = tmp_path / "activation.json"
    clock = {"schema": first_action.SCHEMA, "install_id": old, "installed_at": 1.0,
             "inferred_at_boot": False, "activated": None}
    store.write_text(json.dumps(clock), encoding="utf-8")
    assert first_action.mark_installed(store, now=5.0)["install_id"] == "a" * 32
    assert json.loads(store.read_text(encoding="utf-8")) == {**clock, "install_id": "a" * 32}
    activated = {**clock, "activated": {"at": 2.0, "seconds": 1.0, "band": "under_10_minutes"}}
    store.write_text(json.dumps(activated), encoding="utf-8")
    task = SimpleNamespace(id=1, kind="k", decided_by="owner", decision="accept")
    assert first_action.record_first_action(task, store, now=9.0) is None
    assert json.loads(store.read_text(encoding="utf-8")) == {**activated, "install_id": "a" * 32}
    monkeypatch.setattr(ii, "install_id", lambda root=None: None)
    store.write_text(json.dumps(clock), encoding="utf-8")
    assert first_action.mark_installed(store, now=5.0)["install_id"] == old
    assert json.loads(store.read_text(encoding="utf-8")) == clock
