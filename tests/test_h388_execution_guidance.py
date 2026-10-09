"""Behavioral coverage for the substantive, capability-aware H388 execution tier."""

import pytest

from agents.core.operating_guidance import build_operating_guidance

_QUIET_FLAGS = {
    "task_completion": False,
    "parallel_tool_calls": False,
    "tool_use_enforcement": False,
    "session_search": False,
    "memory_guidance": False,
    "user_profile_guidance": False,
    "skills_guidance": False,
    "help_guidance": False,
    "platform_hint": False,
    "environment_hint": False,
    "profile_hint": False,
}


def guide(model="gpt-5", tools=(), **flags):
    return build_operating_guidance(
        model=model,
        surface="cli",
        capabilities=frozenset(tools),
        enabled={**_QUIET_FLAGS, **flags},
    )


def test_execution_carries_upstream_persistence_and_completion_checks():
    text = guide(tools={"tool:terminal_run"})
    assert "# Execution discipline" in text
    assert "<tool_persistence>" in text
    assert "empty, partial, or suspiciously narrow" in text
    assert "broader or different query or strategy" in text
    assert "<prerequisite_checks>" in text
    assert "prior step" in text
    assert "<verification>" in text
    assert "every named acceptance criterion" in text
    assert "requested format or schema" in text


def test_execution_preserves_external_readback_counts_literals_and_missing_context():
    text = guide(tools={"tool:terminal_run"})
    assert "<external_state_verification>" in text
    assert "reading back the exact target" in text
    assert "Declared totals" in text and "re-fetch or parse programmatically" in text
    assert "provider defaults" in text
    assert "<literal_preservation>" in text
    assert "never 'repair' or normalize a token" in text
    assert "<missing_context>" in text
    assert "label assumptions explicitly" in text


def test_obvious_defaults_and_live_environment_are_not_inferred_from_user_memory():
    text = guide(tools={"tool:terminal_run"})
    assert "<act_dont_ask>" in text
    assert "obvious default interpretation" in text
    assert "What OS am I running?" in text and "terminal_run" in text
    assert "Your memory and user profile describe the USER" in text
    assert "execution environment may differ" in text


@pytest.mark.parametrize(
    ("capability", "named"),
    [
        ("tool:terminal_run", "terminal_run"),
        ("tool:execute_code", "execute_code"),
        ("tool:file_read", "file_read"),
        ("tool:file_search", "file_search"),
        ("tool:web_search", "web_search"),
        ("tool:web_extract", "web_extract"),
    ],
)
def test_execution_names_a_tool_only_when_exact_capability_is_offered(capability, named):
    text = guide(tools={capability})
    assert named in text
    for other in {"terminal_run", "execute_code", "file_read", "file_search", "web_search", "web_extract"} - {named}:
        assert other not in text


def test_an_unrelated_tool_never_implies_terminal_code_file_or_web_access():
    text = guide(tools={"tool:echo"})
    assert "<prerequisite_checks>" in text
    assert "<verification>" in text
    for name in ("terminal_run", "execute_code", "file_read", "file_search", "web_search", "web_extract"):
        assert name not in text


def test_google_guidance_keeps_substantive_operational_rules():
    text = guide(model="gemini-pro", tools={"tool:file_read", "tool:file_search", "tool:terminal_run"})
    assert "# Google model operational directives" in text
    assert "# Execution discipline" not in text
    assert "absolute file paths" in text
    assert "file_read" in text and "file_search" in text
    assert "Never guess at file contents" in text
    assert "Never assume a library is available" in text
    assert "package.json" in text and "requirements.txt" in text
    assert "Non-interactive commands" in text and "--non-interactive" in text
    assert "actions and results" in text
    assert "fully resolved" in text


def test_google_names_only_offered_tools_and_preserves_family_flag_gates():
    echo = guide(model="gemma-3", tools={"tool:echo"})
    for name in ("terminal_run", "execute_code", "file_read", "file_search", "web_search", "web_extract"):
        assert name not in echo
    assert "Non-interactive commands" not in echo
    with_code = guide(model="gemma-3", tools={"tool:execute_code"})
    assert "execute_code" in with_code and "terminal_run" not in with_code
    assert "Non-interactive commands" not in with_code
    assert "# Google model operational directives" not in guide(
        model="gpt-5", tools={"tool:terminal_run"}
    )
    assert "# Google model operational directives" not in guide(
        model="gemini-pro", tools={"tool:terminal_run"}, google_operational=False
    )
    assert "# Execution discipline" not in guide(
        tools={"tool:terminal_run"}, execution_guidance=False
    )
