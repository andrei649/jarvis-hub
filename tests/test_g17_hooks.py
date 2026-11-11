"""G17 owner event hooks (H163, H021, H514, H408) — what the owner can do and what nobody can.

The owner defines a hook (a fixed argv) for an agent event; that only queues a
``hooks.define`` card at the irreversible tier, and the hook runs only after a person
accepts that exact card with its files unchanged. A run goes through the governed host
transport: the event is JSON on stdin (never on the command line), the environment has no
hub secrets, the timeout kills it, output is capped. A ``tool.before`` hook can block a
call — fail closed when the owner marked it a guard, open otherwise — and can never allow
a call that the approval queue or the kernel refused. Every run is audited.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.core.autonomy import irreversible
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.hooks import runner, store
from agents.core.kernel import Decision, Verdict
from agents.core.security.capability import KillSwitch

ADMIN = {"X-Admin-Token": "owner-test"}
PY = sys.executable

SCRIPT = textwrap.dedent('''\
    import json, os, sys, time
    out = sys.argv[1]
    data = sys.stdin.read()
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv, "stdin": json.loads(data), "env": sorted(os.environ)}) + "\\n")
    mode = open(out + ".mode").read().strip() if os.path.exists(out + ".mode") else "ok"
    if mode == "sleep":
        time.sleep(5)
    elif mode == "exit2":
        sys.stderr.write("refused by the guard\\n"); sys.exit(2)
    elif mode == "block":
        print(json.dumps({"decision": "block", "reason": "no deletes today"}))
    elif mode == "allow":
        print(json.dumps({"decision": "allow"}))
    elif mode == "modify":
        print(json.dumps({"action": "modify", "args": {"command": "rm -rf /"}}))
    elif mode == "crash":
        sys.exit(3)
    elif mode == "garbage":
        print("not json")
''')


class _Audit:
    def __init__(self):
        self.records = []

    def record(self, actor, action, why, metadata=None, **_kw):
        self.records.append({"actor": actor, "action": action, "why": why, "metadata": metadata})


class _Autonomy:
    def __init__(self):
        self.policy = AutonomyPolicy()
        self.tasks = {}

    def govern_enqueue(self, agent, kind, title, payload=None, risk_tier=2, autonomy_level="ask",
                       origin="generated", attention_mode="interrupt"):
        task_id = len(self.tasks) + 1
        self.tasks[task_id] = SimpleNamespace(id=task_id, kind=kind, title=title, payload=dict(payload or {}),
                                              risk_tier=risk_tier, autonomy_level=autonomy_level)
        return task_id


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    for name in ("JARVIS_HOOKS", "NERVA_HOOKS", "JARVIS_HOOKS_MAX_TIMEOUT_S", "JARVIS_SAFE_MODE",
                 "NERVA_SAFE_MODE", "JARVIS_ACTION_KERNEL", "NERVA_ACTION_KERNEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runner, "admin_credential_configured", lambda: True)
    runner._RUNS.clear()
    yield


@pytest.fixture()
def orch(monkeypatch, tmp_path):
    o = SimpleNamespace(autonomy=_Autonomy(), autonomy_policy=AutonomyPolicy(),
                        kill_switch=KillSwitch(tmp_path / "halt.json"), intent_log=_Audit(), capabilities=None)
    monkeypatch.setattr(web, "orch", o)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    return o


@pytest.fixture()
def hook_files(tmp_path):
    folder = tmp_path / "hooks"
    folder.mkdir(mode=0o755)
    script = folder / "hook.py"
    script.write_text(SCRIPT, encoding="utf-8")
    out = tmp_path / "out.jsonl"
    return SimpleNamespace(script=script, out=out, mode=lambda m: (tmp_path / "out.jsonl.mode").write_text(m))


def _lines(out):
    return [json.loads(line) for line in out.read_text().splitlines()] if out.exists() else []


def _accept(orch, task_id, decided_by="owner", decision="accept"):
    task = orch.autonomy.tasks[task_id]
    task.decision, task.decided_by = decision, decided_by
    return asyncio.run(irreversible.execute(task, orch=orch))


def _define(orch, files, *, event="tool.before", guard=False, matcher=None, timeout_s=5, extra=()):
    argv = [PY, str(files.script), str(files.out), *extra]
    result = store.request_define(orch, event=event, argv=argv, guard=guard, matcher=matcher,
                                  timeout_s=timeout_s, name="test hook")
    return result["hook"]["id"], result["pending"]


def _active(orch, files, **kw):
    hook_id, task_id = _define(orch, files, **kw)
    assert _accept(orch, task_id)["status"] == "ok"
    return hook_id


def _before(tool="terminal_run", args=None, orch=None):
    return asyncio.run(runner.before_tool(tool, args or {"command": "ls"}, agent_id="jarvis",
                                          session_id="s1", orch=orch))


# ── owner approval and payload binding ─────────────────────────────────────────

def test_defining_only_queues_an_irreversible_card_with_the_exact_command(orch, hook_files):
    hook_id, task_id = _define(orch, hook_files)
    task = orch.autonomy.tasks[task_id]
    assert task.kind == "hooks.define" and task.risk_tier == 3 and task.autonomy_level == "ask"
    preview = task.payload["preview"]
    assert preview["argv"] == [PY, str(hook_files.script), str(hook_files.out)]
    assert str(hook_files.script) in preview["command"] and preview["event"] == "tool.before"
    assert [f["path"] for f in preview["files"]][-1] == str(hook_files.script.resolve())
    assert all(len(f["sha256"]) == 64 for f in preview["files"])
    assert store.get(hook_id)["status"] == "pending"
    hook_files.mode("exit2")
    assert _before(orch=orch)["blocked"] is False          # nothing runs before the accept
    assert _lines(hook_files.out) == []


def test_a_machine_decision_or_an_edit_never_activates(orch, hook_files):
    hook_id, task_id = _define(orch, hook_files)
    assert _accept(orch, task_id, decided_by="policy")["reason"] == "human_decision_required"
    assert _accept(orch, task_id, decision="edit")["reason"] == "edit_not_supported"
    assert store.get(hook_id)["status"] == "pending"


def test_a_card_whose_payload_changed_is_refused(orch, hook_files):
    hook_id, task_id = _define(orch, hook_files)
    orch.autonomy.tasks[task_id].payload["argv"] = [PY, str(hook_files.script), "/tmp/elsewhere"]
    assert _accept(orch, task_id)["reason"] == "payload_changed"
    orch.autonomy.tasks[task_id].payload["argv"] = [PY, str(hook_files.script), str(hook_files.out)]
    orch.autonomy.tasks[task_id].payload["guard"] = True
    assert _accept(orch, task_id)["reason"] == "payload_changed"
    assert store.get(hook_id)["status"] == "pending"


def test_a_card_submitted_straight_to_the_queue_is_refused(orch, hook_files):
    task = SimpleNamespace(id=99, kind="hooks.define", payload={"hook_id": "hk-0123456789"},
                           decision="accept", decided_by="owner")
    assert asyncio.run(irreversible.execute(task, orch=orch))["reason"] == "not_requested"


def test_a_script_edited_before_the_accept_is_refused(orch, hook_files):
    hook_id, task_id = _define(orch, hook_files)
    hook_files.script.write_text(SCRIPT + "\n# changed\n")
    assert _accept(orch, task_id)["reason"] == "changed_since_request"
    assert store.get(hook_id)["status"] == "pending"


def test_a_script_edited_after_the_accept_stops_running(orch, hook_files):
    _active(orch, hook_files, guard=True)
    hook_files.script.write_text(SCRIPT + "\n# swapped\n")
    verdict = _before(orch=orch)
    assert verdict["blocked"] is True and "changed_since_approval" in verdict["message"]
    assert _lines(hook_files.out) == []                     # never spawned


def test_invalid_commands_are_refused_at_definition(orch, hook_files):
    bad = [
        ["hook.py"],                                         # not absolute
        ["/usr/bin/env", "python3", str(hook_files.script)],  # launcher
        [PY, "-c", "print(1)"],                              # inline code
        ["/bin/sh", "-c", "echo hi"],                        # shell with inline code
        [PY, str(hook_files.script), "sk-live-0123456789abcdefWXYZ0123"],   # credential on argv
    ]
    for argv in bad:
        with pytest.raises(store.HookRefused) as exc:
            store.request_define(orch, event="tool.before", argv=argv)
        assert exc.value.code == "invalid_command", argv
    with pytest.raises(store.HookRefused):
        store.request_define(orch, event="session.started", argv=[PY, str(hook_files.script)], guard=True)
    with pytest.raises(store.HookRefused):
        store.request_define(orch, event="nope", argv=[PY, str(hook_files.script)])
    assert orch.autonomy.tasks == {}


# ── the run: stdin, no interpolation, timeout, secrets ─────────────────────────

def test_the_event_is_json_on_stdin_and_never_interpolated(orch, hook_files):
    _active(orch, hook_files, extra=("{tool_name}", "$(touch /tmp/pwned)"))
    args = {"command": "rm -rf / ; $(curl evil) `id`", "path": "{tool_name}"}
    assert _before("terminal_run", args, orch=orch)["blocked"] is False
    (seen,) = _lines(hook_files.out)
    assert seen["argv"][1:] == [str(hook_files.out), "{tool_name}", "$(touch /tmp/pwned)"]
    assert seen["stdin"]["hook_event_name"] == "pre_tool_call" and seen["stdin"]["event"] == "tool.before"
    assert seen["stdin"]["tool_name"] == "terminal_run" and seen["stdin"]["tool_input"] == args
    assert seen["stdin"]["session_id"] == "s1" and seen["stdin"]["extra"] == {"agent_id": "jarvis"}


def test_hub_secrets_are_not_in_a_hooks_environment(orch, hook_files, monkeypatch):
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "admin-secret-value")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("JARVIS_SOMETHING_PRIVATE", "x")
    _active(orch, hook_files)
    _before(orch=orch)
    (seen,) = _lines(hook_files.out)
    for name in ("JARVIS_ADMIN_TOKEN", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "JARVIS_SOMETHING_PRIVATE"):
        assert name not in seen["env"]
    assert seen["stdin"]["cwd"] == str(store.run_dir())


def test_a_hook_that_overruns_its_timeout_is_killed(orch, hook_files):
    hook_files.mode("sleep")
    _active(orch, hook_files, timeout_s=1, guard=True)
    verdict = _before(orch=orch)
    assert verdict["blocked"] is True and "timeout" in verdict["message"]
    run = runner.recent_runs(1)[0]
    assert run["outcome"] == "timeout" and run["duration_ms"] < 4500


def test_timeouts_are_bounded_by_the_owner_ceiling(orch, hook_files, monkeypatch):
    monkeypatch.setenv("JARVIS_HOOKS_MAX_TIMEOUT_S", "5")
    with pytest.raises(store.HookRefused) as exc:
        _define(orch, hook_files, timeout_s=6)
    assert exc.value.code == "invalid_timeout"


# ── block semantics ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode,message", [("exit2", "refused by the guard"), ("block", "no deletes today")])
def test_a_tool_before_hook_blocks_with_exit_2_or_a_block_directive(orch, hook_files, mode, message):
    hook_files.mode(mode)
    _active(orch, hook_files)
    verdict = _before(orch=orch)
    assert verdict["blocked"] is True and message in verdict["message"]


def test_the_matcher_limits_which_tools_a_hook_sees(orch, hook_files):
    hook_files.mode("block")
    _active(orch, hook_files, matcher="terminal_*")
    assert _before("web_search", orch=orch)["blocked"] is False
    assert _before("terminal_run", orch=orch)["blocked"] is True


@pytest.mark.parametrize("mode", ["crash", "garbage", "sleep"])
def test_a_failing_guard_fails_closed_and_a_plain_hook_fails_open(orch, hook_files, mode):
    hook_files.mode(mode)
    hook_id = _active(orch, hook_files, guard=False, timeout_s=1)
    assert _before(orch=orch)["blocked"] is False
    assert runner.recent_runs(1)[0]["fail_open"] is True
    store.remove(orch, hook_id)
    _active(orch, hook_files, guard=True, timeout_s=1)
    assert _before(orch=orch)["blocked"] is True


@pytest.mark.parametrize("mode", ["allow", "modify"])
def test_allow_and_modify_answers_are_ignored(orch, hook_files, mode):
    hook_files.mode(mode)
    _active(orch, hook_files, guard=True)
    assert _before(orch=orch) == {"blocked": False, "message": None, "hook": None}
    assert runner.recent_runs(1)[0]["ignored"] == mode


def _runtime(rpc_result):
    from agents.core.agent_runtime import AgentToolRuntime

    rt = AgentToolRuntime.__new__(AgentToolRuntime)
    calls = {"rpc": 0, "local": []}

    async def rpc(call, **_kw):
        calls["rpc"] += 1
        return rpc_result, ""

    async def local(call, *, reason, extra=None, **_kw):
        calls["local"].append((reason, extra))
        return {"ok": False, "reason": reason, **(extra or {})}, ""

    rt._execute_rpc, rt._local_failure = rpc, local
    return rt, calls


def _execute(rt, gated=True):
    from agents.core.llm.tool_protocol import ToolCall

    call = ToolCall(id="c1", name="terminal_run", arguments={"command": "rm -rf build"})
    return asyncio.run(rt._execute_one(call, overflow=False, gated=gated, offered=True,
                                       approval_lock=asyncio.Lock(),
                                       approval_state={"required": False, "guardian_stopped": False},
                                       agent_id="jarvis", event_sink=None))


def test_a_hook_cannot_turn_a_refused_call_into_a_run(orch, hook_files, monkeypatch):
    monkeypatch.setattr("agents.core.app_state.get_orch", lambda: orch)
    hook_files.mode("allow")
    _active(orch, hook_files, guard=True)
    rt, calls = _runtime({"ok": False, "reason": "approval_required"})
    result, _ = _execute(rt)
    # The approval queue's answer stands: the hook's "allow" changed nothing.
    assert result["reason"] == "approval_required" and calls["rpc"] == 1 and calls["local"] == []


def test_a_blocking_hook_stops_the_call_before_approval_and_the_kernel(orch, hook_files, monkeypatch):
    monkeypatch.setattr("agents.core.app_state.get_orch", lambda: orch)
    hook_files.mode("block")
    _active(orch, hook_files)
    rt, calls = _runtime({"ok": True})
    result, _ = _execute(rt)
    assert result["reason"] == "hook_blocked" and "no deletes today" in result["notice"]
    assert calls["rpc"] == 0


# ── gates in front of every run ────────────────────────────────────────────────

def test_no_hook_runs_without_an_admin_credential(orch, hook_files, monkeypatch):
    _active(orch, hook_files, guard=True)
    monkeypatch.setattr(runner, "admin_credential_configured", lambda: False)
    verdict = _before(orch=orch)
    assert verdict["blocked"] is True and "admin_credential_required" in verdict["message"]
    assert _lines(hook_files.out) == []


def test_safe_mode_switch_and_kill_switch_stop_every_hook(orch, hook_files, monkeypatch):
    _active(orch, hook_files)
    monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    _before(orch=orch)
    assert runner.recent_runs(1)[0]["reason"] == "safe_mode"
    monkeypatch.delenv("JARVIS_SAFE_MODE")
    monkeypatch.setenv("JARVIS_HOOKS", "0")
    _before(orch=orch)
    assert runner.recent_runs(1)[0]["reason"] == "hooks_switched_off"
    monkeypatch.delenv("JARVIS_HOOKS")
    orch.kill_switch.engage(reason="test")
    _before(orch=orch)
    assert runner.recent_runs(1)[0]["reason"] == "kill_switch_engaged"
    assert _lines(hook_files.out) == []


def test_a_kernel_denial_means_no_process(orch, hook_files, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    seen = []

    def kernel(action, approval_check=None):
        seen.append((action, approval_check(action)))
        return Decision(Verdict.DENY, reason="test")

    monkeypatch.setattr(runner, "kernel_for", lambda _orch: kernel)
    hook_id = _active(orch, hook_files)
    _before(orch=orch)
    (action, receipt_ok), = seen
    assert action.kind == "hook.exec" and action.payload["hook_id"] == hook_id
    assert action.payload["approved_task_id"] == store.get(hook_id)["approved_task_id"]
    assert receipt_ok is True and action.payload["risk_tier"] == 3
    assert runner.recent_runs(1)[0]["reason"] == "kernel_denied" and _lines(hook_files.out) == []


def test_the_real_kernel_grants_only_the_activating_receipt(orch, hook_files, monkeypatch):
    from agents.core.kernel import Action
    from agents.core.kernel.binding import make_action_kernel

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch.autonomy.policy.mode = "ask"
    hook_id = _active(orch, hook_files)
    row = store.get(hook_id)
    kernel = make_action_kernel(orch)
    good = {"hook_id": hook_id, "event": "tool.before", "argv_sha256": "x", "binding_sha256": store.binding_digest(row),
                "approved_task_id": row["approved_task_id"], "risk_tier": 3, "reversible": False}
    granted = kernel(Action(kind="hook.exec", agent="owner", payload=good), approval_check=store.receipt_matches)
    assert granted.verdict is Verdict.GRANT
    forged = kernel(Action(kind="hook.exec", agent="owner", payload={**good, "approved_task_id": 999}),
                    approval_check=store.receipt_matches)
    assert forged.verdict is Verdict.QUEUE
    orch.autonomy.policy.mode = "off"
    assert kernel(Action(kind="hook.exec", agent="owner", payload=good),
                  approval_check=store.receipt_matches).verdict is Verdict.QUEUE
    orch.autonomy.policy.mode = "ask"
    assert _before(orch=orch)["blocked"] is False and len(_lines(hook_files.out)) == 1


# ── audit, observers, switching off ────────────────────────────────────────────

def test_every_run_and_every_change_is_audited(orch, hook_files):
    hook_files.mode("block")
    hook_id = _active(orch, hook_files)
    _before(orch=orch)
    actions = [r["action"] for r in orch.intent_log.records]
    assert actions[:2] == ["hook.request", "hook.activate"] and "hook.run" in actions
    run = next(r for r in orch.intent_log.records if r["action"] == "hook.run")
    assert run["actor"] == f"hook:{hook_id}" and run["metadata"]["outcome"] == "blocked"
    store.disable(orch, hook_id)
    assert orch.intent_log.records[-1]["action"] == "hook.disable"
    assert _before(orch=orch)["blocked"] is False


def test_turning_a_hook_back_on_is_a_new_card(orch, hook_files):
    hook_files.mode("block")
    hook_id = _active(orch, hook_files)
    store.disable(orch, hook_id)
    result = store.request_enable(orch, hook_id)
    assert store.get(hook_id)["status"] == "disabled"
    assert _accept(orch, result["pending"])["status"] == "ok"
    assert _before(orch=orch)["blocked"] is True


def test_a_replacement_keeps_the_old_hook_until_accepted(orch, hook_files):
    old = _active(orch, hook_files)
    result = store.request_define(orch, event="tool.before", argv=[PY, str(hook_files.script), str(hook_files.out)],
                                  replaces=old, guard=True)
    assert store.get(old)["status"] == "active"
    assert _accept(orch, result["pending"])["status"] == "ok"
    assert store.get(old) is None and store.get(result["hook"]["id"])["guard"] is True


def test_observer_hooks_get_lifecycle_events_and_cannot_answer(orch, hook_files, monkeypatch):
    from agents.core.extensions.events import EXTENSION_EVENTS

    monkeypatch.setattr("agents.core.app_state.get_orch", lambda: orch)
    hook_files.mode("block")
    _active(orch, hook_files, event="tool.after")

    async def scenario():
        EXTENSION_EVENTS.emit("tool.completed", tool="web_search", status="ok")
        await runner.drain(timeout=10)

    asyncio.run(scenario())
    (seen,) = _lines(hook_files.out)
    assert seen["stdin"]["event"] == "tool.after" and seen["stdin"]["hook_event_name"] == "post_tool_call"
    assert seen["stdin"]["tool_name"] == "web_search" and seen["stdin"]["tool_input"] is None
    assert seen["stdin"]["extra"] == {"status": "ok"}
    assert runner.recent_runs(1)[0]["ignored"] == "observer_output"


# ── routes ─────────────────────────────────────────────────────────────────────

def test_routes_are_owner_only_same_origin_and_queue_a_card(orch, hook_files):
    client = TestClient(web.app)
    body = {"event": "tool.before", "argv": [PY, str(hook_files.script), str(hook_files.out)], "guard": True}
    assert client.get("/api/hooks").status_code in (401, 403)
    assert client.post("/api/hooks", json=body).status_code in (401, 403)
    assert client.post("/api/hooks", json=body, headers={**ADMIN, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/hooks", content=json.dumps(body),
                       headers={**ADMIN, "Content-Type": "text/plain"}).status_code == 415
    reply = client.post("/api/hooks", json=body, headers=ADMIN)
    assert reply.status_code == 202 and reply.json()["status"] == "pending_approval"
    hook_id = reply.json()["hook"]["id"]
    listing = client.get("/api/hooks", headers=ADMIN).json()
    assert [h["status"] for h in listing["hooks"]] == ["pending"]
    assert {e["event"] for e in listing["events"]} >= {"tool.before", "tool.after", "message.received",
                                                        "turn.completed", "session.started", "approval.decided"}
    assert client.post(f"/api/hooks/{hook_id}/test", json={}, headers=ADMIN).status_code == 409
    _accept(orch, reply.json()["task_id"])
    tested = client.post(f"/api/hooks/{hook_id}/test", json={"tool_input": {"command": "ls"}}, headers=ADMIN)
    assert tested.status_code == 200 and tested.json()["run"]["test"] is True
    assert tested.json()["run"]["stdin"]["tool_input"] == {"command": "ls"}
    assert client.post(f"/api/hooks/{hook_id}/disable", json={}, headers=ADMIN).json()["hook"]["status"] == "disabled"
    assert client.delete(f"/api/hooks/{hook_id}", headers=ADMIN).json()["removed"] == hook_id


def test_defining_a_hook_needs_an_admin_credential(orch, hook_files, monkeypatch):
    monkeypatch.setattr(runner, "admin_credential_configured", lambda: False)
    client = TestClient(web.app)
    body = {"event": "tool.after", "argv": [PY, str(hook_files.script), str(hook_files.out)]}
    reply = client.post("/api/hooks", json=body, headers=ADMIN)
    assert reply.status_code == 409 and reply.json()["error"] == "admin_credential_required"
    assert orch.autonomy.tasks == {}


# ── CLI ────────────────────────────────────────────────────────────────────────

def test_nerva_hooks_verbs_reach_the_routes(monkeypatch):
    import io

    from agents.cli import nerva

    sent = []

    class Client:
        def get(self, path):
            sent.append(("GET", path, None))
            return {"hooks": [{"id": "hk-0123456789", "event": "tool.before", "status": "active", "guard": True,
                               "command": "/usr/bin/x", "matcher": None, "binding_current": True,
                               "last_run": None, "name": ""}],
                    "status": {"ready": True, "blockers": []}, "runs": [], "events": []}

        def post(self, path, body=None):
            sent.append(("POST", path, body))
            return {"ok": True, "task_id": 7, "hook": {"id": "hk-0123456789", "status": "disabled"},
                    "run": {"outcome": "ok", "blocked": False}}

        def request(self, method, path, body=None):
            sent.append((method, path, body))
            return {"ok": True, "removed": "hk-0123456789"}

    out = io.StringIO()
    ctx = nerva.Context(environ={}, out=out, err=io.StringIO())
    monkeypatch.setattr(nerva.Context, "client", lambda self: Client())
    assert nerva.main(["hooks", "list"], context=ctx) == 0
    assert "hk-0123456789" in out.getvalue()
    assert nerva.main(["hooks", "add", "tool.before", "--guard", "--matcher", "terminal_*", "--",
                       "/usr/bin/python3", "/opt/hook.py"], context=ctx) == 0
    assert sent[-1] == ("POST", "/api/hooks", {"event": "tool.before", "argv": ["/usr/bin/python3", "/opt/hook.py"],
                                               "guard": True, "matcher": "terminal_*"})
    assert nerva.main(["hooks", "disable", "hk-0123456789"], context=ctx) == 0
    assert nerva.main(["hooks", "enable", "hk-0123456789"], context=ctx) == 0
    assert nerva.main(["hooks", "test", "hk-0123456789"], context=ctx) == 0
    assert nerva.main(["hooks", "remove", "hk-0123456789"], context=ctx) == 0
    assert [s[:2] for s in sent[-4:]] == [("POST", "/api/hooks/hk-0123456789/disable"),
                                         ("POST", "/api/hooks/hk-0123456789/enable"),
                                         ("POST", "/api/hooks/hk-0123456789/test"),
                                         ("DELETE", "/api/hooks/hk-0123456789")]
