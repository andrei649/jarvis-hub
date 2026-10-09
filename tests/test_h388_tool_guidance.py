"""H388 guidance names only tools Nerva has actually offered."""

from agents.core.operating_guidance import build_operating_guidance


def guide(*, capabilities=frozenset(), enabled=None):
    return build_operating_guidance(
        model="gpt-5", surface="cli", capabilities=capabilities, enabled=enabled
    )


def test_memory_and_user_profile_are_independent_and_require_memory_tool():
    offered = frozenset({"tool:memory"})
    both = guide(capabilities=offered)
    assert "# Persistent memory" in both
    assert "# Persistent user profile" in both
    assert "target='memory'" in both and "target='user'" in both
    assert "declarative facts" in both
    assert "a fact stale within a week" in both.lower()

    memory_only = guide(capabilities=offered, enabled={"user_profile_guidance": False})
    assert "# Persistent memory" in memory_only
    assert "# Persistent user profile" not in memory_only
    user_only = guide(capabilities=offered, enabled={"memory_guidance": False})
    assert "# Persistent memory" not in user_only
    assert "# Persistent user profile" in user_only
    assert "target='memory'" not in user_only

    no_memory = guide(capabilities=frozenset({"tool:skills_list"}))
    assert "# Persistent memory" not in no_memory
    assert "# Persistent user profile" not in no_memory
    assert "target='memory'" not in no_memory
    assert "target='user'" not in no_memory


def test_skills_guidance_names_only_offered_skill_tools():
    listed = guide(capabilities=frozenset({"tool:skills_list"}))
    assert "# Skills" in listed and "skills_list" in listed
    assert "skill_view" not in listed and "skill_propose" not in listed

    viewed = guide(capabilities=frozenset({"tool:skill_view"}))
    assert "# Skills" in viewed and "skill_view" in viewed
    assert "skills_list" not in viewed and "skill_propose" not in viewed
    assert "[SKILL_PRUNED]" in viewed

    proposed = guide(capabilities=frozenset({"tool:skill_propose"}))
    assert "# Skills" in proposed and "skill_propose" in proposed
    assert "owner" in proposed.lower() and "review" in proposed.lower()
    assert "skill_manage" not in proposed

    disabled = guide(
        capabilities=frozenset({"tool:skills_list", "tool:skill_view", "tool:skill_propose"}),
        enabled={"skills_guidance": False},
    )
    assert "# Skills" not in disabled
    assert "skill_manage" not in guide(capabilities=frozenset({"tool:skill_view"}))


def test_memory_scope_routes_task_workflows_to_skills_without_inventing_writes():
    no_skill_writes = guide(capabilities=frozenset({"tool:memory"}))
    assert "procedures and workflows belong in skills" in no_skill_writes
    assert "skill_propose" not in no_skill_writes
    with_proposal = guide(capabilities=frozenset({"tool:memory", "tool:skill_propose"}))
    assert "skill_propose" in with_proposal
    assert "skill_manage" not in with_proposal


def test_help_points_to_nerva_docs_without_foreign_authority_or_dangling_tool():
    text = guide()
    assert "# Nerva help" in text
    assert "User guide" in text and "Feature flags" in text and "Privacy" in text
    assert "Hermes Agent" not in text and "hermes-agent.nousresearch.com" not in text
    assert "file_read" not in text
    with_read = guide(capabilities=frozenset({"tool:file_read"}))
    assert "file_read" in with_read
    assert "allowed" in with_read.lower()
    assert "# Nerva help" not in guide(enabled={"help_guidance": False})


def test_kanban_flag_does_not_advertise_unwired_tool_family():
    text = guide(
        capabilities=frozenset({"tool:memory", "tool:kanban_show"}),
        enabled={"kanban_guidance": True},
    )
    assert "Kanban" not in text and "kanban_show" not in text
    assert "HERMES_KANBAN" not in text
