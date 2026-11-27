"""Local vault synchronization for the hub lifespan and optional owner-supplied builders."""
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
from contextlib import closing, suppress
from pathlib import Path

from agents.core.env_config import env_flag, env_str
from agents.core.extensions.store_lock import locked_store
from agents.core.paths import data_root

log = logging.getLogger("jarvis.web")

# The legacy Python builder uses DATA_DIR for its temporary SQLite file and OUT_DB
# for publication. Give both a staging destination, retaining its read-only inputs.
_STAGE = """
import pathlib, runpy, sys
script, dest, vault = map(pathlib.Path, sys.argv[1:4])
root_setting = sys.argv[4]
main = runpy.run_path(str(script))['main']
if root_setting not in main.__globals__:
    raise ValueError('unsupported builder input')
main.__globals__.update(DATA_DIR=dest.parent, OUT_DB=dest)
main.__globals__[root_setting] = vault
main()
"""


def _run(argv, *, capture=False, stop=None):
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "HOME", "USERPROFILE", "LOCALAPPDATA"}}
    env["PYTHONUTF8"] = "1"
    if stop is None:
        # Fixed owner-configured local builder argv with shell=False and scrubbed env.
        return subprocess.run(argv, stdin=subprocess.DEVNULL,  # nosec B603
                              stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, shell=False, timeout=180, check=True, env=env,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL,  # nosec B603
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, shell=False, env=env,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as child:
        deadline = time.monotonic() + 180
        while True:
            if stop.is_set():
                child.kill()
                child.communicate()
                raise RuntimeError("builder stopped")
            try:
                output, _ = child.communicate(timeout=min(.2, max(.01, deadline - time.monotonic())))
                if child.returncode:
                    raise subprocess.CalledProcessError(child.returncode, argv)
                return output
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    child.kill()
                    child.communicate()
                    raise


def _copy_permitted_inputs(cfg, destination, *, stop=None):
    from agents.core.routers import jarvis_os
    engine = jarvis_os._engine()
    include, exclude = engine._folder_policy(cfg)
    with engine.vault_fs.VaultFs(Path(cfg["vaultPath"]), allow_hardlinks=engine._allow_hardlinks(cfg)) as vault:
        for parts, entry, data in vault.walk(
            want=lambda name: name.lower().endswith(".md"), cap=lambda _: engine._NOTE_READ_CAP,
            allow_dir=lambda p: engine._vault_path_allowed(p, include, exclude, directory=True),
            allow_file=lambda p: engine._vault_path_allowed(p, include, exclude, directory=False),
        ):
            if stop is not None and stop.is_set():
                raise RuntimeError("builder stopped")
            if entry.dataless or len(data) != entry.size or not engine._markdown_is_visible(data, entry.size):
                continue
            target = destination.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def rebuild_if_stale(cfg, source_ns, signature="", *, stop=None):
    if not env_flag("NERVA_AUTO_BUILD_VAULT_INDEX") or not (source_ns or signature):
        return
    projects = env_str("NERVA_VAULT_PROJECTS_SCRIPT")
    builder = env_str("NERVA_VAULT_FTS_BUILD_SCRIPT")
    dst = data_root() / "verified_vault_fts.sqlite"
    node = env_str("NERVA_VAULT_NODE")
    python = env_str("NERVA_SECOND_BRAIN_PYTHON") or sys.executable
    root_setting = env_str("NERVA_VAULT_BUILDER_ROOT_SETTING", "VAULT_ROOT")
    if not (builder and Path(builder).is_file() and root_setting.isidentifier()):
        return
    dest = dst.absolute()
    stamp = hashlib.sha256(json.dumps([signature or source_ns, cfg["vaultPath"], cfg.get("vaultInclude"),
                                       cfg.get("vaultExclude"), cfg.get("allowHardLinks")]).encode()).hexdigest()
    with locked_store(dest):
        if stop is not None and stop.is_set():
            return
        if dest.is_file():
            try:
                with closing(sqlite3.connect(dest.as_uri() + "?mode=ro", uri=True)) as db:
                    if db.execute("SELECT inventory FROM nerva_verified_build").fetchone() == (stamp,):
                        return
            except sqlite3.Error:
                pass
        with tempfile.TemporaryDirectory(dir=dest.parent, prefix=".vault-build-") as directory:
            # External generators walk their input recursively. Give them a scoped
            # snapshot so they cannot enumerate excluded areas or replace the owner's catalog.
            vault = Path(directory) / "vault"
            vault.mkdir(mode=0o700)
            _copy_permitted_inputs(cfg, vault, stop=stop)
            if projects and node and Path(projects).is_file():
                _run([node, projects, "build", "--vault", str(vault), "--no-mc"], stop=stop)
            staged = Path(directory) / "candidate.sqlite"
            raw = _run([python, "-I", "-c", _STAGE, builder, str(staged), str(vault), root_setting],
                       capture=True, stop=stop)
            if stop is not None and stop.is_set():
                return
            receipt = json.loads(raw)
            hits = receipt.get("unmasked_friend_core_names")
            if receipt.get("ok") is not True or type(hits) is not int or hits != 0 or not staged.is_file():
                raise ValueError("vault database privacy check failed")
            with closing(sqlite3.connect(staged.as_uri() + "?mode=ro", uri=True)) as db:
                valid = db.execute("PRAGMA quick_check").fetchone() == ("ok",)
            if not valid:
                raise ValueError("vault database integrity check failed")
            with closing(sqlite3.connect(staged)) as db:
                db.execute("CREATE TABLE nerva_verified_build (inventory TEXT NOT NULL)")
                db.execute("INSERT INTO nerva_verified_build VALUES (?)", (stamp,))
                db.commit()
            if stop is not None and stop.is_set():
                return
            os.replace(staged, dest)


async def watch(stop: asyncio.Event):
    from agents.core.memory import second_brain
    from agents.core.routers import jarvis_os
    configured = bool(env_str("JARVIS_OS_VAULT_PATH").strip())
    if not (configured or env_str("NERVA_MEMORY_COPILOT_URL") or env_flag("NERVA_AUTOSTART_MEMORY_COPILOT")):
        return
    try:
        await asyncio.to_thread(second_brain.start_memory_copilot)
    except Exception:
        log.warning("Memory Copilot startup unavailable")
    if not configured:
        return
    first = True
    built = None
    retry_after = 0.0
    unavailable = False
    build_thread = None
    build_result = {}
    build_stop = threading.Event()
    build_signature = None

    def build(cfg, stamp, signature):
        try:
            rebuild_if_stale(cfg, stamp, signature, stop=build_stop)
        except Exception as exc:
            build_result["error"] = exc

    while not stop.is_set():
        try:
            if build_thread is not None and not build_thread.is_alive():
                if "error" in build_result:
                    log.warning("Local vault builder failed. The previous verified copy was preserved.")
                    retry_after = time.monotonic() + 60
                else:
                    built = build_signature
                build_thread = None
                build_result = {}
            engine = jarvis_os._engine()
            if engine is None:
                return
            cfg = jarvis_os._config(engine)
            if jarvis_os._vault_available(cfg):
                stats = await asyncio.to_thread(engine.sync_vault_index, cfg)
                if stats.get("ok") is not True:
                    raise ValueError("vault index unavailable")
                unavailable = False
                if first:
                    health = await asyncio.to_thread(second_brain.health)
                    log.info("Vault: connected (%d notes) | Memory Copilot: %s", stats["indexedNotes"],
                             env_str("NERVA_MEMORY_COPILOT_URL").removeprefix("http://").rstrip("/") + " OK"
                             if health["connected"] else "offline")
                stamp = stats.get("sourceMtimeNs")
                signature = stats.get("sourceSignature") or stamp
                if (signature and signature != built and build_thread is None and
                        time.monotonic() >= retry_after and env_flag("NERVA_AUTO_BUILD_VAULT_INDEX")):
                    build_signature = signature
                    build_thread = threading.Thread(target=build, args=(cfg, stamp, signature),
                                                    name="vault-optional-builder", daemon=True)
                    build_thread.start()
            elif first:
                log.warning("Configured vault unavailable")
            first = False
        except Exception:
            if not unavailable:
                log.warning("Vault synchronization unavailable; retrying locally")
                unavailable = True
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=2)
    build_stop.set()
    if build_thread is not None:
        await asyncio.to_thread(build_thread.join, .2)
