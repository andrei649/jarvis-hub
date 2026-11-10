"""SEC-B6: public safety state stays useful without exposing owner content."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.core.arena import Arena
from agents.core.kernel import metrics as kernel_metrics_module
from agents.core.kernel.metrics import KernelMetrics
from agents.core.learning.loop import LearningLoop
from agents.core.mcp.model_bridge import _description as mcp_tool_description
from agents.core.observability.capability_registry import snapshot as capability_snapshot
from agents.core.observability.datasets import DatasetStore
from agents.core.routers import _deps
from agents.core.routers import eval as eval_router
from agents.core.routers import onboarding as onboarding_router
from agents.core.security.capability import KillSwitch
from agents.core.security.token_store import TokenStore
from agents.core.skills.importer import SkillImporter
from agents.core.tool_rpc import ToolRPCServer

USER = {"X-User-Token": "sec-b6-user"}
BAD_USER = {"X-User-Token": "wrong-user"}
ADMIN = {"X-Admin-Token": "sec-b6-admin"}
BAD_ADMIN = {"X-Admin-Token": "wrong-admin"}
PRIVATE_SCOPE = "scope_owner_private_phrase"
PRIVATE_REASON = "reason_owner_private_phrase"
PRIVATE_AT = "time_owner_private_phrase"
PRIVATE_ORACLE = "oracle_owner_private_session"
PRIVATE_AGENT = "agent_owner_private_description"
PRIVATE_DATASET = "dataset_owner_private_label"
PRIVATE_REGRESSED = "case_owner_private_regressed"
PRIVATE_IMPROVED = "case_owner_private_improved"
PRIVATE_LEARNING = "learning_owner_private_failed_response"
PRIVATE_FOLDER = "/owner/private/documents/notes-secret"
PRIVATE_BASENAME = "owner_secret_document.pdf"
PRIVATE_IMPORT_NOTE = "import_owner_private_note"
PRIVATE_IMPORT_PATH = "/owner/private/skills/notes"
PRIVATE_ARENA_MODEL = "arena_owner_private_candidate"
PRIVATE_KERNEL_REASON = "kernel_owner_house_scope_private_reason"
PRIVATE_MCP_DESCRIPTION = "connected_owner_private_server_description"


@pytest.fixture
def private_reads(tmp_path, monkeypatch):
    from agents import web

    tokens = TokenStore(db_path=str(tmp_path / "tokens.db"))
    monkeypatch.setattr(web, "get_token_store", lambda: tokens)
    monkeypatch.setattr(web, "USER_TOKEN", USER["X-User-Token"])
    monkeypatch.setattr(web, "ADMIN_TOKEN", ADMIN["X-Admin-Token"])
    previous_overrides = {}
    for guard in (web._user_guard, _deps.user_guard):
        previous_overrides[guard] = web.app.dependency_overrides.pop(guard, None)
    assert web._user_guard not in web.app.dependency_overrides
    assert _deps.user_guard not in web.app.dependency_overrides

    kill_path = tmp_path / "kill.json"
    kill = KillSwitch(kill_path)
    kill.engage(PRIVATE_SCOPE, PRIVATE_REASON)
    persisted = json.loads(kill_path.read_text(encoding="utf-8"))
    persisted[PRIVATE_SCOPE]["at"] = PRIVATE_AT
    kill_path.write_text(json.dumps(persisted), encoding="utf-8")
    kill = KillSwitch(kill_path)

    store = DatasetStore(root=tmp_path / "eval")
    store.save_version(PRIVATE_DATASET, [
        {"name": PRIVATE_REGRESSED, "prompt": "one", "expect_contains": "one"},
        {"name": PRIVATE_IMPROVED, "prompt": "two", "expect_contains": "two"},
    ])
    before = store.record_run(PRIVATE_DATASET, 1, {
        "score": 0.75, "passed": 1, "total": 2,
        "results": [{"name": PRIVATE_REGRESSED, "passed": True, "score": 1.0},
                    {"name": PRIVATE_IMPROVED, "passed": False, "score": 0.0}],
    })
    after = store.record_run(PRIVATE_DATASET, 1, {
        "score": 0.25, "passed": 1, "total": 2,
        "results": [{"name": PRIVATE_REGRESSED, "passed": False, "score": 0.0},
                    {"name": PRIVATE_IMPROVED, "passed": True, "score": 1.0}],
    })
    monkeypatch.setattr(eval_router, "_get_dataset_store", lambda: store)
    learning = LearningLoop(db_path=tmp_path / "learning")
    for index in range(3):
        learning.record("jarvis", f"task {index}", PRIVATE_LEARNING,
                        success=False, latency=0.1, error=PRIVATE_LEARNING)
    local_docs_last = {"status": "indexed", "folder": PRIVATE_FOLDER,
                       "skipped": [PRIVATE_BASENAME], "indexed": 1}
    monkeypatch.setattr(onboarding_router, "_local_docs_last", local_docs_last)

    oracle_payload = {"session": PRIVATE_ORACLE, "tasks": [PRIVATE_ORACLE],
                      "conflicts": [PRIVATE_ORACLE], "error": PRIVATE_ORACLE}
    agent = SimpleNamespace(name="Jarvis", config={"tier": "owner", "model": "local"},
                            has_heartbeat=True, soul={"meta": {"description": PRIVATE_AGENT}})
    orch = SimpleNamespace(
        kill_switch=kill,
        oracle_bridge=SimpleNamespace(status=lambda: oracle_payload),
        agents={"jarvis": agent},
        checkpoints=SimpleNamespace(get_agent_stats=lambda _agent_id: {"turns": 2}),
        skills=SimpleNamespace(get_skills_for_agent=lambda _agent_id: []),
        learning=learning,
        get_setting=lambda key, default: {"owner-docs": PRIVATE_FOLDER}
        if key == "local_docs.folders" else default,
    )
    monkeypatch.setattr(web, "orch", orch)
    client = TestClient(web.app)
    paths = {
        "oracle": "/api/oracle/status",
        "agents": "/agents",
        "datasets": "/api/eval/datasets",
        "runs": f"/api/eval/datasets/{PRIVATE_DATASET}/runs",
        "compare": f"/api/eval/datasets/{PRIVATE_DATASET}/compare?a={before}&b={after}",
        "learning": "/learning/stats",
        "local_docs": "/api/local-docs",
    }
    try:
        yield SimpleNamespace(client=client, kill=kill, kill_path=kill_path, store=store,
                              oracle_payload=oracle_payload, paths=paths, before=before, after=after,
                              local_docs_last=local_docs_last)
    finally:
        client.close()
        for guard, override in previous_overrides.items():
            if override is not None:
                web.app.dependency_overrides[guard] = override
        tokens.close()


def test_public_kill_switch_projection_is_exact_and_private_status_persists(private_reads):
    state = private_reads.kill.public_status()
    assert state == {"global": False, "any_halted": True, "halted_count": 1}
    assert type(state["global"]) is bool and type(state["any_halted"]) is bool
    assert type(state["halted_count"]) is int
    public = private_reads.client.get("/api/security/kill-switch")
    assert public.status_code == 200
    assert public.json() == state
    assert "no-store" in public.headers["cache-control"]
    assert all(value not in public.text for value in (PRIVATE_SCOPE, PRIVATE_REASON, PRIVATE_AT))
    assert set(public.json()) == {"global", "any_halted", "halted_count"}
    assert private_reads.kill.status() == {
        "global": False,
        "halted": {PRIVATE_SCOPE: {"scope": PRIVATE_SCOPE, "reason": PRIVATE_REASON, "at": PRIVATE_AT}},
    }
    assert KillSwitch(private_reads.kill_path).status() == private_reads.kill.status()
    private_reads.kill.engage("global", "second private reason")
    assert private_reads.kill.public_status() == {"global": True, "any_halted": True, "halted_count": 2}
    private_reads.kill.disengage(PRIVATE_SCOPE)
    private_reads.kill.disengage("global")
    assert private_reads.kill.public_status() == {"global": False, "any_halted": False, "halted_count": 0}


def test_admin_kill_switch_details_preserve_full_old_status_with_real_guard(private_reads):
    client = private_reads.client
    for headers in ({}, BAD_ADMIN, USER):
        denied = client.get("/api/security/kill-switch/details", headers=headers)
        assert denied.status_code == 401
        assert all(value not in denied.text for value in (PRIVATE_SCOPE, PRIVATE_REASON, PRIVATE_AT))
    detail = client.get("/api/security/kill-switch/details", headers=ADMIN)
    assert detail.status_code == 200
    assert detail.json() == private_reads.kill.status()
    assert "no-store" in detail.headers["cache-control"]
    assert all(value in detail.text for value in (PRIVATE_SCOPE, PRIVATE_REASON, PRIVATE_AT))


@pytest.mark.parametrize("key,sentinel", [
    ("oracle", PRIVATE_ORACLE), ("agents", PRIVATE_AGENT),
    ("datasets", PRIVATE_DATASET), ("runs", PRIVATE_DATASET),
    ("compare", PRIVATE_REGRESSED),
    ("learning", PRIVATE_LEARNING), ("local_docs", PRIVATE_FOLDER),
])
def test_private_reads_require_real_user_credential_and_keep_authorized_payload(
    private_reads, key, sentinel
):
    client = private_reads.client
    path = private_reads.paths[key]
    for headers in ({}, BAD_USER):
        denied = client.get(path, headers=headers)
        assert denied.status_code == 401
        assert sentinel not in denied.text
    allowed = client.get(path, headers=USER)
    assert allowed.status_code == 200, allowed.text
    assert sentinel in allowed.text
    assert "no-store" in allowed.headers["cache-control"]
    if key == "oracle":
        assert allowed.json() == private_reads.oracle_payload
    elif key == "agents":
        assert allowed.json()["agents"]["jarvis"]["description"] == PRIVATE_AGENT
        assert allowed.json()["agents"]["jarvis"]["stats"] == {"turns": 2}
    elif key == "datasets":
        assert allowed.json() == {"datasets": private_reads.store.list_datasets()}
    elif key == "runs":
        assert allowed.json() == {"name": PRIVATE_DATASET,
                                  "runs": private_reads.store.runs(PRIVATE_DATASET, 20)}
    else:
        if key == "compare":
            assert allowed.json() == private_reads.store.compare(
                PRIVATE_DATASET, private_reads.before, private_reads.after
            )
            assert allowed.json()["regressed"] == [PRIVATE_REGRESSED]
            assert allowed.json()["improved"] == [PRIVATE_IMPROVED]
            assert allowed.json()["score_delta"] == -0.5
        elif key == "learning":
            assert allowed.json()["interactions_total"] == 3
            assert PRIVATE_LEARNING in allowed.json()["prompt_optimizations"][0]["after"]
        else:
            assert allowed.json() == {**private_reads.local_docs_last, "available": ["owner-docs"]}
            assert PRIVATE_BASENAME in allowed.text
    admin_allowed = client.get(path, headers=ADMIN)
    assert admin_allowed.status_code == 200
    assert admin_allowed.json() == allowed.json()


def test_private_read_errors_do_not_echo_private_content(private_reads, monkeypatch):
    from agents import web

    monkeypatch.setattr(web, "orch", None)
    missing_oracle = private_reads.client.get("/api/oracle/status", headers=USER)
    assert missing_oracle.status_code == 503
    assert PRIVATE_ORACLE not in missing_oracle.text
    missing_agents = private_reads.client.get("/agents", headers=USER)
    assert missing_agents.status_code == 503
    assert PRIVATE_AGENT not in missing_agents.text
    missing_kill = private_reads.client.get("/api/security/kill-switch")
    assert missing_kill.status_code == 503
    assert all(value not in missing_kill.text for value in (PRIVATE_SCOPE, PRIVATE_REASON, PRIVATE_AT))
    unknown = private_reads.client.get(
        f"/api/eval/datasets/{PRIVATE_DATASET}/compare?a=unknown&b=unknown", headers=USER
    )
    assert unknown.status_code == 200 and unknown.json()["error"] == "run not found"
    assert PRIVATE_REGRESSED not in unknown.text and PRIVATE_IMPROVED not in unknown.text


def test_imported_skill_manifest_requires_real_user_credential_and_preserves_payload(
    private_reads, tmp_path
):
    from agents import web

    skills_dir = tmp_path / "installed"
    skill_dir = skills_dir / "local-notes"
    skill_dir.mkdir(parents=True)
    manifest = {
        "imported": True,
        "source": "local",
        "name": "local-notes",
        "private_note": PRIVATE_IMPORT_NOTE,
        "source_path": PRIVATE_IMPORT_PATH,
        "owner_metadata": {"arbitrary_key": "preserve this owner value"},
    }
    (skill_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    importer = SkillImporter(str(skills_dir))
    assert importer.list_imported() == [manifest]
    web.orch.skill_importer = importer

    client = private_reads.client
    for headers in ({}, BAD_USER):
        denied = client.get("/skills/imported", headers=headers)
        assert denied.status_code == 401
        assert PRIVATE_IMPORT_NOTE not in denied.text
        assert PRIVATE_IMPORT_PATH not in denied.text
    allowed = client.get("/skills/imported", headers=USER)
    assert allowed.status_code == 200
    assert allowed.json() == {"imported": [manifest]}
    assert "no-store" in allowed.headers["cache-control"]
    assert client.get("/skills/imported", headers=ADMIN).json() == allowed.json()


def test_arena_leaderboard_requires_real_user_credential_and_preserves_saved_scores(
    private_reads, tmp_path
):
    from agents import web

    arena_path = tmp_path / "arena.json"
    arena = Arena(arena_path)
    match = arena.create_match("local comparison", {
        PRIVATE_ARENA_MODEL: "first response", "other-model": "second response",
    })
    arena.vote(match["id"], "A")
    assert Arena(arena_path).leaderboard() == arena.leaderboard()
    assert PRIVATE_ARENA_MODEL in {row["model"] for row in arena.leaderboard()}
    web.orch.arena = arena

    client = private_reads.client
    for headers in ({}, BAD_USER):
        denied = client.get("/api/arena/leaderboard", headers=headers)
        assert denied.status_code == 401
        assert PRIVATE_ARENA_MODEL not in denied.text
    allowed = client.get("/api/arena/leaderboard", headers=USER)
    assert allowed.status_code == 200
    assert allowed.json() == {"leaderboard": arena.leaderboard()}
    assert all(row["games"] == 1 for row in allowed.json()["leaderboard"])
    assert "no-store" in allowed.headers["cache-control"]
    assert client.get("/api/arena/leaderboard", headers=ADMIN).json() == allowed.json()


def test_kernel_metrics_requires_real_user_credential_and_preserves_denial_counters(
    private_reads, monkeypatch
):
    meter = KernelMetrics()
    meter.record("house.control", "deny", PRIVATE_KERNEL_REASON)
    monkeypatch.setattr(kernel_metrics_module, "KERNEL_METRICS", meter)
    expected = meter.snapshot()
    assert expected["total"] == 1
    assert expected["by_verdict"]["deny"] == 1
    assert expected["recent_denials"] == [{
        "kind": "house.control", "reason": PRIVATE_KERNEL_REASON,
    }]

    client = private_reads.client
    for headers in ({}, BAD_USER):
        denied = client.get("/api/metrics/kernel", headers=headers)
        assert denied.status_code == 401
        assert PRIVATE_KERNEL_REASON not in denied.text
    allowed = client.get("/api/metrics/kernel", headers=USER)
    assert allowed.status_code == 200
    assert allowed.json() == expected
    assert "no-store" in allowed.headers["cache-control"]
    assert client.get("/api/metrics/kernel", headers=ADMIN).json() == allowed.json()


def test_tool_catalog_reads_require_user_for_connected_tool_description(private_reads):
    from agents import web

    rpc = ToolRPCServer()
    rpc.register_tool(
        "mcp__owner__read", lambda _args: {"unused": True},
        description=mcp_tool_description({
            "qualified_name": "mcp__owner__read",
            "description": PRIVATE_MCP_DESCRIPTION,
        }),
        capability_id="tool:mcp__owner__read",
    )
    web.orch.tool_rpc = rpc
    expected = capability_snapshot(web.orch, live_schemas=False)
    connected = next(row for row in expected["capabilities"]
                     if row["id"] == "tool:mcp__owner__read")
    assert PRIVATE_MCP_DESCRIPTION in connected["description"]
    assert expected["total"] > 0
    assert sum(expected["by_state"].values()) == expected["total"]
    web.orch.sandbox = SimpleNamespace(
        _has_docker=True, docker_image="isolated-test", timeout=30,
        security_status=lambda: {"isolation": "locked"},
    )
    expected_by_path = {
        "/api/metrics/capabilities": json.loads(json.dumps(expected)),
        "/sandbox/status": {
            "available": True, "docker_image": "isolated-test", "timeout": 30,
            "isolation": "locked",
            "tool_rpc": {"available": True, "tools": rpc.tools(live=False)},
        },
    }
    assert PRIVATE_MCP_DESCRIPTION in expected_by_path["/sandbox/status"]["tool_rpc"]["tools"][0]["description"]

    client = private_reads.client
    for path, expected_payload in expected_by_path.items():
        for headers in ({}, BAD_USER):
            denied = client.get(path, headers=headers)
            assert denied.status_code == 401
            assert PRIVATE_MCP_DESCRIPTION not in denied.text
        allowed = client.get(path, headers=USER)
        assert allowed.status_code == 200
        assert allowed.json() == expected_payload
        assert "no-store" in allowed.headers["cache-control"]
        assert client.get(path, headers=ADMIN).json() == allowed.json()
