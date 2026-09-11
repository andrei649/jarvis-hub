"""H048 — the fixed per-call cost, before anybody has said anything.

Nerva's stated advantage is running well on a local model with a small window,
and today the fixed overhead competing for that window is invisible. The number
has to be *honest* to be worth having: the first draft of this report summed all
eighteen personas and announced 71.8% of a 32k window, when a real request pays
one soul and about 6.5%. A wrong number is worse than no number, so the per-call
floor is what the report leads with.
"""

import json

from agents.core.prompt_size import (
    Breakdown,
    Component,
    breakdown,
    render,
    scaffold_component,
    skills_index_component,
    soul_components,
    tool_schema_components,
)


def _souls(tmp_path, sizes: dict[str, int]):
    for agent, size in sizes.items():
        d = tmp_path / agent
        d.mkdir(parents=True, exist_ok=True)
        (d / "SOUL.md").write_text("s" * size, encoding="utf-8")
    return tmp_path


# ── components ───────────────────────────────────────────────────────────────

def test_a_component_reports_both_characters_and_tokens():
    c = Component.of("x", "abcd" * 10)
    assert c.chars == 40
    assert c.tokens > 0


def test_every_persona_on_disk_gets_its_own_row(tmp_path):
    _souls(tmp_path, {"jarvis": 100, "friday": 200})
    rows = soul_components(tmp_path)
    assert {r.name for r in rows} == {"soul:jarvis", "soul:friday"}


def test_the_template_directory_is_not_an_agent(tmp_path):
    _souls(tmp_path, {"jarvis": 100, "_templates": 500})
    assert {r.name for r in soul_components(tmp_path)} == {"soul:jarvis"}


def test_a_tool_is_costed_as_the_schema_that_crosses_the_wire():
    """The name is free; the input_schema is what the model is charged for, and a
    verbose one can outweigh a whole persona."""
    small = {"name": "a", "description": "x", "input_schema": {}}
    big = {"name": "b", "description": "x",
           "input_schema": {"type": "object", "properties": {
               f"f{i}": {"type": "string", "description": "y" * 50} for i in range(20)}}}
    rows = {r.name: r for r in tool_schema_components([small, big])}
    assert rows["tool:b"].tokens > rows["tool:a"].tokens * 5


def test_a_gated_tool_says_so_in_its_detail():
    row = tool_schema_components([{"name": "t", "gated": True, "input_schema": {}}])[0]
    assert "gated" in row.detail


def test_the_skills_index_is_rendered_the_way_the_prompt_renders_it():
    row = skills_index_component([{"command": "/note", "description": "save a note"}])
    assert row.chars > 0 and "1 skill" in row.detail


def test_no_skills_is_a_zero_row_rather_than_a_missing_one():
    """A reader must be able to tell 'nothing registered' from 'not measured'."""
    row = skills_index_component([])
    assert (row.chars, row.tokens) == (0, 0)
    assert "no skills" in row.detail


def test_the_turn_scaffold_is_counted_because_every_call_pays_it():
    assert scaffold_component().tokens > 0


# ── the honest per-call floor ────────────────────────────────────────────────

def test_the_floor_is_one_soul_not_all_of_them(tmp_path):
    """The bug this test exists for: summing eighteen personas describes a request
    that has never been sent. Only the routed agent's soul goes out."""
    _souls(tmp_path, {"a": 4000, "b": 4000, "c": 4000})
    report = breakdown(agents_root=tmp_path)
    floor, soul = report.per_call()
    assert soul is not None
    assert floor < report.total_tokens / 2
    assert floor == sum(c.tokens for c in report.shared_components()) + soul.tokens


def test_without_a_named_agent_the_heaviest_soul_is_used(tmp_path):
    """The worst realistic case, not a flattering one."""
    _souls(tmp_path, {"light": 400, "heavy": 8000})
    _, soul = breakdown(agents_root=tmp_path).per_call()
    assert soul.name == "soul:heavy"


def test_a_named_agent_is_costed_instead(tmp_path):
    _souls(tmp_path, {"light": 400, "heavy": 8000})
    _, soul = breakdown(agents_root=tmp_path).per_call("light")
    assert soul.name == "soul:light"


def test_an_unknown_agent_does_not_silently_bill_somebody_else(tmp_path):
    _souls(tmp_path, {"light": 400})
    floor, soul = breakdown(agents_root=tmp_path).per_call("nobody")
    assert soul is None
    assert floor == sum(c.tokens for c in breakdown(agents_root=tmp_path).shared_components())


def test_the_shared_cost_excludes_every_soul(tmp_path):
    _souls(tmp_path, {"a": 4000, "b": 4000})
    report = breakdown(agents_root=tmp_path)
    assert not any(c.name.startswith("soul:") for c in report.shared_components())


# ── the report ───────────────────────────────────────────────────────────────

def test_components_are_ranked_largest_first(tmp_path):
    """The point of the report is what to cut."""
    _souls(tmp_path, {"small": 100, "large": 9000})
    ranked = breakdown(agents_root=tmp_path).ranked()
    assert ranked[0].name == "soul:large"
    assert [c.tokens for c in ranked] == sorted([c.tokens for c in ranked], reverse=True)


def test_the_window_line_uses_the_per_call_floor_not_the_sum(tmp_path):
    """The whole correction, pinned: against a 32k window three 4k-char personas
    must read as a few percent, never as the sum of all three."""
    _souls(tmp_path, {"a": 4000, "b": 4000, "c": 4000})
    report = breakdown(agents_root=tmp_path)
    text = render(report, window=32_000)
    floor, _ = report.per_call()
    assert f"{floor / 32_000 * 100:.1f}%" in text
    assert f"{report.total_tokens / 32_000 * 100:.1f}%" not in text


def test_the_report_says_its_numbers_are_estimates(tmp_path):
    """It must not be mistaken for the provider's own count."""
    _souls(tmp_path, {"a": 500})
    assert "estimates" in render(breakdown(agents_root=tmp_path))


def test_the_report_says_only_one_soul_is_sent(tmp_path):
    _souls(tmp_path, {"a": 500, "b": 500})
    assert "ONE soul" in render(breakdown(agents_root=tmp_path))


def test_the_json_shape_carries_the_floor_and_which_soul_it_used(tmp_path):
    _souls(tmp_path, {"a": 500, "b": 9000})
    report = breakdown(agents_root=tmp_path)
    payload = json.loads(json.dumps(report.as_dict()))
    assert payload["total_tokens"] > 0
    assert payload["components"][0]["name"] == "soul:b"


def test_an_empty_tree_reports_a_floor_rather_than_crashing(tmp_path):
    report = breakdown(agents_root=tmp_path)
    floor, soul = report.per_call()
    assert soul is None
    assert floor >= 0


# ── the CLI verb ─────────────────────────────────────────────────────────────

def test_the_verb_is_registered_and_offline():
    from agents.cli.nerva import _VERBS, build_parser

    assert "prompt-size" in _VERBS
    ns = build_parser().parse_args(["prompt-size", "--window", "8000"])
    assert ns.verb == "prompt-size" and ns.window == 8000


def test_the_verb_runs_without_a_hub(capsys):
    """It answers 'what am I paying before the conversation starts' on a box
    where the hub is not even running, which is when the question gets asked."""
    from agents.cli.nerva import Context, main

    assert main(["prompt-size", "--window", "32000"], context=Context(environ={})) == 0
    out = capsys.readouterr().out
    assert "What ONE request actually pays" in out


def test_the_verb_emits_machine_readable_output(capsys):
    from agents.cli.nerva import Context, main

    assert main(["prompt-size", "--json"], context=Context(environ={})) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "per_call_tokens" in payload and "components" in payload
