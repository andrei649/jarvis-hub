"""Pinned Hermes Kanban CLI through Nerva's scoped, durable board."""

import argparse
import asyncio
import json
from types import SimpleNamespace

import pytest

from agents.core.kanban.cli import execute_command
from agents.core.kanban.cli_parser import build_parser
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.runtime import delegate_scope
from agents.core.kanban.upstream import kanban_db as kb

OWNER = SimpleNamespace(channel="web", admin=True)


def _orch():
    return SimpleNamespace(get_setting=lambda key, default=None: key == "llm.kanban")


def test_parser_keeps_pinned_nested_tree():
    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers(dest="top"))
    for argv, action, nested in (
        (["kanban", "boards", "create", "alpha"], "boards", "create"),
        (["kanban", "create", "Card", "--triage"], "create", None),
        (["kanban", "request-review", "T1"], "request-review", None),
        (["kanban", "notify-subscribe", "T1", "--platform", "telegram", "--chat-id", "42"], "notify-subscribe", None),
    ):
        ns = parser.parse_args(argv)
        assert ns.kanban_action == action
        if nested:
            assert ns.boards_action == nested


@pytest.mark.asyncio
async def test_durable_owner_lifecycle_and_board_scope(tmp_path):
    orch = _orch()
    with kanban_scope(KanbanContext(tmp_path, "owner", can_mutate=True)):
        made = await execute_command(orch, ["create", "First", "--triage", "--json"], OWNER)
        assert made["ok"], made
        import json
        tid = json.loads(made["output"])["id"]
        commented = await execute_command(orch, ["comment", tid, "evidence", "here", "--author", "spoof"], OWNER)
        assert commented["ok"], commented
        shown = await execute_command(orch, ["show", tid, "--json"], OWNER)
        assert shown["ok"] and "evidence here" in shown["output"]
        with kb.connect_closing() as conn:
            assert kb.get_task(conn, tid).created_by == "owner"
            assert kb.list_comments(conn, tid)[-1].author == "owner"
        board = await execute_command(orch, ["boards", "create", "alpha"], OWNER)
        assert board["ok"], board
        empty = await execute_command(orch, ["--board", "alpha", "list", "--json"], OWNER)
        assert empty["ok"] and empty["output"].strip() == "[]"


@pytest.mark.asyncio
async def test_refusal_and_usage_have_no_side_effects(tmp_path):
    orch = _orch()
    with kanban_scope(KanbanContext(tmp_path, "owner", can_mutate=True)):
        helped = await execute_command(orch, ["--help"], OWNER)
        assert helped["ok"] and "usage: nerva kanban" in helped["output"]
        unknown = await execute_command(orch, ["create", "oops", "--bogus"], OWNER)
        assert not unknown["ok"] and unknown["exit_code"] == 2
        assert not (tmp_path / "kanban.db").exists()
        repair = await execute_command(orch, ["repair", "--json"], OWNER)
        assert repair["ok"] and json.loads(repair["output"])["status"] == "missing"
        worker = await execute_command(orch, ["create", "oops"], OWNER, profile="owner")
        assert worker["ok"]
    with kanban_scope(KanbanContext(tmp_path, "worker", task_id="T1", run_id=1, can_mutate=True)):
        refused = await execute_command(orch, ["list"], OWNER, profile="owner")
        assert not refused["ok"]


@pytest.mark.asyncio
async def test_donor_metadata_graph_attachment_diagnostics_and_review(tmp_path):
    orch = _orch()
    orch.agents = {"jarvis": object(), "reviewer": object()}
    attachment = tmp_path / "proof.txt"
    attachment.write_text("durable proof")
    with kanban_scope(KanbanContext(tmp_path, "owner", can_mutate=True, session_id="trusted-session")):
        parent = await execute_command(orch, ["create", "Parent", "--json"], OWNER, session_id="spoof")
        child = await execute_command(orch, ["create", "Child", "--json"], OWNER)
        assert parent["ok"] and child["ok"]
        p = json.loads(parent["output"])["id"]
        c = json.loads(child["output"])["id"]
        linked = await execute_command(orch, ["link", p, c], OWNER)
        assert linked["ok"], linked
        upload = await execute_command(orch, ["attach", p, str(attachment), "--author", "spoof"], OWNER)
        assert upload["ok"], upload
        shown = await execute_command(orch, ["show", p, "--json"], OWNER)
        assert shown["ok"] and c in json.loads(shown["output"])["children"]
        assignees = await execute_command(orch, ["assignees", "--json"], OWNER)
        assert assignees["ok"] and {"jarvis", "reviewer"}.issubset({r["name"] for r in json.loads(assignees["output"])})
        diag = await execute_command(orch, ["diagnostics", "--json"], OWNER)
        assert diag["ok"], diag
        review = await execute_command(orch, ["request-review", p, "--summary", "proof attached"], OWNER)
        assert review["ok"], review
        runs = await execute_command(orch, ["runs", p, "--json"], OWNER)
        assert runs["ok"], runs
        with kb.connect_closing() as conn:
            task = kb.get_task(conn, p)
            assert task.session_id == "trusted-session"
            assert task.status == "review"
            assert kb.list_attachments(conn, p)[0].uploaded_by == "owner"


@pytest.mark.asyncio
async def test_board_switch_persists_for_unscoped_owner_only(tmp_path, monkeypatch):
    from agents.core.kanban import cli

    monkeypatch.setattr(cli, "data_path", lambda *_: tmp_path)
    orch = _orch()
    created = await execute_command(orch, ["boards", "create", "alpha", "--switch"], OWNER)
    assert created["ok"], created
    selected = await execute_command(orch, ["boards", "show"], OWNER)
    assert selected["ok"] and "Current board: alpha" in selected["output"]
    made = await execute_command(orch, ["create", "Inside alpha", "--json"], OWNER)
    assert made["ok"], made
    with kanban_scope(KanbanContext(tmp_path, "owner", board="default", can_mutate=True)):
        default = await execute_command(orch, ["list", "--json"], OWNER)
        assert default["ok"] and json.loads(default["output"]) == []
    archived = await execute_command(orch, ["boards", "rm", "alpha"], OWNER)
    assert archived["ok"], archived
    selected = await execute_command(orch, ["boards", "show"], OWNER)
    assert selected["ok"] and "Current board: default" in selected["output"]


@pytest.mark.asyncio
async def test_owner_metadata_pins_and_inbound_trust(tmp_path):
    orch = _orch()
    inbound_owner = SimpleNamespace(channel="telegram", admin=True)
    guest = SimpleNamespace(channel="telegram", admin=False)
    with kanban_scope(KanbanContext(tmp_path, "owner", can_mutate=True)):
        denied = await execute_command(orch, ["create", "No"], guest)
        assert not denied["ok"] and not (tmp_path / "kanban.db").exists()
        made = await execute_command(orch, ["create", "Yes", "--json"], inbound_owner)
        assert made["ok"], made
        tid = json.loads(made["output"])["id"]
        assigned = await execute_command(orch, ["assign", tid, "jarvis"], inbound_owner)
        assert assigned["ok"], assigned
        pinned = await execute_command(orch, ["set-model", tid, "local-model"], inbound_owner)
        assert pinned["ok"], pinned
        reassigned = await execute_command(orch, ["reassign", tid, "reviewer"], inbound_owner)
        assert reassigned["ok"], reassigned
        with kb.connect_closing() as conn:
            task = kb.get_task(conn, tid)
            assert task.assignee == "reviewer" and task.model_override == "local-model"
        with delegate_scope():
            refused = await execute_command(orch, ["list"], inbound_owner)
            assert not refused["ok"] and refused["reason"] == "delegated_scope"


@pytest.mark.asyncio
async def test_concurrent_dispatch_output_and_real_principal_are_isolated(tmp_path):
    class Controller:
        def __init__(self):
            self.entered = 0
            self.ready = asyncio.Event()
            self.seen = []

        async def request(self, principal, *, board, limit):
            from agents.core.kanban.context import current_context

            self.seen.append((principal, current_context().home, board, limit))
            self.entered += 1
            if self.entered == 2:
                self.ready.set()
            await asyncio.wait_for(self.ready.wait(), 2)
            return {"ok": True, "home": str(current_context().home), "queued": []}

    controller = Controller()
    orch = _orch()
    orch._autonomy = SimpleNamespace(kanban_dispatcher=lambda: controller)

    async def call(home):
        with kanban_scope(KanbanContext(home, "owner", can_mutate=True)):
            return await execute_command(orch, ["dispatch", "--json"], OWNER)

    first, second = await asyncio.gather(call(tmp_path / "one"), call(tmp_path / "two"))
    assert first["ok"] and second["ok"]
    assert str(tmp_path / "one") in first["output"] and str(tmp_path / "two") not in first["output"]
    assert str(tmp_path / "two") in second["output"] and str(tmp_path / "one") not in second["output"]
    assert all(item[0] is OWNER and item[3] == 4 for item in controller.seen)
