"""H23.28 — phased park-list enforcement for pull-request diffs."""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("park_guard", REPO / "scripts" / "park_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load()


def test_wave_one_modules_are_permanently_removed_from_park_policy():
    graduated = {"browser_agent", "desktop_operator", "screen_grounding"}

    assert graduated.isdisjoint(guard.PARK_POLICY)
    result = guard.evaluate(
        [
            "agents/core/browser_agent.py",
            "agents/core/desktop_operator.py",
            "agents/core/screen_grounding.py",
        ],
        "ordinary H28 maintenance",
    )
    assert result == {
        "ok": True,
        "declarations": [],
        "parked_touches": [],
        "violations": [],
    }


def test_wave_two_modules_are_permanently_removed_from_park_policy():
    graduated = {"image_gen", "media_gen", "media_skill"}

    assert graduated.isdisjoint(guard.PARK_POLICY)
    result = guard.evaluate(
        [
            "agents/core/image_gen.py",
            "agents/core/media_gen.py",
            "agents/core/media_skill.py",
        ],
        "ordinary H29 maintenance",
    )
    assert result == {
        "ok": True,
        "declarations": [],
        "parked_touches": [],
        "violations": [],
    }


def test_remaining_park_policy_is_exact_after_wave_two_graduation():
    assert set(guard.PARK_POLICY) == {
        "wyoming",
        "satellite_hub",
        "node_mesh",
        "e2e_sync",
        "training",
        "rust",
        "park-policy",
    }


def test_unrelated_changes_pass_without_declaration():
    result = guard.evaluate(["agents/core/router.py", "docs/FAQ.md"], "ordinary fix")
    assert result["ok"] is True
    assert result["violations"] == []


def test_every_parked_family_fails_without_unpark_declaration():
    paths = [
        "agents/core/satellite_hub.py",
        "agents/core/node_mesh.py",
        "agents/core/e2e_sync.py",
        "agents/core/voice/wyoming.py",
        "training/prepare_data.py",
        "rust/Cargo.toml",
    ]
    result = guard.evaluate(paths, "feature work")
    assert result["ok"] is False
    assert {violation["module"] for violation in result["violations"]} == {
        "satellite_hub",
        "node_mesh",
        "e2e_sync",
        "wyoming",
        "training",
        "rust",
    }


def test_wave_declaration_allows_only_its_phase():
    wave_one = guard.evaluate(
        ["agents/core/browser_agent.py", "agents/core/desktop_operator.py"],
        "feat: operator\n\nunpark: wave-1",
    )
    assert wave_one["ok"] is True
    cross_wave = guard.evaluate(
        ["agents/core/browser_agent.py", "agents/core/voice/wyoming.py"], "unpark: wave-1"
    )
    assert cross_wave["ok"] is False
    assert [item["module"] for item in cross_wave["violations"]] == ["wyoming"]


def test_named_module_declaration_is_narrow():
    result = guard.evaluate(
        ["agents/core/satellite_hub.py", "agents/core/node_mesh.py"],
        "unpark: satellite_hub",
    )
    assert result["ok"] is False
    assert [item["module"] for item in result["violations"]] == ["node_mesh"]


def test_wave_three_does_not_unpark_owner_pull_modules():
    result = guard.evaluate(
        ["agents/core/voice/wyoming.py", "training/sft_grpo.py"], "unpark: wave-3"
    )
    assert result["ok"] is False
    assert [item["module"] for item in result["violations"]] == ["training"]
    owner = guard.evaluate(["training/sft_grpo.py"], "unpark: owner training")
    assert owner["ok"] is True


def test_policy_files_are_self_protected():
    result = guard.evaluate(["scripts/park_guard.py"], "chore: weaken guard")
    assert result["ok"] is False
    assert result["violations"][0]["module"] == "park-policy"
    assert guard.evaluate([".github/workflows/park-guard.yml"], "unpark: park-policy")["ok"]


def test_windows_paths_and_deleted_files_match_identically():
    result = guard.evaluate([r"agents\core\satellite_hub.py"], "no declaration")
    assert result["ok"] is False
    assert result["violations"][0]["path"] == "agents/core/satellite_hub.py"


def test_declarations_are_line_based_not_incidental_prose():
    prose = "Please do not unpark: wave-3 because this is only documentation."
    assert guard.evaluate(["agents/core/satellite_hub.py"], prose)["ok"] is False
    assert guard.evaluate(["agents/core/satellite_hub.py"], "Context\nunpark: wave-3\nTests")["ok"]


def test_real_policy_covers_remaining_backlog_phase_six_names():
    expected = {
        "satellite_hub",
        "node_mesh",
        "e2e_sync",
        "wyoming",
        "training",
        "rust",
    }
    assert expected == set(guard.PARK_POLICY) - {"park-policy"}


def test_workflow_runs_base_policy_when_guard_already_exists():
    workflow = (REPO / ".github" / "workflows" / "park-guard.yml").read_text(encoding="utf-8")
    assert 'git show "$BASE_SHA:scripts/park_guard.py"' in workflow
    assert 'python "$RUNNER_TEMP/park_guard.py"' in workflow
