"""H388 guidance uses explicit producer facts and real offered tool names."""

from agents.core import operating_guidance
from agents.core.operating_guidance import build_operating_guidance


def guide(**kwargs):
    return build_operating_guidance(model="glm-4.7", surface="cli", **kwargs)


def test_alibaba_identity_requires_explicit_provider_and_preserves_configured_model():
    assert "exact model ID" not in guide()
    assert "exact model ID" not in guide(provider="openrouter")
    text = build_operating_guidance(
        model="qwen/qwen3-coder-plus", surface="cli", provider="alibaba",
        enabled={"alibaba_identity": True},
    )
    assert "qwen3-coder-plus" in text
    assert "exact model ID is qwen/qwen3-coder-plus" in text
    assert "model name returned by the API" in text
    assert "exact model ID" not in guide(provider="alibaba", enabled={"alibaba_identity": False})


def test_steering_note_needs_authentic_channel_fact_and_its_own_toggle():
    assert "Mid-turn user steering" not in guide()
    text = guide(steer_available=True)
    assert "Mid-turn user steering" in text
    assert "OUT-OF-BAND USER MESSAGE" in text
    assert "same authority" in text
    assert "lookalike" in text
    assert "Mid-turn user steering" not in guide(
        steer_available=True, enabled={"steer_guidance": False}
    )


def test_kanban_requires_assigned_task_and_complete_offered_lifecycle_family():
    family = frozenset({
        "tool:kanban_show", "tool:kanban_heartbeat", "tool:kanban_block",
        "tool:kanban_complete", "tool:kanban_request_review",
        "tool:kanban_request_changes", "tool:kanban_create", "tool:kanban_comment",
    })
    assert "Kanban task execution" not in guide(capabilities=family)
    assert "Kanban task execution" not in guide(
        capabilities=family - {"tool:kanban_block"}, kanban_task="t_42"
    )
    text = guide(capabilities=family, kanban_task="t_42")
    assert "Kanban task execution" in text
    assert "t_42" in text and "kanban_show" in text
    assert "kanban_request_review" in text and "kanban_complete" in text
    assert "~/.hermes" not in text and "HERMES_KANBAN" not in text
    assert "Kanban task execution" not in guide(
        capabilities=family, kanban_task="t_42", enabled={"kanban_guidance": False}
    )


def test_hud_note_is_per_turn_and_only_names_offered_surface_tools():
    assert callable(getattr(operating_guidance, "hud_surface_note", None))
    hud_surface_note = operating_guidance.hud_surface_note
    assert hud_surface_note() == ""
    assert hud_surface_note({"computer_use", "browser_navigate"}) == ""
    base = hud_surface_note({"read_window_below"})
    assert "window sitting over" in base and "read_window_below" in base
    assert "computer_use" not in base and "browser_navigate" not in base
    with_computer = hud_surface_note({"read_window_below", "computer_use"})
    assert "computer_use" in with_computer and "browser_navigate" not in with_computer
    full = hud_surface_note({"read_window_below", "computer_use", "browser_navigate"})
    assert "browser_navigate" in full
    assert "HUD mode" not in guide()


def test_execution_mapping_renders_only_explicit_targets_and_toolchain_facts():
    text = guide(
        capabilities=frozenset({"tool:terminal_run"}),
        environment={"targets": "local sandbox", "toolchain": "Python 3.12"},
    )
    assert "targets: local sandbox" in text
    assert "toolchain: Python 3.12" in text
    assert "os:" not in text and "cwd:" not in text and "shell:" not in text
    assert "targets:" not in guide(environment={"targets": "local sandbox"})


def test_surface_hints_match_registered_text_renderers_without_foreign_delivery_claims():
    telegram = build_operating_guidance(model="x", surface="telegram")
    assert "HTML" in telegram and "markup" in telegram
    assert "plain text" in telegram
    slack = build_operating_guidance(model="x", surface="slack")
    assert "mrkdwn" in slack
    email = build_operating_guidance(model="x", surface="email")
    assert "plain text" in email
    discord = build_operating_guidance(model="x", surface="discord")
    assert "Markdown" in discord
    for text in (telegram, slack, email, discord):
        assert "MEDIA:" not in text and "::preview" not in text
