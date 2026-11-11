"""RB-2 — the alias covers every hub variable, measured from the source.

``NERVA_<X>`` is the preferred spelling of every ``JARVIS_<X>``. The alias applies to the
names in ``env_config.HUB_ENV_SUFFIXES`` (and three run-time families) and to nothing else,
so that list has to be the truth: this file reads every tracked text file outside
``docs/`` and ``tests/`` (Python, shell, batch, JavaScript, YAML, unit files, the
Dockerfile) and fails when a ``JARVIS_`` name anywhere in it is neither a hub variable
nor on the short reviewed list of names that are deliberately not one (a new variable
cannot ship without its ``NERVA_`` spelling), when a listed name is gone from the tree
(a stale entry), and when a ``NERVA_*`` variable of its own ever shares a suffix with a
``JARVIS_`` one (the two would silently become one variable). Prose (``docs/``) and
test fixtures (``tests/``, which invent names on purpose) are not variables' homes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
from agents.core import env_alias, env_config  # noqa: E402

_JARVIS = re.compile(r"(?<![A-Za-z0-9_])JARVIS_[A-Z0-9_]+")
_NERVA = re.compile(r"(?<![A-Za-z0-9_])NERVA_[A-Z0-9_]*[A-Z0-9]")
_NERVA_LITERAL = re.compile(r"""["'](NERVA_[A-Z0-9_]*[A-Z0-9])["']""")
# Reviewed: every JARVIS_ token in the tree that is deliberately NOT a hub variable with a
# NERVA_ spelling, and why. Adding a name here is a decision, not a way to get green.
NOT_VARIABLES = {
    # not environment variables at all
    "JARVIS_CHILD_ALLOWED_ENV",      # a Python constant (environments/__init__.py)
    "JARVIS_ACQUIRED_RESULT",        # the result-line prefix a sandboxed child prints
    "JARVIS_X",                      # the placeholder in comments and docs fixtures
    # JavaScript globals of the legacy HUD (agents/web/static/*.js) and a frontend constant
    "JARVIS_AGENT_META", "JARVIS_COLLAB", "JARVIS_DEMO", "JARVIS_FALLBACK_CALENDAR",
    "JARVIS_FALLBACK_NOTIFICATIONS", "JARVIS_FALLBACK_SYS", "JARVIS_FALLBACK_WEATHER", "JARVIS_GLYPHS",
    "JARVIS_PROJECTS", "JARVIS_SAMPLE_CONVERSATION", "JARVIS_TICKER", "JARVIS_TIERS", "JARVIS_TOOLS",
    "JARVIS_PRESENCE_GAP",
    # variables of a CI workflow, set and read inside .github/workflows only
    "JARVIS_EVAL_CACHE_PREFIX", "JARVIS_EVAL_CI_SMALL_MODEL", "JARVIS_EVAL_CI_SMALL_MODEL_ID",
    "JARVIS_NEO4J_LIVE",
    # JARVIS_-only on purpose (docs/FLAGS.md says so): nothing in the hub reads them
    "JARVIS_WORLDVIEW",              # a comment in the systemd env template
    "JARVIS_WORLDVIEW_MODE",         # the signal layer's test that this old name is IGNORED
}
# Prefix tokens (a name cut at an underscore in prose or a prefix tuple) that are not families.
NOT_FAMILIES = {"JARVIS_AUX_"}       # mobile/PARITY.md writes "JARVIS_AUX_*" for the AUX_* variables
# Longer family tokens the declared families already cover.
_FAMILY_TOKENS = {"JARVIS_ROLE_", "JARVIS_ROLE_MAIN_", "JARVIS_ROLE_VIDEO_FALLBACK_", "JARVIS_VLM_",
                  "JARVIS_TERMINAL_SSH_"}


def _families() -> tuple[str, ...]:
    return tuple("JARVIS_" + prefix for prefix in env_config.HUB_ENV_FAMILIES)


def _sources() -> list[Path]:
    return [*sorted((ROOT / "agents").rglob("*.py")), *sorted((ROOT / "scripts").rglob("*.py")),
            ROOT / "serve.py"]


def _tracked() -> list[Path]:
    """Every tracked file outside docs/ and tests/ (and the two ledgers), as git lists them."""
    import subprocess

    listed = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if listed.returncode != 0:
        pytest.skip("not a git checkout: the tracked-file inventory needs git")
    return [ROOT / name for name in listed.stdout.splitlines()
            if name and not name.startswith(("docs/", "tests/")) and name not in ("BACKLOG.md", "CHANGELOG.md")]


def _tokens(pattern: re.Pattern, paths=None) -> set[str]:
    found: set[str] = set()
    for path in (_sources() if paths is None else paths):
        if path.name == "env_config.py":            # the list itself
            continue
        try:
            found |= set(pattern.findall(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):       # a binary or a missing file is not a home for names
            continue
    return found


@pytest.fixture(scope="module")
def jarvis_tokens() -> set[str]:
    """Every JARVIS_ token in every tracked text file outside docs/ and tests/."""
    return _tokens(_JARVIS, _tracked())


def test_the_scan_reaches_beyond_the_python_tree(jarvis_tokens):
    """The names the first inventory missed live in a shell script, a batch file, a
    JavaScript module and a skill: they are found now, and each has both spellings."""
    for name in ("JARVIS_SIGNAL_LAYER", "JARVIS_SIGNAL_LAYER_MODE", "JARVIS_TZ"):
        assert name in jarvis_tokens and env_config.is_hub_name(name), name
    for path, both in (("start.sh", ("NERVA_SIGNAL_LAYER", "NERVA_SIGNAL_LAYER_MODE", "NERVA_HUD", "NERVA_PORT")),
                       ("START.bat", ("NERVA_SIGNAL_LAYER", "NERVA_SIGNAL_LAYER_MODE", "NERVA_HUD")),
                       ("services/signal-layer/src/config.mjs", ("NERVA_SIGNAL_LAYER_MODE",)),
                       ("agents/cli/completion.py", ("NERVA_HOME", "NERVA_MEMORY_DIR"))):
        text = (ROOT / path).read_text(encoding="utf-8")
        for name in both:
            assert name in text and name.replace("NERVA_", "JARVIS_", 1) in text, (path, name)
    # the calendar skill is a signed, shipped source (optional since H696, main #1346): it
    # keeps its one read of JARVIS_TZ, in the hub's own process, where the fold has already
    # brought NERVA_TZ to that name
    assert 'os.environ.get("JARVIS_TZ"' in (ROOT / "optional-skills/calendar/main.py").read_text(encoding="utf-8")
    env = {"NERVA_TZ": "Europe/Paris"}
    env_alias.normalize(env)
    assert env["JARVIS_TZ"] == "Europe/Paris" and "NERVA_TZ" not in env
    stale = sorted(NOT_VARIABLES - jarvis_tokens - {"JARVIS_X"})
    assert not stale, stale                                             # no stale exception


def test_the_list_is_the_source(jarvis_tokens):
    fixed = {token for token in jarvis_tokens if not token.endswith("_")} - NOT_VARIABLES
    missing = sorted(name for name in fixed if not env_config.is_hub_name(name))
    assert not missing, (
        f"{missing} appear in the tree and are not in env_config.HUB_ENV_SUFFIXES (stored without the "
        "JARVIS_ prefix): add them and make their reader honour both spellings, or their NERVA_ "
        "spelling is silently ignored (RB-2). A name that is deliberately not a hub variable goes on "
        "NOT_VARIABLES in this file, with the reason.")
    listed = {"JARVIS_" + suffix for suffix in env_config.HUB_ENV_SUFFIXES}
    stale = listed - fixed
    assert not stale, f"{sorted(stale)} are listed in env_config.HUB_ENV_SUFFIXES and no longer in the source"
    in_a_family = sorted(name for name in listed if name.startswith(_families()))
    assert not in_a_family, f"{in_a_family}: a family prefix already covers these"
    assert len(fixed) > 200 and len(listed) > 180              # the scan found the tree


def test_every_family_token_is_classified(jarvis_tokens):
    families = {token for token in jarvis_tokens if token.endswith("_")} - NOT_FAMILIES
    aliased = {token for token in families if token.startswith(_families())}
    assert aliased == _FAMILY_TOKENS
    unaliased = {"JARVIS_" + prefix for prefix in env_config.UNALIASED_FAMILIES}
    assert families - aliased == unaliased                            # the child's control channel
    for prefix in env_config.UNALIASED_FAMILIES:
        assert env_config.other_spelling("JARVIS_" + prefix + "DIR") is None
        assert env_config.other_spelling("NERVA_" + prefix + "DIR") is None


def test_the_alias_resolves_for_every_hub_variable(jarvis_tokens):
    """Each name, measured from the source: the map goes both ways, a pair resolves from
    either spelling, and the fold puts a NERVA_ value where the hub reads it."""
    names = sorted({token for token in jarvis_tokens if not token.endswith("_")} - NOT_VARIABLES)
    names += ["JARVIS_ROLE_VISION_MODEL", "JARVIS_ROLE_VIDEO_FALLBACK_2_KEY", "JARVIS_VLM_PRESET",
              "JARVIS_TERMINAL_SSH_HOSTS"]
    for name in names:
        new = "NERVA_" + name[len("JARVIS_"):]
        assert env_config.other_spelling(name) == new, name
        assert env_config.other_spelling(new) == name, name
        assert env_alias.canonical(new) == name and env_alias.preferred_name(name) == new
        assert env_config.resolve_spellings({new: "v"}, name) == ("v", new), name
        assert env_config.resolve_spellings({name: "v"}, new) == ("v", name), name
        env = {new: "v"}
        env_alias.normalize(env)
        assert env == {name: "v", env_alias.MARKER: name}, name


def test_no_variable_of_its_own_shares_a_suffix_with_a_hub_variable():
    """A NERVA_* variable the code reads as its own (NERVA_HUB_URL, NERVA_WORKSPACE*, …)
    must never also be the other spelling of a JARVIS_ one: the alias would merge two
    different variables. "Reads as its own" is a quoted NERVA_ name in the hub's source —
    how a read, a module constant and a tuple of names all spell it."""
    native: set[str] = set()
    for path in _sources():
        if path.name == "env_config.py":
            continue
        native |= set(_NERVA_LITERAL.findall(path.read_text(encoding="utf-8", errors="replace")))
    assert {"NERVA_HUB_URL", "NERVA_WORKSPACE", "NERVA_PUBLIC_PROFILE", "NERVA_SAVE_TRAJECTORIES",
            "NERVA_SERVICE_WRAPPER", "NERVA_WORKSPACE_SSO_SECRET"} <= native          # the scan works
    # The two places that name a hub variable's new spelling on purpose: the operator
    # script that reads the admin token itself, and the --safe-mode switch that clears it.
    on_purpose = {"NERVA_ADMIN_TOKEN", "NERVA_SAFE_MODE"}
    collided = sorted(name for name in native - on_purpose if env_config.other_spelling(name))
    assert not collided, (
        f"{collided}: a NERVA_ name the code reads is also the other spelling of a JARVIS_ variable. "
        "Rename one of the two — they are read as ONE variable (RB-2).")
    for name in sorted(native - on_purpose):
        assert env_alias.canonical(name) == name            # its own variable: never folded
        env = {name: "kept"}
        env_alias.normalize(env)
        assert env == {name: "kept"}
        assert name[len("NERVA_"):] not in env_config.HUB_ENV_SUFFIXES


def test_names_outside_the_hub_are_never_touched():
    for name in ("PATH", "OPENAI_API_KEY", "NERVA_SOMEBODY_ELSES", "JARVIS_NOT_A_HUB_NAME", "NERVA_", "JARVIS_",
                 "nerva_port", "XNERVA_PORT", None, 7):
        assert env_config.other_spelling(name) is None
    env = {"NERVA_SOMEBODY_ELSES": "1", "NERVA_HUB_URL": "http://h", "NERVA_WORKSPACE": "1"}
    assert env_alias.normalize(dict(env)).spelling == {} and env_alias.normalized(env) == env


#: What a launcher in this repo sets unconditionally, under the JARVIS_ spelling.
LAUNCHER_PINNED = {"JARVIS_HOST", "JARVIS_PORT", "JARVIS_HOME", "JARVIS_SHUTDOWN_TIMEOUT",
                   "JARVIS_RUNTIME_LOG", "JARVIS_RUNTIME_STATE"}


def test_the_launchers_pin_exactly_the_documented_names():
    """Each launcher's unconditional JARVIS_ assignments, measured from the file, against
    the table in docs/FLAGS.md — a new pin cannot appear without being documented."""
    flags = (ROOT / "docs" / "FLAGS.md").read_text(encoding="utf-8")
    table = flags.split("### Variables a launcher pins", 1)[1]
    pins = {
        "Dockerfile": (r"^\s+(JARVIS_[A-Z_]+)=", {"JARVIS_HOST", "JARVIS_PORT", "JARVIS_HOME"}),
        "docker-compose.yml": (r"^\s+(JARVIS_[A-Z_]+):", {"JARVIS_HOST", "JARVIS_PORT", "JARVIS_HOME"}),
        "docker-compose.quickstart.yml": (r"^\s+(JARVIS_[A-Z_]+):", {"JARVIS_HOST", "JARVIS_PORT", "JARVIS_HOME"}),
        "deploy/systemd/jarvis-hub.service": (r"^Environment=(JARVIS_[A-Z_]+)=",
                                              {"JARVIS_HOST", "JARVIS_PORT", "JARVIS_SHUTDOWN_TIMEOUT", "JARVIS_HOME"}),
        "deploy/systemd/jarvis-runtime.service": (r"^Environment=(JARVIS_[A-Z_]+)=",
                                                  {"JARVIS_HOME", "JARVIS_RUNTIME_LOG", "JARVIS_RUNTIME_STATE"}),
        "deploy/windows/install-service.ps1": (r'^\s+"(JARVIS_[A-Z_]+)=',
                                               {"JARVIS_HOST", "JARVIS_PORT", "JARVIS_SHUTDOWN_TIMEOUT", "JARVIS_HOME"}),
    }
    seen: set[str] = set()
    for path, (pattern, expected) in pins.items():
        found = set(re.findall(pattern, (ROOT / path).read_text(encoding="utf-8"), re.M))
        assert found == expected, (path, sorted(found))
        row = next(line for line in table.splitlines() if f"`{path}`" in line and found <= set(re.findall(r"`(JARVIS_[A-Z_]+)`", line)))
        assert row, path
        seen |= found
    assert seen == LAUNCHER_PINNED
    # a pin that only restated the code's default is gone: nothing to collide with
    assert "JARVIS_HUD" not in (ROOT / "Dockerfile").read_text(encoding="utf-8").split("# RB-2")[0]
    assert not re.search(r"^Environment=JARVIS_LOG_LEVEL", (ROOT / "deploy/systemd/jarvis-hub.service").read_text(encoding="utf-8"), re.M)
    # the scripts that only default a variable look at both spellings before they do
    start_sh = (ROOT / "start.sh").read_text(encoding="utf-8")
    assert 'if [ -z "${NERVA_HUD:-}" ]; then export JARVIS_HUD=' in start_sh
    assert 'if not defined JARVIS_HUD if not defined NERVA_HUD set "JARVIS_HUD=v2"' in (ROOT / "START.bat").read_text(encoding="utf-8")


def test_env_example_spells_every_hub_variable_the_new_way_and_says_the_old_one_works():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    # the only JARVIS_ names in it: the header's list of what a launcher pins under that spelling
    old = sorted(set(_JARVIS.findall(text)) - {"JARVIS_"})
    assert old == sorted(LAUNCHER_PINNED), f"{old}: .env.example documents the NERVA_ spelling"
    assert "JARVIS_<X>" in text and "still works" in text and "Pinned by the launcher" in text
    assignments = set(re.findall(r"^#?[ \t]*(JARVIS_[A-Z0-9_]+)=", text, re.M))
    assert assignments == set(), f"{sorted(assignments)}: a line of the example sets the old spelling"
    # nothing in it would collide with a pin when compose passes the file into the container,
    # and nothing in it is built from a reference
    for name in LAUNCHER_PINNED:
        assert not re.search(rf"^NERVA_{name[len('JARVIS_'):]}=", text, re.M), name
    assert "${" not in "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    declared = set(re.findall(r"^#?[ \t]*(NERVA_[A-Z0-9_]+)=", text, re.M))
    aliased = {name for name in declared if env_config.other_spelling(name)}
    assert len(aliased) > 80
    # every NERVA_ name it declares is a real variable: an alias of a hub variable, or one
    # the code reads under that very name
    own = _tokens(_NERVA)
    unknown = sorted(declared - aliased - own)
    assert not unknown, f"{unknown}: declared in .env.example, read by nothing"


def test_the_docs_say_how_the_two_spellings_behave():
    flags = (ROOT / "docs" / "FLAGS.md").read_text(encoding="utf-8")
    assert "`NERVA_<X>` and `JARVIS_<X>` are one variable" in flags
    assert "NERVA_WINS_ON_CONFLICT" not in flags and "wins and one warning" not in flags
    for phrase in ("preferred spelling", "deprecated", "refuses to", "nerva doctor", "Variables a launcher pins",
                   "under the spelling\nthe launcher uses", "exit status 78", "--token-env NERVA_USER_TOKEN"):
        assert phrase in flags, phrase
