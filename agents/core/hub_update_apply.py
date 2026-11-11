"""hub_update_apply.py — apply an update to the running hub, verify it, roll it back (H624).

G21 (:mod:`agents.core.hub_update`) built the read-only half: what the hub runs, how far
behind its upstream it is, a fetch, a restart. Applying was refused because nothing could
tell whether the new commit is one the owner trusts. This module adds that check and the
pipeline behind it.

**Trust** (:func:`trust_status`, :func:`request_trust`). The owner pins trust once, through
an approval card at the irreversible tier (``hub.update_trust``), in one of three modes:

* ``ssh`` — allowed SSH signing keys. Nerva writes its own allowed-signers file under
  ``<data root>/update/`` and verifies with ``gpg.ssh.allowedSignersFile`` pointing at it;
  a commit (or a tag that points at it) is accepted only when git reports a good signature
  by one of those exact key fingerprints.
* ``gpg`` — OpenPGP public keys, imported into a dedicated keyring (``GNUPGHOME`` under
  ``<data root>/update/gnupg``, nothing else in it, key fetching off); the fingerprints the
  owner declared must be exactly the primary keys in the block.
* ``pinned`` — one exact commit the owner chose; only that commit can be applied.

With no trust configured every apply is refused, named. Verification runs git with a fixed
argv, the minimal environment of G21 (``hub_update._git_env``), hooks and fsmonitor off, the
``ext::`` transport refused, the global and system git configuration ignored, and the signing
programs fixed (``ssh-keygen`` / ``gpg``; the other formats point at a program that does not
exist), so a repository can never choose what runs during verification. Nothing from the
working tree is executed to verify it.

**Apply** (:func:`plan`, :func:`request_apply`, :func:`apply_approved`). ``plan`` says what
would change: the commits, the files, whether the pinned dependency lock changed (and whether
:func:`lock_problem` refuses it), files that may carry a schema migration
(:func:`_possible_migrations`: a migration-shaped name, or store code by content — the stores
declare their migrations inline; a scan that cannot run assumes one), the version from → to,
the trust verdict and every refusal.
``request_apply`` queues a ``hub.update`` card showing that plan and the exact target commit.
Only a person's plain accept of the unchanged card runs the pipeline, as an ops action whose
log the HUD polls (``GET /api/admin/ops/actions/{id}``) and which is copied into the receipt:

1. re-check: HEAD is still the plan's ``from``, the target still verifies, the tree is clean
   (or the owner chose ``stash``: the changes are stashed, never discarded);
2. a fresh full backup of the data root, created and verified immediately before;
3. a receipt (``<data root>/update/current.json`` + ``receipts.jsonl``): from, to, backup,
   who approved, when;
4. HEAD and the tree re-read (the backup took time), then ``git merge --ff-only <target sha>``
   — never a merge commit, never a ref that could move;
5. when the dependency lock changed: ``pip install --require-hashes --only-binary :all:
   --no-deps -r requirements-beta.lock`` (hash-pinned, wheels only, so no build script runs);
6. the hub restarts through ``hub_restart``; schema migrations run as each store opens in
   the restarted hub (the H23.7 framework), which is why the backup comes first.

**Verify after restart** (:func:`on_boot`, :func:`verify_after_restart`). The restarted hub
polls its own ``/readyz`` on loopback and checks that it booted from the target commit and
reports the target's version. On success the receipt says ``verified``. On failure — or
when the new code cannot even start: ``serve.py`` counts the boots (:func:`boot_guard`) —
the update is rolled back: git back to ``from`` (``git reset --keep``, which never discards
uncommitted changes), the old lock reinstalled when it had changed and the packages the new
lock added removed, the pre-update backup staged for an in-place restore when a migration may
have run (the restore keeps the live ``update/`` state: trust and receipts), and the hub
restarted again. A rollback whose reinstall failed or whose backup could not be staged ends
``rollback_incomplete`` with the command to run, never ``rolled_back``. The probe opens
loopback with no proxy. What the automatic rollback cannot do is :data:`AUTO_ROLLBACK_LIMITS`.

**Rollback** (:func:`request_rollback`): the last update, as a ``hub.update_rollback`` card
(the same steps), and :func:`rollback_offline` for a hub that is not running.

Every request, apply, verification and rollback is audited (the intent log, and the hub log).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess  # nosec B404 - fixed argv, no shell
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from agents.core import hub_update

logger = logging.getLogger("jarvis.hub_update_apply")

APPROVAL_KIND = "hub.update"
ROLLBACK_KIND = "hub.update_rollback"
TRUST_KIND = "hub.update_trust"
KINDS = (APPROVAL_KIND, ROLLBACK_KIND, TRUST_KIND)
TRUST_MODES = ("ssh", "gpg", "pinned")
DIRTY_POLICIES = ("refuse", "stash")
#: The lock the installer uses (scripts/bootstrap.py LOCK_FILE); the only one an update installs.
DEPENDENCY_LOCK = "requirements-beta.lock"
#: A program that does not exist: the signature formats a trust mode does not use point here.
_NO_PROGRAM = "/nonexistent/nerva-signing-disabled"
_HEX_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_REF = re.compile(r"^(?!-)(?!.*\.\.)(?!.*@\{)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}$")
_SSH_KEY = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)|sk-ssh-ed25519@openssh\.com|"
                      r"sk-ecdsa-sha2-nistp256@openssh\.com) ([A-Za-z0-9+/]+={0,3})(?: [^\r\n]{0,200})?$")
_GPG_FPR = re.compile(r"^[0-9A-F]{40}(?:[0-9A-F]{24})?$")
_SSH_FPR = re.compile(r"SHA256:[A-Za-z0-9+/]{43}")
_VERSION = re.compile(r"""^__version__\s*=\s*["']([^"'\s]{1,40})["']""", re.M)
#: Changed paths that may carry a schema migration (the stores migrate when they open).
_MIGRATION = re.compile(r"(^|/)(migrations?|persistence)(/|\.py$)|(^|/)(db|schema|store)\.py$|migrat", re.I)
#: Contents that mark a changed file as store code that may migrate data when it opens: DDL,
#: SQLite's schema version, a schema-version constant or migration list, an SQLite connect.
#: POSIX ERE for ``git grep -E -i`` (run against the commit, never the working tree).
_STORE_CODE = (r"alter[[:space:]]+table|create[[:space:]]+(temp(orary)?[[:space:]]+)?(virtual[[:space:]]+)?table|"
               r"create[[:space:]]+(unique[[:space:]]+)?index|user_version|schema_?version|_?migrations?[[:space:]]*[=:(]|"
               r"apply_migrations|sqlite3?\.connect|executescript")
_LOCK_REQ = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9._,-]+\])?==[A-Za-z0-9._+!-]+")
_LOCK_HASH = re.compile(r"^--hash=sha(256|384|512):[0-9a-f]{64,128}$")
#: What the automatic rollback cannot do (status, the apply card, docs/UPGRADE.md).
AUTO_ROLLBACK_LIMITS = (
    "the automatic rollback runs in the code it rolls back from: a release whose serve.py, or whose "
    "agents/core/hub_update_apply.py and its imports, break before the boot guard runs cannot roll "
    "itself back through this module. serve.py then still counts the boots with the standard library "
    "and, past JARVIS_UPDATE_MAX_BOOTS, moves the checkout back with plain git (no data restore, no "
    "dependency reinstall); when even serve.py does not run, stop Nerva and run "
    "`nerva update rollback --offline --yes` (or, if that does not import either, `git reset --keep "
    "<from>` in the checkout and reinstall requirements-beta.lock)")
MAX_KEYS = 8
MAX_ARMOR_BYTES = 64_000
MAX_COMMITS = 200
MAX_FILES = 500
VERIFY_POLL_S = 2.0
PIP_TIMEOUT_S = 900
GPG_TIMEOUT_S = 30

_STATE_LOCK = threading.RLock()
_BOOT: dict[str, Any] = {"commit": None}


class UpdateRefused(Exception):
    """A request refused before anything was queued or changed: ``code`` names it."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


# ── where the state lives ──────────────────────────────────────────────────────

def state_dir() -> Path:
    from agents.core.paths import data_root

    return data_root() / "update"


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _append_receipt(record: dict) -> None:
    path = state_dir() / "receipts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def receipts(limit: int = 50) -> list[dict]:
    """The receipts, newest last (each line is one state an update or rollback reached)."""
    path = state_dir() / "receipts.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-max(1, limit):]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def current() -> dict | None:
    """The update or rollback in flight (it survives the restart), or None."""
    return _read_json(state_dir() / "current.json")


def _save_current(record: dict) -> None:
    _write_json(state_dir() / "current.json", record)


def _close_current(record: dict, result: str, **extra: Any) -> dict:
    """Write the terminal state: the receipt line, then no update in flight."""
    record.update(extra)
    record["result"] = result
    record["ended_at"] = time.time()
    _phase(record, result)
    _append_receipt(record)
    (state_dir() / "current.json").unlink(missing_ok=True)
    return record


def _phase(record: dict, phase: str) -> None:
    record["phase"] = phase
    record.setdefault("phases", []).append({"phase": phase, "at": time.time()})


def _pending_path() -> Path:
    return state_dir() / "pending.json"


def _remember_card(kind: str, task_id: int, payload: dict) -> None:
    with _STATE_LOCK:
        rows = _read_json(_pending_path()) or {}
        rows[kind] = {"task_id": task_id, "payload": payload, "at": time.time()}
        _write_json(_pending_path(), rows)


def _take_card(kind: str, task: Any, keys: tuple[str, ...]) -> tuple[dict | None, str | None]:
    """The recorded request for ``task`` when its payload is unchanged: ``(payload, None)``,
    else ``(None, reason)``. The record is consumed, so a card applies once."""
    with _STATE_LOCK:
        rows = _read_json(_pending_path()) or {}
        row = rows.get(kind)
        if not isinstance(row, dict) or row.get("task_id") != getattr(task, "id", None):
            return None, "not_requested"
        payload = getattr(task, "payload", None) or {}
        expected = row.get("payload") or {}
        if any(payload.get(k) != expected.get(k) for k in keys):
            return None, "payload_changed"
        rows.pop(kind, None)
        _write_json(_pending_path(), rows)
        return dict(expected), None


# ── git ────────────────────────────────────────────────────────────────────────

def _git(*args: str, cfg: tuple[str, ...] = (), isolated: bool = False, env_extra: dict | None = None,
         timeout: float = 60) -> tuple[int, str, str]:
    """git in the hub's checkout: G21's fixed argv and minimal environment, plus ``-c`` pins.
    ``isolated`` also ignores the global and system git configuration."""
    flat: list[str] = []
    for item in cfg:
        flat += ["-c", item]
    env = hub_update._git_env()
    if isolated:
        env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    if env_extra:
        env.update(env_extra)
    try:
        done = subprocess.run(hub_update._git_argv(*flat, *args), cwd=hub_update.repo_root(),  # nosec B603 B607
                              capture_output=True, text=True, timeout=timeout, env=env, check=False)
    except FileNotFoundError:
        return 127, "", "git is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "git timed out"
    except OSError as exc:
        return 126, "", type(exc).__name__
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def _rev(ref: str) -> str | None:
    code, out, _ = _git("rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
    return out if code == 0 and _HEX_SHA.match(out) else None


def head() -> str | None:
    return _rev("HEAD")


def _dirty() -> bool | None:
    code, out, _ = _git("status", "--porcelain", "--untracked-files=no")
    return bool(out) if code == 0 else None


def _version_at(commit: str) -> str | None:
    code, out, _ = _git("show", f"{commit}:agents/__init__.py")
    match = _VERSION.search(out) if code == 0 else None
    return match.group(1) if match else None


def _tag_name_matches(tag: str) -> bool:
    """An annotated tag object carries its own name (``tag <name>`` in its header); a signed
    tag re-pointed under another ref name is refused. A lightweight tag has no object (and no
    signature: ``verify-tag`` refuses it anyway)."""
    code, kind, _ = _git("cat-file", "-t", f"refs/tags/{tag}")
    if code != 0 or kind != "tag":
        return True
    code, out, _ = _git("cat-file", "tag", f"refs/tags/{tag}")
    if code != 0:
        return False
    for line in out.split("\n\n", 1)[0].splitlines():
        if line.startswith("tag "):
            return line[4:] == tag
    return False


def lock_problem(text: str) -> str | None:
    """Why a dependency lock is refused, or None. The installer runs pip with
    ``--require-hashes --only-binary :all: --no-deps``: only wheels whose sha256 the lock pins
    are installed, nothing is built (no ``setup.py`` or build backend runs) and no dependency
    is resolved. What still runs is the installed code itself (imported by the restarted hub,
    including any ``.pth`` file a wheel ships, at interpreter start). A lock line can carry
    pip options that loosen this, so only ``name==version [; marker]`` requirements with
    ``--hash=`` options are accepted: any option line (``--no-binary``, ``--no-build-isolation``,
    ``--index-url``, ``-r``/``-c``/``-e``, …), any other per-requirement option, and any direct
    URL or path reference refuse the lock."""
    logical: list[str] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0] if not raw.lstrip().startswith("#") else ""
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        buf += line
        if buf.strip():
            logical.append(buf.strip())
        buf = ""
    if buf.strip():
        logical.append(buf.strip())
    if not logical:
        return "the lock lists no requirement"
    for line in logical:
        if line.startswith("-"):
            return f"the lock carries a pip option line ({line.split()[0][:60]})"
        tokens = re.sub(r";.*?(?=\s--|$)", " ", line).split()   # an environment marker is not an option
        if not tokens or not _LOCK_REQ.fullmatch(tokens[0]):
            return f"not a pinned name==version requirement: {tokens[0][:60] if tokens else line[:60]}"
        for token in tokens[1:]:
            if not _LOCK_HASH.match(token):
                return f"an option other than --hash on {tokens[0][:60]}: {token[:60]}"
        if not any(_LOCK_HASH.match(t) for t in tokens[1:]):
            return f"{tokens[0][:60]} has no --hash"
    return None


def lock_names(text: str) -> set[str]:
    """The normalised project names a lock pins (PEP 503 normalisation)."""
    names = set()
    for raw in text.splitlines():
        match = _LOCK_REQ.match(raw.strip())
        if match:
            names.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    return names


def _file_at(commit: str, path: str) -> str | None:
    code, out, _ = _git("show", f"{commit}:{path}")
    return out if code == 0 else None


# ── trust ──────────────────────────────────────────────────────────────────────

def ssh_fingerprint(key_line: str) -> str:
    """OpenSSH's ``SHA256:`` fingerprint of a public key line (what ``ssh-keygen -l`` prints)."""
    match = _SSH_KEY.match(key_line.strip())
    if not match:
        raise UpdateRefused("invalid_key", "an SSH public key line: '<type> <base64> [comment]'")
    try:
        blob = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UpdateRefused("invalid_key", "the key's base64 does not decode") from exc
    # The blob starts with its own type name; a mismatch is not that key.
    if len(blob) < 4 or blob[4:4 + int.from_bytes(blob[:4], "big")].decode("ascii", "replace") != match.group(1):
        raise UpdateRefused("invalid_key", "the key's type does not match its contents")
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def _trust_path() -> Path:
    return state_dir() / "trust.json"


def trust() -> dict | None:
    record = _read_json(_trust_path())
    return record if record and record.get("mode") in TRUST_MODES else None


def trust_status() -> dict:
    """What the owner pinned, without key material: mode, fingerprints or commit, when, who."""
    record = trust()
    if record is None:
        return {"configured": False, "mode": None,
                "detail": "no trusted signing key or pinned commit: every apply is refused until the "
                          "owner pins one (an approval card at the irreversible tier)"}
    view = {"configured": True, "mode": record["mode"], "set_at": record.get("set_at"),
            "set_by": record.get("set_by")}
    if record["mode"] == "pinned":
        view["commit"] = record.get("commit")
    else:
        view["fingerprints"] = [k.get("fingerprint") for k in record.get("keys") or []]
        if record["mode"] == "ssh":
            view["principals"] = [k.get("principal") for k in record.get("keys") or []]
    return view


def _gpg_env(home: Path) -> dict[str, str]:
    return {"PATH": hub_update._git_env().get("PATH", os.defpath), "GNUPGHOME": str(home), "LC_ALL": "C"}


def _gpg(home: Path, *args: str, data: str | None = None) -> tuple[int, str, str]:
    try:
        done = subprocess.run(["gpg", "--batch", "--no-tty", "--no-autostart", *args],  # nosec B603 B607
                              input=data, capture_output=True, text=True, timeout=GPG_TIMEOUT_S,
                              env=_gpg_env(home), check=False)
    except FileNotFoundError:
        return 127, "", "gpg is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "gpg timed out"
    return done.returncode, done.stdout, done.stderr


def _new_gnupg_home(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True)
    (path / "gpg.conf").write_text("no-auto-key-retrieve\nno-autostart\nno-greeting\n", encoding="utf-8")


def _import_gpg(home: Path, armored: str) -> set[str]:
    """Import ``armored`` into the fresh keyring ``home``; the primary fingerprints in it."""
    _new_gnupg_home(home)
    code, out, err = _gpg(home, "--status-fd", "1", "--import", data=armored)
    # gpg exits 2 after a good import when it cannot reach an agent (a socket path too long
    # under a deep data root): the import's own status line, then the key list below, decide.
    if code != 0 and "[GNUPG:] IMPORT_OK" not in out:
        raise UpdateRefused("invalid_key", f"gpg could not import the key block ({err.strip()[-200:]})")
    code, out, _ = _gpg(home, "--with-colons", "--fixed-list-mode", "--list-keys")
    primaries: set[str] = set()
    expect_fpr = False
    for line in out.splitlines():
        fields = line.split(":")
        if fields[0] == "pub":
            expect_fpr = True
        elif fields[0] == "fpr" and expect_fpr and len(fields) > 9:
            primaries.add(fields[9].upper())
            expect_fpr = False
        elif fields[0] == "sub":
            expect_fpr = False
    return primaries


def _normalise_trust(body: dict) -> dict:
    """The trust record a request asks for, validated; raises :class:`UpdateRefused`."""
    mode = body.get("mode")
    if mode not in TRUST_MODES:
        raise UpdateRefused("invalid_mode", "mode is ssh, gpg or pinned")
    if mode == "pinned":
        commit = str(body.get("commit") or "").strip().lower()
        if not _HEX_SHA.match(commit):
            raise UpdateRefused("invalid_commit", "a full 40- (or 64-) hex commit id")
        return {"mode": "pinned", "commit": commit}
    if mode == "ssh":
        principal = str(body.get("principal") or "owner")
        if not _PRINCIPAL.match(principal):
            raise UpdateRefused("invalid_principal")
        lines = [str(k).strip() for k in body.get("keys") or [] if str(k).strip()]
        if not 1 <= len(lines) <= MAX_KEYS:
            raise UpdateRefused("invalid_key", f"one to {MAX_KEYS} SSH public keys")
        keys, seen = [], set()
        for line in lines:
            fpr = ssh_fingerprint(line)
            if fpr not in seen:
                seen.add(fpr)
                kind, blob = _SSH_KEY.match(line).group(1, 2)   # the comment is dropped
                keys.append({"principal": principal, "key": f"{kind} {blob}", "fingerprint": fpr})
        return {"mode": "ssh", "keys": keys}
    armored = str(body.get("public_key") or "")
    if not armored.strip().startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----") or len(armored) > MAX_ARMOR_BYTES:
        raise UpdateRefused("invalid_key", "an ASCII-armored OpenPGP public key block")
    declared = {str(f).replace(" ", "").upper() for f in body.get("fingerprints") or []}
    if not declared or not all(_GPG_FPR.match(f) for f in declared) or len(declared) > MAX_KEYS:
        raise UpdateRefused("invalid_fingerprint", "the primary key fingerprints, declared explicitly")
    with tempfile.TemporaryDirectory(prefix="nerva-gpg-") as tmp:
        found = _import_gpg(Path(tmp) / "home", armored)
    if found != declared:
        raise UpdateRefused("fingerprint_mismatch",
                            f"the block holds {sorted(found)}, the request declared {sorted(declared)}")
    return {"mode": "gpg", "keys": [{"fingerprint": f, "armored": armored} for f in sorted(declared)]}


def request_trust(orch: Any, body: dict, *, requested_by: str = "owner") -> dict:
    """Queue a ``hub.update_trust`` card for the trust the owner asks for."""
    from agents.core.autonomy import irreversible

    record = _normalise_trust(body)
    payload = {"operation": TRUST_KIND, "trust": record,
               "trust_sha256": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()}
    previous = trust_status()
    shown = {"mode": record["mode"]}
    if record["mode"] == "pinned":
        shown["commit"] = record["commit"]
    else:
        shown["fingerprints"] = [k["fingerprint"] for k in record["keys"]]
    preview = {"action": "Change which code Nerva may update itself to",
               "new_trust": shown,
               "replaces": {k: v for k, v in previous.items() if k in ("mode", "fingerprints", "commit")}
               if previous.get("configured") else "nothing (no trust configured yet)",
               "effect": "from now on an update applies only a commit signed by these keys"
               if record["mode"] != "pinned" else "from now on an update applies only this exact commit"}
    queued = irreversible.enqueue(orch, TRUST_KIND, title=f"Pin update trust: {record['mode']}",
                                  payload=payload, preview=preview)
    if "pending" not in queued:
        raise UpdateRefused(str(queued.get("refused") or "approval_queue_unavailable"))
    _remember_card(TRUST_KIND, queued["pending"], payload)
    _audit(orch, requested_by, "hub.update.trust_requested", f"trust change requested ({record['mode']})",
           {"mode": record["mode"], "task_id": queued["pending"]})
    return {"pending": queued["pending"], "mode": record["mode"]}


def _write_trust(record: dict, approved_by: str, task_id: Any) -> None:
    base = state_dir()
    base.mkdir(parents=True, exist_ok=True)
    signers = base / "allowed_signers"
    gnupg = base / "gnupg"
    if record["mode"] == "gpg":
        fresh = base / f"gnupg.{uuid.uuid4().hex[:8]}"
        found = _import_gpg(fresh, record["keys"][0]["armored"])
        if found != {k["fingerprint"] for k in record["keys"]}:
            shutil.rmtree(fresh, ignore_errors=True)
            raise UpdateRefused("fingerprint_mismatch")
        shutil.rmtree(gnupg, ignore_errors=True)
        os.replace(fresh, gnupg)
    else:
        shutil.rmtree(gnupg, ignore_errors=True)
    lines = [f'{k["principal"]} namespaces="git" {k["key"]}' for k in record.get("keys") or []
             if record["mode"] == "ssh"]
    signers.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    _write_json(_trust_path(), {**record, "set_at": time.time(), "set_by": approved_by, "task_id": task_id})


def _verify_cfg(mode: str) -> tuple[tuple[str, ...], dict]:
    base = state_dir()
    signers = base / "allowed_signers"
    if mode == "ssh":
        return (("gpg.ssh.program=ssh-keygen", f"gpg.ssh.allowedSignersFile={signers}",
                 f"gpg.program={_NO_PROGRAM}", f"gpg.x509.program={_NO_PROGRAM}"), {})
    return ((f"gpg.ssh.program={_NO_PROGRAM}", f"gpg.ssh.allowedSignersFile={signers}",
             "gpg.program=gpg", f"gpg.x509.program={_NO_PROGRAM}"), {"GNUPGHOME": str(base / "gnupg")})


def verify_target(commit: str, tag: str | None = None) -> dict:
    """Whether ``commit`` (or the tag ``tag`` that points at it) is one the owner trusts:
    ``{"trusted": bool, "how": …, "signer": fingerprint, "reason": …}``."""
    record = trust()
    if record is None:
        return {"trusted": False, "reason": "no_trust_configured"}
    if record["mode"] == "pinned":
        ok = commit == record.get("commit")
        return {"trusted": ok, "how": "pinned", "reason": None if ok else "not_the_pinned_commit"}
    allowed = {k.get("fingerprint") for k in record.get("keys") or []}
    cfg, env = _verify_cfg(record["mode"])
    good = ("G",) if record["mode"] == "ssh" else ("G", "U")   # gpg: our keyring holds only trusted keys
    # A closing field keeps the split stable: str.strip() treats \x1f as whitespace, so an empty
    # last field (%GP is empty for an SSH signature) would otherwise vanish with it.
    code, out, _ = _git("log", "-1", "--format=%G?%x1f%GF%x1f%GP%x1fend", commit, "--", cfg=cfg, isolated=True,
                        env_extra=env)
    parts = out.split("\x1f") if code == 0 else []
    if len(parts) == 4 and parts[3] == "end":
        status, fpr, primary = parts[0], parts[1].upper() if record["mode"] == "gpg" else parts[1], parts[2].upper()
        signer = next((f for f in (fpr, primary) if f in allowed), None)
        if status in good and signer:
            return {"trusted": True, "how": "signed_commit", "signer": signer, "reason": None}
    if tag:
        tag_commit = _rev(f"refs/tags/{tag}")
        if tag_commit == commit and not _tag_name_matches(tag):
            return {"trusted": False, "reason": "tag_name_mismatch",
                    "detail": f"the signed tag object behind refs/tags/{tag} names another tag: a signed "
                              "tag moved to a different name is not trusted under the new name"}
        if tag_commit == commit:
            code, out, err = _git("verify-tag", "--raw", "--end-of-options", f"refs/tags/{tag}", cfg=cfg,
                                  isolated=True, env_extra=env)
            if code == 0:
                text = out + "\n" + err
                if record["mode"] == "gpg":
                    seen = {f.upper() for line in text.splitlines() if line.startswith("[GNUPG:] VALIDSIG")
                            for f in (line.split()[2], line.split()[-1])}
                else:
                    seen = set(_SSH_FPR.findall(text))
                signer = next(iter(seen & allowed), None)
                if signer:
                    return {"trusted": True, "how": "signed_tag", "signer": signer, "reason": None}
    return {"trusted": False, "reason": "signature_not_trusted",
            "detail": "the target carries no good signature by a pinned key (unsigned, signed by another "
                      "key, or the signature does not verify)"}


def default_target_status() -> dict:
    """The default target (the pinned commit in ``pinned`` mode, else the tracked upstream)
    and its signature status against the pinned trust, for ``hub_update.check``:
    ``{"ref", "commit", "signature": "verified"|"unverified"|"no_trust"|"unknown", …}``."""
    try:
        commit, _tag, label = _target(None)
    except UpdateRefused:
        commit, label = None, None
    view: dict[str, Any] = {"ref": label, "commit": commit, "signature": "unknown", "how": None,
                            "signer": None, "reason": None}
    if commit is None:
        return view
    if trust() is None:
        view["signature"] = "no_trust"
        return view
    verdict = verify_target(commit)
    view.update(signature="verified" if verdict["trusted"] else "unverified", how=verdict.get("how"),
                signer=verdict.get("signer"), reason=verdict.get("reason"))
    return view


# ── the plan ───────────────────────────────────────────────────────────────────

def _target(ref: str | None) -> tuple[str | None, str | None, str | None]:
    """``(commit, tag-or-None, label)`` for the requested ref (default: the pinned commit, else
    the tracked upstream)."""
    record = trust()
    if ref is None:
        if record and record["mode"] == "pinned":
            commit = record["commit"]
            return (_rev(commit), None, commit)
        return (_rev("@{u}"), None, "@{u}")
    if _HEX_SHA.match(ref):
        return (_rev(ref), None, ref)
    if not _REF.match(ref):
        raise UpdateRefused("invalid_ref")
    tag = ref if _rev(f"refs/tags/{ref}") else None
    return (_rev(f"refs/tags/{ref}") if tag else _rev(ref), tag, ref)


def _changed(src: str, dst: str) -> list[dict]:
    code, out, _ = _git("diff", "--no-renames", "--name-status", "--no-ext-diff", "--no-textconv", src, dst, "--")
    rows = []
    for line in out.splitlines() if code == 0 else []:
        status, _, path = line.partition("\t")
        if path:
            rows.append({"status": status[:1], "path": path})
    return rows


def _store_code(commit: str, paths: list[str]) -> tuple[set[str], bool]:
    """Which of ``paths`` hold store code at ``commit`` (:data:`_STORE_CODE`), read from the
    commit's tree with ``git grep`` — nothing from the working tree. ``(matches, ok)``: ``ok``
    is False when git could not answer, and the caller then assumes a migration."""
    if not paths:
        return set(), True
    found: set[str] = set()
    for i in range(0, len(paths), 200):
        chunk = paths[i:i + 200]
        code, out, _ = _git("grep", "-l", "-I", "-i", "-E", "--no-textconv", "-e", _STORE_CODE, commit, "--",
                            *[f":(literal){p}" for p in chunk], timeout=120)
        if code not in (0, 1):
            return found, False
        prefix = f"{commit}:"
        found.update(line[len(prefix):] if line.startswith(prefix) else line for line in out.splitlines() if line)
    return found, True


def _possible_migrations(src: str, dst: str, files: list[dict]) -> tuple[list[str], bool]:
    """Changed files that may migrate data when the restarted hub opens its stores: a name that
    looks like a migration, any changed ``.sql``, and any changed Python file under ``agents/``
    whose contents (at the target; at the source for a deleted file) hold DDL, a schema
    version, a migration list or an SQLite connect — the stores declare their migrations
    inline. ``(paths, certain)``: ``certain`` is False when the scan could not run, and the
    update is then treated as migrating (fail safe: the backup is restored on rollback)."""
    named = {r["path"] for r in files if r["path"].endswith(".py") and _MIGRATION.search(r["path"])}
    named |= {r["path"] for r in files if r["path"].endswith(".sql")}
    code_files = [r for r in files if r["path"].startswith("agents/") and r["path"].endswith(".py")]
    present = [r["path"] for r in code_files if r["status"] != "D"]
    gone = [r["path"] for r in code_files if r["status"] == "D"]
    hits_new, ok_new = _store_code(dst, present)
    hits_old, ok_old = _store_code(src, gone)
    return sorted(named | hits_new | hits_old), ok_new and ok_old


def _restart_ready() -> bool:
    return hub_update.restart_mode() == "self"


def plan(ref: str | None = None, dirty_policy: str = "refuse") -> dict:
    """What applying ``ref`` would do, and every reason it would be refused (read-only)."""
    body: dict[str, Any] = {"can_apply": False, "refused": [], "from": None, "to": None, "target_ref": ref,
                            "tag": None, "commits": [], "commit_count": 0, "files": [], "file_count": 0,
                            "dependencies": {"lock": DEPENDENCY_LOCK, "changed": False, "loose_changed": [],
                                             "command": None, "refused": None, "added": []},
                            "migrations": [], "migrations_uncertain": False, "frontend_changed": False, "from_version": None, "to_version": None,
                            "trust": trust_status(), "verdict": None, "dirty": None, "dirty_policy": dirty_policy,
                            "restart": hub_update.restart_mode()}
    refused: list[str] = body["refused"]
    if dirty_policy not in DIRTY_POLICIES:
        raise UpdateRefused("invalid_dirty_policy", "refuse or stash")
    install = hub_update._install_kind()
    if install != "git":
        refused.append("container" if install == "container" else "not_a_git_checkout")
        return body
    if not body["trust"]["configured"]:
        refused.append("no_trust_configured")
    in_flight = current()
    if in_flight:
        refused.append("update_in_progress")
    if not _restart_ready():
        refused.append("restart_manual")
    src = head()
    body["from"] = src
    code, branch, _ = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    if code != 0:
        refused.append("detached_head")
    dst, tag, label = _target(ref)
    body.update({"to": dst, "tag": tag, "target_ref": label})
    body["dirty"] = _dirty()
    if body["dirty"] and dirty_policy == "refuse":
        refused.append("dirty_tree")
    if src is None or dst is None:
        refused.append("target_unknown" if dst is None else "head_unknown")
        return body
    if src == dst:
        refused.append("up_to_date")
        return body
    code, _, _ = _git("merge-base", "--is-ancestor", src, dst)
    if code != 0:
        refused.append("not_fast_forward")
        return body
    code, out, _ = _git("log", "--no-merges", f"--max-count={MAX_COMMITS}", "--format=%H%x1f%s", f"{src}..{dst}", "--")
    body["commits"] = [dict(zip(("sha", "subject"), line.split("\x1f", 1), strict=False))
                       for line in out.splitlines() if code == 0 and line]
    code, count, _ = _git("rev-list", "--count", f"{src}..{dst}")
    body["commit_count"] = int(count) if code == 0 and count.isdigit() else len(body["commits"])
    files = _changed(src, dst)
    body["file_count"] = len(files)
    body["files"] = files[:MAX_FILES]
    paths = {row["path"] for row in files}
    deps = body["dependencies"]
    deps["changed"] = DEPENDENCY_LOCK in paths
    deps["loose_changed"] = sorted(p for p in paths if re.match(r"^requirements[^/]*\.txt$", p))
    if deps["changed"]:
        deps["command"] = " ".join(_pip_argv(hub_update.repo_root() / DEPENDENCY_LOCK))
        lock_text = _file_at(dst, DEPENDENCY_LOCK)
        deps["refused"] = lock_problem(lock_text) if lock_text is not None else "the target has no lock"
        if deps["refused"]:
            refused.append("lock_refused")
        old_lock = _file_at(src, DEPENDENCY_LOCK)
        if lock_text is not None and old_lock is not None:
            deps["added"] = sorted(lock_names(lock_text) - lock_names(old_lock))
    body["migrations"], certain = _possible_migrations(src, dst, files)
    body["migrations_uncertain"] = not certain
    body["frontend_changed"] = any(p.startswith(("frontend/", "package-lock.json")) for p in paths)
    body["from_version"], body["to_version"] = _version_at(src), _version_at(dst)
    verdict = verify_target(dst, tag)
    body["verdict"] = verdict
    if body["trust"]["configured"] and not verdict["trusted"]:
        refused.append("untrusted_target")
    body["can_apply"] = not refused
    return body


def _plan_payload(p: dict) -> dict:
    return {"operation": APPROVAL_KIND, "from": p["from"], "to": p["to"], "target_ref": p["target_ref"],
            "tag": p["tag"], "dirty_policy": p["dirty_policy"], "from_version": p["from_version"],
            "to_version": p["to_version"], "dependencies_changed": p["dependencies"]["changed"],
            "migrations": bool(p["migrations"]) or bool(p.get("migrations_uncertain")),
            "signer": (p["verdict"] or {}).get("signer")}


_APPLY_KEYS = ("operation", "from", "to", "target_ref", "tag", "dirty_policy", "from_version", "to_version",
               "dependencies_changed", "migrations", "signer")


def _migration_line(p: dict) -> str:
    if p.get("migrations_uncertain"):
        return ("possible data migration: the changed files could not be scanned, so one is assumed (the "
                "pre-update backup is restored if the update is rolled back automatically)")
    if p["migrations"]:
        shown = ", ".join(p["migrations"][:20]) + (f" (+{len(p['migrations']) - 20} more)"
                                                   if len(p["migrations"]) > 20 else "")
        return (f"possible data migration in: {shown} (the pre-update backup is restored if the update is "
                "rolled back automatically)")
    return "none expected: the update changes no store code"


def request_apply(orch: Any, ref: str | None = None, dirty_policy: str = "refuse", *,
                  requested_by: str = "owner") -> dict:
    """Queue a ``hub.update`` card for the plan of ``ref``; raises :class:`UpdateRefused`."""
    from agents.core.autonomy import irreversible

    p = plan(ref, dirty_policy)
    if not p["can_apply"]:
        raise UpdateRefused(p["refused"][0], "; ".join(p["refused"]))
    payload = _plan_payload(p)
    preview = {
        "action": f"Update Nerva {p['from_version'] or '?'} → {p['to_version'] or '?'}",
        "from": p["from"], "to": p["to"], "target": p["target_ref"],
        "trust": f"{(p['verdict'] or {}).get('how')} · {(p['verdict'] or {}).get('signer') or ''}".strip(" ·"),
        "commits": p["commit_count"],
        "first_commits": [f"{c['sha'][:12]} {c.get('subject', '')}" for c in p["commits"][:10]],
        "files": p["file_count"],
        "dependencies": p["dependencies"]["command"] or "unchanged",
        "migrations": _migration_line(p),
        "frontend": "changed: rebuild the HUD (npm ci && npm run build in frontend/) after the update"
        if p["frontend_changed"] else "unchanged",
        "dirty_tree": "stash the uncommitted changes first" if p["dirty"] else "clean",
        "effect": ("takes and verifies a full backup, fast-forwards the checkout to the target commit, "
                   "installs the hash-pinned lock if it changed, restarts Nerva and checks that it serves "
                   "the new version; if that check fails it returns to the current commit (the previous "
                   "lock reinstalled and the packages the new lock added removed; the backup restored "
                   "when a migration may have run, keeping the update trust and receipts as they are) "
                   "and restarts again"),
        "limits": AUTO_ROLLBACK_LIMITS,
    }
    queued = irreversible.enqueue(orch, APPROVAL_KIND, title=f"Update Nerva to {p['to'][:12]}",
                                  payload=payload, preview=preview)
    if "pending" not in queued:
        raise UpdateRefused(str(queued.get("refused") or "approval_queue_unavailable"))
    _remember_card(APPROVAL_KIND, queued["pending"], payload)
    _audit(orch, requested_by, "hub.update.requested", f"update to {p['to']} requested",
           {"from": p["from"], "to": p["to"], "task_id": queued["pending"]})
    return {"pending": queued["pending"], "plan": p}


# ── the pipeline ───────────────────────────────────────────────────────────────

def _pip_argv(lock: Path) -> list[str]:
    return [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
            "--require-hashes", "--only-binary", ":all:", "--no-deps", "-r", str(lock)]


def _run_command(argv: list[str], timeout: float) -> tuple[int, str]:
    env = hub_update._git_env()
    env.update({"PIP_NO_INPUT": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    try:
        done = subprocess.run(argv, cwd=hub_update.repo_root(), capture_output=True, text=True,  # nosec B603
                              timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as exc:
        return 126, type(exc).__name__
    return done.returncode, (done.stdout + "\n" + done.stderr)[-4000:]


def install_dependencies(log) -> bool:
    """Install the hash-pinned lock now on disk (wheels only, no dependency resolution); a lock
    :func:`lock_problem` refuses is never handed to pip."""
    lock = hub_update.repo_root() / DEPENDENCY_LOCK
    try:
        problem = lock_problem(lock.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        problem = f"unreadable ({type(exc).__name__})"
    if problem:
        log(f"{DEPENDENCY_LOCK} refused: {problem}")
        return False
    argv = _pip_argv(lock)
    log("$ " + " ".join(argv))
    code, out = _run_command(argv, PIP_TIMEOUT_S)
    for line in out.splitlines()[-20:]:
        if line.strip():
            log(line)
    return code == 0


class _Logger:
    """Lines go to the ops action the HUD polls and to the receipt."""

    def __init__(self, record: dict | None, receipt: dict):
        self.action = record
        self.receipt = receipt

    def __call__(self, line: str) -> None:
        clean = hub_update.clean_line(line)
        logger.info("update: %s", clean)
        if self.action is not None:
            hub_update._log(self.action, clean)
        lines = self.receipt.setdefault("log", [])
        if len(lines) < hub_update.MAX_LOG_LINES:
            lines.append(clean)


def _backup(log, label: str) -> dict:
    from agents.core import backup

    made = backup.create_backup(label=label)
    name = Path(made["archive"]).name
    log(f"backup {name} created ({made.get('file_count')} files)")
    report = backup.verify_backup(made["archive"])
    log(f"backup {name} verified: {'ok' if report.get('ok') else report.get('problem')}")
    return {"name": name, "ok": bool(report.get("ok")), "problem": report.get("problem")}


_KEEP_PACKAGES = frozenset({"pip", "setuptools", "wheel"})


def _uninstall_argv(names: list[str]) -> list[str]:
    return [sys.executable, "-m", "pip", "uninstall", "--disable-pip-version-check", "--no-input", "-y", *names]


def uninstall_packages(names: list[str], log) -> bool:
    """Remove the packages a rolled-back lock added (names come from the lock, validated)."""
    argv = _uninstall_argv(names)
    log("$ " + " ".join(argv))
    code, out = _run_command(argv, PIP_TIMEOUT_S)
    for line in out.splitlines()[-20:]:
        if line.strip():
            log(line)
    return code == 0


def _reinstall_command() -> str:
    return f"cd {hub_update.repo_root()} && " + " ".join(_pip_argv(hub_update.repo_root() / DEPENDENCY_LOCK))


def _return_to(commit: str, log, *, reinstall: bool, leaving: str | None = None) -> dict:
    """Move the checkout back to ``commit`` (``git reset --keep``); when the lock changed,
    reinstall the lock now on disk and remove the packages the lock of ``leaving`` added
    (pip-sync style). ``{"git": bool, "deps": True|False|None, "reason", "remaining"}``:
    ``deps`` False means the previous dependencies are NOT in place."""
    out: dict[str, Any] = {"git": False, "deps": None, "reason": None, "remaining": []}
    code, _, err = _git("reset", "--keep", commit)
    log(f"git reset --keep {commit[:12]}: {'ok' if code == 0 else err[-200:]}")
    if code != 0:
        out["reason"] = "git_reset_failed"
        return out
    out["git"] = True
    if not reinstall:
        return out
    log("reinstalling the previous dependency lock")
    if not install_dependencies(log):
        out.update(deps=False, reason="dependency_reinstall_failed")
        log("the previous dependency lock did NOT reinstall: the previous code now runs on the new "
            f"dependencies until it does — with Nerva stopped, run: {_reinstall_command()}")
        return out
    out["deps"] = True
    old_lock = _file_at(commit, DEPENDENCY_LOCK)
    new_lock = _file_at(leaving, DEPENDENCY_LOCK) if leaving else None
    if old_lock is None or new_lock is None or not lock_names(old_lock):
        if leaving:
            log("could not read both locks: packages the new lock added (if any) are left installed")
            out["remaining"] = ["(unknown: a lock could not be read)"]
        return out
    extras = sorted(lock_names(new_lock) - lock_names(old_lock) - _KEEP_PACKAGES)
    if extras:
        log(f"removing the packages the new lock added: {', '.join(extras)}")
        if not uninstall_packages(extras, log):
            out["remaining"] = extras
            log(f"could not remove {', '.join(extras)}: they stay installed (unused by the previous code); "
                f"remove them with: {' '.join(_uninstall_argv(extras))}")
    return out


def _record_return(receipt: dict, back: dict) -> None:
    """Copy what :func:`_return_to` did into the receipt, with what the owner must run."""
    if back["deps"] is not None:
        receipt["dependencies_restored"] = back["deps"]
    if back["remaining"]:
        receipt["packages_left_installed"] = back["remaining"]
    if back["deps"] is False:
        receipt["action_needed"] = ("the previous dependency lock did not reinstall: with Nerva stopped, run "
                                    f"`{_reinstall_command()}`, then start Nerva")


def _restore_stash(stash: str | None, log) -> None:
    if not stash:
        return
    code, _, err = _git("stash", "apply", "--index", stash)
    log(f"stashed changes {'re-applied' if code == 0 else 'NOT re-applied: ' + err[-200:]} "
        f"(stash {stash[:12]}; `git stash apply {stash}` brings them back)")


def _run_pipeline(payload: dict, approved_by: str, task_id: Any, action_record: dict | None) -> dict:
    receipt: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12], "kind": "update", "from": payload["from"], "to": payload["to"],
        "target_ref": payload.get("target_ref"), "tag": payload.get("tag"),
        "from_version": payload.get("from_version"), "to_version": payload.get("to_version"),
        "signer": payload.get("signer"), "dependencies_changed": bool(payload.get("dependencies_changed")),
        "migrations": bool(payload.get("migrations")), "dirty_policy": payload.get("dirty_policy"),
        "approved_by": approved_by, "task_id": task_id, "started_at": time.time(), "boots": 0,
        "action_id": (action_record or {}).get("id"), "stash": None, "backup": None}
    log = _Logger(action_record, receipt)
    _phase(receipt, "started")
    # 1. re-check what the card showed, just before acting
    if head() != payload["from"]:
        return _close_current(receipt, "refused", reason="head_moved")
    if _rev(payload["to"]) != payload["to"]:
        return _close_current(receipt, "refused", reason="target_unknown")
    verdict = verify_target(payload["to"], payload.get("tag"))
    if not verdict["trusted"]:
        log(f"target refused: {verdict.get('reason')}")
        return _close_current(receipt, "refused", reason="untrusted_target")
    log(f"target {payload['to'][:12]} trusted ({verdict.get('how')} {verdict.get('signer') or ''})".rstrip())
    dirty = _dirty()
    if dirty and payload.get("dirty_policy") != "stash":
        return _close_current(receipt, "refused", reason="dirty_tree")
    if dirty is None:
        return _close_current(receipt, "refused", reason="git_status_failed")
    # 2. a fresh verified backup, immediately before
    try:
        made = _backup(log, f"pre-update {payload['to'][:12]}")
    except Exception as exc:  # noqa: BLE001 — no backup, no update
        log(f"backup failed: {type(exc).__name__}: {exc}")
        return _close_current(receipt, "failed", reason="backup_failed")
    receipt["backup"] = made["name"]
    if not made["ok"]:
        return _close_current(receipt, "failed", reason="backup_failed_verify")
    _phase(receipt, "backed_up")
    # 3. the receipt, before the checkout moves
    _save_current(receipt)
    if dirty:
        code, _, err = _git("stash", "push", "--message", f"nerva-update-{receipt['id']}",
                            cfg=("user.name=Nerva", "user.email=nerva@localhost"))
        stash = _rev("stash@{0}") if code == 0 else None
        if stash is None:
            log(f"could not stash the uncommitted changes: {err[-200:]}")
            return _close_current(receipt, "failed", reason="stash_failed")
        receipt["stash"] = stash
        log(f"uncommitted changes stashed as {stash[:12]}")
    # 4. fast-forward only, to the verified sha — HEAD and the tree re-read now: the backup took
    # time, and nothing may have moved the checkout in the meantime.
    moved = None
    if head() != payload["from"]:
        moved = "head_moved"
    elif _dirty() is not False:
        moved = "tree_changed"
    if moved:
        log(f"the checkout changed while the backup ran ({moved}): nothing applied")
        _restore_stash(receipt["stash"], log)
        return _close_current(receipt, "refused", reason=moved)
    code, _, err = _git("merge", "--ff-only", "--no-edit", "--no-verify-signatures", payload["to"], timeout=300)
    if code != 0:
        log(f"fast-forward failed: {err[-300:]}")
        _restore_stash(receipt["stash"], log)
        return _close_current(receipt, "failed", reason="fast_forward_failed")
    _phase(receipt, "fast_forwarded")
    log(f"checkout fast-forwarded {payload['from'][:12]} → {payload['to'][:12]}")
    _save_current(receipt)
    # 5. pinned dependencies
    if receipt["dependencies_changed"]:
        if not install_dependencies(log):
            log("dependency install failed: returning to the previous commit")
            back = _return_to(payload["from"], log, reinstall=True, leaving=payload["to"])
            _record_return(receipt, back)
            _restore_stash(receipt["stash"], log)
            if not back["git"] or back["deps"] is False:
                return _close_current(receipt, "rollback_incomplete", reason="dependency_install_failed",
                                      rollback_problem=back["reason"])
            return _close_current(receipt, "failed", reason="dependency_install_failed")
        _phase(receipt, "dependencies_installed")
    log("schema migrations run as each store opens in the restarted hub"
        + (" (this update changes files that may migrate)" if receipt["migrations"] else ""))
    # 6. restart; the restarted hub verifies itself (on_boot)
    _phase(receipt, "restarting")
    _save_current(receipt)
    _append_receipt({**receipt, "result": None})
    from agents.core import hub_restart

    if not hub_restart.request(f"update to {payload['to'][:12]}"):
        log("this hub cannot restart itself: returning to the previous commit")
        back = _return_to(payload["from"], log, reinstall=receipt["dependencies_changed"], leaving=payload["to"])
        _record_return(receipt, back)
        _restore_stash(receipt["stash"], log)
        if not back["git"] or back["deps"] is False:
            return _close_current(receipt, "rollback_incomplete", reason="restart_unavailable",
                                  rollback_problem=back["reason"])
        return _close_current(receipt, "failed", reason="restart_unavailable")
    log("restart requested; the restarted hub checks /readyz and its version, and rolls back if not")
    return receipt


def held_here(task: Any = None) -> str | None:
    """An update (or rollback) is applied only by the hub, the process that can restart itself."""
    from agents.core import backup

    return backup.restore_held_here(task)


def _decision_ok(task: Any) -> str | None:
    decision = str(getattr(task, "decision", "") or "").strip().lower()
    return None if decision in ("accept", "approve") else "edit_not_supported"


async def apply_approved(task: Any, orch: Any) -> dict:
    """A person accepted a card of one of :data:`KINDS`: do exactly what it showed, once."""
    import asyncio

    kind = str(getattr(task, "kind", "") or "")
    refused = _decision_ok(task)
    if refused:
        return {"status": "refused", "reason": refused}
    approved_by = str(getattr(task, "decided_by", "") or "owner")
    task_id = getattr(task, "id", None)
    if kind == TRUST_KIND:
        payload, why = _take_card(TRUST_KIND, task, ("operation", "trust", "trust_sha256"))
        if payload is None:
            return {"status": "refused", "reason": why}
        try:
            await asyncio.to_thread(_write_trust, payload["trust"], approved_by, task_id)
        except UpdateRefused as exc:
            return {"status": "refused", "reason": exc.code}
        _audit(orch, approved_by, "hub.update.trust_set", f"trust for updates pinned ({payload['trust']['mode']})",
               {"mode": payload["trust"]["mode"], "task_id": task_id})
        return {"status": "ok", "kind": TRUST_KIND, "mode": payload["trust"]["mode"]}
    if held_here(task):
        return {"status": "refused", "reason": "hub_applies_update"}
    if kind == APPROVAL_KIND:
        payload, why = _take_card(APPROVAL_KIND, task, _APPLY_KEYS)
        if payload is None:
            return {"status": "refused", "reason": why}
        if current():
            return {"status": "refused", "reason": "update_in_progress"}
        record = hub_update._new_action("update")
        if record is None:
            return {"status": "refused", "reason": "action_running"}
        receipt = await asyncio.to_thread(_run_pipeline, payload, approved_by, task_id, record)
        result = receipt.get("result")
        hub_update._finish(record, "ok" if result is None else "failed", {"receipt": receipt["id"], "result": result})
        _audit(orch, approved_by, "hub.update.apply", f"update {payload['from'][:12]} → {payload['to'][:12]}: "
               f"{result or 'restarting'}", {"receipt": receipt["id"], "result": result, "task_id": task_id})
        if result is None:
            return {"status": "ok", "kind": APPROVAL_KIND, "receipt": receipt["id"], "restart": "requested"}
        return {"status": "refused" if result == "refused" else "failed", "reason": receipt.get("reason"),
                "result": result, "receipt": receipt["id"]}
    if kind == ROLLBACK_KIND:
        payload, why = _take_card(ROLLBACK_KIND, task, _ROLLBACK_KEYS)
        if payload is None:
            return {"status": "refused", "reason": why}
        record = hub_update._new_action("rollback")
        if record is None:
            return {"status": "refused", "reason": "action_running"}
        receipt = await asyncio.to_thread(_rollback_command, payload, approved_by, task_id, record)
        result = receipt.get("result")
        hub_update._finish(record, "ok" if result is None else "failed", {"receipt": receipt["id"], "result": result})
        _audit(orch, approved_by, "hub.update.rollback", f"rollback to {payload['to'][:12]}: {result or 'restarting'}",
               {"receipt": receipt["id"], "result": result, "task_id": task_id})
        if result is None:
            return {"status": "ok", "kind": ROLLBACK_KIND, "receipt": receipt["id"], "restart": "requested"}
        return {"status": "refused" if result == "refused" else "failed", "reason": receipt.get("reason"),
                "receipt": receipt["id"]}
    return {"status": "refused", "reason": "unknown_kind"}


# ── after the restart ──────────────────────────────────────────────────────────

def _probe_url() -> str:
    from agents.core.env_config import env_int, env_str

    host = env_str("JARVIS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    host = {"0.0.0.0": "127.0.0.1", "::": "::1", "": "127.0.0.1"}.get(host, host)  # nosec B104
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{env_int('JARVIS_PORT', 8080)}/readyz"


def http_probe() -> dict:
    """What the restarted hub serves: ``/readyz`` on its own bind address, its version and the
    commit this process booted from."""
    from agents import __version__

    ready = False
    try:
        # loopback: never through a proxy the environment names (HTTP_PROXY and friends)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(_probe_url(), timeout=3) as resp:  # nosec B310 - loopback, fixed path
            ready = resp.status == 200 and bool(json.loads(resp.read(65536) or b"{}").get("ready"))
    except Exception:  # noqa: BLE001 — not answering yet is "not ready", never a crash
        ready = False
    return {"ready": ready, "version": __version__, "commit": _BOOT["commit"]}


def verify_seconds() -> int:
    from agents.core.env_config import env_int

    return max(10, env_int("JARVIS_UPDATE_VERIFY_SECONDS", 180))


def max_boots() -> int:
    from agents.core.env_config import env_int

    return max(1, env_int("JARVIS_UPDATE_MAX_BOOTS", 3))


def verify_after_restart(probe=None, *, deadline: float | None = None, poll: float = VERIFY_POLL_S,
                         sleep=time.sleep, restart: bool = True) -> dict | None:
    """In the restarted hub: check it serves the target; roll back when it does not."""
    with _STATE_LOCK:
        receipt = current()
        if not receipt or receipt.get("kind") != "update" or receipt.get("phase") not in ("restarting", "verifying"):
            return None
        _phase(receipt, "verifying")
        _save_current(receipt)
    probe = probe or http_probe
    end = time.monotonic() + (verify_seconds() if deadline is None else deadline)
    seen: dict = {}
    while True:
        try:
            seen = probe() or {}
        except Exception:  # noqa: BLE001
            seen = {}
        problems = []
        if not seen.get("ready"):
            problems.append("/readyz did not answer ready")
        if seen.get("commit") != receipt["to"]:
            problems.append(f"booted from {str(seen.get('commit'))[:12]}, not {receipt['to'][:12]}")
        if receipt.get("to_version") and seen.get("version") != receipt["to_version"]:
            problems.append(f"serves version {seen.get('version')}, not {receipt['to_version']}")
        if not problems:
            receipt.setdefault("log", []).append(f"verified: ready, version {seen.get('version')}, "
                                                 f"commit {receipt['to'][:12]}")
            logger.warning("update %s verified", receipt["id"])
            return _close_current(receipt, "verified", verified_at=time.time())
        if time.monotonic() >= end:
            break
        sleep(poll)
    reason = "; ".join(problems)
    logger.error("update %s failed its post-restart check: %s — rolling back", receipt["id"], reason)
    receipt.setdefault("log", []).append(f"post-restart check failed: {reason}")
    return _auto_rollback(receipt, reason, restart=restart)


def _stage_data_restore(receipt: dict, log, restart_planned: str) -> bool:
    from agents.core import backup

    name = receipt.get("backup")
    if not name:
        log("no pre-update backup recorded: data left as it is")
        return False
    staged = backup.stage_restore(name, requested_by=str(receipt.get("approved_by") or "update"),
                                  task_id=receipt.get("task_id") if isinstance(receipt.get("task_id"), int) else None,
                                  restart=restart_planned)
    log(f"pre-update backup {name} {'staged for restore at the next start' if staged.get('ok') else 'NOT staged: ' + str(staged.get('problem'))}")
    return bool(staged.get("ok"))


def _auto_rollback(receipt: dict, reason: str, *, restart: bool) -> dict:
    from agents.core import hub_restart

    log = _Logger(None, receipt)
    _phase(receipt, "rolling_back")
    receipt["rollback_reason"] = reason
    _save_current(receipt)
    back = _return_to(receipt["from"], log, reinstall=bool(receipt.get("dependencies_changed")),
                      leaving=receipt["to"])
    _record_return(receipt, back)
    if not back["git"]:
        return _close_current(receipt, "rollback_failed", reason="git_reset_failed")
    planned = "self" if restart and hub_restart.available() else "manual"
    if receipt.get("migrations"):
        # fail safe: when a migration may have run, the pre-update data comes back (the update
        # trust and receipts under update/ are kept as they are: backup.restore_backup)
        receipt["data_restored"] = _stage_data_restore(receipt, log, planned)
        if not receipt["data_restored"]:
            receipt["action_needed"] = _join_needed(
                receipt.get("action_needed"),
                f"the pre-update backup {receipt.get('backup')} was not staged: restore it (`nerva backup restore`)")
    _restore_stash(receipt.get("stash"), log)
    _phase(receipt, "rolled_back_restarting")
    _save_current(receipt)
    _append_receipt({**receipt, "result": None})
    if planned == "self" and hub_restart.request("update rollback"):
        log("restart requested to run the previous commit")
        return receipt
    log("restart Nerva to run the previous commit")
    receipt["action_needed"] = _join_needed(receipt.get("action_needed"), "restart Nerva the way it was started")
    _save_current(receipt)
    return receipt


def _join_needed(before: str | None, more: str) -> str:
    return f"{before}; {more}" if before else more


def _rollback_result(receipt: dict, booted_from: str | None) -> tuple[str, str | None]:
    """How a rollback ends once the previous code has booted: never ``rolled_back`` while the
    previous dependencies or the pre-update data the rollback needed are not in place."""
    target = receipt["to"] if receipt.get("kind") == "rollback" else receipt["from"]
    if booted_from != target:
        return "rollback_incomplete", "booted_from_another_commit"
    if receipt.get("dependencies_restored") is False:
        return "rollback_incomplete", "dependency_reinstall_failed"
    wanted_data = receipt.get("restore_data") if receipt.get("kind") == "rollback" else receipt.get("migrations")
    if wanted_data and receipt.get("data_restored") is False:
        return "rollback_incomplete", "data_restore_not_staged"
    return "rolled_back", None


def on_boot() -> dict | None:
    """Called once by the hub's start: finish a rollback, or start the post-restart check."""
    try:
        _BOOT["commit"] = head()
        receipt = current()
        if not receipt:
            return None
        if receipt.get("phase") == "rolled_back_restarting":
            result, problem = _rollback_result(receipt, _BOOT["commit"])
            extra: dict[str, Any] = {"booted_from": _BOOT["commit"]}
            if problem:
                extra["rollback_problem"] = problem
                logger.error("update %s: rollback incomplete (%s): %s", receipt["id"], problem,
                             receipt.get("action_needed") or "see the receipt")
            else:
                logger.warning("update %s: rolled back", receipt["id"])
            return _close_current(receipt, result, **extra)
        if receipt.get("kind") == "update" and receipt.get("phase") in ("restarting", "verifying"):
            threading.Thread(target=verify_after_restart, name="hub-update-verify", daemon=True).start()
            return receipt
    except Exception:  # noqa: BLE001 — the post-update check must never keep the hub from starting
        logger.exception("post-update boot step failed")
    return None


def boot_guard() -> bool:
    """``serve.py``, before the hub is imported: count boots of an unverified update; past
    :func:`max_boots` the new code is not starting, so roll back without it. True when the
    checkout was moved back (the caller re-executes so only the previous code runs)."""
    try:
        receipt = current()
        if not receipt or receipt.get("kind") != "update" or receipt.get("phase") not in ("restarting", "verifying"):
            return False
        receipt["boots"] = int(receipt.get("boots") or 0) + 1
        _save_current(receipt)
        if receipt["boots"] <= max_boots():
            return False
        reason = f"the updated hub did not finish starting in {max_boots()} attempts"
        receipt.setdefault("log", []).append(reason)
        done = _auto_rollback(receipt, reason, restart=False)
        return done.get("phase") == "rolled_back_restarting"
    except Exception:  # noqa: BLE001
        logger.exception("update boot guard failed")
        return False


# ── rollback as a command ──────────────────────────────────────────────────────

_ROLLBACK_KEYS = ("operation", "receipt", "from", "to", "backup", "restore_data", "dependencies_changed")


def last_update() -> dict | None:
    """The newest finished update receipt (verified), or None."""
    for row in reversed(receipts(500)):
        if row.get("kind") == "update" and row.get("result") == "verified":
            return row
        if row.get("kind") == "rollback" and row.get("result") in ("rolled_back", None):
            return None
    return None


def rollback_plan(restore_data: bool | None = None) -> dict:
    last = last_update()
    refused = []
    if last is None:
        refused.append("nothing_to_roll_back")
    if current():
        refused.append("update_in_progress")
    if not _restart_ready():
        refused.append("restart_manual")
    now = head()
    if last and now != last.get("to"):
        refused.append("head_moved")
    if _dirty():
        refused.append("dirty_tree")
    restore = bool(last.get("migrations")) if (last and restore_data is None) else bool(restore_data)
    return {"can_rollback": not refused, "refused": refused, "receipt": (last or {}).get("id"),
            "from": now, "to": (last or {}).get("from"), "backup": (last or {}).get("backup"),
            "restore_data": restore, "dependencies_changed": bool((last or {}).get("dependencies_changed")),
            "from_version": (last or {}).get("to_version"), "to_version": (last or {}).get("from_version")}


def request_rollback(orch: Any, restore_data: bool | None = None, *, requested_by: str = "owner") -> dict:
    from agents.core.autonomy import irreversible

    rp = rollback_plan(restore_data)
    if not rp["can_rollback"]:
        raise UpdateRefused(rp["refused"][0], "; ".join(rp["refused"]))
    payload = {"operation": ROLLBACK_KIND, **{k: rp[k] for k in _ROLLBACK_KEYS if k != "operation"}}
    preview = {"action": f"Roll Nerva back {rp['from_version'] or '?'} → {rp['to_version'] or '?'}",
               "from": rp["from"], "to": rp["to"],
               "data": f"restore the pre-update backup {rp['backup']} (data written since the update is lost); "
                       "the update trust and the update receipts under update/ are kept as they are now"
               if rp["restore_data"] else "kept as it is",
               "dependencies": "the previous lock is reinstalled and the packages the update's lock added are "
                               "removed (reported incomplete, with the command to run, if the reinstall fails)"
               if rp["dependencies_changed"] else "unchanged",
               "effect": "moves the checkout back to the commit before the update and restarts Nerva"}
    queued = irreversible.enqueue(orch, ROLLBACK_KIND, title=f"Roll Nerva back to {str(rp['to'])[:12]}",
                                  payload=payload, preview=preview)
    if "pending" not in queued:
        raise UpdateRefused(str(queued.get("refused") or "approval_queue_unavailable"))
    _remember_card(ROLLBACK_KIND, queued["pending"], payload)
    _audit(orch, requested_by, "hub.update.rollback_requested", f"rollback to {rp['to']} requested",
           {"receipt": rp["receipt"], "task_id": queued["pending"]})
    return {"pending": queued["pending"], "plan": rp}


def _rollback_command(payload: dict, approved_by: str, task_id: Any, action_record: dict | None,
                      *, restart: bool = True) -> dict:
    from agents.core import hub_restart

    receipt: dict[str, Any] = {"id": uuid.uuid4().hex[:12], "kind": "rollback", "of": payload.get("receipt"),
                               "from": payload["from"], "to": payload["to"], "backup": payload.get("backup"),
                               "restore_data": bool(payload.get("restore_data")), "approved_by": approved_by,
                               "task_id": task_id, "started_at": time.time(),
                               "action_id": (action_record or {}).get("id")}
    log = _Logger(action_record, receipt)
    _phase(receipt, "started")
    if current():
        return _close_current(receipt, "refused", reason="update_in_progress")
    if head() != payload["from"]:
        return _close_current(receipt, "refused", reason="head_moved")
    if _dirty():
        return _close_current(receipt, "refused", reason="dirty_tree")
    _save_current(receipt)
    back = _return_to(payload["to"], log, reinstall=bool(payload.get("dependencies_changed")),
                      leaving=payload["from"])
    _record_return(receipt, back)
    if not back["git"]:
        return _close_current(receipt, "failed", reason="git_reset_failed")
    planned = "self" if restart and hub_restart.available() else "manual"
    if receipt["restore_data"]:
        receipt["data_restored"] = _stage_data_restore(receipt, log, planned)
    _phase(receipt, "rolled_back_restarting")
    _save_current(receipt)
    _append_receipt({**receipt, "result": None})
    if planned == "self" and hub_restart.request("update rollback"):
        log("restart requested to run the previous commit")
        return receipt
    receipt["action_needed"] = _join_needed(receipt.get("action_needed"), "restart Nerva the way it was started")
    _save_current(receipt)
    log("restart Nerva to run the previous commit")
    return receipt


def rollback_offline(restore_data: bool | None = None) -> dict:
    """Roll back with no hub running (``nerva update rollback --offline``): an update stuck
    unverified is rolled back like a failed check; otherwise the last verified update."""
    from agents.core import install_identity

    if install_identity.hub_lock_held_elsewhere():
        raise UpdateRefused("hub_running", "a hub is running: ask it (`nerva update rollback`)")
    stuck = current()
    if stuck and stuck.get("kind") == "update" and stuck.get("phase") in ("restarting", "verifying", "rolling_back"):
        if restore_data is not None:
            stuck["migrations"] = bool(restore_data)
        return _auto_rollback(stuck, "rolled back by the owner from the command line", restart=False)
    if stuck:
        raise UpdateRefused("update_in_progress", f"phase {stuck.get('phase')}")
    last = last_update()
    if last is None:
        raise UpdateRefused("nothing_to_roll_back")
    now = head()
    if now != last.get("to"):
        raise UpdateRefused("head_moved")
    if _dirty():
        raise UpdateRefused("dirty_tree")
    restore = bool(last.get("migrations")) if restore_data is None else bool(restore_data)
    payload = {"operation": ROLLBACK_KIND, "receipt": last["id"], "from": now, "to": last["from"],
               "backup": last.get("backup"), "restore_data": restore,
               "dependencies_changed": bool(last.get("dependencies_changed"))}
    return _rollback_command(payload, "owner (command line)", None, None, restart=False)


# ── status ─────────────────────────────────────────────────────────────────────

def status() -> dict:
    """Trust, the update in flight and the last receipts (the HUD and ``nerva update status``)."""
    in_flight = current()
    last = receipts(20)
    return {"trust": trust_status(), "auto_rollback_limits": AUTO_ROLLBACK_LIMITS,
            "in_progress": _public(in_flight) if in_flight else None,
            "last_receipt": _public(last[-1]) if last else None,
            "receipts": [_public(r) for r in last], "rollback": {
                k: v for k, v in rollback_plan().items() if k in ("can_rollback", "refused", "to", "restore_data")}}


def _public(row: dict) -> dict:
    keep = ("id", "kind", "from", "to", "of", "target_ref", "from_version", "to_version", "signer", "backup",
            "migrations", "dependencies_changed", "restore_data", "data_restored", "approved_by", "task_id",
            "started_at", "ended_at", "phase", "result", "reason", "rollback_reason", "action_id", "boots",
            "stash", "action_needed", "dependencies_restored", "packages_left_installed", "rollback_problem",
            "booted_from", "log")
    return {k: row.get(k) for k in keep if k in row}


def _audit(orch: Any, actor: str, action: str, why: str, metadata: dict) -> None:
    logger.warning("%s by %s: %s", action, actor, why)
    audit = getattr(orch, "intent_log", None) if orch is not None else None
    if callable(getattr(audit, "record", None)):
        try:
            audit.record(actor=actor, action=action, why=why, cause="hub.update", metadata=metadata)
        except Exception:  # noqa: BLE001 — a projection
            logger.warning("update audit failed", exc_info=True)


# ── offline CLI (a hub that is not running) ───────────────────────────────────

def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nerva-run -m agents.core.hub_update_apply",
                                 description="Update status and an offline rollback when the hub is not running.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="trust, the update in flight and the last receipts")
    rb = sub.add_parser("rollback", help="roll the last update back (the hub must not be running)")
    rb.add_argument("--yes", action="store_true", help="confirm")
    rb.add_argument("--restore-data", choices=("yes", "no"), default=None)
    args = ap.parse_args(argv)
    if args.cmd == "status":
        print(json.dumps(status(), indent=2, default=str))
        return 0
    if not args.yes:
        print("rollback moves the checkout back and may restore data: add --yes to confirm")
        return 2
    try:
        done = rollback_offline(None if args.restore_data is None else args.restore_data == "yes")
    except UpdateRefused as exc:
        print(f"refused: {exc.code}{' — ' + exc.detail if exc.detail else ''}")
        return 1
    print(json.dumps(_public(done), indent=2, default=str))
    return 0 if done.get("phase") == "rolled_back_restarting" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())


__all__ = ["APPROVAL_KIND", "KINDS", "ROLLBACK_KIND", "TRUST_KIND", "UpdateRefused", "apply_approved",
           "boot_guard", "current", "held_here", "http_probe", "last_update", "on_boot", "plan", "receipts",
           "request_apply", "request_rollback", "request_trust", "rollback_offline", "rollback_plan",
           "ssh_fingerprint", "status", "trust_status", "verify_after_restart", "verify_target"]
