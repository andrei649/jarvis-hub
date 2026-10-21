"""H631 — diagnose a broken install from a symptom, without a screen-share.

``docs/TROUBLESHOOTING.md`` is the user-facing triage guide: a fixed recovery sequence, a
symptom -> cause -> fix table, the "my agent feels dumber" checklist, the named failure
modes of Ollama and LM Studio, and the scheduled-jobs tree. A guide that names a command
or a setting the code does not have sends the reader nowhere, so every command, setting,
environment variable and route the guide names is checked against the code here, and
every reason the doctor, the route check and ``nerva jobs doctor`` can print is named in
it. Hermetic: reads files, parses the CLI, imports no server.
"""

import ast
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


#: ``cat.key`` spans that are not settings, each with where it really lives — anything
#: else shaped like a setting must be one, so a typo in the category cannot slip through.
NOT_SETTINGS = {
    "category.key": None,  # the placeholder in the intro
    "scheduler.timezone": ("agents/core/autonomy/jobs_health.py", '"timezone"'),  # jobs doctor output
}


def test_every_setting_named_is_a_real_setting():
    settings = _settings()
    named = [m for m in (SETTING.match(s) for s in _spans()) if m and m.group(0) not in NOT_SETTINGS]
    assert len(named) >= 12
    for m in named:
        assert m.group(1) in settings, f"no settings category {m.group(1)!r} (in {m.group(0)})"
        assert m.group(2) in settings[m.group(1)], f"no setting {m.group(0)}"
    for span, where in NOT_SETTINGS.items():
        if where:
            path, needle = where
            assert needle in (REPO / path).read_text(encoding="utf-8"), f"{span}: not in {path}"


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


def _probe_reasons() -> set[str]:
    """Every reason ``bootstrap.detect_runtimes`` can put on a probe row (the doctor's
    ``runtimes`` detail ``ollama=…``), read from its source: a new one cannot go unnamed."""
    source = (REPO / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    reasons = {m.group(1) for m in re.finditer(r"row\[\"reason\"\] = f?\"([a-z_]+:?)", source)}
    assert {"connection_refused", "timeout", "http_status:", "probe_error:"} <= reasons
    return reasons - {"ok"}


def test_every_runtime_probe_reason_is_explained():
    spans = " ".join(_spans(_section("Local model servers")))
    for runtime, _ in bootstrap.RUNTIME_PROBES:
        for reason in _probe_reasons():
            assert f"{runtime}={reason}" in spans, f"{runtime}={reason}"


def test_the_address_diagnosis_matches_what_the_doctor_probes():
    """The doctor's ``runtimes`` row probes the fixed loopback ports of
    ``bootstrap.RUNTIME_PROBES`` and never reads ``llm.ollama_url`` / ``llm.lm_studio_url``;
    only the hub's router does. So a wrong ``llm.*_url`` shows as ``provider_offline`` on
    ``runtime_resolves``, never as ``=connection_refused`` on ``runtimes``."""
    doctor_src = (REPO / "scripts" / "doctor.py").read_text(encoding="utf-8")
    bootstrap_src = (REPO / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    for name in ("ollama_url", "lm_studio_url", "JARVIS_OLLAMA_URL", "JARVIS_LM_STUDIO_URL"):
        assert name not in doctor_src and name not in bootstrap_src, f"the doctor now reads {name}"
    body = _section("Local model servers")
    for _runtime, url in bootstrap.RUNTIME_PROBES:
        hostport = url.split("//", 1)[1].split("/", 1)[0]
        assert hostport in body, f"the guide does not say the doctor probes {hostport}"
    rows = [line for line in body.splitlines() if line.startswith("| ") and "---" not in line]
    url_rows = [line for line in rows if "llm.ollama_url" in line or "llm.lm_studio_url" in line]
    assert len(url_rows) >= 2
    for line in url_rows:
        _mode, seen, _fix = (cell.strip() for cell in line.strip("|").split("|"))
        assert "connection_refused" not in seen, f"a wrong llm.*_url cannot show as connection_refused: {line}"
        assert "provider_offline" in seen, f"a wrong llm.*_url shows as provider_offline: {line}"


def _scheduler_outcome_codes() -> set[str]:
    """``last_run_`` + every non-ok outcome the scheduler records (scheduler_health.py's
    ``statuses`` map and ``_returned_status``) + the job's own failed status."""
    source = (REPO / "agents" / "core" / "scheduler_health.py").read_text(encoding="utf-8")
    statuses = re.search(r"statuses = \{(.*?)\}", source, re.S)
    assert statuses, "scheduler_health.py no longer has its statuses map"
    outcomes = set(re.findall(r":\s*\"([a-z_]+)\"", statuses.group(1)))
    returned = re.search(r"def _returned_status\(.*?(?=\ndef )", source, re.S)
    assert returned
    outcomes |= set(re.findall(r"return \"([a-z_]+)\"", returned.group(0)))
    from agents.core.autonomy import jobs

    outcomes |= {jobs.STATUS_FAILED}
    outcomes -= {"ok", "pending", "skipped"}  # not problems (jobs_health.py / persist())
    assert {"failed", "missed", "max_instances"} <= outcomes
    return {f"last_run_{o}" for o in outcomes}


def test_every_jobs_doctor_problem_code_is_in_the_jobs_tree():
    source = (REPO / "agents" / "core" / "autonomy" / "jobs_health.py").read_text(encoding="utf-8")
    codes = set(re.findall(r"problem\([^,]+,\s*[\"']([a-z_]+)[\"']\s*,", source))
    assert '"last_run_" + outcome["status"]' in source  # the derived codes below
    codes |= _scheduler_outcome_codes()
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


# ── every reason a doctor row prints is explained where its link points ──
def _literal_prefix(node) -> str | None:
    """The fixed start of a reason expression: a string, an f-string's leading text, or
    the left side of ``"prefix" + …``; None when nothing fixed leads it."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return node.values[0].value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_prefix(node.left)
    return None


def _dynamic_reasons() -> dict[tuple[str, str], set[str]]:
    """A reason the doctor passes on from elsewhere — (row, expression) -> every value it
    can take, derived from the source that produces it where that source is code."""
    from agents.core.routers.onboarding import MODEL_READINESS_REASONS

    bootstrap_src = (REPO / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    smoke = re.search(r"def run_install_smoke\(.*?(?=\ndef )", bootstrap_src, re.S)
    assert smoke
    floor = re.search(r"def check_python\(.*?(?=\ndef )", bootstrap_src, re.S)
    assert floor and "python_too_old:" in floor.group(0)
    doctor_src = (REPO / "scripts" / "doctor.py").read_text(encoding="utf-8")
    lock_reasons = set(re.findall(r"rows\.append\(\(src_name, lock\.name, \"([a-z_]+)\"\)\)", doctor_src))
    assert lock_reasons == {"source_missing", "lock_missing"}, lock_reasons
    assert '"ok" if want == have else "lock_stale"' in doctor_src
    return {
        ("python", "reason"): {"python_too_old:"},
        ("locks_in_sync", "bad[0]"): {f"{r}:" for r in lock_reasons} | {"lock_stale:"},
        ("runtime_resolves", "reason"): set(MODEL_READINESS_REASONS) | {"unreported"},
        ("smoke", "exc.reason"): set(re.findall(r"BootstrapError\(\"([a-z_]+)\"", smoke.group(0))),
        ("config_sources", "reason"): {"env_not_utf8:", "withheld_env_names:"},
    }


def _doctor_failure_reasons() -> dict[str, set[str]]:
    """Row -> every reason the doctor can print on it while failed or warned, read from
    scripts/doctor.py with ``ast``: each ``_result(row, <not True>, reason)`` and each
    ``Check(row, <not OK/SKIP>, reason)``. A new literal reason is collected without a test
    edit; a new pass-through expression fails until ``_dynamic_reasons`` names its values."""
    tree = ast.parse((REPO / "scripts" / "doctor.py").read_text(encoding="utf-8"))
    dynamic = _dynamic_reasons()
    seen_dynamic: set = set()
    found: dict[str, set[str]] = {}
    for fn in tree.body:
        # _result is the constructor itself; the host rows carry their own fix
        if not isinstance(fn, ast.FunctionDef) or fn.name in ("_result", "check_host_posture"):
            continue
        local = {t.id: n.value.value for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                 for t in n.targets if isinstance(t, ast.Name)}
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id in ("_result", "Check") and len(call.args) >= 3):
                continue
            row_node, status, reason = call.args[:3]
            if call.func.id == "_result" and isinstance(status, ast.Constant) and status.value is True:
                continue
            if call.func.id == "Check" and isinstance(status, ast.Name) and status.id in ("OK", "SKIP"):
                continue
            row = row_node.value if isinstance(row_node, ast.Constant) else local.get(getattr(row_node, "id", ""))
            assert row is not None, f"doctor.{fn.name}: a failing row the test cannot name"
            prefix = _literal_prefix(reason)
            if prefix is None:
                key = (row, ast.unparse(reason))
                assert key in dynamic, f"doctor.{fn.name}: reason {key[1]!r} on {row} — name its values"
                seen_dynamic.add(key)
                found.setdefault(row, set()).update(dynamic[key])
            else:
                found.setdefault(row, set()).add(prefix)
    assert seen_dynamic == set(dynamic), f"stale pass-through entries: {set(dynamic) - seen_dynamic}"
    return found


def _anchored_section(anchor: str) -> str:
    """The text under the heading whose anchor is ``anchor``, up to the next heading of the
    same or a higher level (subsections included)."""
    lines = _guide().splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(#{2,4}) (.+)$", line)
        if m and _slug(m.group(2)) == anchor:
            level = len(m.group(1))
            body = []
            for nxt in lines[i + 1:]:
                h = re.match(r"^(#{2,4}) ", nxt)
                if h and len(h.group(1)) <= level:
                    break
                body.append(nxt)
            return "\n".join(body)
    raise AssertionError(f"no heading for #{anchor}")


def test_every_doctor_reason_is_explained_in_the_section_its_link_points_to():
    reasons = _doctor_failure_reasons()
    # the collection reaches every linked row, and the reasons the review named
    assert set(doctor.HELP_SECTIONS) <= set(reasons), set(doctor.HELP_SECTIONS) - set(reasons)
    for row, expected in (("runtimes", "no_local_runtime"), ("readyz", "readyz_bad_reply"),
                          ("config_sources", "provenance_unavailable"), ("voice", "capabilities_status:"),
                          ("smoke", "smoke_failed"), ("smoke", "smoke_output_unparseable"),
                          ("runtime_resolves", "hub_url_invalid"), ("runtime_resolves", "unreported"),
                          ("locks_in_sync", "source_missing:")):
        assert expected in reasons[row], (row, expected)
    missing = []
    for row, values in sorted(reasons.items()):
        for reason in sorted(values):
            link = doctor.help_for(doctor.Check(row, doctor.WARN, reason))
            assert link.startswith(doctor.TROUBLESHOOTING_DOC + "#"), (row, reason)
            spans = _spans(_anchored_section(link.split("#", 1)[1]))
            if not any(s.startswith(reason) for s in spans):
                missing.append(f"{row}={reason} -> {link}")
    assert not missing, "doctor reasons the linked section does not explain:\n" + "\n".join(missing)


# ── the claims about the CLI and the scheduler hold ─────────────────
def test_recovery_step_names_every_exit_code_a_chat_turn_returns():
    from agents.cli import nerva

    source = (REPO / "agents" / "cli" / "nerva.py").read_text(encoding="utf-8")
    body = re.search(r"def cmd_chat\(.*?(?=\ndef )", source, re.S).group(0)
    names = set(re.findall(r"\b(EXIT_[A-Z_]+)\b", body)) - {"EXIT_INTERRUPTED"}  # Ctrl-C
    assert {"EXIT_OK", "EXIT_FAILED", "EXIT_NO_HUB", "EXIT_AUTH", "EXIT_USAGE"} <= names
    step = re.search(r"^4\. .*?(?=^5\. )", _section("Recovery sequence"), re.S | re.M).group(0)
    step = " ".join(step.split()).lower()
    for name in sorted(names):
        assert f"exit {getattr(nerva, name)}" in step, f"recovery step 4 does not name {name}"


def test_permissions_branch_names_the_withheld_admin_token():
    """The CLI withholds JARVIS_ADMIN_TOKEN over plain http to another machine
    (``_withheld_admin``); a 401/403 there is not fixed by setting the token again."""
    source = (REPO / "agents" / "cli" / "nerva.py").read_text(encoding="utf-8")
    assert "def _withheld_admin" in source
    body = " ".join(_section("Scheduled jobs").split("### Permissions", 1)[1].split("### ", 1)[0].split())
    assert "withholds `JARVIS_ADMIN_TOKEN`" in body and "https" in body and "NERVA_HUB_URL" in body


def test_first_run_claim_matches_the_policy():
    """``first_run_decision``: a one-shot never fires early, even when asked; only an
    interval-cadence ask/brief/task/script job fires on creation by default."""
    from agents.core.autonomy import jobs

    class _Job:
        runnable = True
        cron = jobs.ONE_SHOT_PREFIX + "2099-01-01T00:00:00+00:00"
        options: dict = {}
        action = {"type": "ask"}

    assert jobs.is_one_shot(_Job.cron)
    assert jobs.first_run_decision(_Job(), explicit=True) == (False, "one-shot")
    text = " ".join(_section("Scheduled jobs").split())
    assert "fires any new job" not in text
    assert "one-shot" in text and "--first-run" in text


# ── the failure modes Hermes names are covered (review round 2) ─────
def _subsection(parent: str, sub: str) -> str:
    """One ``### `` subsection of a ``## `` section, flattened to single spaces."""
    body = _section(parent).split(f"\n### {sub}\n", 1)[1]
    return " ".join(body.split("\n### ", 1)[0].split())


def _table_rows(text: str) -> list[list[str]]:
    rows = [line for line in text.splitlines() if line.startswith("| ") and "---" not in line]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in rows]


def _server_rows(server: str) -> list[list[str]]:
    body = _section("Local model servers").split(f"\n### {server}\n", 1)[1].split("\n### ", 1)[0]
    return _table_rows(body)


def _ollama_tool_turn(status: int, body: dict, caplog) -> str:
    """Run OllamaBackend.generate_tool_turn against a mocked /api/chat; the reply text."""
    import asyncio
    import logging

    import httpx

    from agents.core.llm.base import OllamaBackend
    from agents.core.llm.tool_protocol import ToolSpec

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(status, json=body)

    backend = OllamaBackend("http://ollama.test", num_ctx=8192)
    backend.client = httpx.AsyncClient(base_url="http://ollama.test",
                                       transport=httpx.MockTransport(handler))
    with caplog.at_level(logging.ERROR, logger="jarvis.llm.base"):
        turn = asyncio.run(backend.generate_tool_turn(
            "m", [{"role": "user", "content": "hi"}], [ToolSpec(name="memory")]))
    assert seen and seen[0]["tools"], "the tool loop offers tools to /api/chat"
    return turn.content


def test_ollama_model_without_tools_is_an_error_bubble_not_text(caplog):
    """Ollama refuses ``tools`` for a model whose template has none: HTTP 400
    ``<model> does not support tools``. The owner gets a reply that says so (not the
    generic "hit an error" bubble, not JSON as text), the log keeps the server's words,
    and the guide's Ollama table names both."""
    from agents.core.llm.base import (
        OLLAMA_TOOLS_UNSUPPORTED_REPLY,
        is_backend_failure_reply,
        is_degraded_reply,
    )

    reply = _ollama_tool_turn(400, {"error": "m does not support tools"}, caplog)
    assert reply == OLLAMA_TOOLS_UNSUPPORTED_REPLY
    assert is_degraded_reply(reply) and is_backend_failure_reply(reply)
    assert "llm.tool_loop_enabled" in reply and "ollama show" in reply
    assert "server said:" in caplog.text and "does not support tools" in caplog.text
    # any other 400 keeps the generic bubble
    caplog.clear()
    other = _ollama_tool_turn(400, {"error": "invalid options"}, caplog)
    assert other.startswith("⚠️ The local Ollama model hit an error")

    rows = _server_rows("Ollama")
    no_tools = [r for r in rows if "no tool support" in r[0]]
    assert no_tools, "Ollama: no 'model has no tool support' failure mode"
    _mode, seen, fix = no_tools[0]
    assert "llm.tool_loop_enabled" in seen and "does not support tools" in seen
    assert "nerva logs -n 100" in seen
    assert " ".join(OLLAMA_TOOLS_UNSUPPORTED_REPLY.split()) in " ".join(seen.split())
    assert "ollama show MODEL" in fix and "nerva config set llm.tool_loop_enabled false" in fix
    # the "server error" row points there, so the 400 is not read as a corrupt model
    server_error = [r for r in rows if r[0] == "server error"][0]
    assert "no tool support" in server_error[2]


def test_tool_calls_as_text_rows_are_for_tool_capable_models():
    """JSON-as-text is what a model that does take ``tools`` produces when it writes the
    call into its answer — not what a model without tools produces on Ollama."""
    from agents.core.llm.base import LMStudioBackend, OllamaBackend

    assert LMStudioBackend.supports_tools is True and OllamaBackend.supports_tools is True
    runtime = (REPO / "agents" / "core" / "agent_runtime.py").read_text(encoding="utf-8")
    assert 'getattr(backend, "supports_tools", False)' in runtime
    for server in ("Ollama", "LM Studio"):
        rows = [r for r in _server_rows(server) if "as text" in r[0]]
        assert rows, f"{server}: no 'tool calls appear as text' failure mode"
        _mode, seen, fix = rows[0]
        assert "llm.tool_loop_enabled" in seen + fix, server
        assert "nerva config set llm.tool_loop_enabled false" in fix, server
    ollama_text = [r for r in _server_rows("Ollama") if "as text" in r[0]][0]
    assert "has no native tool calling" not in ollama_text[2]
    assert "lists `tools`" in ollama_text[2]
    # the degraded-bubble symptom names the no-tools cause; step 7 names both symptoms
    bubble = [r for r in _table_rows(_section("Symptom, cause, fix")) if "degraded bubble" in r[0]]
    assert bubble and "does not support tools" in bubble[0][1] and "#ollama" in bubble[0][2]
    step7 = " ".join(re.search(r"^7\. .*?(?=^8\. )", _section('"My agent feels dumber"'),
                               re.S | re.M).group(0).split())
    assert "as text" in step7 and "does not support tools" in step7
    assert "#local-model-servers" in step7 or "#ollama" in step7


def test_memory_step_names_the_untrusted_content_refusal():
    """The memory tool refuses a write once the turn has read untrusted content."""
    src = (REPO / "agents" / "core" / "memory_tool.py").read_text(encoding="utf-8")
    assert "\"memory_untrusted_turn\"" in src
    steps = re.split(r"^\d+\. ", _section('"My agent feels dumber"'), flags=re.M)[1:]
    step = [" ".join(s.split()) for s in steps if "forget" in s.lower() and "memory" in s.lower()][0]
    assert "untrusted" in step and "`memory_untrusted_turn`" in step


def test_checklist_has_a_memory_step_that_matches_the_code():
    from agents.core.cognition.memory import CoreMemory
    from agents.core.memory_tool import TARGETS, TOOL_NAME
    from agents.core.settings_db import DEFAULTS
    from agents.core.tool_profiles import OWNER_OPERATOR_TOOLS

    steps = re.split(r"^\d+\. ", _section('"My agent feels dumber"'), flags=re.M)[1:]
    memory = [" ".join(s.split()) for s in steps if "forget" in s.lower() and "memory" in s.lower()]
    assert memory, "no checklist step about memory"
    step = memory[0]
    # what is stored: selected facts in two bounded rings, not a transcript
    assert "not a transcript" in step
    assert f"{CoreMemory().cap} facts" in step
    assert set(TARGETS) == {"memory", "user"}
    # who writes it: the model's memory tool on owner turns, or the off-by-default review
    assert TOOL_NAME in OWNER_OPERATOR_TOOLS and "`memory` tool" in step
    settings = {(r["category"], r["key"]): r["value"] for r in DEFAULTS}
    for name in ("cognition.enabled", "cognition.memory_enabled", "cognition.review_enabled",
                 "memory.recall_enabled"):
        assert f"`{name}`" in step, name
    assert settings[("cognition", "enabled")] is False
    assert settings[("cognition", "review_enabled")] is False
    assert settings[("memory", "recall_enabled")] is False
    assert "off by default" in step
    # when a turn sees it: the core block is frozen per session and day
    orch = (REPO / "agents" / "core" / "orchestrator.py").read_text(encoding="utf-8")
    assert 'cache_key = (session, time.strftime("%Y-%m-%d"))' in orch
    assert "next session" in step
    # how to check one was stored
    for route in ("GET /api/memory/core", "GET /api/memory/search", "POST /api/memory/remember"):
        assert f"`{route}`" in step, route
    rows = _table_rows(_section("Symptom, cause, fix"))
    assert any("last week" in r[0] and "#my-agent-feels-dumber" in r[2] for r in rows)


def test_jobs_tree_covers_channel_permissions_spent_one_shots_and_unattended_tools():
    from agents.core import job_toolsets
    from agents.core.autonomy import jobs

    delivery = _subsection("Scheduled jobs", "Delivery")
    assert "allowed to post" in delivery and 'nerva send --channel telegram "test"' in delivery
    # a one-shot runs once: it stops being runnable, and the jobs doctor skips it
    class _Spent:
        enabled, paused_reason, options, attempts = True, None, {}, 1
        cron = jobs.ONE_SHOT_PREFIX + "2099-01-01T00:00:00+00:00"

    assert jobs.Job.runnable.fget(_Spent()) is False
    health = (REPO / "agents" / "core" / "autonomy" / "jobs_health.py").read_text(encoding="utf-8")
    assert "if not job.runnable:\n            continue" in health
    timing = _subsection("Scheduled jobs", "Timing")
    assert "one-shot" in timing and "runnable" in timing and "expected" in timing
    assert jobs.ONE_SHOT_SPENT in timing
    # unattended turns: the internal posture, the fixed toolset catalog, no memory tool
    skills = _subsection("Scheduled jobs", "Skill loading")
    assert "`llm.internal_actuation`" in skills
    for group in job_toolsets.CATALOG:
        assert f"`{group}`" in skills, group
    assert "`memory`" in skills and "execute_code" in skills
