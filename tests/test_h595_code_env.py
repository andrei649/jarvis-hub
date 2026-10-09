"""H595: owner-scoped skill environment permissions for execute_code."""

import pytest

from agents.core.code_env import CodeEnvRegistry, prepare_code_env


def test_default_scrub_keeps_only_exact_operational_names():
    source = {
        "JARVIS_HOME": "/synthetic/jarvis",
        "JARVIS_PROFILE": "demo",
        "HERMES_HOME": "/synthetic/hermes",
        "HERMES_DELEGATED_CHILD_CONTEXT": "1",
        "JARVIS_PUBLIC_NOTE": "not-secret-but-internal",
        "HERMES_BASE_URL": "private-host",
        "MY_CUSTOM_KEY": "synthetic-secret",
        "PATH": "/synthetic/bin",
        "HOME": "/synthetic/home",
    }

    assert prepare_code_env(source) == {
        "JARVIS_HOME": "/synthetic/jarvis",
        "JARVIS_PROFILE": "demo",
        "HERMES_HOME": "/synthetic/hermes",
        "HERMES_DELEGATED_CHILD_CONTEXT": "1",
    }


def test_owner_declaration_passes_only_named_value_via_source_callback():
    values = {"MY_CUSTOM_KEY": "synthetic-secret", "OTHER_KEY": "other"}
    read_names = []

    def source(name):
        read_names.append(name)
        return values.get(name)

    registry = CodeEnvRegistry(clock=lambda: 10.0)
    registry.declare(
        agent="athena", principal="owner", session_id="a", skill_id="signed:one",
        names=["MY_CUSTOM_KEY"], validator=lambda: True,
    )
    allowed = registry.resolve_names(agent="athena", principal="owner", session_id="a")
    assert prepare_code_env(source, allowed_names=allowed) == {"MY_CUSTOM_KEY": "synthetic-secret"}
    assert "OTHER_KEY" not in read_names


@pytest.mark.parametrize("name", [
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
    "GEMINI_API_KEY", "DEEPINFRA_API_KEY", "OPENAI_BASE_URL", "GH_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK", "AUXILIARY_SUMMARY_API_KEY",
    "GATEWAY_RELAY_JOB_TOKEN", "JARVIS_USER_TOKEN", "HERMES_RPC_TOKEN",
    "JARVIS_RPC_DIR", "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD",
    "DYLD_INSERT_LIBRARIES", "BASH_ENV", "NODE_OPTIONS", "VIRTUAL_ENV",
    "CONDA_PREFIX", "LC_ALL", "SYSTEMROOT",
])
def test_managed_and_control_names_cannot_be_reallowed(name):
    registry = CodeEnvRegistry()
    registry.declare(
        agent="athena", principal="owner", session_id="a", skill_id="signed:one",
        names=[name],
    )
    allowed = registry.resolve_names(
        agent="athena", principal="owner", session_id="a",
        machine_allowlist=[name],
    )
    assert name not in allowed
    assert prepare_code_env({name: "synthetic-secret"}, allowed_names=[name]) == {}


def test_scope_is_exact_and_machine_allowlist_is_owner_only():
    registry = CodeEnvRegistry()
    registry.declare(
        agent="athena", principal="owner", session_id="a", skill_id="signed:one",
        names=["MY_CUSTOM_KEY"],
    )
    assert registry.resolve_names(agent="athena", principal="owner", session_id="a") == frozenset({"MY_CUSTOM_KEY"})
    for scope in (
        {"agent": "athena", "principal": "owner", "session_id": "b"},
        {"agent": "frigga", "principal": "owner", "session_id": "a"},
        {"agent": "athena", "principal": "guest", "session_id": "a"},
    ):
        assert registry.resolve_names(**scope, machine_allowlist=["MACHINE_KEY"]) == (
            frozenset({"MACHINE_KEY"}) if scope["principal"] == "owner" else frozenset()
        )
    with pytest.raises(ValueError):
        registry.declare(
            agent="athena", principal="guest", session_id="a", skill_id="signed:one",
            names=["MY_CUSTOM_KEY"],
        )


def test_expiry_validator_change_and_revoke_remove_permissions():
    now = [10.0]
    trusted = [True]
    registry = CodeEnvRegistry(clock=lambda: now[0], ttl_seconds=5)
    scope = {"agent": "athena", "principal": "owner", "session_id": "a"}
    registry.declare(**scope, skill_id="signed:one", names=["ONE_KEY"], validator=lambda: trusted[0])
    assert registry.resolve_names(**scope) == frozenset({"ONE_KEY"})
    trusted[0] = False
    assert registry.resolve_names(**scope) == frozenset()
    trusted[0] = True
    assert registry.resolve_names(**scope) == frozenset()
    registry.declare(**scope, skill_id="signed:one", names=["ONE_KEY"], validator=lambda: True)
    now[0] = 15.0
    assert registry.resolve_names(**scope) == frozenset()
    registry.declare(**scope, skill_id="signed:one", names=["ONE_KEY"])
    registry.revoke(**scope, skill_id="signed:one")
    assert registry.resolve_names(**scope) == frozenset()


def test_new_empty_skill_declaration_revokes_previous_names():
    registry = CodeEnvRegistry()
    scope = {"agent": "athena", "principal": "owner", "session_id": "a"}
    registry.declare(**scope, skill_id="signed:one", names=["ONE_KEY"])
    registry.declare(**scope, skill_id="signed:one", names=[])
    assert registry.resolve_names(**scope) == frozenset()


def test_bad_names_and_unreadable_policy_fail_closed():
    registry = CodeEnvRegistry(max_variables=2)
    scope = {"agent": "athena", "principal": "owner", "session_id": "a"}
    for bad in ("", "A=B", "A\x00B", "a_key", "openai_api_key", "A-KEY", "9KEY", "A" * 129):
        with pytest.raises(ValueError):
            registry.declare(**scope, skill_id="signed:one", names=[bad])
    with pytest.raises(ValueError):
        registry.declare(**scope, skill_id="signed:one", names=["ONE", "TWO", "THREE"])

    def unreadable():
        raise OSError("catalog unreadable")

    registry.declare(**scope, skill_id="signed:one", names=["ONE_KEY"], validator=unreadable)
    assert registry.resolve_names(**scope, machine_allowlist=unreadable) == frozenset()


def test_values_are_never_stored_in_registry_and_bad_value_is_omitted():
    registry = CodeEnvRegistry()
    scope = {"agent": "athena", "principal": "owner", "session_id": "a"}
    registry.declare(**scope, skill_id="signed:one", names=["MY_CUSTOM_KEY"])
    assert "synthetic-secret" not in repr(registry)
    assert prepare_code_env(
        {"MY_CUSTOM_KEY": "synthetic-secret\x00injection", "OTHER_KEY": "other"},
        allowed_names=registry.resolve_names(**scope),
    ) == {}
