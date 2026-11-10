"""RB-2 — the alias covers every hub variable, measured from the source.

``NERVA_<X>`` is the preferred spelling of every ``JARVIS_<X>``. The alias applies to the
names in ``env_config.HUB_ENV_SUFFIXES`` (and three run-time families) and to nothing else,
so that list has to be the truth: this file reads ``agents/``, ``scripts/`` and
``serve.py`` and fails when a ``JARVIS_`` name in the source is missing from it (a new
variable cannot ship without its ``NERVA_`` spelling), when a listed name is gone from
the source (a stale entry), and when a ``NERVA_*`` variable of its own ever shares a
suffix with a ``JARVIS_`` one (the two would silently become one variable).
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
# Tokens in the source that look like a variable and are not one: a Python constant and
# a result-line prefix a sandboxed child prints.
NOT_VARIABLES = {"JARVIS_CHILD_ALLOWED_ENV", "JARVIS_ACQUIRED_RESULT", "JARVIS_X"}
# Longer family tokens the declared families already cover.
_FAMILY_TOKENS = {"JARVIS_ROLE_", "JARVIS_ROLE_MAIN_", "JARVIS_ROLE_VIDEO_FALLBACK_", "JARVIS_VLM_",
                  "JARVIS_TERMINAL_SSH_"}


def _families() -> tuple[str, ...]:
    return tuple("JARVIS_" + prefix for prefix in env_config.HUB_ENV_FAMILIES)


def _sources() -> list[Path]:
    return [*sorted((ROOT / "agents").rglob("*.py")), *sorted((ROOT / "scripts").rglob("*.py")),
            ROOT / "serve.py"]


def _tokens(pattern: re.Pattern) -> set[str]:
    found: set[str] = set()
    for path in _sources():
        if path.name == "env_config.py":            # the list itself
            continue
        found |= set(pattern.findall(path.read_text(encoding="utf-8", errors="replace")))
    return found


@pytest.fixture(scope="module")
def jarvis_tokens() -> set[str]:
    return _tokens(_JARVIS)


def test_the_list_is_the_source(jarvis_tokens):
    fixed = {token for token in jarvis_tokens if not token.endswith("_")} - NOT_VARIABLES
    missing = sorted(name for name in fixed if not env_config.is_hub_name(name))
    assert not missing, (
        f"{missing} are read by the hub and are not in env_config.HUB_ENV_SUFFIXES (stored without the "
        "JARVIS_ prefix): add them, or their NERVA_ spelling is silently ignored (RB-2).")
    listed = {"JARVIS_" + suffix for suffix in env_config.HUB_ENV_SUFFIXES}
    stale = listed - fixed
    assert not stale, f"{sorted(stale)} are listed in env_config.HUB_ENV_SUFFIXES and no longer in the source"
    in_a_family = sorted(name for name in listed if name.startswith(_families()))
    assert not in_a_family, f"{in_a_family}: a family prefix already covers these"
    assert len(fixed) > 200 and len(listed) > 180              # the scan found the tree


def test_every_family_token_is_classified(jarvis_tokens):
    families = {token for token in jarvis_tokens if token.endswith("_")}
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
        env_alias.normalize(env, quiet=True)
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


def test_the_ordinary_knobs_are_hub_variables_and_none_is_a_credential_or_a_posture_flag():
    """NERVA wins on a disagreement only for this reviewed list; everything else refuses.
    The list may not grow a name that carries a secret, a switch or a location."""
    from agents.core.env_provenance import (
        FROM_PROCESS_ONLY,
        READ_AGAIN_AFTER_LOAD,
        SPLIT_NOTES,
        masked,
    )
    from agents.core.environments import SECRET_ENV_SUBSTRINGS

    assert env_config.NERVA_WINS_ON_CONFLICT <= env_config.HUB_ENV_SUFFIXES
    wins = {"JARVIS_" + suffix for suffix in env_config.NERVA_WINS_ON_CONFLICT}
    forbidden = ("ALLOW", "HARDEN", "STRICT", "SAFE", "TRUST", "EGRESS", "AUTH", "HOME", "ROOT", "DIR", "PATH",
                 "HOST", "URL", "ORIGIN", "PROFILE", "ENABLE", "DISABLE", "REQUIRE", "LIVE", "OPEN", "PAIRING",
                 "MEDIATION", "KERNEL", "GRANT", "POLICY", "FILE", "DOMAIN", "CSP", "CORS", "RATE", "TEST",
                 "FAKE", "FAULT", "ENV", "TLS", "CA_", "REDACT", "ISOLAT", "SANDBOX", "PLUGIN", "SKILL", "MCP")
    for name in sorted(wins):
        assert not masked(name), name
        assert not any(part in name for part in SECRET_ENV_SUBSTRINGS), name
        assert not any(part in name[len("JARVIS_"):] for part in forbidden), name
        assert not env_alias.refuses_on_conflict(name)
    assert not wins & (FROM_PROCESS_ONLY | READ_AGAIN_AFTER_LOAD | set(SPLIT_NOTES))
    for name in ("JARVIS_HARDENED", "JARVIS_STRICT_EGRESS", "JARVIS_ALLOW_INSECURE_BIND", "JARVIS_ADMIN_TOKEN",
                 "JARVIS_USER_TOKEN", "JARVIS_TRUSTED_PROXIES", "JARVIS_TRUSTED_PROXY", "JARVIS_HOME",
                 "JARVIS_USER_HOME", "JARVIS_SAFE_MODE", "JARVIS_AUDIT_KEY", "JARVIS_CHANNEL_OPEN",
                 "JARVIS_CHANNEL_PAIRING", "JARVIS_TASK_MEDIATION", "JARVIS_ALLOWED_HOSTS", "JARVIS_HOST",
                 "JARVIS_PROFILE", "JARVIS_APP_ROOT", "JARVIS_MEMORY_DIR", "JARVIS_ACTION_KERNEL",
                 "JARVIS_ROLE_APPROVAL_JUDGE_KEY", "JARVIS_ROLE_ANYTHING_NEW", "JARVIS_LOG_REDACTION"):
        assert env_alias.refuses_on_conflict(name), name
        assert env_alias.refuses_on_conflict("NERVA_" + name[len("JARVIS_"):]), name


def test_env_example_spells_every_hub_variable_the_new_way_and_says_the_old_one_works():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    old = sorted(set(_JARVIS.findall(text)) - {"JARVIS_"})
    assert old == [], f"{old}: .env.example documents the NERVA_ spelling (one note says JARVIS_ still works)"
    assert "JARVIS_<X>" in text and "still works" in text
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
    for phrase in ("preferred spelling", "deprecated", "refuses to", "NERVA_WINS_ON_CONFLICT", "nerva doctor"):
        assert phrase in flags, phrase
