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


def _run(argv, hub=None, environ=None):
    out, err = io.StringIO(), io.StringIO()
    hub = hub if hub is not None else _FakeHub()
    ctx = Context(environ=dict(environ or {}), out=out, err=err, client_factory=lambda env: hub)
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
        "doctor", "extensions", "status", "config", "approvals", "kernel", "tools", "logs", "estop", "jobs", "sessions", "chat", "send", "completion",
    }
    # S2 added the two owner acts an extension needs: agree to what a descriptor
    # declares, and prove it in the sandbox. `doctor` and `list` stay read-only.
    assert tree["extensions"] == ["activate", "consent", "doctor", "list"]
    assert tree["config"] == ["check", "get", "list", "set"]
    assert tree["approvals"] == ["accept", "defer", "edit", "list", "reject"]
    assert tree["kernel"] == ["explain"]
    assert tree["estop"] == ["engage", "resume", "status"]


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
    assert code == EXIT_AUTH and "JARVIS_ADMIN_TOKEN" in err and "token_store issue admin" in err


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
    assert code == EXIT_OK and "llm.tool_loop_max_iterations = 12  (number)" in out

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
        (r for r in settings_db.DEFAULTS if "token" in r["key"] or "key" in r["key"] or r["kind"] in ("secret", "password")),
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
    assert command_tree()["jobs"] == ["blueprints", "create", "delete", "edit", "list", "pause", "resume", "run", "runs"]
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
    code, _out, err, hub = _run(["send", "--channel", "telegram"])
    assert code == EXIT_USAGE and "1-4,000" in err
    assert hub.calls == []


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
