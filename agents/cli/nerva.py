"""`nerva` — the command tree. See the package docstring for why it exists.

Exit codes: 0 ok · 1 the verb failed (the hub said no, or a check is red) · 2 usage ·
3 no hub is reachable · 4 a credential is required · 5 the check could not run at all ·
130 interrupted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import HubClient, HubError, HubUnavailable, hub_url

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
_PLAIN_KINDS = frozenset({"number", "toggle", "select", "slider", "model-select"})
_TIER_NAMES = {0: "READ_ONLY", 1: "REVERSIBLE", 2: "EXTERNAL", 3: "IRREVERSIBLE_OR_MONEY"}


@dataclass
class Context:
    environ: Mapping[str, str]
    out: Any = field(default_factory=lambda: sys.stdout)
    err: Any = field(default_factory=lambda: sys.stderr)
    inp: Any = field(default_factory=lambda: sys.stdin)
    client_factory: Callable[[Mapping[str, str]], HubClient] = HubClient.from_env
    _client: HubClient | None = None

    def client(self) -> HubClient:
        if self._client is None:
            self._client = self.client_factory(self.environ)
        return self._client

    def say(self, text: str = "") -> None:
        self.out.write(text + "\n")

    def dump(self, payload: Any) -> None:
        self.out.write(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")


# ── parser ────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nerva",
        description="One command for the whole product. Online verbs talk to the running hub "
        "over the same routes the HUD uses; offline verbs read the same data root.",
    )
    verbs = parser.add_subparsers(dest="verb", required=True, metavar="verb")

    doctor = verbs.add_parser("doctor", help="install check-up, one named reason per check (offline)")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--smoke", action="store_true", help="also run the install smoke (~30 s)")

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
    config_get = config_verbs.add_parser("get", help="print one setting: category.key")
    config_get.add_argument("name")
    config_get.add_argument("--reveal", action="store_true")
    config_set = config_verbs.add_parser("set", help="change one setting: category.key value")
    config_set.add_argument("name")
    config_set.add_argument("value")
    config_verbs.add_parser("check", help="validate every stored value against its declared schema")

    approvals = verbs.add_parser("approvals", help="the approval queue (admin)")
    approvals_verbs = approvals.add_subparsers(dest="action", required=True, metavar="action")
    approvals_list = approvals_verbs.add_parser("list", help="pending decisions")
    approvals_list.add_argument("--json", action="store_true")
    for decision in ("accept", "reject", "defer", "edit"):
        decide = approvals_verbs.add_parser(decision, help=f"{decision} one pending task")
        decide.add_argument("task_id", type=int)
        decide.add_argument("--payload", help="JSON object attached to the decision")
        decide.add_argument("--json", action="store_true")

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

    logs = verbs.add_parser("logs", help="the last lines of the hub log (offline)")
    logs.add_argument("-n", "--lines", type=int, default=50)

    estop = verbs.add_parser("estop", help="the global emergency stop")
    estop_verbs = estop.add_subparsers(dest="action", required=True, metavar="action")
    estop_verbs.add_parser("status", help="is it engaged, since when, why")
    engage = estop_verbs.add_parser("engage", help="pause new autonomous work (admin)")
    engage.add_argument("--reason", default="")
    estop_verbs.add_parser("resume", help="lift the emergency stop (admin)")

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
    jobs_create.add_argument("--workdir", help="script-only cwd; requires complete --options with script and no_agent true")
    jobs_create.add_argument("--media-id", action="append", help="opaque artifact ID for an explicit reminder action; repeat up to 8 times")
    jobs_create.add_argument("--options", help='JSON options: repeat, deliver ([] disables delivery); ask jobs accept model/provider pins (configured route only; deterministic compression, no embedding recall)')
    jobs_edit = jobs_verbs.add_parser("edit", help="change an existing job's name, schedule or action")
    jobs_edit.add_argument("job_id")
    jobs_edit.add_argument("--name")
    jobs_edit.add_argument("--when", help="plain words ('every weekday at 7') or a five-field cron")
    jobs_edit.add_argument("--action", dest="action_json", help='JSON, e.g. {"type":"remind","message":"stand up"}')
    jobs_edit.add_argument("--json", action="store_true")
    jobs_edit.add_argument("--toolsets", help="model ask: default, none, or comma-separated installed IDs from jobs doctor; requires complete --options")
    jobs_edit.add_argument("--workdir", help="script-only cwd; requires complete --options; empty clears the field")
    jobs_edit.add_argument("--media-id", action="append", help="replace reminder attachments; requires --action and explicitly reauthorizes content/owner")
    jobs_edit.add_argument("--options", help="replace advanced options as JSON; model/provider pins use deterministic compression and omit embedding recall")
    for verb in ("doctor", "incidents", "tick"):
        sub = jobs_verbs.add_parser(verb)
        sub.add_argument("--json", action="store_true")
    notepad = jobs_verbs.add_parser("notepad", help="read or replace a job's bounded notes")
    notepad.add_argument("job_id")
    notepad.add_argument("--text", help="replacement text; an empty string clears notes")
    notepad.add_argument("--json", action="store_true")
    for name, help_text in (
        ("status", "job configuration and recent runs"),
        ("remove", "remove a job and its history"),
        ("pause", "stop a job from firing"),
        ("resume", "let a paused job fire again"),
        ("run", "fire a job now, even if paused"),
        ("delete", "remove a job and its history"),
        ("runs", "the last attempts of a job"),
    ):
        sub = jobs_verbs.add_parser(name, help=help_text)
        sub.add_argument("job_id")
        sub.add_argument("--json", action="store_true")
        if name == "pause":
            sub.add_argument("--reason", default="")
        if name == "status":
            sub.add_argument("--request", help="durable manual-run receipt id")

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

    chat = verbs.add_parser(
        "chat",
        help="one scripted turn: send a message, print the reply (scripts, cron, CI)",
        description="One turn in, one answer out. The message is the MESSAGE argument, else "
                    "--file PATH (- reads stdin), else whatever is piped on stdin; a terminal is "
                    "never read. With -z the answer is the ONLY thing on stdout and every "
                    "diagnostic goes to stderr, so the command composes in a pipeline. A turn that "
                    "did not complete — one that queued an approval, was refused, or came back "
                    "empty — prints nothing on stdout and exits non-zero. Exit 0 answered · 1 the "
                    "turn did not complete · 2 usage · 3 no hub · 4 not authorised · 130 "
                    "interrupted.",
        epilog="examples:\n"
               "  nerva chat -z \"what is on my calendar?\"\n"
               "  echo \"summarise this\" | nerva chat -z --usage-file spend.json\n"
               "  nerva chat -z -f prompt.txt --agent athena\n"
               "\n"
               "This verb never auto-approves. If the turn queues an action for approval it\n"
               "stays queued: stdout is empty, the exit code is 1, and stderr names what to\n"
               "decide with `nerva approvals`.",
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
    chat.add_argument("--session", help="explicit existing conversation session")
    chat.add_argument("--json", action="store_true")

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

    security = verbs.add_parser(
        "security", help="checks you can run on this box: known vulnerabilities in what is installed")
    security_verbs = security.add_subparsers(dest="action", required=True, metavar="action")
    security_audit = security_verbs.add_parser(
        "audit",
        help="known vulnerabilities in this interpreter's packages and in declared extension pins, "
             "from OSV.dev — exit 0 clean · 1 findings at/above --fail-on · 5 database not "
             "consulted (nothing is claimed)",
        description="Checks what is installed in THIS interpreter, plus the exact Python pins of any "
                    "--extension descriptor, against OSV.dev. It does NOT scan: MCP servers (owner-"
                    "configured stdio commands are listed as not audited), extensions the hub has "
                    "acquired but you did not name, system packages, or anything outside this "
                    "interpreter. Only package name+version pairs leave the machine. Exit 0 clean · "
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
            return {"ready": None, "reason": "needs_token"}
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


def _runnable_line(verdict: Mapping[str, Any]) -> str:
    reason = verdict.get("reason")
    if reason == "needs_token":
        return "(needs JARVIS_USER_TOKEN or JARVIS_ADMIN_TOKEN to read)"
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


def cmd_status(ns: argparse.Namespace, ctx: Context) -> int:
    client = ctx.client()
    status = client.get("/status")
    if not isinstance(status, dict):
        raise HubError(0, "malformed /status reply")
    estop = None
    try:
        estop = client.get("/api/ops/estop")
    except HubError as exc:
        if exc.status not in (401, 403):
            raise
    runnable = _runnable(client)
    if ns.json:
        ctx.dump({"status": status, "estop": estop, "runnable": runnable})
        return EXIT_OK
    agents = status.get("agents") or []
    ctx.say(f"nerva {status.get('version', '?')} — {client.base_url}")
    ctx.say(f"  backend:     {status.get('llm_backend', 'none')}")
    state = str(status.get("model_state", "unknown"))
    ctx.say(
        f"  model:       {status.get('loaded_model') or status.get('configured_model') or '—'}"
        f" ({_MODEL_STATE_WORDS.get(state, state)})"
    )
    ctx.say(f"  runnable:    {_runnable_line(runnable)}")
    ctx.say(f"  agents:      {status.get('agents_online', 0)}/{status.get('agents_total', len(agents))} busy")
    channels = status.get("channels") or []
    names = ", ".join(
        str(c.get("id") or c.get("channel") or c) if isinstance(c, dict) else str(c) for c in channels
    )
    ctx.say(f"  channels:    {names or '—'}")
    if isinstance(estop, dict):
        if estop.get("engaged"):
            state = estop.get("state") or {}
            ctx.say(f"  e-stop:      ENGAGED since {state.get('engaged_at') or '?'} — {state.get('reason') or 'no reason given'}")
        else:
            ctx.say("  e-stop:      not engaged")
    else:
        ctx.say("  e-stop:      (needs JARVIS_USER_TOKEN or JARVIS_ADMIN_TOKEN to read)")
    return EXIT_OK


def _settings():
    from agents.core import settings_db

    return settings_db


def _is_secret(row: Mapping[str, Any]) -> bool:
    key = str(row.get("key", "")).lower()
    kind = str(row.get("kind", ""))
    if kind in _SECRET_KINDS:
        return True
    return kind not in _PLAIN_KINDS and any(hint in key for hint in _SECRET_HINTS)


def _shown(row: Mapping[str, Any], *, reveal: bool) -> Any:
    if _is_secret(row) and not reveal and row.get("value") not in (None, "", [], {}):
        return "••••••"
    return row.get("value")


def _split_name(name: str) -> tuple[str, str]:
    category, sep, key = name.partition(".")
    if not sep or not category or not key:
        raise argparse.ArgumentTypeError(f"setting names are category.key, got {name!r}")
    return category, key


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
                ctx.say(f"{cat}.{row['key']} = {shown}  ({row.get('kind', '?')}{source}{overlay})")
        return EXIT_OK
    if ns.action == "get":
        category, key = _split_name(ns.name)
        row = next((r for r in settings.get_category(category) if r["key"] == key), None)
        if row is None:
            ctx.err.write(f"no setting {ns.name}\n")
            return EXIT_FAILED
        ctx.say(json.dumps(_shown(row, reveal=ns.reveal), ensure_ascii=False))
        return EXIT_OK
    if ns.action == "set":
        category, key = _split_name(ns.name)
        spec = settings._SPEC.get((category, key))
        if spec is None:
            ctx.err.write(f"{ns.name} is not a declared setting (see `nerva config list`)\n")
            return EXIT_FAILED
        try:
            value = _coerce(ns.value, str(spec.get("kind", "text")))
        except ValueError as exc:
            ctx.err.write(f"{ns.name}: {exc}\n")
            return EXIT_FAILED
        errors = settings.validate_category(category, {key: value})
        if errors:
            ctx.err.write(f"{ns.name}: rejected — {'; '.join(errors)}\n")
            return EXIT_FAILED
        settings.put_category(category, {key: value})
        ctx.say(f"{ns.name} = {json.dumps(value)}  (a running hub picks it up within 30 s)")
        return EXIT_OK
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


def cmd_approvals(ns: argparse.Namespace, ctx: Context) -> int:
    client = ctx.client()
    if ns.action == "list":
        reply = client.get("/autonomy/approvals")
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        pending = (reply or {}).get("pending") or []
        if not pending:
            ctx.say("no pending approvals")
            return EXIT_OK
        for task in pending:
            flag = "reversible" if task.get("reversible") else "IRREVERSIBLE"
            ctx.say(
                f"#{task.get('id', '?')}  tier {task.get('risk_tier', '?')}  {flag:12s}  "
                f"{task.get('kind', '?')}  — {task.get('title', '')}"
            )
        ctx.say(f"{len(pending)} pending — `nerva approvals accept|reject|defer <id>`")
        return EXIT_OK
    try:
        payload = _payload(ns.payload)
    except ValueError as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    body: dict[str, Any] = {"action": ns.action}
    if payload:
        body["payload"] = payload
    reply = client.post(f"/autonomy/tasks/{ns.task_id}/decision", body)
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    task = (reply or {}).get("task") or {}
    ctx.say(f"#{ns.task_id} {ns.action}ed → {task.get('status', 'done')}")
    return EXIT_OK


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
    mode = str(_settings().get_value("autonomy", "mode", "auto") or "auto")
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


def cmd_logs(ns: argparse.Namespace, ctx: Context) -> int:
    path = log_path(ctx.environ)
    if not path.exists():
        ctx.err.write(
            f"no log file at {path} — file logging is off unless system.log_to_file is on "
            "(`nerva config set system.log_to_file on`) or JARVIS_LOG_FILE is set\n"
        )
        return EXIT_FAILED
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-max(0, ns.lines):]:
        ctx.say(line)
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
    return value


def cmd_jobs(ns: argparse.Namespace, ctx: Context) -> int:
    client = ctx.client()
    if ns.action in ("doctor", "incidents", "tick", "status", "notepad"):
        if ns.action == "tick":
            reply = client.post("/api/jobs/tick", {})
        elif ns.action == "notepad" and ns.text is not None:
            reply = client.request("PUT", f"/api/jobs/{ns.job_id}/notepad", {"text":ns.text})
        elif ns.action == "status" and ns.request:
            reply = client.get(f"/api/jobs/{ns.job_id}/requests/{ns.request}")
        elif ns.action in ("status", "notepad"):
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
            if ns.options is not None or ns.workdir is not None or ns.toolsets is not None:
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
        reply = client.post("/api/jobs", body) or {}
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
        if ns.options is not None or ns.workdir is not None or ns.toolsets is not None:
            try:
                body["options"] = _job_cli_options(ns)
            except ValueError as exc:
                ctx.err.write(f"{exc}\n")
                return EXIT_USAGE
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
        reply = client.request("PATCH", f"/api/jobs/{ns.job_id}", body) or {}
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
        reply = client.get(f"/api/jobs/{ns.job_id}/runs") or {}
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        runs = reply.get("runs") or []
        if not runs:
            ctx.say("no runs yet")
        for run in runs:
            ctx.say(f"{run.get('started_at')}  {run.get('status'):7s} {run.get('summary', '')[:100]}")
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
    reply = ctx.client().get("/sessions")
    sessions = (reply or {}).get("sessions") or []
    if ns.json:
        ctx.dump(sessions)
        return EXIT_OK
    if not sessions:
        ctx.say("no sessions recorded")
        return EXIT_OK
    for row in sessions:
        sid = row.get("session_id") or row.get("id") or "?"
        started = row.get("started_at") or ""
        ctx.say(f"{sid}  {started}")
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
    "I stopped this turn because its context compaction could not be safely committed. Please retry.":
        "the turn was refused: its context could not be safely compacted",
    # agents.core.session_continuation.CONTINUATION_REFUSED_REPLY
    "I stopped this turn because this continued conversation could not be safely restored.":
        "the turn was refused: the continued conversation could not be restored",
    # agents.core.llm.base.LOCAL_SELECTION_UNAVAILABLE_REPLY
    "\u26a0\ufe0f No local language model is available. Start LM Studio or Ollama and try again.":
        "no local model is available",
    # agents.core.llm.base.THINKING_EXHAUSTED_REPLY
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
    where `jarvis.synthesize` re-writes the text through a model — nothing in a reply
    string can survive that, which is why the hub reporting `pending_approvals` is the
    real fix and why this row stays partial until that lands. The trade is deliberate:
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


def _write_answer(ctx: Context, text: str) -> None:
    """Put the answer on stdout without letting encoding turn a 0 into a crash.

    stdout's encoding belongs to the caller — a pipe under ``LC_ALL=C`` is ascii — and
    a model may answer in any script. A raw write can therefore raise UnicodeEncodeError
    *after* the turn succeeded, which a caller reads as "the turn did not complete" for
    a turn that did, and which skips the receipt that was promised on every path.
    """
    try:
        ctx.out.write(text + "\n")
        return
    except UnicodeEncodeError:
        pass
    encoding = getattr(ctx.out, "encoding", None) or "utf-8"
    ctx.out.write(text.encode(encoding, "backslashreplace").decode(encoding, "replace") + "\n")


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

    Never 0 for "unknown": a spend report that prints $0.00 because nobody measured is
    the exact lie this file exists to avoid. `cost_basis` says which it is, and today it
    is always "unavailable" — see the H002 row's remainder for why the hub cannot yet
    attribute one turn's spend.
    """
    report: dict[str, Any] = {
        "schema": "nerva.chat.usage.v1",
        "status": "failed", "completed": False, "exit_code": EXIT_FAILED,
        "started_at": None, "finished_at": None, "duration_ms": None,
        "session_id": None, "agent": None, "model": None, "provider": None,
        "api_calls": None, "input_tokens": None, "output_tokens": None,
        "estimated_cost_usd": None, "cost_basis": "unavailable",
        "pending_approvals": [], "reason": None,
    }
    report.update(fields)
    return report


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

    def finish(code: int, *, status: str, reason: str | None = None,
               pending: list[Any] | None = None, completed: bool | None = None) -> int:
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
                session_id=getattr(ns, "session", None) or None,
                agent=getattr(ns, "agent", None) or None,
                pending_approvals=list(pending or []), reason=reason,
            ), ctx)
        return code

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

    body: dict[str, Any] = {"message": message}
    if ns.agent:
        body["agent"] = ns.agent
    if getattr(ns, "reasoning", None) is not None:
        body["reasoning"] = ns.reasoning
    if getattr(ns, "session", None):
        body["session_id"] = ns.session
    try:
        reply = ctx.client().post("/chat", body)
    except KeyboardInterrupt:
        # The receipt is promised on every path, and an interrupt is the path a cron
        # wrapper most needs one for — it is what a timeout kill looks like from in
        # here. main() still prints the one line and returns 130; this only makes sure
        # the run leaves a record behind saying so.
        finish(EXIT_INTERRUPTED, status="interrupted", reason="interrupted")
        raise
    except HubUnavailable:
        finish(EXIT_NO_HUB, status="no_hub", reason="no hub is reachable")
        raise
    except HubError as exc:
        status = "unauthorised" if exc.status in (401, 403) else "failed"
        finish(EXIT_AUTH if exc.status in (401, 403) else EXIT_FAILED,
               status=status, reason=str(exc))
        raise

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
    refusal = _not_an_answer(answer)
    queued = bool(pending or pending_unreadable or (refusal and "approval" in refusal))
    incomplete = bool(refusal or queued or not answer.strip())

    if not oneshot:
        # The interactive shape is unchanged: print whatever came back, exit 0. Scripts
        # that need the verdict use -z; changing this would break every existing caller.
        # The receipt is new surface, so it is allowed to say what the exit code cannot.
        if ns.json:
            ctx.dump(reply)
        else:
            ctx.say(str(raw))
        status = "queued_for_approval" if queued else "refused" if incomplete else "completed"
        return finish(EXIT_OK, status=status, reason=refusal, pending=pending,
                      completed=not incomplete)

    if incomplete:
        reason = refusal or ("the turn queued an action for approval and was not executed"
                             if queued else "the hub returned an empty answer")
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


#: What one send carries, subject included — the outbound seam's own bound.
SEND_MAX_CHARS = 4_000
#: What one chat turn carries: `ChatRequest.message` is `max_length=4096` (agents/web.py).
#: Checked here so an over-long prompt is a usage error before the request, not an
#: HTTP 422 that a script would read as "the turn failed".
CHAT_MAX_CHARS = 4_096
_NO_BODY = "no message provided. Pass text as an argument, use --file PATH, or pipe it on stdin"
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _plain(text: Any, width: int = 200) -> str:
    """A string from the hub or the shell, safe to put on a terminal: no control characters."""
    out = _CONTROL_CHARS.sub(" ", "" if text is None else str(text))
    return out if len(out) <= width else out[: width - 1] + "…"


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
                    return None, (f"{_plain(ns.file, 120)} is a terminal, and {verb} never "
                                  "reads one; pipe the body or point --file at a file")
                return _read_body(handle, _plain(ns.file, 120), verb=verb, bound=bound)
        except OSError as exc:
            return None, f"cannot read {_plain(ns.file, 120)}: {exc.strerror or type(exc).__name__}"
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


def _fish_completion(parser: argparse.ArgumentParser) -> str:
    """Complete command paths only; do not execute the CLI while completing."""
    def quote(value: str) -> str:
        # fish single quotes recognize only escaped backslashes and single quotes.
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    lines = [
        "# nerva fish completion — generated from the live parser tree",
        "# Current session: nerva completion fish | source",
        "function __nerva_complete_path",
        "    set -l words (commandline -opc)",
        "    set -e words[1]",
        "    test (count $words) -eq (count $argv); or return 1",
        "    for word in $argv",
        '        test "$words[1]" = "$word"; or return 1',
        "        set -e words[1]",
        "    end",
        "    return 0",
        "end",
        "complete -c nerva -f",
    ]

    def walk(node: argparse.ArgumentParser, path: tuple[str, ...]) -> None:
        condition = "__nerva_complete_path" + "".join(" " + quote(part) for part in path)
        for action in node._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for name, child in sorted(action.choices.items()):
                # -a and -n are evaluated by fish later; quote metadata at both
                # the definition and completion stages, never as shell code.
                lines.append(f"complete -c nerva -n {quote(condition)} -a {quote(quote(name))}")
                walk(child, (*path, name))

    walk(parser, ())
    return "\n".join(lines) + "\n"


def completion_script(shell: str, parser: argparse.ArgumentParser | None = None) -> str:
    if shell not in {"bash", "zsh", "fish"}:
        raise ValueError(f"unsupported completion shell: {shell!r}")
    if shell == "fish":
        return _fish_completion(parser or build_parser())
    tree = command_tree(parser)
    verbs = " ".join(sorted(tree))
    if shell == "bash":
        cases = "\n".join(
            f'        {verb}) COMPREPLY=( $(compgen -W "{" ".join(subs)}" -- "$cur") ) ;;'
            for verb, subs in sorted(tree.items())
            if subs
        )
        return (
            "# nerva bash completion — generated from the parser tree; eval \"$(nerva completion bash)\"\n"
            "_nerva() {\n"
            '    local cur="${COMP_WORDS[COMP_CWORD]}"\n'
            "    if [ \"$COMP_CWORD\" -eq 1 ]; then\n"
            f'        COMPREPLY=( $(compgen -W "{verbs}" -- "$cur") ); return\n'
            "    fi\n"
            '    case "${COMP_WORDS[1]}" in\n'
            f"{cases}\n"
            "        *) COMPREPLY=() ;;\n"
            "    esac\n"
            "}\n"
            "complete -F _nerva nerva\n"
        )
    lines = "\n".join(
        f"        {verb}) _values 'action' {' '.join(subs)} ;;"
        for verb, subs in sorted(tree.items())
        if subs
    )
    return (
        "#compdef nerva\n"
        "# nerva zsh completion — generated from the parser tree\n"
        "_nerva() {\n"
        "    if (( CURRENT == 2 )); then\n"
        f"        _values 'verb' {verbs}; return\n"
        "    fi\n"
        "    case \"${words[2]}\" in\n"
        f"{lines}\n"
        "    esac\n"
        "}\n"
        "_nerva \"$@\"\n"
    )


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


def cmd_security(ns: argparse.Namespace, ctx: Context) -> int:
    """H022 — what is installed here, checked against a vulnerability database.

    Three surfaces, named in the output so a reader knows what was and was not
    looked at: the distributions in *this* interpreter, the exact Python pins any
    extension descriptor on the command line declares, and MCP — on Nerva a set of
    owner-configured stdio commands this verb does not resolve to package versions,
    so it is listed as *not audited* with that reason rather than silently omitted.

    Two things this verb will not do. It will not compute a severity OSV does not
    state (an unrated advisory fails every threshold), and it will not call a run
    "clean" when the database could not be reached: that is EXIT_UNAVAILABLE, and
    the report says nothing is claimed. The same exit covers the audit itself
    failing before it has an answer — a traceback's exit 1 would read as "findings".
    Only package name+version pairs leave the machine, and the verb says so before
    the first request.
    """
    from agents.core.security import dep_audit

    try:
        client = None if ns.offline else dep_audit.default_client(ns.osv_url)
    except ValueError as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    try:
        components, errors = dep_audit.enumerate_installed()
        extension_components, extension_errors = dep_audit.enumerate_extensions(ns.extension)
        components, errors = components + extension_components, errors + extension_errors
        if client is None:
            report = dep_audit.offline_report(components, errors=errors)
        else:
            pairs = len({(c.name, c.version) for c in components})
            ctx.err.write(
                f"sending {pairs} package name+version pairs to {dep_audit.host_of(ns.osv_url)}; "
                "nothing else leaves this machine\n"
            )
            report = dep_audit.audit(
                components, client, fail_on=ns.fail_on, ignore=ns.ignore_vuln,
                errors=errors, database=ns.osv_url,
            )
    except Exception as exc:  # not an answer: neither "clean" nor "findings"
        ctx.err.write(f"security audit did not complete ({type(exc).__name__}): nothing is claimed\n")
        return EXIT_UNAVAILABLE
    if ns.json:
        ctx.dump(report.to_dict())
    else:
        ctx.out.write(dep_audit.render(report) + "\n")
    return {"clean": EXIT_OK, "findings": EXIT_FAILED}.get(report.status, EXIT_UNAVAILABLE)


_VERBS: dict[str, Callable[[argparse.Namespace, Context], int]] = {
    "doctor": cmd_doctor,
    "prompt-size": cmd_prompt_size,
    "extensions": cmd_extensions,
    "status": cmd_status,
    "config": cmd_config,
    "approvals": cmd_approvals,
    "kernel": cmd_kernel,
    "tools": cmd_tools,
    "logs": cmd_logs,
    "estop": cmd_estop,
    "jobs": cmd_jobs,
    "sessions": cmd_sessions,
    "todo": cmd_todo,
    "chat": cmd_chat,
    "send": cmd_send,
    "desktop": cmd_desktop,
    "security": cmd_security,
    "completion": cmd_completion,
}


def main(argv: list[str] | None = None, *, context: Context | None = None) -> int:
    parser = build_parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    ctx = context or Context(environ=os.environ)
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
            hub = HubClient.from_env(ctx.environ)
            if hub.admin_token and not hub._sends_admin_token():
                # The token is set and was kept back on purpose (review-H273f m2): say so,
                # rather than ask the owner to set what they already have.
                ctx.err.write(
                    f"{exc.reason}. JARVIS_ADMIN_TOKEN is set but was withheld from {hub.base_url}: "
                    "plain http to another machine would carry it in clear text. Point NERVA_HUB_URL "
                    "at an https address, or run the verb on the hub itself.\n"
                )
                return EXIT_AUTH
            ctx.err.write(
                f"{exc.reason}. Set JARVIS_ADMIN_TOKEN (mint one on the box: "
                "python -m agents.core.security.token_store issue admin) or JARVIS_USER_TOKEN.\n"
            )
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
