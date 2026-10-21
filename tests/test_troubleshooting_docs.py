"""H631 — diagnose a broken install from a symptom, without a screen-share.

``docs/TROUBLESHOOTING.md`` is the user-facing triage guide: a fixed recovery sequence, a
symptom -> cause -> fix table, the "my agent feels dumber" checklist, the named failure
modes of Ollama and LM Studio, and the scheduled-jobs tree. A guide that names a command
or a setting the code does not have sends the reader nowhere, so every command, setting,
environment variable and route the guide names is checked against the code here, and
every reason the doctor, the route check and ``nerva jobs doctor`` can print is named in
it. Hermetic: reads files, parses the CLI, imports no server.
"""

import re
import shlex
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents"))

from scripts import bootstrap, doctor  # noqa: E402

GUIDE = REPO / "docs" / "TROUBLESHOOTING.md"
SPAN = re.compile(r"`([^`\n]+)`")
ROUTE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) (/[^\s?#]*)$")
ENV = re.compile(r"^((?:JARVIS|NERVA)_[A-Z0-9_]+)(?:=\S*)?$")
SETTING = re.compile(r"^([a-z_]+)\.([a-z0-9_]+)$")


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def _section(title: str) -> str:
    """The body of one ``## `` section (up to the next ``## ``)."""
    text = _guide()
    start = text.index(f"\n## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


def _spans(text: str | None = None) -> list[str]:
    return [m.group(1).strip() for m in SPAN.finditer(_guide() if text is None else text)]


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^a-z0-9 _-]", "", heading.strip().lower()).replace(" ", "-")


def _anchors() -> set[str]:
    return {_slug(m.group(1)) for m in re.finditer(r"^#{2,4} (.+)$", _guide(), re.M)}


def _settings() -> dict[str, set[str]]:
    from agents.core.settings_db import DEFAULTS

    table: dict[str, set[str]] = {}
    for row in DEFAULTS:
        table.setdefault(row["category"], set()).add(row["key"])
    return table


def _routes() -> set[tuple[str, str]]:
    found = set()
    decorator = re.compile(r"@(?:router|app)\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"']")
    for path in (REPO / "agents").rglob("*.py"):
        for m in decorator.finditer(path.read_text(encoding="utf-8", errors="replace")):
            found.add((m.group(1).upper(), m.group(2)))
    return found


# ── the guide exists, is linked, and has the four parts ─────────────
def test_guide_has_the_recovery_sequence_table_checklist_servers_and_jobs_tree():
    text = _guide()
    for title in ("Recovery sequence", "Symptom, cause, fix", '"My agent feels dumber"',
                  "Local model servers", "Scheduled jobs"):
        assert f"\n## {title}\n" in text, f"missing section: {title}"
    for sub in ("### Ollama", "### LM Studio", "### Timing", "### Delivery", "### Permissions",
                "### Skill loading"):
        assert f"\n{sub}\n" in text, f"missing subsection: {sub}"


def test_recovery_sequence_and_checklist_are_fixed_ordered_lists():
    for title, at_least in (("Recovery sequence", 6), ('"My agent feels dumber"', 8)):
        steps = [int(n) for n in re.findall(r"^(\d+)\. ", _section(title), re.M)]
        assert len(steps) >= at_least, title
        assert steps == list(range(1, len(steps) + 1)), f"{title}: steps out of order {steps}"


def test_symptom_table_has_symptom_cause_fix_columns_and_rows():
    body = _section("Symptom, cause, fix")
    header = re.search(r"^\| *Symptom *\| *Cause *\| *Fix *\|$", body, re.M)
    assert header, "the table's header is | Symptom | Cause | Fix |"
    rows = [line for line in body.splitlines() if line.startswith("|") and "---" not in line]
    assert len(rows) - 1 >= 12
    assert all(line.count("|") == 4 for line in rows), "every row has exactly three cells"


def test_guide_is_linked_from_faq_and_runbook():
    assert "TROUBLESHOOTING.md" in (REPO / "docs" / "FAQ.md").read_text(encoding="utf-8")
    assert "TROUBLESHOOTING.md" in (REPO / "docs" / "MAINTENANCE_RUNBOOK.md").read_text(encoding="utf-8")


# ── everything it names exists ──────────────────────────────────────
def test_every_nerva_command_parses_with_the_real_cli():
    from agents.cli.nerva import build_parser

    commands = [s for s in _spans() if s.startswith("nerva ")]
    assert len(commands) >= 15
    settings = _settings()
    for command in commands:
        argv = shlex.split(command)[1:]
        try:
            ns = build_parser().parse_args(argv)
        except SystemExit:
            pytest.fail(f"the guide names a command the CLI refuses: {command}")
        if ns.verb == "config" and ns.action in ("get", "set"):
            category, _, key = ns.name.partition(".")
            assert key in settings.get(category, set()), f"{command}: no setting {ns.name}"


def test_every_python_script_and_flag_exists():
    commands = [s for s in _spans() if s.startswith("python ")]
    assert commands
    for command in commands:
        argv = shlex.split(command)
        script = REPO / argv[1]
        assert script.is_file(), f"{command}: no {argv[1]}"
        source = script.read_text(encoding="utf-8")
        for flag in (a for a in argv[2:] if a.startswith("--")):
            assert f'"{flag}"' in source, f"{command}: {argv[1]} has no {flag}"


def test_every_setting_named_is_a_real_setting():
    settings = _settings()
    named = [m for m in (SETTING.match(s) for s in _spans()) if m and m.group(1) in settings]
    assert len(named) >= 12
    for m in named:
        assert m.group(2) in settings[m.group(1)], f"no setting {m.group(0)}"


def test_every_environment_variable_named_is_read_by_the_code():
    known = doctor.hub_env_names(REPO) | doctor.declared_env_names(REPO)
    # A read the doctor's pattern does not see (paths.py reads JARVIS_HOME through a
    # mapping named ``source``): the name quoted in the hub's own code counts too.
    code = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in [*(REPO / "agents").rglob("*.py"), REPO / "serve.py"])
    named = [m.group(1) for m in (ENV.match(s) for s in _spans()) if m]
    assert len(named) >= 4
    for name in named:
        assert name in known or f'"{name}"' in code, f"the guide names {name}, which nothing reads"


def test_every_route_named_is_served():
    routes = _routes()
    named = [m.groups() for m in (ROUTE.match(s) for s in _spans()) if m]
    assert len(named) >= 4
    for method, path in named:
        assert (method, path) in routes, f"no route {method} {path}"


# ── every reason a tool prints is in the guide ──────────────────────
def test_every_route_readiness_reason_is_explained():
    from agents.core.routers.onboarding import MODEL_READINESS_REASONS

    spans = set(_spans())
    missing = sorted(MODEL_READINESS_REASONS - spans)
    assert not missing, f"runtime_resolves reasons the guide does not explain: {missing}"


def test_every_runtime_probe_reason_is_explained():
    spans = " ".join(_spans(_section("Local model servers")))
    for runtime, _ in bootstrap.RUNTIME_PROBES:
        for reason in ("connection_refused", "timeout", "http_status:"):
            assert f"{runtime}={reason}" in spans, f"{runtime}={reason}"


def test_every_jobs_doctor_problem_code_is_in_the_jobs_tree():
    source = (REPO / "agents" / "core" / "autonomy" / "jobs_health.py").read_text(encoding="utf-8")
    codes = set(re.findall(r"problem\([^,]+,\s*[\"']([a-z_]+)[\"']\s*,", source))
    # "last_run_" + the scheduler outcome (scheduler_health.py: failed, missed, max_instances)
    codes |= {"last_run_failed", "last_run_missed", "last_run_max_instances"}
    assert {"scheduler_not_running", "channel_unavailable", "toolsets_unavailable"} <= codes
    spans = set(_spans(_section("Scheduled jobs")))
    missing = sorted(codes - spans)
    assert not missing, f"nerva jobs doctor codes the jobs tree does not explain: {missing}"


# ── the doctor points at the guide ──────────────────────────────────
def test_every_doctor_help_link_lands_on_a_real_heading():
    anchors = _anchors()
    assert doctor.TROUBLESHOOTING_DOC == "docs/TROUBLESHOOTING.md"
    for name, section in doctor.HELP_SECTIONS.items():
        assert section in anchors, f"{name} -> #{section}: no such heading"
    for name in (*doctor.REQUIRED, *doctor.ADVISORY):
        if name not in ("host_not_root", "sshd_no_passwords", "container_storage"):  # carry their own fix
            assert name in doctor.HELP_SECTIONS, f"doctor row {name} has no troubleshooting section"
