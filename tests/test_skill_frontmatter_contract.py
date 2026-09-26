"""H327 — the SKILL.md frontmatter contract, as agentskills.io / Hermes write it.

Nerva imports Hermes SKILL.md files and claims agentskills.io compatibility, yet the
loader kept eight keys and dropped the rest: a skill declaring ``platforms: [macos]``
or ``required_environment_variables: [AIRTABLE_API_KEY]`` loaded everywhere and failed
at use time, and a byte-order mark or one malformed YAML line demoted the whole file
to the heading dialect (name = directory name, description empty). These tests pin the
parse Hermes performs in ``agent/skill_utils.parse_frontmatter``: the BOM is stripped
before the fence check, malformed YAML falls back to ``key: value`` lines, the name is
capped at 64 characters and the description at 1024, and every recognised key survives
in normalised form. Parsed environment-variable names are metadata only — no value is
ever read here.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from agents.core.skills import frontmatter as fmx
from agents.core.skills.importer import SkillImporter
from agents.core.skills.loader import Skill, SkillLoader


def _manifest(tmp_path: Path, text: str, *, raw: bytes | None = None) -> dict:
    skill_dir = tmp_path / "dir-name"
    skill_dir.mkdir(exist_ok=True)
    path = skill_dir / "SKILL.md"
    if raw is not None:
        path.write_bytes(raw)
    else:
        path.write_text(text, encoding="utf-8")
    return SkillLoader()._parse_manifest(path)


HERMES_SKILL = """---
name: apple-notes
description: Manage Apple Notes from the terminal.
version: 1.2.0
author: Hermes Agent
license: MIT
homepage: https://example.test/notes
platforms: [macos]
environments: [Docker]
triggers: [notes, memo]
dependencies: memo-cli
compatibility: Requires macOS 13+
tags: [top-level-tag]
related_skills: [apple-reminders]
required_environment_variables:
  - AIRTABLE_API_KEY
  - name: NOTES_TOKEN
    prompt: Paste the notes token
    help: https://example.test/token
    required_for: sync
    optional: true
  - "not a valid name"
required_credential_files:
  - path: google_token.json
    description: OAuth token
  - client_secret.json
setup:
  help: https://example.test/setup
  collect_secrets:
    - env_var: SETUP_KEY
      prompt: Setup key please
      provider_url: https://example.test/keys
prerequisites:
  env_vars: [LEGACY_KEY]
  commands: [memo]
metadata:
  hermes:
    tags: [Notes, Apple]
    category: productivity
    upstream_skill: notes-upstream
    supersedes: [old-notes]
    session_platforms: [cli]
    requires_toolsets: [terminal]
    requires_tools: [terminal]
    fallback_for_toolsets: [browser]
    fallback_for_tools: [web_search]
    config:
      - key: notes.folder
        description: Default folder
        default: Inbox
      - key: notes.folder
        description: duplicate is dropped
      - key: missing-description
      - description: missing key
---
# Apple Notes

Body text.
"""


def test_a_hermes_skill_keeps_the_platforms_it_declares(tmp_path):
    manifest = _manifest(tmp_path, HERMES_SKILL)
    assert manifest["platforms"] == ["macos"]


def test_every_recognised_key_survives_in_normalised_form(tmp_path):
    m = _manifest(tmp_path, HERMES_SKILL)
    assert m["name"] == "apple-notes"
    assert m["description"] == "Manage Apple Notes from the terminal."
    assert m["homepage"] == "https://example.test/notes"
    assert m["environments"] == ["docker"]
    assert m["triggers"] == ["notes", "memo"]
    assert m["dependencies"] == ["memo-cli"]
    assert m["compatibility"] == "Requires macOS 13+"
    # metadata.hermes.* wins over the top-level key, as in Hermes' skill_view.
    assert m["tags"] == ["Notes", "Apple"]
    assert m["related_skills"] == ["apple-reminders"]
    assert m["setup"]["help"] == "https://example.test/setup"
    assert m["prerequisites"]["commands"] == ["memo"]
    assert m["required_credential_files"] == [
        {"path": "google_token.json", "description": "OAuth token"},
        {"path": "client_secret.json"},
    ]
    hermes = m["hermes"]
    assert hermes["category"] == "productivity"
    assert hermes["upstream_skill"] == "notes-upstream"
    assert hermes["supersedes"] == ["old-notes"]
    assert hermes["session_platforms"] == ["cli"]
    assert hermes["requires_toolsets"] == ["terminal"]
    assert hermes["requires_tools"] == ["terminal"]
    assert hermes["fallback_for_toolsets"] == ["browser"]
    assert hermes["fallback_for_tools"] == ["web_search"]
    assert hermes["tags"] == ["Notes", "Apple"]
    assert hermes["config"] == [
        {"key": "notes.folder", "description": "Default folder", "default": "Inbox",
         "prompt": "Default folder"},
    ]
    # The pre-existing fallback still holds: requires comes from requires_toolsets.
    assert m["requires"] == ["terminal"]


def test_required_environment_variables_merge_like_hermes_and_carry_names_only(tmp_path):
    m = _manifest(tmp_path, HERMES_SKILL)
    env = m["required_environment_variables"]
    assert [e["name"] for e in env] == ["AIRTABLE_API_KEY", "NOTES_TOKEN", "SETUP_KEY", "LEGACY_KEY"]
    assert env[0] == {"name": "AIRTABLE_API_KEY", "prompt": "Enter value for AIRTABLE_API_KEY",
                      "help": "https://example.test/setup"}
    assert env[1] == {"name": "NOTES_TOKEN", "prompt": "Paste the notes token",
                      "help": "https://example.test/token", "required_for": "sync", "optional": True}
    assert env[2]["prompt"] == "Setup key please" and env[2]["help"] == "https://example.test/keys"
    # A declared name that is not an environment-variable name is dropped, not passed on.
    assert all(" " not in e["name"] for e in env)
    assert all(set(e) <= {"name", "prompt", "help", "required_for", "optional"} for e in env)


def test_a_byte_order_mark_does_not_demote_the_file_to_the_heading_dialect(tmp_path):
    raw = "\ufeff---\nname: bom-skill\ndescription: Written by a Windows editor.\n---\nBody\n".encode()
    m = _manifest(tmp_path, "", raw=raw)
    assert m["name"] == "bom-skill"
    assert m["description"] == "Written by a Windows editor."


def test_malformed_yaml_falls_back_to_key_value_lines(tmp_path):
    text = "---\nname: broken-yaml\ndescription: has: colons: [unclosed\n---\n# Heading Name\n"
    m = _manifest(tmp_path, text)
    assert m["name"] == "broken-yaml"
    assert m["description"] == "has: colons: [unclosed"


def test_name_and_description_are_capped(tmp_path):
    text = f"---\nname: {'n' * 200}\ndescription: {'d' * 3000}\n---\n"
    m = _manifest(tmp_path, text)
    assert m["name"] == "n" * fmx.MAX_NAME_LENGTH == "n" * 64
    assert len(m["description"]) == fmx.MAX_DESCRIPTION_LENGTH == 1024
    assert m["description"].endswith("...")


def test_platform_names_are_mapped_to_one_vocabulary(tmp_path):
    assert fmx.normalize_platforms("darwin") == ["macos"]
    assert fmx.normalize_platforms(["Windows", "win32", "Linux", "FreeBSD", "macOS"]) == [
        "windows", "linux", "freebsd", "macos"]
    assert fmx.normalize_platforms(None) == []
    assert fmx.normalize_platforms({"not": "a list"}) == []


def test_a_yaml_date_or_odd_value_cannot_break_json_consumers(tmp_path):
    text = ("---\nname: dated\ndescription: 12\nsetup:\n  released: 2024-01-01\n"
            "  nested: {deep: [1, 2.5, true, null]}\nhomepage: [not, a, string]\n---\n")
    m = _manifest(tmp_path, text)
    assert m["description"] == "12"
    assert m["setup"]["released"] == "2024-01-01"
    assert m["homepage"] == ""
    json.dumps(m)  # the security posture route serialises Skill.to_dict()


def test_malformed_metadata_blocks_are_tolerated(tmp_path):
    text = "---\nname: odd\nmetadata: [not, a, mapping]\nplatforms: 7\nsetup: just text\n---\n"
    m = _manifest(tmp_path, text)
    assert m["hermes"] == {
        "tags": [], "category": "", "upstream_skill": "", "supersedes": [], "session_platforms": [],
        "requires_toolsets": [], "requires_tools": [], "fallback_for_toolsets": [],
        "fallback_for_tools": [], "config": []}
    assert m["platforms"] == ["7"]
    assert m["setup"] == {}


def test_hostile_frontmatter_is_bounded(tmp_path):
    many = ", ".join(f"t{i}" for i in range(500))
    text = f"---\nname: big\ntriggers: [{many}]\nhomepage: {'h' * 5000}\n---\n"
    m = _manifest(tmp_path, text)
    assert len(m["triggers"]) == fmx.MAX_LIST_ITEMS
    assert len(m["homepage"]) <= fmx.MAX_FIELD_CHARS


def test_the_heading_dialect_is_unchanged(tmp_path):
    text = "# weather\n> Live weather.\n**Version:** 2.0\n**Agents:** jarvis, friday\n"
    m = _manifest(tmp_path, text)
    assert m["name"] == "weather" and m["description"] == "Live weather."
    assert m["version"] == "2.0" and m["agents"] == ["jarvis", "friday"]


def test_skill_exposes_the_contract_fields(tmp_path):
    m = _manifest(tmp_path, HERMES_SKILL)
    skill = Skill(m["name"], tmp_path, m)
    assert skill.platforms == ["macos"]
    assert skill.environments == ["docker"]
    assert skill.required_env == ["AIRTABLE_API_KEY", "NOTES_TOKEN", "SETUP_KEY", "LEGACY_KEY"]
    assert skill.hermes_meta["category"] == "productivity"
    d = skill.to_dict()
    assert d["platforms"] == ["macos"] and d["environments"] == ["docker"]
    assert d["required_env"] == skill.required_env
    assert d["hermes"]["category"] == "productivity"
    json.dumps(d)


def test_a_manifest_without_the_contract_keys_reads_as_empty():
    skill = Skill("plain", Path("/nonexistent"), {"name": "plain"})
    assert skill.platforms == [] and skill.environments == [] and skill.required_env == []
    assert skill.hermes_meta == {}


@pytest.mark.parametrize("text", [
    "\ufeff---\nname: imported\n---\nbody",
    "---\nname: imported\ndescription: bad: yaml: [x\n---\nbody",
])
def test_the_importer_reads_the_same_frontmatter_the_loader_does(text):
    assert SkillImporter._extract_frontmatter(text)["name"] == "imported"


def test_the_shared_splitter_reports_no_frontmatter_honestly():
    assert fmx.split_frontmatter("# heading only") == (None, "# heading only")
    assert fmx.split_frontmatter("---\nname: unterminated\n") == (None, "---\nname: unterminated\n")
    fm, body = fmx.split_frontmatter("---\n- a\n- list\n---\nrest")
    assert fm is None and body.startswith("---")


def test_normalised_values_are_plain_json_types():
    assert fmx.json_safe(datetime.date(2024, 1, 2)) == "2024-01-02"
    assert fmx.json_safe({1: {"x": (1, 2)}}) == {"1": {"x": [1, 2]}}


# ── review round (H327): hostile values, the key:value fallback, Hermes semantics ──


def _discover(tmp_path, monkeypatch, skills: dict[str, str]) -> SkillLoader:
    from agents.core.skills import loader as loader_mod
    from agents.core.skills.approval import SkillApprovalStore

    root = tmp_path / "skills"
    for dirname, text in skills.items():
        (root / dirname).mkdir(parents=True)
        (root / dirname / "SKILL.md").write_text(text, encoding="utf-8")
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: None)
    loader = SkillLoader(approval_store=SkillApprovalStore(tmp_path / "private" / "approvals.json"))
    loader.discover()
    return loader


def _alias_bomb(fan: int) -> str:
    refs = lambda a: "[" + ", ".join([f"*{a}"] * fan) + "]"  # noqa: E731
    lines = ["---", "name: bomb", "x0: &a0 [" + ", ".join(["x"] * fan) + "]"]
    lines += [f"x{i}: &a{i} {refs(f'a{i - 1}')}" for i in range(1, 5)]
    lines += ["setup:"] + [f"  k{j}: *a4" for j in range(fan)] + ["---", ""]
    return "\n".join(lines)


def test_a_yaml_alias_bomb_is_bounded_in_total_nodes(tmp_path):
    import time

    started = time.monotonic()
    m = _manifest(tmp_path, _alias_bomb(64))  # ~2 KB of YAML, 64**6 nodes if expanded
    assert time.monotonic() - started < 5
    assert m["name"] == "bomb"

    def count(value):
        if isinstance(value, dict):
            return 1 + sum(count(v) for v in value.values())
        if isinstance(value, list):
            return 1 + sum(count(v) for v in value)
        return 1

    assert count(m["setup"]) <= fmx.MAX_NODES


@pytest.mark.parametrize("field", ["homepage", "description", "version", "author", "license",
                                   "compatibility", "name"])
def test_a_hex_integer_past_the_str_limit_does_not_break_discovery(tmp_path, monkeypatch, field):
    loader = _discover(tmp_path, monkeypatch, {
        "aaa-benign": "---\nname: benign\n---\nbody\n",
        "zzz-hostile": f"---\n{field}: 0x{'f' * 4000}\n" + ("" if field == "name" else "name: hostile\n")
        + "---\nbody\n",
    })
    assert "benign" in loader.skills and len(loader.skills) == 2


def test_non_finite_and_huge_numbers_never_reach_a_json_route(tmp_path):
    text = ("---\nname: numbers\nagents: [2024-01-01]\nmetadata:\n  hermes:\n    config:\n"
            "      - key: a\n        description: nan\n        default: .nan\n"
            "      - key: b\n        description: inf\n        default: [.inf, -.inf]\n"
            f"      - key: c\n        description: big\n        default: 0x{'f' * 40}\n---\n")
    m = _manifest(tmp_path, text)
    defaults = {c["key"]: c.get("default") for c in m["hermes"]["config"]}
    assert defaults == {"a": None, "b": [None, None], "c": None}
    assert m["agents"] == ["2024-01-01"]
    skill = Skill(m["name"], tmp_path, m)
    json.dumps(skill.to_dict(), allow_nan=False)  # Starlette's own setting


def test_one_unparseable_skill_does_not_stop_the_others(tmp_path, monkeypatch):
    from agents.core.skills import loader as loader_mod

    real = loader_mod.SkillLoader._parse_manifest

    def boom(self, path, **kw):
        if path.parent.name == "zzz-broken":
            raise RuntimeError("hostile manifest")
        return real(self, path, **kw)

    monkeypatch.setattr(loader_mod.SkillLoader, "_parse_manifest", boom)
    loader = _discover(tmp_path, monkeypatch, {"aaa": "---\nname: fine\n---\n", "zzz-broken": "---\nname: x\n---\n"})
    assert list(loader.skills) == ["fine"]


def test_the_signing_misconfiguration_still_stops_discovery(tmp_path, monkeypatch):
    from agents.core.skills import signing

    def refuse():
        raise signing.SkillSigningMisconfigured("no key")

    monkeypatch.setattr(signing, "require_signed", refuse)
    with pytest.raises(signing.SkillSigningMisconfigured):
        _discover(tmp_path, monkeypatch, {"aaa": "---\nname: fine\n---\n"})


def test_the_fallback_reads_top_level_keys_only_and_drops_matching_quotes(tmp_path):
    text = ('---\nname: "notes"\ndescription: fine: [broken\nmetadata:\n  name: weather\n'
            "agents: [jarvis, friday]\n---\nbody\n")
    m = _manifest(tmp_path, text)
    assert m["name"] == "notes"          # the nested name does not replace it, quotes dropped
    assert m["agents"] == ["jarvis", "friday"]


def test_a_heading_file_framed_by_fences_keeps_the_heading_dialect(tmp_path):
    text = "---\n# Weather Intel\n> Live weather.\n**Version:** 2.0\n**Agents:** jarvis\n---\n"
    m = _manifest(tmp_path, text)
    assert (m["name"], m["description"], m["version"], m["agents"]) == (
        "Weather Intel", "Live weather.", "2.0", ["jarvis"])


def test_a_byte_order_mark_does_not_hide_the_heading_dialect(tmp_path):
    m = _manifest(tmp_path, "", raw="\ufeff# weather\n> Live weather.\n".encode())
    assert m["name"] == "weather" and m["description"] == "Live weather."


def test_list_valued_author_and_license_are_joined(tmp_path):
    text = "---\nname: comfy\nauthor: [kshitijk4poor, alt-glitch, purzbeats]\nlicense: [MIT, Apache-2.0]\n---\n"
    m = _manifest(tmp_path, text)
    assert m["author"] == "kshitijk4poor, alt-glitch, purzbeats"
    assert m["license"] == "MIT, Apache-2.0"


def test_a_capped_name_never_ends_in_whitespace(tmp_path):
    m = _manifest(tmp_path, f"---\nname: {'a' * 63} tail\n---\n")
    assert m["name"] == "a" * 63


def test_a_second_skill_taking_the_same_registry_name_is_logged(tmp_path, monkeypatch, caplog):
    prefix = "x" * 64
    with caplog.at_level("WARNING", logger="jarvis.skills"):
        loader = _discover(tmp_path, monkeypatch, {
            "one": f"---\nname: {prefix}-read\n---\n", "two": f"---\nname: {prefix}-write\n---\n"})
    assert len(loader.skills) == 1
    assert any("replaces" in r.getMessage() and "one" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("flag", ["true", "yes", "1"])
def test_an_optional_flag_is_read_as_hermes_reads_it(tmp_path, flag):
    text = f"---\nname: o\nrequired_environment_variables:\n  - name: A_KEY\n    optional: {flag}\n---\n"
    assert _manifest(tmp_path, text)["required_environment_variables"][0]["optional"] is True


@pytest.mark.parametrize("value,expected", [
    ("macos, linux", ["macos, linux"]),   # one string is one name in Hermes, and matches nothing
    (["osx", "mac", "win64"], ["osx", "mac", "win64"]),   # not Hermes aliases: kept, match nothing
    (["darwin", "win", "win32", "MacOS"], ["macos", "windows"]),   # sys.platform prefixes
])
def test_platforms_follow_hermes_matching(value, expected):
    assert fmx.normalize_platforms(value) == expected


def test_environments_and_requires_apps_read_a_string_as_one_item(tmp_path):
    text = "---\nname: e\nenvironments: Docker, Kanban\nrequires_apps: [thing, ' other ']\n---\n"
    m = _manifest(tmp_path, text)
    assert m["environments"] == ["docker, kanban"]
    assert m["requires_apps"] == ["thing", "other"]
    assert _manifest(tmp_path, "---\nname: e\nrequires_apps: solo\n---\n")["requires_apps"] == ["solo"]


def test_an_indented_fence_inside_a_block_scalar_is_content(tmp_path):
    text = "---\nname: fenced\ndescription: |\n  intro\n  ---\n  more\n---\nbody\n"
    m = _manifest(tmp_path, text)
    assert m["description"] == "intro\n---\nmore"


def test_the_description_keeps_its_quotes(tmp_path):
    m = _manifest(tmp_path, "---\nname: q\ndescription: 'Reply with the word \"done\"'\n---\n")
    assert m["description"] == 'Reply with the word "done"'


def test_a_missing_description_falls_back_to_the_first_body_line(tmp_path):
    m = _manifest(tmp_path, "---\nname: nodesc\n---\n# Title\n\nFirst real line.\nSecond.\n")
    assert m["description"] == "First real line."


def test_identity_decisions_use_the_strict_parse():
    broken = "---\nname: imported\ndescription: bad: yaml: [x\n---\nbody"
    assert SkillImporter._extract_frontmatter(broken, strict=True) == {}
    assert SkillImporter._extract_frontmatter("---\nname: ok\n---\n", strict=True) == {"name": "ok"}


def test_the_hermes_identity_gate_refuses_a_name_only_the_fallback_finds():
    import inspect

    from agents.core.skills import importer

    source = inspect.getsource(importer)
    gate = source[source.index("Hermes content identity mismatch") - 400:]
    assert "_extract_frontmatter(text, strict=True)" in gate.split("Hermes content identity mismatch")[0]


def test_env_names_dedupe_first_wins_across_sources(tmp_path):
    text = ("---\nname: d\nrequired_environment_variables:\n  - name: SAME\n    prompt: first\n"
            "setup:\n  collect_secrets:\n    - env_var: SAME\n      prompt: second\n---\n")
    env = _manifest(tmp_path, text)["required_environment_variables"]
    assert [(e["name"], e["prompt"]) for e in env] == [("SAME", "first")]


def test_related_skills_prefer_metadata_hermes(tmp_path):
    text = "---\nname: r\nrelated_skills: [top]\nmetadata:\n  hermes:\n    related_skills: [nested]\n---\n"
    assert _manifest(tmp_path, text)["related_skills"] == ["nested"]


def test_depth_and_width_caps_hold():
    deep: dict = {}
    node = deep
    for _ in range(10):
        node["k"] = {}
        node = node["k"]
    out = fmx.json_safe(deep)
    depth = 0
    while isinstance(out, dict):
        out, depth = out.get("k"), depth + 1
    assert depth == 6
    assert len(fmx.json_safe({f"k{i}": i for i in range(100)})) == fmx.MAX_LIST_ITEMS


def test_command_entries_are_reduced_to_json_types(tmp_path):
    text = "---\nname: c\ncommands:\n  - command: go\n    since: 2024-01-01\n    weight: .nan\n---\n"
    commands = _manifest(tmp_path, text)["commands"]
    assert commands == [{"command": "go", "since": "2024-01-01", "weight": None}]


def test_discovery_reads_a_byte_order_marked_heading_file_from_the_snapshot(tmp_path, monkeypatch):
    from agents.core.skills import loader as loader_mod
    from agents.core.skills.approval import SkillApprovalStore

    root = tmp_path / "skills"
    (root / "bom-dir").mkdir(parents=True)
    (root / "bom-dir" / "SKILL.md").write_bytes("\ufeff# weather\n> Live weather.\n".encode())
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: None)
    loader = SkillLoader(approval_store=SkillApprovalStore(tmp_path / "private" / "approvals.json"))
    loader.discover()
    assert list(loader.skills) == ["weather"]
