"""The agent-generated skill loop must produce a skill whose command actually runs.

`SkillLoader.generate_skill()` writes a `main.py` from a template. Two loader contracts
constrain that template, and CDX-8's quarantine tests never exercised either:

* `Skill.execute()` dispatches a registered command as ``cmd_fn(args, context)`` — or
  ``cmd_fn(args)`` when there is no context (`loader.py:177-179`). A 3-parameter function
  registered as a command raises `TypeError` on every call, which `execute()` turns into a
  user-visible ``[skill:X] error: …``.
* `_load_skill()` resolves every `get_commands()` name with ``getattr(mod, name)``
  (`loader.py:284-286`). A name with no module-level function raises `AttributeError`,
  aborting the load block and logging a misleading "Failed to load skill module".

Plus: `command_name` is untrusted LLM output (`orchestrator.py` parses it out of a
``[learn:task|steps|cmd]`` block) that is string-substituted into generated Python source,
so it must be coerced to a bare identifier before it is written.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.skills import loader as loader_mod  # noqa: E402
from agents.core.skills.approval import SkillApprovalStore  # noqa: E402
from agents.core.skills.loader import SkillLoader  # noqa: E402


@pytest.fixture
def loader(tmp_path, monkeypatch):
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tmp_path)
    return SkillLoader(approval_store=SkillApprovalStore(tmp_path / "private" / "approvals.json"))


def _gen(loader, task="organize the morning inbox", cmd="tidy_inbox"):
    return loader.generate_skill(
        agent_id="pepper",
        task_description=task,
        solution_steps=["read inbox", "label", "archive"],
        command_name=cmd,
    )


def _registered(loader, skill_dir):
    """Generated skills register under the manifest title, not the dir slug."""
    for skill in loader.skills.values():
        if Path(skill.path) == Path(skill_dir):
            return skill
    return None


def _approved(loader, tmp_path, cmd="tidy_inbox"):
    """Generate + owner-approve a skill; return (skill, skill_dir)."""
    name = _gen(loader, cmd=cmd)
    assert name is not None
    assert loader.approve_generated_skill(name) is True
    skill_dir = tmp_path / name
    skill = _registered(loader, skill_dir)
    assert skill is not None and skill.module is not None
    return skill, skill_dir


# ── the dispatcher contract: a generated command must actually execute ────────


async def test_generated_command_executes_with_context(loader, tmp_path):
    skill, _ = _approved(loader, tmp_path)
    out = await skill.execute("tidy_inbox", "inbox", {"user": "andrei"})
    assert not out.startswith(f"[skill:{skill.name}] error:"), out
    assert out.strip()


async def test_generated_command_executes_without_context(loader, tmp_path):
    """The `cmd_fn(args)` branch of execute() (loader.py:179) — no context supplied."""
    skill, _ = _approved(loader, tmp_path)
    out = await skill.execute("tidy_inbox", "inbox")
    assert not out.startswith(f"[skill:{skill.name}] error:"), out
    assert out.strip()


async def test_module_handle_fallback_still_works(loader, tmp_path):
    """`handle()` stays the 3-arg module-level fallback (loader.py:184-186)."""
    skill, _ = _approved(loader, tmp_path)
    assert hasattr(skill.module, "handle")
    out = await skill.module.handle("tidy_inbox", "inbox", {})
    assert isinstance(out, str) and out.strip()


def test_get_commands_names_resolve_on_the_module(loader, tmp_path):
    """Every name in get_commands() must be getattr-able (loader.py:284-286)."""
    skill, _ = _approved(loader, tmp_path)
    names = skill.module.get_commands()
    assert names
    for name in names:
        assert hasattr(skill.module, name), (
            f"get_commands() names {name!r}, module does not define it"
        )


def test_approved_skill_loads_without_a_failure_warning(loader, tmp_path, caplog):
    name = _gen(loader)
    assert loader.approve_generated_skill(name) is True
    caplog.clear()
    with caplog.at_level("WARNING"):
        loader.skills.clear()
        loader._load_skill(tmp_path / name)
    assert "Failed to load skill module" not in caplog.text


def test_registered_command_matches_the_manifest(loader, tmp_path):
    """The SKILL.md `## Commands` entry and the registered command are the same name."""
    skill, _ = _approved(loader, tmp_path)
    documented = [c["command"] for c in skill.commands_meta]
    assert documented, "generated SKILL.md documents no command"
    for cmd in documented:
        assert cmd in skill.commands, f"{cmd!r} documented but not registered"


# ── command_name is untrusted LLM output substituted into Python source ───────

HOSTILE_COMMAND_NAMES = [
    'x", print("pwned")) or ("',  # break out of the register_command string literal
    "run\n\nimport os; os.system('id')",
    "tidy-inbox",  # not an identifier
    "123start",  # identifiers cannot start with a digit
    "def",  # reserved word
    "",
]


@pytest.mark.parametrize("hostile", HOSTILE_COMMAND_NAMES)
def test_generated_main_py_is_always_valid_python(loader, tmp_path, hostile):
    """A hostile command_name must never produce a broken or injected main.py."""
    name = _gen(loader, cmd=hostile)
    if name is None:
        return  # refused outright is also a valid outcome
    src = (tmp_path / name / "main.py").read_text(encoding="utf-8")
    compile(src, "main.py", "exec")  # must parse
    assert "os.system" not in src and 'print("pwned")' not in src


@pytest.mark.parametrize("hostile", HOSTILE_COMMAND_NAMES)
def test_hostile_command_name_becomes_an_identifier(loader, tmp_path, hostile):
    name = _gen(loader, cmd=hostile)
    if name is None:
        return
    skill = _registered(loader, tmp_path / name)
    assert skill is not None
    # Generated skills stay quarantined (no module), so read the names off the manifest.
    commands = [c["command"] for c in skill.commands_meta]
    assert commands, "generated SKILL.md documents no command"
    for cmd in commands:
        assert cmd.isidentifier(), f"{cmd!r} is not a valid Python identifier"


# ── catalog ratchet: shipped skills answer the commands they document ────────


def test_shipped_skills_resolve_their_documented_commands():
    """Every `## Commands` entry in skills/*/SKILL.md must resolve to something callable.

    A manifest-only skill returns "" from `execute()` (loader.py:191); the orchestrator's
    `if result:` then falls through to the normal agent path, so this is a soft gap rather
    than a dead end — but an *undeclared* one still means the catalog advertises a command
    the skill does not implement. Declared seams are exempt via the one existing escape
    set, `INTENTIONALLY_SEAM`, so a new manifest-only skill has to be a conscious entry
    there rather than a silent addition.
    """
    from tests.test_capability_readiness_matrix import INTENTIONALLY_SEAM

    live = SkillLoader()
    live.discover()
    unresolved = []
    for skill in live.skills.values():
        if f"skill:{skill.name}" in INTENTIONALLY_SEAM:
            continue
        for meta in skill.commands_meta:
            cmd = meta.get("command")
            if not cmd:
                continue
            if cmd in skill.commands:
                continue
            if skill.module is not None and hasattr(skill.module, "handle"):
                continue
            if skill.sandboxed:  # quarantined/untrusted: not loaded by design
                continue
            unresolved.append(f"{skill.name}:{cmd}")
    assert not unresolved, f"documented commands with no implementation: {unresolved}"
