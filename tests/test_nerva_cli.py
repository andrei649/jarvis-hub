"""The `nerva` command (Hermes absorption, wave 1).

One discoverable command tree for a headless install. Online verbs speak to the running
hub over the same admin/user-guarded routes the HUD uses — so they can do exactly what the
HUD can do and nothing more — and offline verbs read the same data root without the hub.

Hermetic: a recording fake client stands in for the hub, a temp settings DB for the data
root, a temp file for the log. No network, no server.
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from agents.cli import client as client_module
from agents.cli.client import HubClient, HubError, HubUnavailable, hub_url
from agents.cli.nerva import (
    EXIT_AUTH,
    EXIT_FAILED,
    EXIT_NO_HUB,
    EXIT_OK,
    EXIT_USAGE,
    Context,
    build_parser,
    command_tree,
    completion_script,
    explain_action,
    main,
)
from agents.core import settings_db


class _FakeHub:
    """Records every request; answers from a route table; raises what it is told to."""

    def __init__(self, routes=None, *, raise_with=None):
        self.routes = dict(routes or {})
        self.calls = []
        self.raise_with = raise_with
        self.base_url = "http://127.0.0.1:8080"

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.raise_with is not None:
            raise self.raise_with
        key = f"{method} {path}"
        if key not in self.routes:
            raise HubError(404, f"no fake route {key}")
        answer = self.routes[key]
        return answer(body) if callable(answer) else answer

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body if body is not None else {})


def _run(argv, hub=None, environ=None, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    hub = hub if hub is not None else _FakeHub()
    # A StringIO is not a TTY, so piped stdin is what the verb sees; "" is an empty pipe.
    ctx = Context(environ=dict(environ or {}), out=out, err=err, inp=io.StringIO(stdin),
                  client_factory=lambda env: hub)
    code = main(argv, context=ctx)
    return code, out.getvalue(), err.getvalue(), hub


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    return tmp_path


# ── the tree ─────────────────────────────────────────────────────────────────


def test_the_command_tree_is_discoverable_and_complete():
    tree = command_tree(build_parser())
    assert set(tree) == {
        "doctor", "extensions", "status", "config", "approvals", "kernel", "tools", "inspect", "logs", "estop", "jobs", "sessions", "chat", "send", "completion",
        "prompt-size", "desktop", "security", "todo", "skills",
    }
    # S2 added the two owner acts an extension needs: agree to what a descriptor
    # declares, and prove it in the sandbox. `doctor` and `list` stay read-only.
    assert tree["extensions"] == ["activate", "consent", "doctor", "list"]
    # H022: the audit is the only security act so far; it reads and reports, never mutates.
    assert tree["security"] == ["audit"]
    assert tree["config"] == ["check", "get", "list", "set"]
    assert tree["approvals"] == ["accept", "defer", "edit", "list", "reject"]
    assert tree["kernel"] == ["explain"]
    assert tree["estop"] == ["engage", "resume", "status"]
    # H350: the linter reads files and reports; it never writes a skill.
    assert tree["skills"] == ["lint", "list", "off", "on"]


@pytest.mark.parametrize("report,expected", [
    ({"ok": True, "problems": []}, EXIT_OK),
    ({"ok": False, "problems": [{"code": "overdue"}]}, EXIT_FAILED),
    ({"ok": True, "problems": [{"code": "overdue"}]}, EXIT_FAILED),
    ({}, EXIT_FAILED),
    ({"ok": "true", "problems": []}, EXIT_FAILED),
])
def test_jobs_doctor_exit_status_requires_verified_health(report, expected):
    hub = _FakeHub({"GET /api/jobs/doctor": report})
    code, out, _err, hub = _run(["jobs", "doctor", "--json"], hub=hub)
    assert code == expected and json.loads(out) == report
    assert hub.calls == [("GET", "/api/jobs/doctor", None)]


def test_no_verb_is_a_usage_error_not_a_traceback():
    code, _out, _err, _hub = _run([])
    assert code == EXIT_USAGE


def test_completion_scripts_are_generated_from_the_parser():
    bash = completion_script("bash")
    zsh = completion_script("zsh")
    for verb in command_tree():
        assert verb in bash and verb in zsh
    assert "kernel) COMPREPLY" in bash and "explain" in bash
    assert bash.strip().endswith("complete -F _nerva nerva")
    assert zsh.startswith("#compdef nerva")
    code, out, _err, _hub = _run(["completion", "bash"])
    assert code == EXIT_OK and "complete -F _nerva nerva" in out


# ── the client ───────────────────────────────────────────────────────────────


def test_hub_url_prefers_the_explicit_override_then_the_hub_bind():
    assert hub_url({}) == "http://127.0.0.1:8080"
    assert hub_url({"JARVIS_HOST": "127.0.0.1", "JARVIS_PORT": "9090"}) == "http://127.0.0.1:9090"
    assert hub_url({"NERVA_HUB_URL": "http://10.0.0.5:8080/"}) == "http://10.0.0.5:8080"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "[::]"])
def test_hub_url_reaches_a_wildcard_bound_hub_over_loopback(host):
    """JARVIS_HOST=0.0.0.0 (docs/PHONE_ACCESS.md) is a bind address, not a destination:
    Windows refuses to connect to it. Every interface includes loopback, so dial that."""
    assert hub_url({"JARVIS_HOST": host, "JARVIS_PORT": "9000"}) == "http://127.0.0.1:9000"


def test_client_sends_the_hub_credentials_as_the_hud_does():
    seen = {}

    class _Response:
        def __init__(self, request):
            seen["url"] = request.full_url
            seen["headers"] = {k.lower(): v for k, v in request.header_items()}
            seen["method"] = request.get_method()
            seen["body"] = request.data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"ok": true}'

    client = HubClient.from_env(
        {"JARVIS_ADMIN_TOKEN": "adm", "JARVIS_USER_TOKEN": "usr"}, opener=lambda request, timeout: _Response(request)
    )
    assert client.post("/x", {"a": 1}) == {"ok": True}
    assert seen["headers"]["x-admin-token"] == "adm"
    assert seen["headers"]["x-user-token"] == "usr"
    assert seen["method"] == "POST" and json.loads(seen["body"]) == {"a": 1}
    assert seen["url"] == "http://127.0.0.1:8080/x"


def test_client_maps_http_errors_and_unreachable_hubs():
    def _http_error(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"detail": "admin token required"}')
        )

    with pytest.raises(HubError) as info:
        HubClient(opener=_http_error).get("/autonomy/approvals")
    assert (info.value.status, info.value.reason) == (401, "admin token required")

    def _down(request, timeout):
        raise urllib.error.URLError("connection refused")

    with pytest.raises(HubUnavailable):
        HubClient(opener=_down).get("/status")
    assert client_module.DEFAULT_HUB_URL == "http://127.0.0.1:8080"

    class _CutOff:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            import http.client
            raise http.client.IncompleteRead(b'{"version": "1.', 40)

    # A reply cut off mid-body is the hub being unreachable, never a traceback.
    with pytest.raises(HubUnavailable):
        HubClient(opener=lambda request, timeout: _CutOff()).get("/status")


# ── online verbs ─────────────────────────────────────────────────────────────

STATUS = {
    "version": "1.0.0", "llm_backend": "lm-studio", "loaded_model": "gemma-4", "model_state": "loaded",
    "agents": [{"id": "jarvis", "status": "idle"}], "agents_online": 0, "agents_total": 18,
    "channels": [{"id": "telegram"}],
}


def test_status_reads_the_open_route_and_the_estop_when_allowed():
    hub = _FakeHub({"GET /status": STATUS, "GET /api/ops/estop": {"engaged": False, "state": None}})

    code, out, _err, hub = _run(["status"], hub)

    assert code == EXIT_OK
    assert "nerva 1.0.0" in out and "lm-studio" in out and "gemma-4" in out
    assert "0/18 busy" in out and "telegram" in out and "e-stop:      not engaged" in out


def test_status_says_when_the_estop_needs_a_token():
    hub = _FakeHub({"GET /status": STATUS})
    hub.routes["GET /api/ops/estop"] = lambda body: (_ for _ in ()).throw(HubError(401, "user token required"))

    code, out, _err, _hub = _run(["status"], hub)

    assert code == EXIT_OK
    assert "needs JARVIS_USER_TOKEN" in out


def test_status_json_is_the_raw_reply():
    hub = _FakeHub({"GET /status": STATUS, "GET /api/ops/estop": {"engaged": True, "state": {"reason": "x"}}})
    code, out, _err, _hub = _run(["status", "--json"], hub)
    assert code == EXIT_OK and json.loads(out)["estop"]["engaged"] is True


_ESTOP_OFF = {"engaged": False, "state": None}


def _command_center(**model):
    block = {
        "ready": False, "reason": "configured_not_resident", "route": "local",
        "selected_provider": "lm-studio", "selected_model": "test-route-model",
        "active_provider": None, "active_model": None, "residency_state": "known",
        "resident_models": [{"provider": "ollama", "id": "test-other-model"}],
    }
    block.update(model)
    return {"install": {"ready": True}, "model": block}


def test_status_says_the_route_is_not_runnable_though_a_model_is_resident():
    """H242: `status` used to print `(ready)` whenever ANY model was resident. The
    `runnable:` line carries the hub's strict verdict for the route a Jarvis turn takes,
    with the named reason; the legacy inventory word is shown as what it is."""
    resident_elsewhere = {**STATUS, "loaded_model": "test-other-model", "model_state": "ready"}
    hub = _FakeHub({
        "GET /status": resident_elsewhere,
        "GET /api/ops/estop": {"engaged": False, "state": None},
        "GET /api/onboarding/command-center": _command_center(),
    })

    code, out, _err, hub = _run(["status"], hub)

    assert code == EXIT_OK
    assert "runnable:    no — configured_not_resident: route local → lm-studio/test-route-model" in out
    assert "test-other-model (resident)" in out and "(ready)" not in out
    assert ("GET", "/api/onboarding/command-center", None) in hub.calls


@pytest.mark.parametrize("model, line", [
    ({"ready": True, "reason": "resident", "selected_model": "test-route-model",
      "active_provider": "lm-studio", "active_model": "test-route-model"},
     "runnable:    yes — route local → lm-studio/test-route-model (resident)"),
    ({"ready": True, "reason": "cloud_selected", "route": "cloud-flash",
      "selected_provider": "gemini", "selected_model": "test-cloud-model"},
     "runnable:    yes — route cloud-flash → gemini/test-cloud-model (cloud_selected)"),
    ({"ready": None, "reason": "residency_unknown"},
     "runnable:    unknown — residency_unknown: route local → lm-studio/test-route-model"),
    ({"ready": False, "reason": "route_unselected", "route": None,
      "selected_provider": None, "selected_model": None},
     "runnable:    no — route_unselected: no route"),
])
def test_status_runnable_line_names_the_verdict(model, line):
    hub = _FakeHub({"GET /status": STATUS, "GET /api/ops/estop": _ESTOP_OFF,
                    "GET /api/onboarding/command-center": _command_center(**model)})
    code, out, _err, _hub = _run(["status"], hub)
    assert code == EXIT_OK and line in out


def test_status_runnable_line_says_when_it_needs_a_token_or_could_not_read():
    hub = _FakeHub({"GET /status": STATUS, "GET /api/ops/estop": _ESTOP_OFF})
    hub.routes["GET /api/onboarding/command-center"] = (
        lambda body: (_ for _ in ()).throw(HubError(401, "user token required")))
    code, out, _err, _hub = _run(["status"], hub)
    assert code == EXIT_OK
    assert "runnable:    (needs JARVIS_USER_TOKEN or JARVIS_ADMIN_TOKEN to read)" in out

    hub = _FakeHub({"GET /status": STATUS, "GET /api/ops/estop": _ESTOP_OFF,
                    "GET /api/onboarding/command-center": {"install": {}}})
    code, out, _err, _hub = _run(["status"], hub)
    assert code == EXIT_OK and "runnable:    unknown — malformed_reply" in out

    hub = _FakeHub({"GET /status": STATUS, "GET /api/ops/estop": _ESTOP_OFF})  # no such route: 404
    code, out, _err, _hub = _run(["status"], hub)
    assert code == EXIT_OK and "runnable:    unknown — command_center_unavailable (HTTP 404" in out

    # /status already answered: a transport failure on the second read (a timeout, a
    # reset) is a verdict it could not read, not "no hub" — the status still prints.
    hub = _FakeHub({"GET /status": STATUS, "GET /api/ops/estop": _ESTOP_OFF})
    hub.routes["GET /api/onboarding/command-center"] = (
        lambda body: (_ for _ in ()).throw(HubUnavailable("http://127.0.0.1:8080", "timed out")))
    code, out, err, _hub = _run(["status"], hub)
    assert code == EXIT_OK and err == ""
    assert "backend:" in out
    assert "runnable:    unknown — hub_unreachable (no hub at http://127.0.0.1:8080 (timed out))" in out


@pytest.mark.parametrize("model", [
    {"ready": True, "route": None},
    {"ready": True, "selected_provider": None, "active_provider": None},
    {"ready": True, "selected_model": "", "active_model": None},
])
def test_status_never_says_runnable_for_a_verdict_that_names_nothing(model):
    """Same rule as the doctor's strict row: `yes` needs the route, provider and model."""
    hub = _FakeHub({"GET /status": STATUS, "GET /api/ops/estop": _ESTOP_OFF,
                    "GET /api/onboarding/command-center": _command_center(**model)})
    code, out, _err, _hub = _run(["status"], hub)
    assert code == EXIT_OK
    assert "runnable:    unknown — malformed_reply" in out and "runnable:    yes" not in out


def test_status_json_carries_the_runnable_verdict():
    hub = _FakeHub({"GET /status": STATUS, "GET /api/ops/estop": _ESTOP_OFF,
                    "GET /api/onboarding/command-center": _command_center()})
    code, out, _err, _hub = _run(["status", "--json"], hub)
    assert code == EXIT_OK
    assert json.loads(out)["runnable"] == {
        "ready": False, "reason": "configured_not_resident", "route": "local",
        "provider": "lm-studio", "model": "test-route-model",
    }


def test_approvals_list_and_decide_use_the_admin_routes():
    hub = _FakeHub(
        {
            "GET /autonomy/approvals": {
                "pending": [
                    {"id": 7, "kind": "payment.send", "title": "pay the plumber", "risk_tier": 3, "reversible": False},
                    {"id": 8, "kind": "writeback.notion", "title": "note", "risk_tier": 2, "reversible": True},
                ]
            },
            "POST /autonomy/tasks/7/decision": lambda body: {"ok": True, "task": {"id": 7, "status": body["action"] + "ed"}},
        }
    )

    code, out, _err, hub = _run(["approvals", "list"], hub)
    assert code == EXIT_OK
    assert "#7  tier 3  IRREVERSIBLE  payment.send" in out and "#8  tier 2  reversible" in out
    assert "2 pending" in out

    code, out, _err, hub = _run(["approvals", "accept", "7", "--payload", '{"note": "ok"}'], hub)
    assert code == EXIT_OK and "#7 accepted → accepted" in out
    assert hub.calls[-1] == ("POST", "/autonomy/tasks/7/decision", {"action": "accept", "payload": {"note": "ok"}})


def test_approvals_bad_payload_is_a_usage_error():
    code, _out, err, hub = _run(["approvals", "reject", "7", "--payload", "[1,2]"])
    assert code == EXIT_USAGE and "JSON object" in err
    assert hub.calls == []


def test_estop_verbs_hit_the_owner_routes():
    hub = _FakeHub(
        {
            "GET /api/ops/estop": {"engaged": False, "state": None},
            "POST /api/ops/estop/engage": lambda body: {"engaged": True, "state": {"engaged_at": "t0", "reason": body.get("reason")}},
            "POST /api/ops/estop/resume": {"engaged": False, "lifted": True},
        }
    )
    code, out, _err, hub = _run(["estop", "engage", "--reason", "smoke"], hub)
    assert code == EXIT_OK and "ENGAGED since t0 — smoke" in out
    assert hub.calls[-1] == ("POST", "/api/ops/estop/engage", {"reason": "smoke"})
    code, out, _err, hub = _run(["estop", "resume"], hub)
    assert code == EXIT_OK and "not engaged" in out
    code, out, _err, hub = _run(["estop", "status"], hub)
    assert code == EXIT_OK and hub.calls[-1][0] == "GET"


def test_sessions_and_chat_use_the_user_routes():
    hub = _FakeHub(
        {
            "GET /sessions": {"sessions": [{"session_id": "s1", "started_at": "2026-09-07"}]},
            "POST /chat": lambda body: {"reply": f"echo:{body['message']}:{body.get('agent', '-')}"},
        }
    )
    code, out, _err, hub = _run(["sessions"], hub)
    assert code == EXIT_OK and "s1  2026-09-07" in out
    code, out, _err, hub = _run(["chat", "hello", "--agent", "friday"], hub)
    assert code == EXIT_OK and out.strip() == "echo:hello:friday"
    assert hub.calls[-1] == ("POST", "/chat", {"message": "hello", "agent": "friday"})


def test_an_unreachable_hub_is_exit_3_with_the_next_step():
    hub = _FakeHub(raise_with=HubUnavailable("http://127.0.0.1:8080", "connection refused"))
    code, _out, err, _hub = _run(["status"], hub)
    assert code == EXIT_NO_HUB and "python serve.py" in err and "NERVA_HUB_URL" in err


def test_a_missing_credential_is_exit_4_with_how_to_mint_one():
    hub = _FakeHub(raise_with=HubError(401, "admin token required"))
    code, _out, err, _hub = _run(["approvals", "list"], hub)
    assert code == EXIT_AUTH and "JARVIS_ADMIN_TOKEN" in err and "token_recover.py issue admin" in err


def test_any_other_hub_error_is_exit_1():
    hub = _FakeHub(raise_with=HubError(409, "decision could not be applied"))
    code, _out, err, _hub = _run(["approvals", "accept", "1"], hub)
    assert code == EXIT_FAILED and "decision could not be applied" in err


# ── offline verbs ────────────────────────────────────────────────────────────


def test_config_list_get_set_and_check_work_on_the_data_root(temp_settings):
    code, out, _err, _hub = _run(["config", "get", "llm.tool_loop_enabled"])
    assert code == EXIT_OK and out.strip() == "false"

    code, out, _err, _hub = _run(["config", "set", "llm.tool_loop_enabled", "on"])
    assert code == EXIT_OK and "llm.tool_loop_enabled = true" in out and "30 s" in out
    assert settings_db.get_value("llm", "tool_loop_enabled") is True

    code, out, _err, _hub = _run(["config", "set", "llm.tool_loop_max_iterations", "12"])
    assert code == EXIT_OK and settings_db.get_value("llm", "tool_loop_max_iterations") == 12

    code, out, _err, _hub = _run(["config", "list", "llm"])
    assert code == EXIT_OK and "llm.tool_loop_max_iterations = 12  (number, set)" in out   # H273: changed from 8

    code, out, _err, _hub = _run(["config", "list", "--json"])
    assert code == EXIT_OK and json.loads(out)["llm"]

    code, out, _err, _hub = _run(["config", "check"])
    assert code == EXIT_OK and "matches its declared schema" in out


def test_config_set_refuses_what_the_schema_refuses(temp_settings):
    code, _out, err, _hub = _run(["config", "set", "llm.tool_loop_enabled", "maybe"])
    assert code == EXIT_FAILED and "on/off" in err
    assert settings_db.get_value("llm", "tool_loop_enabled") is False

    code, _out, err, _hub = _run(["config", "set", "llm.no_such_key", "1"])
    assert code == EXIT_FAILED and "not a declared setting" in err

    code, _out, err, _hub = _run(["config", "set", "badname", "1"])
    assert code == EXIT_USAGE and "category.key" in err

    code, _out, err, _hub = _run(["config", "get", "llm.no_such_key"])
    assert code == EXIT_FAILED

    code, _out, err, _hub = _run(["config", "list", "no_such_category"])
    assert code == EXIT_FAILED


def test_config_masks_secrets_unless_revealed(temp_settings):
    secret_row = next(
        (r for r in settings_db.DEFAULTS
         if r["kind"] == "text" and ("token" in r["key"] or "secret" in r["key"]) or r["kind"] in ("secret", "password")),
        None,
    )
    if secret_row is None:
        pytest.skip("no secret-shaped setting declared")
    name = f"{secret_row['category']}.{secret_row['key']}"
    settings_db.put_category(secret_row["category"], {secret_row["key"]: "sk-live-1234"})

    code, out, _err, _hub = _run(["config", "get", name])
    assert code == EXIT_OK and "sk-live-1234" not in out and "••••" in out
    code, out, _err, _hub = _run(["config", "get", name, "--reveal"])
    assert code == EXIT_OK and "sk-live-1234" in out


def test_config_shows_a_token_budget_as_the_number_it_is(temp_settings):
    """A number named ``…max_tokens`` is a budget, not a credential (review-H465c m-2:
    /refine tells the owner to raise ``learning.review_max_tokens``)."""
    for name in ("learning.review_max_tokens", "llm.max_tokens"):
        category, key = name.split(".")
        settings_db.put_category(category, {key: 4096})
        code, out, _err, _hub = _run(["config", "get", name])
        assert code == EXIT_OK and "4096" in out and "••" not in out, name


def test_logs_tail_the_hub_log_or_say_where_it_would_be(tmp_path, monkeypatch):
    log = tmp_path / "jarvis.log"
    log.write_text("\n".join(f"line {i}" for i in range(1, 101)), encoding="utf-8")
    code, out, _err, _hub = _run(["logs", "-n", "3"], environ={"JARVIS_LOG_FILE": str(log)})
    assert code == EXIT_OK and out.splitlines() == ["line 98", "line 99", "line 100"]

    code, _out, err, _hub = _run(["logs"], environ={"JARVIS_LOG_FILE": str(tmp_path / "missing.log")})
    assert code == EXIT_FAILED and "system.log_to_file" in err


def test_doctor_delegates_to_the_install_doctor(monkeypatch):
    from scripts import doctor

    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(doctor, "main", fake_main)
    code, _out, _err, _hub = _run(["doctor", "--json", "--smoke"])
    assert code == EXIT_OK and seen["argv"] == ["--json", "--smoke"]


# ── kernel explain ───────────────────────────────────────────────────────────


def test_kernel_explain_replays_the_gates_for_money_and_for_a_read(temp_settings, monkeypatch):
    from agents.core import estop

    monkeypatch.setattr(estop, "get_state", lambda: None)

    money = explain_action("payment", title="pay the plumber", payload={"amount": 120, "to": "plumber"})
    assert money["risk_tier"] == 3 and money["irreversible"] is True
    assert money["approval_required"] is True and money["verdict"].startswith("QUEUE")
    assert money["mediation"] == "kernel"  # `payment` is the registered, kernel-mediated kind

    # A kind no broker declares is named as such — not denied, not granted.
    nobody = explain_action("payment.send", payload={"amount": 120})
    assert nobody["mediation"] is None and nobody["verdict"].startswith("NO BROKER")
    assert nobody["risk_tier"] == 3  # the gates it would face are still shown
    assert [step["gate"] for step in money["path"]] == [
        "kill-switch", "mediation", "risk tier", "irreversible", "autonomy mode", "approval",
    ]
    assert {"field": "amount", "value": 120} in money["effects"]

    settings_db.put_category("autonomy", {"mode": "auto"})
    read = explain_action("tech_scout.finding", title="a finding")
    assert read["risk_tier"] == 0 and read["approval_required"] is False

    # In "ask" mode a pure read still acts; in "off" everything waits.
    settings_db.put_category("autonomy", {"mode": "ask"})
    assert explain_action("tech_scout.finding")["approval_required"] is False
    assert explain_action("draft_email", payload={"to": "x"})["approval_required"] is True
    settings_db.put_category("autonomy", {"mode": "off"})
    assert explain_action("tech_scout.finding")["approval_required"] is True
    settings_db.put_category("autonomy", {"mode": "auto"})

    code, out, _err, _hub = _run(["kernel", "explain", "payment", "--payload", '{"amount": 5}'])
    assert code == EXIT_OK
    assert "kernel explain: payment" in out and "→ QUEUE" in out and "static replay" in out


def test_kernel_explain_denies_under_the_emergency_stop(temp_settings, monkeypatch):
    from agents.core import estop

    monkeypatch.setattr(estop, "get_state", lambda: {"reason": "drill", "engaged_at": "t0"})

    result = explain_action("writeback.notion.page", payload={"target": "page"})
    assert result["verdict"].startswith("DENY") and "emergency stop" in result["verdict"]


def test_kernel_explain_json_and_bad_payload(temp_settings, monkeypatch):
    from agents.core import estop

    monkeypatch.setattr(estop, "get_state", lambda: None)
    code, out, _err, _hub = _run(["kernel", "explain", "social.post", "--json"])
    assert code == EXIT_OK and json.loads(out)["kind"] == "social.post"
    code, _out, err, _hub = _run(["kernel", "explain", "social.post", "--payload", "nope"])
    assert code in (EXIT_USAGE, EXIT_FAILED)


def test_the_wrapper_script_exists_and_points_at_the_package():
    wrapper = Path(__file__).resolve().parent.parent / "scripts" / "nerva.py"
    assert wrapper.exists()
    assert "from agents.cli.nerva import main" in wrapper.read_text(encoding="utf-8")


# ── jobs ─────────────────────────────────────────────────────────────────────

JOB = {
    "id": "abc123abc123", "name": "Reminder", "schedule_text": "every day at 10", "cron": "0 10 * * *",
    "enabled": True, "paused_reason": None, "last_status": "ok", "last_run_at": "2026-09-07T10:00:00+00:00",
}


def test_jobs_verbs_ride_the_admin_routes():
    hub = _FakeHub(
        {
            "GET /api/jobs": {"jobs": [JOB], "scheduler": {"alive": True, "runnable": 1, "paused": 0}},
            "GET /api/jobs/blueprints": {"blueprints": [{"id": "reminder", "title": "Reminder", "description": "d", "schedule_text": "every day at 9:00", "params": ["schedule_text", "message"]}]},
            "POST /api/jobs": lambda body: {"ok": True, "job": {**JOB, "name": body.get("name") or "Reminder"}},
            "GET /api/jobs/abc123abc123/runs": {"runs": [{"started_at": "t", "status": "ok", "summary": "reminder delivered to telegram"}]},
            "POST /api/jobs/abc123abc123/pause": lambda body: {"ok": True, "job": {**JOB, "paused_reason": body.get("reason", "paused")}},
            "POST /api/jobs/abc123abc123/resume": {"ok": True, "job": JOB},
            "POST /api/jobs/abc123abc123/run": {"ok": True, "run": {"status": "ok", "summary": "reminder delivered to telegram"}, "job": JOB},
            "DELETE /api/jobs/abc123abc123": {"ok": True},
        }
    )
    code, out, _err, hub = _run(["jobs", "list"], hub)
    assert code == EXIT_OK and "scheduler alive" in out and "abc123abc123  on     every day at 10" in out

    code, out, _err, hub = _run(["jobs", "blueprints"], hub)
    assert code == EXIT_OK and "reminder" in out and "params: schedule_text, message" in out

    code, out, _err, hub = _run(["jobs", "create", "--blueprint", "reminder", "--param", "message=water", "--when", "every day at 10"], hub)
    assert code == EXIT_OK and "armed abc123abc123" in out
    assert hub.calls[-1] == ("POST", "/api/jobs", {"blueprint": "reminder", "params": {"message": "water"}, "schedule_text": "every day at 10"})

    code, out, _err, hub = _run(["jobs", "create", "--name", "n", "--when", "every day at 9", "--action", '{"type":"remind","message":"m"}'], hub)
    assert code == EXIT_OK and hub.calls[-1][2]["action"] == {"type": "remind", "message": "m"}

    code, _out, err, hub = _run(["jobs", "create", "--name", "n"], hub)
    assert code == EXIT_USAGE and "--action" in err
    code, _out, err, hub = _run(["jobs", "create", "--blueprint", "reminder", "--param", "nonsense"], hub)
    assert code == EXIT_USAGE and "KEY=VALUE" in err

    code, out, _err, hub = _run(["jobs", "runs", "abc123abc123"], hub)
    assert code == EXIT_OK and "ok      reminder delivered" in out
    code, out, _err, hub = _run(["jobs", "pause", "abc123abc123", "--reason", "holiday"], hub)
    assert code == EXIT_OK and "is paused" in out and hub.calls[-1][2] == {"reason": "holiday"}
    code, out, _err, hub = _run(["jobs", "resume", "abc123abc123"], hub)
    assert code == EXIT_OK and "is runnable" in out
    code, out, _err, hub = _run(["jobs", "run", "abc123abc123"], hub)
    assert code == EXIT_OK and "ok: reminder delivered" in out
    code, out, _err, hub = _run(["jobs", "delete", "abc123abc123"], hub)
    assert code == EXIT_OK and "deleted abc123abc123" in out and hub.calls[-1][0] == "DELETE"


def test_jobs_is_in_the_tree_and_the_completion():
    assert command_tree()["jobs"] == ["blueprints", "create", "delete", "doctor", "edit", "incidents", "list", "notepad", "pause", "remove", "resume", "run", "runs", "status", "tick"]
    assert "jobs) COMPREPLY" in completion_script("bash")


# ── `nerva tools` — the reader for the tool loop's trail ─────────────────────
# Before this the loop ran with no event sink at all, so the 5a fence fired and left
# no trace anywhere the owner could look.

_TRAIL = [
    {"at": "2026-09-08T06:11:02+00:00", "agent_id": "jarvis", "event": "tool_requested",
     "tool": "web_search", "status": "requested", "call_id": "c1"},
    {"at": "2026-09-08T06:11:09+00:00", "agent_id": "stark", "event": "tool_result_untrusted",
     "tool": "osint_enrich", "status": "fenced", "reasons": ["untrusted_tool"],
     "injection_flags": [], "suspicious": False},
]


def _tools_hub(events=None, counts=None, limit=20):
    return _FakeHub(routes={
        f"GET /api/admin/tool-events?limit={limit}": {
            "events": _TRAIL if events is None else events,
            "counts": counts if counts is not None else {},
        },
    })


def test_tools_prints_the_trail_and_the_since_boot_tally():
    hub = _tools_hub(counts={"tool_requested": 4, "tool_result_untrusted": 1})
    code, out, _err, hub = _run(["tools"], hub=hub)
    assert code == EXIT_OK
    assert "tool_result_untrusted" in out and "osint_enrich" in out
    assert "reasons=untrusted_tool" in out
    assert "5 events, 1 fenced as untrusted" in out
    assert any("/api/admin/tool-events" in call[1] for call in hub.calls)


def test_tools_filters_by_agent_and_by_fenced_only():
    code, out, _err, _hub = _run(["tools", "--agent", "stark"], hub=_tools_hub())
    assert code == EXIT_OK and "osint_enrich" in out and "web_search" not in out

    code, out, _err, _hub = _run(["tools", "--untrusted"], hub=_tools_hub())
    assert code == EXIT_OK and "osint_enrich" in out and "tool_requested" not in out


def test_tools_says_so_when_nothing_has_used_the_loop():
    code, out, _err, _hub = _run(["tools"], hub=_tools_hub(events=[]))
    assert code == EXIT_OK and "no tool events yet" in out


def test_tools_bounds_the_number_of_events_it_asks_for():
    """A caller cannot ask the hub for an unbounded page, or for none."""
    for asked, sent in ((5, 5), (99999, 500), (0, 1)):
        hub = _tools_hub(events=[], limit=sent)
        code, _out, _err, hub = _run(["tools", "-n", str(asked)], hub=hub)
        assert code == EXIT_OK, (asked, hub.calls)
        assert any(f"limit={sent}" in call[1] for call in hub.calls), (asked, hub.calls)


def test_jobs_edit_sends_only_the_flags_that_were_given():
    """`nerva jobs edit` is the shell half of the H146/H449 gap."""
    hub = _FakeHub({"PATCH /api/jobs/abc": {"ok": True, "job": {
        "id": "abc", "name": "stretch", "schedule_text": "every day at 9", "cron": "0 9 * * *"}}})
    code, out, _err, hub = _run(["jobs", "edit", "abc", "--when", "every day at 9"], hub=hub)
    assert code == 0
    assert hub.calls == [("PATCH", "/api/jobs/abc", {"schedule_text": "every day at 9"})]
    assert "edited abc" in out and "0 9 * * *" in out


def test_jobs_edit_carries_name_schedule_and_action_together():
    hub = _FakeHub({"PATCH /api/jobs/abc": {"ok": True, "job": {"id": "abc"}}})
    code, _out, _err, hub = _run(
        ["jobs", "edit", "abc", "--name", "stretch", "--when", "every day at 9",
         "--action", '{"type":"remind","message":"m"}'], hub=hub)
    assert code == 0
    assert hub.calls[0][2] == {
        "name": "stretch",
        "schedule_text": "every day at 9",
        "action": {"type": "remind", "message": "m"},
    }


def test_jobs_edit_with_no_flags_is_a_usage_error_and_calls_nothing():
    code, _out, err, hub = _run(["jobs", "edit", "abc"])
    assert code == EXIT_USAGE
    assert "nothing to change" in err
    assert hub.calls == [], "a no-op edit must not reach the hub"


def test_jobs_edit_rejects_unparseable_action_json_before_calling():
    code, _out, err, hub = _run(["jobs", "edit", "abc", "--action", "{not json"])
    assert code == EXIT_USAGE and err.strip()
    assert hub.calls == []


def test_jobs_edit_prints_the_hubs_refusal_rather_than_claiming_success():
    hub = _FakeHub({"PATCH /api/jobs/abc": {"error": "a schedule that fires every minute"}})
    code, out, _err, _hub = _run(["jobs", "edit", "abc", "--when", "every minute"], hub=hub)
    assert code == 0
    assert "a schedule that fires every minute" in out
    assert "edited" not in out


def test_send_to_a_configured_channel_needs_no_inbox_thread():
    """H018/H480: the gap was that `send` could only answer, never speak first."""
    hub = _FakeHub({"POST /api/channels/send": {"ok": True, "channel": "telegram", "audited": True}})
    code, out, _err, hub = _run(["send", "--channel", "telegram", "the roof is leaking"], hub=hub)
    assert code == 0
    assert hub.calls == [("POST", "/api/channels/send", {
        "channel": "telegram", "text": "the roof is leaking", "source": "nerva.cli.send"})]
    assert "sent to telegram" in out
    assert "WARNING" not in out


def test_an_unaudited_send_is_reported_not_hidden():
    """Reversible tier means the audit record is the only trace; a missing one is news."""
    hub = _FakeHub({"POST /api/channels/send": {"ok": True, "channel": "telegram", "audited": False}})
    code, out, _err, _hub = _run(["send", "--channel", "telegram", "hi"], hub=hub)
    assert code == 0 and "not recorded in the audit log" in out


def test_send_prints_the_hubs_refusal_and_fails():
    hub = _FakeHub({"POST /api/channels/send": {
        "ok": False, "error": "no owner chat is configured (autonomy.owner_chat_id)"}})
    code, _out, err, _hub = _run(["send", "--channel", "telegram", "hi"], hub=hub)
    assert code == EXIT_FAILED and "autonomy.owner_chat_id" in err


def test_send_rejects_a_channel_id_that_is_not_one():
    code, _out, err, hub = _run(["send", "--channel", "../etc/passwd", "hi"])
    assert code == EXIT_USAGE and "channel id" in err
    assert hub.calls == [], "a malformed target must not reach the hub"


def test_send_to_a_channel_still_requires_a_message():
    """No argument, no --file and an empty pipe: a usage error that says where a body can come from."""
    code, _out, err, hub = _run(["send", "--channel", "telegram"])
    assert code == EXIT_USAGE and "no message provided" in err and "--file" in err
    assert hub.calls == []


# ── H480: body from a file or stdin, a subject, quiet, the list filter ───────

_SENT = {"POST /api/channels/send": {"ok": True, "channel": "ntfy", "audited": True}}


def _posted(hub):
    return [call for call in hub.calls if call[:2] == ("POST", "/api/channels/send")]


def test_send_reads_the_body_from_a_file(tmp_path):
    log = tmp_path / "build.log"
    log.write_text("step 1 ok\nstep 2 ok\n", encoding="utf-8")
    code, out, _err, hub = _run(["send", "--channel", "ntfy", "-f", str(log)], hub=_FakeHub(_SENT))
    assert code == 0 and "sent to ntfy" in out
    assert _posted(hub) == [("POST", "/api/channels/send",
                             {"channel": "ntfy", "text": "step 1 ok\nstep 2 ok\n", "source": "nerva.cli.send"})]


def test_send_reads_stdin_when_the_file_is_a_dash_and_when_stdin_is_a_pipe():
    code, _out, _err, hub = _run(["send", "--channel", "ntfy", "-f", "-"], hub=_FakeHub(_SENT), stdin="RAM 92%")
    assert code == 0 and _posted(hub)[0][2]["text"] == "RAM 92%"
    code, _out, _err, hub = _run(["send", "--channel", "ntfy"], hub=_FakeHub(_SENT), stdin="RAM 93%")
    assert code == 0 and _posted(hub)[0][2]["text"] == "RAM 93%"


class _Tty(io.StringIO):
    def isatty(self):
        return True

    def read(self, *a):
        raise AssertionError("the terminal must not be read")


def _run_with_stdin(argv, inp, hub=None):
    hub = hub if hub is not None else _FakeHub(_SENT)
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=inp, client_factory=lambda env: hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue(), hub


def test_send_never_reads_a_terminal_with_or_without_a_dash():
    """A TTY stdin is a usage error, not a hang — also when -f - asks for stdin explicitly."""
    code, _out, err, hub = _run_with_stdin(["send", "--channel", "ntfy"], _Tty())
    assert code == EXIT_USAGE and "no message provided" in err and hub.calls == []
    code, _out, err, hub = _run_with_stdin(["send", "--channel", "ntfy", "-f", "-"], _Tty())
    assert code == EXIT_USAGE and "terminal" in err and "--file PATH" in err and hub.calls == []


def test_send_with_stdin_closed_is_a_usage_error_not_a_traceback():
    """cron and `<&-` leave sys.stdin as None; -f - must say so and exit 2, not crash with exit 1."""
    code, _out, err, hub = _run_with_stdin(["send", "--channel", "ntfy", "-f", "-"], None)
    assert code == EXIT_USAGE and "stdin is closed" in err and hub.calls == []
    code, _out, err, hub = _run_with_stdin(["send", "--channel", "ntfy"], None)
    assert code == EXIT_USAGE and "no message provided" in err and hub.calls == []


def test_send_strips_a_byte_order_mark_and_refuses_a_bom_only_body(tmp_path):
    bom = tmp_path / "bom.txt"
    bom.write_bytes("\ufeffhello\n".encode("utf-8"))
    code, _out, _err, hub = _run(["send", "--channel", "ntfy", "-f", str(bom)], hub=_FakeHub(_SENT))
    assert code == 0 and _posted(hub)[0][2]["text"] == "hello\n"
    only = tmp_path / "only.txt"
    only.write_bytes("\ufeff \n".encode("utf-8"))
    code, _out, err, hub = _run(["send", "--channel", "ntfy", "-f", str(only)])
    assert code == EXIT_USAGE and "no message provided" in err and hub.calls == []
    code, _out, _err, hub = _run(["send", "--channel", "ntfy", "-f", "-"], hub=_FakeHub(_SENT), stdin="\ufeffpiped")
    assert code == 0 and _posted(hub)[0][2]["text"] == "piped"


def test_send_refuses_a_runaway_file_without_loading_it(tmp_path):
    class _Counting(io.StringIO):
        asked: list = []

        def read(self, size=-1):
            self.asked.append(size)
            return super().read(size)

    big = _Counting("x" * 1_000_000)
    code, _out, err, hub = _run_with_stdin(["send", "--channel", "ntfy", "-f", "-"], big)
    assert code == EXIT_USAGE and "longer than 4,000" in err and hub.calls == []
    assert _Counting.asked == [4_001], "only the bound plus one character is ever requested"
    huge = tmp_path / "huge.log"
    huge.write_text("y" * 50_000, encoding="utf-8")
    code, _out, err, hub = _run(["send", "--channel", "ntfy", "-f", str(huge)])
    assert code == EXIT_USAGE and "huge.log is longer than 4,000" in err and hub.calls == []


def test_send_takes_the_argument_or_the_file_not_both(tmp_path):
    log = tmp_path / "a.txt"
    log.write_text("x", encoding="utf-8")
    code, _out, err, hub = _run(["send", "--channel", "ntfy", "hello", "-f", str(log)])
    assert code == EXIT_USAGE and "not both" in err and hub.calls == []


def test_send_refuses_a_binary_file_without_echoing_it(tmp_path):
    blob = tmp_path / "chart.png"
    blob.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe secret-bytes")
    code, out, err, hub = _run(["send", "--channel", "ntfy", "-f", str(blob)])
    assert code == EXIT_USAGE and "not a text file" in err and "attachments" in err
    assert "secret-bytes" not in err + out and hub.calls == []


def test_send_names_an_unreadable_file_and_an_empty_one(tmp_path):
    code, _out, err, hub = _run(["send", "--channel", "ntfy", "-f", str(tmp_path / "missing.txt")])
    assert code == EXIT_USAGE and "cannot read" in err and "missing.txt" in err and hub.calls == []
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n", encoding="utf-8")
    code, _out, err, hub = _run(["send", "--channel", "ntfy", "-f", str(empty)])
    assert code == EXIT_USAGE and "no message provided" in err and hub.calls == []


def test_send_carries_a_subject_separately_to_a_channel_and_as_a_first_line_to_a_thread():
    code, _out, _err, hub = _run(["send", "--channel", "ntfy", "-s", "[CI]", "build green"], hub=_FakeHub(_SENT))
    assert code == 0
    assert _posted(hub)[0][2] == {"channel": "ntfy", "text": "build green", "subject": "[CI]",
                                  "source": "nerva.cli.send"}
    hub = _FakeHub({
        "GET /api/channels/inbox/t1": {"thread": {"thread_id": "t1", "reply": {"channel": "telegram"}}},
        "POST /api/channels/inbox/t1/reply": {"ok": True, "queued": True, "task_id": 7},
    })
    code, _out, _err, hub = _run(["send", "--to", "t1", "-s", "[CI]", "  build green"], hub=hub)
    assert code == 0
    assert hub.calls[-1] == ("POST", "/api/channels/inbox/t1/reply",
                             {"text": "[CI]\n\nbuild green", "source": "nerva.cli.send"})


def test_send_subject_is_one_printable_bounded_line():
    for bad in ["two\nlines", "a\rb", "a\x0bb", "a\u2028b", "a\x1b[31mred", "x" * 201]:
        code, _out, err, hub = _run(["send", "--channel", "telegram", "-s", bad, "hi"])
        assert code == EXIT_USAGE and "printable line" in err and hub.calls == []


def test_send_refuses_an_ntfy_title_the_adapter_would_mangle_but_not_elsewhere():
    code, _out, err, hub = _run(["send", "--channel", "ntfy", "-s", "Déploiement terminé ✓", "hi"])
    assert code == EXIT_USAGE and "ASCII" in err and hub.calls == []
    code, _out, err, hub = _run(["send", "--channel", "ntfy", "-s", "x" * 121, "hi"])
    assert code == EXIT_USAGE and "120" in err and hub.calls == []
    code, _out, _err, hub = _run(["send", "--channel", "telegram", "-s", "Déploiement terminé ✓", "hi"], hub=_FakeHub(_SENT))
    assert code == 0 and _posted(hub)[0][2]["subject"] == "Déploiement terminé ✓"


def test_send_refuses_a_body_over_the_carried_bound_before_any_request():
    """The bound is the seam's own: the subject counts where it becomes the first line, and
    not for ntfy, where it travels as a header."""
    code, _out, err, hub = _run(["send", "--channel", "ntfy", "x" * 4_001])
    assert code == EXIT_USAGE and "4,001" in err and "4,000" in err and hub.calls == []
    code, _out, err, hub = _run(["send", "--channel", "telegram", "-s", "[CI]", "x" * 3_998])
    assert code == EXIT_USAGE and "4,004" in err and "subject included" in err and hub.calls == []
    code, _out, _err, hub = _run(["send", "--channel", "ntfy", "-s", "[CI]", "x" * 3_998], hub=_FakeHub(_SENT))
    assert code == 0 and len(_posted(hub)) == 1
    hub = _FakeHub({
        "GET /api/channels/inbox/t1": {"thread": {"thread_id": "t1", "reply": {"channel": "telegram"}}},
    })
    code, _out, err, hub = _run(["send", "--to", "t1", "-s", "[CI]", "x" * 3_998], hub=hub)
    assert code == EXIT_USAGE and hub.calls == []


def test_send_quiet_prints_nothing_on_success_and_still_reports_failure():
    code, out, _err, _hub = _run(["send", "--channel", "ntfy", "-q", "hi"], hub=_FakeHub(_SENT))
    assert code == 0 and out == ""
    hub = _FakeHub({"POST /api/channels/send": {"ok": False, "error": "ntfy is not connected on this hub"}})
    code, out, err, _hub = _run(["send", "--channel", "ntfy", "-q", "hi"], hub=hub)
    assert code == EXIT_FAILED and out == "" and "not connected" in err
    hub = _FakeHub({
        "GET /api/channels/inbox/t1": {"thread": {"thread_id": "t1", "reply": {"channel": "telegram"}}},
        "POST /api/channels/inbox/t1/reply": {"ok": True, "queued": True, "task_id": 7},
    })
    code, out, _err, _hub = _run(["send", "--to", "t1", "-q", "hi"], hub=hub)
    assert code == 0 and out == ""


def test_send_puts_nothing_from_the_hub_or_the_shell_on_the_terminal_raw(tmp_path):
    """Reasons, senders, ids and the typed path are cleaned of control characters, as
    `nerva security audit` does with advisory text."""
    hub = _FakeHub({"POST /api/channels/send": {"ok": False, "error": "\x1b[31mforged\x1b[0m reason"}})
    code, _out, err, _hub = _run(["send", "--channel", "ntfy", "hi"], hub=hub)
    assert code == EXIT_FAILED and "\x1b" not in err and "forged" in err
    routes = {
        "GET /api/channels/targets": {"targets": [{"channel": "tele\x1b[31mgram", "ready": True, "reason": "\x07ok"}]},
        "GET /api/channels/inbox/status": {"enabled": True},
        "GET /api/channels/inbox?limit=200": {"threads": [{"thread_id": "t\x1b[2J1", "channel": "telegram", "from": "\x1b[Hbob"}]},
    }
    code, out, err, _hub = _run(["send", "--list"], hub=_FakeHub(routes))
    assert code == 0 and "\x1b" not in out + err and "\x07" not in out
    code, _out, err, _hub = _run(["send", "--list", "ntfy"], hub=_FakeHub(routes))
    assert code == EXIT_FAILED and "\x1b" not in err and "Configured: tele" in err
    code, _out, err, hub = _run(["send", "--channel", "ntfy", "-f", str(tmp_path / "no\x1b[31mpe.txt")])
    assert code == EXIT_USAGE and "\x1b" not in err and "cannot read" in err and hub.calls == []


def test_send_list_filters_by_channel_and_names_the_configured_ones_when_none_match():
    routes = {
        "GET /api/channels/targets": {"targets": [
            {"channel": "telegram", "ready": True, "reason": ""},
            {"channel": "ntfy", "ready": False, "reason": "ntfy is not connected on this hub"}]},
        "GET /api/channels/inbox/status": {"enabled": True},
        "GET /api/channels/inbox?limit=200": {"threads": [
            {"thread_id": "t1", "channel": "telegram", "from": "andrei"},
            {"thread_id": "t2", "channel": "ntfy", "from": "cron"}]},
    }
    code, out, _err, _hub = _run(["send", "--list", "ntfy"], hub=_FakeHub(routes))
    assert code == 0 and "--channel ntfy" in out and "--channel telegram" not in out
    assert "t2" in out and "t1" not in out
    # A name that can never be a direct-send channel is decided offline: usage, no request.
    code, _out, err, hub = _run(["send", "--list", "signal"], hub=_FakeHub(routes))
    assert code == EXIT_USAGE and "telegram, web, voice, ntfy" in err and hub.calls == []
    # A hub that does not list a real channel (older hub) is exit 1 and names what it lists.
    older = {**routes, "GET /api/channels/targets": {"targets": [{"channel": "telegram", "ready": True, "reason": ""}]}}
    code, _out, err, _hub = _run(["send", "--list", "ntfy"], hub=_FakeHub(older))
    assert code == EXIT_FAILED and "no targets found for channel 'ntfy'" in err and "Configured: telegram" in err
    for extra in (["-s", "x"], ["-f", "-"]):
        code, _out, err, hub = _run(["send", "--list", *extra], hub=_FakeHub(routes))
        assert code == EXIT_USAGE and hub.calls == []
    # A hub without /api/channels/targets at all: the filter is not silently dropped.
    no_targets = {k: v for k, v in routes.items() if "targets" not in k}
    code, out, err, _hub = _run(["send", "--list", "ntfy"], hub=_FakeHub(no_targets))
    assert code == 0 and "does not list send targets" in err and "t2" in out and "t1" not in out
    code, _out, err, _hub = _run(["send", "--list", "telegram"], hub=_FakeHub({
        **no_targets, "GET /api/channels/inbox?limit=200": {"threads": []}}))
    assert code == EXIT_FAILED and "no targets found for channel 'telegram'" in err


def test_send_list_says_so_in_one_human_line_when_nothing_is_ready():
    """Spark S-003: the empty state under a list where no channel is ready."""
    def routes(ready):
        return {
            "GET /api/channels/targets": {"targets": [
                {"channel": "telegram", "ready": ready, "reason": "" if ready else "no owner chat is configured"},
                {"channel": "ntfy", "ready": False, "reason": "ntfy is not connected on this hub"}]},
            "GET /api/channels/inbox/status": {"enabled": True},
            "GET /api/channels/inbox?limit=200": {"threads": []},
        }
    code, out, _err, _hub = _run(["send", "--list"], hub=_FakeHub(routes(False)))
    assert code == 0 and "none ready yet" in out and "connect one above" in out
    code, out, _err, _hub = _run(["send", "--list"], hub=_FakeHub(routes(True)))
    assert code == 0 and "none ready yet" not in out
    code, out, _err, _hub = _run(["send", "--list", "--json"], hub=_FakeHub(routes(False)))
    assert code == 0 and "none ready yet" not in out          # machine output stays machine output


def test_send_treats_a_blank_argument_as_no_message():
    """Hermes' precedence: a blank positional falls through to --file and stdin, never to the hub."""
    code, _out, err, hub = _run(["send", "--channel", "ntfy", "  "])
    assert code == EXIT_USAGE and "no message provided" in err and hub.calls == []
    code, _out, _err, hub = _run(["send", "--channel", "ntfy", ""], hub=_FakeHub(_SENT), stdin="from the pipe")
    assert code == 0 and _posted(hub)[0][2]["text"] == "from the pipe"


def test_send_list_shows_configured_destinations_as_well_as_threads():
    hub = _FakeHub({
        "GET /api/channels/targets": {"targets": [
            {"channel": "telegram", "ready": True, "reason": ""},
            {"channel": "ntfy", "ready": False, "reason": "ntfy is not connected on this hub"}]},
        "GET /api/channels/inbox/status": {"enabled": True},
        "GET /api/channels/inbox?limit=200": {"threads": []},
    })
    code, out, _err, _hub = _run(["send", "--list"], hub=hub)
    assert code == 0
    assert "--channel telegram" in out and "ready" in out
    assert "ntfy is not connected on this hub" in out


def test_jobs_advanced_cli_payloads():
    hub=_FakeHub({'POST /api/jobs':{'ok':True,'job':JOB},'PUT /api/jobs/x/notepad':{'ok':True},'GET /api/jobs/doctor':{'ok':True,'problems':[]},'GET /api/jobs/incidents':{},'POST /api/jobs/tick':{},'GET /api/jobs/x':{'job':JOB}})
    code,_,_,hub=_run(['jobs','create','--blueprint','reminder','--param','message=x','--options','{"repeat":2,"deliver":[]}'],hub)
    assert code==EXIT_OK and hub.calls[-1][2]['options']=={'repeat':2,'deliver':[]}
    for args,method,path in [(['doctor'],'GET','/api/jobs/doctor'),(['incidents'],'GET','/api/jobs/incidents'),(['tick'],'POST','/api/jobs/tick'),(['notepad','x','--text','memo'],'PUT','/api/jobs/x/notepad'),(['status','x'],'GET','/api/jobs/x')]:
        code,_,_,hub=_run(['jobs',*args],hub)
        assert code==EXIT_OK and hub.calls[-1][:2]==(method,path)


def test_jobs_run_pending_approval_is_an_accepted_request():
    hub = _FakeHub({'POST /api/jobs/x/run': {'ok': True, 'pending': True,
        'run': {'status': 'pending', 'summary': 'Awaiting this run approval'}}})
    code, out, _, _ = _run(['jobs', 'run', 'x'], hub)
    assert code == 0 and 'pending' in out


def test_manual_dispatch_acceptance_and_receipt_lookup():
    receipt = {'id':'r1', 'status':'queued', 'job_id':'j1', 'run':None}
    hub = _FakeHub({'POST /api/jobs/j1/run': {'ok':True, 'pending':True, 'request':receipt},
                    'GET /api/jobs/j1/requests/r1': {'request':receipt}})
    code, out, _, _ = _run(['jobs','run','j1'], hub)
    assert code == 0 and 'accepted' in out and 'r1' in out
    code, out, _, _ = _run(['jobs','status','j1','--request','r1'], hub)
    assert code == 0 and 'queued' in out


def test_jobs_model_provider_authored_options():
    hub = _FakeHub({'POST /api/jobs': {'ok': True, 'job': JOB}})
    code, _, _, hub = _run(['jobs', 'create', '--blueprint', 'inbox_watch',
                            '--options', '{"model":"org/model","provider":"lm-studio"}'], hub)
    assert code == EXIT_OK
    assert hub.calls[-1][2]['options'] == {'model':'org/model', 'provider':'lm-studio'}


def test_jobs_media_flag_authors_reminder_ids():
    hub = _FakeHub({'POST /api/jobs': {'ok': True, 'job': {'id':'mediajob','schedule_text':'daily','cron':'0 9 * * *','name':'report'}}})
    code, out, err, hub = _run(['jobs','create','--name','report','--when','daily','--action','{"type":"remind","message":"report"}', '--media-id','ba-'+'a'*32],hub)
    assert code == EXIT_OK, err
    assert hub.calls[-1][2]['action']['media_ids'] == ['ba-'+'a'*32]


def test_jobs_workdir_flag_requires_complete_options_and_can_clear():
    hub = _FakeHub({'POST /api/jobs': {'ok':True,'job':JOB}, 'PATCH /api/jobs/j1': {'ok':True,'job':JOB}})
    code, _, err, hub = _run(['jobs','create','--name','report','--when','daily','--action','{"type":"ask","prompt":"report"}', '--options','{"script":"watch.py","no_agent":true}', '--workdir','/workspace/report'],hub)
    assert code == EXIT_OK, err
    assert hub.calls[-1][2]['options']['workdir'] == '/workspace/report'
    code, _, err, hub = _run(['jobs','edit','j1','--options','{"script":"watch.py","no_agent":true,"workdir":"/old"}', '--workdir',''],hub)
    assert code == EXIT_OK, err
    assert 'workdir' not in hub.calls[-1][2]['options']


def test_jobs_workdir_does_not_replace_options_implicitly():
    hub = _FakeHub({})
    code, _, err, hub = _run(['jobs','edit','j1','--workdir','/workspace/report'],hub)
    assert code == EXIT_USAGE and 'complete --options' in err
    assert hub.calls == []


# ── security audit (H022) ─────────────────────────────────────────────────────


class _FakeOSV:
    """Enough of an OSV client for the verb: hits per (name, version), advisory bodies by id."""

    def __init__(self, hits=None, vulns=None, *, fail_batch=None):
        self.hits, self.vulns, self.fail_batch = hits or {}, vulns or {}, fail_batch
        self.calls = 0

    def query_batch(self, queries):
        from agents.core.security.dep_audit import OSVUnavailable

        self.calls += 1
        if self.fail_batch:
            raise OSVUnavailable(self.fail_batch)
        return [list(self.hits.get((q["package"]["name"], q["version"]), [])) for q in queries]

    def vulnerability(self, vuln_id):
        return self.vulns[vuln_id]


def _advisory(vid, package, severity, *, fixed=None, aliases=()):
    return {"id": vid, "aliases": list(aliases), "summary": "leaks credentials",
            "database_specific": {"severity": severity},
            "affected": [{"package": {"name": package, "ecosystem": "PyPI"},
                          "ranges": [{"type": "ECOSYSTEM",
                                      "events": [{"introduced": "0"}] + ([{"fixed": fixed}] if fixed else [])}]}]}


@pytest.fixture
def audited_box(monkeypatch):
    """One installed package with one HIGH advisory; the network is a fake."""
    from agents.core.security import dep_audit

    fake = _FakeOSV(hits={("pkg", "1.0"): ["GHSA-x"]},
                    vulns={"GHSA-x": _advisory("GHSA-x", "pkg", "HIGH", fixed="1.1", aliases=("CVE-2026-1",))})
    monkeypatch.setattr(dep_audit, "enumerate_installed",
                        lambda distributions=None: ([dep_audit.Component("installed", "pkg", "1.0", "importlib.metadata")], []))
    monkeypatch.setattr(dep_audit, "default_client", lambda url: fake)
    return fake


def test_security_audit_finds_the_advisory_and_says_what_left_the_machine(audited_box):
    from agents.cli.nerva import EXIT_UNAVAILABLE  # noqa: F401 - the ladder must expose it

    code, out, err, _hub = _run(["security", "audit"])
    assert code == EXIT_FAILED
    assert "HIGH" in out and "pkg 1.0" in out and "GHSA-x" in out and "CVE-2026-1" in out and "fixed in 1.1" in out
    assert "sending 1 package name+version pairs to api.osv.dev" in err and "nothing else leaves this machine" in err
    assert audited_box.calls == 1


def test_security_audit_threshold_and_ignore_change_the_verdict_not_the_listing(audited_box):
    code, out, _err, _hub = _run(["security", "audit", "--fail-on", "critical"])
    assert code == EXIT_OK and "GHSA-x" in out          # listed, below the bar
    code, out, _err, _hub = _run(["security", "audit", "--ignore-vuln", "cve-2026-1"])
    assert code == EXIT_OK and "ignored" in out and "GHSA-x" in out


def test_security_audit_json_is_the_machine_report(audited_box):
    code, out, _err, _hub = _run(["security", "audit", "--json"])
    payload = json.loads(out)
    assert code == EXIT_FAILED and payload["status"] == "findings"
    assert payload["surfaces"]["mcp"]["count"] == 0 and "HTTP" in payload["surfaces"]["mcp"]["reason"]
    assert payload["findings"][0]["id"] == "GHSA-x" and payload["findings"][0]["severity"] == "high"


def test_security_audit_offline_consults_nothing_and_is_exit_5(monkeypatch):
    from agents.cli.nerva import EXIT_UNAVAILABLE
    from agents.core.security import dep_audit

    monkeypatch.setattr(dep_audit, "default_client", lambda url: (_ for _ in ()).throw(AssertionError("no network in --offline")))
    code, out, err, _hub = _run(["security", "audit", "--offline"])
    assert code == EXIT_UNAVAILABLE
    assert "nothing is claimed" in out.lower() and "sending" not in err


def test_security_audit_unreachable_database_is_exit_5_never_clean(monkeypatch):
    from agents.cli.nerva import EXIT_UNAVAILABLE
    from agents.core.security import dep_audit

    monkeypatch.setattr(dep_audit, "default_client", lambda url: _FakeOSV(fail_batch="connection refused"))
    code, out, _err, _hub = _run(["security", "audit"])
    assert code == EXIT_UNAVAILABLE
    assert "could not consult" in out and "connection refused" in out and "nothing is claimed" in out.lower()
    assert "clean" not in out.lower()


def test_security_audit_refuses_a_non_https_database():
    code, _out, err, _hub = _run(["security", "audit", "--osv-url", "http://api.osv.dev"])
    assert code == EXIT_USAGE and "https" in err


def test_security_audit_reports_a_bad_descriptor_and_still_audits(audited_box, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    code, out, _err, _hub = _run(["security", "audit", "--json", "--extension", str(bad)])
    payload = json.loads(out)
    assert code == EXIT_FAILED
    assert payload["errors"] == [{"index": 0, "reason": "manifest_unreadable"}]
    assert str(tmp_path) not in out                       # descriptor paths are not echoed


def test_security_audit_names_a_skipped_distribution_without_changing_the_verdict(monkeypatch, audited_box):
    """A distribution whose metadata cannot be read is reported as skipped, not dropped."""
    from agents.core.security import dep_audit

    error = {"surface": "installed", "location": "bad-1.0.dist-info",
             "reason": "metadata_unreadable: UnicodeDecodeError"}
    monkeypatch.setattr(dep_audit, "enumerate_installed",
                        lambda distributions=None: ([dep_audit.Component("installed", "pkg", "1.0", "importlib.metadata")], [error]))
    code, out, _err, _hub = _run(["security", "audit", "--fail-on", "critical"])
    assert code == EXIT_OK
    assert "installed distribution bad-1.0.dist-info: metadata_unreadable: UnicodeDecodeError — skipped, not audited" in out
    code, out, _err, _hub = _run(["security", "audit", "--fail-on", "critical", "--json"])
    assert json.loads(out)["errors"] == [error]


def test_security_audit_that_cannot_complete_is_exit_5_not_a_findings_exit(monkeypatch, audited_box):
    """A crash inside the audit must not surface as Python's exit 1, which a script reads as findings."""
    from agents.cli.nerva import EXIT_UNAVAILABLE
    from agents.core.security import dep_audit

    def boom(distributions=None):
        raise RuntimeError("site-packages vanished")

    monkeypatch.setattr(dep_audit, "enumerate_installed", boom)
    code, out, err, _hub = _run(["security", "audit"])
    assert code == EXIT_UNAVAILABLE
    assert out == "" and "did not complete (RuntimeError)" in err and "nothing is claimed" in err
    assert "site-packages vanished" not in err                 # the message is not reflected


def test_jobs_create_prints_whether_a_first_run_was_queued():
    # H687 — the hub's confirmation names the first run (or the wait for the cadence).
    interval = {"id": "abc123abc123", "name": "Ask", "schedule_text": "every 2 hours", "cron": "0 */2 * * *"}
    queued = _FakeHub({"POST /api/jobs": {"ok": True, "job": interval, "first_run": {"status": "queued"},
                                          "confirmation": "first run now, then every 2 hours (0 */2 * * *)"}})
    code, out, _err, _hub = _run(["jobs", "create", "--blueprint", "ask_agent", "--param", "prompt=hi"], queued)
    assert code == EXIT_OK and "first run now, then every 2 hours (0 */2 * * *)" in out
    job = {"id": "abc123abc123", "name": "Ask", "schedule_text": "every weekday at 8:00", "cron": "0 8 * * 1-5"}
    # An older hub without the field still prints the schedule, as before.
    older = _FakeHub({"POST /api/jobs": {"ok": True, "job": job}})
    code, out, _err, _hub = _run(["jobs", "create", "--blueprint", "ask_agent", "--param", "prompt=hi"], older)
    assert code == EXIT_OK and "every weekday at 8:00 (0 8 * * 1-5)" in out
