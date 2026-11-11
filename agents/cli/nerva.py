"""`nerva` — the command tree. See the package docstring for why it exists.

Exit codes: 0 ok · 1 the verb failed (the hub said no, or a check is red) · 2 usage ·
3 no hub is reachable · 4 a credential is required · 5 the check could not run at all ·
130 interrupted.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shlex
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from .client import HubClient, HubError, HubUnavailable, hub_url, is_loopback_url
from .custom_endpoints import run as cmd_custom_provider
from .mcp_catalog import run as cmd_mcp

REPO_ROOT = Path(__file__).resolve().parents[2]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_NO_HUB = 3
EXIT_AUTH = 4
#: The check could not run at all — a database that was not consulted, a probe that
#: could not be made. Distinct from EXIT_FAILED on purpose: a script must never read
#: "we could not look" as either "clean" or "findings". Nothing is claimed.
EXIT_UNAVAILABLE = 5
#: Ctrl-C. Not a new rung — 130 is what a shell reports for SIGINT (128 + 2) and what
#: this process already exited with, just via an uncaught traceback. The value is kept
#: so `nerva` agrees with every other command a script wraps.
EXIT_INTERRUPTED = 130

_OSV_DEFAULT = "https://api.osv.dev"

_SECRET_KINDS = frozenset({"secret", "password"})
_SECRET_HINTS = ("token", "secret", "password", "api_key", "apikey", "private")
#: Kinds that hold no credential whatever their name: ``llm.max_tokens`` and
#: ``learning.review_max_tokens`` are budgets, and /refine tells the owner to raise one.
#: A model id (``model-select``) is not listed, so a hinted name would be masked; the one
#: model row, ``llm.default_model``, has no hint and shows as typed (review-H465e nit 1).
_PLAIN_KINDS = frozenset({"number", "toggle", "select", "slider"})
_TIER_NAMES = {0: "READ_ONLY", 1: "REVERSIBLE", 2: "EXTERNAL", 3: "IRREVERSIBLE_OR_MONEY"}


@dataclass
class Context:
    environ: Mapping[str, str]
    out: Any = field(default_factory=lambda: sys.stdout)
    err: Any = field(default_factory=lambda: sys.stderr)
    inp: Any = field(default_factory=lambda: sys.stdin)
    client_factory: Callable[[Mapping[str, str]], HubClient] = HubClient.from_env
    #: Reads a secret without echo when a `nerva chat` turn asks for one (H226);
    #: ``None`` is ``getpass``. Tests inject a reader.
    secret_reader: Callable[[str], str] | None = None
    _client: HubClient | None = None

    def client(self) -> HubClient:
        if self._client is None:
            self._client = self.client_factory(self.environ)
        return self._client

    def say(self, text: str = "") -> None:
        self.out.write(text + "\n")

    def dump(self, payload: Any) -> None:
        self.out.write(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")



def _selection_flags(parser: argparse.ArgumentParser) -> None:
    """H378 — the owner's clearance for a model choice a selection guard asks about."""
    parser.add_argument("--confirm-expensive", action="store_true",
                        help="choose a model whose output costs at least llm.cost_confirm_usd_per_mtok anyway")
    parser.add_argument("--acknowledge-training", action="store_true",
                        help="choose a model or route whose vendor may train on your prompts anyway "
                             "(written to the audit log as your consent)")


def _selection_body(ns: argparse.Namespace, body: dict) -> dict:
    for flag in ("confirm_expensive", "acknowledge_training"):
        if getattr(ns, flag, False):
            body[flag] = True
    return body


def _audit_log():
    """The hub's audit log, opened from this process: a consent row a choice made here needs."""
    try:
        from agents.core.security.audit import AuditLogger

        return AuditLogger()
    except Exception:  # noqa: BLE001 — no audit log, no consent, no choice
        return None


def _guarded_job_call(ctx: Context, call) -> dict | None:
    """A job create/edit; a model pin the hub's selection guards refused (409) is named with
    the flags that clear it, and answers None."""
    try:
        return call() or {}
    except HubError as exc:
        if exc.status != 409:
            raise
        ctx.err.write(f"{exc.reason}\nnot changed — rerun with --confirm-expensive / --acknowledge-training "
                      f"to choose that model anyway\n")
        return None


# ── parser ────────────────────────────────────────────────────────────────────


def _profile_arg(value: str) -> str:
    """A profile name ``agents.core.paths`` accepts, else a usage error (exit 2)."""
    from agents.core.paths import PROFILE_ENV, profile_error

    refused = profile_error({PROFILE_ENV: value})
    if refused:
        raise argparse.ArgumentTypeError(refused)
    return value


def _verb_index(raw: list[str]) -> int:
    """Where the verb sits in *raw*: after any leading ``-p NAME`` / ``--profile[=]NAME``."""
    i = 0
    while i < len(raw):
        word = raw[i]
        if word in ("-p", "--profile"):
            i += 2
        elif word.startswith("--profile=") or (word.startswith("-p") and not word.startswith("--")):
            i += 1
        else:
            break
    return i


def _leading_profile(raw: list[str]) -> str | None:
    """The last ``-p NAME`` / ``-pNAME`` / ``--profile[=]NAME`` before the verb (argparse
    keeps the last one too), or None."""
    name = None
    i = 0
    while i < _verb_index(raw):
        word = raw[i]
        if word in ("-p", "--profile"):
            name = raw[i + 1] if i + 1 < len(raw) else None
            i += 2
            continue
        name = word.split("=", 1)[1] if word.startswith("--profile=") else word[2:]
        i += 1
    return name


def _apply_profile_early(raw: list[str]) -> None:
    """H574 review — set ``JARVIS_PROFILE`` from a leading ``-p NAME`` *before* the parser
    is built. :func:`build_parser` imports verb modules, and several of those fix a path
    in the data root at import (``agents.core.secrets.DEFAULT_STORE``, the kanban stores),
    so setting the profile after parsing sent ``nerva -p work secrets op set …`` into the
    default profile's store. An invalid name is left for argparse to refuse (exit 2)."""
    from agents.core.paths import PROFILE_ENV, profile_error

    name = _leading_profile(raw)
    if name is not None and not profile_error({PROFILE_ENV: name}):
        os.environ.update({PROFILE_ENV: name})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nerva",
        # `--prof work` must not pass for `--profile work`: the verb's own argv
        # (kanban, project) is sliced after the profile by `_verb_index`, which only knows
        # the spelled-out forms.
        allow_abbrev=False,
        description="One command for the whole product. Online verbs talk to the running hub "
        "over the same routes the HUD uses; offline verbs read the same data root.",
    )
    # H574 — the H689 profile for this invocation, before the verb (`nerva -p work doctor`).
    parser.add_argument("-p", "--profile", metavar="NAME", type=_profile_arg,
                        help="use this profile's data root, as JARVIS_PROFILE=NAME would "
                             "('default' is the main one); online verbs still reach NERVA_HUB_URL")
    verbs = parser.add_subparsers(dest="verb", required=True, metavar="verb")

    from .nous_auth import configure_parser as configure_nous_auth
    configure_nous_auth(verbs)
    from .secrets import register_parser as configure_secrets
    configure_secrets(verbs)
    from .custom_endpoints import register_parser as configure_custom_endpoints
    configure_custom_endpoints(verbs)
    from .mcp_catalog import register_parser as configure_mcp_catalog
    configure_mcp_catalog(verbs)

    from agents.core.kanban.cli_parser import build_parser as configure_kanban
    configure_kanban(verbs)
    from agents.core.kanban.cli_upstream.projects_commands import build_parser as configure_projects
    configure_projects(verbs)

    doctor = verbs.add_parser("doctor", help="install check-up, one named reason per check (offline)")
    doctor.add_argument("--json", action="store_true")
    doctor_mode = doctor.add_mutually_exclusive_group()
    doctor_mode.add_argument("--smoke", action="store_true", help="also run the install smoke (~30 s)")
    doctor_mode.add_argument("--local-pilot", action="store_true",
                             help="read-only local model and MCP memory prerequisite check")

    support = verbs.add_parser("support", help="a pasteable, non-sensitive diagnostic report")
    support_verbs = support.add_subparsers(dest="action", required=True, metavar="action")
    bundle = support_verbs.add_parser(
        "bundle", help="version, model, which key names are set, changed settings, posture (admin)")
    bundle.add_argument("--json", action="store_true", help="the full allow-listed bundle as JSON")
    bundle.add_argument("--offline", action="store_true",
                        help="build it from the data root without the hub (no audit or route count)")
    bundle.add_argument("--out", metavar="FILE", help="also write it to FILE (owner-only permissions)")
    bundle.add_argument("--logs", type=int, default=0, metavar="N",
                        help="also include the newest N redacted warning/error log records (max 500)")

    prompt_size = verbs.add_parser(
        "prompt-size",
        help="what a fresh turn costs before anybody has said anything (offline)",
    )
    prompt_size.add_argument("--json", action="store_true")
    prompt_size.add_argument("--agent", default="",
                             help="cost the named agent's soul instead of the heaviest")
    prompt_size.add_argument("--window", type=int, default=0,
                             help="compare the floor against a context window of this many tokens")

    extensions = verbs.add_parser("extensions", help="inspect declarative extensions without executing them")
    extension_verbs = extensions.add_subparsers(dest="action", required=True, metavar="action")
    extension_doctor = extension_verbs.add_parser("doctor", help="validate named JSON descriptors and dependency metadata (offline)")
    extension_doctor.add_argument("paths", nargs="+", metavar="MANIFEST")
    extension_doctor.add_argument("--json", action="store_true")
    extension_list = extension_verbs.add_parser("list", help="inspect already-composed acquired packages (user)")
    extension_list.add_argument("--json", action="store_true")
    extension_consent = extension_verbs.add_parser("consent", help="agree to exactly what a descriptor declares, or withdraw it (owner)")
    extension_consent.add_argument("path", metavar="MANIFEST")
    extension_consent.add_argument("--revoke", action="store_true", help="withdraw consent and take its tools off the surface")
    extension_consent.add_argument("--json", action="store_true")
    extension_activate = extension_verbs.add_parser("activate", help="prove a consented descriptor in the sandbox and make its tools callable (owner)")
    extension_activate.add_argument("path", metavar="MANIFEST")
    extension_activate.add_argument("--json", action="store_true")

    status = verbs.add_parser("status", help="what the hub is doing right now")
    status.add_argument("--json", action="store_true")

    config = verbs.add_parser("config", help="read, change and check settings (offline, same data root)")
    config_verbs = config.add_subparsers(dest="action", required=True, metavar="action")
    config_list = config_verbs.add_parser("list", help="list settings, optionally one category")
    config_list.add_argument("category", nargs="?")
    config_list.add_argument("--json", action="store_true")
    config_list.add_argument("--reveal", action="store_true", help="print secret values instead of masking them")
    # H688 — a name may go on below the key into a json value; `\\.` or "quotes" keep a dot
    # inside one key (agents/core/settings_path.py has the grammar).
    path_help = 'category.key[.path] — escape a dot inside a key as \\. or quote the key: "a.b"'
    config_get = config_verbs.add_parser("get", help="print one setting: category.key[.path]")
    config_get.add_argument("name", help=path_help)
    config_get.add_argument("--reveal", action="store_true")
    config_set = config_verbs.add_parser("set", help="change one setting: category.key[.path] value")
    config_set.add_argument("name", help=path_help)
    config_set.add_argument("value")
    _selection_flags(config_set)
    config_unset = config_verbs.add_parser(
        "unset", help="put a setting back to its declared value, or remove one key inside a json setting")
    config_unset.add_argument("name", help=path_help)
    _selection_flags(config_unset)
    config_verbs.add_parser("check", help="validate every stored value against its declared schema")
    # H006 — the rest of `hermes config`: an editor over the declared settings, the files,
    # and a migration an operator can read before a boot applies it.
    config_edit = config_verbs.add_parser(
        "edit", help="open every editable setting in $VISUAL/$EDITOR, then write back only what changed")
    _selection_flags(config_edit)
    config_path = config_verbs.add_parser(
        "path", help="the data root and the settings store these verbs use (the hub's, in the same environment)")
    config_path.add_argument("--json", action="store_true")
    config_env_path = config_verbs.add_parser(
        "env-path", help="the .env files and the secret store the hub reads — names only, never a value")
    config_env_path.add_argument("--json", action="store_true")
    config_migrate = config_verbs.add_parser(
        "migrate", help="write this build's new defaults and retired-model replacements into an existing store")
    config_migrate.add_argument("--dry-run", action="store_true", help="print what would change; change nothing")
    config_migrate.add_argument("--json", action="store_true")
    # G1 (H249/H267/H629) — what an administrator pinned, and whether writes are refused.
    config_managed = config_verbs.add_parser(
        "managed", help="the settings and environment values your administrator pinned (names, never a value)")
    config_managed.add_argument("--json", action="store_true")

    approvals = verbs.add_parser("approvals", help="the approval queue (admin)")
    approvals_verbs = approvals.add_subparsers(dest="action", required=True, metavar="action")
    approvals_list = approvals_verbs.add_parser("list", help="pending decisions")
    approvals_list.add_argument("--json", action="store_true")
    for decision in ("accept", "reject", "defer", "edit"):
        decide = approvals_verbs.add_parser(decision, help=f"{decision} one pending task")
        decide.add_argument("task_id", type=int)
        decide.add_argument("--payload", help="JSON object attached to the decision")
        decide.add_argument("--reason", help="optional human decision reason (at most 280 characters)")
        decide.add_argument("--json", action="store_true")
    consent = approvals_verbs.add_parser("consent", help="decide an exact reusable terminal offer (owner)")
    consent.add_argument("task_id", type=int, metavar="TASK_ID")
    consent.add_argument("--choice", required=True, choices=("session", "always", "deny"))
    consent.add_argument("--revision", required=True, help="the exact 64-character offer revision from approvals list")
    consent.add_argument("--reason", help="optional human decision reason (at most 280 characters)")
    consent.add_argument("--json", action="store_true")
    # H484 — the approval dial. No `choices=`: Hermes' words (manual, smart) are read too,
    # and an unknown word is refused before the hub is asked.
    approvals_mode = approvals_verbs.add_parser(
        "mode", help="show or set how much runs without asking: auto|ask|off (owner)")
    approvals_mode.add_argument("value", nargs="?", metavar="auto|ask|off")
    approvals_mode.add_argument("--json", action="store_true")

    curator = verbs.add_parser("curator", help="review and request owner-governed skill curation")
    curator_verbs = curator.add_subparsers(dest="action", required=True, metavar="action")
    for action in ("status", "usage", "list-unmanaged", "list-archived", "ledger"):
        read = curator_verbs.add_parser(action, help=f"read curator {action}")
        read.add_argument("--json", action="store_true")
        if action in {"usage", "list-unmanaged", "list-archived", "ledger"}:
            read.add_argument("--limit", type=int, metavar="N")
        if action == "usage":
            read.add_argument("--origin", choices=("agent", "import", "bundled", "unknown"))
            read.add_argument("--sort", choices=("activity", "recent", "name"))
        if action == "ledger":
            read.add_argument("--name", metavar="SKILL")
    for action in ("run", "pause", "resume", "pin", "unpin", "adopt", "restore",
                   "archive", "prune", "backup", "rollback", "purge"):
        change = curator_verbs.add_parser(action, help=f"preview or request curator {action}")
        change.add_argument("--json", action="store_true")
        change.add_argument("--dry-run", action="store_true", help="preview only; create no approval card")
        change.add_argument("--preview-fingerprint", metavar="SHA256",
                            help="refuse if the current preview differs from an earlier review")
        change.add_argument("--yes", action="store_true",
                            help="acknowledge the request; owner approval and kernel checks still apply")
        if action in {"pin", "unpin", "archive", "restore"}:
            change.add_argument("name" if action != "restore" else "archive_id")
        elif action == "adopt":
            change.add_argument("name", nargs="?")
            change.add_argument("--all-unmanaged", action="store_true")
        elif action in {"prune", "purge"}:
            change.add_argument("--days", type=int, metavar="DAYS")
            if action == "purge":
                change.add_argument("--archive-id", action="append", dest="archive_ids", metavar="ID")
        elif action == "backup":
            change.add_argument("--reason", metavar="TEXT")
        elif action == "rollback":
            select = change.add_mutually_exclusive_group()
            select.add_argument("--ledger-id", metavar="ID")
            select.add_argument("--backup-id", metavar="ID")
            select.add_argument("--list", action="store_true", help="show available verified backups")
        elif action == "run":
            change.add_argument("--consolidate", action="store_true",
                                help="apply already owner-approved skill proposals after the run")
            change.add_argument("--background", action="store_true",
                                help="return after queuing the owner review card")

    checkpoints = verbs.add_parser("checkpoints", help="owner checkpoint inventory and maintenance")
    checkpoint_verbs = checkpoints.add_subparsers(dest="action", metavar="action")
    for action in ("status", "list"):
        query = checkpoint_verbs.add_parser(action, help="show checkpoint storage and projects")
        query.add_argument("--project", metavar="ROOT")
        query.add_argument("--limit", type=int, metavar="N")
    diff = checkpoint_verbs.add_parser("diff", help="preview one checkpoint's bounded diff")
    diff.add_argument("identifier", metavar="ID")
    diff.add_argument("--project", metavar="ROOT")
    restore = checkpoint_verbs.add_parser("restore", help="preview or request an approved restore")
    restore.add_argument("identifier", metavar="ID")
    restore.add_argument("--project", metavar="ROOT")
    restore.add_argument("--path", dest="paths", action="append", metavar="REL")
    restore_mode = restore.add_mutually_exclusive_group()
    restore_mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    restore_mode.add_argument("--execute", action="store_true", help="request governed approval")
    restore.add_argument("--force", action="store_true",
                         help="preview or request an owner overwrite; never bypass approval")
    for action in ("prune", "clear", "clear-legacy"):
        change = checkpoint_verbs.add_parser(action, help="preview or request owner approval")
        if action == "prune":
            change.add_argument("--project", metavar="ROOT")
            change.add_argument("--keep-last", type=int, metavar="N")
            change.add_argument("--max-bytes", type=int, metavar="BYTES")
            change.add_argument("--include-orphans", action="store_true")
        mode = change.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
        mode.add_argument("--execute", action="store_true", help="request governed approval")
        change.add_argument("--force", action="store_true",
                            help="bind the legacy owner intent; does not change selection or approval")

    backup = verbs.add_parser("backup", help="back up and restore the whole install (H010)")
    backup_verbs = backup.add_subparsers(dest="action", required=True, metavar="action")
    backup_create = backup_verbs.add_parser("create", help="snapshot the data root (offline, same data root)")
    backup_create.add_argument("--quick", action="store_true",
                               help="only the state DBs: a small, fast rollback point")
    backup_create.add_argument("--encrypt", action="store_true",
                               help="encrypt at rest ($JARVIS_BACKUP_KEY, else a generated key in $JARVIS_KEY_DIR)")
    backup_create.add_argument("--label", default="")
    backup_create.add_argument("--json", action="store_true")
    backup_list = backup_verbs.add_parser("list", help="snapshots, a staged restore and the last one applied (offline)")
    backup_list.add_argument("--json", action="store_true")
    backup_verify = backup_verbs.add_parser("verify", help="restore-drill a snapshot without touching live data (offline)")
    backup_verify.add_argument("name", nargs="?", help="backup file name (default: the newest)")
    backup_verify.add_argument("--json", action="store_true")
    backup_restore = backup_verbs.add_parser(
        "restore", help="restore a snapshot over the live data root (irreversible tier)")
    backup_restore.add_argument("name", help="backup file name (see `nerva backup list`)")
    backup_restore.add_argument("--confirm", metavar="RESTORE", default="",
                                help="with no hub running: type RESTORE to restore in place now")
    backup_restore.add_argument("--json", action="store_true")
    backup_cancel = backup_verbs.add_parser(
        "cancel", help="withdraw a staged restore before it is applied (offline, same data root)")
    backup_cancel.add_argument("--json", action="store_true")

    kernel = verbs.add_parser("kernel", help="the Action Kernel")
    kernel_verbs = kernel.add_subparsers(dest="action", required=True, metavar="action")
    explain = kernel_verbs.add_parser(
        "explain",
        help="replay the real gates for an action without executing it (offline)",
    )
    explain.add_argument("kind", help="action kind, e.g. writeback.notion.page or payment.send")
    explain.add_argument("--title", default="")
    explain.add_argument("--payload", help="JSON object: target, amount, url, …")
    explain.add_argument("--tier", type=int, help="explicit risk tier 0-3 (else classified)")
    explain.add_argument("--json", action="store_true")

    tools = verbs.add_parser("tools", help="what the tool loop just did (admin)")
    tools.add_argument("-n", "--lines", type=int, default=20, help="how many events")
    tools.add_argument("--agent", help="only this agent's events")
    tools.add_argument("--untrusted", action="store_true",
                       help="only the results that were fenced as untrusted data")
    tools.add_argument("--json", action="store_true")

    # H227 — what an agent can do right now, as a principal sees it (admin, read-only).
    inspect = verbs.add_parser("inspect", help="what an agent can do right now: status, tools, "
                               "skills, MCP servers and its resolved prompt (admin)")
    inspect.add_argument("agent", nargs="?", default="jarvis")
    inspect.add_argument("--as", dest="view", choices=INSPECT_VIEWS, default="owner",
                         help="whose turn: the owner or a guest on the HUD, the owner or a "
                              "stranger on an external channel, or no human (internal)")
    inspect.add_argument("--section", choices=tuple(INSPECT_SECTIONS), help="only this section")
    inspect.add_argument("--json", action="store_true")

    logs = verbs.add_parser("logs", help="the newest records of the hub log, read from the end "
                            "and redacted (offline; -n counts records, a traceback is one)")
    logs.add_argument("name", nargs="?", help="exact configured log basename or numbered rotation; "
                      "'list' shows available files (use --name to read a file named 'list')")
    logs.add_argument("--name", dest="exact_name", help="exact configured log basename, including 'list'")
    logs.add_argument("-n", "--lines", type=int, default=50)

    skills = verbs.add_parser("skills", help="skill authoring tools (offline)")
    skills_verbs = skills.add_subparsers(dest="action", required=True, metavar="action")
    skills_lint = skills_verbs.add_parser(
        "lint", help="check SKILL.md files: an error is what every write refuses, advice is not enforced")
    skills_lint.add_argument("paths", nargs="+", metavar="path",
                             help="a SKILL.md, a skill folder, or a folder of skill folders")
    skills_lint.add_argument("--strict", action="store_true", help="advice fails the run too")
    skills_lint.add_argument("--json", action="store_true")
    # H329 — switched off, not uninstalled; enabling waits for approval.
    skills_verbs.add_parser("list", help="installed skills and where each is switched off").add_argument(
        "--json", action="store_true")
    skills_verbs.add_parser("config", help="interactively switch a skill or category on/off")
    for verb, text in (("off", "switch a skill off without uninstalling it (admin)"),
                       ("on", "request owner approval to switch a skill back on (admin)")):
        switch = skills_verbs.add_parser(verb, help=text)
        switch.add_argument("name", nargs="?", help="the skill's name or folder")
        switch.add_argument("--category", help="every skill of this category instead of one skill")
        switch.add_argument("--bundle", help="every installed skill of this bundle instead of one skill")
        switch.add_argument("--channel", help="only on this channel (telegram, voice, web, ...)")
        switch.add_argument("--json", action="store_true")
    # H349 — the owner's pin: the curator leaves a pinned skill alone, and an agent's batch
    # and the journey's forget refuse to delete it; the owner's own removals are not blocked.
    for verb, text in (("pin", "pin a skill: never aged out by the curator, never deleted by an agent's "
                               "batch or the journey's forget (admin)"),
                       ("unpin", "remove a skill's pin (admin)")):
        pin = skills_verbs.add_parser(verb, help=text)
        pin.add_argument("name", help="the skill's name or folder, as `nerva skills list` shows it")
        pin.add_argument("--json", action="store_true")
    # H026 — named groups of skills, switched off/on as one unit with --bundle.
    bundles = skills_verbs.add_parser(
        "bundles", help="named groups of skills, switched as one unit (`nerva skills off|on --bundle`) "
                        "or loaded into a chat turn with /<bundle>; with no action, the list")
    bundle_verbs = bundles.add_subparsers(dest="bundle_action", required=False, metavar="action")
    bundle_verbs.add_parser("list", help="every bundle, its skills and which are not installed").add_argument(
        "--json", action="store_true")
    bundle_show = bundle_verbs.add_parser("show", help="one bundle's skills")
    bundle_show.add_argument("name", help="the bundle's name (any casing; spaces and _ read as -)")
    bundle_show.add_argument("--json", action="store_true")
    bundle_create = bundle_verbs.add_parser(
        "create", help="create a bundle of installed skills; it switches nothing (admin). Skills come "
                       "from --skill, or are asked for one a line on a terminal when there is none")
    bundle_create.add_argument("name", help="the bundle's name (/<its slug> loads it in chat)")
    bundle_create.add_argument("--skill", "-s", action="append", default=[], metavar="SKILL",
                               help="an installed skill's name or folder, or its path below the skills "
                                    "folder as Hermes writes one (productivity/maps); repeat for each")
    bundle_create.add_argument("--description", "-d", default="")
    bundle_create.add_argument("--instruction", "-i", default=None,
                               help="extra guidance put before the skills when the bundle is loaded; "
                                    "omitted, a replaced bundle keeps its own (\"\" drops it)")
    bundle_create.add_argument("--force", "-f", action="store_true",
                               help="replace the bundle of that name (only its own file is replaced)")
    bundle_create.add_argument("--json", action="store_true")
    bundle_delete = bundle_verbs.add_parser(
        "delete", help="delete a bundle; its skills and their switches are untouched (admin)")
    bundle_delete.add_argument("name", help="the bundle's name")
    bundle_delete.add_argument("--json", action="store_true")
    bundle_verbs.add_parser(
        "reload", help="re-read the bundle files and report what changed (admin)").add_argument(
        "--json", action="store_true")
    # H336 — Hermes's optional-skills catalog, vendored inert: browse, install, repair.
    catalog = skills_verbs.add_parser(
        "catalog", help="the vendored Hermes skill catalog: with no action, browse it (at most 100 rows, "
                        "like `hermes skills browse`); install or repair one skill (admin)")
    catalog.add_argument("--search", "-q", default="", help="text in the slug, name, category, description or tags")
    catalog.add_argument("--category", "-c", default="", help="only this category (mlops, creative, ...)")
    catalog.add_argument("--kind", choices=("instruction", "upstream_only", "excluded"), default="",
                         help="instruction (installable), upstream_only (carries code) or excluded")
    catalog.add_argument("--limit", "-n", type=int, default=100, help="at most this many rows (1-100)")
    catalog.add_argument("--json", action="store_true")
    catalog_verbs = catalog.add_subparsers(dest="catalog_action", required=False, metavar="action")
    catalog_install = catalog_verbs.add_parser(
        "install", help="install one instruction skill from the catalog; works without DEV_MODE (admin)")
    catalog_install.add_argument("skill", help="<category>/<skill>, official/<category>/<skill> or the slug")
    catalog_install.add_argument("--json", action="store_true")
    catalog_repair = catalog_verbs.add_parser(
        "repair", help="restore an installed catalog skill's deleted or edited files from the vendored "
                       "bytes (admin)")
    catalog_repair.add_argument("skill", help="<category>/<skill> or the slug")
    catalog_repair.add_argument("--force", "-f", action="store_true",
                                help="also replace files you edited (a copy of each is kept on the hub)")
    catalog_repair.add_argument("--json", action="store_true")
    # H354 — the owner's trigger for one skill's reality-harness case.
    verify = skills_verbs.add_parser(
        "verify", help="run the reality harness's case for one loaded skill on the hub, now (admin)")
    verify.add_argument("name", help="the skill's name as `nerva skills list` shows it")
    verify.add_argument("--json", action="store_true")

    estop = verbs.add_parser("estop", help="the global emergency stop")
    estop_verbs = estop.add_subparsers(dest="action", required=True, metavar="action")
    estop_verbs.add_parser("status", help="is it engaged, since when, why")
    engage = estop_verbs.add_parser("engage", help="pause new autonomous work (admin)")
    engage.add_argument("--reason", default="")
    estop_verbs.add_parser("resume", help="lift the emergency stop (admin)")

    company = verbs.add_parser("company", help="company-mode work runs (user)")
    company_verbs = company.add_subparsers(dest="action", required=True, metavar="action")
    company_list = company_verbs.add_parser("list", help="every run and its honest headline")
    company_list.add_argument("--json", action="store_true")
    clear_wait = company_verbs.add_parser(
        "clear-wait", help="let a parked run go: clear what it is waiting on (H464)")
    clear_wait.add_argument("run_id")
    clear_wait.add_argument("--json", action="store_true")

    goal = verbs.add_parser("goal", help="propose a goal for a work run, or add a criterion to one (H462)")
    goal_verbs = goal.add_subparsers(dest="action", required=True, metavar="action")
    goal_propose = goal_verbs.add_parser(
        "propose", help="send a goal to the decision inbox; nothing runs until you approve it (admin)")
    goal_propose.add_argument(
        "lines", nargs="+", metavar="line",
        help="the goal: a headline, then optional 'verify: ...', 'scope: ...', 'step: <kind>: ...', "
             "'must not: ...', 'stop when: ...' lines, one per argument; '-' reads them from stdin")
    goal_propose.add_argument("--json", action="store_true")
    goal_subgoal = goal_verbs.add_parser(
        "subgoal", help="add an acceptance criterion to a running goal; it resets nothing (user)")
    goal_subgoal.add_argument("run_id")
    goal_subgoal.add_argument("criterion", nargs="+")
    goal_subgoal.add_argument("--json", action="store_true")

    pairing = verbs.add_parser("pairing", help="who may talk to the agent over a DM channel (admin, H051)")
    pairing_verbs = pairing.add_subparsers(dest="action", required=True, metavar="action")
    pairing_list = pairing_verbs.add_parser("list", help="every sender the pairing store knows, and its status")
    pairing_list.add_argument("--status", choices=_PAIRING_STATUSES, help="only senders with this status")
    pairing_list.add_argument("--json", action="store_true")
    pairing_approve = pairing_verbs.add_parser("approve", help="let one sender through (pending, blocked or new)")
    pairing_approve.add_argument("channel")
    pairing_approve.add_argument("sender_id")
    pairing_approve.add_argument("--name", default="", help="a label for the sender")
    pairing_approve.add_argument("--json", action="store_true")
    pairing_revoke = pairing_verbs.add_parser(
        "revoke", help="forget one sender: an approved one loses access, a blocked one may ask again")
    pairing_revoke.add_argument("channel")
    pairing_revoke.add_argument("sender_id")
    pairing_revoke.add_argument("--json", action="store_true")
    pairing_clear = pairing_verbs.add_parser(
        "clear-pending", help="drop every pending request (nobody is blocked); a preview without --confirm")
    pairing_clear.add_argument("--confirm", action="store_true", help="actually drop them")
    pairing_clear.add_argument("--json", action="store_true")

    hooks = verbs.add_parser(
        "hooks", help="owner event hooks: programs that run on agent events, each behind an approval card (admin, G17)")
    hooks_verbs = hooks.add_subparsers(dest="action", required=True, metavar="action")
    hooks_list = hooks_verbs.add_parser(
        "list", aliases=["ls"], help="every hook with its event, state and last run, and whether hooks can run here")
    hooks_list.add_argument("--json", action="store_true")
    hooks_add = hooks_verbs.add_parser(
        "add", help="define a hook: queues an approval card showing the exact command; nothing runs until accepted")
    hooks_add.add_argument("event", help="tool.before, tool.after, message.received, turn.completed, "
                                         "session.started, session.ended, command.completed, "
                                         "approval.requested or approval.decided")
    hooks_add.add_argument("argv", nargs="+",
                           help="the program (absolute path) and its fixed arguments; put -- before them")
    hooks_add.add_argument("--matcher", help="tool events only: a tool name or glob (terminal_*)")
    hooks_add.add_argument("--guard", action="store_true",
                           help="tool.before only: if the hook fails, block the call (fail closed)")
    hooks_add.add_argument("--timeout", type=int, help="seconds before the hook is killed")
    hooks_add.add_argument("--name", help="a label")
    hooks_add.add_argument("--replaces", help="the id of a hook this one replaces once accepted")
    hooks_add.add_argument("--json", action="store_true")
    for verb, text in (("disable", "switch a hook off now (no card)"),
                       ("enable", "turn a switched-off hook back on, or re-approve changed files (queues an approval card)"),
                       ("remove", "delete a hook now (no card)")):
        sub = hooks_verbs.add_parser(verb, aliases=["rm"] if verb == "remove" else [], help=text)
        sub.add_argument("hook_id")
        sub.add_argument("--json", action="store_true")
    hooks_test = hooks_verbs.add_parser(
        "test", help="run one active hook once against a synthetic event (audited as a test)")
    hooks_test.add_argument("hook_id")
    hooks_test.add_argument("--tool", default="terminal_run", help="the tool name in the synthetic event")
    hooks_test.add_argument("--payload-file", help="a JSON object used as the synthetic tool_input")
    hooks_test.add_argument("--json", action="store_true")
    hooks_verbs.add_parser("doctor", help="check every hook: files unchanged since approval, and the blockers")

    memory = verbs.add_parser(
        "memory", help="the long-term memory every prompt carries: what it holds, reset it, switch it off (H422)")
    memory_verbs = memory.add_subparsers(dest="action", metavar="action")
    memory_status = memory_verbs.add_parser(
        "status", help="is memory on, and what the agent notes and the user profile hold (the default)")
    memory_status.add_argument("--json", action="store_true")
    memory_reset = memory_verbs.add_parser(
        "reset", help="erase the agent notes, the user profile or both, for good (admin)")
    memory_reset.add_argument("--target", choices=_MEMORY_RESET_TARGETS, default="all",
                              help="which store to erase: all (default), memory (the agent notes) or user")
    memory_reset.add_argument("--yes", "-y", action="store_true", help="skip the typed confirmation")
    memory_reset.add_argument("--json", action="store_true")
    memory_off = memory_verbs.add_parser(
        "off", help="take the curated memory out of every prompt, whatever the posture; nothing is erased (admin)")
    memory_off.add_argument("--json", action="store_true")
    memory_on = memory_verbs.add_parser(
        "on", help="bring the curated memory back into the prompt after `nerva memory off` (admin)")
    memory_on.add_argument("--json", action="store_true")

    agents = verbs.add_parser(
        "agents", help="the owner's roster: create, rename, retire and restore agents (admin, H202)")
    agent_verbs = agents.add_subparsers(dest="action", metavar="action")
    agents_list = agent_verbs.add_parser(
        "list", help="every agent, active and retired, and what the owner changed (the default)")
    agents_list.add_argument("--json", action="store_true")
    agents_create = agent_verbs.add_parser(
        "create", help="create an agent from a template or blank, kept across restarts")
    agents_create.add_argument("name", help="the display name")
    agents_create.add_argument("--template", default="",
                               help="a template key (nerva agents list shows them); default: blank")
    agents_create.add_argument("--id", dest="agent_id", default="", help="the agent id; default: from the name")
    agents_create.add_argument("--tier", default="", choices=("", *_AGENT_TIERS),
                               help="the roster tier; default: the template's")
    agents_create.add_argument("--json", action="store_true")
    agents_rename = agent_verbs.add_parser("rename", help="give an agent a new display name for good; the id stays")
    agents_rename.add_argument("agent_id")
    agents_rename.add_argument("name")
    agents_rename.add_argument("--json", action="store_true")
    agents_retire = agent_verbs.add_parser(
        "retire", help="take an agent out of the hub; nothing is deleted and restore brings it back")
    agents_retire.add_argument("agent_id")
    agents_retire.add_argument("--reason", default="", help="why, kept with the roster entry")
    agents_retire.add_argument("--yes", "-y", action="store_true", help="skip the typed confirmation")
    agents_retire.add_argument("--json", action="store_true")
    agents_restore = agent_verbs.add_parser("restore", help="bring a retired agent back as it was")
    agents_restore.add_argument("agent_id")
    agents_restore.add_argument("--json", action="store_true")


    # H046 — Hermes's `hermes journey` (aliases `learning`, `memory-graph`): the learning
    # timeline the HUD's TODAY card reads, every learned entry with its id, and one of them
    # edited or forgotten by that id.
    journey = verbs.add_parser(
        "journey", aliases=list(_JOURNEY_ALIASES),
        help="look back at what the assistant did and learned: the timeline (the default), every "
             "learned entry with its id, and one edited or forgotten by its id (reads: user; writes: admin)")
    journey.add_argument("--days", type=_bounded_int(1, 30), metavar="1-30", default=_JOURNEY_DAYS,
                         help=f"how far back the timeline looks (default {_JOURNEY_DAYS}, the most it serves)")
    journey.add_argument("--kind", choices=("action", "learning", "followup"),
                         help="only one kind of timeline entry (learning: only what it learned)")
    journey.add_argument("--limit", type=_bounded_int(1, 500), metavar="1-500", default=_JOURNEY_LIMIT,
                         help=f"at most this many timeline entries, newest first (default {_JOURNEY_LIMIT})")
    journey.add_argument("--json", action="store_true")
    journey_verbs = journey.add_subparsers(dest="action", metavar="action")
    # A sub-verb's --json must not reset the verb's own (`nerva journey --json list`).
    journey_list = journey_verbs.add_parser(
        "list", help="every learned entry, whatever its age, oldest first, each with the id show/edit/"
                     "delete take: the agent's notes, the user profile, the skills it learned, stored facts")
    journey_list.add_argument("--store", choices=_JOURNEY_STORES, help="only one store")
    journey_list.add_argument("--limit", dest="list_limit", type=_bounded_int(1, 5000), metavar="1-5000",
                              default=None, help="only the newest this many (default: every one, up to 5000)")
    journey_list.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    journey_show = journey_verbs.add_parser("show", help="one learned entry, whatever its age (a skill: its SKILL.md)")
    journey_show.add_argument("entry", help=_JOURNEY_ENTRY_HELP)
    journey_show.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    journey_delete = journey_verbs.add_parser(
        "delete", help="forget one learned entry (a skill is archived, recoverable; one awaiting review is "
                       "discarded); admin, crosses kg.write")
    journey_delete.add_argument("entry", help=_JOURNEY_ENTRY_HELP)
    journey_delete.add_argument("--yes", "-y", action="store_true", help="skip the typed confirmation")
    journey_delete.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    journey_edit = journey_verbs.add_parser(
        "edit", help="change what one learned entry says (a skill: its SKILL.md) in $VISUAL/$EDITOR, or "
                     "--text; admin, crosses kg.write")
    journey_edit.add_argument("entry", help=_JOURNEY_ENTRY_HELP)
    journey_edit.add_argument("--text", metavar="TEXT",
                              help="the new text, without opening an editor ('-' reads it from stdin)")
    journey_edit.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    webhook = verbs.add_parser("webhook", help="inbound webhooks: subscribe an external system's events to an agent (admin, H039)")
    webhook_verbs = webhook.add_subparsers(dest="action", required=True, metavar="action")
    webhook_subscribe = webhook_verbs.add_parser(
        "subscribe", help="create a hook that runs an agent or workflow on each delivery; its credential is shown once")
    webhook_subscribe.add_argument("target", help="the agent or workflow id the hook runs")
    webhook_subscribe.add_argument("--type", dest="target_type", choices=("agent", "workflow"), default="agent")
    webhook_subscribe.add_argument("--name", default="", help="a label for the hook (default: the target)")
    webhook_subscribe.add_argument("--signed", action="store_true",
                                   help="HMAC-signed deliveries (X-Signature-256 over the raw body) instead of a token")
    webhook_subscribe.add_argument("--events", default="",
                                   help="comma-separated event names the hook runs, e.g. push,issues (empty: every event)")
    webhook_subscribe.add_argument("--prompt", default="",
                                   help="prompt template over the payload, e.g. '{event} on {repository.full_name}'")
    webhook_subscribe.add_argument("--deliver", choices=_WEBHOOK_DESTINATIONS, default="log",
                                   help="where the reply goes: the log, or one of your own channels")
    webhook_subscribe.add_argument("--deliver-only", action="store_true",
                                   help="skip the agent: the rendered text goes straight to the channel")
    webhook_subscribe.add_argument("--description", default="")
    webhook_subscribe.add_argument("--filter", default=None,
                                   help='JSON list of rules every delivery must satisfy, e.g. \'[{"path": "ref", "op": "eq", '
                                        '"value": "refs/heads/main"}]\'; ops: eq ne contains startswith endswith glob in exists missing')
    webhook_subscribe.add_argument("--json", action="store_true")
    webhook_list = webhook_verbs.add_parser("list", help="every hook, its credential kind, switch, calls and filter")
    webhook_list.add_argument("--json", action="store_true")
    webhook_remove = webhook_verbs.add_parser("remove", help="delete a hook: the sender's token or secret dies with it")
    webhook_remove.add_argument("hook_id")
    webhook_remove.add_argument("--json", action="store_true")
    webhook_test = webhook_verbs.add_parser(
        "test", help="send a correctly signed sample delivery through the hook's receive path, dry, and show the outcome")
    webhook_test.add_argument("hook_id")
    webhook_test.add_argument("--event", default="", help="the event the sample names (default: the hook's first subscribed event)")
    webhook_test.add_argument("--payload", default=None, help="a JSON object to send instead of the built-in sample")
    webhook_test.add_argument("--json", action="store_true")

    jobs = verbs.add_parser("jobs", help="your scheduled jobs (admin)")
    jobs_verbs = jobs.add_subparsers(dest="action", required=True, metavar="action")
    jobs_list = jobs_verbs.add_parser("list", help="every job and whether the scheduler is alive")
    jobs_list.add_argument("--json", action="store_true")
    jobs_verbs.add_parser("blueprints", help="one-tap job templates")
    jobs_create = jobs_verbs.add_parser("create", help="arm a job from a blueprint or from parts")
    jobs_create.add_argument("--blueprint", help="blueprint id (see `nerva jobs blueprints`)")
    jobs_create.add_argument("--param", action="append", default=[], metavar="KEY=VALUE", help="blueprint parameter")
    jobs_create.add_argument("--name")
    jobs_create.add_argument("--when", help="plain words ('every weekday at 7') or a five-field cron")
    # dest differs from the subparser's own `action` dest, which an option default would clobber.
    jobs_create.add_argument("--action", dest="action_json", help='JSON, e.g. {"type":"remind","message":"stand up"}')
    jobs_create.add_argument("--first-run", dest="first_run", action=argparse.BooleanOptionalAction, default=None,
                             help="fire once now whatever the schedule (--no-first-run: never); by default only an "
                                  "interval job fires at once")
    jobs_create.add_argument("--json", action="store_true")
    jobs_create.add_argument("--toolsets", help="model ask: default, none, or comma-separated installed IDs from jobs doctor; requires complete --options")
    jobs_create.add_argument("--reasoning-effort", choices=("default", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
                             help="model ask: one canonical reasoning effort or default; requires complete --options")
    jobs_create.add_argument("--workdir", help="script-only cwd; requires complete --options with script and no_agent true")
    jobs_create.add_argument("--media-id", action="append", help="opaque artifact ID for an explicit reminder action; repeat up to 8 times")
    jobs_create.add_argument("--options", help='JSON options: repeat, deliver ([] disables delivery); ask jobs accept model/provider pins (configured route only; deterministic compression, no embedding recall)')
    create_continuity = jobs_create.add_mutually_exclusive_group()
    create_continuity.add_argument("--continuity", dest="continuity", action="store_true", default=None,
                                   help="include previous model output on later runs")
    create_continuity.add_argument("--no-continuity", dest="continuity", action="store_false",
                                   help="omit previous model output on later runs")
    jobs_create.add_argument("--context-from", action="append", metavar="ID",
                             help="include the latest eligible output of this job; repeat for up to eight IDs or self")
    _selection_flags(jobs_create)
    jobs_edit = jobs_verbs.add_parser("edit", help="change an existing job's name, schedule or action")
    jobs_edit.add_argument("job_id")
    jobs_edit.add_argument("--name")
    jobs_edit.add_argument("--when", help="plain words ('every weekday at 7') or a five-field cron")
    jobs_edit.add_argument("--action", dest="action_json", help='JSON, e.g. {"type":"remind","message":"stand up"}')
    jobs_edit.add_argument("--json", action="store_true")
    jobs_edit.add_argument("--toolsets", help="model ask: default, none, or comma-separated installed IDs from jobs doctor; requires complete --options")
    jobs_edit.add_argument("--reasoning-effort", choices=("default", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
                           help="model ask: one canonical reasoning effort or default; requires complete --options")
    jobs_edit.add_argument("--workdir", help="script-only cwd; requires complete --options; empty clears the field")
    jobs_edit.add_argument("--media-id", action="append", help="replace reminder attachments; requires --action and explicitly reauthorizes content/owner")
    jobs_edit.add_argument("--options", help="replace advanced options as JSON; model/provider pins use deterministic compression and omit embedding recall")
    edit_continuity = jobs_edit.add_mutually_exclusive_group()
    edit_continuity.add_argument("--continuity", dest="continuity", action="store_true", default=None,
                                 help="include previous model output on later runs")
    edit_continuity.add_argument("--no-continuity", dest="continuity", action="store_false",
                                 help="omit previous model output on later runs")
    edit_context = jobs_edit.add_mutually_exclusive_group()
    edit_context.add_argument("--context-from", action="append", metavar="ID",
                              help="replace external context sources; repeat for up to eight IDs or self")
    edit_context.add_argument("--clear-context-from", action="store_true",
                              help="clear external context sources without replacing other options")
    _selection_flags(jobs_edit)
    for verb, help_text in (("doctor", "scheduler health; exit 1 when it reports a problem"),
                            ("tick", "run one scheduler pass now")):
        sub = jobs_verbs.add_parser(verb, help=help_text)
        sub.add_argument("--json", action="store_true")
    incidents = jobs_verbs.add_parser("incidents", help="list or acknowledge durable job failures")
    incidents.add_argument("operation", nargs="?", choices=("list", "ack"), default="list")
    incidents.add_argument("incident_id", nargs="?", type=int)
    incidents.add_argument("--state", choices=("detected", "alerted", "closed"))
    incidents.add_argument("--job-id")
    incidents.add_argument("--limit", type=int)
    incidents.add_argument("--json", action="store_true")
    notepad = jobs_verbs.add_parser("notepad", help="read legacy note or manage named job notes")
    notepad.add_argument("job_id")
    notepad.add_argument("operation", nargs="?", choices=("list", "get", "set", "delete"), default="list")
    notepad.add_argument("key", nargs="?")
    notepad.add_argument("value", nargs="?")
    notepad.add_argument("--text", help="replacement text; an empty string clears notes")
    notepad.add_argument("--json", action="store_true")
    for name, help_text in (
        ("status", "job configuration and recent runs"),
        ("remove", "remove a job but retain its run history"),
        ("pause", "stop a job from firing"),
        ("resume", "let a paused job fire again"),
        ("run", "fire a job now, even if paused"),
        ("delete", "remove a job but retain its run history"),
    ):
        sub = jobs_verbs.add_parser(name, help=help_text)
        sub.add_argument("job_id")
        sub.add_argument("--json", action="store_true")
        if name == "pause":
            sub.add_argument("--reason", default="")
        if name == "status":
            sub.add_argument("--request", help="durable manual-run receipt id")
    runs = jobs_verbs.add_parser("runs", help="recent attempts, including deleted jobs")
    runs.add_argument("job_id", nargs="?")
    runs.add_argument("--limit", type=int)
    runs.add_argument("--json", action="store_true")

    todo = verbs.add_parser("todo", help="the checklists the agent keeps while it works")
    todo.add_argument("session", nargs="?", help="one session's plan (else the recent ones)")
    todo.add_argument("--json", action="store_true")

    sessions = verbs.add_parser("sessions", help="recent conversation sessions")
    sessions.add_argument("--json", action="store_true")
    session_verbs = sessions.add_subparsers(dest="session_action")
    continuation = session_verbs.add_parser("continue", help="create a new session carrying retained context; does not switch default")
    continuation.add_argument("source_session_id")
    continuation.add_argument("--request-id", required=True, help="stable UUID for safe retry")
    continuation.add_argument("--json", action="store_true")
    imported = session_verbs.add_parser("import", help="import a local Claude Code/Codex JSONL conversation")
    imported.add_argument("--from", dest="foreign_source", choices=("claude", "codex"), required=True)
    imported.add_argument("path", help="owner-selected local JSONL path")
    imported.add_argument("--json", action="store_true")
    # H652 — the session's saved full turns as training data (admin; capture is opt-in).
    exported = session_verbs.add_parser(
        "export", help="the session's saved full turns (tool calls and results kept) as JSONL training data")
    exported.add_argument("session_id")
    exported.add_argument("--format", dest="export_format", choices=("sharegpt", "messages"), default="sharegpt",
                          help="sharegpt: Hermes conversations of from/value (default); messages: OpenAI chat rows")
    exported.add_argument("--sharegpt", dest="export_format", action="store_const", const="sharegpt",
                          help="same as --format sharegpt")
    exported.add_argument("--completed-only", action="store_true",
                          help="only turns that ended on the model's own answer")
    exported.add_argument("-o", "--out", default="-", help="output JSONL path ('-' = stdout)")
    exported.add_argument("--json", action="store_true")

    chat = verbs.add_parser(
        "chat",
        help="one scripted turn: send a message, print the reply (scripts, cron, CI)",
        description="One turn in, one answer out. The message is the MESSAGE argument, else "
                    "--file PATH (- reads stdin), else whatever is piped on stdin; a terminal is "
                    "never read for the message. With -z the answer is the ONLY thing on stdout and every "
                    "diagnostic goes to stderr, so the command composes in a pipeline. A turn that "
                    "did not complete — one that queued an approval, was refused, or came back "
                    "empty — prints nothing on stdout and exits non-zero. Exit 0 answered · 1 the "
                    "turn did not complete · 2 usage · 3 no hub · 4 not authorised · 130 "
                    "interrupted.",
        epilog="examples:\n"
               "  nerva chat -z \"what is on my calendar?\"\n"
               "  echo \"summarise this\" | nerva chat -z --usage-file spend.json\n"
               "  nerva chat -z -f prompt.txt --agent athena\n"
               "  nerva chat -z --image screenshot.png \"what does this error say?\"\n"
               "\n"
               "This verb never auto-approves. If the turn queues an action for approval it\n"
               "stays queued: stdout is empty, the exit code is 1, and stderr names what to\n"
               "decide with `nerva approvals`.\n"
               "\n"
               "Run from a terminal (stdin not piped), the turn's questions are asked right\n"
               "here while it runs: a clarify question, a missing secret (typed without echo,\n"
               "stored only in the hub's secret store) and, after the turn, each approval card\n"
               "it queued (accept, reject, defer, or leave it queued). --no-prompts turns this off.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    chat.add_argument("message", nargs="?",
                      help="the message; omit it to read --file or stdin")
    chat.add_argument("-f", "--file", metavar="PATH",
                      help="read the message from PATH, or from stdin when PATH is -")
    chat.add_argument("-z", "--oneshot", action="store_true",
                      help="only the answer on stdout; diagnostics on stderr; non-zero when the "
                           "turn did not complete")
    chat.add_argument("--usage-file", metavar="PATH",
                      help="write a JSON report of this run (written even when it fails)")
    chat.add_argument("--agent", help="address one agent instead of the router")
    # Keep CLI help/completion stdlib-only; test parity with the runtime ladder.
    chat.add_argument("--reasoning", choices=("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
                      help="reasoning effort for this invocation only")
    selection = chat.add_mutually_exclusive_group()
    selection.add_argument("--session", help="explicit existing conversation session")
    selection.add_argument("-r", "--resume", metavar="SELECTOR", help="exact ID, unique prefix, title, latest, or @claude/@codex")
    selection.add_argument("-c", "--continue", dest="continue_latest", action="store_true",
                           help="use the latest unarchived conversation and print a free recap")
    chat.add_argument("--json", action="store_true")
    chat.add_argument("--no-prompts", action="store_true",
                      help="do not answer the turn's questions, secret requests or approvals here, "
                           "even on a terminal")
    chat.add_argument("--image", action="append", metavar="PATH",
                      help="ask the vision model about this PNG/JPEG/GIF/WebP file (up to 8, 4 MiB "
                           "each); the turn goes to the hub's vision model only, never to an agent")
    chat.add_argument("--clipboard-image", action="store_true",
                      help="attach the image on the clipboard (wl-paste, xclip, pngpaste, "
                           "osascript, or PowerShell on Windows and WSL), as --image does")
    chat.add_argument("--remote-vision", metavar="URL",
                      help="acknowledge that the images go to this vision destination off the "
                           "hub's machine; it must name the destination the hub reports")
    _selection_flags(chat)

    send = verbs.add_parser(
        "send",
        help="message a configured channel, or reply to an inbox thread (scripts, cron, CI)",
        description="Send one message with no model call. The body is the MESSAGE argument, else "
                    "--file PATH (- reads stdin), else whatever is piped on stdin; a terminal is "
                    "never read, with or without -f -. Bodies are text of up to 4,000 characters as "
                    "delivered (the subject counts where it becomes the first line); native "
                    "attachments (MEDIA:) are not carried yet. Exit 0 sent · 1 not delivered (the "
                    "hub refused, or the transport failed) · 2 usage · 3 no hub · 4 not authorised.",
        epilog="examples:\n"
               "  nerva send --channel telegram \"deploy finished\"\n"
               "  echo \"RAM 92%\" | nerva send --channel ntfy\n"
               "  nerva send --channel ntfy -s \"[CI]\" -f build.log\n"
               "  nerva send --list ntfy",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    target = send.add_mutually_exclusive_group(required=True)
    target.add_argument("--list", action="store_true",
                        help="list configured channels and inbox targets; MESSAGE, if given, filters by channel")
    target.add_argument("--to", metavar="THREAD_ID", help="exact thread id from --list (a governed reply)")
    target.add_argument("--channel", metavar="CHANNEL",
                        help="a configured destination from --list (telegram, ntfy, …) — no thread needed")
    send.add_argument("message", nargs="?",
                      help="the message (up to 4,000 characters); omit it to read --file or stdin")
    send.add_argument("-f", "--file", metavar="PATH",
                      help="read the body from PATH, or from stdin when PATH is -")
    send.add_argument("-s", "--subject", metavar="LINE",
                      help="one printable subject line (≤200): ntfy's title (printable ASCII, ≤120), "
                           "elsewhere the first line of the message")
    send.add_argument("-q", "--quiet", action="store_true", help="print nothing on success")
    send.add_argument("--json", action="store_true")

    desktop = verbs.add_parser(
        "desktop", help="can this machine run the desktop operator, and what is missing (offline)")
    desktop_verbs = desktop.add_subparsers(dest="sub", required=True)
    desktop_status = desktop_verbs.add_parser(
        "status", help="the ordered setup path for this host, and the first thing to do")
    desktop_status.add_argument("--json", action="store_true")
    desktop_grant = desktop_verbs.add_parser(
        "grant", help="open the OS pane where you award a permission (owner; grants nothing itself)")
    desktop_grant.add_argument("step", help="the step key from `nerva desktop status`")

    # H014 — the same module uninstall.sh / UNINSTALL.bat run; nothing is decided here.
    # On Windows the verb runs from the .venv it would delete (locked), so the module refuses
    # the software removal there and points to UNINSTALL.bat; --dry-run/--gui-only still work.
    uninstall = verbs.add_parser(
        "uninstall", help="remove the installed software (offline; your data stays unless --purge-data;"
                          " on Windows use UNINSTALL.bat for the engine — the running .venv is locked)")
    uninstall.add_argument("--dry-run", action="store_true",
                           help="print what would be removed and whether data would be purged")
    uninstall.add_argument("--confirm", action="store_true", help="required to actually remove anything")
    uninstall.add_argument("--purge-data", action="store_true",
                           help="also erase the data root (backup-first; needs the folder name typed back)")
    uninstall.add_argument("--yes-purge", metavar="PATH",
                           help="the data root's absolute path, for --purge-data without a prompt")
    uninstall.add_argument("--no-backup", action="store_true", help="with --purge-data, skip the backup")
    uninstall.add_argument("--gui", action="store_true", help="also remove the desktop app")
    uninstall.add_argument("--gui-only", action="store_true",
                           help="remove only the desktop app; keep the engine and your data")
    uninstall.add_argument("--gui-summary", action="store_true",
                           help="JSON probe of the desktop app (installed, paths); removes nothing")
    uninstall.add_argument("--root", help="app root to uninstall from")

    security = verbs.add_parser(
        "security", help="checks you can run on this box: known vulnerabilities in what is installed")
    security.set_defaults(action="audit")
    security_verbs = security.add_subparsers(dest="action", metavar="action")
    security.add_argument("--skip-venv", action="store_true", help="omit installed interpreter distributions")
    security.add_argument("--skip-plugins", action="store_true", help="omit registered extension Python pins")
    security.add_argument("--skip-mcp", action="store_true", help="omit saved pinned npx/uvx MCP packages")
    security_audit = security_verbs.add_parser(
        "audit",
        help="known vulnerabilities in this interpreter, declared extension pins, and saved pinned MCP commands, "
             "from OSV.dev — exit 0 clean · 1 findings at/above --fail-on · 5 database not "
             "consulted (nothing is claimed)",
        description="Checks this interpreter's installed distributions, owner-declared extension "
                    "Python pins, and exact pinned npx/uvx refs in saved MCP commands against OSV.dev. "
                    "Unpinned or unsupported commands are named as unaudited; declared pins are not "
                    "proof of extension installation or activation. System packages are outside scope. "
                    "Only package name+version pairs leave the machine after hub egress authorization. Exit 0 clean · "
                    "1 findings at/above --fail-on · 5 the database was not consulted or the audit "
                    "did not complete (nothing is claimed).")
    security_audit.add_argument(
        "--fail-on", choices=("low", "moderate", "high", "critical"), default="low",
        help="the lowest severity that fails the run (default: low, i.e. any finding — stricter "
             "than Hermes's critical, on purpose). An advisory with no stated severity always "
             "fails: unrated is not safe.")
    security_audit.add_argument(
        "--ignore-vuln", action="append", default=[], metavar="ID",
        help="an advisory id or alias to list but not fail on (repeatable)")
    security_audit.add_argument(
        "--extension", action="append", default=[], metavar="MANIFEST",
        help="an extension descriptor whose exact Python pins are audited too (repeatable)")
    security_audit.add_argument(
        "--offline", action="store_true",
        help="enumerate only; consult no database and claim nothing (exit 5)")
    security_audit.add_argument(
        "--osv-url", default=_OSV_DEFAULT, metavar="URL",
        help="an https OSV-compatible endpoint (default: api.osv.dev)")
    security_audit.add_argument("--json", action="store_true")
    security_audit.add_argument("--skip-venv", action="store_true", default=argparse.SUPPRESS,
                                help="omit installed interpreter distributions")
    security_audit.add_argument("--skip-plugins", action="store_true", default=argparse.SUPPRESS,
                                help="omit registered extension Python pins")
    security_audit.add_argument("--skip-mcp", action="store_true", default=argparse.SUPPRESS,
                                help="omit saved pinned npx/uvx MCP packages")

    completion = verbs.add_parser("completion", help="print a shell completion script")
    completion.add_argument("shell", choices=("bash", "zsh", "fish"))
    return parser


def command_tree(parser: argparse.ArgumentParser | None = None) -> dict[str, list[str]]:
    """verb → its sub-verbs, read from the parser so completion can never drift from it."""
    parser = parser or build_parser()
    tree: dict[str, list[str]] = {}
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            tree[name] = sorted(
                child
                for sub_action in sub._actions
                if isinstance(sub_action, argparse._SubParsersAction)
                for child in sub_action.choices
            )
    return tree


# ── verbs ─────────────────────────────────────────────────────────────────────


def _desktop_plan():
    """Probe this host and build the setup path. Imported late: the probe is heavy."""
    from agents.core.desktop_setup import plan
    from agents.core.host_probe import probe_host

    return plan(probe_host())


def cmd_desktop(ns: argparse.Namespace, ctx: Context) -> int:
    """Read-only by default; `grant` opens a settings pane and still grants nothing."""
    from agents.core.desktop_setup import open_settings, render

    try:
        report = _desktop_plan()
    except Exception as exc:  # a host fact we could not establish is not a crash
        ctx.err.write(f"could not probe this host: {type(exc).__name__}\n")
        return EXIT_FAILED

    if ns.sub == "status":
        if ns.json:
            ctx.out.write(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n")
        else:
            ctx.out.write(render(report))
        return EXIT_OK if report.ready else EXIT_FAILED

    step = report.step(ns.step)
    if step is None:
        keys = ", ".join(s.key for s in report.steps)
        ctx.err.write(f"no step named {ns.step!r} on this host. Steps here: {keys}\n")
        return EXIT_USAGE
    import subprocess  # nosec B404 - fixed argv from a closed table, never a shell

    # The argv can only be one of desktop_setup._OPENERS' own values: open_settings
    # checks the Opener by identity, so neither this call site nor a caller can
    # substitute one. tests/test_desktop_setup.py pins that with a value-equal
    # forgery that must still be refused.
    result = open_settings(
        step,
        spawn=lambda argv: subprocess.run(argv, check=False),  # nosec B603 - see above
    )
    if not result.get("ok"):
        ctx.err.write(f"{result.get('reason', 'grant_failed')}\n")
        return EXIT_FAILED
    ctx.out.write(
        f"opened {result['opened']}\n"
        "Grant it there, then run `nerva desktop status` again — the re-probe is the proof.\n"
    )
    return EXIT_OK


def cmd_support(ns: argparse.Namespace, ctx: Context) -> int:
    """H009 — the report a support thread asks for. Online it is the hub's own
    ``/api/support/bundle`` (what the HUD Support panel copies); ``--offline`` builds the
    same allow-listed bundle from this data root when the hub is down."""
    from datetime import UTC, datetime

    from agents.core import support_bundle

    lines = ns.logs
    if not 0 <= lines <= support_bundle.MAX_LOG_LINES:
        ctx.err.write(f"--logs takes 0..{support_bundle.MAX_LOG_LINES}\n")
        return EXIT_USAGE
    if ns.offline:
        bundle = support_bundle.build_bundle(now_iso=datetime.now(UTC).isoformat(),
                                             environ=ctx.environ, log_lines=lines)
    else:
        query = f"?{urlencode({'log_lines': lines})}" if lines else ""
        bundle = ctx.client().get(f"/api/support/bundle{query}")
        if not isinstance(bundle, dict):
            ctx.err.write("support bundle request returned a malformed response\n")
            return EXIT_FAILED
    text = (json.dumps(bundle, indent=2, ensure_ascii=False, default=str) + "\n" if ns.json
            else support_bundle.render_text(bundle))
    ctx.out.write(text)
    if ns.out:
        path = Path(ns.out)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)          # the create mode does not narrow a file that exists
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        ctx.err.write(f"written to {path}\n")
    return EXIT_OK


def cmd_doctor(ns: argparse.Namespace, ctx: Context) -> int:
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from scripts import doctor
    except ImportError:
        ctx.err.write("doctor is not available in this install (scripts/doctor.py missing)\n")
        return EXIT_FAILED
    argv = []
    if ns.json:
        argv.append("--json")
    if ns.smoke:
        argv.append("--smoke")
    if ns.local_pilot:
        argv.append("--local-pilot")
    return int(doctor.main(argv))


def _extension_descriptor(path, ctx):
    """Read the descriptor here, so the owner consents to the bytes they can see."""
    from agents.core.extensions.manifest import ManifestError, load_manifest

    try:
        manifest = load_manifest(path)
    except ManifestError as exc:
        ctx.err.write(f"{exc}\n")
        return None
    # Re-serialize from the parsed manifest rather than forwarding raw file bytes:
    # what the hub records consent for is exactly what was validated locally, and
    # an unknown field in the file can never ride along to the route.
    return {
        "manifest_version": 1, "api_version": 1, "id": manifest.id, "version": manifest.version,
        "capabilities": list(manifest.capabilities), "tools": list(manifest.tools),
        "commands": list(manifest.commands), "events": list(manifest.events),
        "requires": {"extensions": dict(manifest.extension_requires),
                     "python": dict(manifest.python_requires)},
    }


def cmd_extensions(ns: argparse.Namespace, ctx: Context) -> int:
    if ns.action == "doctor":
        from agents.core.extensions.doctor import doctor_paths

        report = doctor_paths(ns.paths)
        success = report["ok"]
    elif ns.action in {"consent", "activate"}:
        body = _extension_descriptor(ns.path, ctx)
        if body is None:
            return EXIT_FAILED
        if ns.action == "consent":
            report = ctx.client().post("/api/plugins/extensions/consent",
                                       {"manifest": body, "revoke": bool(ns.revoke)})
        else:
            report = ctx.client().post("/api/plugins/extensions/activate", {"manifest": body})
        if not isinstance(report, dict):
            ctx.err.write("extension request returned a malformed response\n")
            return EXIT_FAILED
        success = report.get("ok") is True
        if ns.json:
            ctx.dump(report)
        elif not success:
            ctx.say(f"Refused: {report.get('reason', 'unknown')}")
        elif ns.action == "consent":
            ctx.say("Consent withdrawn." if report.get("revoked") else
                    f"Consent recorded for {body['id']} ({report.get('declared_digest', '')[:12]}).")
        else:
            activation = report.get("activation") or {}
            tools = activation.get("callable_tools") or []
            ctx.say(f"Activated {activation.get('id')} {activation.get('version')}; callable tools: {len(tools)}")
            for tool in tools:
                ctx.say(f"  {tool}")
        return EXIT_OK if success else EXIT_FAILED
    else:
        report = ctx.client().get("/api/plugins/extensions")
        if (not isinstance(report, dict) or report.get("mode") != "inspection_only"
                or not isinstance(report.get("extensions"), list)
                or not isinstance(report.get("reason"), str)
                or any(not isinstance(row, dict)
                       or any(not isinstance(row.get(key), str) for key in ("id", "version", "reason"))
                       or not isinstance(row.get("callable_tools"), list)
                       or row.get("callable_commands") != []
                       # An inactive row still advertises nothing; only an activated
                       # one may, and only tools. This pin moved deliberately in S2 —
                       # before it, "callable" was unreachable by construction.
                       or (row.get("execution_available") is not True
                           and (row.get("execution_available") is not False or row.get("callable_tools") != []))
                       for row in report["extensions"])):
            ctx.err.write("extension inspection returned a malformed response\n")
            return EXIT_FAILED
        success = (report["reason"] in {"sdk_dispatch_unavailable", "activated",
                                        "acquisition_disabled", "acquisition_not_composed"}
                   and all(row["reason"] in {"sdk_dispatch_unavailable", "acquired_inactive", "activated"}
                           for row in report["extensions"]))
    if ns.json:
        ctx.dump(report)
    else:
        ctx.say("Extension inspection only; SDK dispatch is unavailable."
                if report.get("reason") != "activated" else "Extension inspection; some tools are activated.")
        for error in report.get("errors", []):
            ctx.say(f"  {error['reason']}")
        for row in report.get("extensions", []):
            issues = ", ".join(row.get("issues", [])) or row["reason"]
            ctx.say(f"  {row['id']} {row['version']}: {issues}; callable tools: {len(row.get('callable_tools') or [])}")
        if not report.get("extensions") and report.get("reason"):
            ctx.say(f"  {report['reason']}")
    return EXIT_OK if success else EXIT_FAILED


#: /status's legacy ``model_state`` says ``ready`` when ANY model is resident — even one
#: the Jarvis route would not use. The terminal shows it as what it is; whether the route
#: is runnable is the separate ``runnable:`` line (H242).
_MODEL_STATE_WORDS = {"ready": "resident"}


def _runnable(client: HubClient) -> dict:
    """The hub's strict route verdict — the model block of the first-run command center
    (onboarding._model_snapshot: the same select_backend a Jarvis turn makes, plus
    residency). Hermes's ``setup.runtime_check``. Read-only; never raises for a verdict
    it could not read — that is a named reason too. It runs after ``/status`` answered,
    so a transport failure here (a timeout, a reset) is ``hub_unreachable`` for this line,
    not "no hub": the rest of the status still prints."""
    try:
        center = client.get("/api/onboarding/command-center")
    except HubUnavailable as exc:
        return {"ready": None, "reason": "hub_unreachable", "error": exc.reason}
    except HubError as exc:
        if exc.status in (401, 403):
            return {"ready": None, "reason": "needs_token", "error": exc.reason}
        return {"ready": None, "reason": "command_center_unavailable",
                "error": f"HTTP {exc.status}: {exc.reason}"}
    model = center.get("model") if isinstance(center, dict) else None
    if not isinstance(model, dict):
        return {"ready": None, "reason": "malformed_reply"}
    ready = model.get("ready")
    verdict = {
        "ready": ready if isinstance(ready, bool) else None,
        "reason": _named(model.get("reason")) or "unreported",
        "route": _named(model.get("route")),
        "provider": _named(model.get("selected_provider")) or _named(model.get("active_provider")),
        "model": _named(model.get("selected_model")) or _named(model.get("active_model")),
    }
    if verdict["ready"] is True and not (verdict["route"] and verdict["provider"] and verdict["model"]):
        # Same rule as the doctor's strict row: "yes" must say what resolves.
        return {"ready": None, "reason": "malformed_reply",
                "error": "ready without a named route/provider/model"}
    return verdict


def _named(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


#: Settings read once, at start: a running hub does not pick them up (review-H667 nit 6).
_RESTART_SETTINGS = frozenset({("security", "sandbox_temp_dir")})


def _applies_at_restart(category: str, key: str, kind: str) -> bool:
    """A setting a running hub does not pick up. The H285 load set, and the plugin
    switches it counts, are read at boot only (review-H285 F7)."""
    return ((category, key) in _RESTART_SETTINGS or category == "loadset"
            or (category == "plugins" and kind == "toggle"))


def _withheld_admin(client: Any) -> bool:
    """The admin token is set and this client keeps it back: plain http off this machine
    would carry it in clear text (review-H273f m2)."""
    sends = getattr(client, "_sends_admin_token", None)
    return bool(getattr(client, "admin_token", "")) and callable(sends) and not sends()


def _refusal_tier(reason: str) -> str | None:
    """The tier the hub's refusal asked for, read from its own reason (agents/web.py's
    guards): "admin", "user", or None when the reason does not say."""
    text = (reason or "").lower()
    if "admin token required" in text or text.startswith("admin disabled from network"):
        return "admin"
    if "user token required" in text or "disabled from network" in text:
        return "user"
    return None


def _auth_hint(client: Any, reason: str = "") -> str:
    """What to do about a 401/403, for the client that was refused and the hub's own
    reason. The withheld admin token is named as one possible cause, beside the user
    token, never as the only one (review-H273g m3). The reason says which tier the hub
    wanted: only a token of that tier that was sent is called refused, and a verb that
    needs the admin tier asks for the admin token when only the user token is set
    (review-H273i m2). Recovery is the additive ``issue``; ``rotate`` revokes every
    token of the tier, so it is named only for a leaked one."""
    if _withheld_admin(client):
        return (f"JARVIS_ADMIN_TOKEN is set but was withheld from {client.base_url}: plain http to "
                "another machine would carry it in clear text. If this needs the admin token, point "
                "NERVA_HUB_URL at an https address or run it on the hub itself; otherwise set "
                "JARVIS_USER_TOKEN, or check that it is current.")
    admin_set = bool(getattr(client, "admin_token", ""))
    user_set = bool(getattr(client, "user_token", ""))
    tier = _refusal_tier(reason)
    if "disabled from network" in (reason or "").lower():
        name = "JARVIS_ADMIN_TOKEN" if tier == "admin" else "JARVIS_USER_TOKEN"
        return (f"The hub has no {name} configured, so it refuses this from another machine "
                f"whatever is sent: set {name} on the hub (mint one there: python "
                f"scripts/token_recover.py issue {tier or 'user'}) and use it here, or run the verb "
                "on the hub itself.")
    if tier == "admin":
        if not admin_set:
            also = " (JARVIS_USER_TOKEN is not enough)" if user_set else ""
            return (f"This needs JARVIS_ADMIN_TOKEN{also}. Mint one on the box: python "
                    "scripts/token_recover.py issue admin.")
        return ("The hub refused JARVIS_ADMIN_TOKEN: it may be expired or revoked. Mint another on "
                "the box: python scripts/token_recover.py issue admin (rotate admin only if it "
                "leaked: rotating revokes every admin token).")
    sent = [name for name, value in (("JARVIS_ADMIN_TOKEN", admin_set),
                                     ("JARVIS_USER_TOKEN", user_set)) if value]
    if tier == "user":
        if not sent:
            return ("Set JARVIS_USER_TOKEN (mint one on the box: python scripts/token_recover.py "
                    "issue user) or JARVIS_ADMIN_TOKEN.")
        return (f"The hub refused {' and '.join(sent)}: it may be expired or revoked. Mint another "
                "on the box: python scripts/token_recover.py issue user.")
    if sent:
        return (f"The hub refused {' and '.join(sent)}: it may be expired or revoked, or this needs "
                "the other tier. Mint another on the box: python scripts/token_recover.py issue "
                "admin (or issue user).")
    return ("Set JARVIS_ADMIN_TOKEN (mint one on the box: python scripts/token_recover.py issue admin) "
            "or JARVIS_USER_TOKEN.")


def _read_hint(client: Any, reason: str = "") -> str:
    """The status lines' version of the hint, for a read the hub refused (a user-tier
    read). The hub's reason rules causes out: a hub with no user token configured
    refuses every read from the network, whatever is sent (review-H273i n4)."""
    if "disabled from network" in (reason or "").lower():
        return "(refused from the network: the hub has no JARVIS_USER_TOKEN configured)"
    if _withheld_admin(client):
        if getattr(client, "user_token", ""):
            return ("(refused: JARVIS_ADMIN_TOKEN is withheld over plain http, and JARVIS_USER_TOKEN "
                    "may be expired or revoked)")
        return "(needs JARVIS_USER_TOKEN to read here: JARVIS_ADMIN_TOKEN is withheld over plain http)"
    if getattr(client, "admin_token", "") or getattr(client, "user_token", ""):
        return "(refused: the token set may be expired or revoked)"
    return "(needs JARVIS_USER_TOKEN or JARVIS_ADMIN_TOKEN to read)"


def _runnable_line(verdict: Mapping[str, Any], client: Any = None) -> str:
    reason = verdict.get("reason")
    if reason == "needs_token":
        return _read_hint(client, str(verdict.get("error") or ""))
    if reason in ("command_center_unavailable", "malformed_reply", "hub_unreachable"):
        error = verdict.get("error")
        return f"unknown — {reason}" + (f" ({error})" if error else "")
    route = verdict.get("route")
    target = (
        f"route {route} → {verdict.get('provider') or '?'}/{verdict.get('model') or '?'}"
        if route else "no route"
    )
    if verdict.get("ready") is True:
        return f"yes — {target} ({reason})"
    word = "unknown" if verdict.get("ready") is None else "no"
    return f"{word} — {reason}: {target}"


#: H019 — a name from the hub (a unit, a channel) is printed only in systemd's characters;
#: anything else (a control sequence from a hub at a wrong address) reads as unknown.
_PRINTABLE_NAME = re.compile(r"[A-Za-z0-9:_.@\-]{1,128}")
_SERVICE_MANAGERS = frozenset({"systemd", "launchd", "s6", "nssm", "none", "unknown"})


def _count_value(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _printable(value: Any) -> str | None:
    return value if isinstance(value, str) and _PRINTABLE_NAME.fullmatch(value) else None


def _uptime_words(seconds: Any) -> str:
    whole = _count_value(seconds)
    if whole is None:
        return "unknown"
    hours, rest = divmod(whole, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}"


def _service_line(block: Any) -> str:
    """H019 — the hub's service block in one line (Hermes' Gateway Service: manager,
    running, installed-but-not-managing vs installed-but-stopped, pid). A fact the hub could
    not read says unknown; an older hub that sends no block says so."""
    if not isinstance(block, dict):
        return "unknown (this hub does not report it)"
    manager = block.get("manager") if block.get("manager") in _SERVICE_MANAGERS else "unknown"
    unit = _printable(block.get("unit"))
    shipped = unit or "the shipped unit"
    state, active = block.get("state"), block.get("active")
    if state == "managed" and manager not in ("none", "unknown"):
        head = f"{manager} — running as {unit}" if unit else f"{manager} — running (unit name unknown)"
    elif state == "unconfirmed" and manager not in ("none", "unknown"):
        head = f"{manager}? — not confirmed that it runs this hub" + (f" (unit {unit})" if unit else "")
    elif state == "installed_not_managing":
        how = " and active" if active is True else (" (state unknown)" if active is None else "")
        head = f"none detected — {shipped} is installed{how} but not managing this hub"
    elif state == "installed_stopped":
        head = f"none detected — {shipped} is installed but stopped; this hub runs outside it"
    elif state == "not_installed":
        head = f"none detected — {shipped} is not installed"
    elif state == "unsupported":
        head = "none detected — no service unit Nerva ships applies on this host"
    else:
        head = "unknown — the service manager could not be read"
    pid = _count_value(block.get("pid"))
    return f"{head} · pid {pid if pid is not None else 'unknown'} · up {_uptime_words(block.get('uptime_s'))}"


def _in_use(running: Any, cap: Any) -> str:
    held, limit = _count_value(running), _count_value(cap)
    text = f"{held if held is not None else '?'}/{limit if limit is not None else '?'} in use"
    return text + (" (full)" if held is not None and limit is not None and held >= limit else "")


def _slots_line(slots: Any) -> str:
    """H019 — concurrency in use against what is allowed (Hermes' Sessions → Slots): turns
    holding a session's lease, each running channel's chat lanes, the sub-agents."""
    if not isinstance(slots, dict):
        return "unknown (this hub does not report it)"
    parts = []
    turns = slots.get("turns")
    running = _count_value(turns.get("running")) if isinstance(turns, dict) else None
    if running is None:
        parts.append("turns unknown")
    elif _count_value(turns.get("cap")) is not None:
        parts.append(f"turns {_in_use(running, turns.get('cap'))}")
    else:
        per = _count_value(turns.get("per_session"))
        bound = f"{per} per session" if per is not None else "per-session bound unknown"
        parts.append(f"turns {running} running ({bound}, no hub-wide cap)")
    lanes = slots.get("lanes")
    if isinstance(lanes, list):
        for row in lanes:
            if not isinstance(row, dict):
                continue
            text = f"{_printable(row.get('channel')) or '?'} lanes {_in_use(row.get('running'), row.get('cap'))}"
            queued = _count_value(row.get("queued"))
            parts.append(text + (f", {queued} queued" if queued else ("" if queued == 0 else ", queued unknown")))
    else:
        parts.append("chat lanes unknown")
    sub = slots.get("subagents")
    if isinstance(sub, dict) and _count_value(sub.get("running")) is not None and _count_value(sub.get("cap")) is not None:
        parts.append(f"sub-agents {_in_use(sub['running'], sub['cap'])}")
    else:
        parts.append("sub-agents unknown")
    return " · ".join(parts)


#: The status lines' value column: holder rows sit under the `slots:` value.
_STATUS_INDENT = " " * 15


def _holder_rows(detail: Any) -> list[str]:
    """H019 — one row per slot holder under `slots:` (Hermes' Slots rows: surface, session
    id, age), from `GET /api/status/slots`; nothing when the hub did not return them."""
    holders = detail.get("holders") if isinstance(detail, dict) else None
    if not isinstance(holders, list):
        return []
    rows = []
    for row in holders:
        if not isinstance(row, dict):
            continue
        surface = _printable(row.get("surface")) or "unknown"
        session = _printable(row.get("session_id")) or "?"
        rows.append(f"{_STATUS_INDENT}{surface:<17} {session:<24} held {_uptime_words(row.get('age_s'))}")
    total = _count_value(detail.get("holders_total"))
    if total is not None and total > len(rows):
        rows.append(f"{_STATUS_INDENT}… and {total - len(rows)} more")
    return rows


def _estop_banner(estop: Any) -> str | None:
    """H019 — the e-stop announced at the top of `nerva status` while it is engaged
    (Hermes' pause banner under the status header); None when it is not engaged."""
    if not isinstance(estop, dict) or not estop.get("engaged"):
        return None
    state = estop.get("state") if isinstance(estop.get("state"), dict) else {}
    since = _plain(state.get("engaged_at") or "?", 64)
    reason = _plain(state.get("reason") or "no reason given")
    return f"  PAUSED — emergency stop ENGAGED since {since} — {reason}; `nerva estop resume` lifts it"


def _local_service_line() -> str | None:
    """H019 — no hub answered on this machine: the unit Nerva ships, as this box sees it
    (Hermes' "stopped" / "installed but stopped"). None where no unit is shipped."""
    from agents.core import service_status

    try:
        unit = service_status.shipped_unit()
    except Exception:
        return None
    if not isinstance(unit, dict) or not unit.get("applicable"):
        return None
    name = _printable(unit.get("unit")) or "the service unit"
    installed, active = unit.get("installed"), unit.get("active")
    if installed is None:
        return f"{name}: could not tell whether it is installed"
    if installed is False:
        return f"{name} is not installed"
    if active is False:
        return f"{name} is installed but stopped"
    if active is True:
        return f"{name} is active, yet no hub answers at this address (still starting, or another port)"
    return f"{name} is installed; its state is unknown"


def cmd_status(ns: argparse.Namespace, ctx: Context) -> int:
    client = ctx.client()
    try:
        status = client.get("/status")
    except HubUnavailable:
        # H019: say what this box's service unit is doing; the no-hub error follows (exit 3).
        line = (None if ns.json or not is_loopback_url(str(getattr(client, "base_url", "")))
                else _local_service_line())
        if line:
            ctx.say(f"nerva — no hub answered at {client.base_url}")
            ctx.say(f"  service:     {line}")
        raise
    if not isinstance(status, dict):
        raise HubError(0, "malformed /status reply")
    estop = None
    estop_refused = ""
    try:
        estop = client.get("/api/ops/estop")
    except HubError as exc:
        if exc.status not in (401, 403):
            raise
        estop_refused = exc.reason
    # H019: who holds the slots (a user-tier read). A hub without the route, or one that
    # refuses it, leaves the rows out; only a hub gone away mid-way ends the verb.
    slot_holders, holders_refused = None, None
    try:
        slot_holders = client.get("/api/status/slots")
    except HubUnavailable:
        raise
    except HubError as exc:
        if exc.status in (401, 403):
            holders_refused = exc.reason
    if not isinstance(slot_holders, dict):
        slot_holders = None
    runnable = _runnable(client)
    if ns.json:
        ctx.dump({"status": status, "estop": estop, "runnable": runnable, "slot_holders": slot_holders})
        return EXIT_OK
    agents = status.get("agents") or []
    ctx.say(f"nerva {status.get('version', '?')} — {client.base_url}")
    banner = _estop_banner(estop)
    if banner:   # H019: a paused hub says so at the top (Hermes' pause banner)
        ctx.say(banner)
    ctx.say(f"  backend:     {status.get('llm_backend', 'none')}")
    state = str(status.get("model_state", "unknown"))
    ctx.say(
        f"  model:       {status.get('loaded_model') or status.get('configured_model') or '—'}"
        f" ({_MODEL_STATE_WORDS.get(state, state)})"
    )
    ctx.say(f"  runnable:    {_runnable_line(runnable, client)}")
    ctx.say(f"  agents:      {status.get('agents_online', 0)}/{status.get('agents_total', len(agents))} busy")
    channels = status.get("channels") or []
    names = ", ".join(
        str(c.get("id") or c.get("channel") or c) if isinstance(c, dict) else str(c) for c in channels
    )
    ctx.say(f"  channels:    {names or '—'}")
    ctx.say(f"  service:     {_service_line(status.get('service'))}")
    slots = status.get("slots")
    ctx.say(f"  slots:       {_slots_line(slots)}")
    for row in _holder_rows(slot_holders):
        ctx.say(row)
    turns = slots.get("turns") if isinstance(slots, dict) else None
    if holders_refused is not None and isinstance(turns, dict) and _count_value(turns.get("running")):
        ctx.say(f"{_STATUS_INDENT}holders {_read_hint(client, holders_refused)}")
    if isinstance(estop, dict):
        if estop.get("engaged"):
            state = estop.get("state") if isinstance(estop.get("state"), dict) else {}
            ctx.say(f"  e-stop:      ENGAGED since {_plain(state.get('engaged_at') or '?', 64)}"
                    f" — {_plain(state.get('reason') or 'no reason given')}")
        else:
            ctx.say("  e-stop:      not engaged")
    else:
        ctx.say(f"  e-stop:      {_read_hint(client, estop_refused)}")
    return EXIT_OK


def _settings():
    from agents.core import settings_db

    return settings_db


def _is_secret(row: Mapping[str, Any]) -> bool:
    key = str(row.get("key", "")).lower()
    kind = str(row.get("kind", ""))
    # A key the store encrypts is a credential whatever its name (review-H465d nit 5: the
    # GA4 service-account JSON, a private key, printed in the clear).
    if kind in _SECRET_KINDS or key in _settings().SECRET_KEYS:
        return True
    # H006: the store's own rule (export, reset and preview use it) as well as the hint list,
    # so `config list`, `get` and `edit` agree — it adds the `client_id` suffix.
    return kind not in _PLAIN_KINDS and (
        any(hint in key for hint in _SECRET_HINTS)
        or _settings().is_secret_setting(str(row.get("category", "")), str(row.get("key", ""))))


def _shown(row: Mapping[str, Any], *, reveal: bool) -> Any:
    if _is_secret(row) and not reveal and row.get("value") not in (None, "", [], {}):
        return "••••••"
    return row.get("value")


def _resolve_name(settings: Any, name: str, *, stored: bool = False) -> tuple[str, str, list[Any]] | None:
    """H688 — ``(category, key, path below the key)`` for a setting name, or None when no
    declared setting matches. Keys whose name contains a dot are matched greedily; a
    malformed or ambiguous name is a usage error (exit 2) naming how to spell it.

    With *stored* (``config get``), a name no declared setting matches is matched next
    against the rows stored in its category, as ``config list`` shows them: rows nothing
    declares (``cache.entries``, a removed declaration's leftover) stay readable. Writes
    never pass it — they stay limited to declared settings."""
    from agents.core import settings_path

    try:
        resolved = settings_path.resolve_setting(name, settings._SPEC.keys())
        if resolved is None and stored:
            category = settings_path.parse(name)[0].text
            rows = settings.get_category(category)
            resolved = settings_path.resolve_setting(name, {(category, str(r["key"])) for r in rows})
        return resolved
    except settings_path.PathError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _coerce(value: str, kind: str) -> Any:
    from agents.core.env_config import is_recognized_bool, truthy

    if kind == "toggle":
        if not is_recognized_bool(value):
            raise ValueError(f"a toggle takes on/off (true/false, 1/0), got {value!r}")
        return truthy(value)
    if kind in ("number", "slider"):
        try:
            return int(value)
        except ValueError:
            return float(value)
    if kind == "tags":
        return [part.strip() for part in value.split(",") if part.strip()]
    if kind == "json":
        return json.loads(value)
    return value


def _coerce_inner(value: str) -> Any:
    """H688 — a value written inside a json setting: JSON when it parses (a number, true,
    an object), else the text as typed."""
    try:
        return json.loads(value)
    except ValueError:
        return value


def cmd_config(ns: argparse.Namespace, ctx: Context) -> int:
    settings = _settings()
    if ns.action == "list":
        groups = settings.get_all()
        if ns.category:
            groups = {ns.category: groups.get(ns.category, [])}
            if not groups[ns.category]:
                ctx.err.write(f"no settings category {ns.category!r}\n")
                return EXIT_FAILED
        if ns.json:
            ctx.dump({cat: [{**row, "value": _shown(row, reveal=ns.reveal)} for row in rows] for cat, rows in groups.items()})
            return EXIT_OK
        for cat, rows in groups.items():
            for row in rows:
                shown = json.dumps(_shown(row, reveal=ns.reveal), ensure_ascii=False)
                # H273: "default" is the declared value; "set" was changed from it
                source = f", {row['source']}" if row.get("source") else ""
                overlay = (f"; in effect: {json.dumps(row['in_effect'])} by {row['overlay']}"
                           if row.get("overlay") else "")
                managed = _managed_note(row)
                ctx.say(f"{cat}.{row['key']} = {shown}  ({row.get('kind', '?')}{source}{overlay}{managed})")
        return EXIT_OK
    if ns.action == "get":
        from agents.core import settings_path

        resolved = _resolve_name(settings, ns.name, stored=True)
        row = None
        if resolved is not None:
            category, key, path = resolved
            row = next((r for r in settings.get_category(category) if r["key"] == key), None)
        if row is None:
            ctx.err.write(f"no setting {ns.name}\n")
            return EXIT_FAILED
        try:
            # A secret stays masked whole, wherever inside it the name points.
            value = settings_path.get_in(row.get("value"), path)
        except settings_path.PathError as exc:
            ctx.err.write(f"{ns.name}: {exc}\n")
            return EXIT_FAILED
        ctx.say(json.dumps(_shown({**row, "value": value}, reveal=ns.reveal), ensure_ascii=False))
        return EXIT_OK
    if ns.action in ("set", "unset"):
        from agents.core import settings_path

        resolved = _resolve_name(settings, ns.name)
        spec = settings._SPEC.get(resolved[:2]) if resolved is not None else None
        if resolved is None or spec is None:
            ctx.err.write(f"{ns.name} is not a declared setting (see `nerva config list`)\n")
            return EXIT_FAILED
        category, key, path = resolved
        if (category, key) in settings.ROUTE_ONLY:
            # review-H329 F1: a route-only row has one writer (the skill switches, which record a
            # switch-on; H613 the voice command providers, which ask for approval).
            hint = " — use `nerva skills on|off`" if category == "skills" else ""
            ctx.err.write(f"{ns.name} is changed only in {settings.ROUTE_ONLY[(category, key)]}{hint}\n")
            return EXIT_FAILED
        kind = str(spec.get("kind", "text"))
        if not path:
            # G1 — Hermes's `config set|unset` on a pinned key: refused whatever the value
            # (a path below a json setting is judged by the pinned leaves it would change)
            refusal = _managed_refusal(ns.name, category, key)
            if refusal:
                ctx.err.write(refusal + "\n")
                return EXIT_FAILED
        try:
            if path:
                # H688 — inside a json value: the rest of the name is a path, the new whole
                # value goes through the same validation and guards as any other write.
                current = settings.get_value(category, key, spec.get("value"))
                if ns.action == "unset":
                    value = settings_path.unset_in(current, path)
                else:
                    value = settings_path.set_in(current, path, _coerce_inner(ns.value))
            elif ns.action == "unset":
                value = copy.deepcopy(spec.get("value"))
            else:
                value = _coerce(ns.value, kind)
        except ValueError as exc:  # settings_path.PathError is a ValueError
            ctx.err.write(f"{ns.name}: {exc}\n")
            return EXIT_FAILED
        errors = settings.validate_category(category, {key: value})
        if errors:
            ctx.err.write(f"{ns.name}: rejected — {'; '.join(errors)}\n")
            return EXIT_FAILED
        value = _stamped(category, key, value)
        refusal = _write_setting(settings, ns.name, category, key, value, ns)
        if refusal:
            ctx.err.write("".join(line + "\n" for line in refusal))
            return EXIT_FAILED
        # A stored secret is echoed back masked, as `config get` shows it (review-H465e
        # nit 3); the value typed on this command line is the shell's to keep or not.
        when = _when_applied(category, key, spec)
        if ns.action == "unset":
            what = "removed" if path else "back to its declared value"
            ctx.say(f"{ns.name} {what}  ({when})")
            return EXIT_OK
        written = settings_path.get_in(value, path) if path else value
        shown = _shown({"key": key, "kind": spec.get("kind", ""), "value": written}, reveal=False)
        ctx.say(f"{ns.name} = {json.dumps(shown, ensure_ascii=False)}  ({when})")
        return EXIT_OK
    if ns.action == "edit":
        return _config_edit(ns, ctx, settings)
    if ns.action == "path":
        return _config_path(ns, ctx, settings)
    if ns.action == "env-path":
        return _config_env_path(ns, ctx)
    if ns.action == "migrate":
        return _config_migrate(ns, ctx, settings)
    if ns.action == "managed":
        return _config_managed(ns, ctx)
    if ns.action == "check":
        problems: list[str] = []
        for cat, rows in settings.get_all().items():
            for row in rows:
                for error in settings.validate_category(cat, {row["key"]: row["value"]}):
                    problems.append(f"{cat}.{row['key']}: {error}")
        if problems:
            for problem in problems:
                ctx.say(f"  ✗ {problem}")
            ctx.say(f"{len(problems)} setting(s) do not match their declared schema")
            return EXIT_FAILED
        ctx.say("every stored setting matches its declared schema")
        return EXIT_OK
    return EXIT_USAGE


def _stamped(category: str, key: str, value: Any) -> Any:
    """review-H688 r2: the HUD syncs appearance across devices on this revision; a CLI
    write moves it as ``appearance.update_appearance`` does, or no other device sees it."""
    if (category, key) == ("appearance", "preferences") and isinstance(value, dict):
        return {**value, "_revision": uuid.uuid4().hex}
    return value


def _write_setting(settings: Any, name: str, category: str, key: str, value: Any,
                   ns: argparse.Namespace) -> list[str]:
    """The guarded write ``config set``, ``unset`` and ``edit`` share once a value has
    passed its schema: the retention approval (H262), the selection guards (H378), the
    write, and the approval lowering a narrowing implies. Returns the lines that explain
    a refusal (nothing written), or ``[]`` once the value is stored."""
    # G1 — a value an administrator pinned is refused before any guard or approval sees it.
    refusal = _managed_refusal(name, category, key, value)
    if refusal:
        return [refusal]
    # H262 — a value that makes retention delete deeper than a human approved waits for
    # the approval queue, which is the hub's: refused here (the approval is read, read-only).
    from agents.core import retention

    if retention.needs_approval({category: {key: value}}, retention.stored_values(),
                                retention.approved_horizons_offline()):
        return [f"{name}: not changed — it would make retention delete deeper than approved; "
                "change it in the HUD, Settings → Retention, which asks for approval"]
    # H378 — a model choice passes the selection guards here as on the hub's routes.
    from agents.core.llm import selection_guards as guards
    from agents.core.llm.provider_selection import SelectionConflict
    from agents.core.llm.providers.selection_gates import SelectionBusy, SelectionUnavailable
    from agents.core.managed_scope import ManagedRefused

    try:
        pair_state = (settings.compatible_pair_state()
                      if category == 'llm' and key in {'compatible_provider', 'compatible_model'}
                      else None)
    except (SelectionBusy, SelectionUnavailable) as exc:
        return [f'{name}: {exc} — not changed, retry']

    def current(other_key):
        if pair_state is not None and other_key == 'compatible_provider':
            return pair_state[1]
        if pair_state is not None and other_key == 'compatible_model':
            return pair_state[2]
        return settings.get_value(category, other_key)

    choices = guards.choices_from_settings(category, {key: value}, current)
    if choices:
        try:
            findings = guards.enforce(choices, confirm_expensive=getattr(ns, "confirm_expensive", False),
                                      acknowledge_training=getattr(ns, "acknowledge_training", False))
        except guards.SelectionRefused as refused:
            lines = [f"{name}: {finding.message}" for finding in refused.findings]
            flags = " ".join("--" + need.replace("_", "-") for need in refused.missing)
            lines.append(f"{name}: not changed — rerun with {flags} to choose it anyway")
            return lines
        try:
            guards.record(findings, "cli", _audit_log())
        except guards.ConsentNotRecorded as exc:
            return [f"{name}: {exc}"]
    approval_key = category == "autonomy" and key in ("mode", "agent_modes")
    before = settings.get_value(category, key) if approval_key else None
    try:
        if pair_state is not None:
            settings.put_category(category, {key: value},
                                  expected_pair_revision=pair_state[0])
        else:
            settings.put_category(category, {key: value})
    except (SelectionConflict, SelectionBusy, SelectionUnavailable):
        return [f'{name}: compatible provider/model changed or busy — not changed, retry']
    except ManagedRefused as exc:           # G1: the managed layer moved under this write
        return [f"{name}: {exc}"]
    except sqlite3.OperationalError as exc:
        return [f"{name}: {_busy(exc)}"]
    if approval_key:
        # H484: the approval dial written straight to the store is on the audit log too.
        from agents.core.autonomy.mode import audit_offline_write

        audit_offline_write(_audit_log(), key, before, value, actor="owner", surface="cli")
    if f"{category}.{key}" in retention.RETENTION_KEYS:
        # H262 review — a narrowing is a human decision too: the approval is lowered to it,
        # so deepening again later needs a new approval (never raised here).
        retention.lower_approval_offline()
    return []


def _managed_note(row: Mapping[str, Any]) -> str:
    """G1 — ``; managed by your administrator (file)`` for a pinned row, else ``""``."""
    managed = row.get("managed")
    if not isinstance(managed, Mapping):
        return ""
    leaves = managed.get("leaves") or []
    where = f" at {', '.join(str(leaf) for leaf in leaves)}" if leaves else ""
    invalid = "; the pinned value is invalid and not applied" if managed.get("invalid") else ""
    return f"; managed by your administrator{where} ({managed.get('source')}){invalid}"


def _managed_refusal(name: str, category: str, key: str, value: Any = None) -> str:
    """G1 — the line that refuses a write the managed layer forbids (audited), or ``""``.
    Without *value* the write is refused whenever the key is pinned (``config unset``)."""
    from agents.core import managed_scope

    try:
        managed_scope.check_setting_write(category, key, managed_scope.ANY if value is None else value)
    except managed_scope.ManagedRefused as exc:
        from agents.core.autonomy.mode import SimpleAudit, _audit

        _audit(SimpleAudit(_audit_log()), f"settings.{category}.{key} write refused: {exc} (via cli)",
               "settings_managed_refused")
        return f"{name}: {exc}"
    return ""


def _config_managed(ns: argparse.Namespace, ctx: Context) -> int:
    """``nerva config managed`` — the administrator's managed layer: where it is read
    from, each file's state, the pinned settings and environment names (never a value),
    the managed-mode marker and whether writes are refused. Exit 1 when a managed file
    cannot be read (every write is refused until it is fixed)."""
    from agents.core import managed_scope

    info = managed_scope.describe()        # the environment the settings writers judge by
    if ns.json:
        ctx.dump(info)
        return EXIT_FAILED if info["problems"] else EXIT_OK
    if info["directory"] is None:
        ctx.say("no managed configuration: nothing is pinned by an administrator "
                "(NERVA_MANAGED_DIR is not set and /etc/nerva does not exist)")
        return EXIT_OK
    how = "the managed-directory variable" if info["explicit"] else "the system location"
    ctx.say(f"managed directory: {info['directory']}  ({how}"
            + (f", profile {info['profile']}" if info["profile"] else "") + ")")
    for row in info["files"]:
        if row["state"] == "absent":
            continue
        error = f" — {row['error']}" if row.get("error") else ""
        ctx.say(f"  {row['scope']:<10} {row['path']}  {row['state']}{error}")
    for row in info["settings"]:
        leaves = f" (leaves: {', '.join(row['leaves'])})" if row["leaves"] else ""
        ctx.say(f"  setting  {row['name']}{leaves}  ← {row['source']}")
    for row in info["env"]:
        ctx.say(f"  env      {row['name']}  ← {row['source']}")
    if info["lock"]:
        ctx.say(f"managed mode: every configuration write is refused — {info['lock']['instruction']}"
                f" ({info['lock']['source']})")
    for problem in info["problems"]:
        ctx.err.write(f"cannot read the managed configuration: {problem}\n")
    for detail in info.get("details", []):
        ctx.err.write(f"  why: {detail}\n")
    for warning in info.get("warnings", []):
        ctx.err.write(f"warning: {warning}\n")
    ctx.say(f"writes: {info['writes']}")
    return EXIT_FAILED if info["problems"] else EXIT_OK


def _busy(exc: sqlite3.Error) -> str:
    """The reason a store write or read failed with ``OperationalError``, named."""
    return ("settings store busy (another process holds it) — not changed, retry"
            if "locked" in str(exc).lower() or "busy" in str(exc).lower()
            else f"settings store unusable: {_plain(exc, 120)} — not changed")


def _when_applied(category: str, key: str, spec: Mapping[str, Any]) -> str:
    if _applies_at_restart(category, key, str(spec.get("kind", ""))):
        return "restart the hub to apply it"
    if category == "autonomy" and key in ("mode", "agent_modes"):     # H484: synced per tick
        return "a running hub picks it up at its next autonomy tick (60 s by default)"
    return "a running hub picks it up within 30 s"


# ── H006: config edit / path / env-path / migrate ────────────────────────────

_EDIT_HEADER = (
    "# nerva config edit — every setting you may change here, as `nerva config list` prints it.\n"
    "# Change a value and save: `category.key = VALUE`, VALUE as JSON (true/false, 12, 0.7,\n"
    '# "text", ["a", "b"], {"k": 1}); what follows the value on a line is ignored. Lines\n'
    "# starting with # are ignored; delete a line to leave that setting alone. Only values\n"
    "# that differ are written, each through the same checks as `nerva config set`.\n"
)


def _editor_argv(environ: Mapping[str, str]) -> list[str]:
    """``$VISUAL``, then ``$EDITOR`` (split as a shell would, so ``code --wait`` works),
    then the platform's plain editor. On Windows a backslash path is not an escape
    (``posix=False``), and the quotes that leaves around a word are stripped."""
    windows = os.name == "nt"
    for var in ("VISUAL", "EDITOR"):
        try:
            argv = shlex.split(str(environ.get(var, "") or ""), posix=not windows)
        except ValueError:
            argv = []
        if windows:
            argv = [word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in "\"'" else word
                    for word in argv]
        if argv:
            return argv
    return ["notepad"] if windows else ["vi"]


def _run_editor(argv: list[str], path: str) -> int:
    """Run the owner's editor on *path* with this terminal; its exit status."""
    import subprocess  # nosec B404 — the owner's own $VISUAL/$EDITOR argv, never a shell

    return subprocess.run([*argv, path], check=False).returncode  # noqa: S603  # nosec B603


def _editor_failure(exc: OSError) -> str:
    """Why the owner's editor did not start, in the words ``config edit`` and ``journey
    edit`` both print."""
    import errno

    if isinstance(exc, FileNotFoundError):
        return "not found"
    if isinstance(exc, PermissionError) or exc.errno == errno.ENOEXEC or getattr(exc, "winerror", None) == 193:
        return "not executable"
    return "could not start"


def _edit_document(settings: Any) -> tuple[str, dict[str, Mapping[str, Any]]]:
    """The file the editor opens, and by name the rows it may change. A secret, a
    route-only row and an undeclared row are named in a comment, their value never
    written to disk (the file is owner-only and removed, but it still leaves this process)."""
    lines = [_EDIT_HEADER]
    editable: dict[str, Mapping[str, Any]] = {}
    for cat, rows in settings.get_all().items():
        lines.append(f"\n# [{cat}]")
        for row in rows:
            name = f"{cat}.{row['key']}"
            if settings._SPEC.get((cat, row["key"])) is None:
                lines.append(f"# {name}: nothing declares it — read it with `nerva config get {name}`")
            elif (cat, row["key"]) in settings.ROUTE_ONLY:
                lines.append(f"# {name}: changed only in {settings.ROUTE_ONLY[(cat, row['key'])]}")
            elif row.get("managed"):          # G1
                lines.append(f"# {name}: {_managed_note(row).lstrip('; ')} — it cannot be changed here")
            elif _is_secret(row):
                lines.append(f"# {name}: a secret — change it with `nerva config set {name} VALUE`")
            else:
                source = f", {row['source']}" if row.get("source") else ""
                lines.append(f"{name} = {json.dumps(row['value'], ensure_ascii=False)}"
                             f"  ({row.get('kind', '?')}{source})")
                editable[name] = row
    return "\n".join(lines) + "\n", editable


def _parse_edit(text: str) -> tuple[dict[str, Any], list[str]]:
    """``(values by name, rejected lines)`` from the saved file: a value is the JSON at
    the start of what follows ``=``; the rest of the line is the annotation and is ignored."""
    decoder = json.JSONDecoder()
    values: dict[str, Any] = {}
    rejected: list[str] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, rest = line.partition("=")
        name = name.strip()
        if not sep or "." not in name or any(ch.isspace() for ch in name):
            rejected.append(f"line {number}: not `category.key = value`: {_plain(line, 80)}")
            continue
        try:
            value, _end = decoder.raw_decode(rest.strip())
        except ValueError:
            rejected.append(f"line {number}: {name}: the value is not JSON "
                            '(true/false, a number, "text" in quotes, [...] or {...})')
            continue
        if name in values:
            rejected.append(f"line {number}: {name} is named twice")
            continue
        values[name] = value
    return values, rejected


def _config_edit(ns: argparse.Namespace, ctx: Context, settings: Any) -> int:
    """``nerva config edit`` — the declared settings in ``$VISUAL``/``$EDITOR``; only the
    values that differ afterwards are written, each through ``config set``'s checks, and
    every line that cannot be written is named. A failed editor writes nothing."""
    import contextlib
    import tempfile

    document, editable = _edit_document(settings)
    argv = _editor_argv(ctx.environ)
    fd, temporary = tempfile.mkstemp(prefix="nerva-config-", suffix=".conf")   # owner-only (0600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(document)
        try:
            status = _run_editor(argv, temporary)
        except OSError as exc:
            ctx.err.write(f"editor {_plain(argv[0], 80)} {_editor_failure(exc)} — set $VISUAL or $EDITOR "
                          "to one; nothing changed\n")
            return EXIT_FAILED
        if status != 0:
            ctx.err.write(f"editor exited {status}; nothing changed\n")
            return EXIT_FAILED
        edited = Path(temporary).read_text(encoding="utf-8")
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
    values, rejected = ({}, []) if edited == document else _parse_edit(edited)
    changed: list[str] = []
    for name, value in values.items():
        category, _, key = name.partition(".")
        spec = settings._SPEC.get((category, key))
        if spec is None:
            rejected.append(f"{name}: not a declared setting (see `nerva config list`)")
            continue
        if (category, key) in settings.ROUTE_ONLY:
            rejected.append(f"{name}: changed only in {settings.ROUTE_ONLY[(category, key)]}")
            continue
        if _is_secret({"key": key, "kind": spec.get("kind", "")}):
            rejected.append(f"{name}: a secret — change it with `nerva config set {name} VALUE`")
            continue
        current = editable[name]["value"] if name in editable else spec.get("value")
        if settings._same_value(value, current):
            continue
        errors = settings.validate_category(category, {key: value})
        if errors:
            rejected.append(f"{name}: rejected — {'; '.join(errors)}")
            continue
        refusal = _write_setting(settings, name, category, key, _stamped(category, key, value), ns)
        if refusal:
            rejected.extend(refusal)
            continue
        shown = _shown({"key": key, "kind": spec.get("kind", ""), "value": value}, reveal=False)
        changed.append(f"{name} = {json.dumps(shown, ensure_ascii=False)}  ({_when_applied(category, key, spec)})")
    for line in changed:
        ctx.say(line)
    for line in rejected:
        ctx.err.write(line + "\n")
    if not changed and not rejected:
        ctx.say("nothing changed")
        return EXIT_OK
    ctx.say(f"{len(changed)} setting(s) changed")
    if rejected:
        ctx.err.write(f"{len(rejected)} line(s) rejected — "
                      + ("the rest was written\n" if changed else "nothing written\n"))
        return EXIT_FAILED
    return EXIT_OK


def _config_path(ns: argparse.Namespace, ctx: Context, settings: Any) -> int:
    """``nerva config path`` — where the data lives: the profile, its data root (as
    ``nerva backup`` resolves it) and the settings store the offline verbs read and
    write, with a row count read without touching it (no init, no seeding)."""
    from agents.core.paths import data_root, profile_name

    try:
        root = data_root(ctx.environ)
    except RuntimeError as exc:         # a refused JARVIS_PROFILE
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    store = Path(settings.DB_PATH)
    present = store.exists()
    count: int | None = None
    if present:
        try:
            conn = sqlite3.connect(store.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                count = int(conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0])
            finally:
                conn.close()
        except sqlite3.Error:
            count = None
    profile = profile_name(ctx.environ) or "default"
    if ns.json:
        ctx.dump({"profile": profile, "data_root": str(root), "settings_db": str(store),
                  "settings_db_present": present, "settings_count": count})
        return EXIT_OK
    if not present:
        state = "not created yet — the hub seeds it at first start, or `nerva config migrate`"
    elif count is None:
        state = "present, not readable as a settings store"
    else:
        state = f"present, {count} settings"
    ctx.say(f"{'profile:':<14}{profile}")
    ctx.say(f"{'data root:':<14}{root}")
    ctx.say(f"{'settings db:':<14}{store}  ({state})")
    return EXIT_OK


def _config_env_path(ns: argparse.Namespace, ctx: Context) -> int:
    """``nerva config env-path`` — the ``.env`` files the hub's load reads, in its order
    (the repo's, then the data home's; a profile reads only its own, H689b), the example
    they start from and the secret store. Names and presence only: a value is never read."""
    from agents.core import env_provenance as ep
    from agents.core.env_config import dotenv_disabled
    from agents.core.paths import app_root, data_root, profile_name, user_home

    environ = ctx.environ
    try:
        profile_env = ep.profile_env_file(environ)
        root = data_root(environ)
    except RuntimeError as exc:         # a refused JARVIS_PROFILE
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    profile = profile_name(environ)
    home = user_home(environ)
    home_env = home / ".env" if home is not None else None
    files: list[dict[str, Any]] = []
    if profile_env is not None:
        files.append({"layer": "profile_env", "label": "profile .env", "path": str(profile_env),
                      "present": profile_env.exists(), "read": True,
                      "note": "the only .env a profile's hub reads"})
    shared_note = ep.PROFILE_NOT_READ if profile else None
    files.append({"layer": ep.REPO_ENV, "label": "repo .env", "path": str(ep.REPO_ENV_FILE),
                  "present": ep.REPO_ENV_FILE.exists(), "read": not profile, "note": shared_note})
    files.append({"layer": ep.USER_ENV, "label": "data-home .env",
                  "path": str(home_env) if home_env is not None else None,
                  "present": bool(home_env is not None and home_env.exists()),
                  "read": not profile and home_env is not None,
                  "note": shared_note or (None if home_env is not None else
                                          "no JARVIS_USER_HOME; the packaged app uses ~/Documents/Nerva/.env")})
    # G1 — the administrator's managed .env, applied last, over every file above
    from agents.core import managed_scope

    managed_root = managed_scope.managed_dir(environ)[0]
    if managed_root is not None:
        files.append({"layer": ep.MANAGED, "label": "managed .env", "path": str(managed_root / managed_scope.ENV_FILE),
                      "present": (managed_root / managed_scope.ENV_FILE).exists(), "read": True,
                      "note": "pinned by your administrator, applied last over every other layer"})
    example = app_root() / ".env.example"
    store = root / "security" / "secrets.enc"
    disabled = bool(dotenv_disabled(environ))
    if ns.json:
        ctx.dump({"profile": profile or "default", "files": files, "example": str(example),
                  "secret_store": {"path": str(store), "present": store.exists()},
                  "dotenv_disabled": disabled})
        return EXIT_OK
    for entry in files:
        line = f"{entry['label'] + ':':<17}{entry['path'] or 'none'}"
        if entry["path"]:
            line += f"  ({'present' if entry['present'] else 'absent'})"
        if entry["note"]:
            line += f"  — {entry['note']}"
        ctx.say(line)
    ctx.say(f"{'.env.example:':<17}{example}" + ("" if example.exists() else "  (absent)"))
    ctx.say(f"{'secret store:':<17}{store}  ({'present' if store.exists() else 'absent'})"
            "  — `nerva secrets` reads it")
    if disabled:
        ctx.say("PYTHON_DOTENV_DISABLED is set: no .env file is loaded")
    ctx.say("values are never printed here; `nerva doctor` names which keys each file sets")
    return EXIT_OK


def _describe_change(change: Any, settings: Any) -> str:
    category, _, key = change.setting.partition(".")
    kind = str((settings._SPEC.get((category, key)) or {}).get("kind", ""))
    after = json.dumps(_shown({"key": key, "kind": kind, "value": change.after}, reveal=False), ensure_ascii=False)
    if change.kind == "seed":
        return f"seed     {change.setting} = {after}   ({change.why})"
    if change.kind == "kept":
        return f"kept     {change.setting}   ({change.why})"
    before = json.dumps(_shown({"key": key, "kind": kind, "value": change.before}, reveal=False), ensure_ascii=False)
    return f"{change.kind:<8} {change.setting}: {before} → {after}   ({change.why})"


def _config_migrate(ns: argparse.Namespace, ctx: Context, settings: Any) -> int:
    """``nerva config migrate`` — what this build writes into an existing store (a seed
    for each new setting, a changed shipped default, a retired model id's replacement),
    listed one per line; ``--dry-run`` lists it and writes nothing. A boot does the same
    seeding silently; this is the same work read first, plus the retired-model rewrite on
    every model setting (agents/core/settings_migrate.py)."""
    from agents.core import managed_scope, settings_migrate

    if not ns.dry_run:
        try:            # G1 — managed mode, or an unreadable managed file: nothing is written
            managed_scope.check_writable()
        except managed_scope.ManagedRefused as exc:
            ctx.err.write(f"config migrate: {exc}\n")
            return EXIT_FAILED
    store = Path(settings.DB_PATH)
    try:
        return _config_migrate_run(ns, ctx, settings, settings_migrate, store)
    except sqlite3.OperationalError as exc:
        ctx.err.write(f"{store}: {_busy(exc)}\n")
        return EXIT_FAILED
    except sqlite3.Error as exc:
        ctx.err.write(f"{store} could not be read as a settings store: {exc}\n")
        return EXIT_UNAVAILABLE


def _config_migrate_run(ns: argparse.Namespace, ctx: Context, settings: Any, settings_migrate: Any,
                        store: Path) -> int:
    changes = settings_migrate.plan()
    if changes is None:
        total = len(settings._SPEC)
        if ns.dry_run:
            if ns.json:
                ctx.dump({"dry_run": True, "changes": [], "store": str(store), "would_create": total})
            else:
                ctx.say(f"no settings store at {store}: migrate would create it with all {total} declared "
                        "settings (a hub's first start does the same)")
            return EXIT_OK
        count = settings_migrate.create()
        if ns.json:
            ctx.dump({"dry_run": False, "changes": [], "store": str(store), "created": count})
        else:
            ctx.say(f"created {store} with {count} declared settings")
        return EXIT_OK
    kept = [c for c in changes if c.kind == "kept"]
    planned = [c for c in changes if c.kind != "kept"]
    done = planned if ns.dry_run else settings_migrate.apply(changes)
    if ns.json:
        doc: dict[str, Any] = {"dry_run": bool(ns.dry_run), "changes": [c.to_dict() for c in done],
                               "store": str(store)}
        if kept:
            doc["kept"] = [c.to_dict() for c in kept]
        ctx.dump(doc)
        return EXIT_OK
    for change in [*done, *kept]:
        ctx.say("  " + _describe_change(change, settings))
    if not done:
        ctx.say(f"nothing to migrate: {store} holds every setting of this build")
    elif ns.dry_run:
        ctx.say(f"{len(done)} change(s) would be made — rerun without --dry-run to apply them")
    else:
        ctx.say(f"{len(done)} change(s) applied; a running hub picks them up within 30 s")
    return EXIT_OK


def _payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--payload must be a JSON object")
    return value


def cmd_tools(ns: argparse.Namespace, ctx: Context) -> int:
    """The tool loop's recent trail — the surface the 5a fence writes to.

    Every event the runtime emits used to be discarded (no sink was ever passed), so
    "the model read a page and the turn was tainted" left no trace anywhere the owner
    could look. This is that trace: bounded, in memory, tool names and reasons only.
    """
    client = ctx.client()
    # argparse already supplies the default, so `or 20` would only ever swallow an
    # explicit `-n 0` and quietly ask for twenty instead of the one the bound implies.
    limit = max(1, min(int(ns.lines or 0), 500))
    reply = client.get(f"/api/admin/tool-events?limit={limit}") or {}
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    events = reply.get("events") or []
    if ns.agent:
        events = [e for e in events if e.get("agent_id") == ns.agent]
    if ns.untrusted:
        events = [e for e in events if e.get("event") == "tool_result_untrusted"]
    if not events:
        ctx.say("no tool events yet — the tool loop is off, or nothing has used it")
        return EXIT_OK
    for event in events:
        line = (f"{str(event.get('at', ''))[11:19]}  {event.get('agent_id', '?'):10s}  "
                f"{str(event.get('event', '?')):24s}  {event.get('tool', '')}")
        status = event.get("status")
        if status and status not in ("ok", "requested", "running"):
            line += f"  [{status}]"
        reasons = event.get("reasons")
        if reasons:
            line += f"  reasons={','.join(str(r) for r in reasons)}"
        ctx.say(line)
    counts = reply.get("counts") or {}
    fenced = counts.get("tool_result_untrusted", 0)
    ctx.say(f"{len(events)} shown — since boot: {sum(counts.values())} events, "
            f"{fenced} fenced as untrusted")
    return EXIT_OK


#: `nerva inspect --as` — the inspector's views (agents/core/inspector.py VIEWS, same order).
INSPECT_VIEWS = ("owner", "guest", "inbound-owner", "inbound", "internal")
#: `nerva inspect --section` → the payload's section.
INSPECT_SECTIONS = {"status": "status", "tools": "tools", "skills": "skills", "mcp": "mcp",
                    "prompt": "system_prompt"}


def cmd_inspect(ns: argparse.Namespace, ctx: Context) -> int:
    """H227 — what an agent can do right now, as the chosen principal sees it.

    One read of GET /api/admin/inspector — the payload the HUD's Inspector panel reads —
    rendered section by section; ``--json`` prints it as it came.
    """
    from urllib.parse import urlencode

    query = [("agent", ns.agent), ("view", ns.view)]
    if ns.section:
        query.append(("section", INSPECT_SECTIONS[ns.section]))
    reply = ctx.client().get(f"/api/admin/inspector?{urlencode(query)}") or {}
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    only = INSPECT_SECTIONS[ns.section] if ns.section else None
    for line in render_inspector(reply, only=only):
        ctx.say(line)
    return EXIT_OK


def render_inspector(payload: Mapping[str, Any], *, only: str | None = None) -> list[str]:
    """The inspector payload as text, in the payload's section order (*only*: one section)."""
    if only is not None:
        payload = {k: v for k, v in payload.items() if k in ("agent", "view", "posture", only)}
    lines = [f"{payload.get('agent', '?')} as {payload.get('view', '?')} — posture {payload.get('posture', '?')}"]
    status = payload.get("status")
    if isinstance(status, Mapping):
        loaded = status.get("loaded_model")
        lines.append(
            f"status   nerva {status.get('version', '?')} · backend {status.get('backend', 'none')} · "
            f"model {status.get('model') or '?'} · {status.get('model_state', 'unknown')}"
            + (f" ({loaded})" if loaded else "")
            + f" · context budget {status.get('context_tokens') or '75% of the model window'}"
            + f" · tool loop {'on' if status.get('tool_loop') else 'off'}"
            + (" · SAFE MODE" if status.get("safe_mode") else ""))
    tools = payload.get("tools")
    if isinstance(tools, Mapping):
        offered = list(tools.get("offered") or [])
        withheld = list(tools.get("withheld") or [])
        head = f"tools    {len(offered)} offered of {tools.get('registry', 0)}"
        if not tools.get("wired", True):
            head += " — the tool runtime is not wired"
        elif tools.get("error"):
            head += " — the offer could not be resolved, so nothing is offered"
        elif not tools.get("loop_enabled"):
            head += " — the tool loop is off: none of these reach the model until llm.tool_loop_enabled is on"
        lines.append(head)
        for row in offered:
            marks = [m for m, on in (("gated", row.get("gated")),
                                     ("untrusted output", row.get("untrusted_output"))) if on]
            description = str(row.get("description") or "")
            if len(description) > 60:
                description = description[:59] + "…"
            lines.append(f"  {row.get('name', '?'):22s} {', '.join(marks):24s} {description}".rstrip())
        if withheld:
            lines.append(f"  withheld ({len(withheld)}): {', '.join(withheld)}")
    skills = payload.get("skills")
    if isinstance(skills, Mapping):
        if not skills.get("in_prompt", True):
            lines.append("skills   none in the prompt (llm.skills_in_prompt is off)")
        else:
            lines.append(f"skills   {skills.get('count', 0)} in the prompt")
        for row in skills.get("rows") or []:
            lines.append(f"  {row.get('command', '?'):24s} {row.get('description', '')}".rstrip())
    mcp = payload.get("mcp")
    if isinstance(mcp, Mapping):
        servers = list(mcp.get("servers") or [])
        lines.append(f"mcp      {len(servers)} servers, {mcp.get('connected', 0)} connected")
        for row in servers:
            names = ", ".join(row.get("tool_names") or [])
            lines.append(f"  {row.get('name', '?'):16s} {row.get('transport', ''):16s} {row.get('trust', ''):10s} "
                         f"{'connected' if row.get('connected') else 'down':10s} {row.get('tools', 0)} tools"
                         + (f": {names}" if names else ""))
    prompt = payload.get("system_prompt")
    if isinstance(prompt, Mapping):
        if prompt.get("withheld"):
            lines.append("prompt   withheld: the secret redactor could not be loaded")
        else:
            if prompt.get("resolved") is True:
                model, route = prompt.get("model"), prompt.get("route")
                if isinstance(model, str) and model and isinstance(route, str) and route:
                    lines.append(f"prompt   resolved for model {model} via {route}")
                else:
                    lines.append("prompt   unresolved: route details incomplete")
            elif prompt.get("resolved") is False:
                reason = "route unavailable" if prompt.get("route_error") == "unavailable" else "route not resolved"
                lines.append(f"prompt   unresolved: base system prompt only ({reason})")
            else:
                lines.append("prompt   legacy preview: route resolution not reported; model-specific prompt additions unverified")
            lines.append("prompt   fixed empty user message; active history, user input and tool schemas omitted; cached runtime facts may differ")
            size = f"prompt   {prompt.get('bytes', 0)} bytes, about {prompt.get('tokens', 0)} tokens before any history"
            if prompt.get("truncated"):
                size += f", shown to {prompt.get('cap')}"
            lines += [size, "--- system ---", str(prompt.get("system") or ""),
                      "--- turn (an empty user message) ---", str(prompt.get("turn") or "")]
    return lines


def _valid_consent_offer(offer: Any) -> bool:
    """Only the bounded HUD offer shape earns reusable CLI guidance."""
    if not isinstance(offer, dict):
        return False
    revision = offer.get("revision")
    count = offer.get("count")
    categories = offer.get("categories")
    return (
        isinstance(revision, str) and re.fullmatch(r"[a-f0-9]{64}", revision) is not None
        and type(count) is int and 1 <= count <= 64
        and offer.get("choices") == ["session", "always", "deny"]
        and isinstance(categories, list) and 1 <= len(categories) <= 64
        and all(isinstance(category, dict)
                and isinstance(category.get("description"), str)
                and 1 <= len(category["description"]) <= 500
                and type(category.get("permanent")) is bool
                for category in categories)
    )


_APPROVAL_MODES = ("auto", "ask", "off")


def _approval_mode_note(shown: Any, asked: Any = None) -> str:
    """H484 — the mode line of one approval card: the mode it was asked under when the hub
    recorded one, else the mode in force now (said as such); "" when the hub sent neither
    (an older hub) or something that is not a mode."""
    if isinstance(asked, Mapping) and asked.get("mode") in _APPROVAL_MODES:
        mode, overall = asked["mode"], asked.get("global")
        where = (f"agent override; global {overall}"
                 if asked.get("source") == "agent" and overall in _APPROVAL_MODES else "global")
        why = "the mode is why it waits" if asked.get("by_mode") is True else "the mode is not why it waits"
        return f"asked under mode {mode} ({where}; {why})"
    if not isinstance(shown, Mapping):
        return ""
    effective, overall = shown.get("effective"), shown.get("global")
    if effective not in _APPROVAL_MODES:
        return ""
    if shown.get("source") == "agent" and overall in _APPROVAL_MODES:
        return f"mode now {effective} (agent override; global {overall})"
    return f"mode now {effective} (global)"


def _say_looser_overrides(ctx: Context, reply: Any) -> None:
    """H484 — name the agents whose own override lets them ask less than the global mode."""
    looser = reply.get("looser") if isinstance(reply, Mapping) else None
    names = [f"{agent}: {mode}" for agent, mode in sorted(looser.items())
             if mode in _APPROVAL_MODES] if isinstance(looser, Mapping) else []
    if names:
        ctx.say("a per-agent override asks less than the global mode for: " + ", ".join(names))


def _cmd_approvals_mode(ns: argparse.Namespace, ctx: Context) -> int:
    """``nerva approvals mode [auto|ask|off]`` — the dial the HUD and ``/approvals`` set.
    Every position only adds asking; ``off`` is the strictest, never a bypass."""
    from agents.core.autonomy.mode import parse_requested

    if ns.value is None:
        reply = ctx.client().get("/autonomy/policy")
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        overall = reply.get("global") if isinstance(reply, Mapping) else None
        if overall not in _APPROVAL_MODES:
            ctx.err.write("the hub did not report an approval mode\n")
            return EXIT_FAILED
        ctx.say(f"approval mode: {overall}")
        agents = reply.get("agents")
        for agent, mode in sorted(agents.items()) if isinstance(agents, Mapping) else ():
            if mode in _APPROVAL_MODES:
                ctx.say(f"  {agent}: {mode}" + ("  (ignored while the global mode is off)"
                                                if overall == "off" else ""))
        _say_looser_overrides(ctx, reply)
        return EXIT_OK
    wanted = parse_requested(ns.value)
    if wanted is None:
        ctx.err.write("mode must be auto|ask|off (manual and smart are read as ask and auto)\n")
        return EXIT_USAGE
    client = ctx.client()
    try:
        reply = client.post("/autonomy/mode", {"mode": wanted})
    except HubError as exc:
        if exc.status != 503:
            raise
        # The hub saved nothing, or saved it but runs another mode: say which is in force.
        try:
            now = client.get("/autonomy/policy")
        except (HubError, HubUnavailable):
            now = None
        live = now.get("global") if isinstance(now, Mapping) else None
        if live not in _APPROVAL_MODES:
            ctx.err.write(f"approval mode {wanted} was not confirmed by the hub\n")
        elif live == wanted:
            ctx.err.write(f"approval mode in force: {live} (the hub did not confirm the write; "
                          "check `nerva approvals mode` again)\n")
        else:
            ctx.err.write(f"approval mode in force: {live}; {wanted} did not take effect\n")
        return EXIT_FAILED
    effective = reply.get("mode") if isinstance(reply, Mapping) else None
    if effective != wanted or reply.get("ok") is not True:
        ctx.err.write(f"approval mode {wanted} did not become effective"
                      + (f"; the hub reports {effective}\n" if effective in _APPROVAL_MODES else "\n"))
        return EXIT_FAILED
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    ctx.say(f"approval mode: {effective}")
    _say_looser_overrides(ctx, reply)
    if reply.get("audited") is False:
        ctx.err.write("the change is in effect, but the hub could not record it in the audit log\n")
    return EXIT_OK


def cmd_approvals(ns: argparse.Namespace, ctx: Context) -> int:
    if ns.action == "mode":
        return _cmd_approvals_mode(ns, ctx)
    if ns.action == "list":
        reply = ctx.client().get("/autonomy/approvals")
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        pending = (reply or {}).get("pending") or []
        if not pending:
            ctx.say("no pending approvals")
            return EXIT_OK
        from .chat_prompts import card_safe

        for task in pending:
            flag = "reversible" if task.get("reversible") else "IRREVERSIBLE"
            # G4 review M3: hub and model text without bidi or zero-width marks, so a
            # title cannot reorder or hide what sits beside the accept command.
            ctx.say(
                f"#{card_safe(task.get('id', '?'))[:20]}  tier {card_safe(task.get('risk_tier', '?'))[:8]}  "
                f"{flag:12s}  {card_safe(task.get('kind', '?'))[:80]}  — {card_safe(task.get('title', ''))[:400]}"
            )
            note = _approval_mode_note(task.get("approval_mode"), task.get("asked_under"))
            if note:
                ctx.say(f"  {note}")
            offer = task.get("consent_offer")
            task_id = task.get("id")
            if _valid_consent_offer(offer) and type(task_id) is int and task_id > 0:
                count = offer["count"]
                ctx.say(f"  reusable offer: {count} matching request{'s' if count != 1 else ''}; "
                        "choices session|always|deny")
                for category in offer["categories"]:
                    scope = "" if category["permanent"] else " (session only)"
                    ctx.say(f"    {category['description']}{scope}")
                ctx.say(f"  nerva approvals consent {task_id} --choice session "
                        f"--revision {offer['revision']}")
        ctx.say(f"{len(pending)} pending — `nerva approvals accept|reject|defer <id>`")
        return EXIT_OK
    if ns.action == "consent":
        if ns.task_id <= 0:
            ctx.err.write("task id must be positive\n")
            return EXIT_USAGE
        if re.fullmatch(r"[a-f0-9]{64}", ns.revision) is None:
            ctx.err.write("revision must be 64 lowercase hex characters\n")
            return EXIT_USAGE
        from agents.core.autonomy.decision_reasons import normalize_reason

        try:
            reason = normalize_reason(ns.reason)
        except ValueError as exc:
            ctx.err.write(f"{exc}\n")
            return EXIT_USAGE
        body: dict[str, Any] = {"choice": ns.choice, "revision": ns.revision}
        if reason is not None:
            body["reason"] = reason
        reply = ctx.client().post(f"/autonomy/tasks/{ns.task_id}/consent", body)
        tasks = reply.get("tasks") if isinstance(reply, dict) else None
        if (not isinstance(reply, dict) or reply.get("ok") is not True
                or not isinstance(tasks, list) or not tasks
                or not all(isinstance(task, dict) and task for task in tasks)):
            ctx.err.write("consent was not confirmed by the hub\n")
            return EXIT_FAILED
        if ns.json:
            ctx.dump(reply)
        else:
            ctx.say(f"#{ns.task_id} consent {ns.choice} → {len(tasks)} matching "
                    f"request{'s' if len(tasks) != 1 else ''} decided")
        return EXIT_OK
    try:
        payload = _payload(ns.payload)
    except ValueError as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    from agents.core.autonomy.decision_reasons import normalize_reason

    try:
        reason = normalize_reason(ns.reason)
    except ValueError as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    body: dict[str, Any] = {"action": ns.action}
    if reason is not None:
        body["reason"] = reason
    if payload:
        body["payload"] = payload
    reply = ctx.client().post(f"/autonomy/tasks/{ns.task_id}/decision", body)
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    task = (reply or {}).get("task") or {}
    ctx.say(f"#{ns.task_id} {ns.action}ed → {task.get('status', 'done')}")
    if (isinstance(task, Mapping) and task.get("kind") == "backup.restore"
            and ns.action in ("accept", "edit") and task.get("status") == "approved"):
        _follow_accepted_restore(ctx, ns.task_id)
    return EXIT_OK


_CURATOR_READS = frozenset({"status", "usage", "list-unmanaged", "list-archived", "ledger"})
_CURATOR_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _curator_label(value: Any) -> str:
    """One bounded CLI line, even if the hub returned an unexpected string."""
    return "".join(char if char.isprintable() else "?" for char in str(value))[:160]


def _curator_id(value: Any) -> bool:
    return (type(value) is str and 1 <= len(value) <= 128
            and value not in {".", ".."} and "/" not in value and "\\" not in value
            and all(char.isprintable() for char in value))


def cmd_curator(ns: argparse.Namespace, ctx: Context) -> int:
    """One CLI for the 17 frozen operations; all writes create owner review cards."""
    action = ns.action
    if action in _CURATOR_READS or (action == "rollback" and ns.list):
        view = "backups" if action == "rollback" else action
        filters: dict[str, str] = {}
        for key in ("origin", "sort", "name", "limit"):
            value = getattr(ns, key, None)
            if value is not None:
                if key == "limit" and not 1 <= value <= 200:
                    ctx.err.write("limit must be between 1 and 200\n")
                    return EXIT_USAGE
                if key == "name" and not _curator_id(value):
                    ctx.err.write("skill name must be a bounded identifier\n")
                    return EXIT_USAGE
                filters[key] = str(value)
        path = f"/api/curator/{view}"
        if filters:
            path += "?" + urlencode(filters)
        reply = ctx.client().get(path)
        if not isinstance(reply, Mapping):
            ctx.err.write("curator read unavailable: malformed hub reply\n")
            return EXIT_FAILED
        ctx.dump(reply)
        return EXIT_OK

    args: dict[str, Any] = {}
    if action in {"pin", "unpin", "archive"}:
        if not _curator_id(ns.name):
            ctx.err.write("skill name must be a bounded identifier\n")
            return EXIT_USAGE
        args["name"] = ns.name
    elif action == "adopt":
        if bool(ns.name) == bool(ns.all_unmanaged) or (ns.name and not _curator_id(ns.name)):
            ctx.err.write("choose one bounded skill name or --all-unmanaged\n")
            return EXIT_USAGE
        args = {"name": ns.name} if ns.name else {"all_unmanaged": True}
    elif action == "restore":
        if not _curator_id(ns.archive_id):
            ctx.err.write("archive ID must be a bounded identifier\n")
            return EXIT_USAGE
        args["archive_id"] = ns.archive_id
    elif action in {"prune", "purge"}:
        if ns.days is not None:
            if not 1 <= ns.days <= 36_500:
                ctx.err.write("days must be between 1 and 36500\n")
                return EXIT_USAGE
            args["days"] = ns.days
        if action == "purge" and ns.archive_ids:
            if (len(ns.archive_ids) > 128 or len(set(ns.archive_ids)) != len(ns.archive_ids)
                    or not all(_curator_id(value) for value in ns.archive_ids)):
                ctx.err.write("archive IDs must be unique bounded identifiers (at most 128)\n")
                return EXIT_USAGE
            args["archive_ids"] = ns.archive_ids
    elif action == "backup":
        if ns.reason is not None:
            if len(ns.reason) > 280 or not all(char.isprintable() for char in ns.reason):
                ctx.err.write("backup reason must be at most 280 printable characters\n")
                return EXIT_USAGE
            args["reason"] = ns.reason
    elif action == "rollback":
        value = ns.ledger_id or ns.backup_id
        if value is not None and not _curator_id(value):
            ctx.err.write("rollback ID must be a bounded identifier\n")
            return EXIT_USAGE
        if value is not None:
            args["ledger_id" if ns.ledger_id else "backup_id"] = value
    elif action == "run" and ns.consolidate:
        args["consolidate"] = True

    reviewed = getattr(ns, "preview_fingerprint", None)
    if reviewed is not None and not _CURATOR_SHA256.fullmatch(reviewed):
        ctx.err.write("preview fingerprint must be 64 lowercase hex characters\n")
        return EXIT_USAGE
    body = {"operation": action, "args": args}
    preview = ctx.client().post("/api/curator/preview", body)
    if not isinstance(preview, Mapping) or preview.get("ok") is not True or preview.get("status") != "preview":
        reason = preview.get("reason", "unavailable") if isinstance(preview, Mapping) else "unavailable"
        ctx.err.write(f"curator preview refused: {_curator_label(reason)}\n")
        return EXIT_FAILED
    fingerprint = preview.get("preview_fingerprint")
    if type(fingerprint) is not str or not _CURATOR_SHA256.fullmatch(fingerprint):
        ctx.err.write("curator preview unavailable: missing fingerprint\n")
        return EXIT_FAILED
    if reviewed is not None and reviewed != fingerprint:
        ctx.err.write("curator preview changed; review the current targets before requesting\n")
        return EXIT_FAILED
    if ns.dry_run:
        ctx.dump(preview)
        return EXIT_OK
    outcome = ctx.client().post("/api/curator/request", {**body, "preview_fingerprint": fingerprint})
    if not isinstance(outcome, Mapping) or outcome.get("ok") is not True or outcome.get("status") != "pending":
        reason = outcome.get("reason", "unavailable") if isinstance(outcome, Mapping) else "unavailable"
        ctx.err.write(f"curator request refused: {_curator_label(reason)}\n")
        return EXIT_FAILED
    if ns.json:
        ctx.dump(outcome)
    else:
        targets = preview.get("targets")
        if isinstance(targets, list):
            labels = [_curator_label(item.get("id", item.get("name", "?")) if isinstance(item, Mapping) else item)
                      for item in targets[:20]]
            ctx.say(f"{action}: reviewed {len(targets)} target(s)" + (f" — {', '.join(labels)}" if labels else ""))
        card_id = outcome.get("card_id", outcome.get("request_id", "?"))
        ctx.say(f"approval pending #{_curator_label(card_id)}; decide it in the owner inbox or `nerva approvals list`")
    return EXIT_OK


#: How long ``nerva approvals accept`` waits for an accepted restore to be staged, and
#: how often it asks (H010 review r6). The hub's loop runs the accept after the reply, on
#: its next tick — so the answer never depends on the stage showing up in this window (r7).
RESTORE_FOLLOW_SECONDS = 8.0
RESTORE_FOLLOW_POLL_SECONDS = 0.5


def _restore_of_task(reply: Any, task_id: int) -> tuple[str, Mapping[str, Any]] | None:
    """What ``GET /api/admin/backup`` says about the restore task ``task_id`` accepted:
    ``("staged", view)``, ``("finished", last_restore)`` or ``("refused", row)``, or None
    when nothing yet."""
    if not isinstance(reply, Mapping):
        return None
    staged = reply.get("pending_restore")
    if isinstance(staged, Mapping) and staged.get("task_id") == task_id:
        return "staged", staged
    last = reply.get("last_restore")
    if (isinstance(last, Mapping) and last.get("task_id") == task_id
            and last.get("status") != "deferred"):
        return "finished", last
    refused = reply.get("refused_restore")
    if isinstance(refused, Mapping) and refused.get("task_id") == task_id:
        return "refused", refused
    return None


def _say_accepted_restore(ctx: Context, reply: Any) -> bool:
    """H010 review r7: say at once how the hub applies the accept — the hub's worker stages
    it only on its next tick (60 s by default), far past the follow window. True when said."""
    if not isinstance(reply, Mapping) or reply.get("restart") not in ("self", "manual"):
        return False                                      # a hub that predates r7
    tick = reply.get("stage_within_seconds")
    when = (f"on its next autonomy tick (within ~{tick} s)"
            if isinstance(tick, int) and not isinstance(tick, bool) else "on its next autonomy tick")
    if reply["restart"] == "manual":
        ctx.say(f"  restore accepted, NOT applied yet: the hub stages it {when}, and nothing "
                f"restarts this hub — restart the hub/service yourself once `nerva backup list` "
                f"shows it staged (it says by when)")
    else:
        ctx.say(f"  restore accepted: the hub stages it {when} and restarts itself to apply it "
                f"(`nerva backup list` shows the outcome)")
    return True


def _follow_accepted_restore(ctx: Context, task_id: int) -> None:
    """H010 review r6/r7: the decision route answers ``approved`` before the hub's loop
    stages the restore. Say right away what happens (NOT applied yet when the hub cannot
    restart itself), then wait a bounded few seconds for the stage, an outcome or a refusal
    and add it — never a restart nobody makes, never a stage that will not come."""
    end = time.monotonic() + RESTORE_FOLLOW_SECONDS
    announced = False
    while True:
        try:
            reply = ctx.client().get("/api/admin/backup")
        except HubUnavailable:
            # The hub went away right after the accept: most likely restarting to apply it.
            ctx.say("  the hub stopped answering (restarting to apply the restore?) — "
                    "`nerva backup list` shows whether it was applied")
            return
        except HubError:
            reply = None
        found = _restore_of_task(reply, task_id)
        if found is None and not announced:
            announced = _say_accepted_restore(ctx, reply)
        if found is not None:
            break
        if time.monotonic() >= end:
            if not announced:
                ctx.say("  the restore is not staged yet — `nerva backup list` shows when it is, "
                        "and whether the hub must be restarted by hand")
            return
        time.sleep(RESTORE_FOLLOW_POLL_SECONDS)
    state, view = found
    if state == "refused":
        ctx.say(f"  restore of {view.get('name')} refused ({view.get('reason')}): it will not "
                f"be applied — request it again with `nerva backup restore`")
    elif state == "finished":
        ctx.say(f"  restore of {view.get('name')}: {view.get('status')}")
    elif view.get("action_needed"):
        # The accept staged the restore but nothing restarts this hub.
        ctx.say(f"  restore of {view.get('name')} staged, NOT applied yet: {view['action_needed']}")
    elif view.get("state") == "expired":
        ctx.say(f"  restore of {view.get('name')} staged but expired: it will not be applied")
    elif view.get("restart") == "self":
        ctx.say(f"  restore of {view.get('name')} staged; the hub restarts itself to apply it "
                f"(`nerva backup list` shows the outcome)")
    else:
        ctx.say(f"  restore of {view.get('name')} staged ({view.get('state')}) — "
                f"`nerva backup list` shows when it is applied")


_CHECKPOINT_NOTICE_CODES = frozenset({
    "checkpoint.complete", "checkpoint.preview", "checkpoint.queued",
    "checkpoint.refused", "checkpoint.unavailable", "checkpoint.partial",
})
_CHECKPOINT_SUCCESS_CODES = frozenset({"checkpoint.complete", "checkpoint.preview"})


def _checkpoint_identifier(value: object) -> bool:
    if type(value) is not str or not 1 <= len(value) <= 64:
        return False
    if re.fullmatch(r"file:[1-9][0-9]*|group:[0-9a-f]{32}", value):
        return True
    return bool(re.fullmatch(r"[1-9][0-9]*", value)) and int(value) <= 500


def _checkpoint_path(value: object) -> bool:
    if (type(value) is not str or not 1 <= len(value) <= 4096
            or value.startswith("/") or "\\" in value
            or re.match(r"^[A-Za-z]:", value)
            or any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in value)):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def cmd_checkpoints(ns: argparse.Namespace, ctx: Context) -> int:
    """Forward a fixed owner command; only the hub's checkpoint notice decides success."""
    action = ns.action or "status"
    project = getattr(ns, "project", None)
    if project is not None and (
        not isinstance(project, str) or not project.strip() or len(project) > 4096
        or any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in project)
    ):
        ctx.err.write("project must be nonempty, at most 4096 characters, without controls\n")
        return EXIT_USAGE
    limit = getattr(ns, "limit", None)
    if limit is not None and not 1 <= limit <= 500:
        ctx.err.write("limit must be between 1 and 500\n")
        return EXIT_USAGE
    identifier = getattr(ns, "identifier", None)
    if action in {"diff", "restore"} and not _checkpoint_identifier(identifier):
        ctx.err.write("checkpoint ID must be canonical file/group ID or ordinal 1..500\n")
        return EXIT_USAGE
    paths = getattr(ns, "paths", None) or []
    if len(paths) > 500 or len(set(paths)) != len(paths) or not all(
        _checkpoint_path(path) for path in paths
    ):
        ctx.err.write("paths must be unique canonical relative paths (at most 500)\n")
        return EXIT_USAGE
    if paths and isinstance(identifier, str) and identifier.startswith("file:"):
        ctx.err.write("--path selects group members, not a file checkpoint\n")
        return EXIT_USAGE
    execute = bool(getattr(ns, "execute", False))
    force = bool(getattr(ns, "force", False))
    keep_last = getattr(ns, "keep_last", None)
    max_bytes = getattr(ns, "max_bytes", None)
    if keep_last is not None and not 1 <= keep_last <= 5_000:
        ctx.err.write("keep-last must be between 1 and 5000\n")
        return EXIT_USAGE
    if max_bytes is not None and not 1 <= max_bytes <= 1 << 40:
        ctx.err.write("max-bytes must be between 1 and 1099511627776\n")
        return EXIT_USAGE
    include_orphans = bool(getattr(ns, "include_orphans", False))

    tokens = ["/checkpoints", action]
    if identifier is not None:
        tokens.append(identifier)
    if project is not None:
        tokens.extend(("--project", project))
    if limit is not None:
        tokens.extend(("--limit", str(limit)))
    if keep_last is not None:
        tokens.extend(("--keep-last", str(keep_last)))
    if max_bytes is not None:
        tokens.extend(("--max-bytes", str(max_bytes)))
    if include_orphans:
        tokens.append("--include-orphans")
    for path in paths:
        tokens.extend(("--path", path))
    if action in {"prune", "clear", "clear-legacy", "restore"}:
        tokens.append("--execute" if execute else "--dry-run")
    if force:
        tokens.append("--force")
    command = " ".join(shlex.quote(token) for token in tokens)
    if len(command.partition(" ")[2]) > 2_000:
        ctx.err.write("checkpoint command is too long\n")
        return EXIT_USAGE
    reply = ctx.client().post("/chat", {"message": command})
    if not isinstance(reply, Mapping):
        ctx.err.write("checkpoint result unavailable: malformed hub reply\n")
        return EXIT_FAILED

    pending = reply.get("pending_approvals", [])
    if not isinstance(pending, (list, tuple)):
        ctx.err.write("checkpoint result unavailable: approval IDs unreadable; run `nerva approvals list`\n")
        return EXIT_FAILED
    valid_ids = [value for value in pending if type(value) is int and value > 0]
    if pending:
        ids = ", ".join(f"#{value}" for value in dict.fromkeys(valid_ids))
        malformed = len(valid_ids) != len(pending) or len(set(valid_ids)) != len(valid_ids)
        detail = f" ({ids})" if ids else ""
        suffix = "; approval IDs partly unreadable" if malformed else ""
        ctx.err.write(f"checkpoint request queued for approval{detail}{suffix}; "
                      "run `nerva approvals list`\n")
        return EXIT_FAILED

    notices = reply.get("notices")
    if not isinstance(notices, list):
        ctx.err.write("checkpoint result unavailable: no status notice\n")
        return EXIT_FAILED
    checkpoint_notices = [item for item in notices if isinstance(item, Mapping)
                          and isinstance(item.get("code"), str)
                          and item["code"].startswith("checkpoint.")]
    if len(checkpoint_notices) != 1:
        ctx.err.write("checkpoint result unavailable: missing or ambiguous status notice\n")
        return EXIT_FAILED
    notice = checkpoint_notices[0]
    code = notice["code"]
    raw_text = notice.get("text")
    if (code not in _CHECKPOINT_NOTICE_CODES or not isinstance(raw_text, str)
            or not raw_text.strip() or len(raw_text) > 16_000):
        ctx.err.write("checkpoint result unavailable: malformed status notice\n")
        return EXIT_FAILED
    message = _answer_text(raw_text).strip()
    if not message:
        ctx.err.write("checkpoint result unavailable: empty status notice\n")
        return EXIT_FAILED
    if code in _CHECKPOINT_SUCCESS_CODES:
        _write_answer(ctx, message)
        return EXIT_OK
    ctx.err.write(message + "\n")
    return EXIT_FAILED


#: What an offline in-place restore must be told, typed (the forget route's "FORGET" shape).
_RESTORE_WORD = "RESTORE"


def _backup_row(row: Mapping[str, Any]) -> str:
    tags = [tag for tag, on in (("quick", row.get("quick")), ("encrypted", row.get("encrypted"))) if on]
    return f"  {row['name']}  {row['bytes']:>12,d} B  {row['modified_at']}" + (f"  [{', '.join(tags)}]" if tags else "")


def cmd_backup(ns: argparse.Namespace, ctx: Context) -> int:
    """H010 — back up and restore the install. create/list/verify read the data root the
    hub uses (a DB snapshot is consistent while the hub runs); restore crosses the
    irreversible tier: with a hub running it is a ``backup.restore`` approval card the
    hub applies by restarting itself, and with none running it needs RESTORE typed."""
    from agents.core import backup as bk
    from agents.core.paths import data_root

    root = data_root(ctx.environ)
    out = bk.default_backup_dir(root)
    if ns.action == "create":
        made = bk.create_backup(source_root=str(root), out_dir=str(out), label=ns.label,
                                encrypt=True if ns.encrypt else None, quick=ns.quick)
        if ns.json:
            ctx.dump(made)
        else:
            ctx.say(f"{made['mode']} backup {Path(made['archive']).name}: {made['file_count']} file(s), "
                    f"{len(made['dbs'])} DB(s), {made['bytes']:,d} B"
                    + (" (encrypted)" if made["encrypted"] else ""))
        return EXIT_OK
    if ns.action == "list":
        payload = {"backups": bk.list_backups(str(out)), "pending_restore": bk.staged_restore_view(root),
                   "last_restore": bk.last_restore(root),
                   "refused_restore": bk.last_refused_restore(root)}
        if ns.json:
            ctx.dump(payload)
            return EXIT_OK
        if not payload["backups"]:
            ctx.say("no backup has ever been made — `nerva backup create`")
        for row in payload["backups"]:
            ctx.say(_backup_row(row))
        staged = payload["pending_restore"]
        if staged:
            if staged.get("state") == "deferred":
                note = f"deferred: {staged.get('deferred_reason')}"
            elif staged.get("state") == "expired":
                note = "expired: it is discarded, never applied — stage it again"
            else:
                note = f"applied at the next hub start; expires {staged.get('expires_at')}"
            ctx.say(f"staged restore: {staged['name']} ({note}) — `nerva backup cancel` withdraws it")
            if staged.get("action_needed"):
                ctx.say(f"  ACTION NEEDED: the hub could not restart itself — {staged['action_needed']}")
            if staged.get("runtime_resumed_at"):
                ctx.say(f"  not applied in time: jarvis-runtime resumed at {staged['runtime_resumed_at']} "
                        f"and stops again when the hub applies it")
        if payload["last_restore"]:
            last = payload["last_restore"]
            ctx.say(f"last restore: {last.get('name')} {last.get('status')} at {last.get('applied_at')}")
        if payload["refused_restore"]:
            # H010 review r7: an accept the apply refused staged nothing; it must be asked again.
            refused = payload["refused_restore"]
            ctx.say(f"refused restore: {refused.get('name')} ({refused.get('reason')}) at "
                    f"{refused.get('at')} — not applied; `nerva backup restore` asks again")
        return EXIT_OK
    if ns.action == "verify":
        name = ns.name
        if not name:
            listing = bk.list_backups(str(out))
            if not listing:
                ctx.err.write("no backups to verify\n")
                return EXIT_FAILED
            name = listing[0]["name"]
        path = bk.resolve_backup(name, out_dir=str(out))
        if path is None:
            ctx.err.write(f"no such backup: {name}\n")
            return EXIT_FAILED
        try:
            report = bk.verify_backup(str(path))
        except (ValueError, OSError) as exc:   # ArchiveRejected is a ValueError
            ctx.err.write(f"archive rejected: {exc}\n")
            return EXIT_FAILED
        if ns.json:
            ctx.dump(report)
        else:
            ctx.say(f"{path.name}: {'ok' if report['ok'] else 'FAILED'} — {report['file_count']} file(s), "
                    + ", ".join(f"{db} {verdict}" for db, verdict in report["dbs"].items())
                    + (f"; {report['problem']}" if report["problem"] else ""))
        return EXIT_OK if report["ok"] else EXIT_FAILED
    if ns.action == "cancel":
        result = bk.cancel_staged_restore(root, cancelled_by="nerva-cli")
        if ns.json:
            ctx.dump(result)
        elif result["ok"]:
            ctx.say(f"cancelled the staged restore of {result['cancelled']}")
        elif result.get("reason") == "applying":
            ctx.err.write("the restore is being applied right now and can no longer be cancelled\n")
        else:
            ctx.err.write("no staged restore to cancel\n")
        return EXIT_OK if result["ok"] else EXIT_FAILED
    return _backup_restore(ns, ctx, bk, root)


def _backup_restore(ns: argparse.Namespace, ctx: Context, bk: Any, root: Path) -> int:
    try:
        reply = ctx.client().post("/api/admin/backup/restore", {"name": ns.name})
    except HubUnavailable:
        reply = None
    if reply is not None:
        task_id = (reply or {}).get("pending") if isinstance(reply, Mapping) else None
        if type(task_id) is not int:
            ctx.err.write("restore result unavailable: malformed hub reply\n")
            return EXIT_FAILED
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        queued = (f"restore of {ns.name} queued at the irreversible tier as approval #{task_id}"
                  + (" (already waiting)" if reply.get("existing") else "")
                  + f". Accept it with `nerva approvals accept {task_id}`: the hub stages it")
        if reply.get("restart") == "self":
            ctx.say(queued + ", restarts itself and restores before any store opens.")
        else:
            # H010 review r5: a hub without a self-restart (raw uvicorn, a Windows service
            # without the NSSM marker), or one too old to say — never promise a restart.
            ttl = bk.stage_ttl_seconds() / 3600.0
            ctx.say(queued + ", but this hub cannot restart itself: after the accept, restart "
                    "the hub/service yourself — the restore is applied at the next `python "
                    "serve.py` (service, nerva.exe) start, before any store opens. The stage "
                    f"expires {ttl:g} h after the accept (`nerva backup list` shows when).")
        return EXIT_OK
    # No hub: nothing holds the DBs open, so the restore can run now — but the approval
    # queue that would ask a human is not running either, so the human is asked here.
    tier = f"tier 3 ({_TIER_NAMES[3]})"
    if ns.confirm != _RESTORE_WORD:
        typed = ""
        if _is_tty(ctx.inp):
            ctx.err.write(f"backup.restore is {tier}: it overwrites the live data root at {root}. "
                          f"Type {_RESTORE_WORD} to continue: ")
            typed = (ctx.inp.readline() or "").strip()
        if typed != _RESTORE_WORD:
            ctx.err.write(f"not restored: backup.restore is {tier} — no hub is running to queue it for "
                          f"approval, so rerun with --confirm {_RESTORE_WORD} to restore in place now\n")
            return EXIT_USAGE
    try:
        staged = bk.stage_restore(ns.name, source_root=str(root), requested_by="nerva-cli")
    except FileNotFoundError:
        ctx.err.write(f"no such backup: {ns.name}\n")
        return EXIT_FAILED
    if not staged["ok"]:
        ctx.err.write(f"not restored: {staged['name']} failed its restore drill: {staged['problem']}\n")
        return EXIT_FAILED
    result = bk.apply_pending_restore(root) or {}
    if ns.json:
        ctx.dump(result)
    elif result.get("status") == "restored":
        ctx.say(f"restored {result['name']} in place: {result['file_count']} file(s); "
                f"rollback point {result.get('rollback')}"
                + ("" if result.get("ok") else f"; the drill found a problem: {result.get('problem')}"))
    elif result.get("status") == "deferred":
        ctx.say(f"staged {staged['name']}, deferred: {result['reason']} — it is applied at the next "
                f"hub start (python serve.py) once no other process has the data root open, unless "
                f"it expires first ({staged.get('expires_at')}); `nerva backup cancel` withdraws it")
    else:
        ctx.err.write(f"restore of {ns.name} failed ({result.get('reason')}): {result.get('detail', '')}\n")
    return EXIT_OK if result.get("status") in ("restored", "deferred") and result.get("ok", True) else EXIT_FAILED


def explain_action(
    kind: str,
    *,
    title: str = "",
    payload: Mapping[str, Any] | None = None,
    tier: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Replay the kernel's gates for one action, statically, from this box's data root.

    The same functions the hub uses (`autonomy.dry_run.preview_task`, the policy's tier
    classification, the mediation registry, the e-stop sentinel), without executing
    anything. What it cannot see: the running hub's live state — per-agent modes, money
    spent today, capability tokens — so the verdict is the *floor*, never a promise.
    """
    from agents.core import estop
    from agents.core.autonomy.dry_run import preview_task
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.kernel.registry import classify

    task: dict[str, Any] = {"kind": kind, "title": title, "payload": dict(payload or {})}
    if tier is not None:
        task["risk_tier"] = tier
    policy = AutonomyPolicy()
    classified = int(policy.classify({**task, **task["payload"]}))
    preview = preview_task({**task, "risk_tier": tier if tier is not None else classified})
    mediation = classify(kind)
    estop_state = estop.get_state()
    from agents.core.autonomy.mode import read_mode

    # H484: the stored value as the policy reads it (unknown → ask, boolean False → off).
    mode = read_mode(_settings().get_value("autonomy", "mode", "auto"))
    # The policy's modes: "auto" — per-tier outcomes; "ask" — anything with a side effect
    # waits (pure reads still act); "off" — everything waits.
    if mode == "off":
        approval_required = True
    elif mode == "ask":
        approval_required = bool(preview["requires_approval"]) or classified >= 1
    else:
        approval_required = bool(preview["requires_approval"])
    if estop_state is not None:
        verdict = "DENY — emergency stop engaged"
    elif mediation is None:
        verdict = (
            "NO BROKER — no component of Nerva emits this kind; the gates above are what "
            "it would face if one did"
        )
    elif approval_required:
        verdict = "QUEUE — waits in the approval inbox"
    else:
        verdict = "GRANT — runs, audited"
    if mediation is not None and mediation.value == "pending":
        verdict += " (broker not yet routed through kernel.authorize; the approval floor still holds)"
    path = [
        {"gate": "kill-switch", "result": "engaged" if estop_state else "clear"},
        {"gate": "mediation", "result": mediation.value if mediation is not None else "unregistered"},
        {"gate": "risk tier", "result": f"{classified} ({_TIER_NAMES.get(classified, '?')})"},
        {"gate": "irreversible", "result": "yes" if preview["irreversible"] else "no"},
        {"gate": "autonomy mode", "result": str(mode)},
        {"gate": "approval", "result": "required" if approval_required else "not required"},
    ]
    return {
        "kind": kind,
        "title": title,
        "effects": preview["effects"],
        "mediation": mediation.value if mediation is not None else None,
        "risk_tier": classified,
        "irreversible": preview["irreversible"],
        "autonomy_mode": mode,
        "estop": estop_state,
        "approval_required": approval_required,
        "verdict": verdict,
        "path": path,
        "note": "static replay from this data root; the running hub's live policy, spend and tokens may tighten this, never loosen it",
    }


def cmd_kernel(ns: argparse.Namespace, ctx: Context) -> int:
    try:
        payload = _payload(ns.payload)
    except ValueError as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    result = explain_action(ns.kind, title=ns.title, payload=payload, tier=ns.tier, environ=ctx.environ)
    if ns.json:
        ctx.dump(result)
        return EXIT_OK
    ctx.say(f"kernel explain: {ns.kind}")
    for step in result["path"]:
        ctx.say(f"  {step['gate']:14s} {step['result']}")
    if result["effects"]:
        ctx.say("  effects:       " + ", ".join(f"{e['field']}={e['value']}" for e in result["effects"]))
    ctx.say(f"  → {result['verdict']}")
    ctx.say(f"  ({result['note']})")
    return EXIT_OK


def log_path(environ: Mapping[str, str]) -> Path:
    explicit = (environ.get("JARVIS_LOG_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    from agents.core.paths import data_path

    return data_path("logs", "jarvis.log")


def _log_display(value: Any, width: int = 200, *, keep_tail: bool = False) -> str:
    """Printable log filename/error text, including bidi and surrogate-safe names."""
    visible = re.sub(r"[\u202a-\u202e\u2066-\u2069]", "", str(value))
    visible = visible.encode("utf-8", "backslashreplace").decode("utf-8")
    return _plain(visible, width, keep_tail=keep_tail)


def _job_note_display(value: str) -> str:
    """Preserve a bounded note's line breaks while removing terminal controls and bidi marks."""
    visible = re.sub(r"[\u202a-\u202e\u2066-\u2069]", "", value)
    visible = visible.encode("utf-8", "backslashreplace").decode("utf-8")
    return "\n".join(_plain(line, len(line) + 1) for line in visible.split("\n"))


def _skill_files(raw: str) -> list[Path] | None:
    """The SKILL.md files *raw* names: itself, a skill folder's, or each skill folder's."""
    path = Path(raw)
    if path.is_file():
        return [path]
    if not path.is_dir():
        return None
    if (path / "SKILL.md").is_file():
        return [path / "SKILL.md"]
    return sorted(p for p in path.glob("*/SKILL.md") if p.is_file())


def cmd_skills(ns: argparse.Namespace, ctx: Context) -> int:
    """H350 — ``nerva skills lint``: the hard check every write path runs, plus advice.
    H329 — ``nerva skills list | off | on | config``: running-hub skill switches.
    H354 — ``nerva skills verify``: run one skill's reality-harness case on the hub.
    H026 — ``nerva skills bundles list|show|create|delete|reload``: named skill bundles.
    H349 — ``nerva skills pin | unpin``: the owner's pin, and where each skill came from
    in ``nerva skills list``.
    H336 — ``nerva skills catalog [install|repair]``: the vendored Hermes skill catalog."""
    if ns.action in ("list", "off", "on", "config"):
        return _skill_switches(ns, ctx)
    if ns.action in ("pin", "unpin"):
        return _skill_pin(ns, ctx)
    if ns.action == "verify":
        return _skill_verify(ns, ctx)
    if ns.action == "bundles":
        return _skill_bundles(ns, ctx)
    if ns.action == "catalog":
        return _skill_catalog(ns, ctx)
    from agents.core.skills.validate import (
        MAX_SKILL_MD_BYTES,
        Problem,
        lint_skill_md,
        validate_skill_md,
    )

    files: list[Path] = []
    for raw in ns.paths:
        found = _skill_files(raw)
        if found is None:
            ctx.err.write(f"no such file or folder: {raw}\n")
            return EXIT_USAGE
        if not found:
            ctx.err.write(f"no SKILL.md in {raw} or in the folders directly under it\n")
            return EXIT_USAGE
        files.extend(found)
    report, errors, advice = [], 0, 0
    for path in dict.fromkeys(files):
        try:
            with open(path, "rb") as handle:
                data = handle.read(MAX_SKILL_MD_BYTES + 1)     # past the cap is an error anyway
                size = os.fstat(handle.fileno()).st_size
        except OSError as exc:
            problems, findings = [Problem("document", f"cannot be read ({exc.strerror or exc})")], []
        else:
            problems = validate_skill_md(data)
            findings = lint_skill_md(data, folder=path.parent.name)
            if len(data) > MAX_SKILL_MD_BYTES:
                # Only the cap's worth was read: the size is the file's (review-H350 F10).
                problems = [Problem("document", f"{max(size, len(data)):,} bytes; at most {MAX_SKILL_MD_BYTES:,}")]
        errors += len(problems)
        advice += len(findings)
        report.append({"path": str(path), "errors": [p.as_dict() for p in problems],
                       "advice": [p.as_dict() for p in findings]})
    if ns.json:
        ctx.dump(report)
    else:
        for entry in report:
            if not entry["errors"] and not entry["advice"]:
                ctx.out.write(f"{entry['path']}: ok\n")
                continue
            ctx.out.write(f"{entry['path']}:\n")
            for kind, items in (("error ", entry["errors"]), ("advice", entry["advice"])):
                for item in items:
                    line = f" (line {item['line']})" if "line" in item else ""
                    ctx.out.write(f"  {kind} {item['field']}: {item['message']}{line}\n")
        ctx.out.write(f"{len(report)} file{'s' if len(report) != 1 else ''}: {errors} error"
                      f"{'s' if errors != 1 else ''}, {advice} advice\n")
    return EXIT_FAILED if errors or (ns.strict and advice) else EXIT_OK


def cmd_logs(ns: argparse.Namespace, ctx: Context) -> int:
    positional_name = getattr(ns, "name", None)
    exact_name = getattr(ns, "exact_name", None)
    if positional_name is not None and exact_name is not None:
        ctx.err.write("choose one log name: positional NAME or --name NAME\n")
        return EXIT_USAGE
    name = exact_name if exact_name is not None else positional_name
    path = log_path(ctx.environ)
    from agents.core import log_tail

    files = log_tail.list_files(path)
    if positional_name == "list":
        if not files:
            ctx.say("no log files for the configured hub log")
        else:
            for item in files:
                ctx.say(f"{_log_display(item['name'], 120)}  {item['size']} bytes  "
                        f"modified {item['modified']}")
        return EXIT_OK
    if not files:
        if path.exists():
            ctx.err.write(f"{_log_display(path, 200, keep_tail=True)} could not be read "
                          "(not a regular log file)\n")
            return EXIT_FAILED
        ctx.err.write(
            f"no log file at {_log_display(path, 200, keep_tail=True)} — file logging is off unless system.log_to_file is on "
            "(`nerva config set system.log_to_file on`) or JARVIS_LOG_FILE is set\n"
        )
        return EXIT_FAILED
    allowed = {item["name"] for item in files}
    if name is not None and name not in allowed:
        available = ", ".join(_log_display(item["name"], 120) for item in files[:10])
        more = " …" if len(files) > 10 else ""
        ctx.err.write(f"no configured log named {_log_display(name, 120)}; available: {available}{more}\n")
        return EXIT_FAILED
    chosen = files[0]["name"] if name is None else name
    selected = path.parent / chosen
    # H145: read from the end within a byte budget and redacted again, as the HUD's log
    # page reads it; a multi-gigabyte log costs the same as a small one.
    if ns.lines <= 0:
        return EXIT_OK
    try:
        tail = log_tail.read_path(selected, lines=ns.lines, cap=max(ns.lines, 1))
    except log_tail.RedactionUnavailable as exc:
        ctx.err.write(f"the secret redactor could not be loaded ({_log_display(exc)}); the log is not shown\n")
        return EXIT_FAILED
    except OSError as exc:
        ctx.err.write(f"{_log_display(selected, 200, keep_tail=True)} could not be read "
                      f"({_log_display(exc.strerror or exc.__class__.__name__)})\n")
        return EXIT_FAILED
    for entry in tail["entries"]:
        ctx.say(entry["text"])
    if tail["truncated"] and len(tail["entries"]) < ns.lines:
        ctx.err.write(f"(only the last {tail['scanned_bytes'] // 1024} KiB of "
                      f"{_log_display(selected, 200, keep_tail=True)} were read)\n")
    return EXIT_OK


def _skill_usage_suffix(usage: Any) -> str:
    """H354 — `` · used 3× (last 2026-10-20 08:15 UTC) · patched 1×``, or `` · never used``;
    nothing when the hub reports no counters (an older hub)."""
    if not isinstance(usage, Mapping):
        return ""
    try:
        used, patched = int(usage.get("use_count") or 0), int(usage.get("patch_count") or 0)
    except (TypeError, ValueError):
        return ""
    if not used:
        # Edited but never run (an owner batch, an approved proposal): say so, don't hide it.
        return f" · never used · patched {patched}×" if patched else " · never used"
    text = f" · used {used}×"
    last = usage.get("last_used_at")
    if isinstance(last, str) and last:
        from datetime import UTC, datetime

        try:
            when = datetime.fromisoformat(last)
            when = when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)
            text += f" (last {when.strftime('%Y-%m-%d %H:%M')} UTC)"
        except ValueError:
            text += f" (last {last})"
    if patched:
        text += f" · patched {patched}×"
    return text


def _skill_origin_suffix(usage: Any) -> str:
    """H349 — `` · import (hermes) · pinned``: where the hub recorded the skill came from,
    and the owner's pin. Nothing for an older hub, or for an origin it never recorded."""
    if not isinstance(usage, Mapping):
        return ""
    origin = usage.get("origin")
    text = ""
    if isinstance(origin, str) and origin and origin != "unknown":
        text = f" · {_plain(origin, 20)}"
        source = usage.get("source")
        if isinstance(source, str) and source:
            text += f" ({_plain(source, 64)})"
        # Both facts when both are true: agent-made, and an install record in its folder.
        if usage.get("agent_created") is True and origin != "agent":
            text += " · agent-made"
        if usage.get("agent_created") is True and usage.get("write_origin") == "assistant_tool":
            text += " · made in a turn, not curated"
    if usage.get("pinned") is True:
        text += " · pinned"
    return text


def _skill_pin(ns: argparse.Namespace, ctx: Context) -> int:
    """H349 — ``nerva skills pin|unpin NAME``: the hub's ``POST /api/skills/pin``. A
    refusal (no such skill, a skill that ships with Nerva, a sidecar that could not be
    written) is the hub's error and a failed exit, never a printed success."""
    wanted = ns.action == "pin"
    reply = ctx.client().post("/api/skills/pin", {"skill": ns.name, "pinned": wanted})
    if not isinstance(reply, Mapping) or reply.get("ok") is not True or reply.get("pinned") is not wanted:
        ctx.err.write("unexpected reply from the hub: the pin was not confirmed\n")
        return EXIT_FAILED
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    name = _plain(reply.get("skill") or ns.name, 130)
    if not reply.get("changed"):
        ctx.say(f"{name}: already {'pinned' if wanted else 'not pinned'}")
        return EXIT_OK
    if wanted:
        ctx.say(f"pinned {name}: the curator leaves it alone, and neither an agent's batch nor the journey's "
                "forget deletes it; your own delete, uninstall or reject still removes it")
    else:
        ctx.say(f"unpinned {name}")
    if not reply.get("audited"):
        ctx.say("note: the intent log could not record this change")
    return EXIT_OK


def _skill_verify(ns: argparse.Namespace, ctx: Context) -> int:
    """H354 — ``nerva skills verify <name>``: the hub runs the reality harness's case for
    that skill now; a green probe marks its capability record VERIFIED until the hub's
    next boot, a red one leaves it ref-only. Exit 1 on a red probe, so a script can tell."""
    from urllib.parse import quote

    reply = ctx.client().post(f"/api/capabilities/skills/{quote(ns.name, safe='')}/verify", {})
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK if isinstance(reply, dict) and reply.get("passed") is True else EXIT_FAILED
    if not isinstance(reply, dict) or "passed" not in reply:
        ctx.err.write("unexpected reply from the hub: no verdict in it\n")
        return EXIT_FAILED
    record = reply.get("record") if isinstance(reply.get("record"), dict) else {}
    passed = bool(reply.get("passed"))
    ctx.say(f"{reply.get('skill') or ns.name}: {'passed' if passed else 'FAILED'} — "
            f"{reply.get('detail', '')} ({reply.get('ref', '')})")
    when = f", verified at {reply['verified_at']}" if reply.get("verified_at") else ""
    ctx.say(f"  record {record.get('state', '?')}{when}; the verdict lives until the hub's next boot")
    return EXIT_OK if passed else EXIT_FAILED


_CATALOG_INSTALL_PATH = "/api/skills/catalog/install"


def _skill_catalog(ns: argparse.Namespace, ctx: Context) -> int:
    """H336 — ``nerva skills catalog``: Hermes's ``skills browse --source official`` (the
    catalog rows of ``GET /skills/imported``, filtered here and capped at 100 like Hermes),
    ``install`` and ``repair`` (``POST /api/skills/catalog/install``, admin, no DEV_MODE: the
    vendored catalog is pinned, byte-verified and instruction-only). A skill that carries
    code is listed with its code files and refused by the hub."""
    from agents.core.skills import hermes_catalog

    action = getattr(ns, "catalog_action", None)
    if action in ("install", "repair"):
        body = {"skill": ns.skill, "repair": action == "repair", "force": bool(getattr(ns, "force", False))}
        try:
            reply = ctx.client().post(_CATALOG_INSTALL_PATH, body)
        except HubError as exc:
            if exc.status == 409 and "edited" in str(exc.reason):
                ctx.err.write(f"{_plain(exc.reason, 400)}\nrerun with --force to replace them; a copy of each "
                              "edited file is kept on the hub\n")
                return EXIT_FAILED
            raise
        if not isinstance(reply, Mapping) or reply.get("ok") is not True:
            ctx.err.write("unexpected reply from the hub: the install was not confirmed\n")
            return EXIT_FAILED
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        name, commit = _plain(reply.get("skill"), 80), _plain(str(reply.get("commit") or "")[:8], 8)
        status = reply.get("status")
        if status == "intact":
            ctx.say(f"{name}: intact — every file matches the catalog @{commit}; nothing was written")
            return EXIT_OK
        if reply.get("action") == "install":
            ctx.say(f"installed {name} from the Hermes catalog @{commit} ({_plain(reply.get('path'), 160)})")
            ctx.say("  it is an imported skill: its text is read as data until you vouch for it")
        else:
            ctx.say(f"{'updated' if status == 'updated' else 'repaired'} {name} from the Hermes catalog @{commit}")
            for key, word in (("restored", "restored"), ("replaced", "replaced your edit of"),
                              ("backed_up", "kept a copy of")):
                for rel in reply.get(key) or []:
                    ctx.say(f"  {word} {_plain(rel, 200)}")
            if reply.get("backup_dir"):
                ctx.say(f"  copies in {_plain(reply.get('backup_dir'), 300, keep_tail=True)}")
        if not reply.get("audited"):
            ctx.say("note: the intent log could not record this change")
        return EXIT_OK
    if not 1 <= ns.limit <= hermes_catalog.BROWSE_LIMIT:
        ctx.err.write(f"--limit takes 1 to {hermes_catalog.BROWSE_LIMIT}\n")
        return EXIT_USAGE
    reply = ctx.client().get("/skills/imported")
    catalog = reply.get("hermes_catalog") if isinstance(reply, Mapping) else None
    if not isinstance(catalog, Mapping):
        ctx.err.write("this hub reports no Hermes catalog\n")
        return EXIT_FAILED
    if catalog.get("available") is False:
        ctx.err.write(f"the Hermes catalog is unavailable on the hub: {_plain(catalog.get('error'), 300)}\n")
        return EXIT_FAILED
    rows = catalog.get("skills") if isinstance(catalog.get("skills"), list) else []
    shown, matched = hermes_catalog.browse(rows, search=ns.search, category=ns.category, kind=ns.kind,
                                           limit=ns.limit)
    if ns.json:
        ctx.dump({"commit": catalog.get("commit"), "counts": catalog.get("counts"), "matched": matched,
                  "shown": len(shown), "truncated": matched > len(shown), "skills": shown})
        return EXIT_OK
    counts = catalog.get("counts") if isinstance(catalog.get("counts"), Mapping) else {}
    ctx.say(f"Hermes catalog @{_plain(str(catalog.get('commit') or '')[:8], 8)}: "
            f"{_count_value(counts.get('instruction')) or 0} installable, "
            f"{_count_value(counts.get('upstream_only')) or 0} carry code, "
            f"{_count_value(counts.get('excluded')) or 0} excluded")
    for row in shown:
        kind = row.get("kind")
        mark = ("installed" if row.get("installed_commit") else "install") if kind == "instruction" \
            else ("code" if kind == "upstream_only" else "excluded")
        where = f"{row.get('category')}/{row.get('slug')}" if row.get("category") else row.get("slug")
        line = f"  {mark:<9} {_plain(where, 70):<40} {_plain(row.get('description'), 90)}"
        ctx.say(line.rstrip())
        needs = [str(k) for k in row.get("required_env") or []]
        if needs:
            ctx.say(f"            needs {_plain(', '.join(needs), 160)}")
        if kind == "upstream_only" and row.get("code_files"):
            ctx.say(f"            carries code: {_plain(', '.join(map(str, row['code_files'])), 160)}")
        if row.get("injection_flags"):
            ctx.say("            its text looks like an instruction to a model (flagged)")
    if not shown:
        ctx.say("no catalog skill matches")
    elif matched > len(shown):
        ctx.say(f"showing {len(shown)} of {matched} — narrow with --search/--category, or raise --limit "
                f"(at most {hermes_catalog.BROWSE_LIMIT})")
    else:
        ctx.say(f"{matched} shown")
    ctx.say("install one: nerva skills catalog install <category>/<skill>")
    return EXIT_OK


_BUNDLES_PATH = "/api/skills/bundles"


def _bundle_line(row: Mapping[str, Any]) -> str:
    skills = row.get("skills") if isinstance(row.get("skills"), list) else []
    missing = row.get("missing") if isinstance(row.get("missing"), list) else []
    text = f"{_plain(row.get('slug'), 70)}  {_plain(row.get('name'), 70)}  {len(skills)} skill{'s' if len(skills) != 1 else ''}"
    if missing:
        text += f" ({len(missing)} not installed)"
    return text + (f"  {_plain(row.get('description'), 120)}" if row.get("description") else "")


def _ask_bundle_skills(ctx: Context) -> list[str] | None:
    """Hermes' interactive fallback: one skill a line at ``skill> ``, an empty line ends;
    None when the owner cancels (end of input or Ctrl-C)."""
    ctx.say("No skills passed via --skill. Enter one skill name per line.")
    ctx.say("Submit an empty line to finish.")
    members: list[str] = []
    try:
        while len(members) < 64:
            ctx.out.write("skill> ")
            flush = getattr(ctx.out, "flush", None)
            if callable(flush):
                flush()
            line = ctx.inp.readline()
            if not line:
                return None
            name = line.strip()
            if not name:
                break
            members.append(name)
    except KeyboardInterrupt:
        return None
    return members


def _skill_bundles(ns: argparse.Namespace, ctx: Context) -> int:
    """H026 — ``nerva skills bundles``: keep named skill bundles on the hub (no action
    lists them, as Hermes' ``bundles`` does). A bundle is switched off or on as one unit
    with ``nerva skills off|on --bundle NAME`` (on waits for the owner's approval, as for
    one skill), and loaded into a chat turn with ``/<bundle> [instruction]``."""
    from urllib.parse import quote

    action = ns.bundle_action or "list"       # Hermes: `bundles` alone lists them
    as_json = bool(getattr(ns, "json", False))
    if action == "create":
        members = [s for s in ns.skill if s.strip()]
        if not members:
            if not _is_tty(ctx.inp):
                ctx.err.write("a bundle must name at least one skill: pass --skill NAME (repeat for each); "
                              "without one, skills are asked for only on an interactive terminal\n")
                return EXIT_USAGE
            asked = _ask_bundle_skills(ctx)
            if asked is None:
                ctx.err.write("Cancelled.\n")
                return EXIT_FAILED
            members = asked
            if not members:
                ctx.err.write("A bundle must reference at least one skill.\n")
                return EXIT_USAGE
        body = {"name": ns.name, "skills": members, "description": ns.description, "overwrite": ns.force}
        if ns.instruction is not None:
            body["instruction"] = ns.instruction
        reply = ctx.client().post(_BUNDLES_PATH, body)
    elif action == "delete":
        reply = ctx.client().request("DELETE", f"{_BUNDLES_PATH}/{quote(ns.name, safe='')}")
    elif action == "reload":
        reply = ctx.client().post(f"{_BUNDLES_PATH}/reload", {})
    elif action == "show":
        reply = ctx.client().get(f"{_BUNDLES_PATH}/{quote(ns.name, safe='')}")
    else:
        reply = ctx.client().get(_BUNDLES_PATH)
    if not isinstance(reply, dict):
        ctx.err.write("unexpected reply from the hub\n")
        return EXIT_FAILED
    if as_json:
        ctx.dump(reply)
        return EXIT_OK
    if action == "list":
        rows = reply.get("bundles")
        if not isinstance(rows, list):
            ctx.err.write("unexpected reply from the hub: no bundles in it\n")
            return EXIT_FAILED
        if not rows:
            ctx.say("no bundles yet; create one with: nerva skills bundles create NAME --skill A --skill B")
        for row in rows:
            if isinstance(row, Mapping):
                ctx.say(_bundle_line(row))
        for problem in reply.get("problems") or []:
            if isinstance(problem, Mapping):
                ctx.say(f"skipped {_plain(problem.get('file'), 120)}: {_plain(problem.get('detail'), 200)}")
        if reply.get("directory"):
            ctx.say(f"bundles folder: {_plain(reply['directory'], 300, keep_tail=True)}")
        return EXIT_OK
    if action == "show":
        row = reply.get("bundle") if isinstance(reply.get("bundle"), Mapping) else {}
        missing = {str(m).casefold() for m in row.get("missing") or []}
        ctx.say(f"{_plain(row.get('slug'), 70)}  {_plain(row.get('name'), 70)}")
        if row.get("description"):
            ctx.say(f"  {_plain(row['description'], 200)}")
        ctx.say(f"  file: {_plain(row.get('file'), 300, keep_tail=True)}")
        skills = row.get("skills") if isinstance(row.get("skills"), list) else []
        ctx.say(f"  skills ({len(skills)}):")
        for name in skills:
            ctx.say(f"    - {_plain(name, 130)}{' (not installed)' if str(name).casefold() in missing else ''}")
        if row.get("instruction"):
            ctx.say("  Instruction:")
            for line in str(row["instruction"]).splitlines() or [""]:
                ctx.say(f"    {_plain(line, 300)}")
        return EXIT_OK
    if action == "create":
        row = reply.get("bundle") if isinstance(reply.get("bundle"), Mapping) else {}
        skills = row.get("skills") if isinstance(row.get("skills"), list) else []
        ctx.say(f"{'replaced' if reply.get('replaced') else 'created'} bundle {_plain(row.get('name'), 70)} "
                f"({len(skills)} skill{'s' if len(skills) != 1 else ''}): {_plain(row.get('file'), 300, keep_tail=True)}")
        ctx.say(f"  switch it as one unit: nerva skills off|on --bundle {_plain(row.get('slug'), 70)}")
        return EXIT_OK
    if action == "delete":
        row = reply.get("deleted") if isinstance(reply.get("deleted"), Mapping) else {}
        ctx.say(f"deleted bundle {_plain(row.get('name'), 70)}: {_plain(row.get('file'), 300, keep_tail=True)}; "
                "its skills and their switches are untouched")
        return EXIT_OK
    added = [r for r in reply.get("added") or [] if isinstance(r, Mapping)]
    removed = [r for r in reply.get("removed") or [] if isinstance(r, Mapping)]
    changed = [str(s) for s in reply.get("changed") or []]
    if not (added or removed or changed):
        ctx.say(f"no changes; {reply.get('total', 0)} bundle(s) loaded")
    if added:
        ctx.say(f"added ({len(added)}):")
        for row in added:
            text = f" — {_plain(row['description'], 120)}" if row.get("description") else ""
            ctx.say(f"  + {_plain(row.get('name'), 70)}{text}")
    if removed:
        ctx.say(f"removed ({len(removed)}):")
        for row in removed:
            ctx.say(f"  - {_plain(row.get('name'), 70)}")
    if changed:
        ctx.say(f"changed ({len(changed)}): {', '.join(_plain(s, 70) for s in changed)}")
    if added or removed or changed:
        ctx.say(f"total bundles now: {reply.get('total', 0)}")
    for problem in reply.get("problems") or []:
        if isinstance(problem, Mapping):
            ctx.say(f"skipped {_plain(problem.get('file'), 120)}: {_plain(problem.get('detail'), 200)}")
    return EXIT_OK


def _skill_switches(ns: argparse.Namespace, ctx: Context) -> int:
    client = ctx.client()
    if ns.action == "config":
        return _skill_switch_config(ctx, client)
    if ns.action == "list":
        reply = client.get("/skills")
        skills = reply.get("skills") if isinstance(reply, dict) else None
        if not isinstance(skills, dict):
            ctx.err.write("unexpected reply from the hub: no skills in it\n")
            return EXIT_FAILED
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        for name in sorted(skills, key=str.casefold):
            row = skills[name] if isinstance(skills[name], dict) else {}
            where = ("off everywhere" if row.get("disabled") else
                     "off on " + ", ".join(row["disabled_channels"]) if row.get("disabled_channels") else "on")
            ctx.say(f"{name}: {where}{' (essential)' if row.get('essential') else ''}"
                    f"{_skill_usage_suffix(row.get('usage'))}{_skill_origin_suffix(row.get('usage'))}")
        return EXIT_OK
    bundle = getattr(ns, "bundle", None)
    if sum(1 for target in (ns.name, ns.category, bundle) if target) != 1:
        ctx.err.write("name one skill, or one --category, or one --bundle\n")
        return EXIT_USAGE
    body = {"enabled": ns.action == "on"}
    body.update({"skill": ns.name} if ns.name else {"category": ns.category} if ns.category
                else {"bundle": bundle})
    if ns.channel:
        body["channel"] = ns.channel
    reply = client.post("/api/skills/switch", body)
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    # H026: a bundle member that is not installed is skipped, and said so.
    missing = (reply.get("missing") or []) if isinstance(reply, dict) else []
    if isinstance(reply, dict) and reply.get("status") == "pending":
        ctx.say(f"pending owner approval: task {reply.get('task_id')} · "
                f"{', '.join(reply.get('pending') or [])}")
        for name in reply.get("off_everywhere") or []:
            ctx.say(f"{name}: still off everywhere after a channel-only approval")
        for name in missing:
            ctx.say(f"{_plain(str(name), 130)}: in the bundle but not installed, skipped")
        return EXIT_OK
    changed = reply.get("changed") or [] if isinstance(reply, dict) else []
    where = f"on {ns.channel}" if ns.channel else "everywhere"
    if changed:
        ctx.say(f"switched {ns.action} {where}: {', '.join(changed)}")
    for name in (reply.get("unchanged") or []) if isinstance(reply, dict) else []:
        ctx.say(f"{name}: already {ns.action} {where}")
    for name in (reply.get("off_everywhere") or []) if isinstance(reply, dict) else []:
        ctx.say(f"{name}: still off everywhere (switch it on without --channel)")
    for name in (reply.get("unstorable") or []) if isinstance(reply, dict) else []:
        ctx.say(f"{name}: not switched off; the switch could not be stored")
    for name in (reply.get("essential") or []) if isinstance(reply, dict) else []:
        ctx.say(f"{name}: essential, stays on")
    for name in missing:
        ctx.say(f"{_plain(str(name), 130)}: in the bundle but not installed, skipped")
    if changed and isinstance(reply, dict) and not reply.get("audited"):
        ctx.say("note: the intent log could not record this switch")
    return EXIT_OK


def _skill_switch_config(ctx: Context, client: HubClient) -> int:
    """A literal terminal picker using the same owner route as the HUD."""
    if not callable(getattr(ctx.inp, "isatty", None)) or not ctx.inp.isatty():
        ctx.err.write("skills config requires an interactive terminal\n")
        return EXIT_USAGE
    reply = client.get("/skills")
    skills = reply.get("skills") if isinstance(reply, dict) else None
    if not isinstance(skills, dict):
        ctx.err.write("skill list unavailable\n")
        return EXIT_FAILED
    choices = [("skill", name) for name in sorted(skills, key=str.casefold)]
    categories = sorted({row.get("category") for row in skills.values()
                         if isinstance(row, dict) and isinstance(row.get("category"), str)
                         and row.get("category")}, key=str.casefold)
    choices.extend(("category", name) for name in categories)
    def where(row: dict) -> str:
        if row.get("disabled"):
            return "off everywhere"
        channels = row.get("disabled_channels")
        if isinstance(channels, list) and channels:
            return "off on " + ", ".join(str(item) for item in channels)
        return "on"

    for number, (kind, name) in enumerate(choices, 1):
        if kind == "skill":
            state = where(skills[name] if isinstance(skills[name], dict) else {})
        else:
            members = [where(row) for row in skills.values()
                       if isinstance(row, dict) and row.get("category") == name]
            state = members[0] if len(set(members)) == 1 else "mixed"
        ctx.say(f"{number}. {kind}: {name} ({state})")
    try:
        ctx.out.write("Choose number (Enter cancels): ")
        line = ctx.inp.readline()
        if not line:
            return EXIT_OK
        selected = line.strip()
        if not selected:
            return EXIT_OK
        if not selected.isdigit() or not 1 <= int(selected) <= len(choices):
            ctx.err.write("invalid choice\n")
            return EXIT_USAGE
        kind, name = choices[int(selected) - 1]
        ctx.out.write("Switch on or off (Enter cancels): ")
        line = ctx.inp.readline()
        if not line:
            return EXIT_OK
        action = line.strip().casefold()
        if not action:
            return EXIT_OK
        if action not in ("on", "off"):
            ctx.err.write("choose on or off\n")
            return EXIT_USAGE
        if action == "off" and kind == "skill" and isinstance(skills[name], dict) and skills[name].get("essential"):
            ctx.err.write("essential skill stays on\n")
            return EXIT_FAILED
        ctx.out.write("Channel (Enter means everywhere): ")
        line = ctx.inp.readline()
        if not line:
            return EXIT_OK
        channel = line.strip()
    except (EOFError, KeyboardInterrupt):
        return EXIT_OK
    if channel and not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,31}", channel):
        ctx.err.write("invalid channel\n")
        return EXIT_USAGE
    body = {kind: name, "enabled": action == "on"}
    if channel:
        body["channel"] = channel
    result = client.post("/api/skills/switch", body)
    if isinstance(result, dict) and result.get("status") == "pending":
        ctx.say(f"pending owner approval: task {result.get('task_id')}")
    else:
        ctx.say(f"switched {action}: {', '.join(result.get('changed') or [])}")
    return EXIT_OK


def cmd_estop(ns: argparse.Namespace, ctx: Context) -> int:
    client = ctx.client()
    if ns.action == "status":
        reply = client.get("/api/ops/estop")
    elif ns.action == "engage":
        reply = client.post("/api/ops/estop/engage", {"reason": ns.reason} if ns.reason else {})
    else:
        reply = client.post("/api/ops/estop/resume")
    engaged = bool((reply or {}).get("engaged"))
    state = (reply or {}).get("state") or {}
    if engaged:
        ctx.say(f"e-stop ENGAGED since {state.get('engaged_at') or '?'} — {state.get('reason') or 'no reason given'}")
    else:
        ctx.say("e-stop not engaged")
    return EXIT_OK


_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def cmd_company(ns: argparse.Namespace, ctx: Context) -> int:
    """H464 — read the work runs, and let a parked one go.

    There is no verb that starts a run, for the same reason there is no route: a run
    opens only on a goal the owner approved in the decision inbox (``nerva goal
    propose`` only asks for one, H462). ``clear-wait`` grants nothing — the run goes
    back to the cadence it was already approved for.
    """
    client = ctx.client()
    if ns.action == "list":
        reply = client.get("/api/company/runs")
        runs = reply.get("runs") if isinstance(reply, dict) else None
        if not isinstance(runs, list):
            ctx.err.write("unexpected reply from the hub: no list of runs in it\n")
            return EXIT_FAILED
        if ns.json:
            ctx.dump(reply)
        elif not runs:
            ctx.say(str(reply.get("reason") or "no work runs"))
        else:
            for run in runs:
                ctx.say(f"{run.get('run_id')}  {run.get('status')}  {run.get('headline')}")
        return EXIT_OK
    if not _RUN_ID.match(ns.run_id or ""):
        ctx.err.write(f"not a run id: {ns.run_id!r} (letters, digits, _ and -)\n")
        return EXIT_USAGE
    reply = client.post(f"/api/company/runs/{ns.run_id}/barrier/clear")
    if ns.json:
        ctx.dump(reply)
    else:
        reply = reply if isinstance(reply, dict) else {}
        # ``cleared`` is what this call did; a newer wait that raced it is named
        # rather than reported as "no barrier" (H464 review F8).
        if reply.get("cleared"):
            ctx.say("cleared")
        elif reply.get("waiting_on"):
            ctx.say(f"not cleared: it is now waiting on {reply['waiting_on']}")
        else:
            ctx.say("no barrier")
    return EXIT_OK


def cmd_goal(ns: argparse.Namespace, ctx: Context) -> int:
    """H462 — say "goal: ..." from the shell.

    ``propose`` sends the goal to the hub's one front door (``POST
    /api/company/goals``, the same as ``/goal`` in chat): the card crosses the Action
    Kernel and waits in the decision inbox, and a run opens only when it is accepted
    there. ``subgoal`` adds a criterion to a running goal, which only narrows it.
    """
    client = ctx.client()
    if ns.action == "propose":
        lines = list(ns.lines)
        if lines == ["-"]:
            lines = ctx.inp.read().splitlines()
        text = "\n".join(line for line in lines if line.strip())
        if not text.strip():
            ctx.err.write("no goal given\n")
            return EXIT_USAGE
        reply = client.post("/api/company/goals", {"text": text})
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        reply = reply if isinstance(reply, dict) else {}
        ctx.say(f"proposed as task {reply.get('task_id')}: decide it in the decision inbox "
                "(nerva approvals list); nothing runs until you accept it")
        for line in reply.get("card") or ():
            ctx.say(f"  {line}")
        return EXIT_OK
    if not _RUN_ID.match(ns.run_id or ""):
        ctx.err.write(f"not a run id: {ns.run_id!r} (letters, digits, _ and -)\n")
        return EXIT_USAGE
    criterion = " ".join(ns.criterion).strip()
    reply = client.post(f"/api/company/runs/{ns.run_id}/subgoals", {"text": criterion})
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    added = reply.get("subgoal") if isinstance(reply, dict) else None
    added = added if isinstance(added, dict) else {}
    ctx.say(f"added {added.get('id')}: {added.get('describe')}")
    return EXIT_OK


_PAIRING_STATUSES = ("allowed", "pending", "blocked")
#: Where a hook may deliver (agents/core/webhooks.py DELIVER_CHOICES), spelled here so the
#: parser builds without importing the hub.
_WEBHOOK_DESTINATIONS = ("log", "telegram", "voice", "ntfy")
_WEBHOOK_PATH = "/api/webhooks"


def cmd_pairing(ns: argparse.Namespace, ctx: Context) -> int:
    """H051 — approve or revoke who may talk to the agent over a DM channel.

    The same admin routes the HUD's SENDER PAIRING card uses
    (agents/core/routers/pairing.py). ``revoke`` is the store's ``unpair``: the
    record goes, so an approved sender is back to unknown (held for approval on its
    next message) and a blocked one may ask again. ``clear-pending`` is a bulk
    reject and only previews unless ``--confirm`` is given — the CLI's counterpart
    of the HUD's two-step confirm.
    """
    client = ctx.client()
    if ns.action == "list":
        path = "/api/channels/pairing"
        if ns.status:
            path += "?" + urlencode({"status": ns.status})
        reply = client.get(path)
        senders = reply.get("senders") if isinstance(reply, dict) else None
        if not isinstance(senders, list):
            ctx.err.write("unexpected reply from the hub: no list of senders in it\n")
            return EXIT_FAILED
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        summary = reply.get("summary") if isinstance(reply.get("summary"), dict) else {}
        if summary:
            state = "on" if summary.get("enabled") else "off (every sender passes)"
            ctx.say(f"pairing {state} · " + " · ".join(
                f"{int(summary.get(name) or 0)} {name}" for name in _PAIRING_STATUSES))
        if not senders:
            ctx.say("no senders" + (f" with status {ns.status}" if ns.status else ""))
        for sender in senders:
            if not isinstance(sender, dict):
                continue
            name = sender.get("name") or ""
            label = f"  {name}" if name and name != sender.get("sender_id") else ""
            ctx.say(f"{sender.get('channel')}  {sender.get('sender_id')}  {sender.get('status')}{label}")
        return EXIT_OK
    if ns.action == "clear-pending":
        if not ns.confirm:
            reply = client.get("/api/channels/pairing?" + urlencode({"status": "pending"}))
            senders = reply.get("senders") if isinstance(reply, dict) else None
            count = len(senders) if isinstance(senders, list) else 0
            ctx.say(f"would drop {count} pending request(s); nobody is blocked and they may ask again. "
                    "Rerun with --confirm to drop them.")
            return EXIT_OK
        reply = client.post("/api/channels/pairing/clear-pending")
        reply = reply if isinstance(reply, dict) else {}
        if ns.json:
            ctx.dump(reply)
        else:
            # ``audited: false`` is said, so a cleared inbox never implies an audit row.
            ctx.say(f"cleared {int(reply.get('cleared') or 0)} pending"
                    + (" · not audited" if reply.get("audited") is False else ""))
        return EXIT_OK
    body = {"channel": ns.channel, "sender_id": ns.sender_id,
            "action": "approve" if ns.action == "approve" else "unpair"}
    if ns.action == "approve" and ns.name:
        body["name"] = ns.name
    reply = client.post("/api/channels/pairing/decide", body)
    reply = reply if isinstance(reply, dict) else {}
    who = f"{ns.channel}:{ns.sender_id}"
    if ns.action == "revoke" and not reply.get("unpaired"):
        ctx.err.write(f"no pairing record for {who}; nothing to revoke\n")
        return EXIT_FAILED
    if ns.action == "approve" and reply.get("status") != "allowed":
        ctx.err.write(f"the hub did not approve {who}: {reply}\n")
        return EXIT_FAILED
    if ns.json:
        ctx.dump(reply)
    else:
        ctx.say(f"approved {who}" if ns.action == "approve" else f"revoked {who}")
    return EXIT_OK


#: H422 — a reset's ``--target`` and the stores each erases (``memory_tool.RESET_TARGETS``).
_MEMORY_RESET_TARGETS = ("all", "memory", "user")
_MEMORY_STORES = {"all": ("memory", "user"), "memory": ("memory",), "user": ("user",)}
#: Both rings' lock waits on the hub (``cognition.memory.CLEAR_LOCK_TIMEOUT_S`` each), and a margin.
_MEMORY_RESET_TIMEOUT_S = 75.0


def _memory_store_line(target: str, store: Mapping[str, Any]) -> str:
    line = (f"  {target} ({store.get('label') or target}): {int(store.get('entries') or 0)}/"
            f"{store.get('cap')} entries · {int(store.get('chars') or 0)}/{store.get('char_budget')} chars"
            f" · {int(store.get('bytes') or 0):,} bytes on disk")
    if store.get("omitted"):
        line += f" · {int(store['omitted'])} older not shown (over the budget)"
    if store.get("blocked"):
        line += f" · {int(store['blocked'])} blocked as prompt-injection"
    return line


def _memory_erases(target: str, store: Mapping[str, Any]) -> str:
    line = (f"  - {target} ({store.get('label') or target}): {int(store.get('entries') or 0)} entries,"
            f" {int(store.get('bytes') or 0):,} bytes")
    extra = []
    if store.get("copies"):
        extra.append(f"{int(store['copies'])} hand-edit copies ({int(store.get('copies_bytes') or 0):,} bytes)")
    if store.get("undo_writes"):
        extra.append(f"{int(store['undo_writes'])} undoable writes")
    return line + (f", and {' and '.join(extra)}" if extra else "")


def _memory_holds(store: Any) -> bool:
    return isinstance(store, Mapping) and any(
        int(store.get(key) or 0) for key in ("entries", "copies", "undo_writes"))


def _memory_switch(client: Any, ctx: Context, on: bool, as_json: bool) -> int:
    """H422 — ``nerva memory off|on``: post the switch, then reread the status, and claim
    only what the hub reports."""
    reply = client.post("/api/memory/switch", {"enabled": on})
    status = client.get("/api/memory")
    status = status if isinstance(status, dict) else {}
    enabled = status.get("enabled") is True
    if as_json:
        ctx.dump({"switch": reply, "status": status})
        return EXIT_OK if enabled is on else EXIT_FAILED
    if not on:
        if enabled:
            ctx.err.write("memory is still on: the hub saved the switch but still reads it as on; "
                          "check again with `nerva memory` in 30 s\n")
            return EXIT_FAILED
        ctx.say("memory off: from the next turn no prompt carries the agent notes or the user profile, "
                "the memory tool refuses and the background review and reflection add nothing to them; "
                "nothing was erased (the stores stay on disk). "
                "Turn it back on with: nerva memory on")
        return EXIT_OK
    if enabled:
        tail = ", but safe mode leaves it out of every prompt" if status.get("safe_mode") else ""
        ctx.say(f"memory on: the next turn's prompt carries the agent notes and the user profile{tail}")
        return EXIT_OK
    if status.get("switch") is True and status.get("cognition") is False:
        ctx.err.write("the switch is on, but memory stays off: cognition.enabled and cognition.memory_enabled "
                      "must be on too (nerva config set, or a product posture that sets them)\n")
    elif status.get("available") is False:
        ctx.err.write("memory is not available on this hub (no cognition module)\n")
    else:
        ctx.err.write("memory is still off: the hub saved the switch but still reads it as off; "
                      "check again with `nerva memory` in 30 s\n")
    return EXIT_FAILED


def cmd_memory(ns: argparse.Namespace, ctx: Context) -> int:
    """H422 — the long-term memory every prompt carries (the agent notes and the user
    profile: LivingMemory's core rings), over the hub's routes.

    ``status`` (the default) reads ``GET /api/memory``: whether the core block reaches the
    prompt and the memory tool can write, and per store its entries, characters against
    the section budget and bytes on disk. ``reset`` shows what it would erase, asks for a
    typed ``yes`` unless ``--yes``, and posts ``POST /api/memory/reset`` (admin; the hub
    records it in the intent log). ``off`` / ``on`` post the owner's memory switch
    (``POST /api/memory/switch``, admin), which no product posture overrides; nothing is
    erased. Each then rereads ``GET /api/memory`` and says what the hub really does: it
    fails when memory is not in the state asked for.
    """
    client = ctx.client()
    action = ns.action or "status"
    as_json = bool(getattr(ns, "json", False))
    if action in ("off", "on"):
        return _memory_switch(client, ctx, action == "on", as_json)
    status = client.get("/api/memory")
    stores = status.get("stores") if isinstance(status, dict) else None
    if not isinstance(stores, dict):
        ctx.err.write("unexpected reply from the hub: no memory stores in it\n")
        return EXIT_FAILED
    if action == "status":
        if as_json:
            ctx.dump(status)
            return EXIT_OK
        if not status.get("available"):
            ctx.say("memory: not available on this hub (no cognition module)")
            return EXIT_OK
        if not status.get("enabled"):
            why = ("switched off by the owner (nerva memory on brings it back)" if status.get("switch") is False
                   else "cognition.enabled and cognition.memory_enabled must both be on")
            state = f"off ({why}); the stores stay on disk"
        elif status.get("safe_mode"):
            state = "on, but safe mode leaves it out of every prompt and the memory tool refuses"
        else:
            state = ("on · the prompt carries it · the memory tool "
                     + ("writes in owner turns" if status.get("tool") else "is not offered (llm.tool_loop_enabled off)"))
        ctx.say(f"memory: {state}")
        for target in ("memory", "user"):
            if isinstance(stores.get(target), Mapping):
                ctx.say(_memory_store_line(target, stores[target]))
        if status.get("drift"):
            ctx.say(f"note: {status['drift']}")
        return EXIT_OK
    targets = _MEMORY_STORES[ns.target]
    holding = [target for target in targets if _memory_holds(stores.get(target))]
    if not holding:
        ctx.say("Nothing to reset — the selected memory is empty.")
        return EXIT_OK
    if not as_json or not ns.yes:
        ctx.say("This will permanently erase:")
        for target in holding:
            ctx.say(_memory_erases(target, stores[target]))
    if not ns.yes:
        ctx.out.write("Type 'yes' to confirm: ")
        if callable(getattr(ctx.out, "flush", None)):
            ctx.out.flush()
        try:
            answer = ctx.inp.readline() if ctx.inp is not None else ""
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if (answer or "").strip().lower() != "yes":
            ctx.say("\nCancelled — nothing was erased.")
            return EXIT_FAILED
    # The hub waits up to 30 s for each ring's lock (CoreMemory.clear) before it answers.
    reply = client.post("/api/memory/reset", {"target": ns.target, "confirm": "RESET"},
                        timeout=_MEMORY_RESET_TIMEOUT_S)
    reply = reply if isinstance(reply, dict) else {}
    if as_json:
        ctx.dump(reply)
        return EXIT_OK if reply.get("ok") is True else EXIT_FAILED
    erased = reply.get("erased") if isinstance(reply.get("erased"), dict) else {}
    for target, count in erased.items():
        label = (stores.get(target) or {}).get("label") or target
        ctx.say(f"  erased {target} ({label}): {int(count or 0)} entries")
    if reply.get("ok") is not True:
        ctx.err.write(f"not erased: {', '.join(reply.get('not_erased') or []) or 'unknown'}; run the reset again\n")
        return EXIT_FAILED
    ctx.say("Memory reset complete. A conversation under way keeps what it started with; "
            "the next one starts with a blank slate.")
    if reply.get("audited") is False:
        ctx.say("note: the intent log could not record this reset")
    return EXIT_OK


#: H202 — the roster tiers ``agents.core.agent_roster.TIERS`` accepts.
_AGENT_TIERS = ("command", "business", "tech", "foundation")


def _agent_line(agent: Mapping[str, Any]) -> str:
    tags = []
    if agent.get("status") == "retired":
        tags.append("retired")
    elif not agent.get("live"):
        tags.append("not live")
    if agent.get("created"):
        tags.append(f"created from {agent.get('template') or 'blank'}")
    if agent.get("protected"):
        tags.append("protected")
    if agent.get("revision"):
        tags.append(f"rev {agent['revision']}")
    return f"{agent.get('id')}  {agent.get('name')}" + (f"  ({', '.join(tags)})" if tags else "")


def cmd_agents(ns: argparse.Namespace, ctx: Context) -> int:
    """H202 — the owner's roster over the hub's admin routes (the Agents roster and the
    Dossier in the HUD call the same ones; ``agents/core/agent_roster.py``).

    ``list`` (the default) reads ``GET /api/admin/agents/roster``. ``create`` posts a new
    agent from a template or blank (``POST /api/admin/agents``): kept in the roster, live at
    once and at every boot, no plugins or heartbeat granted. ``rename`` changes the display
    name for good; the id stays. ``retire`` shows what stops and what is kept, asks for the
    agent's id typed back unless ``--yes``, and posts the id as the hub's confirmation;
    nothing is deleted, and ``restore`` brings the agent back as it was.
    """
    client = ctx.client()
    action = ns.action or "list"
    as_json = bool(getattr(ns, "json", False))
    if action == "list":
        reply = client.get("/api/admin/agents/roster")
        rows = reply.get("agents") if isinstance(reply, dict) else None
        if not isinstance(rows, list):
            ctx.err.write("unexpected reply from the hub: no list of agents in it\n")
            return EXIT_FAILED
        if as_json:
            ctx.dump(reply)
            return EXIT_OK
        for agent in rows:
            if isinstance(agent, Mapping):
                ctx.say(_agent_line(agent))
        templates = [t.get("key") for t in reply.get("templates") or [] if isinstance(t, Mapping)]
        if templates:
            ctx.say("templates: " + ", ".join(str(t) for t in templates))
        if reply.get("error") == "roster_unreadable":
            ctx.say("note: the roster file could not be read; changes are refused until it is fixed")
        return EXIT_OK
    if action == "create":
        body = {"name": ns.name, "template": ns.template, "agent_id": ns.agent_id, "tier": ns.tier}
        reply = client.post("/api/admin/agents", body)
        verb = "created"
    elif action == "rename":
        reply = client.post(f"/api/admin/agents/{quote(ns.agent_id, safe='')}/rename", {"name": ns.name})
        verb = "renamed" if (reply or {}).get("changed", True) else "unchanged"
    elif action == "restore":
        reply = client.post(f"/api/admin/agents/{quote(ns.agent_id, safe='')}/restore")
        verb = "restored"
    else:
        ident = ns.agent_id.strip().lower()
        if not ns.yes:
            rows = (client.get("/api/admin/agents/roster") or {}).get("agents") or []
            agent = next((a for a in rows if isinstance(a, Mapping) and a.get("id") == ident), None)
            if agent is None:
                ctx.err.write(f"no agent {ident!r} on the roster\n")
                return EXIT_FAILED
            ctx.say(f"Retiring {agent.get('id')} ({agent.get('name')}) takes it out of the hub now and at "
                    "every boot. Nothing is deleted: its persona, persona versions, run history and memory "
                    "stay, and `nerva agents restore` brings it back as it was.")
            ctx.out.write(f"Type '{ident}' to confirm: ")
            if callable(getattr(ctx.out, "flush", None)):
                ctx.out.flush()
            try:
                answer = ctx.inp.readline() if ctx.inp is not None else ""
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if (answer or "").strip().lower() != ident:
                ctx.say("\nCancelled — nothing changed.")
                return EXIT_FAILED
        reply = client.post(f"/api/admin/agents/{quote(ident, safe='')}/retire",
                            {"confirm": ident, "reason": ns.reason})
        verb = "retired"
    reply = reply if isinstance(reply, dict) else {}
    if as_json:
        ctx.dump(reply)
        return EXIT_OK if reply.get("ok") is True else EXIT_FAILED
    agent = reply.get("agent") if isinstance(reply.get("agent"), Mapping) else {}
    ctx.say(f"{verb} {_agent_line(agent)}")
    if reply.get("audited") is False and verb != "unchanged":
        ctx.say("note: the hub's audit log could not record this change")
    return EXIT_OK if reply.get("ok") is True else EXIT_FAILED


#: H046 — Hermes names the same verb `journey`, `learning` and `memory-graph`.
_JOURNEY_ALIASES = ("learning", "memory-graph")
_JOURNEY_DAYS = 30      # the widest window GET /api/dashboard/today serves
_JOURNEY_LIMIT = 50
_JOURNEY_PATH = "/api/dashboard/today"
_JOURNEY_TAGS = {"action": "did", "learning": "learned", "followup": "follow-up"}
#: Where a learned entry is kept, and how a listing names it.
_JOURNEY_STORES = ("memory", "user", "skill", "facts")
_JOURNEY_STORE_TAGS = {"memory": "agent notes", "user": "user profile", "skill": "skill", "facts": "fact"}
_JOURNEY_ENTRY_HELP = ("the id `nerva journey list` prints (memory:<memory|user>:<digest>, skill:<name> "
                       "or learning:<n>)")


def _bounded_int(low: int, high: int) -> Callable[[str], int]:
    """An argparse ``type``: a whole number in ``low..high``, else a usage error."""
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"{value} is outside {low}-{high}")
        return value
    return parse


def _journey_entry_path(entry: str) -> str:
    return f"{_JOURNEY_PATH}/entries/{quote(entry, safe=':')}"


def _journey_text(item: Mapping[str, Any]) -> str:
    """What one timeline entry says, on one line."""
    kind = item.get("kind")
    if kind == "learning":
        if item.get("store") == "skill":
            return f"skill {item.get('label') or item.get('key')}: {item.get('value') or ''}".rstrip(": ")
        where = item.get("label") or "/".join(
            str(part) for part in (item.get("category"), item.get("key")) if part)
        return f"{where}: {item.get('value')}"
    if kind == "followup":
        detail = item.get("detail")
        return f"{item.get('title')}" + (f": {detail}" if detail else "")
    return str(item.get("title") or f"task #{item.get('id')}")


def _journey_when(item: Mapping[str, Any]) -> str:
    epoch = item.get("epoch")
    if isinstance(epoch, (int, float)) and not isinstance(epoch, bool):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch))
    return _plain(item.get("ts") or "?", 16) if item.get("ts") else "undated         "


def _journey_reply(reply: Any) -> Mapping[str, Any]:
    entry = reply.get("entry") if isinstance(reply, dict) else None
    if not isinstance(entry, Mapping):
        raise HubError(502, "unexpected reply from the hub: no entry in it")
    return entry


def _journey_timeline(ns: argparse.Namespace, ctx: Context, client: HubClient, as_json: bool) -> int:
    query = {"days": getattr(ns, "days", _JOURNEY_DAYS), "limit": getattr(ns, "limit", _JOURNEY_LIMIT)}
    if getattr(ns, "kind", None):
        query["kind"] = ns.kind
    reply = client.get(f"{_JOURNEY_PATH}?{urlencode(query)}")
    if as_json:
        ctx.dump(reply)
        return EXIT_OK
    items = reply.get("items") if isinstance(reply, dict) else None
    if not isinstance(items, list):
        ctx.err.write("unexpected reply from the hub: no timeline items in it\n")
        return EXIT_FAILED
    counts = reply.get("counts") if isinstance(reply.get("counts"), Mapping) else {}
    summary = [f"{int(counts.get('actions') or 0)} did", f"{int(counts.get('learnings') or 0)} learned"]
    if counts.get("followups"):
        summary.append(f"{int(counts['followups'])} follow-ups")
    ctx.say(f"journey · last {reply.get('days', query['days'])} day(s) · " + " · ".join(summary))
    if reply.get("drift"):
        ctx.say(f"note: {_plain(reply['drift'], 300)}")
    if not items:
        ctx.say("nothing in this window yet")
        return EXIT_OK
    for item in items:
        if not isinstance(item, Mapping):
            continue
        tag = _JOURNEY_TAGS.get(str(item.get("kind")), _plain(item.get("kind"), 10))
        ctx.say(f"{_journey_when(item)}  {tag:<9}  {_plain(item.get('entry_id') or '-', 48):<22}  "
                f"{_plain(_journey_text(item), 160)}")
    total = int(counts.get("total") or 0)
    if len(items) < total and not getattr(ns, "kind", None):
        ctx.say(f"showing the newest {len(items)} of {total} (--limit shows more, --kind narrows; "
                "`nerva journey list` lists every learned entry, whatever its age)")
    return EXIT_OK


def _journey_list(ns: argparse.Namespace, ctx: Context, client: HubClient, as_json: bool) -> int:
    """Every learned entry, oldest first, with its id (Hermes's ``journey list``)."""
    query: dict[str, Any] = {"limit": ns.list_limit or 5000}
    if ns.store:
        query["store"] = ns.store
    reply = client.get(f"{_JOURNEY_PATH}/entries?{urlencode(query)}")
    if as_json:
        ctx.dump(reply)
        return EXIT_OK
    entries = reply.get("entries") if isinstance(reply, dict) else None
    if not isinstance(entries, list):
        ctx.err.write("unexpected reply from the hub: no entries in it\n")
        return EXIT_FAILED
    counts = reply.get("counts") if isinstance(reply.get("counts"), Mapping) else {}
    ctx.say("learned · " + " · ".join(f"{int(counts.get(name) or 0)} {_JOURNEY_STORE_TAGS[name]}"
                                      for name in _JOURNEY_STORES))
    if reply.get("drift"):
        ctx.say(f"note: {_plain(reply['drift'], 300)}")
    if not entries:
        ctx.say("No learning yet.")
        return EXIT_OK
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        tag = _JOURNEY_STORE_TAGS.get(str(item.get("store")), _plain(item.get("store"), 12))
        ctx.say(f"{_plain(item.get('entry_id') or '-', 160):<34}  {tag:<12}  {_journey_when(item)}  "
                f"{_plain(_journey_value(item), 160)}")
    total = int(reply.get("total") or 0)
    if len(entries) < total:
        ctx.say(f"showing the newest {len(entries)} of {total} (--limit shows more, --store narrows)")
    return EXIT_OK


def _journey_value(item: Mapping[str, Any]) -> str:
    if item.get("store") == "skill":
        return f"{item.get('label') or item.get('key')}" + (f": {item['value']}" if item.get("value") else "")
    if item.get("store") == "facts":
        return f"{item.get('label')}: {item.get('value')}"
    return str(item.get("value") or "")


def cmd_journey(ns: argparse.Namespace, ctx: Context) -> int:
    """H046 — `nerva journey` (also `nerva learning` / `nerva memory-graph`), Hermes's
    `hermes journey`: look back at what the assistant did and learned.

    With no action it prints the timeline the HUD's TODAY card reads (``GET
    /api/dashboard/today``), newest first, each entry with its id. ``list`` prints every
    learned entry whatever its age, oldest first (``GET /api/dashboard/today/entries``):
    the agent's notes and the user profile every prompt carries, the skills it learned,
    and the stored facts, each with the id ``show``, ``edit`` and ``delete`` take.
    ``show`` reads one (a skill: its SKILL.md). ``delete`` forgets one (after a typed
    ``yes`` unless ``--yes``: a skill is archived, recoverable, and one still awaiting the
    owner's review is discarded, as the review's reject does; a note or profile fact
    keeps an undo) and ``edit`` changes what it says, in ``$VISUAL``/``$EDITOR`` or from
    ``--text``: both are admin memory writes and cross ``kg.write`` on the hub (the Action
    Kernel, when it is on, decides; a refusal is printed and nothing changes). Only a
    learned entry can be changed: an action is the record of what the hub did.
    """
    client = ctx.client()
    action = ns.action
    as_json = bool(getattr(ns, "json", False))
    if action is None:
        return _journey_timeline(ns, ctx, client, as_json)
    if action == "list":
        return _journey_list(ns, ctx, client, as_json)

    path = _journey_entry_path(ns.entry)
    if action == "show":
        reply = client.get(path)
        if as_json:
            ctx.dump(reply)
            return EXIT_OK
        entry = _journey_reply(reply)
        ctx.say(f"{_plain(entry.get('entry_id'), 160)}  {_journey_when(entry)}  {_plain(_journey_text(entry), 400)}")
        if entry.get("store") == "skill" and isinstance(entry.get("content"), str):
            # A learned skill's text came from a model: line by line, with no control
            # character reaching the terminal (an escape sequence is printed as a space).
            ctx.say("")
            for line in entry["content"].splitlines():
                ctx.say(_plain(line, 10_000))
        elif entry.get("content_withheld"):
            # H046 review: a quarantined skill's text is read only in the owner's review.
            ctx.say(f"note: {_plain(entry['content_withheld'], 400)}")
        return EXIT_OK

    if action == "delete":
        return _journey_delete(ns, ctx, client, path, as_json)

    # edit
    entry: Mapping[str, Any] = {}
    if ns.text is not None:
        text = ctx.inp.read() if ns.text == "-" else ns.text
    else:
        entry = _journey_reply(client.get(path))
        skill = entry.get("store") == "skill"
        if skill and entry.get("pending_review"):
            # Never an editor on an empty file in place of a SKILL.md the hub withholds.
            ctx.err.write(f"{_plain(entry.get('content_withheld') or 'this skill awaits the owner review', 400)}; "
                          "nothing changed\n")
            return EXIT_FAILED
        before = str((entry.get("content") if skill else entry.get("value")) or "")
        edited = _journey_edit_in_editor(ctx, before, suffix=".md" if skill else ".txt")
        if edited is None:
            return EXIT_FAILED
        if edited.strip() == before.strip():
            ctx.say("nothing changed")
            return EXIT_OK
        text = edited
    if not text.strip():
        ctx.err.write("the new text is empty; nothing changed (to forget the entry: nerva journey delete "
                      f"{_plain(ns.entry, 160)})\n")
        return EXIT_USAGE
    reply = _journey_write(ctx, lambda: client.request("PATCH", path, {"value": text}))
    if reply is _REFUSED:
        return EXIT_FAILED
    if as_json:
        ctx.dump(reply)
        return EXIT_OK if isinstance(reply, dict) and reply.get("ok") is True else EXIT_FAILED
    changed = _journey_reply(reply)
    ctx.say(("changed " if reply.get("changed") else "unchanged ")
            + f"{_plain(changed.get('entry_id'), 160)}  {_plain(_journey_text(changed), 400)}")
    if reply.get("changed") and changed.get("entry_id") != ns.entry:
        ctx.say(f"its id is now {_plain(changed.get('entry_id'), 160)} (a note's id follows its text)")
    if reply.get("undo_ref"):
        ctx.say(f"undo: the Long-Term Memory panel, or POST /api/memory/core/undo {{\"ref\": "
                f"\"{_plain(reply['undo_ref'], 40)}\"}}")
    return EXIT_OK


def _journey_reference_line(e: Mapping[str, Any]) -> str:
    """One reference a skill delete left where it is (the HUD's ``referenceLine``)."""
    def get(key: str, limit: int = 120) -> str:
        return _plain(e.get(key), limit) if e.get(key) not in (None, "") else ""

    holder = get("holder", 40)
    if e.get("unreadable"):
        return f"{holder}{' ' + get('file', 200) if get('file', 200) else ''} · could not be read" + (
            f" · {get('why')}" if get("why") else "")
    if holder == "skill":
        if e.get("field") == "related_skills":
            return f"skill {get('name')} · related_skills" + (f" · {get('why')}" if get("why") else "")
        lines = e.get("lines") if isinstance(e.get("lines"), list) else []
        return f"skill {get('name')} · {get('file', 200)} line {', '.join(str(n) for n in lines[:12])}"
    if holder == "bundle":
        return f"bundle {get('name')} · lists {get('member')}" + (f" · {get('why')}" if get("why") else "")
    if holder == "job":
        return f"job {get('name')} ({get('id', 60)}) · {get('field', 60)}"
    if holder in ("load_set", "switch"):
        extra = get("warning", 200) or get("channel", 60)
        return f"{get('setting', 80)}" + (f" · {extra}" if extra else "")
    if holder in ("proposal", "batch"):
        return f"pending {holder} {get('id', 60)}"
    return holder


def _journey_reference_lines(refs: Any) -> list[str]:
    """H330 — what still names a skill the journey archived, one line each, so a delete
    never leaves something pointing at a gone skill without the owner being told."""
    out: list[str] = []
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, Mapping):
            continue
        for e in ref.get("left") if isinstance(ref.get("left"), list) else []:
            if isinstance(e, Mapping):
                out.append(f"  still names it: {_journey_reference_line(e)}")
        more = ref.get("more")
        if isinstance(more, int) and more > 0:
            out.append(f"  and {more} more")
        hidden = ref.get("hidden")
        if isinstance(hidden, int) and hidden > 0:
            out.append(f"  {hidden} skill(s) not shown here name it too")
    if out:
        out.insert(0, "nothing absorbed it, so these still name the archived skill (edit or remove them):")
    return out


def _journey_delete(ns: argparse.Namespace, ctx: Context, client: HubClient, path: str, as_json: bool) -> int:
    entry = _journey_reply(client.get(path))
    skill = entry.get("store") == "skill"
    pending = skill and bool(entry.get("pending_review"))
    if not ns.yes:
        # With --json the reply alone goes to stdout: the question goes to stderr.
        ask = ctx.err if as_json else ctx.out
        what = ("discards (rejects the skill awaiting review; its folder is kept)" if pending
                else "archives (recoverable)" if skill else "forgets")
        ask.write(f"This {what}: {_plain(_journey_text(entry), 400)}\nType 'yes' to confirm: ")
        if callable(getattr(ask, "flush", None)):
            ask.flush()
        try:
            answer = ctx.inp.readline() if ctx.inp is not None else ""
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if (answer or "").strip().lower() != "yes":
            ask.write("\nCancelled — nothing was forgotten.\n")
            return EXIT_FAILED
    reply = _journey_write(ctx, lambda: client.request("DELETE", path))
    if reply is _REFUSED:
        return EXIT_FAILED
    if as_json:
        ctx.dump(reply)
        return EXIT_OK if isinstance(reply, dict) and reply.get("ok") is True else EXIT_FAILED
    if not (isinstance(reply, dict) and reply.get("ok") is True):
        ctx.err.write("the hub did not confirm the delete; run `nerva journey show` to see what is there\n")
        return EXIT_FAILED
    if skill:
        where = reply.get("archived_to")
        if reply.get("discarded"):
            ctx.say(f"discarded {_plain(reply.get('deleted'), 160)}"
                    + (f" — never loaded again; its folder is kept in {_plain(where, 300)}" if where else ""))
            return EXIT_OK
        ctx.say(f"archived {_plain(reply.get('deleted'), 160)}"
                + (f" — its folder is kept in {_plain(where, 300)}; move it back into the skills folder to "
                   "restore it" if where else ""))
        for line in _journey_reference_lines(reply.get("references")):
            ctx.say(line)
        return EXIT_OK
    ctx.say(f"forgot {_plain(reply.get('deleted'), 160)}")
    if reply.get("undo_ref"):
        ctx.say(f"undo: the Long-Term Memory panel, or POST /api/memory/core/undo {{\"ref\": "
                f"\"{_plain(reply['undo_ref'], 40)}\"}} (`nerva memory reset` erases kept copies)")
    return EXIT_OK


_REFUSED = object()


def _journey_write(ctx: Context, call: Callable[[], Any]) -> Any:
    """An edit or delete; a ``kg.write`` refusal (the write contract or the Action Kernel:
    a halt, a missing capability) is the hub's own reason, not a credential problem, so it
    is printed as such and answers ``_REFUSED``."""
    try:
        return call()
    except HubError as exc:
        if exc.status == 403 and str(exc.reason).startswith(("kernel denied", "contract denied")):
            ctx.err.write(f"{exc.reason}; nothing changed\n")
            return _REFUSED
        raise


def _journey_edit_in_editor(ctx: Context, before: str, *, suffix: str = ".txt") -> str | None:
    """The owner's ``$VISUAL``/``$EDITOR`` on one entry's text, in an owner-only temporary
    file removed afterwards; what was saved, or None (said why) when the editor failed."""
    import contextlib
    import tempfile

    argv = _editor_argv(ctx.environ)
    fd, temporary = tempfile.mkstemp(prefix="nerva-journey-", suffix=suffix)   # owner-only (0600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(before if before.endswith("\n") else before + "\n")
        try:
            status = _run_editor(argv, temporary)
        except OSError as exc:
            ctx.err.write(f"editor {_plain(argv[0], 80)} {_editor_failure(exc)} — set $VISUAL or $EDITOR "
                          "to one; nothing changed\n")
            return None
        if status != 0:
            ctx.err.write(f"editor exited {status}; nothing changed\n")
            return None
        return Path(temporary).read_text(encoding="utf-8")
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)


def _json_option(flag: str, text: str, *, an_object: bool = False):
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{flag} is not JSON: {exc}") from None
    if an_object and not isinstance(value, dict):
        raise argparse.ArgumentTypeError(f"{flag} must be a JSON object")
    return value


def _webhook_line(hook: dict) -> str:
    """One hook as ``list`` shows it: id, name, target, credential kind, switch, and
    what narrows or routes its deliveries."""
    kind = "hmac" if hook.get("signed") else "token"
    parts = [str(hook.get("id")), str(hook.get("name") or hook.get("target") or ""),
             f"{hook.get('target_type')}:{hook.get('target')}", kind, "on" if hook.get("enabled") else "off"]
    deliver = hook.get("deliver") or "log"
    if deliver != "log":
        parts.append(f"-> {deliver}")
    if hook.get("deliver_only") is True:
        parts.append("deliver only")
    if hook.get("events_unreadable"):
        parts.append("events: unreadable")
    elif hook.get("events"):
        parts.append("events: " + ", ".join(str(name) for name in hook["events"]))
    rules = hook.get("filter") if isinstance(hook.get("filter"), list) else []
    if hook.get("filter_unreadable"):
        parts.append("filter: unreadable")
    elif rules:
        parts.append(f"filter: {len(rules)} rule" + ("" if len(rules) == 1 else "s"))
    parts.append(f"calls {int(hook.get('calls') or 0)}")
    return "  ".join(parts)


def cmd_webhook(ns: argparse.Namespace, ctx: Context) -> int:
    """H039 — `nerva webhook subscribe|list|remove|test`, Hermes' `hermes webhook`.

    The same admin routes the HUD's WEBHOOKS card uses (agents/core/routers/webhooks.py).
    ``subscribe`` prints the hook's URL and its token or signing secret once: the hub
    masks it ever after. ``test`` asks the hub for a correctly signed sample delivery run
    through the hook's own receive path, dry (nothing runs, nothing is pushed, no call is
    counted), and shows what a real delivery like it would do.
    """
    client = ctx.client()
    if ns.action == "list":
        reply = client.get(_WEBHOOK_PATH)
        hooks = reply.get("webhooks") if isinstance(reply, dict) else None
        if not isinstance(hooks, list):
            ctx.err.write("unexpected reply from the hub: no list of webhooks in it\n")
            return EXIT_FAILED
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        if not hooks:
            ctx.say("no webhooks")
        for hook in hooks:
            if isinstance(hook, dict):
                ctx.say(_webhook_line(hook))
        return EXIT_OK
    if ns.action == "subscribe":
        body: dict[str, Any] = {
            "target": ns.target, "target_type": ns.target_type, "name": ns.name, "signed": bool(ns.signed),
            "events": [name.strip() for name in ns.events.split(",") if name.strip()],
            "prompt": ns.prompt, "deliver": ns.deliver, "deliver_only": bool(ns.deliver_only),
            "description": ns.description,
        }
        if ns.filter is not None:
            body["filter"] = _json_option("--filter", ns.filter)
        reply = client.post(_WEBHOOK_PATH, body)
        reply = reply if isinstance(reply, dict) else {}
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        hook_id = str(reply.get("id") or "")
        ctx.say(f"subscribed {hook_id}  {reply.get('name') or ns.target}  {reply.get('target_type')}:{reply.get('target')}")
        ctx.say(f"POST {client.base_url}{_WEBHOOK_PATH}/{quote(hook_id, safe='')}")
        if reply.get("signed"):
            ctx.say(f"signing secret: {reply.get('signing_secret')}")
            ctx.say("The sender signs each raw body: X-Signature-256: sha256=<HMAC-SHA256 with this secret>.")
            ctx.say("Save it now: the signing secret is shown once and never again.")
        else:
            ctx.say(f"X-Webhook-Token: {reply.get('token')}")
            ctx.say("Save it now: the token is shown once and never again.")
        return EXIT_OK
    path = f"{_WEBHOOK_PATH}/{quote(ns.hook_id, safe='')}"
    if ns.action == "remove":
        try:
            reply = client.request("DELETE", path)
        except HubError as exc:
            if exc.status == 404:
                ctx.err.write(f"no webhook {ns.hook_id}; nothing to remove\n")
                return EXIT_FAILED
            raise
        if ns.json:
            ctx.dump(reply if isinstance(reply, dict) else {"ok": True})
        else:
            ctx.say(f"removed {ns.hook_id}")
        return EXIT_OK
    # test
    body = {}
    if ns.event:
        body["event"] = ns.event
    if ns.payload is not None:
        body["payload"] = _json_option("--payload", ns.payload, an_object=True)
    try:
        reply = client.post(path + "/test", body)
    except HubError as exc:
        if exc.status == 404:
            ctx.err.write(f"no webhook {ns.hook_id}; nothing to test\n")
            return EXIT_FAILED
        raise
    test = reply.get("test") if isinstance(reply, dict) else None
    if not isinstance(test, dict):
        ctx.err.write("unexpected reply from the hub: no test report in it\n")
        return EXIT_FAILED
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    verified = "verified" if test.get("authenticated") else "NOT verified"
    ctx.say(f"{test.get('auth')} {verified} · event {test.get('event')} · receiver {test.get('receiver')} "
            f"· hook {'on' if test.get('enabled') else 'off'}")
    outcome, reason = test.get("outcome"), test.get("reason") or ""
    if outcome == "run":
        ctx.say(f"would run {test.get('target')}, reply to {test.get('deliver')}")
    elif outcome == "deliver_only":
        ctx.say(f"would deliver only to {test.get('deliver')}: no turn")
    elif outcome in ("skipped", "filtered"):
        ctx.say(f"would be {outcome}: {reason}")
    else:
        ctx.say(f"would be refused ({test.get('status')}): {reason}")
    if test.get("text"):
        ctx.say(f"text: {test['text']}")
    return EXIT_OK


def _params(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"--param takes KEY=VALUE, got {pair!r}")
        out[key.strip()] = value
    return out


def _job_cli_options(ns):
    value = json.loads(ns.options) if ns.options is not None else {}
    if not isinstance(value, dict):
        raise ValueError('--options must be an object')
    if ns.workdir is not None:
        if ns.options is None:
            raise ValueError('--workdir requires complete --options')
        if ns.workdir:
            value['workdir'] = ns.workdir
        else:
            value.pop('workdir', None)
    if ns.toolsets is not None:
        if ns.options is None:
            raise ValueError('--toolsets requires complete --options')
        if ns.toolsets == 'default':
            value.pop('enabled_toolsets', None)
        else:
            value['enabled_toolsets'] = [] if ns.toolsets == 'none' else ns.toolsets.split(',')
    if ns.reasoning_effort is not None:
        if ns.options is None:
            raise ValueError('--reasoning-effort requires complete --options')
        if ns.reasoning_effort == 'default':
            value.pop('reasoning_effort', None)
        else:
            value['reasoning_effort'] = ns.reasoning_effort
    if ns.continuity is not None:
        value['continuity'] = ns.continuity
    if getattr(ns, 'clear_context_from', False):
        value['context_from'] = []
    elif ns.context_from is not None:
        value['context_from'] = ns.context_from
    return value


def cmd_jobs(ns: argparse.Namespace, ctx: Context) -> int:
    client = ctx.client()
    def machine(payload: Any) -> None:
        ctx.out.write(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n")

    if ns.action == "incidents":
        if ns.operation == "ack":
            if ns.incident_id is None or ns.incident_id <= 0 or ns.state or ns.job_id or ns.limit is not None:
                ctx.err.write("ack requires one positive incident ID and no list filters\n")
                return EXIT_USAGE
            reply = client.post(f"/api/jobs/incidents/{ns.incident_id}/ack", {})
            if ns.json:
                machine(reply)
            else:
                ctx.say(f"acknowledged incident {ns.incident_id}; job remains unchanged")
            return EXIT_OK
        if ns.incident_id is not None or (ns.limit is not None and not 1 <= ns.limit <= 100):
            ctx.err.write("list accepts filters and a limit from 1 to 100, not an incident ID\n")
            return EXIT_USAGE
        params = {key: value for key, value in (("state", ns.state), ("job_id", ns.job_id),
                                                ("limit", ns.limit)) if value is not None}
        reply = client.get("/api/jobs/incidents" + ("?" + urlencode(params) if params else ""))
        if ns.json:
            machine(reply)
        else:
            for row in reply.get("incidents") or []:
                ctx.say(f"#{row.get('id')}  {_log_display(row.get('state'), 20)}  "
                        f"{_log_display(row.get('job_id'), 80)}  {_log_display(row.get('safe_error'), 160)}")
            if not reply.get("incidents"):
                ctx.say("no incidents")
        return EXIT_OK
    if ns.action == "notepad":
        job_path = f"/api/jobs/{quote(ns.job_id, safe='')}"
        if ns.text is not None and (ns.operation != "list" or ns.key is not None or ns.value is not None):
            ctx.err.write("--text replaces the legacy note and cannot be combined with a key operation\n")
            return EXIT_USAGE
        if ns.text is not None:
            reply = client.request("PUT", job_path + "/notepad", {"text": ns.text})
        else:
            path = job_path + "/notepad/keys"
            if ns.operation == "list":
                if ns.key is not None or ns.value is not None:
                    ctx.err.write("notepad list takes no key or value\n")
                    return EXIT_USAGE
                entries = client.get(path).get("entries") or []
                legacy = (client.get(job_path).get("job") or {}).get("notepad") or ""
                reply = {"entries": entries, "notepad": legacy}
            elif ns.operation == "get":
                if ns.key is None or ns.value is not None:
                    ctx.err.write("notepad get requires one key\n")
                    return EXIT_USAGE
                reply = client.get(path + "?" + urlencode({"key": ns.key}))
            elif ns.operation == "set":
                if ns.key is None or ns.value is None:
                    ctx.err.write("notepad set requires a key and value\n")
                    return EXIT_USAGE
                reply = client.request("PUT", path, {"key": ns.key, "value": ns.value})
            else:
                if ns.key is None or ns.value is not None:
                    ctx.err.write("notepad delete requires one key\n")
                    return EXIT_USAGE
                reply = client.request("DELETE", path + "?" + urlencode({"key": ns.key}))
        if ns.json:
            machine(reply)
        elif ns.operation == "list" and ns.text is None:
            for row in reply["entries"]:
                ctx.say(f"{_log_display(row.get('key'), 128)}  {_log_display(row.get('value'), 200)}")
            if reply["notepad"]:
                ctx.say(f"previous output: {_log_display(reply['notepad'], 200)}")
            elif not reply["entries"]:
                ctx.say("no notes")
        elif ns.operation == "get" and ns.text is None:
            value = (reply.get("entry") or {}).get("value")
            if not isinstance(value, str):
                ctx.err.write("unexpected note reply from hub\n")
                return EXIT_FAILED
            shown = _job_note_display(value)
            ctx.out.write(shown + ("" if shown.endswith("\n") else "\n"))
        else:
            ctx.say("note updated" if ns.operation == "set" or ns.text is not None else "note deleted")
        return EXIT_OK
    if ns.action in ("doctor", "tick", "status"):
        if ns.action == "tick":
            reply = client.post("/api/jobs/tick", {})
        elif ns.action == "status" and ns.request:
            reply = client.get(f"/api/jobs/{ns.job_id}/requests/{ns.request}")
        elif ns.action == "status":
            reply = client.get(f"/api/jobs/{ns.job_id}")
        else:
            reply = client.get(f"/api/jobs/{ns.action}")
        ctx.dump(reply)
        if ns.action == "doctor":
            healthy = isinstance(reply, dict) and reply.get("ok") is True and reply.get("problems") == []
            return EXIT_OK if healthy else EXIT_FAILED
        return EXIT_OK
    if ns.action == "list":
        reply = client.get("/api/jobs") or {}
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        scheduler = reply.get("scheduler") or {}
        ctx.say(
            f"scheduler {'alive' if scheduler.get('alive') else 'NOT RUNNING'} — "
            f"{scheduler.get('runnable', 0)} runnable, {scheduler.get('paused', 0)} paused"
            + (f", {scheduler['held']} held for quiet hours" if scheduler.get("held") else "")
            + (" — quiet hours now" if scheduler.get("quiet_hours") else "")
        )
        for job in reply.get("jobs") or []:
            state = "paused" if job.get("paused_reason") else ("on" if job.get("enabled") else "off")
            last = f"{job.get('last_status')} {job.get('last_run_at') or ''}".strip() if job.get("last_status") else "never ran"
            ctx.say(f"{job.get('id')}  {state:6s} {job.get('schedule_text', ''):28s} {job.get('name', '')}  [{last}]")
        if not reply.get("jobs"):
            ctx.say("no jobs — `nerva jobs blueprints` shows what you can arm in one line")
        return EXIT_OK
    if ns.action == "blueprints":
        for blueprint in (client.get("/api/jobs/blueprints") or {}).get("blueprints") or []:
            ctx.say(f"{blueprint['id']:14s} {blueprint['title']} — {blueprint['description']}")
            ctx.say(f"{'':14s} default: {blueprint['schedule_text']}; params: {', '.join(blueprint.get('params') or [])}")
        return EXIT_OK
    if ns.action == "create":
        body: dict[str, Any] = {}
        try:
            if (ns.options is not None or ns.workdir is not None or ns.toolsets is not None
                    or ns.reasoning_effort is not None
                    or ns.continuity is not None or ns.context_from is not None):
                body["options"] = _job_cli_options(ns)
            if ns.media_id and ns.blueprint:
                raise ValueError("--media-id requires an explicit --action reminder, not a blueprint")
            if ns.blueprint:
                body["blueprint"] = ns.blueprint
                params = _params(ns.param)
                if params:
                    body["params"] = params
            else:
                if not (ns.name and ns.when and ns.action_json):
                    ctx.err.write("without --blueprint, --name, --when and --action are all required\n")
                    return EXIT_USAGE
                body["action"] = json.loads(ns.action_json)
                if ns.media_id:
                    if not isinstance(body["action"], dict) or body["action"].get("type") != "remind":
                        raise ValueError("--media-id requires a reminder action")
                    body["action"]["media_ids"] = ns.media_id
            if ns.name:
                body["name"] = ns.name
            if ns.when:
                body["schedule_text"] = ns.when
            if ns.first_run is not None:
                body["first_run"] = ns.first_run
        except ValueError as exc:
            ctx.err.write(f"{exc}\n")
            return EXIT_USAGE
        reply = _guarded_job_call(ctx, lambda: client.post("/api/jobs", _selection_body(ns, body)))
        if reply is None:
            return EXIT_FAILED
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        job = reply.get("job") or {}
        # H687 — the hub says whether a first run was queued now or the job waits.
        when = reply.get("confirmation") or f"{job.get('schedule_text')} ({job.get('cron')})"
        ctx.say(f"armed {job.get('id')}  {when}  {job.get('name')}")
        return EXIT_OK
    if ns.action == "edit":
        if ns.media_id and not ns.action_json:
            ctx.err.write("--media-id requires --action to explicitly reauthorize the reminder\n")
            return EXIT_USAGE
        body = {}
        if (ns.options is not None or ns.workdir is not None or ns.toolsets is not None
                or ns.reasoning_effort is not None):
            try:
                body["options"] = _job_cli_options(ns)
            except ValueError as exc:
                ctx.err.write(f"{exc}\n")
                return EXIT_USAGE
        else:
            if ns.continuity is not None:
                body["continuity"] = ns.continuity
            if ns.context_from is not None:
                body["context_from"] = ns.context_from
            elif ns.clear_context_from:
                body["context_from"] = []
        if ns.name:
            body["name"] = ns.name
        if ns.when:
            body["schedule_text"] = ns.when
        if ns.action_json:
            try:
                body["action"] = json.loads(ns.action_json)
                if ns.media_id:
                    if not isinstance(body["action"], dict) or body["action"].get("type") != "remind":
                        raise ValueError("--media-id requires a reminder action")
                    body["action"]["media_ids"] = ns.media_id
            except ValueError as exc:
                ctx.err.write(f"{exc}\n")
                return EXIT_USAGE
        if not body:
            ctx.err.write("nothing to change — pass --name, --when or --action\n")
            return EXIT_USAGE
        reply = _guarded_job_call(ctx, lambda: client.request("PATCH", f"/api/jobs/{ns.job_id}", _selection_body(ns, body)))
        if reply is None:
            return EXIT_FAILED
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        job = reply.get("job") or {}
        if not reply.get("ok"):
            ctx.say(f"{ns.job_id}: {reply.get('error') or reply}")
            return EXIT_OK
        ctx.say(f"edited {job.get('id')}  {job.get('schedule_text')} ({job.get('cron')})  {job.get('name')}")
        return EXIT_OK
    if ns.action == "runs":
        if ns.limit is not None and not 1 <= ns.limit <= 100:
            ctx.err.write("run limit must be 1-100\n")
            return EXIT_USAGE
        path = (f"/api/jobs/{quote(ns.job_id, safe='')}/runs" if ns.job_id else "/api/jobs/runs")
        reply = client.get(path + ("?" + urlencode({"limit": ns.limit}) if ns.limit is not None else "")) or {}
        if ns.json:
            machine(reply)
            return EXIT_OK
        runs = reply.get("runs") or []
        if not runs:
            ctx.say("no runs yet")
        for run in runs:
            ctx.say(f"{_log_display(run.get('job_id'), 80)}  {_log_display(run.get('started_at'), 40)}  "
                    f"{_log_display(run.get('status'), 20):7s} {_log_display(run.get('summary'), 100)}")
        return EXIT_OK
    if ns.action in ("delete", "remove"):
        reply = client.request("DELETE", f"/api/jobs/{ns.job_id}") or {}
        ctx.say(f"deleted {ns.job_id}" if reply.get("ok") else f"{ns.job_id}: {reply}")
        return EXIT_OK
    body = {"reason": ns.reason} if ns.action == "pause" and ns.reason else {}
    reply = client.post(f"/api/jobs/{ns.job_id}/{ns.action}", body) or {}
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    job = reply.get("job") or {}
    if ns.action == "run":
        receipt = reply.get("request")
        if isinstance(receipt, dict):
            ctx.say(f"accepted · {receipt.get('status')} · request {receipt.get('id')}; "
                    f"nerva jobs status {ns.job_id} --request {receipt.get('id')}")
            return EXIT_OK
        run = reply.get("run") or {}
        ctx.say(f"{run.get('status')}: {run.get('summary', '')}")
        return EXIT_OK if run.get("status") in {"ok", "pending"} else EXIT_FAILED
    state = "paused" if job.get("paused_reason") else "runnable"
    ctx.say(f"{ns.job_id} is {state}")
    return EXIT_OK


def cmd_sessions(ns: argparse.Namespace, ctx: Context) -> int:
    if getattr(ns, "session_action", None) == "continue":
        reply = ctx.client().post("/sessions/continue", {"source_session_id": ns.source_session_id, "request_id": ns.request_id})
        if ns.json:
            ctx.dump(reply)
        else:
            ctx.say(f"Created {reply['session_id']}; continue with nerva chat --session {reply['session_id']} MESSAGE")
        return EXIT_OK
    if getattr(ns, "session_action", None) == "import":
        from .client import is_loopback_url
        from .foreign_sessions import ForeignSourceError, read_file

        if not is_loopback_url(hub_url(ctx.environ)):
            ctx.err.write("foreign transcripts can only be imported to a local hub\n")
            return EXIT_AUTH
        try:
            parsed = read_file(ns.foreign_source, ns.path)
        except ForeignSourceError as exc:
            ctx.err.write(f"{exc}\n")
            return EXIT_FAILED
        import uuid
        reply = ctx.client().post("/sessions/import", {**parsed, "request_id": str(uuid.uuid4())})
        if ns.json:
            ctx.dump(reply)
        else:
            ctx.say(f"Imported {reply['session_id']}; resume with nerva chat -r {reply['session_id']} MESSAGE")
        return EXIT_OK
    if getattr(ns, "session_action", None) == "export":
        return _export_trajectories(ns, ctx)
    reply = ctx.client().get("/sessions")
    sessions = (reply or {}).get("sessions") or []
    if ns.json:
        ctx.dump(sessions)
        return EXIT_OK
    if not sessions:
        ctx.say("no sessions recorded")
        return EXIT_OK
    for row in sessions:
        # H440: the id a resume opens. ``continuations`` counts the other sessions of the
        # row's conversation (earlier parts, other branches); ``earlier_part`` marks a
        # session that was continued and then used again.
        sid = row.get("resume_id") or row.get("session_id") or row.get("id") or "?"
        started = row.get("started_at") or ""
        title = row.get("title") or ""   # H413
        more = row.get("continuations") or 0
        note = (f"  (+{more} other session{'' if more == 1 else 's'} in this conversation)"
                if isinstance(more, int) and not isinstance(more, bool) and more > 0 else "")
        if row.get("earlier_part") is True:
            note += "  (earlier part, still in use)"
        ctx.say(f"{sid}  {started}  {title}".rstrip() + note)
    return EXIT_OK


def _export_trajectories(ns: argparse.Namespace, ctx: Context) -> int:
    """H652 — ``nerva sessions export ID --sharegpt``: one JSONL row per saved turn, to
    ``-o`` or stdout; the count (and why there may be none) goes to stderr, so a pipe
    into a trainer reads only rows."""
    from urllib.parse import quote

    query = f"format={ns.export_format}" + ("&completed_only=true" if ns.completed_only else "")
    reply = ctx.client().get(f"/sessions/{quote(ns.session_id, safe='')}/trajectories?{query}") or {}
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    rows = reply.get("trajectories") or []
    data = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    if ns.out == "-":
        ctx.out.write(data)
    else:
        with open(ns.out, "w", encoding="utf-8") as handle:
            handle.write(data)
    noun = "trajectory" if len(rows) == 1 else "trajectories"
    ctx.err.write(f"{len(rows)} {noun} ({ns.export_format}) from session {ns.session_id}"
                  + ("" if ns.out == "-" else f" written to {ns.out}") + "\n")
    if not rows and reply.get("capture_enabled") is False:
        ctx.err.write("trajectory capture is off; set NERVA_SAVE_TRAJECTORIES=1 on the hub to save full turns\n")
    return EXIT_OK


#: How `nerva todo` draws a status — the same four Hermes uses.
_TODO_MARKS = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]", "cancelled": "[-]"}


#: Who wrote an item's text, when it was not the owner (the posture's principal).
_TODO_WRITERS = {"guest": "guest turn", "system": "background turn"}


def _todo_tags(item: dict) -> list[str]:
    """What the owner should know about an item's text: a guest's or a household
    member's turn wrote it (``operator/guest`` reads as a household turn), a background
    turn did, or it came from an untrusted source."""
    by = str(item.get("by") or "")
    surface, _, principal = by.partition("/")
    tags = []
    if principal == "guest" and surface == "operator":
        tags.append("household turn")
    elif principal in _TODO_WRITERS:
        tags.append(_TODO_WRITERS[principal])
    if item.get("tainted") is True:
        tags.append("untrusted source")
    return tags


def _plan_shape_ok(plan) -> bool:
    return isinstance(plan, dict) and isinstance(plan.get("todos"), list) and all(
        isinstance(item, dict) for item in plan["todos"])


def _print_plan(ctx: Context, plan: dict) -> None:
    todos = plan.get("todos") or []
    done = sum(1 for item in todos if item.get("status") == "completed")
    head = [str(plan.get("session_id") or "?")]
    head += [str(plan[key]) for key in ("agent", "posture") if plan.get(key)]
    stamp = plan.get("updated_at")
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        head.append("updated " + time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp)))
    head.append(f"{done}/{len(todos)} done")
    ctx.say("  ·  ".join(head))
    # Subtasks sit under their parent (H666); a missing, self or cyclic parent draws at
    # the top and nothing is dropped (agents/core/todo_tree.py).
    from agents.core.todo_tree import tree

    for item, depth in tree(todos, lambda row: row.get("id"), lambda row: row.get("parent")):
        mark = _TODO_MARKS.get(str(item.get("status")), "[?]")
        tags = _todo_tags(item)
        ctx.say("  " * (depth + 1) + f"{mark} {item.get('content', '')}"
                + (f"  ({', '.join(tags)})" if tags else ""))


def cmd_todo(ns: argparse.Namespace, ctx: Context) -> int:
    """H315 — what the agent has planned and where it stands, read-only.

    The plans are the ones the model keeps with its `todo` tool; the owner reads them
    here, in the Decision Inbox, and in the tool trail (`nerva tools`), before any
    approval card they lead to appears.
    """
    if ns.session is not None:
        from agents.core.validation import is_valid_session_id

        if not is_valid_session_id(ns.session):
            ctx.err.write(f"not a session id: {ns.session!r} (letters, digits, _ and -)\n")
            return EXIT_USAGE
        plan = ctx.client().get(f"/sessions/{ns.session}/todo")
        if not _plan_shape_ok(plan):
            ctx.err.write("unexpected reply from the hub: no plan in it\n")
            return EXIT_FAILED
        if ns.json:
            ctx.dump(plan)
        elif not plan.get("todos"):
            ctx.say(f"no plan for {ns.session}")
        else:
            _print_plan(ctx, plan)
        return EXIT_OK
    reply = ctx.client().get("/sessions/todo")
    plans = reply.get("plans") if isinstance(reply, dict) else None
    if not isinstance(plans, list) or not all(_plan_shape_ok(plan) for plan in plans):
        ctx.err.write("unexpected reply from the hub: no list of plans in it\n")
        return EXIT_FAILED
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    if not plans:
        ctx.say("no plans yet — the agent writes one when it works through a multi-step task")
        return EXIT_OK
    for plan in plans:
        _print_plan(ctx, plan)
    return EXIT_OK


#: Replies that are NOT an answer. The hub returns each of these as a normal HTTP 200
#: ``{"reply": …}``, so a caller that only looks at the status code cannot tell a refused
#: turn from a real one — and a script would treat "Internal error." as the model's
#: opinion. Each entry maps the hub's own wording to a short machine reason.
#:
#: This is a COPY of constants that live in `agents.core.*`, kept here because the CLI's
#: parser and completion must stay stdlib-only (importing the orchestrator to read one
#: string would pull the whole runtime into `nerva --help`). A copy can drift, so the
#: drift is made loud rather than silent: ``test_nerva_oneshot.py`` imports the real
#: constants and fails the moment one of them changes. Treat a failure there as this
#: table needing an update, not as a broken test.
_NOT_AN_ANSWER: dict[str, str] = {
    # agents.core.agent_runtime._APPROVAL_REPLY
    "I paused the tool loop because this action requires approval.":
        "the turn queued an action for approval and was not executed",
    # agents.core.orchestrator.TURN_BUSY_REPLY
    "I'm still working on your previous message — send that again in a moment.":
        "the session was busy with the previous turn",
    # agents.core.conversation_clock.CONTEXT_REFUSED_REPLY
    "I stopped this turn because its context could not be safely prepared. Please retry; if this persists, reduce the context size.":
        "the turn was refused: its context could not be safely prepared",
    # Older hubs used the pre-dispatch-CAS wording; retain refusal recognition.
    "I stopped this turn because its context compaction could not be safely committed. Please retry.":
        "the turn was refused: its context could not be safely compacted",
    # agents.core.session_continuation.CONTINUATION_REFUSED_REPLY
    "I stopped this turn because this continued conversation could not be safely restored.":
        "the turn was refused: the continued conversation could not be restored",
    # agents.core.llm.base.LOCAL_SELECTION_UNAVAILABLE_REPLY
    "\u26a0\ufe0f No local language model is available. Start LM Studio or Ollama and try again.":
        "no local model is available",
    # agents.core.llm.base.THINKING_EXHAUSTED_REPLY
    "\u26a0\ufe0f The model spent its whole answer budget thinking and produced no visible "
    "answer. Ask again more narrowly, or raise llm.max_tokens (or load a larger-context model).":
        "the model exhausted its answer budget without a visible answer",
    # agents/web.py — the chat route's own two failure replies
    "Internal error.": "the hub failed while handling the turn",
    "Jarvis not initialized.": "the hub has no orchestrator",
    # agents.core.agent_runtime — the tool loop's own stops. Each one means the turn
    # gave up part-way; a script that read them as answers would pipe "I stopped the
    # tool loop because the same tool kept failing." into whatever consumes the reply
    # and record the run as a success.
    "I stopped the tool loop because it reached the safety deadline.":
        "the tool loop stopped: it reached the safety deadline",
    "I stopped the tool loop because its context exceeded the safety budget.":
        "the tool loop stopped: its context exceeded the safety budget",
    "I stopped the tool loop because the model context window metadata could not be validated.":
        "the tool loop stopped: the context window could not be validated",
    "I stopped the tool loop because it kept repeating the same tool call.":
        "the tool loop stopped: it kept repeating the same call",
    "I stopped the tool loop because the same tool kept failing.":
        "the tool loop stopped: the same tool kept failing",
}

#: One stop reason is built with an f-string — agent_runtime's "I stopped the tool loop
#: after N model turns because …" — so no table of exact strings can hold the family.
#: The shared opening is the rule, which also covers stops added after this was written.
_NOT_AN_ANSWER_PREFIXES: dict[str, str] = {
    "I stopped the tool loop": "the tool loop stopped before the turn finished",
}


def _not_an_answer(answer: str) -> str | None:
    """The machine reason this reply is not an answer, or ``None`` if it is one.

    Matched by CONTAINMENT, not equality. The hub does not hand `/chat` the agent's
    reply verbatim: `Orchestrator._synthesize` wraps a single specialist's answer as
    ``"[athena]: …"`` whenever `jarvis` is not among the responders — which is the
    ordinary routed path, not an edge case. An equality test read that wrapper as a
    completed turn and exited 0 with a queued approval printed as the answer, which is
    exactly the Hermes behaviour this verb exists to invert.

    Containment survives the wrapper. It does NOT survive the other synthesis branch,
    where `jarvis.synthesize` re-writes the text through a model. The hub's source-assigned
    ``runtime_stops`` and ``pending_approvals`` fields cover those paths; this table is
    the fallback for older hubs. The trade is deliberate:
    a model that quotes one of these sentences verbatim makes the verb exit non-zero
    with a stated reason, which is the safe direction to be wrong in.
    """
    text = " ".join(str(answer or "").split())
    for sentinel, reason in _NOT_AN_ANSWER.items():
        if " ".join(sentinel.split()) in text:
            return reason
    for prefix, reason in _NOT_AN_ANSWER_PREFIXES.items():
        if prefix in text:
            return reason
    return None


def _pending_ids(raw: Any) -> tuple[list[Any], bool]:
    """``(ids, reported_but_unreadable)`` from a hub's ``pending_approvals``.

    A ``str`` is iterable, so ``list("71")`` is ``['7', '1']`` — two approval ids that
    do not exist, handed to the operator as things to go and decide. Anything that is
    not a list or a tuple is reported as present-but-unreadable rather than exploded:
    a wrong id is worse than no id, because the operator can act on it.
    """
    if not raw:
        return [], False
    if isinstance(raw, (list, tuple)):
        return list(raw), False
    return [], True

#: An escape sequence is stripped whole, terminator included. Dropping only the ESC byte
#: would leave `[2J` behind: inert on a terminal, but noise in the string a script parses.
#: CSI and OSC cover what a model or an echoed tool result actually emits — colour, cursor
#: moves, window titles; anything else falls through to _ANSWER_CONTROL below.
_ANSWER_ESCAPE = re.compile(
    # OSC/DCS/APC/PM: payload bounded, and a newline ends it. Unbounded, one stray
    # `ESC ]` swallowed every character up to the next BEL — across newlines, deleting
    # real answer text; and when no terminator ever arrived the match failed outright
    # and the payload (`0;rm -rf /`) was emitted as visible text, which is the thing
    # the comment above says must not happen. Bounded, both cases lose at most one
    # line of a reply that already contained a terminal escape.
    r"\x1b[\]PX^_][^\x1b\x07\n]{0,256}(?:\x07|\x1b\\|(?=\n)|$)"
    r"|\x1b\[[0-?]*[ -/]*[@-~]"             # CSI … final byte
    r"|\x1b[@-Z\\-_]"                       # two-character escapes
)

#: An answer may legitimately contain newlines and tabs; everything else in the C0/C1
#: range is stripped so a model (or anything upstream of it) cannot repaint the terminal
#: or forge output in a piped run. Deliberately NOT `_plain`, which also eats \n and
#: truncates at 200 characters — that would destroy the payload.
_ANSWER_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _answer_text(reply: Any) -> str:
    text = str(reply if reply is not None else "")
    return _ANSWER_CONTROL.sub("", _ANSWER_ESCAPE.sub("", text))


def _write_answer(ctx: Context, text: str, *, stream: Any = None) -> None:
    """Put the answer on stdout (or *stream*) without letting encoding turn a 0 into a crash.

    stdout's encoding belongs to the caller — a pipe under ``LC_ALL=C`` is ascii — and
    a model may answer in any script. A raw write can therefore raise UnicodeEncodeError
    *after* the turn succeeded, which a caller reads as "the turn did not complete" for
    a turn that did, and which skips the receipt that was promised on every path.
    """
    out = ctx.out if stream is None else stream
    try:
        out.write(text + "\n")
        return
    except UnicodeEncodeError:
        pass
    encoding = getattr(out, "encoding", None) or "utf-8"
    out.write(text.encode(encoding, "backslashreplace").decode(encoding, "replace") + "\n")


def _recall_lines(reply: Any) -> list[str]:
    """H430 — the turn's memory recall indicator, one line per memory provider, from the
    ``outcome.recall`` a hub sends its owner. Rendered by the hub's own renderer
    (``recall_admission.describe_recalls``), which renders only counts and closed words:
    anything else in the payload prints nothing."""
    outcome = reply.get("outcome") if isinstance(reply, dict) else None
    if not isinstance(outcome, dict):
        return []
    from agents.core.memory.recall_admission import describe_recalls

    return describe_recalls(outcome.get("recall"))


def _utc_now() -> str:
    """This run's clock. The hub has its own; these timestamps date the CLI's attempt."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _elapsed_ms(started: str, finished: str) -> int | None:
    from datetime import datetime

    try:
        return int((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds() * 1000)
    except (TypeError, ValueError):
        return None


def _usage_report(**fields: Any) -> dict[str, Any]:
    """The run report, with `null` wherever the value was not actually obtained.

    Never 0 for "unknown": a spend report that prints $0.00 because nobody measured
    is the exact lie this file exists to avoid. A validated server snapshot can fill
    these fields; a missing or malformed one leaves the original null values.
    """
    report: dict[str, Any] = {
        "schema": "nerva.chat.usage.v1",
        "status": "failed", "completed": False, "exit_code": EXIT_FAILED,
        "started_at": None, "finished_at": None, "duration_ms": None,
        "session_id": None, "requested_session_id": None,
        "agent": None, "model": None, "provider": None,
        "api_calls": None, "input_tokens": None, "output_tokens": None,
        "estimated_cost_usd": None, "usage_basis": "unavailable", "cost_basis": "unavailable",
        "runtime_stops": [],
        "pending_approvals": [], "reason": None,
    }
    report.update(fields)
    return report


def _validated_turn_usage(value: Any) -> dict[str, Any] | None:
    """Copy only the bounded, internally consistent v1 telemetry object.

    The CLI cannot infer spend from prose, a model display name, or a legacy hub.
    Treat any malformed field as an unavailable snapshot instead of writing a
    plausible looking partial bill to the atomic receipt.
    """
    import math

    if not isinstance(value, dict) or value.get("schema") != "nerva.turn.usage.v1":
        return None
    usage_bases = {"measured_zero", "provider_complete", "unknown"}
    cost_bases = {"measured_zero", "local_zero", "price_table", "unknown"}

    def count(item: Any, limit: int) -> bool:
        return item is None or (type(item) is int and 0 <= item <= limit)

    def cost(item: Any) -> bool:
        return item is None or (type(item) in (int, float) and 0 <= item <= 1_000_000_000
                                and math.isfinite(item))

    def identity(item: Any, limit: int) -> bool:
        return item is None or (isinstance(item, str) and 0 < len(item) <= limit
                                and re.fullmatch(r"[A-Za-z0-9._/+:-]+", item) is not None
                                and "://" not in item)

    def row(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        if not {"api_calls", "input_tokens", "output_tokens", "estimated_cost_usd",
                "model", "provider", "usage_basis", "cost_basis"} <= item.keys():
            return False
        calls, inp, out = (item.get(key) for key in ("api_calls", "input_tokens", "output_tokens"))
        amount = item.get("estimated_cost_usd")
        usage, basis = item.get("usage_basis"), item.get("cost_basis")
        if not (count(calls, 1_000_000) and count(inp, 1_000_000_000_000)
                and count(out, 1_000_000_000_000) and cost(amount)
                and identity(item.get("model"), 120) and identity(item.get("provider"), 64)
                and isinstance(usage, str) and usage in usage_bases
                and isinstance(basis, str) and basis in cost_bases):
            return False
        if usage == "measured_zero":
            return (calls == inp == out == 0 and amount == 0 and basis == "measured_zero"
                    and item.get("model") is None and item.get("provider") is None)
        if usage == "provider_complete" and (calls is None or calls < 1 or inp is None or out is None):
            return False
        if usage == "unknown" and (inp is not None or out is not None):
            return False
        if basis == "unknown":
            return amount is None
        if basis == "local_zero":
            return usage == "provider_complete" and amount == 0
        if basis == "price_table":
            return usage == "provider_complete" and amount is not None
        return False

    if not row(value):
        return None
    breakdown = value.get("breakdown")
    if not isinstance(breakdown, list) or len(breakdown) > 16 or not all(row(entry) for entry in breakdown):
        return None
    if value.get("usage_basis") == "measured_zero" and breakdown:
        return None
    truncated = value.get("breakdown_truncated", False)
    if type(truncated) is not bool:
        return None
    date = value.get("price_verified_at")
    if (value.get("cost_basis") == "price_table") != (date is not None):
        return None
    if date is not None:
        from datetime import date as calendar_date

        if not isinstance(date, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) is None:
            return None
        try:
            calendar_date.fromisoformat(date)
        except ValueError:
            return None
    fields = {key: value[key] for key in (
        "api_calls", "input_tokens", "output_tokens", "estimated_cost_usd",
        "model", "provider", "usage_basis", "cost_basis",
    )}
    fields["breakdown"] = [{key: entry.get(key) for key in (
        "api_calls", "input_tokens", "output_tokens", "estimated_cost_usd",
        "model", "provider", "usage_basis", "cost_basis",
    )} for entry in breakdown]
    if "breakdown_truncated" in value:
        fields["breakdown_truncated"] = truncated
    if date is not None:
        fields["price_verified_at"] = date
    return fields


# Keep this stdlib-only CLI list aligned with agents.core.turn_stops.STOP_REASONS.
TURN_STOP_REASONS = frozenset({
    "window_invalid", "context_refused", "turn_revoked", "replay_refused",
    "tool_call_limit", "no_capability", "no_tools", "tools_withdrawn",
    "guardian_denied", "repeated_call", "approval_required", "failing_tool",
    "iteration_limit", "deadline", "thinking_exhausted", "generation_failed",
    "generation_refused", "continuation_refused",
})


def _validated_runtime_stops(value: Any) -> list[str] | None:
    if (not isinstance(value, list) or len(value) > len(TURN_STOP_REASONS)
            or any(type(reason) is not str or reason not in TURN_STOP_REASONS for reason in value)
            or value != sorted(set(value))):
        return None
    return list(value)


def _write_usage(path: str, report: dict[str, Any], ctx: Context) -> None:
    """Write the report atomically, so a reader never sees a half-written file.

    A path that cannot be written is a warning, not a different exit code: the run's
    outcome is the run's outcome, and losing the receipt must not change it.
    """
    import tempfile

    temporary = ""
    try:
        target = Path(path)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False,
                                         dir=str(target.parent or "."),
                                         prefix=".nerva-usage-", suffix=".json") as handle:
            temporary = handle.name
            # `ensure_ascii=False` keeps the file readable, but a lone surrogate from
            # the hub then raises UnicodeEncodeError — a ValueError, not an OSError, so
            # it used to escape this handler and crash the verb *after* the answer was
            # already on stdout. Losing the receipt must not change the run's outcome.
            json.dump(report, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        os.replace(temporary, target)
        temporary = ""
    except (OSError, ValueError, TypeError) as exc:
        reason = getattr(exc, "strerror", None) or type(exc).__name__
        ctx.err.write(f"could not write the usage file to {_plain(path, 120)}: {reason}\n")
    finally:
        # NamedTemporaryFile(delete=False) outlives a failed dump or a failed replace;
        # without this, a cron entry with a mistyped path drops one hidden report file
        # per run into the target's directory, forever.
        if temporary:
            import contextlib

            with contextlib.suppress(OSError):
                os.unlink(temporary)


def cmd_chat(ns: argparse.Namespace, ctx: Context) -> int:
    """One scripted turn. H002 — a turn in, an answer out, and an exit code a script can trust.

    The governance clause of the row this implements is binding and visible here: Hermes'
    one-shot mode sets its own YOLO and accept-hooks flags because "no user is watching".
    Nerva does the opposite. A turn that queues an action for approval stays queued; this
    verb reports it on stderr and exits non-zero, and there is no flag that changes that.
    Nothing in this function can approve, execute or bypass a queued item.
    """
    oneshot = bool(getattr(ns, "oneshot", False))
    usage_file = getattr(ns, "usage_file", None)
    if usage_file is not None and not str(usage_file).strip():
        # `--usage-file "$SPEND_FILE"` with SPEND_FILE unset. Treating it as "no receipt
        # requested" makes the flag vanish in silence; an unwritable path is warned
        # about, and so is this.
        ctx.err.write("--usage-file was given an empty path; no report will be written\n")
        usage_file = None
    started = _utc_now()
    # A request names intent; only a decoded /chat response can establish the session
    # actually used. The vision branch and every pre-response failure leave this unknown.
    observed_session_id: str | None = None
    observed_usage: dict[str, Any] | None = None
    observed_stops: list[str] = []
    observed_pending: list[Any] = []
    stops_unreadable = False
    interrupted_receipt_written = False

    def finish(code: int, *, status: str, reason: str | None = None,
               pending: list[Any] | None = None, completed: bool | None = None) -> int:
        nonlocal interrupted_receipt_written
        if code == EXIT_INTERRUPTED and interrupted_receipt_written:
            return code
        if usage_file:
            finished = _utc_now()
            _write_usage(usage_file, _usage_report(
                status=status,
                # `completed` is explicit where the exit code and the outcome disagree:
                # without `-z` the verb always exits 0 to keep every existing caller
                # working, but a turn that queued an approval did not complete, and the
                # receipt is machine-readable state, not a terminal courtesy.
                completed=(code == EXIT_OK) if completed is None else completed,
                exit_code=code,
                started_at=started, finished_at=finished,
                duration_ms=_elapsed_ms(started, finished),
                session_id=observed_session_id,
                requested_session_id=getattr(ns, "session", None) or None,
                agent=getattr(ns, "agent", None) or None,
                runtime_stops=list(observed_stops),
                pending_approvals=list(pending or []), reason=reason,
                **(observed_usage or {}),
            ), ctx)
        if code == EXIT_INTERRUPTED:
            interrupted_receipt_written = True
        return code

    def perform() -> int:
        nonlocal observed_session_id, observed_usage, observed_stops, observed_pending, stops_unreadable
        if oneshot and ns.json:
            ctx.err.write("-z and --json both own stdout; pick one\n")
            return finish(EXIT_USAGE, status="usage", reason="-z and --json are mutually exclusive")
        message, why = _send_body(ns, ctx, verb="nerva chat", bound=CHAT_MAX_CHARS)
        if message is None:
            ctx.err.write(f"{why}\n")
            return finish(EXIT_USAGE, status="usage", reason=why)
        if len(message) > CHAT_MAX_CHARS:
            # _send_body bounds what it *reads* from a file or stdin; an argument arrives
            # whole. `ChatRequest.message` is max_length=4096, so the hub would answer 422 —
            # which a script reads as "the turn failed". It is a usage error, and it is one
            # before the request rather than after it.
            why = (f"the prompt is {len(message):,} characters, and one chat turn carries up to "
                   f"{CHAT_MAX_CHARS:,} — trim it, or split the turn")
            ctx.err.write(f"{why}\n")
            return finish(EXIT_USAGE, status="usage", reason=why)

        selected_session = getattr(ns, "session", None)
        selector = getattr(ns, "resume", None)
        latest_mode = bool(getattr(ns, "continue_latest", False))
        if selector or latest_mode:
            from .foreign_sessions import ForeignSourceError
            try:
                if selector and selector.startswith(("@claude", "@codex")):
                    from .client import is_loopback_url
                    from .foreign_sessions import discover, read_file

                    if not is_loopback_url(hub_url(ctx.environ)):
                        raise ForeignSourceError("foreign transcripts can only be imported to a local hub")
                    source, _, external_id = selector[1:].partition(":")
                    if source not in {"claude", "codex"}:
                        raise ForeignSourceError("invalid foreign selector")
                    parsed = read_file(source, discover(source, external_id or None))
                    import uuid
                    imported = ctx.client().post("/sessions/import", {**parsed, "request_id": str(uuid.uuid4())})
                    selector = imported["session_id"]
                resolved = ctx.client().post("/sessions/resolve", {
                    "selector": selector or "latest", "latest_mode": latest_mode})
                selected_session = resolved["session_id"]
                recap = resolved.get("recap")
                if recap:
                    ctx.err.write(str(recap.get("text", "") if isinstance(recap, dict) else recap).rstrip() + "\n")
            except ForeignSourceError as exc:
                ctx.err.write(f"{exc}\n")
                return finish(EXIT_FAILED, status="failed", reason=str(exc))
            except HubError as exc:
                ctx.err.write(f"{exc}\n")
                return finish(EXIT_AUTH if exc.status in {401, 403} else EXIT_FAILED,
                              status="unauthorised" if exc.status in {401, 403} else "failed", reason=str(exc))
        if selected_session:
            ns.session = selected_session

        if getattr(ns, "image", None) or getattr(ns, "clipboard_image", False):
            return _vision_turn(ns, ctx, message, finish=finish, oneshot=oneshot)
        if getattr(ns, "remote_vision", None) is not None:
            why = "--remote-vision applies only to an image turn (--image or --clipboard-image)"
            ctx.err.write(f"{why}\n")
            return finish(EXIT_USAGE, status="usage", reason=why)
        if getattr(ns, "acknowledge_training", False) or getattr(ns, "confirm_expensive", False):
            why = "selection confirmation flags on chat apply only to an image turn (--image or --clipboard-image)"
            ctx.err.write(f"{why}\n")
            return finish(EXIT_USAGE, status="usage", reason=why)

        body: dict[str, Any] = {"message": message}
        if ns.agent:
            body["agent"] = ns.agent
        if getattr(ns, "reasoning", None) is not None:
            body["reasoning"] = ns.reasoning
        if selected_session:
            body["session_id"] = selected_session
        # H226: on a terminal, the turn's clarify and secret prompts are answered here,
        # mid-turn, through the hub's pending-input routes. A script (piped stdin) is
        # never read, so nothing changes for it.
        interactive = (_is_tty(ctx.inp) and not ns.json
                       and not getattr(ns, "no_prompts", False))
        try:
            if interactive:
                from .chat_prompts import run_turn

                reply = run_turn(ctx, body, read_secret=ctx.secret_reader)
            else:
                reply = ctx.client().post("/chat", body)
        except HubUnavailable:
            finish(EXIT_NO_HUB, status="no_hub", reason="no hub is reachable")
            raise
        except HubError as exc:
            observed_usage = _validated_turn_usage(getattr(exc, "usage", None))
            if getattr(exc, "runtime_stops", None) is not None:
                parsed_stops = _validated_runtime_stops(exc.runtime_stops)
                stops_unreadable = parsed_stops is None
                observed_stops = parsed_stops or []
            status = "unauthorised" if exc.status in (401, 403) else "failed"
            finish(EXIT_AUTH if exc.status in (401, 403) else EXIT_FAILED,
                   status=status, reason=("the hub returned invalid runtime-stop metadata"
                                          if stops_unreadable else str(exc)))
            raise

        if isinstance(reply, dict):
            observed_usage = _validated_turn_usage(reply.get("usage"))
            if "runtime_stops" in reply:
                parsed_stops = _validated_runtime_stops(reply["runtime_stops"])
                stops_unreadable = parsed_stops is None
                observed_stops = parsed_stops or []
            returned_session = reply.get("session_id")
            if isinstance(returned_session, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", returned_session):
                observed_session_id = returned_session

        raw = (reply or {}).get("reply", "") if isinstance(reply, dict) else ""
        # Sanitise BEFORE judging, not after. The verdict used to read the raw reply while
        # the printer read the cleaned one, so a reply made only of control characters was
        # "not empty" to the guard and an empty line to stdout — exit 0 over nothing — and
        # a sentinel padded with control bytes slipped the table entirely.
        answer = _answer_text(raw)
        # A hub that reports what the turn queued (ChatResponse.pending_approvals) lets this
        # name the ids; an older one does not, and then the refusal is reported without them.
        pending, pending_unreadable = _pending_ids(
            (reply or {}).get("pending_approvals") if isinstance(reply, dict) else None)
        observed_pending = list(pending)
        refusal = _not_an_answer(answer)
        queued = bool(pending or pending_unreadable or "approval_required" in observed_stops
                      or (refusal and "approval" in refusal))
        incomplete = bool(refusal or queued or not answer.strip() or observed_stops or stops_unreadable)
        stop_reason = ("the hub returned invalid runtime-stop metadata" if stops_unreadable else
                       f"model turn stopped: {', '.join(observed_stops)}" if observed_stops else None)

        if not oneshot:
            # The interactive shape is unchanged: print whatever came back, exit 0. Scripts
            # that need the verdict use -z; changing this would break every existing caller.
            # The receipt is new surface, so it is allowed to say what the exit code cannot.
            if ns.json:
                ctx.dump(reply)
            else:
                # H430: which memory this turn used, before the answer (Hermes prints it right
                # after the prefetch) and on stderr, so stdout stays exactly the answer.
                for line in _recall_lines(reply):
                    _write_answer(ctx, line, stream=ctx.err)
                ctx.say(str(raw))
            if interactive and pending:
                from .chat_prompts import decide_queued

                decide_queued(ctx, pending)
            status = "queued_for_approval" if queued else "refused" if incomplete else "completed"
            return finish(EXIT_OK, status=status, reason=stop_reason or refusal, pending=pending,
                          completed=not incomplete)

        if incomplete:
            reason = stop_reason or refusal or ("the turn queued an action for approval and was not executed"
                                 if queued else "the hub returned an empty answer")
            decided: dict[int, str] = {}
            if interactive and pending:
                from .chat_prompts import decide_queued

                decided = decide_queued(ctx, pending)
            if decided:
                # The decision is made, but the action runs later on the hub: the turn still
                # did not complete, and the receipt says what was decided here.
                reason = (f"{reason}; decided here: "
                          + ", ".join(f"#{i} {a}" for i, a in sorted(decided.items())))
            if pending:
                ids = ", ".join(_plain(i, 40) for i in pending)
                reason = f"{reason} (approval {ids})"
                ctx.err.write(f"{reason}; decide it with `nerva approvals`\n")
            elif pending_unreadable:
                ctx.err.write(f"{reason}; this hub reported the approval in a shape this "
                              "version cannot read — run `nerva approvals` to find it\n")
            elif queued:
                ctx.err.write(f"{reason}; this hub did not report the id — run `nerva approvals` to find it\n")
            else:
                ctx.err.write(f"{reason}\n")
            status = "queued_for_approval" if queued else "refused"
            return finish(EXIT_FAILED, status=status, reason=reason, pending=pending)

        _write_answer(ctx, answer)
        return finish(EXIT_OK, status="completed", pending=pending)

    try:
        return perform()
    except KeyboardInterrupt:
        finish(EXIT_INTERRUPTED, status="interrupted", reason="interrupted", pending=observed_pending)
        raise


#: What one vision turn carries (agents/core/routers/composer_vision.py, the HUD's
#: composer alike): up to eight rasters of up to 4 MiB each, and a 4 000-character question.
VISION_MAX_IMAGES = 8
VISION_MAX_BYTES = 4 * 1024 * 1024
VISION_MAX_PROMPT = 4_000
_RASTER_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _image_mime(raw: bytes) -> str | None:
    """The raster type the bytes are, by their signature, never by a file name."""
    for magic, mime in _RASTER_MAGIC:
        if raw.startswith(magic):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _read_image(path: str) -> tuple[bytes | None, str]:
    """``(bytes, "")`` for a regular raster file of at most 4 MiB, else ``(None, why)``.
    The file is opened once, without blocking, and judged by what was opened: a path
    swapped for a pipe between a check and the read never hangs the verb."""
    import stat

    target = Path(path).expanduser()
    try:
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    except FileNotFoundError:
        return None, f"--image {path}: not a file"
    except OSError as exc:
        # Metadata after a denied open only explains refusal; it never admits a read.
        try:
            directory = isinstance(exc, IsADirectoryError) or (
                isinstance(exc, PermissionError) and target.is_dir())
        except OSError:
            directory = False
        if directory:
            return None, f"--image {path}: not a file"
        return None, f"--image {path}: cannot be read ({exc.strerror or exc.__class__.__name__})"
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None, f"--image {path}: not a file"
        with os.fdopen(fd, "rb") as fh:
            fd = -1
            raw = fh.read(VISION_MAX_BYTES + 1)
    except OSError as exc:
        return None, f"--image {path}: cannot be read ({exc.strerror or exc.__class__.__name__})"
    finally:
        if fd >= 0:
            os.close(fd)
    if len(raw) > VISION_MAX_BYTES:
        return None, f"--image {path}: larger than 4 MiB"
    if _image_mime(raw) is None:
        return None, f"--image {path}: not a PNG, JPEG, GIF or WebP image"
    return raw, ""


#: PowerShell's own clipboard reader: the image as PNG on binary stdout, nothing else.
_POWERSHELL_CLIPBOARD = (
    "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
    "$i=[System.Windows.Forms.Clipboard]::GetImage();"
    "if($i){$m=New-Object System.IO.MemoryStream;"
    "$i.Save($m,[System.Drawing.Imaging.ImageFormat]::Png);"
    "$o=[Console]::OpenStandardOutput();$o.Write($m.ToArray(),0,[int]$m.Length);$o.Flush()}")
#: macOS without pngpaste: AppleScript prints the clipboard's PNG as «data PNGf<hex>».
_OSASCRIPT_CLIPBOARD = "the clipboard as «class PNGf»"
_WSL_POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False


def _windows_powershell(environ: Mapping[str, str], which: Callable[..., str | None],
                        exists: Callable[[str], bool]) -> str | None:
    """Windows PowerShell from the system directory, else the first powershell.exe or
    pwsh.exe in an absolute PATH entry that is not the current directory, which Windows
    searches first (review-H586 m4)."""
    system = os.path.join(environ.get("SystemRoot") or "C:\\Windows", "System32",
                          "WindowsPowerShell", "v1.0", "powershell.exe")
    if exists(system):
        return system
    # Never shutil.which here: on Windows it puts the current directory back at the
    # front of any path it is given (review-H586b B3). The absolute PATH entries are
    # walked instead, the current directory left out.
    cwd = os.path.normcase(os.path.abspath(os.getcwd()))
    entries = [e for e in (environ.get("PATH") or "").split(os.pathsep)
               if e and e != "." and os.path.isabs(e) and os.path.normcase(os.path.abspath(e)) != cwd]
    for name in ("powershell.exe", "pwsh.exe"):
        for entry in entries:
            candidate = os.path.join(entry, name)
            if exists(candidate):
                return candidate
    return None


def _clipboard_command(platform: str, environ: Mapping[str, str],
                       which: Callable[..., str | None], *, wsl: bool = False,
                       exists: Callable[[str], bool] = os.path.isfile) -> list[str] | None:
    """The fixed argv that prints the clipboard's image on this machine, or None:
    pngpaste, else osascript (macOS); PowerShell (Windows); wl-paste (Wayland), xclip
    (X11), else Windows PowerShell through WSL interop."""
    if platform == "darwin":
        if which("pngpaste"):
            return ["pngpaste", "-"]
        return ["osascript", "-e", _OSASCRIPT_CLIPBOARD] if which("osascript") else None
    if platform.startswith("win"):
        exe = _windows_powershell(environ, which, exists)
        return [exe, "-NoProfile", "-STA", "-Command", _POWERSHELL_CLIPBOARD] if exe else None
    if environ.get("WAYLAND_DISPLAY") and which("wl-paste"):
        return ["wl-paste", "--no-newline", "--type", "image/png"]
    if environ.get("DISPLAY") and which("xclip"):
        return ["xclip", "-selection", "clipboard", "-target", "image/png", "-out"]
    if wsl:
        # The interop default, else wherever PATH puts it (a custom automount root).
        exe = _WSL_POWERSHELL if exists(_WSL_POWERSHELL) else which("powershell.exe")
        if exe:
            return [exe, "-NoProfile", "-STA", "-Command", _POWERSHELL_CLIPBOARD]
    return None


def _run_reader(argv: list[str], limit: int, deadline: float = 10.0) -> tuple[int | None, bytes, str]:
    """``(exit code, stdout, why)``: the reader's output, read up to *limit* + 1 bytes
    and never more, within *deadline* seconds; a reader that says more, or takes
    longer, is killed (review-H586 m2). On POSIX it runs in a session of its own and
    the whole group is killed, so a descendant holding the pipe open cannot stretch the
    deadline, and the pipe is read against a monotonic clock, never by a thread
    (review-H586b B2). An interrupt kills it too."""
    import subprocess  # nosec B404  (a fixed argv, never a shell)
    import time

    posix = os.name == "posix"
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,  # noqa: S603  # nosec B603
                                stderr=subprocess.DEVNULL, start_new_session=posix)
    except OSError as exc:
        return None, b"", f"{argv[0]} failed ({exc.__class__.__name__})"

    def kill() -> None:
        with _suppressed():
            if posix:
                import signal

                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()

    end = time.monotonic() + deadline
    out = bytearray()
    timed_out = False
    pump_alive = False
    try:
        if posix:
            import selectors

            fd = proc.stdout.fileno()
            with selectors.DefaultSelector() as selector:
                selector.register(fd, selectors.EVENT_READ)
                while len(out) <= limit:
                    left = end - time.monotonic()
                    if left <= 0 or not selector.select(left):
                        timed_out = True
                        break
                    chunk = os.read(fd, min(1 << 16, limit + 1 - len(out)))
                    if not chunk:
                        break
                    out += chunk
        else:
            import threading

            box: dict[str, bytes] = {}
            pump = threading.Thread(target=lambda: box.setdefault("out", proc.stdout.read(limit + 1)),
                                    daemon=True)
            pump.start()
            pump.join(deadline)
            pump_alive = pump.is_alive()
            timed_out = pump_alive
            out += box.get("out", b"")
        if timed_out:
            kill()
            return None, b"", f"{argv[0]} did not answer within {deadline:g} s"
        if len(out) > limit:
            kill()
            return None, bytes(out[: limit + 1]), ""
        try:
            code = proc.wait(timeout=max(0.1, end - time.monotonic()))
        except subprocess.TimeoutExpired:
            kill()
            code = None
        return code, bytes(out), ""
    finally:
        if proc.poll() is None:
            kill()                       # an interrupt, or anything else, never leaves it running
        if not pump_alive:
            with _suppressed():
                proc.stdout.close()
        with _suppressed():
            proc.wait(timeout=2)


def _suppressed():
    import contextlib

    return contextlib.suppress(Exception)


def _clipboard_image(environ: Mapping[str, str]) -> tuple[bytes | None, str]:
    """``(bytes, "")`` for the clipboard's image, else ``(None, why)``. Nothing but the
    platform's own clipboard reader runs, with a fixed argv and no shell, its output
    bounded while it is read."""
    import binascii
    import shutil

    argv = _clipboard_command(sys.platform, environ, shutil.which, wsl=_is_wsl())
    if argv is None:
        return None, ("--clipboard-image: no clipboard reader found (wl-paste or xclip on "
                      "Linux, pngpaste or osascript on macOS, PowerShell on Windows and WSL); "
                      "save the image and pass --image PATH")
    hexed = argv[0] == "osascript"
    code, raw, why = _run_reader(argv, 2 * VISION_MAX_BYTES + 64 if hexed else VISION_MAX_BYTES)
    if why:
        return None, f"--clipboard-image: {why}"
    if len(raw) > (2 * VISION_MAX_BYTES + 64 if hexed else VISION_MAX_BYTES):
        # Cut off at the bound (and killed): an image too large, not an empty
        # clipboard (review-H586b B1).
        return None, "--clipboard-image: the image is larger than 4 MiB"
    if hexed and code == 0 and raw:
        text = raw.decode("utf-8", errors="replace").strip()
        head, _, body = text.partition("«data PNGf")
        try:
            raw = binascii.unhexlify(body.removesuffix("»")) if body and not head else b""
        except (binascii.Error, ValueError):
            raw = b""
    if code != 0 or not raw:
        return None, "--clipboard-image: the clipboard holds no image"
    if len(raw) > VISION_MAX_BYTES:
        return None, "--clipboard-image: the image is larger than 4 MiB"
    if _image_mime(raw) is None:
        return None, "--clipboard-image: the clipboard's content is not a PNG, JPEG, GIF or WebP image"
    return raw, ""


#: How long an image turn waits for the vision model: the hub gives it 180 s.
VISION_TIMEOUT = 240.0
#: The longest vision answer printed, as the HUD's own display limit.
VISION_MAX_ANSWER = 128 * 1024


def _destination_key(url: str) -> tuple[str, str, int | None, str] | None:
    """A destination as the hub names it (public_config): scheme and host in any case,
    the default port spelled or not, a trailing slash or not — one key."""
    import urllib.parse

    try:
        parts = urllib.parse.urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        return None                     # a look-alike (user@host) is not an acknowledgement
    if port == {"http": 80, "https": 443}[scheme]:
        port = None
    return scheme, parts.hostname.lower(), port, parts.path.rstrip("/")


def _vision_turn(ns: argparse.Namespace, ctx: Context, message: str, *,
                 finish: Callable[..., int], oneshot: bool) -> int:
    """H586 — the terminal's image turn: the HUD composer's, over the same route.

    The images and the question go to POST /api/vlm/composer/describe, the configured
    vision model's route, and never to /chat: no agent, session or tool plan sees them,
    as in the HUD. The destination the hub reports is bound into the request, so a model
    changed in between is refused (409), and a destination off the hub's machine is used
    only when --remote-vision names it (the HUD's per-destination acknowledgement)."""
    import base64

    def usage(why: str) -> int:
        ctx.err.write(f"{why}\n")
        return finish(EXIT_USAGE, status="usage", reason=why)

    def failed(why: str) -> int:
        why = _plain(why, 500)                       # hub text never reaches the terminal raw
        ctx.err.write(f"{why}\n")
        return finish(EXIT_FAILED, status="failed", reason=why)

    for flag, given in (("--agent", ns.agent), ("--session", getattr(ns, "session", None)),
                        ("--reasoning", getattr(ns, "reasoning", None))):
        if given:
            return usage(f"{flag} does not apply to an image turn: it goes to the vision model "
                         "only, never to an agent or a conversation")
    if len(message) > VISION_MAX_PROMPT:
        return usage(f"the question is {len(message):,} characters, and an image turn carries "
                     f"up to {VISION_MAX_PROMPT:,}")
    paths = list(getattr(ns, "image", None) or [])
    count = len(paths) + (1 if getattr(ns, "clipboard_image", False) else 0)
    if count > VISION_MAX_IMAGES:
        return usage(f"{count} images given; one turn carries up to {VISION_MAX_IMAGES}")
    acknowledged = getattr(ns, "remote_vision", None)
    if acknowledged is not None and _destination_key(acknowledged) is None:
        return usage(f"--remote-vision {_plain(acknowledged, 200)}: not a plain http(s) address "
                     "(no user name, query or fragment)")
    images: list[str] = []
    for path in paths:
        raw, why = _read_image(path)
        if raw is None:
            return usage(why)
        images.append(f"data:{_image_mime(raw)};base64,{base64.b64encode(raw).decode('ascii')}")
    if getattr(ns, "clipboard_image", False):
        try:
            raw, why = _clipboard_image(ctx.environ)
        except KeyboardInterrupt:
            finish(EXIT_INTERRUPTED, status="interrupted", reason="interrupted")
            raise
        if raw is None:
            return usage(why)
        images.append(f"data:{_image_mime(raw)};base64,{base64.b64encode(raw).decode('ascii')}")

    client = ctx.client()
    try:
        status = client.get("/api/vlm/composer/status")
        if not isinstance(status, dict) or status.get("configured") is not True:
            return failed("no vision model is configured on the hub (Admin → vision model)")
        destination, binding, local = status.get("destination"), status.get("binding"), status.get("local")
        if not isinstance(destination, str) or not isinstance(binding, str) or not isinstance(local, bool):
            return failed("the hub's vision status is incomplete (destination, binding or local "
                          "missing); nothing was sent")
        if "empty_retries" in status or "retry_notice" in status:
            budget, notice = status.get("empty_retries"), status.get("retry_notice")
            if (type(budget) is not int or budget != 1 or not isinstance(notice, str)
                    or not notice.strip() or len(notice) > 500
                    or any(ord(char) < 32 or ord(char) == 127 for char in notice)):
                return failed("the hub's vision retry policy is invalid; nothing was sent")
            ctx.err.write(f"{_plain(notice, 500)}\n")
        requirements = status.get("selection_requirements", [])
        if not isinstance(requirements, list) or len(requirements) > 8:
            return failed("the hub's vision selection requirements are invalid; nothing was sent")
        needs = set()
        for requirement in requirements:
            if not isinstance(requirement, dict):
                return failed("the hub's vision selection requirements are invalid; nothing was sent")
            need, notice = requirement.get("needs"), requirement.get("message")
            if (not isinstance(need, str) or need not in ("acknowledge_training", "confirm_expensive")
                    or need in needs or not isinstance(notice, str) or not notice.strip()
                    or len(notice) > 500 or any(ord(char) < 32 or ord(char) == 127 for char in notice)):
                return failed("the hub's vision selection requirements are invalid; nothing was sent")
            needs.add(need)
        for requirement in requirements:
            ctx.err.write(f"{_plain(requirement['message'], 500)}\n")
        missing = sorted(need for need in needs if getattr(ns, need, False) is not True)
        if missing:
            flags = " and ".join("--" + need.replace("_", "-") for need in missing)
            return usage(f"this image turn requires {flags}; nothing was sent")
        if local and acknowledged is not None:
            ctx.err.write("--remote-vision is not needed: the vision model is on the hub's machine\n")
        if not local and (acknowledged is None
                          or _destination_key(acknowledged) != _destination_key(destination)):
            return usage(f"the vision model is at {_plain(destination, 200)}, off the hub's machine; "
                         "the images go there only with --remote-vision set to that address")
        where = "on the hub's machine" if local else "off the hub's machine"
        model = _plain(str(status.get("model") or "?"), 80)
        ctx.err.write(f"asking {model} at {_plain(destination, 200)} ({where}) about "
                      f"{len(images)} image(s)\n")
    except KeyboardInterrupt:
        finish(EXIT_INTERRUPTED, status="interrupted", reason="interrupted")
        raise
    except HubUnavailable:
        finish(EXIT_NO_HUB, status="no_hub", reason="no hub is reachable")
        raise
    except HubError as exc:
        if exc.status in (401, 403):
            finish(EXIT_AUTH, status="unauthorised", reason=str(exc))
            raise
        return failed(exc.reason)
    try:
        reply = client.post("/api/vlm/composer/describe", _selection_body(ns, {
            "prompt": message, "images": images, "expected_destination": destination,
            "expected_binding": binding, "remote_ack": not local,
        }), timeout=VISION_TIMEOUT)
    except KeyboardInterrupt:
        finish(EXIT_INTERRUPTED, status="interrupted", reason="interrupted")
        raise
    except HubUnavailable as exc:
        if "timed out" in str(exc):
            # The hub answered the status a moment ago: the model is what is slow.
            return failed(f"the vision model did not answer within {VISION_TIMEOUT:g} s")
        finish(EXIT_NO_HUB, status="no_hub", reason="no hub is reachable")
        raise
    except HubError as exc:
        if exc.status == 401 or (exc.status == 403 and not exc.reason.startswith("Acknowledge")):
            finish(EXIT_AUTH, status="unauthorised", reason=str(exc))
            raise
        return failed(exc.reason)

    if (not isinstance(reply, dict) or reply.get("ok") is not True
            or not isinstance(reply.get("response"), str)):
        return failed("the hub's vision reply is malformed")
    if len(reply["response"]) > VISION_MAX_ANSWER:
        return failed("the vision answer is longer than 128 KiB, the display limit")
    answer = _answer_text(reply["response"])
    if ns.json:
        ctx.dump(reply)
        return finish(EXIT_OK, status="completed" if answer.strip() else "refused",
                      completed=bool(answer.strip()))
    if not answer.strip():
        why = "the vision model returned an empty answer"
        ctx.err.write(f"{why}\n")
        return finish(EXIT_FAILED if oneshot else EXIT_OK, status="refused", reason=why,
                      completed=False)
    _write_answer(ctx, answer)
    return finish(EXIT_OK, status="completed")


#: What one send carries, subject included — the outbound seam's own bound.
SEND_MAX_CHARS = 4_000
#: What one chat turn carries: `ChatRequest.message` is `max_length=4096` (agents/web.py).
#: Checked here so an over-long prompt is a usage error before the request, not an
#: HTTP 422 that a script would read as "the turn failed".
CHAT_MAX_CHARS = 4_096
_NO_BODY = "no message provided. Pass text as an argument, use --file PATH, or pipe it on stdin"
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _plain(text: Any, width: int = 200, *, keep_tail: bool = False) -> str:
    """A string from the hub or the shell, safe to put on a terminal: no control characters."""
    out = _CONTROL_CHARS.sub(" ", "" if text is None else str(text))
    if len(out) <= width:
        return out
    return "…" + out[-(width - 1):] if keep_tail else out[: width - 1] + "…"


def _is_tty(stream: Any) -> bool:
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(callable(isatty) and isatty())
    except (OSError, ValueError):
        return False


def _send_body(ns: argparse.Namespace, ctx: Context, *, verb: str = "nerva send",
               bound: int = SEND_MAX_CHARS) -> tuple[str | None, str]:
    """``(body, "")`` from the MESSAGE argument, else ``--file`` (``-`` is stdin), else piped stdin.

    Hermes' precedence, with its one safety rule kept: a terminal is never read, so a
    script that forgot the body gets a usage error instead of a hang. ``(None, reason)``
    is a usage error; the reason names what to fix and never reflects the file's bytes.

    *verb* and *bound* exist because `chat` reads its prompt exactly the way `send` reads
    its message — same precedence, same refusals — but carries a different limit and must
    name itself correctly when it refuses.
    """
    given = ns.message if isinstance(ns.message, str) and ns.message.strip() else None
    if given is not None and ns.file:
        return None, "give the message as an argument or with --file, not both"
    if given is not None:
        return given, ""
    if ns.file == "-":
        if ctx.inp is None or not hasattr(ctx.inp, "read"):
            return None, "stdin is closed; pipe the body or use --file PATH"
        if _is_tty(ctx.inp):
            return None, f"stdin is a terminal, and {verb} never reads one; pipe the body or use --file PATH"
        return _read_body(ctx.inp, "stdin", verb=verb, bound=bound)
    if ns.file:
        try:
            with open(ns.file, encoding="utf-8-sig") as handle:
                if _is_tty(handle):
                    # `-f -` is guarded above, but an explicit terminal path is the same
                    # hang by another spelling: `-f /dev/tty` (or /dev/stdin from an
                    # interactive shell) blocked forever, which is exactly what the "a
                    # terminal is never read" rule exists to prevent.
                    return None, (f"{_plain(ns.file, 120, keep_tail=True)} is a terminal, and {verb} never "
                                  "reads one; pipe the body or point --file at a file")
                return _read_body(handle, _plain(ns.file, 120, keep_tail=True), verb=verb, bound=bound)
        except OSError as exc:
            return None, f"cannot read {_plain(ns.file, 120, keep_tail=True)}: {exc.strerror or type(exc).__name__}"
    if ctx.inp is not None and hasattr(ctx.inp, "read") and not _is_tty(ctx.inp):
        return _read_body(ctx.inp, "stdin", verb=verb, bound=bound)
    return None, _NO_BODY


def _read_body(stream: Any, label: str, *, verb: str = "nerva send",
               bound: int = SEND_MAX_CHARS) -> tuple[str | None, str]:
    """At most the bound plus one character is read: a runaway file is refused, not loaded."""
    try:
        text = stream.read(bound + 1)
        if isinstance(text, bytes):
            # The bound counts CHARACTERS; `read` on a binary stream counts bytes. A
            # body of 2,000 two-byte characters was being cut mid-character and then
            # reported as "not UTF-8 text" — a wrong diagnosis of a valid body. One
            # UTF-8 character is at most four bytes, so this is enough to decide.
            text += stream.read(3 * (bound + 1))
    except UnicodeDecodeError:
        if label == "stdin":
            return None, f"stdin is not UTF-8 text; {verb} carries text bodies only"
        return None, (f"{label} is not a text file. --file reads the message body (logs, reports, "
                      f"markdown); native attachments are not carried by {verb} yet")
    except OSError as exc:
        return None, f"cannot read {label}: {exc.strerror or type(exc).__name__}"
    if isinstance(text, bytes):
        decoded = None
        for cut in range(4):
            # Only the tail can be a truncated character: drop up to three bytes before
            # calling the body invalid, so an over-long body is refused for its LENGTH
            # rather than misreported as binary.
            try:
                decoded = text[: len(text) - cut].decode("utf-8")
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            return None, f"{label} is not UTF-8 text"
        text = decoded
    if not isinstance(text, str):
        return None, _NO_BODY
    text = text.lstrip("\ufeff")
    if not text.strip():
        return None, _NO_BODY
    if len(text) > bound:
        return None, (f"{label} is longer than {bound:,} characters, which is what {verb} "
                      "carries — trim it, or send the tail")
    return text, ""


def cmd_send(ns: argparse.Namespace, ctx: Context) -> int:
    """One message, no model call. Queue acceptance is never delivery confirmation.

    H480: the body comes from the argument, a file or stdin; a subject rides as ntfy's
    title or as the first line elsewhere; exit codes are 0 sent · 1 not delivered ·
    2 usage, plus Nerva's own 3 (no hub) and 4 (not authorised).
    """
    if ns.list:
        if ns.file or ns.subject:
            ctx.err.write("--list takes no body or subject; a MESSAGE argument filters by channel\n")
            return EXIT_USAGE
        only = (ns.message or "").strip().lower()
        if only:
            from agents.core.channels.outbound import DIRECT_SEND_CHANNELS

            if only not in DIRECT_SEND_CHANNELS:
                ctx.err.write(f"--list filters by a direct-send channel: "
                              f"{', '.join(DIRECT_SEND_CHANNELS)}; not '{only[:32]}'\n")
                return EXIT_USAGE
        client = ctx.client()
        # A hub that does not serve destinations (older, or the route disabled) must not
        # cost the owner the inbox listing too: --list reports what it can reach.
        try:
            targets = client.get("/api/channels/targets")
        except HubError:
            targets = None
        rows_t = targets.get("targets") if isinstance(targets, dict) else None
        if only and isinstance(rows_t, list):
            known = sorted(_plain(r.get("channel", ""), 32) for r in rows_t if isinstance(r, dict))
            rows_t = [r for r in rows_t if isinstance(r, dict) and r.get("channel") == only]
            if not rows_t:
                ctx.err.write(f"no targets found for channel '{only}'. Configured: "
                              f"{', '.join(known) or '(none)'}\n")
                return EXIT_FAILED
        elif only:
            ctx.err.write("this hub does not list send targets; only inbox threads are filtered\n")
        if isinstance(rows_t, list) and not ns.json:
            ctx.say("configured destinations (no inbox thread needed):")
            for row in rows_t:
                mark = "ready " if row.get("ready") else "not ok"
                ctx.say(f"--channel {_plain(row.get('channel', '?'), 32):<9} {mark}  {_plain(row.get('reason', ''))}")
            if rows_t and not any(row.get("ready") for row in rows_t):
                # Spark S-003: the first empty state a stranger meets on the way to their
                # first automation deserves one honest, human line. Delete freely.
                ctx.say("(none ready yet — Nerva has things to say and nowhere to say them; connect one above)")
        status = client.get("/api/channels/inbox/status")
        if not isinstance(status, dict) or status.get("enabled") is not True:
            ctx.err.write("channel inbox unavailable\n")
            return EXIT_FAILED
        reply = client.get("/api/channels/inbox?limit=200")
        rows = reply.get("threads") if isinstance(reply, dict) else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise HubError(0, "malformed inbox target list")
        if only:
            rows = [row for row in rows if row.get("channel") == only]
            if not rows and rows_t is None:
                ctx.err.write(f"no targets found for channel '{only}' on this hub\n")
                return EXIT_FAILED
        if ns.json:
            ctx.dump({"targets": rows_t, "threads": rows})
        elif not rows:
            ctx.say("no inbox targets — receive a message in a configured channel first")
        else:
            ctx.say("recent inbox targets (up to 200):")
            for row in rows:
                ctx.say(f"{_plain(row.get('thread_id', '?'))}  {_plain(row.get('channel', '?'), 32)}  "
                        f"{_plain(row.get('from', ''))}")
        return EXIT_OK

    # The target id is checked before anything is read, so a bad id costs no stdin.
    if ns.channel and not re.fullmatch(r"[a-z0-9_-]{1,32}", ns.channel):
        ctx.err.write("--channel takes a channel id from `nerva send --list`\n")
        return EXIT_USAGE
    # An id is a single path segment, never a URL, a display name or a guessed recipient.
    if not ns.channel and not re.fullmatch(r"[A-Za-z0-9_:-]{1,200}", ns.to or ""):
        ctx.err.write("--to requires an exact thread id from `nerva send --list`\n")
        return EXIT_USAGE
    from agents.core.channels.outbound import carried_length, subject_problem

    subject = (ns.subject or "").strip()
    problem = subject_problem(ns.channel or "", subject)
    if problem:
        ctx.err.write(f"--subject: {problem}\n")
        return EXIT_USAGE
    body, reason = _send_body(ns, ctx)
    if body is None:
        ctx.err.write(f"{reason}\n")
        return EXIT_USAGE
    carried = carried_length(ns.channel or "", body, subject)
    if carried > SEND_MAX_CHARS:
        ctx.err.write(f"the message is {carried:,} characters as delivered (subject included); nerva send "
                      f"carries up to {SEND_MAX_CHARS:,} — trim it, or send the tail\n")
        return EXIT_USAGE

    if ns.channel:
        # A configured destination, not a thread: reversible tier, recorded in the
        # IntentLog by the route. `audited:false` is surfaced, never hidden — an
        # unrecorded send is a real (small) governance gap the owner should see.
        payload = {"channel": ns.channel, "text": body, "source": "nerva.cli.send"}
        if subject:
            payload["subject"] = subject
        reply = ctx.client().post("/api/channels/send", payload)
        sent = isinstance(reply, dict) and reply.get("ok") is True
        if ns.json:
            ctx.dump(reply)
        elif sent and not ns.quiet:
            note = "" if reply.get("audited") else "  (WARNING: not recorded in the audit log)"
            ctx.say(f"sent to {ns.channel}{note}")
        elif not sent:
            reason = reply.get("error") or reply.get("reason") if isinstance(reply, dict) else None
            ctx.err.write(f"not sent: {_plain(reason) or 'the hub refused the message'}\n")
        return EXIT_OK if sent else EXIT_FAILED

    # A thread reply has no title anywhere, so the subject is Hermes' first line.
    text = f"{subject}\n\n{body.lstrip()}" if subject else body
    client = ctx.client()
    path = f"/api/channels/inbox/{ns.to}"
    found = client.get(path)
    thread = found.get("thread") if isinstance(found, dict) else None
    if (not isinstance(thread, dict) or thread.get("thread_id") != ns.to
            or not isinstance(thread.get("reply"), dict) or not thread["reply"]):
        ctx.err.write("target has no resolved inbox recipient; nothing was queued\n")
        return EXIT_FAILED
    reply = client.post(f"{path}/reply", {"text": text, "source": "nerva.cli.send"})
    task_id = reply.get("task_id") if isinstance(reply, dict) else None
    queued = (isinstance(reply, dict) and reply.get("ok") is True
              and reply.get("queued") is True and type(task_id) is int and task_id > 0)
    if ns.json:
        ctx.dump(reply)
    elif queued and not ns.quiet:
        ctx.say(f"queued task {task_id} for {ns.to} — delivery follows the hub's approval policy")
    elif not queued:
        reason = reply.get("reason") if isinstance(reply, dict) else None
        ctx.err.write(f"reply was not queued: {_plain(reason) or 'no durable task returned'}\n")
    return EXIT_OK if queued else EXIT_FAILED


def completion_script(shell: str, parser: argparse.ArgumentParser | None = None, *,
                      profiles_base: str | None = None) -> str:
    """H004/H574 — command paths, help text and profile names; see ``agents.cli.completion``."""
    from .completion import SHELLS
    from .completion import completion_script as generate

    if shell not in SHELLS:
        raise ValueError(f"unsupported completion shell: {shell!r}")
    return generate(shell, parser or build_parser(), profiles_base=profiles_base)


def cmd_completion(ns: argparse.Namespace, ctx: Context) -> int:
    ctx.out.write(completion_script(ns.shell))
    return EXIT_OK


def cmd_prompt_size(ns: argparse.Namespace, ctx: Context) -> int:
    """H048 — the fixed per-call floor, by component, largest first.

    Offline on purpose: it reads the personas off disk and asks the tool registry
    for the specs it already declares. No hub, no backend, no request. That is
    what makes it usable for the question it answers — "what am I paying before
    the conversation starts" — on a box where the hub is not even running.
    """
    import json as _json
    from pathlib import Path

    from agents.core.prompt_size import breakdown, render

    root = Path(__file__).resolve().parent.parent          # …/agents
    specs: list = []
    try:
        from agents.core.tool_rpc import ToolRPCServer  # declared specs only
        server = ToolRPCServer.__new__(ToolRPCServer)
        specs = server.tools() if getattr(server, "_tools", None) else []
    except Exception:
        # A registry that will not construct offline is not a reason to refuse the
        # report: the personas are the dominant term and they are always readable.
        specs = []

    report = breakdown(agents_root=root, tool_specs=specs, skills=())
    if not specs:
        report.notes.append(
            "Tool schemas are not included: the registry is populated at boot, and "
            "this verb deliberately does not boot one. Run it against a live hub's "
            "`nerva tools` output to add them."
        )
    if getattr(ns, "json", False):
        payload = report.as_dict()
        floor, soul = report.per_call(getattr(ns, "agent", "") or "")
        payload["per_call_tokens"] = floor
        payload["per_call_soul"] = soul.name if soul else None
        ctx.out.write(_json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return EXIT_OK
    ctx.out.write(render(report, window=int(getattr(ns, "window", 0) or 0),
                         agent=getattr(ns, "agent", "") or "") + "\n")
    return EXIT_OK


def cmd_uninstall(ns: argparse.Namespace, ctx: Context) -> int:
    """Delegate to agents.core.uninstall — its refusals, typed purge prompt and exit codes."""
    from agents.core import uninstall as _uninstall

    argv = [flag for flag, on in (("--dry-run", ns.dry_run), ("--confirm", ns.confirm),
                                  ("--purge-data", ns.purge_data), ("--no-backup", ns.no_backup),
                                  ("--gui", ns.gui), ("--gui-only", ns.gui_only),
                                  ("--gui-summary", ns.gui_summary)) if on]
    if ns.yes_purge is not None:
        argv.append(f"--yes-purge={ns.yes_purge}")
    if ns.root:
        argv += ["--root", ns.root]
    return _uninstall._main(argv, out=ctx.out, inp=ctx.inp)


def cmd_security(ns: argparse.Namespace, ctx: Context) -> int:
    """Audit this install's three dependency surfaces via the governed admin hub."""
    from agents.core.security import dep_audit

    skip = {"venv": bool(getattr(ns, "skip_venv", False)),
            "plugins": bool(getattr(ns, "skip_plugins", False)),
            "mcp": bool(getattr(ns, "skip_mcp", False))}
    osv_url = getattr(ns, "osv_url", _OSV_DEFAULT)
    fail_on = getattr(ns, "fail_on", "low")
    try:
        dep_audit._https_only(osv_url)
    except ValueError as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    try:
        components, errors = [], []
        if not skip["venv"]:
            found, issues = dep_audit.enumerate_installed()
            components.extend(found)
            errors.extend(issues)
        if not skip["plugins"]:
            found, issues = dep_audit.enumerate_catalog()
            components.extend(found)
            errors.extend(issues)
            found, issues = dep_audit.enumerate_extensions(getattr(ns, "extension", []))
            components.extend(found)
            errors.extend(issues)
        if not skip["mcp"]:
            found, issues = dep_audit.enumerate_mcp()
            components.extend(found)
            errors.extend(issues)
        if len(components) > 4096 or len(errors) > 4096:
            raise ValueError("dependency inventory exceeds audit bound")
        if getattr(ns, "offline", False):
            report = dep_audit.offline_report(components, errors=errors, skipped=skip)
            if getattr(ns, "json", False):
                ctx.dump(report.to_dict())
            else:
                ctx.out.write(dep_audit.render(report) + "\n")
            return EXIT_UNAVAILABLE
        pairs = len({(c.ecosystem, c.name, c.version) for c in components})
        ctx.err.write(
            f"requesting governed hub audit of {pairs} package name+version pairs; "
            f"if admitted, only those pairs go to {dep_audit.host_of(osv_url)}\n"
        )
        response = ctx.client().post("/api/security/dependencies/audit", {
            "components": [c.to_dict() for c in components], "errors": errors,
            "fail_on": fail_on, "ignore_vuln": getattr(ns, "ignore_vuln", []),
            "osv_url": osv_url, "skip": skip,
        })
        if not isinstance(response, dict) or not isinstance(response.get("report"), dict) \
                or not isinstance(response.get("human"), str):
            raise ValueError("invalid hub audit response")
        status = response["report"].get("status")
        if status not in {"clean", "findings", "unavailable"}:
            raise ValueError("invalid hub audit status")
        if getattr(ns, "json", False):
            ctx.dump(response["report"])
        else:
            ctx.out.write(response["human"] + "\n")
        return {"clean": EXIT_OK, "findings": EXIT_FAILED, "unavailable": EXIT_UNAVAILABLE}[status]
    except HubError as exc:
        ctx.err.write(f"governed security audit unavailable (HTTP {exc.status}): nothing is claimed\n")
        return EXIT_UNAVAILABLE
    except Exception as exc:  # not an answer: neither "clean" nor "findings"
        ctx.err.write(f"security audit did not complete ({type(exc).__name__}): nothing is claimed\n")
        return EXIT_UNAVAILABLE


def cmd_auth(ns: argparse.Namespace, ctx: Context) -> int:
    from .nous_auth import run
    return run(ns, ctx)


def cmd_secrets(ns: argparse.Namespace, ctx: Context) -> int:
    from .secrets import cmd_secrets as run
    return run(ns, ctx)


def cmd_kanban(ns: argparse.Namespace, ctx: Context) -> int:
    result = ctx.client().post("/api/kanban/command", {"argv": ns._kanban_argv})
    if not isinstance(result, dict) or type(result.get("exit_code")) is not int:
        ctx.err.write("Kanban returned an invalid command result\n")
        return EXIT_FAILED
    if result.get("output"):
        ctx.say(str(result["output"]))
    code = result["exit_code"]
    return code if 0 <= code <= 255 and (code != 0 or result.get("ok") is True) else EXIT_FAILED


def cmd_project(ns: argparse.Namespace, ctx: Context) -> int:
    result = ctx.client().post("/api/kanban/projects/command", {"argv": ns._project_argv})
    if not isinstance(result, dict) or type(result.get("exit_code")) is not int:
        ctx.err.write("Project returned an invalid command result\n")
        return EXIT_FAILED
    if result.get("output"):
        ctx.say(str(result["output"]))
    code = result["exit_code"]
    return code if 0 <= code <= 255 and (code != 0 or result.get("ok") is True) else EXIT_FAILED


def cmd_hooks(ns: argparse.Namespace, ctx: Context) -> int:
    """G17 — the owner's event hooks, over the same admin routes as the HUD's Hooks panel
    (agents/core/routers/hooks.py). ``add`` and ``enable`` only queue an approval card;
    ``disable`` and ``remove`` narrow what runs and apply at once."""
    client = ctx.client()
    action = {"ls": "list", "rm": "remove"}.get(ns.action, ns.action)
    if action in ("list", "doctor"):
        reply = client.get("/api/hooks")
        hooks = reply.get("hooks") if isinstance(reply, dict) else None
        if not isinstance(hooks, list):
            ctx.err.write("unexpected reply from the hub: no list of hooks in it\n")
            return EXIT_FAILED
        if getattr(ns, "json", False):
            ctx.dump(reply)
            return EXIT_OK
        status = reply.get("status") if isinstance(reply.get("status"), dict) else {}
        blockers = status.get("blockers") or []
        ctx.say("hooks can run here" if status.get("ready") else
                "hooks cannot run here: " + ", ".join(str(b) for b in blockers))
        if not hooks:
            ctx.say("no hooks")
        problems = 0
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            flags = [hook.get("status") or "?"]
            if hook.get("guard"):
                flags.append("guard")
            if hook.get("matcher"):
                flags.append(f"tools={hook['matcher']}")
            if hook.get("binding_current") is False:
                flags.append("FILES CHANGED since approval: it will not run "
                             f"(`nerva hooks enable {hook.get('id')}` asks to re-approve)")
                problems += 1
            last = hook.get("last_run") if isinstance(hook.get("last_run"), dict) else None
            if last:
                flags.append(f"last run {last.get('outcome')}")
            ctx.say(f"{hook.get('id')}  {hook.get('event')}  {' · '.join(flags)}")
            ctx.say(f"    {hook.get('command')}")
        if action == "doctor":
            return EXIT_FAILED if problems or blockers else EXIT_OK
        return EXIT_OK
    if action == "add":
        body: dict[str, Any] = {"event": ns.event, "argv": list(ns.argv), "guard": bool(ns.guard)}
        for key, value in (("matcher", ns.matcher), ("timeout_s", ns.timeout), ("name", ns.name),
                           ("replaces", ns.replaces)):
            if value is not None:
                body[key] = value
        reply = client.post("/api/hooks", body)
    elif action == "remove":
        reply = client.request("DELETE", f"/api/hooks/{quote(ns.hook_id, safe='')}")
    elif action == "test":
        body = {"tool": ns.tool}
        if ns.payload_file:
            try:
                with open(ns.payload_file, encoding="utf-8") as fh:
                    tool_input = json.load(fh)
            except (OSError, ValueError) as exc:
                ctx.err.write(f"could not read {ns.payload_file}: {exc}\n")
                return EXIT_USAGE
            if not isinstance(tool_input, dict):
                ctx.err.write("the payload file must hold a JSON object\n")
                return EXIT_USAGE
            body["tool_input"] = tool_input
        reply = client.post(f"/api/hooks/{quote(ns.hook_id, safe='')}/test", body)
    else:
        reply = client.post(f"/api/hooks/{quote(ns.hook_id, safe='')}/{action}")
    reply = reply if isinstance(reply, dict) else {}
    if getattr(ns, "json", False):
        ctx.dump(reply)
        return EXIT_OK
    if action in ("add", "enable"):
        ctx.say(f"approval card {reply.get('task_id')} queued for hook {(reply.get('hook') or {}).get('id')}; "
                "it runs only after you accept it (nerva approvals)")
    elif action == "test":
        run = reply.get("run") if isinstance(reply.get("run"), dict) else {}
        ctx.say(f"{run.get('outcome')}" + (" · would block" if run.get("blocked") else "")
                + (f" · {run.get('reason')}" if run.get("reason") else "")
                + (f" · {run.get('message')}" if run.get("message") else ""))
    elif action == "remove":
        ctx.say(f"removed {reply.get('removed')}")
    else:
        ctx.say(f"{ns.hook_id} switched off")
    return EXIT_OK


_VERBS: dict[str, Callable[[argparse.Namespace, Context], int]] = {
    "secrets": cmd_secrets,
    "kanban": cmd_kanban,
    "project": cmd_project,
    "auth": cmd_auth,
    "doctor": cmd_doctor,
    "prompt-size": cmd_prompt_size,
    "extensions": cmd_extensions,
    "status": cmd_status,
    "config": cmd_config,
    "approvals": cmd_approvals,
    "curator": cmd_curator,
    "checkpoints": cmd_checkpoints,
    "backup": cmd_backup,
    "kernel": cmd_kernel,
    "tools": cmd_tools,
    "inspect": cmd_inspect,
    "logs": cmd_logs,
    "skills": cmd_skills,
    "estop": cmd_estop,
    "company": cmd_company,
    "goal": cmd_goal,
    "pairing": cmd_pairing,
    "hooks": cmd_hooks,
    "memory": cmd_memory,
    "agents": cmd_agents,
    # argparse names the verb as typed, so each alias dispatches too.
    **dict.fromkeys(("journey", *_JOURNEY_ALIASES), cmd_journey),
    "provider": cmd_custom_provider,
    "mcp": cmd_mcp,
    "webhook": cmd_webhook,
    "jobs": cmd_jobs,
    "sessions": cmd_sessions,
    "todo": cmd_todo,
    "chat": cmd_chat,
    "send": cmd_send,
    "desktop": cmd_desktop,
    "support": cmd_support,
    "uninstall": cmd_uninstall,
    "security": cmd_security,
    "completion": cmd_completion,
}


def main(argv: list[str] | None = None, *, context: Context | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    if context is None:
        _apply_profile_early(raw)
    parser = build_parser()
    try:
        ns = parser.parse_args(raw)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    profile = getattr(ns, "profile", None)
    if profile is not None and context is None:
        # Offline verbs resolve the data root from this process's environment.
        os.environ.update({"JARVIS_PROFILE": profile})
    ctx = context or Context(environ=os.environ)
    if profile is not None and context is not None:
        ctx = replace(ctx, environ={**ctx.environ, "JARVIS_PROFILE": profile}, _client=None)
    verb_at = _verb_index(raw) + 1
    if ns.verb == "kanban":
        ns._kanban_argv = raw[verb_at:]
    elif ns.verb == "project":
        ns._project_argv = raw[verb_at:]
    try:
        return _VERBS[ns.verb](ns, ctx)
    except HubUnavailable as exc:
        ctx.err.write(
            f"{exc.reason}. Start the hub (python serve.py) or point NERVA_HUB_URL at it "
            f"(now {hub_url(ctx.environ)}).\n"
        )
        return EXIT_NO_HUB
    except HubError as exc:
        if exc.status in (401, 403):
            ctx.err.write(f"{exc.reason}. {_auth_hint(ctx.client(), exc.reason)}\n")
            return EXIT_AUTH
        ctx.err.write(f"{exc}\n")
        return EXIT_FAILED
    except argparse.ArgumentTypeError as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    except KeyboardInterrupt:
        # Ctrl-C already exited 130 — but through an uncaught traceback, which in a
        # one-shot pipeline is indistinguishable from a crash and can spill a partial
        # answer. One line, nothing on stdout, the same code a shell would report.
        ctx.err.write("interrupted\n")
        return EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in tests
    # Without this, `python -m agents.cli.nerva <verb>` imports the module, runs
    # nothing and exits 0 — silently, for every verb. There is no console script
    # in pyproject.toml either, so this is the only way the command tree H001
    # promises can actually be invoked outside a test that calls main() in-process.
    raise SystemExit(main())
