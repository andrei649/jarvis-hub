"""H689 shared install identity and conservative profile migration."""

from __future__ import annotations

import json
import multiprocessing
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import first_action, paths
from agents.core import install_identity as ii


@pytest.fixture(autouse=True)
def _fresh_identity():
    ii.forget_cache()
    ii.release_hub_lock()
    yield
    ii.forget_cache()
    ii.release_hub_lock()


@pytest.mark.parametrize("selector", ["JARVIS_HOME", "JARVIS_MEMORY_DIR", "JARVIS_USER_HOME"])
def test_default_and_named_profiles_use_one_canonical_identity(tmp_path, monkeypatch, selector):
    for key in ("JARVIS_HOME", "JARVIS_MEMORY_DIR", "JARVIS_USER_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(selector, str(tmp_path / "selected"))
    base = tmp_path / "selected" / "memory" if selector == "JARVIS_USER_HOME" else tmp_path / "selected"
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert paths.install_root() == base
    work = paths.data_root()
    work_id = ii.install_id()
    monkeypatch.setenv("JARVIS_PROFILE", "personal")
    assert paths.install_root() == base and ii.install_id() == work_id
    monkeypatch.delenv("JARVIS_PROFILE")
    assert ii.install_id() == work_id
    assert (base / ii.ID_FILE).read_text().strip() == work_id
    assert not (work / ii.ID_FILE).exists()
    assert paths.data_root() == base


def test_invalid_selected_profile_never_uses_canonical_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_PROFILE", "Bad")
    with pytest.raises(RuntimeError, match="not a profile name"):
        paths.install_root()
    with pytest.raises(RuntimeError, match="not a profile name"):
        ii.install_id()
    assert not (tmp_path / "home").exists()


def _profile_mint(home: str, profile: str, barrier, queue):
    import os

    from agents.core import install_identity

    os.environ["JARVIS_HOME"] = home
    os.environ["JARVIS_PROFILE"] = profile
    barrier.wait(timeout=30)
    queue.put(install_identity.install_id())


def test_two_profile_processes_racing_share_one_first_mint(tmp_path):
    home = tmp_path / "home"
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    procs = [ctx.Process(target=_profile_mint, args=(str(home), profile, barrier, queue))
             for profile in ("work", "personal")]
    for proc in procs:
        proc.start()
    try:
        answers = [queue.get(timeout=40) for _ in procs]
    finally:
        for proc in procs:
            proc.join(timeout=40)
    assert len(set(answers)) == 1 and ii.ID_RE.fullmatch(answers[0])
    assert (home / ii.ID_FILE).read_text().strip() == answers[0]


def _legacy(home: Path, profile: str, content: bytes):
    root = home.parent / f"{home.name}-profiles" / profile
    root.mkdir(parents=True)
    (root / ii.ID_FILE).write_bytes(content)
    return root


def test_sole_legacy_id_is_adopted_without_removing_profile_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    old = "a" * 32
    legacy = _legacy(home, "work", (old + "\n").encode())
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_PROFILE", "personal")
    assert ii.install_id() == old
    assert (home / ii.ID_FILE).read_text() == old + "\n"
    assert (legacy / ii.ID_FILE).read_text() == old + "\n"


@pytest.mark.parametrize("second", [b"b" * 32, b"malformed", b"\xff"])
def test_conflicting_or_bad_legacy_state_refuses_until_repaired(tmp_path, monkeypatch, second):
    home = tmp_path / "home"
    _legacy(home, "work", b"a" * 32)
    other = _legacy(home, "personal", second)
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert ii.install_id() is None and not (home / ii.ID_FILE).exists()
    (other / ii.ID_FILE).write_bytes(b"a" * 32)
    assert ii.install_id() == "a" * 32


def test_symlinked_legacy_file_is_not_followed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    target = tmp_path / "foreign"
    target.write_text("a" * 32)
    root = home.parent / "home-profiles" / "work"
    root.mkdir(parents=True)
    (root / ii.ID_FILE).symlink_to(target)
    monkeypatch.setenv("JARVIS_HOME", str(home))
    assert ii.install_id() is None and not (home / ii.ID_FILE).exists()


def test_unreadable_legacy_file_refuses_without_minting(tmp_path, monkeypatch):
    home = tmp_path / "home"
    legacy = _legacy(home, "work", b"a" * 32) / ii.ID_FILE
    monkeypatch.setenv("JARVIS_HOME", str(home))
    real_read = ii._read

    def unreadable(path):
        if path == legacy:
            raise PermissionError("legacy profile not readable")
        return real_read(path)

    monkeypatch.setattr(ii, "_read", unreadable)
    assert ii.install_id() is None and not (home / ii.ID_FILE).exists()


def test_valid_canonical_wins_over_legacy_and_corrupt_canonical_is_never_overwritten(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _legacy(home, "work", b"b" * 32)
    home.mkdir()
    canonical = home / ii.ID_FILE
    canonical.write_text("a" * 32)
    monkeypatch.setenv("JARVIS_HOME", str(home))
    assert ii.install_id() == "a" * 32
    ii.forget_cache()
    canonical.write_bytes(b"broken")
    assert ii.install_id() is None and canonical.read_bytes() == b"broken"


def test_only_selected_profiles_proven_legacy_activation_id_migrates(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / ii.ID_FILE).write_text("a" * 32)
    profile = _legacy(home, "work", b"b" * 32)
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    clock = profile / "activation.json"
    record = {"schema": first_action.SCHEMA, "install_id": "b" * 32,
              "installed_at": 1.0, "inferred_at_boot": False, "activated": None}
    clock.write_text(json.dumps(record))
    got = first_action.mark_installed(clock, now=2.0)
    assert got["install_id"] == "a" * 32 and got["previous_install_id"] == "b" * 32
    assert json.loads(clock.read_text())["previous_install_id"] == "b" * 32
    foreign = {**record, "install_id": "c" * 32}
    clock.write_text(json.dumps(foreign))
    assert first_action.mark_installed(clock, now=2.0)["migration_required"] is True
    assert json.loads(clock.read_text()) == foreign
    assert first_action.activation_state(clock, now=2.0)["migration_required"] is True
    task = SimpleNamespace(id=1, kind="k", decided_by="owner", decision="accept")
    assert first_action.record_first_action(task, clock, now=3.0) is None
    assert json.loads(clock.read_text()) == foreign

    copied = tmp_path / "copied_activation.json"
    copied.write_text(json.dumps(record))  # same old ID, outside the selected profile
    assert first_action.mark_installed(copied, now=4.0)["migration_required"] is True
    assert json.loads(copied.read_text()) == record


def test_symlinked_profile_directory_cannot_prove_activation_migration(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / ii.ID_FILE).write_text("a" * 32)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / ii.ID_FILE).write_text("b" * 32)
    siblings = tmp_path / "home-profiles"
    siblings.mkdir()
    (siblings / "work").symlink_to(foreign, target_is_directory=True)
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    clock = foreign / "activation.json"
    record = {"schema": first_action.SCHEMA, "install_id": "b" * 32,
              "installed_at": 1.0, "inferred_at_boot": False, "activated": None}
    clock.write_text(json.dumps(record))
    assert first_action.mark_installed(clock, now=2.0)["migration_required"] is True
    assert json.loads(clock.read_text()) == record


def test_profile_hub_locks_stay_separate_from_shared_id(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    first = ii.install_id()
    ii.acquire_hub_lock()
    try:
        assert (tmp_path / "home-profiles" / "work" / ii.HUB_LOCK_FILE).exists()
        assert ii.install_id() == first
        assert not (home / ii.HUB_LOCK_FILE).exists()
    finally:
        ii.release_hub_lock()


def test_windows_identity_lock_prepares_byte_and_hub_pid_stays_readable(tmp_path, monkeypatch):
    pid = {"value": os.getpid()}

    class NT:
        name = "nt"

        @staticmethod
        def getpid():
            return pid["value"]

        def __getattr__(self, name):
            return getattr(os, name)

    class Msvcrt:
        LK_LOCK = 1
        LK_NBLCK = 2
        LK_UNLCK = 3
        held = False

        @staticmethod
        def locking(fd, mode, count):
            assert count == 1 and os.lseek(fd, 0, os.SEEK_CUR) == ii._NT_LOCK_BYTE
            assert os.fstat(fd).st_size > ii._NT_LOCK_BYTE
            if mode == Msvcrt.LK_NBLCK and Msvcrt.held:
                raise BlockingIOError("hub lock held")

    monkeypatch.setitem(sys.modules, "msvcrt", Msvcrt)
    monkeypatch.setattr(ii, "os", NT())

    real_open = ii._open_hub_lock

    class Guarded:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def truncate(self, size=None):
            assert size is not None and size > ii._NT_LOCK_BYTE, "locked byte was truncated"
            return self.handle.truncate(size)

    def guarded_open(path):
        return Guarded(real_open(path))

    monkeypatch.setattr(ii, "_open_hub_lock", guarded_open)
    assert ii.ID_RE.fullmatch(ii.install_id(tmp_path))
    handle = ii.acquire_hub_lock(tmp_path)
    try:
        assert handle is not None
        assert (tmp_path / ii.HUB_LOCK_FILE).read_text().strip() == str(os.getpid())
        assert (tmp_path / ii.HUB_LOCK_FILE).read_text()[:32].strip() == str(os.getpid())
        Msvcrt.held = True
        ii._hub_handle = None  # simulate another process against the held inode
        with pytest.raises(ii.HubAlreadyRunning) as refused:
            ii.acquire_hub_lock(tmp_path)
        assert refused.value.pid == str(os.getpid())
    finally:
        ii._hub_handle = handle
        Msvcrt.held = False
        ii.release_hub_lock()
    lock_path = tmp_path / ii.HUB_LOCK_FILE
    inode = lock_path.stat().st_ino
    pid["value"] = 987654
    ii.acquire_hub_lock(tmp_path)
    try:
        assert lock_path.read_text()[:32].strip() == "987654"
        assert lock_path.stat().st_ino == inode
    finally:
        ii.release_hub_lock()


@pytest.mark.asyncio
async def test_identity_bound_owner_routes_return_fixed_503(tmp_path, monkeypatch):
    from agents.core.channels.pairing import SenderPairing
    from agents.core.node_mesh import NodeMesh
    from agents.core.routers import mesh, pairing

    monkeypatch.setattr(ii, "install_id", lambda root=None: None)
    nodes = NodeMesh(capability_broker=SimpleNamespace(issue=lambda *a, **k: pytest.fail("token issued")))
    sender = SenderPairing(tmp_path / "sender.json")
    monkeypatch.setattr(mesh, "require_component", lambda *a: (None, nodes, None))
    monkeypatch.setattr(pairing, "_get_sender_pairing", lambda: sender)
    node = await mesh.nodes_register(mesh.NodeRegisterBody(node_id="phone", capabilities=["notify"]))
    link = await pairing.pairing_mint_link(pairing.PairingLinkBody(channel="telegram"))
    assert node.status_code == link.status_code == 503
    assert json.loads(node.body) == json.loads(link.body) == {
        "ok": False, "reason": ii.UNAVAILABLE_REASON,
    }
    assert nodes.nodes() == [] and sender.outstanding_deeplinks() == 0
