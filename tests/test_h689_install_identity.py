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


def _mint(root, queue):
    from agents.core import install_identity

    queue.put(install_identity.install_id(root))


def test_racing_processes_agree_on_one_id(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    procs = [ctx.Process(target=_mint, args=(str(tmp_path), queue)) for _ in range(4)]
    for p in procs:
        p.start()
    got = {queue.get(timeout=60) for _ in procs}
    for p in procs:
        p.join(timeout=60)
    assert len(got) == 1 and ii.ID_RE.match(got.pop())


def test_the_lock_guards_the_mint(tmp_path, monkeypatch):
    calls = []
    real_lock, real_unlock = ii._file_lock, ii._file_unlock
    monkeypatch.setattr(ii, "_file_lock", lambda h, blocking: (calls.append(("lock", blocking)), real_lock(h, blocking=blocking)))
    monkeypatch.setattr(ii, "_file_unlock", lambda h: (calls.append(("unlock",)), real_unlock(h)))
    ii.install_id(tmp_path)
    assert calls == [("lock", True), ("unlock",)]
    assert (tmp_path / "install_id.lock").exists()


# ── one hub per root ─────────────────────────────────────────────────────────────

def test_a_second_hub_on_the_same_root_is_refused(tmp_path):
    handle = ii.acquire_hub_lock(tmp_path)
    assert ii.acquire_hub_lock(tmp_path) is handle                        # idempotent in-process
    assert (tmp_path / "hub.lock").read_text(encoding="ascii") == str(os.getpid())
    code = (f"import sys; sys.path.insert(0, {str(REPO)!r})\n"
            "from agents.core import install_identity as ii\n"
            f"try:\n    ii.acquire_hub_lock({str(tmp_path)!r})\nexcept ii.HubAlreadyRunning as e:\n"
            "    print('REFUSED', e.pid)\nelse:\n    print('GOT')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == f"REFUSED {os.getpid()}"
    ii.release_hub_lock()
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "GOT"


def test_the_refusal_names_the_holder():
    err = ii.HubAlreadyRunning(Path("/x"), "")
    assert "pid unknown" in str(err) and "/x" in str(err)
    assert "pid 42" in str(ii.HubAlreadyRunning(Path("/x"), "42"))


def test_serve_takes_the_lock_before_starting():
    src = (REPO / "serve.py").read_text(encoding="utf-8")
    main = src[src.index("def main():"):]
    assert main.index("install_identity.acquire_hub_lock()") < main.index("uvicorn.Server(config).run()")
    assert "raise SystemExit(f\"Nerva is already running on this data root: {exc}\")" in main
    assert main.index("profile_error()") < main.index("acquire_hub_lock()")
    assert "refused = profile_error()\n    if refused:\n        raise SystemExit(refused)" in main


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
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    assert paths.data_root() == tmp_path
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert paths.data_root() == tmp_path / "profiles" / "work"
    assert paths.data_path("settings.db") == tmp_path / "profiles" / "work" / "settings.db"
    monkeypatch.setenv("JARVIS_PROFILE", "Bad Name")
    assert paths.data_root() == tmp_path
    assert "not a profile name" in paths.profile_error()


def test_a_profile_without_a_home_sits_under_the_default_root(monkeypatch):
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    monkeypatch.delenv("JARVIS_USER_HOME", raising=False)
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    assert paths.data_root() == paths._DEFAULT_ROOT / "profiles" / "work"


def test_two_profiles_have_two_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_PROFILE", "one")
    one = ii.install_id()
    monkeypatch.setenv("JARVIS_PROFILE", "two")
    assert ii.install_id() != one


def test_credentials_resolve_under_the_profile_root(tmp_path):
    env = {**os.environ, "JARVIS_HOME": str(tmp_path), "JARVIS_PROFILE": "work"}
    code = "from agents.core import secrets; print(secrets.DEFAULT_STORE)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO), env=env, timeout=120)
    assert out.stdout.strip() == str(tmp_path / "profiles" / "work" / "security" / "secrets.enc")


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
