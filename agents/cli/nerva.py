"""`nerva` — the command tree. See the package docstring for why it exists.

Exit codes: 0 ok · 1 the verb failed (the hub said no, or a check is red) · 2 usage ·
3 no hub is reachable · 4 a credential is required.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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

_SECRET_KINDS = frozenset({"secret", "password"})
_SECRET_HINTS = ("token", "secret", "password", "api_key", "apikey", "private")
_TIER_NAMES = {0: "READ_ONLY", 1: "REVERSIBLE", 2: "EXTERNAL", 3: "IRREVERSIBLE_OR_MONEY"}


@dataclass
class Context:
    environ: Mapping[str, str]
    out: Any = field(default_factory=lambda: sys.stdout)
    err: Any = field(default_factory=lambda: sys.stderr)
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
    jobs_create.add_argument("--json", action="store_true")
    for name, help_text in (
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

    sessions = verbs.add_parser("sessions", help="recent conversation sessions")
    sessions.add_argument("--json", action="store_true")

    chat = verbs.add_parser("chat", help="one scripted turn: send a message, print the reply")
    chat.add_argument("message")
    chat.add_argument("--agent", help="address one agent instead of the router")
    chat.add_argument("--json", action="store_true")

    completion = verbs.add_parser("completion", help="print a shell completion script")
    completion.add_argument("shell", choices=("bash", "zsh"))
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
    if ns.json:
        ctx.dump({"status": status, "estop": estop})
        return EXIT_OK
    agents = status.get("agents") or []
    ctx.say(f"nerva {status.get('version', '?')} — {client.base_url}")
    ctx.say(f"  backend:     {status.get('llm_backend', 'none')}")
    ctx.say(
        f"  model:       {status.get('loaded_model') or status.get('configured_model') or '—'}"
        f" ({status.get('model_state', 'unknown')})"
    )
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
    return str(row.get("kind", "")) in _SECRET_KINDS or any(hint in key for hint in _SECRET_HINTS)


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
                ctx.say(f"{cat}.{row['key']} = {shown}  ({row.get('kind', '?')})")
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


def cmd_jobs(ns: argparse.Namespace, ctx: Context) -> int:
    client = ctx.client()
    if ns.action == "list":
        reply = client.get("/api/jobs") or {}
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        scheduler = reply.get("scheduler") or {}
        ctx.say(
            f"scheduler {'alive' if scheduler.get('alive') else 'NOT RUNNING'} — "
            f"{scheduler.get('runnable', 0)} runnable, {scheduler.get('paused', 0)} paused"
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
            if ns.name:
                body["name"] = ns.name
            if ns.when:
                body["schedule_text"] = ns.when
        except ValueError as exc:
            ctx.err.write(f"{exc}\n")
            return EXIT_USAGE
        reply = client.post("/api/jobs", body) or {}
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        job = reply.get("job") or {}
        ctx.say(f"armed {job.get('id')}  {job.get('schedule_text')} ({job.get('cron')})  {job.get('name')}")
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
    if ns.action == "delete":
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
        run = reply.get("run") or {}
        ctx.say(f"{run.get('status')}: {run.get('summary', '')}")
        return EXIT_OK if run.get("status") == "ok" else EXIT_FAILED
    state = "paused" if job.get("paused_reason") else "runnable"
    ctx.say(f"{ns.job_id} is {state}")
    return EXIT_OK


def cmd_sessions(ns: argparse.Namespace, ctx: Context) -> int:
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


def cmd_chat(ns: argparse.Namespace, ctx: Context) -> int:
    body: dict[str, Any] = {"message": ns.message}
    if ns.agent:
        body["agent"] = ns.agent
    reply = ctx.client().post("/chat", body)
    if ns.json:
        ctx.dump(reply)
        return EXIT_OK
    ctx.say(str((reply or {}).get("reply", "")))
    return EXIT_OK


def completion_script(shell: str, parser: argparse.ArgumentParser | None = None) -> str:
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


_VERBS: dict[str, Callable[[argparse.Namespace, Context], int]] = {
    "doctor": cmd_doctor,
    "status": cmd_status,
    "config": cmd_config,
    "approvals": cmd_approvals,
    "kernel": cmd_kernel,
    "logs": cmd_logs,
    "estop": cmd_estop,
    "jobs": cmd_jobs,
    "sessions": cmd_sessions,
    "chat": cmd_chat,
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
