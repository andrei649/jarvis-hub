"""G2/G3 — session commands: /plan (H668), /loop (H460, H578), the /btw fork (H669) and
the context meter, /context and /compress (H412).

Written from the owner's side (what the owner can do) and the attacker's (what a
non-owner, a model's arguments or a forged payload cannot). Hermetic: orchestrator
doubles, loopback backend doubles, no model, no network.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import cost_tracker, estop
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.commands import Principal, build_default_registry
from agents.core.kernel import Action, Verdict, authorize, plan_mode
from agents.core.llm.request_context import session_scope
from agents.core.security.capability import KillSwitch

REPO = Path(__file__).resolve().parent.parent
OWNER = Principal(channel="web", sender="owner", admin=True)
GUEST = Principal(channel="telegram", sender="7", admin=False)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """A private data root, plan-mode store, loop store and cost ledger per test."""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    previous = plan_mode.set_default_store(plan_mode.PlanModeStore(tmp_path / "plan_mode.json"))
    from agents.core.session_meta import SessionMetaStore
    from agents.vendor.hermes_compat import goals as compat_goals
    from agents.vendor.hermes_compat import loops_config

    compat_goals.set_session_db(SessionMetaStore(tmp_path / "session_meta.json"))
    loops_config.set_loops_overrides({})
    monkeypatch.setattr(cost_tracker, "_store_path", lambda: tmp_path / "cost_usage.json")
    cost_tracker.reset()
    estop.disengage()
    yield tmp_path
    estop.disengage()
    cost_tracker.reset()
    plan_mode.set_default_store(previous)
    compat_goals.set_session_db(None)
    compat_goals.set_goal_probe(None)


def _kernel(**extra):
    return lambda action: authorize(action, policy=AutonomyPolicy(), **extra)


# ── plan mode: the kernel floor ──────────────────────────────────────────────────────


def _enter(session="s-plan"):
    plan_mode.default_store().enter(session, owner=True, by="web:owner", task="the trip")


@pytest.mark.parametrize("kind", ["terminal.exec", "file.write", "call.outbound", "social.post",
                                  "payment", "kg.write", "channel.reply", "writeback.email",
                                  "browser.step", "tool.rpc", "house.control"])
def test_plan_mode_denies_writes_sends_and_exec_at_the_kernel(kind):
    _enter()
    with session_scope("s-plan"):
        decision = _kernel()(Action(kind=kind, payload={"risk_tier": 0}))
    assert decision.verdict is Verdict.DENY and decision.reason.startswith("plan mode")


@pytest.mark.parametrize("kind", ["research", "search.web", "memory.read", "status.check", "list.files"])
def test_plan_mode_lets_reads_through_to_the_ordinary_gates(kind):
    _enter()
    with session_scope("s-plan"):
        decision = _kernel()(Action(kind=kind))
    assert decision.verdict is Verdict.GRANT


def test_a_payload_cannot_make_a_write_a_read_and_egress_reads_only_get():
    _enter()
    with session_scope("s-plan"):
        forged = _kernel()(Action(kind="file.write", payload={"risk_tier": "READ_ONLY", "kind": "read"}))
        get = _kernel()(Action(kind="plugin.egress", payload={"method": "GET", "risk_tier": 0}))
        post = _kernel()(Action(kind="plugin.egress", payload={"method": "POST", "risk_tier": 0}))
    assert forged.verdict is Verdict.DENY
    assert get.verdict is not Verdict.DENY or not get.reason.startswith("plan mode")
    assert post.verdict is Verdict.DENY and post.reason.startswith("plan mode")


def test_plan_mode_only_restricts_another_session_and_no_session_are_unchanged():
    _enter("s-plan")
    action = Action(kind="call.outbound", payload={"risk_tier": 2})
    baseline = _kernel()(action)
    with session_scope("s-other"):
        other = _kernel()(action)
    assert other.verdict is baseline.verdict and _kernel()(action).verdict is baseline.verdict


def test_plan_mode_never_grants_what_the_kill_switch_denies(tmp_path):
    _enter()
    switch = KillSwitch(tmp_path / "kill.json")
    switch.engage(reason="test")
    with session_scope("s-plan"):
        decision = _kernel(kill_switch=switch)(Action(kind="research"))
    assert decision.verdict is Verdict.DENY and "kill-switch" in decision.reason


def test_plan_mode_survives_a_restart_and_an_unreadable_state_fails_closed(tmp_path):
    _enter()
    reopened = plan_mode.PlanModeStore(tmp_path / "plan_mode.json")     # a new process
    assert reopened.is_active("s-plan") and not reopened.is_active("s-other")
    (tmp_path / "plan_mode.json").write_text("{not json", encoding="utf-8")
    assert reopened.is_active("s-other")                                 # every session held
    with session_scope("s-other"):
        assert _kernel()(Action(kind="file.write")).verdict is Verdict.DENY
    assert reopened.exit("s-other", owner=True, by="web:owner") is True  # the owner's way out
    assert not reopened.is_active("s-other")


def test_only_the_owner_enters_or_leaves_plan_mode():
    store = plan_mode.default_store()
    with pytest.raises(plan_mode.PlanModeRefused):
        store.enter("s-plan", owner=False, by="telegram:7")
    _enter()
    with pytest.raises(plan_mode.PlanModeRefused):
        store.exit("s-plan", owner=False, by="telegram:7")
    with pytest.raises(plan_mode.PlanModeRefused):
        store.exit("s-plan", owner="yes", by="telegram:7")               # truthy is not the owner
    assert store.is_active("s-plan")


# ── plan mode: the tool front door, with the kernel off ──────────────────────────────


async def test_plan_mode_refuses_gated_and_undeclared_tools_before_any_card():
    from agents.core.capability_manifests import RollbackContract
    from agents.core.tool_rpc import ToolRPCServer

    queued, ran = [], []

    async def handler(args):
        ran.append(args)
        return {"ok": True}

    server = ToolRPCServer(enqueue=lambda *a, **k: queued.append(a) or 7)
    server.register_tool("send_mail", handler, gated=True)
    server.register_tool("note_write", handler, risk="reversible",
                         rollback=RollbackContract(mode="restore", description="undo the note"))
    server.register_tool("mystery", handler)
    server.register_tool("read_notes", handler, risk="read_only")
    _enter()
    with session_scope("s-plan"):
        for name in ("send_mail", "note_write", "mystery"):
            answer = await server.handle({"tool": name, "args": {}})
            assert answer["ok"] is False and answer["reason"] == "plan_mode", name
        assert (await server.handle({"tool": "read_notes", "args": {}}))["ok"] is True
    assert queued == [] and len(ran) == 1
    # Leaving plan mode is all it takes to get the ordinary behaviour back.
    plan_mode.default_store().exit("s-plan", owner=True, by="web:owner")
    with session_scope("s-plan"):
        assert (await server.handle({"tool": "send_mail", "args": {}}))["reason"] == "approval_required"


# ── /plan, the command ───────────────────────────────────────────────────────────────


def _plan_orch(session="s-plan"):
    return SimpleNamespace(commands=build_default_registry(), session_id=session, intent_log=None)


async def test_plan_command_enters_plan_mode_and_continues_the_turn_with_the_adopted_prompt():
    from agents.vendor.hermes.agent.plan_prompt import build_plan_prompt

    orch = _plan_orch()
    outcome = await orch.commands.dispatch("/plan add a dark mode toggle", orch=orch, principal=OWNER)
    assert outcome.status == "continue"
    prompt = outcome.continuation.prompt
    assert prompt.startswith(build_plan_prompt("add a dark mode toggle"))
    assert "Nerva saves your reply as the plan file" in prompt
    assert plan_mode.default_store().is_active("s-plan")
    status = await orch.commands.dispatch("/plan status", orch=orch, principal=OWNER)
    assert "Plan mode is ON" in status.reply
    off = await orch.commands.dispatch("/plan off", orch=orch, principal=OWNER)
    assert off.reply.startswith("Plan mode is off") and not plan_mode.default_store().is_active("s-plan")


async def test_a_non_owner_cannot_enter_or_leave_plan_mode_by_command():
    orch = _plan_orch()
    refused = await orch.commands.dispatch("/plan do it", orch=orch, principal=GUEST)
    assert refused.status == "refused" and not plan_mode.default_store().is_active("s-plan")
    _enter()
    refused = await orch.commands.dispatch("/plan off", orch=orch, principal=GUEST)
    assert refused.status == "refused" and plan_mode.default_store().is_active("s-plan")


async def test_the_plan_turns_reply_is_saved_by_the_hub_in_the_plans_folder(tmp_path):
    from agents.core import plan_commands

    orch = _plan_orch()
    outcome = await orch.commands.dispatch("/plan migrate the db", orch=orch, principal=OWNER)
    path = Path(outcome.continuation.path)
    assert path.parent == plan_commands.plans_dir() and path.suffix == ".md"
    plan_commands.begin_plan_turn("s-plan", str(path))
    saved = await plan_commands.finish_plan_turn("s-plan", "# Plan\n\n1. back up\n2. migrate")
    assert saved == str(path) and path.read_text(encoding="utf-8").startswith("# Plan")
    assert str(path) in plan_mode.default_store().state("s-plan")["plans"]
    # Nothing is saved for another session, an unmarked turn, or outside the plans folder.
    plan_commands.begin_plan_turn("s-plan", str(tmp_path / "evil.md"))
    assert await plan_commands.finish_plan_turn("s-plan", "x") is None
    assert await plan_commands.finish_plan_turn("s-plan", "x") is None


def test_the_adopted_plan_prompt_is_byte_identical_with_the_manifest():
    manifest = json.loads((REPO / "agents/vendor/hermes/MANIFEST.json").read_text(encoding="utf-8"))
    rows = {row["path"]: row for row in manifest["files"]}
    row = rows["agent/plan_prompt.py"]
    data = (REPO / "agents/vendor/hermes/agent/plan_prompt.py").read_bytes()
    assert row["rules_applied"] == []
    assert hashlib.sha256(data).hexdigest() == row["vendored_sha256"] == row["upstream_sha256"]
    loops = rows["hermes_cli/loops.py"]
    assert sorted(loops["rules_applied"]) == ["hermes-cli-config", "hermes-cli-goals"]
    assert hashlib.sha256((REPO / "agents/vendor/hermes/hermes_cli/loops.py").read_bytes()).hexdigest() \
        == loops["vendored_sha256"]


# ── /loop ────────────────────────────────────────────────────────────────────────────


class _LoopOrch(SimpleNamespace):
    def __init__(self, replies, tmp_path, **kw):
        written, prompts = [], []

        class Memory:
            async def add_turn(self, *args, **kwargs):
                written.append(args)

            async def get_history(self, *a, **k):
                return []

        async def handle_input(text, channel="voice", agent_override=None, session_id=None):
            from agents.core.orchestrator import current_principal

            prompts.append((text, channel, session_id, current_principal()))
            return replies.pop(0) if replies else "nothing changed"

        super().__init__(commands=build_default_registry(), session_id="s-loop", memory=Memory(),
                         handle_input=handle_input, intent_log=None, llm_router=None,
                         turn_holders=lambda: [], work_runs=None,
                         kill_switch=KillSwitch(tmp_path / "kill.json"),
                         autonomy_policy=AutonomyPolicy(), written=written, prompts=prompts, **kw)


def _due(session="s-loop"):
    from agents.core.session_loops import _loops

    manager = _loops().LoopManager(session)
    manager.state.next_due_at = 0.0
    manager._save()
    return manager


async def _set(orch, text):
    return await orch.commands.dispatch(text, orch=orch, principal=OWNER)


async def test_loop_is_an_owner_command_and_its_state_survives_a_restart(_isolated):
    from agents.core.session_loops import _loops

    orch = _LoopOrch([], _isolated)
    guest = await orch.commands.dispatch("/loop 5m check the deploy", orch=orch, principal=GUEST)
    assert guest.status == "refused"
    out = await _set(orch, "/loop 5m check the deploy --times 3")
    assert "Loop set (every 5m)" in out.reply and "Action Kernel" in out.reply
    reopened = _loops().LoopManager("s-loop")                            # a new process
    assert reopened.is_active() and reopened.state.times == 3
    assert reopened.state.route["channel"] == "web"
    alias = await _set(orch, "/proactive status")
    assert "Loop (active" in alias.reply


async def test_each_tick_runs_as_an_owner_turn_and_self_paced_backs_off_then_snaps_back(_isolated):
    from agents.core.session_loops import run_tick

    orch = _LoopOrch(["queue: 3 items", "queue: 3 items", "queue: 3 items", "queue: 1 item"], _isolated)
    await _set(orch, "/loop watch the queue")
    delays = []
    for _ in range(4):
        _due()
        result = await run_tick(orch, "s-loop")
        assert result["ran"] and result["status"] == "active"
        from agents.core.session_loops import _loops

        delays.append(_loops().LoopManager("s-loop").state.current_delay)
    assert delays == [60.0, 120.0, 240.0, 60.0]          # doubles while unchanged, snaps back
    text, channel, session, principal = orch.prompts[0]
    assert text.startswith("[/loop wakeup #1, self-paced]") and "LOOP_COMPLETE" in text
    assert channel == "web" and session == "s-loop" and principal.admin is True


async def test_loop_complete_and_times_stop_the_loop(_isolated):
    from agents.core.session_loops import _loops, run_tick

    orch = _LoopOrch(["all green\nLOOP_COMPLETE"], _isolated)
    await _set(orch, "/loop 1m poll CI")
    _due()
    result = await run_tick(orch, "s-loop")
    assert result["stopped"] and result["status"] == "done"
    assert _loops().LoopManager("s-loop").state.status == "done"
    orch = _LoopOrch(["a", "b"], _isolated)
    await _set(orch, "/loop 1m poll CI --times 2")
    for _ in range(2):
        _due()
        result = await run_tick(orch, "s-loop")
    assert result["stopped"] and "2 runs" in result["reason"]


async def test_the_until_judge_stops_the_loop_and_a_missing_judge_fails_open(_isolated, monkeypatch):
    from agents.core import session_loops

    orch = _LoopOrch(["queue empty", "queue empty"], _isolated)
    await _set(orch, "/loop 1m watch the queue --until the queue is empty")
    _due()
    result = await session_loops.run_tick(orch, "s-loop")      # no model: continue (fail-open)
    assert result["ran"] and not result["stopped"]

    async def judge(_orch, until, reply):
        return "done", "the report shows an empty queue"

    monkeypatch.setattr(session_loops, "_judge", judge)
    _due()
    result = await session_loops.run_tick(orch, "s-loop")
    assert result["stopped"] and "stop condition met" in result["reason"]


async def test_the_e_stop_pauses_every_loop_and_resume_continues_it(_isolated):
    from agents.core.session_loops import _loops, run_tick

    orch = _LoopOrch([], _isolated)
    await _set(orch, "/loop 1m check")
    _due()
    estop.engage("test")
    result = await run_tick(orch, "s-loop")
    assert result == {"ran": False, "why": "estop"} and orch.prompts == []
    state = _loops().LoopManager("s-loop").state
    assert state.status == "paused" and state.paused_reason == "e-stop engaged"
    estop.disengage()
    assert "Loop resumed" in (await _set(orch, "/loop resume")).reply
    _due()
    assert (await run_tick(orch, "s-loop"))["ran"]


async def test_stop_command_kill_switch_budget_and_plan_mode_stop_or_pause_ticks(_isolated):
    from agents.core.session_loops import _loops, run_tick

    orch = _LoopOrch([], _isolated)
    await _set(orch, "/loop 1m check")
    assert "Loop stopped" in (await _set(orch, "/loop stop")).reply
    assert await run_tick(orch, "s-loop") == {"ran": False, "why": "not_due"}

    await _set(orch, "/loop 1m check")
    _due()
    orch.kill_switch.engage(reason="halt")
    result = await run_tick(orch, "s-loop")
    assert result["why"] == "kernel" and "kill-switch" in result["reason"] and orch.prompts == []
    orch.kill_switch.disengage()

    await _set(orch, "/loop 1m check")
    manager = _due()
    manager.state.ticks_fired = manager.state.max_ticks           # the backstop is spent
    manager._save()
    result = await run_tick(orch, "s-loop")
    assert result["why"] == "kernel" and "loop_ticks budget" in result["reason"]

    await _set(orch, "/loop 1m check")
    _due()
    _enter("s-loop")
    result = await run_tick(orch, "s-loop")
    assert result["why"] == "kernel" and result["reason"].startswith("plan mode")
    assert _loops().LoopManager("s-loop").state.status == "paused" and orch.prompts == []


async def test_with_the_kernel_on_every_tick_is_authorized_by_it(_isolated, monkeypatch):
    from agents.core import session_loops

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch = _LoopOrch(["a", "b"], _isolated)
    seen = []
    real = session_loops.tick_decision

    def spying(*args, **kwargs):
        allowed, reason = real(*args, **kwargs)
        seen.append(allowed)
        return allowed, reason

    monkeypatch.setattr(session_loops, "tick_decision", spying)
    await _set(orch, "/loop 1m check")
    for _ in range(2):
        _due()
        assert (await session_loops.run_tick(orch, "s-loop"))["ran"]
    assert seen == [True, True]
    orch.autonomy_policy.mode = "off"                     # approval mode off: nothing auto-runs
    _due()
    result = await session_loops.run_tick(orch, "s-loop")
    assert result["why"] == "kernel" and "approval mode" in result["reason"]


async def test_the_watcher_never_fires_mid_turn_and_no_hub_work_run_blocks_it(_isolated):
    from agents.core.session_loops import _loops, run_tick, scan

    orch = _LoopOrch([], _isolated)
    await _set(orch, "/loop 1m check")
    _due()
    orch.turn_holders = lambda: [{"session_id": "s-loop"}]
    assert await run_tick(orch, "s-loop") == {"ran": False, "why": "busy"}
    assert _loops().LoopManager("s-loop").is_due()                # left due
    orch.turn_holders = lambda: []
    # Review MINOR (b): a company-mode work run takes no turn in this conversation, so it
    # does not hold the loop back.
    run = SimpleNamespace(id="r1", barrier=None)
    orch.work_runs = SimpleNamespace(list_runs=lambda **k: [run])
    rows = await scan(orch)
    assert rows and rows[0]["ran"] is True


async def test_a_chat_loop_is_busy_while_its_route_holds_a_turn(_isolated):
    from agents.core.channels.session import SessionSource, build_session_key
    from agents.core.session_loops import run_tick

    orch = _LoopOrch([], _isolated, _channel_principal=_owner_judge({"42"}))
    tg = Principal(channel="telegram", sender="42", admin=True, chat="123")
    await orch.commands.dispatch("/loop 1m check", orch=orch, principal=tg)
    _due()
    base = build_session_key(SessionSource(channel="telegram", sender="42", thread_id="123"))
    orch.turn_holders = lambda: [{"session_id": base}]
    assert await run_tick(orch, "s-loop") == {"ran": False, "why": "busy"}


# ── /btw fork ────────────────────────────────────────────────────────────────────────


async def test_the_btw_fork_sends_no_tools_and_charges_the_parent_session(monkeypatch):
    from agents.core import turn_usage
    from agents.core.llm.providers import get_profile

    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return "You asked about Cluj."

    backend = SimpleNamespace(profile=get_profile("lm-studio"), base_url="http://127.0.0.1:1234",
                              generate=generate)
    router = SimpleNamespace(local_backend=backend, active_model="active-local", _backend=backend,
                             _local_model="active-local")

    class Collector:
        def snapshot(self):
            return {"api_calls": 1, "input_tokens": 1200, "output_tokens": 40, "model": "active-local"}

    @contextmanager
    def scope(**kwargs):
        yield Collector()

    monkeypatch.setattr(turn_usage, "turn_usage_scope", scope)

    class Memory:
        async def get_history(self, session_id, last_n=None):
            return [{"role": "user", "content": "plan Cluj"}, {"role": "assistant", "content": "ok"}]

    orch = SimpleNamespace(commands=build_default_registry(), llm_router=router, session_id="s-parent",
                           memory=Memory(), on_shared_session=lambda: False)
    outcome = await orch.commands.dispatch("/btw what did I ask?", orch=orch, principal=OWNER)
    assert outcome.reply == "You asked about Cluj."
    (call,) = calls
    assert "tools" not in call and "tool_choice" not in call
    usage = cost_tracker.session_usage("s-parent")
    assert usage["purposes"]["btw"]["input_tokens"] == 1200
    assert usage["purposes"]["btw"]["output_tokens"] == 40


# ── /context and /compress ───────────────────────────────────────────────────────────


def _meter_orch(turns, *, window=32_000):
    from agents.core.context_compressor import CompactionPolicy

    class Memory:
        async def get_history(self, session_id, last_n=None):
            return list(turns)

    return SimpleNamespace(
        commands=build_default_registry(), session_id="s-ctx", memory=Memory(),
        _compaction_model=lambda: "qwen2.5",
        _compaction_policy=lambda: CompactionPolicy(per_model={"qwen2.5": window}),
        _living_core_memory_block=lambda freeze=False: "Core memory: the owner lives in Cluj.",
        tool_rpc=SimpleNamespace(tools=lambda: [{"name": "file_read", "description": "read a file",
                                                 "input_schema": {"type": "object"}}]),
        skills=None, _usage_anchor=lambda n: None)


async def test_the_context_meter_numbers_add_up_and_read_the_compaction_policy():
    from agents.core.context_meter import CATEGORIES, GRID_CELLS, breakdown

    turns = [{"role": "user", "content": "hello " * 400},
             {"role": "assistant", "content": "data:image/png;base64,AAAA"},
             {"role": "user", "content": "look\n--- Attached Context ---\n" + "x" * 4000}]
    meter = await breakdown(_meter_orch(turns), "s-ctx")
    tokens = {row["name"]: row["tokens"] for row in meter["categories"]}
    assert list(tokens) == list(CATEGORIES)
    assert sum(tokens.values()) == meter["used"] and meter["used"] + meter["free"] == meter["window"]
    assert meter["window"] == 32_000                                       # the policy's window
    assert meter["thresholds"]["soft"] == int(0.6 * 32_000)
    assert all(tokens[name] > 0 for name in CATEGORIES if name != "skills")
    assert next(r for r in meter["categories"] if r["name"] == "attachments")["images"] == 1
    assert len(meter["grid"]) == GRID_CELLS


async def test_context_and_compress_commands_are_owner_only_and_report_the_tier():
    orch = _meter_orch([{"role": "user", "content": "hi"}])
    shown = await orch.commands.dispatch("/context", orch=orch, principal=OWNER)
    assert shown.status == "answered" and "Context:" in shown.reply and "history" in shown.reply
    assert (await orch.commands.dispatch("/context", orch=orch, principal=GUEST)).status == "refused"
    noop = await orch.commands.dispatch("/compress", orch=orch, principal=OWNER)
    assert noop.reply.splitlines()[1].startswith("No-op")
    big = _meter_orch([{"role": "user", "content": "w " * 60_000}], window=32_000)
    hard = await big.commands.dispatch("/compress", orch=big, principal=OWNER)
    assert "Above the hard tier" in hard.reply and "was not changed" in hard.reply


def test_the_grid_always_has_a_hundred_cells():
    from agents.core.context_meter import grid

    assert len(grid({"system": 10, "history": 999_999}, 1000)) == 100
    assert len(grid({"system": 1, "tools": 1, "history": 1}, 1_000_000)) == 100
    assert grid({}, 0) == ["free"] * 100


# ── /plan through the real orchestrator turn (web and stream) ────────────────────────


@pytest.mark.parametrize("stream", [False, True])
async def test_plan_turn_reaches_the_model_and_the_reply_is_saved(tmp_path, monkeypatch, stream):
    import types

    from agents.core import plan_commands
    from agents.core.orchestrator import Orchestrator
    from tests.test_h026_skill_bundles import _hub, _say

    orch, seen = _hub(tmp_path, monkeypatch)
    orch._complete_llm_turn = types.MethodType(Orchestrator._complete_llm_turn, orch)
    reply, notices = await _say(orch, "/plan add a dark mode toggle", stream=stream)
    assert len(seen.sent) == 1 and "[/plan — plan mode]" in seen.sent[0]
    assert "add a dark mode toggle" in seen.sent[0]
    assert plan_mode.default_store().is_active("s")
    saved = list(plan_commands.plans_dir().glob("*-add-a-dark-mode-toggle.md"))
    assert len(saved) == 1 and saved[0].read_text(encoding="utf-8").strip().endswith("answer")
    assert any(text.startswith("Plan saved:") for text in notices)
    # A guest's /plan never reaches the model and changes nothing.
    plan_mode.default_store().exit("s", owner=True, by="web:owner")
    reply, _ = await _say(orch, "/plan something", admin=False, stream=stream)
    assert len(seen.sent) == 1 and not plan_mode.default_store().is_active("s")


async def test_a_loop_set_on_telegram_pushes_each_wakeup_to_that_chat(_isolated):
    from agents.core.session_loops import run_tick

    sent = []

    async def send(channel, text, **kwargs):
        sent.append((channel, str(text), kwargs))
        return True

    orch = _LoopOrch(["deploy is green\nLOOP_COMPLETE"], _isolated,
                     channel_manager=SimpleNamespace(send=send), _channel_principal=_owner_judge({"42"}))
    telegram_owner = Principal(channel="telegram", sender="42", admin=True, chat="123")
    await orch.commands.dispatch("/loop 1m check the deploy", orch=orch, principal=telegram_owner)
    _due()
    result = await run_tick(orch, "s-loop")
    assert result["delivered"] is True
    assert sent[0][0] == "telegram" and sent[0][2]["chat_id"] == "123"
    assert "deploy is green" in sent[0][1]
    assert any("Loop finished" in text for _c, text, _k in sent[1:])
    _channel, _channel_name, _session, principal = orch.prompts[0]
    assert principal.channel == "telegram" and principal.chat == "123" and principal.admin


# ── review round: owner authority, budgets, migration, plan-mode reads, meter, fork ──


def _owner_judge(owners):
    """A stand-in for Orchestrator._channel_principal: admin only for a current owner id."""
    def judge(channel, sender, chat_id, chat_type=None):
        return Principal(channel=channel, sender=sender, admin=str(sender) in owners,
                         chat=None if chat_id is None else str(chat_id), scope="dm")

    return judge


async def test_a_tick_rechecks_the_owner_and_pauses_when_the_chat_is_no_longer_theirs(_isolated):
    """M1: the route saved at /loop time grants nothing; every tick asks the channel's
    owner check again, and a revoked owner pauses the loop before anything runs or is sent."""
    from agents.core.session_loops import _loops, run_tick

    owners = {"111"}
    sent = []

    async def send(channel, text, **kwargs):
        sent.append((channel, str(text), kwargs))
        return True

    orch = _LoopOrch(["inbox summary"], _isolated, channel_manager=SimpleNamespace(send=send),
                     _channel_principal=_owner_judge(owners))
    tg = Principal(channel="telegram", sender="111", admin=True, chat="111", scope="dm")
    await orch.commands.dispatch("/loop 1m summarize my inbox", orch=orch, principal=tg)
    owners.clear()                                     # the owner identity is revoked
    _due()
    result = await run_tick(orch, "s-loop")
    assert result["why"] == "owner" and "no longer confirmed" in result["reason"]
    assert orch.prompts == [] and not any("inbox summary" in text for _c, text, _k in sent)
    state = _loops().LoopManager("s-loop").state
    assert state.status == "paused" and "owner" in state.paused_reason
    # A channel without any owner check pauses too (fail closed).
    plain = _LoopOrch(["x"], _isolated)
    await plain.commands.dispatch("/loop 1m check", orch=plain, principal=tg)
    _due()
    assert (await run_tick(plain, "s-loop"))["why"] == "owner"


async def test_loop_is_refused_in_a_group(_isolated):
    orch = _LoopOrch([], _isolated)
    group = Principal(channel="telegram", sender="111", admin=True, chat="-100", scope="group")
    out = await orch.commands.dispatch("/loop 1m check", orch=orch, principal=group)
    assert "never in a group" in out.reply
    from agents.core.session_loops import _loops

    assert _loops().LoopManager("s-loop").state is None


async def test_resume_after_the_tick_cap_or_the_wall_budget_gets_a_fresh_allotment(_isolated):
    """M2: /loop resume after the tick cap or the 24 h budget runs ticks again."""
    import time as _time

    from agents.core.session_loops import _loops, run_tick

    orch = _LoopOrch(["x"] * 10, _isolated)
    await _set(orch, "/loop 1m check")
    manager = _due()
    manager.state.ticks_fired = manager.state.max_ticks
    manager._save()
    assert (await run_tick(orch, "s-loop"))["why"] == "kernel"           # the cap pauses it
    assert "Loop resumed" in (await _set(orch, "/loop resume")).reply
    _due()
    result = await run_tick(orch, "s-loop")
    assert result["ran"] and result["status"] == "active"

    await _set(orch, "/loop 1m check")
    from agents.core import session_loops

    session_loops._set_budget_since("s-loop", _time.time() - 25 * 3600)
    _due()
    assert "wall-time" in (await run_tick(orch, "s-loop"))["reason"]
    await _set(orch, "/loop resume")
    _due()
    assert (await run_tick(orch, "s-loop"))["ran"]
    assert _loops().LoopManager("s-loop").state.status == "active"


async def test_an_explicit_times_above_the_backstop_is_honoured(_isolated):
    from agents.core.session_loops import _loops

    orch = _LoopOrch([], _isolated)
    await _set(orch, "/loop 1m check --times 150")
    state = _loops().LoopManager("s-loop").state
    assert state.times == 150 and state.max_ticks == 150


async def test_loop_and_plan_mode_follow_the_conversation_to_a_new_session_id(_isolated):
    """MINOR (a): /undo, /new, /reset and a chat's rollover give the conversation a new id;
    its loop and plan mode move with it."""
    from agents.core.session_loops import _loops, migrate_session

    orch = _LoopOrch([], _isolated)
    await _set(orch, "/loop 5m check")
    _enter("s-loop")
    moved = migrate_session("s-loop", "s-next")
    assert moved == {"loop": True, "plan_mode": True}
    assert _loops().LoopManager("s-next").is_active()
    assert _loops().LoopManager("s-loop").state is None or \
        _loops().LoopManager("s-loop").state.status == "cleared"
    assert plan_mode.default_store().is_active("s-next")


async def test_undo_carries_the_loop_and_plan_mode(tmp_path, monkeypatch):
    from agents.core import session_loops
    from tests.test_h026_skill_bundles import _hub, _say

    orch, _seen = _hub(tmp_path, monkeypatch)
    moves = []
    monkeypatch.setattr(session_loops, "migrate_session", lambda old, new: moves.append((old, new)) or {})
    await orch.memory.add_turn("s", "user", "hello")
    await orch.memory.add_turn("s", "assistant", "hi")
    reply, _ = await _say(orch, "/undo")
    assert moves and moves[0][0] == "s" and moves[0][1] != "s", reply


def test_registered_kinds_are_reads_only_when_listed():
    """MINOR (d): a registered kind's name is never trusted; checkpoint.restore is not a read."""
    for kind in ("checkpoint.restore", "checkpoint.maintenance", "kanban.worker", "goal.approve",
                 "admin.kill_switch", "media.present", "host.control", "terminal.exec"):
        assert not plan_mode.kind_is_read(kind), kind
    assert plan_mode.kind_is_read("research")
    assert plan_mode.kind_is_read("memory.read") and not plan_mode.kind_is_read("memory.write")
    assert not plan_mode.kind_is_read("search.and.send")
    _enter()
    with session_scope("s-plan"):
        assert _kernel()(Action(kind="checkpoint.restore")).reason.startswith("plan mode")


async def test_slash_command_loops_are_not_judged_on_the_commands_output(_isolated, monkeypatch):
    from agents.core import session_loops
    from agents.core.session_loops import run_tick

    orch = _LoopOrch(["done\nLOOP_COMPLETE"], _isolated)
    seen = []
    real = session_loops._loops().LoopManager.complete_tick

    def spy(self, reply):
        seen.append(reply)
        return real(self, reply)

    monkeypatch.setattr(session_loops._loops().LoopManager, "complete_tick", spy)
    await _set(orch, "/loop 1m /recap")
    _due()
    result = await run_tick(orch, "s-loop")
    assert seen == [""] and result["status"] == "active"
    assert orch.prompts[0][0] == "/recap"


async def test_a_tick_that_raised_counts_and_a_cancelled_tick_does_not_wedge_the_loop(_isolated):
    import asyncio

    from agents.core.session_loops import _loops, run_tick

    orch = _LoopOrch([], _isolated)

    async def boom(*a, **k):
        raise RuntimeError("acted, then failed")

    orch.handle_input = boom
    await _set(orch, "/loop 1m check")
    _due()
    assert (await run_tick(orch, "s-loop"))["why"] == "turn_failed"
    state = _loops().LoopManager("s-loop").state
    assert state.ticks_fired == 1 and state.awaiting_response is False

    async def hang(*a, **k):
        await asyncio.sleep(30)

    orch.handle_input = hang
    _due()
    task = asyncio.ensure_future(run_tick(orch, "s-loop"))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    state = _loops().LoopManager("s-loop").state
    assert state.ticks_fired == 2 and state.awaiting_response is False


async def test_the_meter_measures_per_conversation_and_survives_an_unverified_history():
    from agents.core.context_meter import MeterUnavailable, breakdown
    from agents.core.memory.conversation import UnverifiedRewind

    orch = _meter_orch([{"role": "user", "content": "hi"}])
    orch._context_measured_by_session = {"s-other": (9999, 0)}
    assert (await breakdown(orch, "s-ctx"))["measured"] is None          # another session's count
    orch._context_measured_by_session["s-ctx"] = (1234, 1)
    assert (await breakdown(orch, "s-ctx"))["measured"] == 1234

    class Broken:
        async def get_history(self, *a, **k):
            raise UnverifiedRewind("unverified")

    orch.memory = Broken()
    with pytest.raises(MeterUnavailable):
        await breakdown(orch, "s-ctx")
    out = await orch.commands.dispatch("/context", orch=orch, principal=OWNER)
    assert out.status == "answered" and "could not run" in out.reply


async def test_the_btw_fork_budget_uses_the_backends_real_window():
    from agents.core.llm import auxiliary_text

    class Ollama:
        async def resolve_context_window(self, model):
            return 8_192

    router = SimpleNamespace(local_backend=Ollama(), active_model="qwen2.5")
    small = await auxiliary_text.resolve_btw_fork_budget(router)
    assert small < auxiliary_text.btw_fork_budget_chars(router)          # 8k, not the 32k family
    assert small == auxiliary_text.btw_fork_budget_chars(router, window=8_192)


async def test_a_failed_plan_turn_saves_nothing_and_a_same_second_name_gets_a_suffix(tmp_path):
    from agents.core import plan_commands

    _enter()
    path = plan_commands.plans_dir() / "2026-11-10_120000-same.md"
    plan_commands.begin_plan_turn("s-plan", str(path))
    assert await plan_commands.finish_plan_turn("s-plan", "error text", failed=True) is None
    assert await plan_commands.finish_plan_turn("s-plan", "# later") is None    # mark cleared
    for expected in (path, path.with_name("2026-11-10_120000-same-2.md")):
        plan_commands.begin_plan_turn("s-plan", str(path))
        assert await plan_commands.finish_plan_turn("s-plan", "# plan") == str(expected)
