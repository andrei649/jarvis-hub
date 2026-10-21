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
  files it overwrites against the free-space clamp. A restored DB's stale ``-wal`` /
  ``-shm`` / ``-journal`` sidecars are removed before anything opens it, so an old WAL
  can never replay over the snapshot.
* **A quick snapshot for rollback (H010).** ``create_backup(quick=True)`` archives only
  the state SQLite DBs (``jarvis-backup-quick-*``; ``*.db`` and SQLite ``*.sqlite`` /
  ``*.sqlite3``, see :func:`is_state_db`) — Hermes' ``backup --quick``: small and fast.
  Of the automatic quick rollback points a restore takes (``jarvis-backup-quick-prerestore-*``)
  the newest ``JARVIS_BACKUP_QUICK_KEEP`` (default 5) are kept; an owner's backup is never pruned.
* **The hub restores itself in place (H010).** ``stage_restore`` drills an archive and
  leaves a marker under ``backups/`` that expires (``JARVIS_RESTORE_STAGE_TTL_HOURS``,
  default 24) and can be cancelled; ``serve.py`` calls ``apply_pending_restore`` at the
  next boot, before ``agents.web`` is imported and the orchestrator built (so no store of
  the hub holds a DB open), and only while no other hub has the root open; the
  jarvis-runtime coordinator sees the stage and gives the root up — its process exits
  (``scripts/coordinator.py`` ``RESTORE_YIELD_EXIT``) and the supervisor's fresh one waits
  without opening a store — and the restore waits for that. The archive must still be
  the one drilled; a rollback snapshot covering what
  the restore overwrites (full before full, quick before quick) is taken first. A running
  hub reaches it only through the approval queue's irreversible tier (``backup.restore``,
  tier 3, ``apply_approved``) and then restarts itself (``agents.core.hub_restart``;
  ``serve.run_server`` says how on each platform). A hub that cannot (raw uvicorn, a
  Windows service without the NSSM marker) answers ``restart: "manual"``, and the stage
  and the listing carry ``action_needed`` (``manual_restart_hint``).
  ``backups/restore-history.jsonl`` keeps the trace, deferrals and cancellations included.
  Process marks (``hub.lock``, ``runtime.pid``) are never archived or restored.

CLI: ``nerva backup create|list|verify|restore`` and, for the module itself,
``nerva-run -m agents.core.backup create|list|verify|restore`` (the one-command story;
:data:`PROG`). Run either with the service's environment — the pilot guide's
``nerva-run`` (PILOT_GUIDE §2) runs the venv's ``python`` as the service's user with the
service's ``EnvironmentFile`` and ``UMask``, so the data root, ``JARVIS_KEY_DIR`` and
``JARVIS_BACKUP_KEY`` are the hub's own — never from a bare shell, whose defaults would
back up (or look for archives of) another data root with another key. Restore refuses
to overwrite a non-empty target unless ``--force``.
"""

from __future__ import annotations

import argparse
import asyncio
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
from agents.core.env_config import env_float, env_int, env_str
from agents.core.estop import SENTINEL_NAME as ESTOP_SENTINEL
from agents.core.paths import data_root
from agents.core.secrets import SecretStore, SecretStoreError, _looks_like_fernet_key

logger = logging.getLogger("jarvis.backup")

BACKUP_VERSION = 1
_ARCHIVE_PREFIX = "jarvis-backup-"
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")
_ENC_SUFFIX = ".enc"  # an encrypted archive is "<name>.tar.gz.enc"
_MANIFEST_NAME = "backup_manifest.json"  # the last member of every archive create_backup writes
_QUICK_TAG = "quick-"  # a quick snapshot is "jarvis-backup-quick-<stamp>.tar.gz"
_PENDING_RESTORE = "pending-restore.json"  # a staged in-place restore, under backups/
_LAST_RESTORE = "last-restore.json"        # what the last staged restore did
_APPLYING = "restore-applying.json"        # journal of a restore being applied right now
_HISTORY = "restore-history.jsonl"         # every staged/applied restore: the audit trace
_RUNTIME_PID = "runtime.pid"               # the headless coordinator's mark, at the data root
_CLAIMED = "pending-restore.claimed"       # the marker, renamed by the one process applying it
_APPLY_LOCK = "restore.lock"               # held while a restore is checked and applied
# Process marks at the data root say which process has it open NOW. They are never data:
# archiving one and restoring it planted a stale pid (a reused one reads as a live hub or
# coordinator) that deferred every later restore (H010 review r2). They are never
# archived, and a restore keeps what the live root held instead of an archive's copy.
_PROCESS_MARKS = frozenset({_RUNTIME_PID, "hub.lock"})
_ROLLBACK_TAG = "prerestore-"  # automatic rollback points: jarvis-backup-[quick-]prerestore-*
# State DBs are SQLite files under these suffixes (settings.db, channel_routes.sqlite,
# checkpoints' history.sqlite3 ...). A ``*.db`` has always been treated as SQLite; the
# other two only when the file says so (the 16-byte header), so a plugin's text file
# that merely carries the name is archived as a plain file, never "snapshotted".
_DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")
_SQLITE_MAGIC = b"SQLite format 3\x00"
QUICK_KEEP_DEFAULT = 5   # automatic quick rollback points kept (JARVIS_BACKUP_QUICK_KEEP)
STAGE_TTL_HOURS_DEFAULT = 24.0   # a staged restore expires (JARVIS_RESTORE_STAGE_TTL_HOURS)
RUNTIME_WAIT_DEFAULT = 60.0      # seconds a restore waits for the coordinator to yield the root
# seconds a stage nobody applies keeps the coordinator stopped (JARVIS_RUNTIME_RESTORE_GRACE_SECONDS)
RUNTIME_RESTORE_GRACE_DEFAULT = 600.0

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


def is_state_db(path: Path) -> bool:
    """Whether *path* is a SQLite state DB: snapshotted through the backup API, kept in a
    quick snapshot, integrity-checked by the drill, and stripped of stale sidecars on
    restore (H010 review: ``*.sqlite`` / ``*.sqlite3`` stores were left out)."""
    path = Path(path)
    if path.suffix not in _DB_SUFFIXES:
        return False
    if path.suffix == ".db":
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(len(_SQLITE_MAGIC))
    except OSError:
        return False
    return head in (_SQLITE_MAGIC, b"")   # an empty file is a valid, empty SQLite DB


def _state_dbs(root: Path) -> list[Path]:
    """Every state DB under *root* (sorted), judged by :func:`is_state_db`."""
    found = []
    for suffix in _DB_SUFFIXES:
        found.extend(p for p in root.rglob(f"*{suffix}") if p.is_file() and is_state_db(p))
    return sorted(set(found))


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


def _is_process_mark(path: Path, root: Path) -> bool:
    """A process mark at the top of the data root (``hub.lock``, ``runtime.pid``)."""
    try:
        parts = Path(path).relative_to(root).parts
    except ValueError:
        return False
    return len(parts) == 1 and parts[0] in _PROCESS_MARKS


def create_backup(source_root: Optional[str] = None, out_dir: Optional[str] = None,
                  label: str = "", encrypt: Optional[bool] = None,
                  key: Optional[str] = None, quick: bool = False,
                  rollback: bool = False) -> dict:
    """Snapshot the data root into a single ``.tar.gz``; return a manifest dict.

    DBs are copied through the SQLite backup API (consistent); everything else is
    archived as-is. The output ``backups/`` dir and SQLite sidecars are excluded.

    ``quick=True`` (H010, Hermes' ``backup --quick``) archives only the state DBs —
    audio, media and the rest of the root are left out — as a small, fast rollback
    point; restoring it overwrites those DBs and nothing else.

    When a backup key is configured (``key`` arg / ``$JARVIS_BACKUP_KEY``) or
    ``encrypt=True``, the archive is encrypted at rest (``.tar.gz.enc``) so it
    carries no plaintext secrets (AUD-1). Default behavior (no key) is unchanged.

    ``rollback=True`` names the archive as an automatic rollback point
    (``jarvis-backup-[quick-]prerestore-*``): only those are ever pruned by a restore,
    never a backup the owner made. Process marks (``hub.lock``, ``runtime.pid``) are
    never archived.
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
    name = (f"{_ARCHIVE_PREFIX}{_QUICK_TAG if quick else ''}{_ROLLBACK_TAG if rollback else ''}"
            f"{ts}_{secrets.token_hex(3)}.tar.gz")
    archive = out / (name + _ENC_SUFFIX if do_encrypt else name)
    safe_label = "".join(c for c in (label or "") if c.isalnum() or c in "-_ ")[:80]
    manifest = {"created_at": _now_iso(), "source_root": str(src),
                "version": BACKUP_VERSION, "label": safe_label, "encrypted": do_encrypt,
                "mode": "quick" if quick else "full",
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
    files = [f for f in files
             if not _in_exec_cache(f, src, owner_root) and not _is_process_mark(f, src)]
    # H694: the ESTOP sentinel is the live kill switch shared by every profile of the
    # install, not owner data. Archiving it would let a later restore reinstate a stale
    # pause for every hub; leaving it out means a restore never touches the live switch
    # (extraction only adds files, so an engaged pause also survives a restore).
    files = [f for f in files if f != src / ESTOP_SENTINEL]
    if quick:
        files = [f for f in files if is_state_db(f)]
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
            if is_state_db(path):
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


def _is_rollback_point(name: str) -> bool:
    """An automatic rollback point a restore took (never a backup the owner made)."""
    return (name.startswith(_ARCHIVE_PREFIX + _ROLLBACK_TAG)
            or name.startswith(_ARCHIVE_PREFIX + _QUICK_TAG + _ROLLBACK_TAG))


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
            "quick": p.name.startswith(_ARCHIVE_PREFIX + _QUICK_TAG),
            "rollback": _is_rollback_point(p.name),
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
        for db in _state_dbs(tmpp):
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
    data root). Into the live root it runs only with the hub stopped: the staged path
    below (``apply_pending_restore``) is how the hub does that to itself. Encrypted
    archives are decrypted first.
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
    # An archive made before process marks were left out may carry one: the live root's
    # own mark (or its absence) is put back after the extract, never the archive's pid.
    live_marks: dict[str, Optional[bytes]] = {}
    for mark in _PROCESS_MARKS:
        try:
            live_marks[mark] = (target / mark).read_bytes()
        except OSError:
            live_marks[mark] = None
    with _readable_archive(arc, key) as tarpath:
        written = archive_safe.extract_tar_path(tarpath, target, limits=backup_limits(),
                                                compression="gz", last_wins=(_MANIFEST_NAME,),
                                                superseded=stale)
    for mark, before in live_marks.items():
        if (mark,) not in written:
            continue
        if before is None:
            (target / mark).unlink(missing_ok=True)
        else:
            (target / mark).write_bytes(before)
    # A restored DB is a consistent snapshot; a -wal/-shm/-journal left beside it by the
    # state it replaced would be replayed over it on the next open (the drill below
    # included). They are dropped before anything opens the DB.
    for parts in written:
        db = target.joinpath(*parts) if parts else None
        if db is not None and is_state_db(db):
            for sidecar in _SQLITE_SIDECARS:
                db.with_name(db.name + sidecar).unlink(missing_ok=True)
    # Post-restore drill on the live target so a corrupt or shortened restore is caught now.
    problem = _manifest_problem(_read_manifest(target, written), written, stale=len(stale))
    dbs = {str(p.relative_to(target)): _integrity_check(p) for p in _state_dbs(target)}
    return {"restored_to": str(target), "file_count": len(written), "dbs": dbs,
            "problem": problem,
            "ok": problem is None and all(v == "ok" for v in dbs.values())}


# ── staged in-place restore (H010) ────────────────────────────────
# The live root cannot be overwritten under a running hub: its stores hold the DBs open
# and would write their own state back over the restore. So an in-place restore is
# staged — drilled, then a marker beside the archives — and applied by the next boot
# before any store opens (serve.py), or at once by the offline `nerva backup restore`,
# only when no other process has the root open: neither a hub (hub.lock) nor the
# headless coordinator of jarvis-runtime (runtime.pid). The coordinator watches for a
# stage (runtime_should_yield), stops its orchestrator and EXITS — a process that built an
# orchestrator never drops its mark while alive, so the restore, which waits for the mark
# to be gone (dead pid), never runs under a live SQLite handle of it (H010 review r3). The
# supervisor respawns it at once; the fresh process waits without opening a store and
# builds its orchestrator on the restored files once the stage and the journal are gone.
# A stage nobody applies keeps the runtime stopped for JARVIS_RUNTIME_RESTORE_GRACE_SECONDS
# at most; the coordinator then resumes (restore-history "runtime_resumed") and yields
# again when an apply journals. The marker is
# claimed (renamed) before the restore runs, so a restore that fails is reported once
# (last-restore.json) and never retried every boot; a journal (restore-applying.json) is
# kept while it runs, so one killed partway is reported at the next boot as interrupted,
# with its rollback point. A stage expires (expires_at) and can be cancelled. Every
# staged, deferred, cancelled and applied restore is appended to restore-history.jsonl
# under backups/, which no archive holds, so the restore cannot erase that trace.

def _root_of(source_root) -> Path:
    return Path(source_root) if source_root else data_root()


def _read_json(path: Path) -> Optional[dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with archive_safe.atomic_write(path) as fh:
        fh.write(json.dumps(value, indent=2, default=str).encode("utf-8"))


def pending_restore(source_root=None) -> Optional[dict]:
    """The staged in-place restore waiting for the next boot, or None."""
    return _read_json(default_backup_dir(_root_of(source_root)) / _PENDING_RESTORE)


def last_restore(source_root=None) -> Optional[dict]:
    """What the last staged restore did (restored / failed / interrupted), or None."""
    return _read_json(default_backup_dir(_root_of(source_root)) / _LAST_RESTORE)


def _append_history(out: Path, event: str, record: dict) -> None:
    """One line in restore-history.jsonl. Advisory: a failed append never fails a restore."""
    row = {"event": event, "at": _now_iso(),
           **{k: record.get(k) for k in ("name", "requested_by", "task_id", "staged_at",
                                         "expires_at", "rollback", "pruned", "status",
                                         "reason", "ok", "pid", "cancelled_by")
              if k in record}}
    try:
        out.mkdir(parents=True, exist_ok=True)
        with open(out / _HISTORY, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except OSError:
        logger.warning("could not append to the restore history")


def restore_history(source_root=None, limit: int = 50) -> list[dict]:
    """The newest *limit* entries of restore-history.jsonl, oldest first."""
    return _history_rows(default_backup_dir(_root_of(source_root)) / _HISTORY, limit)


def _history_rows(path: Path, limit: int) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-max(1, int(limit)):]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


# ── who else has the data root open ──
def _pid_in(path: Path) -> Optional[int]:
    try:
        text = path.read_text(encoding="ascii").strip()[:16]
    except (OSError, ValueError):
        return None
    return int(text) if text.isdigit() and int(text) > 0 else None


def mark_runtime(source_root=None) -> None:
    """The headless coordinator (scripts/coordinator.py) says it has the root open."""
    path = _root_of(source_root) / _RUNTIME_PID
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="ascii")


def clear_runtime_mark(source_root=None) -> None:
    """Remove this process's runtime mark (never another live coordinator's)."""
    path = _root_of(source_root) / _RUNTIME_PID
    if _pid_in(path) == os.getpid():
        path.unlink(missing_ok=True)


def runtime_running_elsewhere(source_root=None) -> bool:
    """Whether another live process (the jarvis-runtime coordinator) marked the root.

    A stale mark of a dead process, or this process's own, is not "elsewhere"."""
    from agents.core import install_identity

    pid = _pid_in(_root_of(source_root) / _RUNTIME_PID)
    if pid is None or pid == os.getpid():
        return False
    return install_identity._pid_alive(pid) and not _zombie(pid)


def _zombie(pid: int) -> bool:
    """A coordinator that exited for a restore leaves its mark (H010 review r3): once it
    is dead it holds nothing, even before its parent has reaped it (Linux state ``Z``)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return False
    fields = stat.rsplit(")", 1)[-1].split()
    return bool(fields) and fields[0] in ("Z", "X")


#: A SQLite file a restore replaces: a DB or its -wal/-shm/-journal (a replaced inode
#: reads as "<path> (deleted)" in /proc/self/fd).
_DB_FILE = re.compile(r"\.(db|sqlite|sqlite3)(-wal|-shm|-journal)?( \(deleted\))?$")


def open_root_db_files(source_root=None) -> Optional[list[str]]:
    """The SQLite files (DBs and their -wal/-shm/-journal) under the data root that THIS
    process has open (Linux: ``/proc/self/fd``); None where that cannot be read.

    Both processes that open the root's stores check it before the root changes under
    them: the coordinator before it drops its mark (scripts/coordinator.py), and the
    apply itself (``_apply_locked``) — the hub applies a staged restore in an image it
    re-exec'd into, and a handle carried across that exec would keep writing to the
    replaced inode (H010 review r4). Other files (a log pointed under the root) are not
    what a restore corrupts."""
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.is_dir():
        return None
    prefix = os.path.realpath(_root_of(source_root)) + os.sep
    held = []
    for entry in os.listdir(fd_dir):
        try:
            target = os.readlink(fd_dir / entry)
        except OSError:
            continue                                  # closed meanwhile (the listdir fd)
        if target.startswith(prefix) and _DB_FILE.search(target):
            held.append(target)
    return held


def _journal_live(journal: dict) -> bool:
    """A journal written by a live process other than this one is a restore running now."""
    from agents.core import install_identity

    pid = journal.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or pid == os.getpid():
        return False
    return install_identity._pid_alive(pid)


def restore_in_progress(source_root=None) -> bool:
    """Whether another process is applying a restore to this root right now."""
    journal = _read_json(default_backup_dir(_root_of(source_root)) / _APPLYING)
    return journal is not None and _journal_live(journal)


def wait_while_restoring(source_root=None, *, poll: float = 1.0,
                         timeout: Optional[float] = None, sleep=time.sleep) -> bool:
    """Block while another process applies a restore (the coordinator, before it opens
    the stores). True once none is running; False if *timeout* ran out first."""
    waited = 0.0
    while restore_in_progress(source_root):
        if timeout is not None and waited >= timeout:
            return False
        sleep(poll)
        waited += poll
    return True


def boot_restore_due(source_root=None) -> bool:
    """Cheap boot probe: a restore is staged, or a journal says one was being applied."""
    out = default_backup_dir(_root_of(source_root))
    return (out / _PENDING_RESTORE).exists() or (out / _APPLYING).exists()


def stage_ttl_seconds() -> float:
    """How long a staged restore stays applicable (``JARVIS_RESTORE_STAGE_TTL_HOURS``)."""
    return env_float("JARVIS_RESTORE_STAGE_TTL_HOURS", STAGE_TTL_HOURS_DEFAULT,
                     minimum=0.001) * 3600.0


def _parse_iso(value) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def stage_expired(staged: dict, *, now: Optional[float] = None) -> bool:
    """Whether a staged restore is past its ``expires_at``. A marker without one (staged
    before the expiry existed) expires ``JARVIS_RESTORE_STAGE_TTL_HOURS`` after
    ``staged_at``; a marker with neither readable has expired (it cannot be dated)."""
    moment = time.time() if now is None else float(now)
    expires = _parse_iso(staged.get("expires_at"))
    if expires is None:
        staged_at = _parse_iso(staged.get("staged_at"))
        if staged_at is None:
            return True
        expires = staged_at + stage_ttl_seconds()
    return moment >= expires


def restore_wanted(source_root=None) -> bool:
    """A restore is staged (and not expired), or another live process is applying one.
    The coordinator watches ``runtime_should_yield`` (this, bounded by a grace period for a
    stage nobody applies) and uses this to tell that it resumed with a stage pending."""
    root = _root_of(source_root)
    staged = pending_restore(root)
    if staged is not None and not stage_expired(staged):
        return True
    return restore_in_progress(root)


def runtime_restore_grace_seconds() -> float:
    """How long a staged restore nobody applies keeps the coordinator stopped
    (``JARVIS_RUNTIME_RESTORE_GRACE_SECONDS``, default 600; 0 = only while one is applied)."""
    return env_float("JARVIS_RUNTIME_RESTORE_GRACE_SECONDS", RUNTIME_RESTORE_GRACE_DEFAULT,
                     minimum=0.0)


def _stage_past_grace(staged: dict, now: float) -> bool:
    staged_at = _parse_iso(staged.get("staged_at"))
    return staged_at is not None and now - staged_at >= runtime_restore_grace_seconds()


def runtime_should_yield(source_root=None, *, now: Optional[float] = None) -> bool:
    """What the jarvis-runtime coordinator watches (H010 review r3): another live process
    is applying a restore (its journal), or a restore was staged less than
    ``runtime_restore_grace_seconds`` ago. An approved restore asks for the hub's restart at
    once, so the coordinator is usually already gone when the apply begins; a stage left
    unapplied (the hub kept down, or started without serve.py) stops the runtime only for
    the grace period — the coordinator then runs again and yields when an apply journals,
    which the apply waits for (``wait_for_runtime_yield``)."""
    root = _root_of(source_root)
    if restore_in_progress(root):
        return True
    staged = pending_restore(root)
    moment = time.time() if now is None else float(now)
    if staged is None or stage_expired(staged, now=moment):
        return False
    return not _stage_past_grace(staged, moment)


def note_runtime_resumed(source_root=None) -> bool:
    """Record (once per stage) that the coordinator resumed with a restore still staged:
    restore-history.jsonl gets a ``runtime_resumed`` line, which ``staged_restore_view``
    reports as ``runtime_resumed_at``. True when a line was written."""
    root = _root_of(source_root)
    out = default_backup_dir(root)
    staged = pending_restore(root)
    if staged is None:
        return False
    if _runtime_resumed_at(out, staged) is not None:
        return False
    _append_history(out, "runtime_resumed", {**staged, "pid": os.getpid()})
    return True


def _runtime_resumed_at(out: Path, staged: dict) -> Optional[str]:
    for row in reversed(_history_rows(out / _HISTORY, 200)):
        if row.get("staged_at") != staged.get("staged_at"):
            continue
        if row.get("event") == "runtime_resumed":
            return row.get("at")
        if row.get("event") == "staged":
            return None
    return None


def runtime_wait_seconds() -> float:
    """How long a restore waits for the coordinator to yield (``JARVIS_RESTORE_RUNTIME_WAIT_SECONDS``)."""
    return env_float("JARVIS_RESTORE_RUNTIME_WAIT_SECONDS", RUNTIME_WAIT_DEFAULT, minimum=0.0)


def wait_for_runtime_yield(source_root=None, *, timeout: float, poll: float = 0.25,
                           sleep=time.sleep) -> bool:
    """Block until no other live process holds the runtime mark; False if *timeout* ran out.
    A coordinator that ran an orchestrator releases it by exiting (its pid is then dead or a
    zombie); a fresh one that opened nothing drops it (``runtime_should_yield``)."""
    waited = 0.0
    while runtime_running_elsewhere(source_root):
        if waited >= timeout:
            return False
        sleep(poll)
        waited += poll
    return True


def staged_restore_view(source_root=None) -> Optional[dict]:
    """The staged restore as the owner should read it: the marker plus ``state`` —
    ``waiting`` (applied at the next hub start), ``deferred`` (the last attempt was put
    off: ``deferred_reason`` says why) or ``expired`` (it will be discarded, never applied)."""
    root = _root_of(source_root)
    staged = pending_restore(root)
    if staged is None:
        return None
    view = dict(staged)
    last = last_restore(root) or {}
    if stage_expired(staged):
        view["state"] = "expired"
    elif last.get("status") == "deferred" and last.get("staged_at") == staged.get("staged_at"):
        view["state"] = "deferred"
        view["deferred_reason"] = last.get("reason")
        view["deferred_at"] = last.get("applied_at")
    else:
        view["state"] = "waiting"
    if view.get("restart") == "manual" and view["state"] != "expired":
        # The hub that took the accept could not restart itself (H010 review r5).
        view["action_needed"] = manual_restart_hint(staged.get("expires_at"))
    resumed = _runtime_resumed_at(default_backup_dir(root), staged)
    if resumed is not None:
        # Unapplied past the grace: jarvis-runtime runs again, and yields at the apply.
        view["runtime_resumed_at"] = resumed
    return view


def manual_restart_hint(expires_at) -> str:
    """What the owner must do when the hub cannot restart itself (``restart: "manual"``)."""
    return (f"restart the hub/service (python serve.py, the Windows service, or nerva.exe) "
            f"to apply it before {expires_at}; until then jarvis-runtime stays paused for "
            f"its restore grace and the stage is discarded at that time")


def _note_manual_restart(source_root, staged: dict) -> None:
    """Record on the stage that nothing restarts the hub for it, so the listing says so."""
    marker = default_backup_dir(_root_of(source_root)) / _PENDING_RESTORE
    current = _read_json(marker)
    if current is None or current.get("staged_at") != staged.get("staged_at"):
        return                                   # applied, cancelled or restaged meanwhile
    try:
        _write_json(marker, {**current, "restart": "manual"})
    except OSError:
        logger.warning("could not record that the staged restore needs a manual restart")


def unapplied_restore_warning(source_root=None) -> Optional[str]:
    """What to log when the hub starts with a restore still staged (a raw-uvicorn start
    never applies one: only serve.py does, at boot, before the stores open)."""
    staged = pending_restore(source_root)
    if staged is None:
        return None
    return (f"a restore of {staged.get('name')} is staged but not applied: only serve.py "
            f"applies it at boot, and only when no other hub or jarvis-runtime coordinator "
            f"has the data root open. Restart the hub with `python serve.py`.")


def prune_quick_backups(keep: Optional[int] = None, out_dir: Optional[str] = None,
                        protect: tuple[str, ...] = ()) -> list[str]:
    """Keep only the newest *keep* automatic quick rollback points (never one named in
    *protect*); return what was removed. ``JARVIS_BACKUP_QUICK_KEEP`` sets the default (at
    least 1). Only archives a restore took (``jarvis-backup-quick-prerestore-*``) are ever
    candidates: a quick backup the owner made (``nerva backup create --quick``) is theirs
    to keep or delete (H010 review r2)."""
    if keep is None:
        keep = env_int("JARVIS_BACKUP_QUICK_KEEP", QUICK_KEEP_DEFAULT, minimum=1)
    keep = max(0, int(keep))
    out = Path(out_dir) if out_dir else default_backup_dir()
    if not out.is_dir():
        return []
    tag = _ARCHIVE_PREFIX + _QUICK_TAG + _ROLLBACK_TAG
    quick = sorted((p for p in _iter_archives(out) if p.name.startswith(tag)),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    removed: list[str] = []
    for stale in quick[keep:]:
        if stale.name in protect:
            continue
        try:
            stale.unlink()
            removed.append(stale.name)
        except OSError:
            logger.warning("could not prune stale quick snapshot %s", stale.name)
    return removed


def stage_restore(name: str, source_root=None, key: Optional[str] = None,
                  requested_by: str = "", task_id: Optional[int] = None,
                  restart: Optional[str] = None) -> dict:
    """Drill backup *name* and, when it verifies, stage it for an in-place restore.

    ``restart`` (``"self"`` / ``"manual"``, an approved task's apply only) is written on
    the stage from its first byte, so no reader sees a stage whose restart is unknown.

    Touches no live data. Raises FileNotFoundError for a name not in the listing;
    a failed drill is ``{ok: False, problem}`` and stages nothing. The stage carries an
    ``expires_at`` (``JARVIS_RESTORE_STAGE_TTL_HOURS``, default 24): past it the restore
    is discarded, never applied, so one accept cannot roll back data written days later.
    """
    root = _root_of(source_root)
    out = default_backup_dir(root)
    path = resolve_backup(name, out_dir=str(out))
    if path is None:
        raise FileNotFoundError(f"no such backup: {name}")
    try:
        report = verify_backup(str(path), key=key)
    except (archive_safe.ArchiveRejected, ValueError, OSError) as exc:
        return {"ok": False, "name": path.name, "problem": f"archive rejected: {exc}"}
    if not report["ok"]:
        bad = {k: v for k, v in report["dbs"].items() if v != "ok"}
        return {"ok": False, "name": path.name,
                "problem": report["problem"] or f"integrity check failed: {bad}"}
    st = path.stat()
    mode = (report.get("manifest") or {}).get("mode")
    now = datetime.now(timezone.utc)
    staged = {"name": path.name, "bytes": st.st_size, "mtime": st.st_mtime,
              "mode": mode if mode in ("quick", "full") else "full",
              "staged_at": now.isoformat(),
              "expires_at": datetime.fromtimestamp(now.timestamp() + stage_ttl_seconds(),
                                                   timezone.utc).isoformat(),
              "requested_by": requested_by, "task_id": task_id,
              "file_count": report["file_count"]}
    if restart in ("self", "manual"):
        staged["restart"] = restart
    _write_json(out / _PENDING_RESTORE, staged)
    _append_history(out, "staged", staged)
    return {"ok": True, **staged}


def _finish(out: Path, result: dict) -> dict:
    try:
        _write_json(out / _LAST_RESTORE, result)
    except OSError:
        logger.warning("could not record the outcome of the staged restore")
    _append_history(out, str(result.get("status")), result)
    return result


def _defer(out: Path, staged: dict, reason: str) -> dict:
    """Record that a staged restore was put off, and why (H010 review r2: a deferral left
    no trace). last-restore.json says ``deferred`` with the reason; restore-history.jsonl
    gets one ``deferred`` line per process and reason, not one per poll."""
    result = {**{k: staged.get(k) for k in ("name", "staged_at", "expires_at",
                                            "requested_by", "task_id")},
              "status": "deferred", "reason": reason, "applied_at": _now_iso(),
              "pid": os.getpid()}
    try:
        _write_json(out / _LAST_RESTORE, result)
    except OSError:
        logger.warning("could not record the deferral of the staged restore")
    last = (_history_rows(out / _HISTORY, 1) or [{}])[-1]
    if not (last.get("event") == "deferred" and last.get("pid") == os.getpid()
            and last.get("staged_at") == result["staged_at"] and last.get("reason") == reason):
        _append_history(out, "deferred", result)
    return result


def cancel_staged_restore(source_root=None, cancelled_by: str = "") -> dict:
    """Withdraw a staged restore before it is applied (``nerva backup cancel``,
    ``DELETE /api/admin/backup/restore``). ``{ok: True, cancelled: name}``, or ``{ok:
    False, reason: nothing_staged|applying}`` — a restore already claimed by the process
    applying it cannot be withdrawn. Logged as ``cancelled`` in the history."""
    root = _root_of(source_root)
    out = default_backup_dir(root)
    marker = out / _PENDING_RESTORE
    staged = _read_json(marker)
    if staged is None:
        applying = (out / _CLAIMED).exists() or restore_in_progress(root)
        return {"ok": False, "reason": "applying" if applying else "nothing_staged"}
    try:
        marker.unlink()
    except FileNotFoundError:   # claimed by the applying process between the read and here
        return {"ok": False, "reason": "applying", "name": staged.get("name")}
    result = {**{k: staged.get(k) for k in ("name", "staged_at", "expires_at",
                                            "requested_by", "task_id")},
              "status": "cancelled", "ok": False, "reason": "cancelled",
              "cancelled_by": cancelled_by, "applied_at": _now_iso()}
    _finish(out, result)
    return {"ok": True, "cancelled": staged.get("name"), "staged_at": staged.get("staged_at")}


@contextmanager
def _apply_lock(out: Path) -> Iterator[bool]:
    """An exclusive, non-blocking file lock around one apply: two hubs booting at the same
    moment both reached apply before either took hub.lock (H010 review r2). Yields False
    when another process holds it."""
    from agents.core import install_identity

    out.mkdir(parents=True, exist_ok=True)
    # Text mode, like every other _file_lock caller: on Windows the helper pads a short lock
    # file with a str (Codex review on #1249), which a binary handle would refuse.
    handle = open(out / _APPLY_LOCK, "a+", encoding="ascii")  # noqa: SIM115 - held across the yield
    try:
        try:
            install_identity._file_lock(handle, blocking=False)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            try:
                install_identity._file_unlock(handle)
            except OSError:
                logger.debug("restore lock already released")
    finally:
        handle.close()
def apply_pending_restore(source_root=None, key: Optional[str] = None, *,
                          runtime_wait: Optional[float] = None,
                          sleep=time.sleep) -> Optional[dict]:
    """Apply a staged restore to the live root — only while no other process has it open.

    None when nothing is staged. Otherwise ``{status: restored|failed|deferred|interrupted|
    cancelled, …}``. A stage past its ``expires_at`` is discarded (``failed``,
    ``stage_expired``) without touching the root. The jarvis-runtime coordinator gives the
    root up once it sees the stage or this apply's journal (``runtime_should_yield``) — its
    process exits — and this waits up to *runtime_wait* seconds
    (``JARVIS_RESTORE_RUNTIME_WAIT_SECONDS``, default 60) for its mark to be released,
    and defers only if it does not. Every deferral is recorded (``_defer``). The archive
    must still be the one that was drilled (bytes and mtime); a rollback snapshot of what
    the restore overwrites is taken first (``rollback``: a full snapshot before a full
    restore, a quick one before a quick restore), then the archive is restored over the
    root with ``force``. ``interrupted`` reports a previous attempt that was killed partway
    (the root may be half-restored; restore its ``rollback``).
    """
    root = _root_of(source_root)
    out = default_backup_dir(root)
    if not boot_restore_due(root) and not (out / _CLAIMED).exists():
        return None
    with _apply_lock(out) as locked:
        if not locked:
            staged = _read_json(out / _PENDING_RESTORE)
            if staged is None:
                return None
            return _defer(out, staged, "another process is applying a restore to this data root")
        return _apply_locked(root, out, key,
                             runtime_wait_seconds() if runtime_wait is None else runtime_wait,
                             sleep)


def _base(staged: dict) -> dict:
    return {k: staged.get(k) for k in ("name", "staged_at", "expires_at", "requested_by", "task_id")}


def _apply_locked(root: Path, out: Path, key: Optional[str], runtime_wait: float,
                  sleep) -> Optional[dict]:
    from agents.core import install_identity

    marker, journal_path, claimed = out / _PENDING_RESTORE, out / _APPLYING, out / _CLAIMED
    journal = _read_json(journal_path)
    if journal is not None:
        if _journal_live(journal):
            staged = _read_json(marker) or journal
            return _defer(out, staged, "another process is applying a restore to this data root")
        journal_path.unlink(missing_ok=True)
        if journal.get("phase") == "snapshotting":
            # Killed after the marker was claimed but before the restore began: the live
            # root was not touched, and the request must not vanish without a word.
            claimed.unlink(missing_ok=True)
            return _finish(out, {
                **_base(journal), "status": "failed", "ok": False,
                "reason": "interrupted_before_restore", "applied_at": _now_iso(),
                "detail": "the process was killed while taking the rollback snapshot; nothing "
                          "was restored — stage the restore again"})
        if journal.get("phase") == "restoring":
            claimed.unlink(missing_ok=True)
            return _finish(out, {
                **_base(journal), "status": "interrupted", "ok": False,
                "reason": "interrupted", "rollback": journal.get("rollback"),
                "applied_at": _now_iso(),
                "detail": "the restore was killed partway: the data root may be half-restored; "
                          "restore the rollback point (or the archive again) before relying on it"})
        # Killed while checking: nothing began. A claim it made goes back to being staged.
        if claimed.exists() and not marker.exists():
            os.replace(claimed, marker)
    staged = _read_json(marker)
    if staged is None:
        return None
    if stage_expired(staged):
        marker.unlink(missing_ok=True)
        return _expired(out, staged)
    # Journal first, then look for other openers: a coordinator that marks the root at the
    # same moment then sees this journal (runtime_should_yield) and gives the root up again.
    _write_json(journal_path, {**_base(staged), "phase": "checking", "pid": os.getpid()})
    reason = None
    held = open_root_db_files(root)
    if held:
        # The applying process itself still has a DB open (a handle that survived the hub's
        # re-exec): restoring now would leave it writing to the replaced inode.
        reason = (f"this process still holds {len(held)} SQLite file(s) under the data root "
                  f"({', '.join(sorted({Path(t.removesuffix(' (deleted)')).name for t in held}))}); "
                  f"the restore stays staged until a start that holds none")
    elif install_identity.hub_lock_held_elsewhere(root):
        reason = "another hub holds this data root; the restore stays staged"
    elif not wait_for_runtime_yield(root, timeout=runtime_wait, sleep=sleep):
        reason = (f"the jarvis-runtime coordinator did not release the data root within "
                  f"{runtime_wait:g}s (a current coordinator releases it once it sees the staged "
                  f"restore); the restore stays staged until it expires at {staged.get('expires_at')}")
    if reason:
        journal_path.unlink(missing_ok=True)
        return _defer(out, staged, reason)
    try:
        os.replace(marker, claimed)                 # one attempt: never a boot loop
    except FileNotFoundError:                      # withdrawn while this waited
        journal_path.unlink(missing_ok=True)
        return {**_base(staged), "status": "cancelled", "ok": False, "reason": "cancelled"}
    staged = _read_json(claimed) or staged         # the stage as it stands now
    base = _base(staged)
    _write_json(journal_path, {**base, "phase": "snapshotting", "pid": os.getpid()})
    claimed.unlink(missing_ok=True)
    if stage_expired(staged):
        journal_path.unlink(missing_ok=True)
        return _expired(out, staged)
    name = str(staged.get("name") or "")
    result: dict = {**base, "name": name, "applied_at": _now_iso()}
    path = resolve_backup(name, out_dir=str(out)) if name else None
    st = path.stat() if path is not None else None
    if path is None or st is None:
        result.update(status="failed", reason="backup_missing", ok=False)
    elif st.st_size != staged.get("bytes") or st.st_mtime != staged.get("mtime"):
        result.update(status="failed", reason="backup_changed", ok=False,
                      detail="the archive changed after it was drilled and staged")
    else:
        try:
            rollback = create_backup(source_root=str(root), out_dir=str(out),
                                     quick=staged.get("mode") == "quick",
                                     label="pre-restore", key=key, rollback=True)
            result["rollback"] = Path(rollback["archive"]).name
            try:
                result["pruned"] = prune_quick_backups(out_dir=str(out),
                                                       protect=(name, result["rollback"]))
            except OSError:
                logger.warning("could not prune old quick rollback points")
            _write_json(journal_path, {**base, "phase": "restoring", "pid": os.getpid(),
                                       "rollback": result["rollback"]})
            restored = restore_backup(str(path), str(root), force=True, key=key)
        except archive_safe.ArchiveRejected as exc:
            result.update(status="failed", reason="archive_rejected", ok=False,
                          partial=bool(exc.partial), detail=str(exc))
        except (OSError, ValueError) as exc:
            result.update(status="failed", reason="restore_error", ok=False, detail=str(exc))
        else:
            result.update(status="restored", ok=restored["ok"], problem=restored["problem"],
                          file_count=restored["file_count"], dbs=restored["dbs"])
    journal_path.unlink(missing_ok=True)
    return _finish(out, result)


def _expired(out: Path, staged: dict) -> dict:
    return _finish(out, {
        **_base(staged), "status": "failed", "ok": False, "reason": "stage_expired",
        "applied_at": _now_iso(),
        "detail": "the staged restore expired before it could be applied; nothing was "
                  "restored — stage it again if it is still wanted"})


#: The irreversible-tier kind (agents/core/autonomy/irreversible.py BUILTIN_KINDS).
APPROVAL_KIND = "backup.restore"


def restore_request(name: str) -> dict:
    """The card for restoring *name* over the live root: the archive's identity (an
    accept is refused if it changed since) and the drill's verdict as the preview."""
    path = resolve_backup(name)
    if path is None:
        raise FileNotFoundError(f"no such backup: {name}")
    report = verify_backup(str(path))
    st = path.stat()
    manifest = report.get("manifest") or {}
    mode = manifest.get("mode", "full")
    return {
        "title": f"Restore backup {path.name} over the live data root (the hub restarts)",
        "payload": {"name": path.name, "bytes": st.st_size, "mtime": st.st_mtime},
        "preview": {
            "verify": {"ok": report["ok"], "problem": report["problem"],
                       "file_count": report["file_count"], "dbs": report["dbs"]},
            "created_at": manifest.get("created_at"), "mode": mode,
            "effect": "overwrites the live state with the archive's (files the archive does "
                      "not hold are kept); a "
                      + ("quick" if mode == "quick" else "full")
                      + " rollback snapshot of the current state is taken first",
        },
    }


def restore_held_here(task=None) -> Optional[str]:
    """Why this process must leave an accepted ``backup.restore`` for another one, or None.

    H010 review r6: the hub and jarvis-runtime (``scripts/coordinator.py``) both run the
    autonomy loop over one queue and both register this kind. Only a process that can
    restart the hub may stage it — or one with no hub to restart. A process with no
    stopper (``hub_restart.available()`` False) while a live hub holds ``hub.lock``
    leaves the task APPROVED for the hub's worker (``irreversible.held_here``): staging
    it here would answer "manual" after the hub's 202 said "self", and nothing would
    restart the hub."""
    from agents.core import hub_restart, install_identity

    if hub_restart.available():
        return None
    try:
        elsewhere = install_identity.hub_lock_held_elsewhere()
    except Exception:  # noqa: BLE001 — an unreadable probe is "no hub": the old behaviour
        logger.warning("could not tell whether a hub holds the data root", exc_info=True)
        return None
    return "hub_applies_restore" if elsewhere else None


async def _refuse(task, reason: str, **extra) -> dict:
    """The refusal of an accepted restore, recorded (H010 review r7): it stages nothing and
    writes no outcome, so without a ``refused`` line in restore-history.jsonl the owner
    who accepted it would wait for a stage that never comes (``last_refused_restore``)."""
    payload = getattr(task, "payload", None)
    name = payload.get("name") if isinstance(payload, dict) else None
    task_id = getattr(task, "id", None)
    record = {"name": name if isinstance(name, str) else None, "reason": reason,
              "status": "refused", "task_id": task_id if isinstance(task_id, int) else None,
              "requested_by": str(getattr(task, "decided_by", "") or "")}
    await asyncio.to_thread(_append_history, default_backup_dir(_root_of(None)), "refused",
                            record)
    return {"status": "refused", "reason": reason, **extra}


def last_refused_restore(source_root=None) -> Optional[dict]:
    """The newest accepted restore the apply refused, unless a restore was staged since
    (``GET /api/admin/backup`` → ``refused_restore``; the CLI matches it by ``task_id``)."""
    rows = _history_rows(default_backup_dir(_root_of(source_root)) / _HISTORY, 200)
    for row in reversed(rows):
        if row.get("event") == "refused":
            return row
        if row.get("event") == "staged":
            return None
    return None


async def apply_approved(task, orch) -> dict:
    """Stage a ``backup.restore`` task a human accepted (``irreversible.execute`` checked
    who decided) and ask the hub to restart, which applies it before any store opens."""
    from agents.core import hub_restart

    held = restore_held_here(task)
    if held is not None:
        # The worker holds this kind for the hub (``irreversible.held_here``); reached
        # only if a hub took the data root between that check and here. Nothing staged.
        return await _refuse(task, held)
    payload = task.payload
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        return await _refuse(task, "payload_invalid")
    path = resolve_backup(name)
    if path is None:
        return await _refuse(task, "backup_missing")
    st = path.stat()
    if st.st_size != payload.get("bytes") or st.st_mtime != payload.get("mtime"):
        return await _refuse(task, "backup_changed")
    task_id = getattr(task, "id", None)
    # Known before the stage is written (review r6), so the stage never reads as waiting
    # for a restart that is not coming.
    planned = "self" if hub_restart.available() else "manual"
    staged = await asyncio.to_thread(stage_restore, name,
                                     requested_by=str(getattr(task, "decided_by", "") or ""),
                                     task_id=task_id if isinstance(task_id, int) else None,
                                     restart=planned)
    if not staged["ok"]:
        return await _refuse(task, "backup_failed_verify", problem=staged["problem"])
    restart = "requested" if planned == "self" and hub_restart.request(APPROVAL_KIND) else "manual"
    result = {"status": "ok", "kind": APPROVAL_KIND, "staged": name, "restart": restart,
              "expires_at": staged.get("expires_at")}
    if restart == "manual":
        # Nothing restarts this hub (a raw uvicorn start, a Windows service without the
        # NSSM marker): say so on the result and on the stage, never imply a restart.
        if planned != "manual":
            await asyncio.to_thread(_note_manual_restart, None, staged)
        result["action_needed"] = manual_restart_hint(staged.get("expires_at"))
    return result


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
    pc.add_argument("--quick", action="store_true", help="only the state DBs: a small, fast rollback point")
    sub.add_parser("list", help="list existing backups")
    pv = sub.add_parser("verify", help="restore-drill a backup (integrity-check its DBs)")
    pv.add_argument("name", help="backup file name (see `list`), or a path to one in the backups dir")
    pr = sub.add_parser("restore", help="restore a backup into a target dir")
    pr.add_argument("name", help="backup file name (see `list`), or a path to one in the backups dir")
    pr.add_argument("target", help="destination directory")
    pr.add_argument("--force", action="store_true", help="overwrite a non-empty target")
    args = ap.parse_args(argv)

    if args.cmd == "create":
        print(json.dumps(create_backup(encrypt=True if args.encrypt else None, quick=args.quick),
                         indent=2))
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
