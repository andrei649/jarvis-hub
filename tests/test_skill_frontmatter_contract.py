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
    raw = "﻿---\nname: bom-skill\ndescription: Written by a Windows editor.\n---\nBody\n".encode()
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
    "﻿---\nname: imported\n---\nbody",
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
