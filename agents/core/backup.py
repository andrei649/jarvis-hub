"""backup.py — one-command local backup / restore + restore-drill (roadmap 0.14 · H23.8).

All persistent runtime state lives under a single root (``paths.data_root()``):
SQLite DBs (settings, autonomy, missions, analytics, marketplace, notes …),
JSON stores, tokens, audio, eval corpora. This module snapshots that root into a
single ``.tar.gz`` and restores it, with three honesty/safety properties a real
backup needs:

* **Consistent DB snapshots.** A live SQLite DB in WAL mode must not be copied
  byte-for-byte mid-write. Each ``*.db`` is snapshotted through the SQLite online
  backup API (``Connection.backup``), which takes a transactionally-consistent
  copy even while the app is running; the transient ``-wal`` / ``-shm`` sidecars
  are skipped (their content is already folded into the snapshot).
* **A real restore drill.** ``verify_backup`` extracts the archive into a temp
  dir and runs ``PRAGMA integrity_check`` on every DB — so "we have backups" is
  provable, not assumed, without touching live data.
* **No archive path-traversal, no quiet partial restore.** Extraction goes through
  the shared ``agents.core.archive_safe`` module (H503): member names are normalised
  (``\\`` folded, absolute / drive-lettered / ``..`` refused), only regular files and
  dirs are written, and a symlink, hardlink or device member RAISES instead of being
  skipped — validated before a byte is written, under a member-count and a
  total-bytes cap (``JARVIS_BACKUP_MAX_MEMBERS`` / ``JARVIS_BACKUP_MAX_BYTES``). The
  manifest's ``file_count`` is checked against what the archive actually held, so a
  shortened archive fails the drill instead of passing it.
* **A failed backup never impersonates or destroys a good one.** The archive is
  written to a sibling temp file and ``os.replace``d into place (GNU tar format, so
  macOS Archive Utility opens it); the export walk skips symlinks, so a link planted
  in the data root cannot pull an arbitrary file into the archive. Every other name is
  archived as a regular member, hardlinked ones included; a path that stops being a
  regular file mid-backup is listed in the manifest's ``dropped``, never counted.
* **An in-place restore replaces, never writes through.** ``--force`` into the live
  root unlinks a link or hardlinked name before writing the file, and credits the
  files it overwrites against the free-space clamp.

CLI: ``nerva-run -m agents.core.backup create|list|verify|restore`` (the
one-command story; :data:`PROG`). Run it with the service's environment — the pilot
guide's ``nerva-run`` (PILOT_GUIDE §2) runs the venv's ``python`` as the service's user
with the service's ``EnvironmentFile`` and ``UMask``, so the data root,
``JARVIS_KEY_DIR`` and ``JARVIS_BACKUP_KEY`` are the hub's own — never from a bare
shell, whose defaults would back up (or look for archives of) another data root with
another key. Restore refuses to overwrite a non-empty target unless ``--force``.
"""

from __future__ import annotations

import argparse
import errno
import json
import logging
import os
import re
import secrets
import sqlite3
import stat
import tarfile
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from agents.core import archive_safe
from agents.core.archive_safe import ArchiveLimits
from agents.core.env_config import env_int, env_str
from agents.core.paths import data_root
from agents.core.secrets import SecretStore, SecretStoreError, _looks_like_fernet_key

logger = logging.getLogger("jarvis.backup")

BACKUP_VERSION = 1
_ARCHIVE_PREFIX = "jarvis-backup-"
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")
_ENC_SUFFIX = ".enc"  # an encrypted archive is "<name>.tar.gz.enc"
_MANIFEST_NAME = "backup_manifest.json"  # the last member of every archive create_backup writes

# H503 bomb caps for unpacking a backup (verify drill + restore). Generous, because a
# real data root holds audio, media and many small files and a false refusal on the
# owner's own restore is its own failure; the byte budget is ALSO clamped to the free
# space on the destination by archive_safe, which is what actually protects the disk.
# Both are owner-tunable; a malformed or non-positive value keeps the default.
BACKUP_MAX_MEMBERS_DEFAULT = 1_000_000
BACKUP_MAX_BYTES_DEFAULT = 64 * 1024 ** 3

# An atomic_write temp file older than this is debris from a killed backup, not one
# still being written (a live one's mtime moves with every write).
_ABANDONED_TEMP_SECONDS = 3600.0


def backup_limits() -> ArchiveLimits:
    """The member-count and uncompressed-bytes caps applied when a backup is unpacked."""
    return ArchiveLimits(
        max_members=env_int("JARVIS_BACKUP_MAX_MEMBERS", BACKUP_MAX_MEMBERS_DEFAULT, minimum=1),
        max_bytes=env_int("JARVIS_BACKUP_MAX_BYTES", BACKUP_MAX_BYTES_DEFAULT, minimum=1),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── archive encryption (AUD-1 / F2) ───────────────────────────────
# A backup archives settings.db, tokens/ and secrets.enc — so it must not sit on
# disk as plaintext. When a backup key is configured the whole archive is
# encrypted with the key-managed cipher in agents.core.secrets. The key lives
# OUTSIDE the data root (so a stolen archive never ships its own key): an explicit
# arg / $JARVIS_BACKUP_KEY, else $JARVIS_SECRET_KEY (SecretStore's own fallback), else a
# persisted keyfile under $JARVIS_KEY_DIR — generated by create, never by verify / restore.

def _key_dir() -> Path:
    return Path(os.environ.get("JARVIS_KEY_DIR") or (Path.home() / ".config" / "jarvis"))


def _backup_cipher(key: Optional[str]) -> SecretStore:
    """A SecretStore whose key resolves to the backup key (never the data root).

    Reuses SecretStore's full key management (raw key / passphrase / generated
    keyfile) and its Fernet-or-fallback cipher; the keyfile, if generated, lands
    in $JARVIS_KEY_DIR — outside the archived data root.
    """
    kd = _key_dir()
    kd.mkdir(parents=True, exist_ok=True)
    return SecretStore(path=kd / "backup.cipher",
                       key=key or os.environ.get("JARVIS_BACKUP_KEY") or None)


_KEY_FILE = "backup.cipher.key"     # SecretStore(<key dir>/backup.cipher) → .key / .salt
_SALT_FILE = "backup.cipher.salt"
_SERVICE_ENV = "run with the service's environment: nerva-run, PILOT_GUIDE §2"


class BackupKeyMissing(SecretStoreError):
    """Decrypting needs a key file or a salt that does not exist (REV-POLISH-04).

    A read (verify, restore) never mints key material: a key or salt made now could not
    open an archive made before, and it would stay in the key directory for the next
    ``create`` to use — a key that is in no off-site copy. ``reason`` is the operator's line.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _backup_key_source(key: Optional[str]) -> tuple[str, Optional[str]]:
    """``(source, missing)``: where a decryption's key comes from, in an operator's words.

    Resolved the way :func:`_backup_cipher` and ``SecretStore`` resolve it: the key given,
    ``$JARVIS_BACKUP_KEY``, ``$JARVIS_SECRET_KEY`` (SecretStore's own fallback), else the key
    file ``$JARVIS_KEY_DIR/backup.cipher.key``; a passphrase (not a Fernet key) also needs its
    salt ``$JARVIS_KEY_DIR/backup.cipher.salt``. *missing* says which key file or salt is
    needed but does not exist, else it is ``None`` (REV-POLISH-04).
    """
    kd = _key_dir()
    unset = f"JARVIS_BACKUP_KEY is not set: {_SERVICE_ENV}"
    backup_key, secret_key = env_str("JARVIS_BACKUP_KEY"), env_str("JARVIS_SECRET_KEY")
    if key:
        name, secret = "the key given", key
    elif backup_key:
        name, secret = "JARVIS_BACKUP_KEY in this environment", backup_key
    elif secret_key:
        name, secret = f"JARVIS_SECRET_KEY in this environment ({unset})", secret_key
    else:
        keyfile = kd / _KEY_FILE
        if keyfile.exists():
            return f"the key file {keyfile} ({unset})", None
        return "", (f"JARVIS_BACKUP_KEY is not set ({_SERVICE_ENV}) and there is no key "
                    f"file {keyfile}")
    if _looks_like_fernet_key(secret):
        return name, None
    salt = kd / _SALT_FILE
    if salt.exists():
        return f"{name} (a passphrase, with the salt {salt})", None
    return "", (f"{name} is a passphrase and its salt {salt} does not exist (the key directory "
                f"is kept off-site, PILOT_GUIDE §14)")


def _should_encrypt(encrypt: Optional[bool], key: Optional[str]) -> bool:
    """Resolve whether to encrypt: explicit flag wins, else 'a key is configured'."""
    if encrypt is not None:
        return encrypt
    return bool(key or os.environ.get("JARVIS_BACKUP_KEY"))


def _is_encrypted(name: str) -> bool:
    return name.endswith(_ENC_SUFFIX)


@contextmanager
def _readable_archive(arc: Path, key: Optional[str]) -> Iterator[Path]:
    """Yield a path to a readable (plaintext) ``.tar.gz``, decrypting if needed.

    Raises :class:`BackupKeyMissing` before anything is created when the key file or the
    salt the key needs does not exist (no key material is minted on a read).
    """
    if _is_encrypted(arc.name):
        _source, missing = _backup_key_source(key)
        if missing is not None:
            raise BackupKeyMissing(missing)
        store = _backup_cipher(key)
        with tempfile.TemporaryDirectory() as td:
            plain = Path(td) / "archive.tar.gz"
            plain.write_bytes(store.decrypt_bytes(arc.read_bytes()))
            yield plain
    else:
        yield arc


def _is_within(path: Path, root: Path) -> bool:
    root = root.resolve()
    p = path.resolve()
    return p == root or root in p.parents


def _sqlite_consistent_copy(src: Path, dst: Path) -> None:
    """Transactionally-consistent copy of a (possibly live, WAL-mode) SQLite DB."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(src))
    dest = sqlite3.connect(str(dst))
    try:
        with dest:
            source.backup(dest)
    finally:
        dest.close()
        source.close()


def _integrity_check(db: Path) -> str:
    """Run PRAGMA integrity_check; return 'ok' or the first problem reported."""
    try:
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        return row[0] if row else "empty"
    except sqlite3.DatabaseError as e:
        return f"error: {e}"


def default_backup_dir(source_root: Optional[Path] = None) -> Path:
    return (source_root or data_root()) / "backups"


# ── AUDIT-2c: the pre-forget archive ──────────────────────────────
# The safety net for `POST /api/admin/forget` used to land in `<data_root>/backups`,
# unencrypted unless a key happened to be configured, with no API way to decline it and
# nothing pruning it. So a forget did not erase the user's data — it CONCENTRATED what was
# scattered across the data root into one grab-and-go archive, and left it inside the
# folder it had just cleaned. Every marker the adversarial audit planted was recoverable
# from it, including a settings.db token.
#
# Three properties now, and they are the whole point of the change: the archive lives
# OUTSIDE the data root (so purging the root cannot leave a copy behind), it is encrypted
# unconditionally (the cipher key resolves under $JARVIS_KEY_DIR, never inside the archive
# — `_backup_cipher` generates one if the owner set none), and old ones are pruned,
# because "keep every full copy forever" is a strange reading of a deletion request.
def pre_forget_dir(source_root: Optional[Path] = None) -> Path:
    """Where pre-forget archives live: a sibling of the data root, never inside it."""
    override = os.environ.get("JARVIS_FORGET_ARCHIVE_DIR")
    if override:
        return Path(override)
    root = Path(source_root) if source_root else data_root()
    return root.parent / f"{root.name}-forget-archives"


def prune_pre_forget_archives(keep: Optional[int] = None,
                              source_root: Optional[Path] = None) -> list[str]:
    """Keep only the newest *keep* pre-forget archives; return what was removed.

    Defaults to 1 — enough to undo the most recent forget, which is what the safety net
    is for. Retaining more means retaining more complete copies of data the owner asked
    to be deleted, which is the opposite of the request. ``JARVIS_FORGET_ARCHIVE_KEEP``
    overrides; 0 keeps none.
    """
    if keep is None:
        try:
            keep = int(os.environ.get("JARVIS_FORGET_ARCHIVE_KEEP", "1"))
        except ValueError:
            keep = 1
    keep = max(0, keep)
    out = pre_forget_dir(source_root)
    if not out.is_dir():
        return []
    archives = sorted(
        (p for p in out.iterdir() if p.is_file() and p.name.startswith(_ARCHIVE_PREFIX)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = []
    for stale in archives[keep:]:
        try:
            stale.unlink()
            removed.append(stale.name)
        except OSError:
            logger.warning("could not prune stale pre-forget archive %s", stale.name)
    return removed


# ── retention ─────────────────────────────────────────────────────

# How many ordinary backups to keep. Seven is a week of daily snapshots: long
# enough to notice a corruption that happened while you were away, short enough
# that a full copy of the data root does not fill a laptop. Deliberately NOT the
# pre-forget default of 1 — that archive exists to undo one deletion, and keeping
# more of it would retain more copies of data someone asked to have deleted.
BACKUP_KEEP_DEFAULT = 7


def prune_backups(keep: Optional[int] = None,
                  out_dir: Optional[str] = None) -> list[str]:
    """Keep only the newest *keep* ordinary backups; return what was removed.

    Without this, an automatic backup writes a full copy of the data root every
    night and never stops — which turns a safety feature into the thing that
    fills the owner's disk. ``keep=0`` removes everything, and is a real request
    rather than a guard to defend against: someone turning backups off entirely
    may well want the archives gone too.
    """
    if keep is None:
        keep = BACKUP_KEEP_DEFAULT
    keep = max(0, int(keep))
    out = Path(out_dir) if out_dir else default_backup_dir()
    if not out.is_dir():
        return []
    archives = sorted(_iter_archives(out), key=lambda p: p.stat().st_mtime, reverse=True)
    removed: list[str] = []
    for stale in archives[keep:]:
        try:
            stale.unlink()
            removed.append(stale.name)
        except OSError:
            # A file we cannot remove is reported by its absence from `removed`
            # rather than raising: a prune that failed must not fail the backup
            # that just succeeded.
            logger.warning("could not prune stale backup %s", stale.name)
    return removed


def backup_health(out_dir: Optional[str] = None,
                  *, now: Optional[float] = None) -> dict:
    """Whether there is actually a recent backup — not whether one was attempted.

    A backup that has been failing quietly for a month is worse than none at all,
    because the owner believes they have one. So this reports the AGE of the
    newest archive and says plainly when there is nothing: "no backup has ever
    been made" and "the last backup is 40 days old" are different findings, and
    neither is an empty list.

    ``encrypted`` is reported per archive because an unencrypted local archive of
    the entire data root is a fact the owner should be able to see, not infer.
    """
    moment = time.time() if now is None else float(now)
    rows = list_backups(out_dir)
    total_bytes = sum(int(r.get("bytes") or 0) for r in rows)
    if not rows:
        return {
            "ok": False,
            "count": 0,
            "total_bytes": 0,
            "reason": "no backup has ever been made",
            "age_seconds": None,
            "newest": None,
            "all_encrypted": None,
        }
    newest = rows[0]
    try:
        stamp = datetime.fromisoformat(str(newest["modified_at"])).timestamp()
    except (TypeError, ValueError):
        stamp = moment
    age = max(0.0, moment - stamp)
    return {
        # "ok" is about recency, not about whether the directory has files in it.
        "ok": age <= _STALE_AFTER_SECONDS,
        "count": len(rows),
        "total_bytes": total_bytes,
        "reason": "" if age <= _STALE_AFTER_SECONDS else f"the newest backup is {int(age // 86_400)} day(s) old",
        "age_seconds": age,
        "newest": newest["name"],
        # None would be ambiguous with "no archives"; with archives present this is
        # a real yes/no about every one of them.
        "all_encrypted": all(bool(r.get("encrypted")) for r in rows),
    }


# Two days: one missed nightly run is a hiccup, two is a pattern worth surfacing.
_STALE_AFTER_SECONDS = 2 * 86_400.0


# ── create ────────────────────────────────────────────────────────
_RUN_DIR = re.compile(r"nerva-sandbox-[a-z0-9_]{8}")


def _owner_sandbox_root(root: Path) -> tuple[str, ...] | None:
    """The sandbox root the owner chose, as parts relative to the data root, when it is
    inside it (else None)."""
    try:
        from .exec_cache import resolve_root

        chosen, managed = resolve_root()
        if managed:
            return None
        return Path(os.path.realpath(chosen)).relative_to(os.path.realpath(root)).parts
    except Exception:  # noqa: BLE001 (no settings, a bad root: nothing more to leave out)
        return None


def _in_exec_cache(path: Path, root: Path, owner_root: tuple[str, ...] | None = None) -> bool:
    """The sandbox's files stay out of a backup: the managed cache, and a run directory
    (exactly as mkdtemp names it, ``nerva-sandbox-`` and eight characters) directly under
    the root the owner chose inside the data root (review-H667b nit 3). A folder of the
    owner's that merely starts with the prefix is kept (review-H667c m2)."""
    try:
        parts = Path(path).relative_to(root).parts
    except ValueError:
        return False
    if parts[:2] == ("cache", "exec"):
        return True
    if owner_root is None:
        return False
    depth = len(owner_root)
    return (len(parts) > depth + 1 and parts[:depth] == owner_root
            and bool(_RUN_DIR.fullmatch(parts[depth])))


def create_backup(source_root: Optional[str] = None, out_dir: Optional[str] = None,
                  label: str = "", encrypt: Optional[bool] = None,
                  key: Optional[str] = None) -> dict:
    """Snapshot the data root into a single ``.tar.gz``; return a manifest dict.

    DBs are copied through the SQLite backup API (consistent); everything else is
    archived as-is. The output ``backups/`` dir and SQLite sidecars are excluded.

    When a backup key is configured (``key`` arg / ``$JARVIS_BACKUP_KEY``) or
    ``encrypt=True``, the archive is encrypted at rest (``.tar.gz.enc``) so it
    carries no plaintext secrets (AUD-1). Default behavior (no key) is unchanged.
    """
    src = Path(source_root) if source_root else data_root()
    if not src.exists():
        raise FileNotFoundError(f"data root does not exist: {src}")
    out = Path(out_dir) if out_dir else default_backup_dir(src)
    out.mkdir(parents=True, exist_ok=True)

    do_encrypt = _should_encrypt(encrypt, key)

    # The archive filename is built ONLY from a server-generated timestamp +
    # random suffix — the caller's label never reaches the path (it is recorded in
    # the manifest as data instead), so no user-controlled value enters a path
    # expression. The microsecond stamp + token also keep rapid backups unique.
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    name = f"{_ARCHIVE_PREFIX}{ts}_{secrets.token_hex(3)}.tar.gz"
    archive = out / (name + _ENC_SUFFIX if do_encrypt else name)
    safe_label = "".join(c for c in (label or "") if c.isalnum() or c in "-_ ")[:80]
    manifest = {"created_at": _now_iso(), "source_root": str(src),
                "version": BACKUP_VERSION, "label": safe_label, "encrypted": do_encrypt,
                "dbs": [], "file_count": 0, "dropped": []}

    _sweep_abandoned_temps(out)

    # Materialise the file list BEFORE opening the archive so the growing archive
    # (written into out/) is never itself swept in. Symlinks are skipped, not archived
    # and not followed (H503): a link planted in the data root must not pull an
    # arbitrary file into an archive that may leave the machine.
    files, manifest["skipped_links"] = archive_safe.collect_regular_files(src)
    # The sandbox's run directories are a disposable cache, not the owner's data: model-
    # written scripts and tool-call mailboxes stay out of an archive (review-H667 m3).
    owner_root = _owner_sandbox_root(src)
    files = [f for f in files if not _in_exec_cache(f, src, owner_root)]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if do_encrypt:
            # Stage the tar inside the temp dir (never plaintext in out/), then write
            # the ciphertext all-or-nothing.
            staged = tmp / "archive.tar.gz"
            with open(staged, "wb") as fh:
                _write_tar(fh, src, out, files, tmp, manifest)
            ciphertext = _backup_cipher(key).encrypt_bytes(staged.read_bytes())
            with archive_safe.atomic_write(archive) as fh:
                fh.write(ciphertext)
        else:
            # tarfile.open(archive, "w") would truncate the final name the instant it
            # opened; stream into a sibling temp and os.replace it into place instead.
            with archive_safe.atomic_write(archive) as fh:
                _write_tar(fh, src, out, files, tmp, manifest)

    return {"archive": str(archive), "bytes": archive.stat().st_size, **manifest}


def _still_regular(path: Path) -> bool:
    """True if *path* is (still) a regular file, judged without following a link."""
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def _add_regular(tar: tarfile.TarFile, path: Path, arcname: str) -> bool:
    """Archive *path* as a REGULAR member, stat'ed and read through one O_NOFOLLOW fd.

    Returns False, archiving nothing, when *path* is no longer a regular file (it
    vanished, or was swapped for a link, fifo or directory after the walk). Every name
    becomes its own regular member: ``tar.add`` would turn the second name of a shared
    inode into a hardlink member, which the extractor refuses (and the old regular-only
    filter silently dropped while the manifest still counted it).
    """
    if not _still_regular(path):
        return False
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_BINARY", 0))
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return False
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):  # became a link since the lstat
            return False
        raise
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return False
        tar.inodes.clear()  # no hardlink bookkeeping: each name is archived in full
        info = tar.gettarinfo(arcname=arcname, fileobj=fh)
        tar.addfile(info, fh)
    return True


def _write_tar(fileobj, src: Path, out: Path, files: list[Path], tmp: Path,
               manifest: dict) -> None:
    """Write the gzip'd tar of *files* (+ the manifest) into *fileobj*.

    GNU format rather than the PAX default, as Hermes does, so macOS Archive Utility
    opens the archive; tarfile reads both, so older PAX backups still restore.
    ``file_count`` counts only what was archived; a path that stopped being a regular
    file between the walk and the archive is listed in ``dropped`` instead, so the
    manifest never claims a file the archive does not hold (verify checks the two agree).
    """
    with tarfile.open(fileobj=fileobj, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for path in files:
            if _is_within(path, out):
                continue  # never back up the backups dir
            if path.name.endswith(_SQLITE_SIDECARS):
                continue  # WAL/shm/journal — folded into the DB snapshot
            rel = path.relative_to(src)
            arcname = rel.as_posix()
            if arcname == _MANIFEST_NAME:
                # A restore leaves the archive's manifest in the data root. It is never
                # data, and archiving it beside the manifest appended below gave every
                # later backup two members of that name (restorable only by last-wins).
                continue
            if path.suffix == ".db":
                # sqlite3.connect follows a link, so check before snapshotting through it.
                added = _still_regular(path)
                if added:
                    snap = tmp / "snap" / rel
                    _sqlite_consistent_copy(path, snap)
                    added = _add_regular(tar, snap, arcname)
                if added:
                    manifest["dbs"].append(str(rel))
            else:
                added = _add_regular(tar, path, arcname)
            if added:
                manifest["file_count"] += 1
            else:
                manifest["dropped"].append(arcname)
        mpath = tmp / _MANIFEST_NAME
        mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        _add_regular(tar, mpath, _MANIFEST_NAME)


def _sweep_abandoned_temps(out: Path, *, now: Optional[float] = None) -> list[str]:
    """Remove atomic-write temps a killed backup left behind; never a live one.

    Writing into a sibling temp means a SIGKILL mid-backup leaves debris in ``out``
    (the old staging lived in the system temp dir). It is never listed or restored —
    the name starts with ``.`` — but it would hold disk forever, so it is swept once
    it is clearly abandoned.
    """
    moment = time.time() if now is None else float(now)
    removed: list[str] = []
    for p in out.iterdir():
        if not archive_safe.is_temp_name(p.name, _ARCHIVE_PREFIX):
            continue
        try:
            if (p.is_file() and not p.is_symlink()
                    and moment - p.stat().st_mtime > _ABANDONED_TEMP_SECONDS):
                p.unlink()
                removed.append(p.name)
        except OSError:
            logger.warning("could not sweep an abandoned backup temp file")
    return removed


# ── list ──────────────────────────────────────────────────────────
def _iter_archives(out: Path) -> Iterator[Path]:
    """Yield both plaintext (``.tar.gz``) and encrypted (``.tar.gz.enc``) archives."""
    seen: set[str] = set()
    for pat in (f"{_ARCHIVE_PREFIX}*.tar.gz", f"{_ARCHIVE_PREFIX}*.tar.gz{_ENC_SUFFIX}"):
        for p in out.glob(pat):
            if p.name not in seen:
                seen.add(p.name)
                yield p


def list_backups(out_dir: Optional[str] = None) -> list[dict]:
    """List backup archives (newest first) with size + mtime."""
    out = Path(out_dir) if out_dir else default_backup_dir()
    if not out.exists():
        return []
    rows = []
    for p in _iter_archives(out):
        try:
            st = p.stat()
        except OSError:
            continue
        rows.append({
            "name": p.name,
            "bytes": st.st_size,
            "encrypted": _is_encrypted(p.name),
            "modified_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        })
    rows.sort(key=lambda r: r["modified_at"], reverse=True)
    return rows


def resolve_backup(name: str, out_dir: Optional[str] = None) -> Optional[Path]:
    """Resolve a backup *name* to a path by matching the trusted listing.

    The caller-supplied ``name`` is matched against the actual directory listing
    rather than joined into a path, so no request value reaches a path expression
    (path-injection defeated at the source)."""
    out = Path(out_dir) if out_dir else default_backup_dir()
    if not out.exists():
        return None
    for p in _iter_archives(out):
        if p.name == name:
            return p
    return None


def resolve_backup_arg(arg: str, out_dir: Optional[str] = None) -> Optional[Path]:
    """The archive an operator's ``verify`` / ``restore`` argument names, or None (NWS-18).

    Either the file name ``list`` shows or a path — absolute or relative to the working
    directory, e.g. the ``"archive"`` value ``create`` printed — to an archive directly
    inside the backups directory. Either way the archive's real location (symlinks and
    ``..`` resolved) must be in the backups directory's real location: a path elsewhere,
    or an entry that is a link to a file elsewhere, names no backup, so neither can point
    the drill or a restore at an arbitrary file. The answer is always an entry of the
    directory listing, never the caller's spelling of it.
    """
    out = Path(out_dir) if out_dir else default_backup_dir()
    try:
        real_out = out.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    found = resolve_backup(arg, out_dir)
    if found is None:
        try:
            wanted = Path(arg).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return None
        found = next((p for p in _iter_archives(out) if p.name == wanted.name), None)
        if found is None or wanted.parent != real_out:
            return None
    try:
        real = found.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if real.parent != real_out or real.name != found.name:
        return None
    return found


# ── safe extraction ───────────────────────────────────────────────
# There is deliberately no backup-local extractor any more (H503): verify and restore
# both call archive_safe.extract_tar, the same module the marketplace install uses.


# ── verify (the restore drill) ────────────────────────────────────
def verify_backup(archive: str, key: Optional[str] = None) -> dict:
    """Restore-drill: extract into a temp dir and integrity-check every DB.

    Proves the archive is restorable without touching live data (decrypting first
    if it is an encrypted ``.enc`` archive). Returns
    ``{ok, dbs:{rel: 'ok'|problem}, file_count, manifest}``.
    """
    arc = Path(archive)
    if not arc.exists():
        raise FileNotFoundError(f"backup not found: {arc}")
    report = {"archive": str(arc), "ok": True, "encrypted": _is_encrypted(arc.name),
              "dbs": {}, "file_count": 0, "manifest": None, "problem": None}
    with _readable_archive(arc, key) as tarpath, tempfile.TemporaryDirectory() as tmp:
        tmpp = Path(tmp)
        stale: list[tuple[str, ...]] = []
        written = archive_safe.extract_tar_path(tarpath, tmpp, limits=backup_limits(),
                                                compression="gz", last_wins=(_MANIFEST_NAME,),
                                                superseded=stale)
        report["file_count"] = len(written)
        report["manifest"] = _read_manifest(tmpp, written)
        report["problem"] = _manifest_problem(report["manifest"], written, stale=len(stale))
        if report["problem"]:
            report["ok"] = False
        for db in sorted(tmpp.rglob("*.db")):
            res = _integrity_check(db)
            report["dbs"][str(db.relative_to(tmpp))] = res
            if res != "ok":
                report["ok"] = False
    return report


def _read_manifest(root: Path, written: list[tuple[str, ...]]) -> Optional[dict]:
    """The manifest THIS archive carried (never a stale one already in *root*), or None."""
    if (_MANIFEST_NAME,) not in written:
        return None
    try:
        manifest = json.loads((root / _MANIFEST_NAME).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _manifest_problem(manifest: Optional[dict], written: list[tuple[str, ...]],
                      *, stale: int = 0) -> Optional[str]:
    """Why the unpacked tree disagrees with what create_backup recorded, or None.

    The manifest is the archive's last member and counts every file archived before it,
    so a missing manifest or a lower count is a shortened archive — a tree that would
    restore quietly incomplete while every member that IS there checks out. *stale* is
    how many earlier manifest members the extractor dropped: a backup taken of a
    restored root before the walk skipped the manifest archived the old one as a file
    and counted it, so it counts here too (last one wins, as tarfile always resolved it).
    """
    if manifest is None:
        return (f"the archive carries no readable {_MANIFEST_NAME}: it is incomplete "
                f"or not a Nerva backup")
    expected = manifest.get("file_count")
    if not isinstance(expected, int) or isinstance(expected, bool):
        return None  # nothing recorded to check against
    held = sum(1 for parts in written if parts != (_MANIFEST_NAME,)) + stale
    if held != expected:
        return f"the archive holds {held} file(s) but its manifest counted {expected}"
    return None


# ── restore ───────────────────────────────────────────────────────
def restore_backup(archive: str, target_root: str, force: bool = False,
                   key: Optional[str] = None) -> dict:
    """Extract a backup into ``target_root``. Refuses a non-empty target unless force.

    Deliberately requires an *explicit* target (never silently overwrites the live
    data root). Hot in-place restore is an operator action: pass the live root +
    ``force=True`` with the server stopped. Encrypted archives are decrypted first.
    """
    arc = Path(archive)
    if not arc.exists():
        raise FileNotFoundError(f"backup not found: {arc}")
    target = Path(target_root)
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(
            f"target {target} is not empty — pass force=True to overwrite")
    target.mkdir(parents=True, exist_ok=True)
    stale: list[tuple[str, ...]] = []
    with _readable_archive(arc, key) as tarpath:
        written = archive_safe.extract_tar_path(tarpath, target, limits=backup_limits(),
                                                compression="gz", last_wins=(_MANIFEST_NAME,),
                                                superseded=stale)
    # Post-restore drill on the live target so a corrupt or shortened restore is caught now.
    problem = _manifest_problem(_read_manifest(target, written), written, stale=len(stale))
    dbs = {str(p.relative_to(target)): _integrity_check(p) for p in sorted(target.rglob("*.db"))}
    return {"restored_to": str(target), "file_count": len(written), "dbs": dbs,
            "problem": problem,
            "ok": problem is None and all(v == "ok" for v in dbs.values())}


# ── CLI (one-command) ─────────────────────────────────────────────
# Exit codes: 0 done; 1 the command ran and failed (a failed drill, a rejected archive, a
# wrong key, a non-empty target, …); 2 the argument names no backup. Every failure is one
# line on stdout, never a traceback (NWS-18).

def _no_such_backup(arg: str) -> int:
    print(f"no such backup: {arg} — verify and restore take a file name from `list`, or a "
          f"path to an archive inside {default_backup_dir()} (copy one from elsewhere there "
          f"first)")
    return 2


def _decrypt_failed(name: str, outcome: str, error: SecretStoreError) -> int:
    """One line naming the key's actual source (REV-POLISH-04), not always JARVIS_BACKUP_KEY."""
    if isinstance(error, BackupKeyMissing):
        print(f"cannot decrypt {name}: {error.reason} — no key was made; {outcome}")
        return 1
    source, _missing = _backup_key_source(None)
    print(f"cannot decrypt {name}: {source} is not the key the archive was made with, or the "
          f"archive is damaged; {outcome}")
    return 1


#: The name ``--help`` and usage lines show: the form the pilot guide runs (§2, ``nerva-run``
#: with the service's environment), not a bare ``python -m`` that would miss it.
PROG = "nerva-run -m agents.core.backup"


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog=PROG,
        description="Local backup / restore of the hub's data root. Run it with the service's "
                    "environment (PILOT_GUIDE §2: nerva-run), never from a bare shell — that "
                    "would use another data root and another backup key.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("create", help="snapshot the data root to a .tar.gz")
    pc.add_argument("--encrypt", action="store_true",
                    help="encrypt the archive at rest (uses $JARVIS_BACKUP_KEY, else $JARVIS_SECRET_KEY, else a key file generated in $JARVIS_KEY_DIR)")
    sub.add_parser("list", help="list existing backups")
    pv = sub.add_parser("verify", help="restore-drill a backup (integrity-check its DBs)")
    pv.add_argument("name", help="backup file name (see `list`), or a path to one in the backups dir")
    pr = sub.add_parser("restore", help="restore a backup into a target dir")
    pr.add_argument("name", help="backup file name (see `list`), or a path to one in the backups dir")
    pr.add_argument("target", help="destination directory")
    pr.add_argument("--force", action="store_true", help="overwrite a non-empty target")
    args = ap.parse_args(argv)

    if args.cmd == "create":
        print(json.dumps(create_backup(encrypt=True if args.encrypt else None), indent=2))
    elif args.cmd == "list":
        print(json.dumps(list_backups(), indent=2))
    elif args.cmd == "verify":
        path = resolve_backup_arg(args.name)
        if not path:
            return _no_such_backup(args.name)
        try:
            rep = verify_backup(str(path))
        except archive_safe.ArchiveRejected as e:
            print(f"archive rejected: {e}"); return 1
        except SecretStoreError as e:
            return _decrypt_failed(path.name, "nothing was checked", e)
        except FileNotFoundError:
            print(f"no such backup: {path.name} (it is no longer in {path.parent})"); return 1
        except OSError as e:
            print(f"verify failed: {e}"); return 1
        print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1
    elif args.cmd == "restore":
        path = resolve_backup_arg(args.name)
        if not path:
            return _no_such_backup(args.name)
        try:
            result = restore_backup(str(path), args.target, force=args.force)
        except archive_safe.ArchiveRejected as e:
            if e.partial:
                # A read error after the first write: say so, never "nothing restored".
                print(f"archive rejected partway through, the target holds a partial "
                      f"restore: {e}. Restore a good backup over it before starting Nerva.")
                return 1
            # Refused in the pre-scan, before the first write: nothing was restored.
            print(f"archive rejected, nothing restored: {e}"); return 1
        except SecretStoreError as e:
            return _decrypt_failed(path.name, "nothing was restored", e)
        except FileExistsError:
            print(f"target {args.target} is not empty, nothing restored — restore into a new, "
                  f"empty directory (--force overwrites, but never restore over the data "
                  f"directory in use)")
            return 1
        except FileNotFoundError:
            print(f"no such backup: {path.name} (it is no longer in {path.parent})"); return 1
        except OSError as e:
            print(f"restore failed: {e}"); return 1
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
