"""The CLI's actual inspector renderer must disclose preview provenance."""

from agents.cli.nerva import render_inspector


def _render(prompt):
    return "\n".join(render_inspector({"agent": "jarvis", "view": "owner",
                                        "posture": "operator/owner", "system_prompt": prompt},
                                      only="system_prompt"))


def _prompt(**changes):
    return {"system": "base instructions", "turn": "empty turn rails", "bytes": 33,
            "tokens": 9, "cap": 65536, "truncated": False, "withheld": False, **changes}


def test_resolved_cli_preview_names_its_own_model_route_and_fixed_scope():
    out = _render(_prompt(resolved=True, model="preview-model", route="local"))
    assert "resolved" in out and "preview-model" in out and "local" in out
    assert "empty user message" in out
    assert "active history" in out and "tool schemas" in out
    assert "cached runtime facts may differ" in out
    assert "base instructions" in out and "empty turn rails" in out


def test_unresolved_cli_preview_calls_system_base_only_without_route_details():
    out = _render(_prompt(resolved=False, route_error="unavailable"))
    assert "unresolved" in out and "base system prompt only" in out
    assert "route unavailable" in out
    assert "resolved for model" not in out


def test_legacy_cli_preview_does_not_guess_resolution():
    out = _render(_prompt())
    assert "legacy" in out and "resolution not reported" in out
    assert "base instructions" in out
    assert "resolved for model" not in out


def test_withheld_cli_preview_never_prints_prompt_or_route_details():
    out = _render(_prompt(system="secret", turn="secret turn", withheld=True,
                          resolved=True, model="private-model", route="local"))
    assert "withheld" in out and "secret redactor" in out
    assert "secret turn" not in out and "private-model" not in out
