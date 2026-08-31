"""H23.30 residual closed: fail-closed on a set-but-unparseable posture flag (DRA-07/DRA-14).

`env_config.truthy` (AUD-14) resolves an unrecognized spelling to the flag's *declared
default*, in both directions — one parse home, no local boolean dialects. That convention is
right and stays exactly as it is. It has one consequence this guard exists for:
`NERVA_PUBLIC_PROFILE` is a default-off opt-in whose "on" position is the *safe* one, so
`NERVA_PUBLIC_PROFILE=pubic` resolves to "private" and a public demo box seeds the owner's
family into a stranger's graph (tests/test_public_profile_seed_gate.py).

So the parse does not change; the *boot* does. `boot_guards.assert_parseable_posture_flags`
refuses to start when a parse-critical flag is set to something no spelling recognizes, and
runs before every other guard so the refusal happens before anything constructs a graph.
"""

import inspect
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import boot_guards, env_config  # noqa: E402

RECOGNIZED = ("1", "true", "TRUE", " yes ", "on", "0", "false", "no", "off",
              "disable", "disabled", "", "   ")
TYPOS = ("pubic", "publlic", "y", "TRUE!", "enabled")


def _clean_env(monkeypatch):
    for var in ("JARVIS_USER_TOKEN", "JARVIS_ADMIN_TOKEN", "JARVIS_ALLOW_INSECURE_BIND",
                "JARVIS_HARDENED", "JARVIS_AUDIT_KEY", "JARVIS_HOST",
                "NERVA_PUBLIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)


# ── the guard itself ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("typo", TYPOS)
def test_a_set_but_unparseable_posture_flag_refuses_to_start(monkeypatch, typo):
    _clean_env(monkeypatch)
    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", typo)

    with pytest.raises(SystemExit) as excinfo:
        boot_guards.assert_parseable_posture_flags()
    message = str(excinfo.value)
    assert "NERVA_PUBLIC_PROFILE" in message
    assert "1/true/yes/on" in message and "0/false/no/off" in message
    # env_config's contract is "never log values" — the guard names the variable, not the
    # value, so a mistyped *secret* can never be echoed by a future entry in the tuple.
    # (Checked as a standalone token, since a short typo like "y" is a substring of
    # ordinary English words in the message.)
    assert typo.strip() not in message.replace(".", " ").split()
    assert repr(typo) not in message


@pytest.mark.parametrize("spelling", RECOGNIZED)
def test_every_recognized_spelling_boots(monkeypatch, spelling):
    _clean_env(monkeypatch)
    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", spelling)
    boot_guards.assert_parseable_posture_flags()  # must not raise


def test_unset_is_not_malformed(monkeypatch):
    _clean_env(monkeypatch)
    boot_guards.assert_parseable_posture_flags()


# ── it runs from enforce_boot_posture, first ─────────────────────────────────
def test_enforce_boot_posture_refuses_the_typo(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "pubic")

    with pytest.raises(SystemExit) as excinfo:
        boot_guards.enforce_boot_posture()
    assert "NERVA_PUBLIC_PROFILE" in str(excinfo.value)


def test_the_parse_guard_runs_before_the_bind_guard(monkeypatch):
    """Order matters: the refusal must land before anything touches the graph."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "pubic")
    monkeypatch.setenv("JARVIS_HOST", "0.0.0.0")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "tok")

    with pytest.raises(SystemExit) as excinfo:
        boot_guards.enforce_boot_posture()
    assert "NERVA_PUBLIC_PROFILE" in str(excinfo.value)


def test_enforce_boot_posture_is_still_a_noop_on_a_clean_env(monkeypatch):
    _clean_env(monkeypatch)
    boot_guards.enforce_boot_posture()


# ── both documented entry points ─────────────────────────────────────────────
def test_both_entry_points_run_the_new_guard():
    """`serve.py` calls the guards individually, so the lifespan pin is not enough."""
    import serve
    from agents import web

    assert "enforce_boot_posture" in inspect.getsource(web.lifespan)
    assert "assert_parseable_posture_flags" in inspect.getsource(boot_guards.enforce_boot_posture)
    assert serve.assert_parseable_posture_flags is boot_guards.assert_parseable_posture_flags
    assert "assert_parseable_posture_flags" in inspect.getsource(serve.main)


# ── the env_config helpers, unit level ───────────────────────────────────────
def test_is_recognized_bool_covers_the_whole_spelling_table():
    for spelling in env_config.TRUTHY_SPELLINGS | env_config.FALSY_SPELLINGS:
        assert env_config.is_recognized_bool(spelling) is True
        assert env_config.is_recognized_bool(spelling.upper()) is True
    for junk in ("pubic", "y", "n", "enabled", "2", "TRUE!"):
        assert env_config.is_recognized_bool(junk) is False
    assert env_config.is_recognized_bool(None) is False


def test_env_flag_is_malformed_only_for_a_deliberate_unparseable_value(monkeypatch):
    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "pubic")
    assert env_config.env_flag_is_malformed("NERVA_PUBLIC_PROFILE") is True
    for benign in ("on", "off", "", "   "):
        monkeypatch.setenv("NERVA_PUBLIC_PROFILE", benign)
        assert env_config.env_flag_is_malformed("NERVA_PUBLIC_PROFILE") is False
    monkeypatch.delenv("NERVA_PUBLIC_PROFILE", raising=False)
    assert env_config.env_flag_is_malformed("NERVA_PUBLIC_PROFILE") is False


def test_the_aud_14_parse_convention_is_deliberately_unchanged(monkeypatch):
    """The guard stops the boot; it does not add a second boolean dialect."""
    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "pubic")
    assert env_config.env_flag("NERVA_PUBLIC_PROFILE") is False
    assert env_config.truthy("pubic", default=True) is True
