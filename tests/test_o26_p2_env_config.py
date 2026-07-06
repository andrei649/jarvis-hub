"""
test_o26_p2_env_config.py — ORIZONT 26 P2.1 (AUD-14): one env_config, one truthy().

Three layers:
1. the primitives — spelling matrix, default direction both ways, garbage
   never raises and never flips a flag away from its declared default;
2. the convention guard — a source scan that fails on any NEW ad-hoc
   boolean-parse of an env read outside env_config (the ratchet that keeps
   the count of truthy conventions at exactly one);
3. pins for the deliberate behavior flips the consolidation makes (each
   one moves a mis-spelled or case-mangled value from "silently wrong" to
   "honors the operator's intent" or to the flag's declared default).
"""

import re
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.env_config import (  # noqa: E402
    env_flag,
    env_float,
    env_int,
    env_int_map,
    env_json_object,
    env_list,
    env_str,
    truthy,
)

VAR = "JARVIS_TEST_P21_FLAG"


# ── layer 1: the primitives ──────────────────────────────────────────────────

@pytest.mark.parametrize("spelling", ["1", "true", "yes", "on", "TRUE", "Yes", " on ", "ON"])
def test_truthy_spellings(spelling):
    assert truthy(spelling) is True
    assert truthy(spelling, default=False) is True


@pytest.mark.parametrize("spelling", ["0", "false", "no", "off", "disable", "disabled",
                                      "FALSE", "Off", " 0 ", "DISABLED"])
def test_falsy_spellings(spelling):
    assert truthy(spelling, default=True) is False
    assert truthy(spelling) is False


@pytest.mark.parametrize("junk", [None, "", "   ", "banana", "yess", "2", "enabled?"])
def test_unknown_resolves_to_default_both_directions(junk):
    """A typo can never flip a flag away from its declared posture."""
    assert truthy(junk, default=False) is False
    assert truthy(junk, default=True) is True


def test_truthy_accepts_non_strings():
    assert truthy(True) is True and truthy(False, default=True) is False
    assert truthy(1) is True and truthy(0, default=True) is False


def test_env_flag_unset_uses_default(monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    assert env_flag(VAR) is False
    assert env_flag(VAR, default=True) is True


def test_env_flag_reads_at_call_time(monkeypatch):
    monkeypatch.setenv(VAR, "1")
    assert env_flag(VAR) is True
    monkeypatch.setenv(VAR, "0")
    assert env_flag(VAR, default=True) is False


def test_env_int_and_float_never_raise(monkeypatch):
    for bad in ("", "  ", "abc", "1.5x"):
        monkeypatch.setenv(VAR, bad)
        assert env_int(VAR, 42) == 42
    monkeypatch.setenv(VAR, " 7 ")
    assert env_int(VAR, 0) == 7
    monkeypatch.setenv(VAR, "2.5")
    assert env_int(VAR, 9) == 9          # int() rejects it → default
    assert env_float(VAR, 0.0) == 2.5
    monkeypatch.setenv(VAR, "-1.5")
    assert env_float(VAR, 4.0, minimum=0.0) == 4.0
    monkeypatch.delenv(VAR)
    assert env_float(VAR, 1.25) == 1.25


def test_env_str_raw(monkeypatch):
    monkeypatch.setenv(VAR, "  padded  ")
    assert env_str(VAR) == "  padded  "   # no strip: callers that trim, trim
    monkeypatch.delenv(VAR)
    assert env_str(VAR, "fallback") == "fallback"


def test_env_list_strips_and_skips_blank_entries(monkeypatch):
    default = ["https://fallback.example"]

    monkeypatch.delenv(VAR, raising=False)
    assert env_list(VAR, default) == default
    monkeypatch.setenv(VAR, "")
    assert env_list(VAR, default) == default
    monkeypatch.setenv(VAR, " https://a.example, ,https://b.example ,, ")
    assert env_list(VAR) == ["https://a.example", "https://b.example"]


def test_env_json_object_never_raises_and_requires_object(monkeypatch):
    default = {"twilio": {"from": "+1000"}}

    monkeypatch.delenv(VAR, raising=False)
    assert env_json_object(VAR, default) == default
    monkeypatch.setenv(VAR, "")
    assert env_json_object(VAR, default) == default
    monkeypatch.setenv(VAR, "{bad-json")
    assert env_json_object(VAR, default) == default
    monkeypatch.setenv(VAR, "[]")
    assert env_json_object(VAR, default) == default
    monkeypatch.setenv(VAR, '{"telnyx":{"connection_id":"abc"}}')
    assert env_json_object(VAR, default) == {"telnyx": {"connection_id": "abc"}}


def test_env_int_map_never_raises_and_skips_bad_entries(monkeypatch):
    default = {"fallback": 9}

    monkeypatch.delenv(VAR, raising=False)
    assert env_int_map(VAR, default) == default
    monkeypatch.setenv(VAR, "")
    assert env_int_map(VAR, default) == default
    monkeypatch.setenv(VAR, "whatsapp:2, teams:30 ,junk,bad:x, negative:-1")
    assert env_int_map(VAR) == {"whatsapp": 2, "teams": 30, "negative": -1}


# ── layer 2: the convention guard (the ratchet) ──────────────────────────────

# A literal boolean-spellings set ('"1", "true"' / '"0", "false"' in any
# quoting/case, tuple or set) is banned CONTEXT-FREE: that also catches
# split-line parses (read on one line, membership on the next), injectable
# env mappings (env.get(...)), and module-local _TRUTHY/_TRUE constants.
_SET_LITERAL = re.compile(r"""["'][01]["']\s*,\s*["'](true|false)["']""", re.IGNORECASE)
# == "1" / != "1" is only a boolean env parse when the line reads env.
_EQ_ONE = re.compile(r"""[=!]=\s*["']1["']""")
_ENV_READ = re.compile(r"getenv|environ|env\.get")
_HELPER_DEF = re.compile(r"def\s+(_env_truthy|_env_flag|_env_int|_env_bool|truthy|env_flag)\s*\(")

# Runtime code only: agents/ + serve.py. tests/ set env, scripts/ are dev
# tooling, worldview/ is a separate stack.
_SCAN_ROOTS = ["agents", "serve.py"]
_EXEMPT = {
    "agents/core/env_config.py",   # the one home for the convention
}


def _runtime_py_files():
    for root in _SCAN_ROOTS:
        p = repo_root / root
        if p.is_file():
            yield p
        else:
            yield from sorted(p.rglob("*.py"))


def test_one_truthy_convention_in_the_tree():
    """No env read may be boolean-parsed with a local convention.

    Before P2.1 this failed with ~40 sites across 8 conventions ("TRUE" that
    meant off, "off" that meant on, == "1" ...). Every boolean env read goes
    through env_config.env_flag/truthy now; this is the ratchet that keeps
    it that way. If you legitimately need a new env flag: env_flag(name,
    default) — do not parse spellings yourself.
    """
    violations = []
    for path in _runtime_py_files():
        rel = path.relative_to(repo_root).as_posix()
        if rel in _EXEMPT:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _SET_LITERAL.search(line) or (_EQ_ONE.search(line) and _ENV_READ.search(line)):
                violations.append(f"{rel}:{n}: {line.strip()[:120]}")
            elif _HELPER_DEF.search(line):
                violations.append(f"{rel}:{n}: helper redefinition — {line.strip()[:100]}")
    assert not violations, (
        "ad-hoc boolean env parsing found (use agents.core.env_config):\n  "
        + "\n  ".join(violations)
    )


def test_env_config_is_a_stdlib_leaf():
    """The module must stay import-cycle-free: stdlib imports only."""
    src = (repo_root / "agents/core/env_config.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) and "__future__" not in stripped:
            root_mod = stripped.split()[1].split(".")[0]
            assert root_mod in {"json", "os"}, f"env_config imports non-stdlib-leaf module: {stripped}"
    assert "load_dotenv" not in src, "env_config must never load .env (posture change)"


def test_web_email_ports_use_shared_env_int():
    """Malformed SMTP/IMAP port env values must fall back, not crash startup."""
    src = (repo_root / "agents/web.py").read_text(encoding="utf-8")
    assert 'int(os.environ.get("SMTP_PORT"' not in src
    assert 'int(os.environ.get("IMAP_PORT"' not in src
    assert 'env_int("SMTP_PORT", 587' in src
    assert 'env_int("IMAP_PORT", 993' in src


def test_webhook_channels_use_shared_env_json_object():
    """Malformed webhook-channel JSON env must fall back, not hand-roll parsing."""
    src = (repo_root / "agents/web.py").read_text(encoding="utf-8")
    assert 'os.environ.get("JARVIS_WEBHOOK_CHANNELS"' not in src
    assert 'json.loads(wh_raw)' not in src
    assert 'env_json_object("JARVIS_WEBHOOK_CHANNELS", {})' in src


def test_web_cors_origins_use_shared_env_list():
    """Comma-separated CORS origins should use the shared list parser."""
    src = (repo_root / "agents/web.py").read_text(encoding="utf-8")
    assert 'os.environ.get("JARVIS_CORS_ORIGINS"' not in src
    assert 'env_list("JARVIS_CORS_ORIGINS")' in src


# ── layer 3: pins for the deliberate flips ───────────────────────────────────

def test_a2a_gate_accepts_on(monkeypatch):
    """Convention A→unified: 'on' used to be silently falsy for the A2A gate."""
    from agents.core import a2a

    monkeypatch.setenv("JARVIS_A2A_ENABLED", "on")
    assert a2a.a2a_enabled() is True
    monkeypatch.setenv("JARVIS_A2A_ENABLED", "banana")
    assert a2a.a2a_enabled() is False, "junk must keep the fail-closed gate shut"


def test_workflow_persist_zero_now_disables(monkeypatch):
    """The '=0 enables it' footgun: the coordinator's presence-check and the
    engine's truthy-check disagreed on the SAME var. Both read env_flag now."""
    from agents.core.workflows import engine

    monkeypatch.setenv("JARVIS_WORKFLOW_PERSIST", "0")
    assert engine.persist_enabled() is False
    monkeypatch.setenv("JARVIS_WORKFLOW_PERSIST", "1")
    assert engine.persist_enabled() is True
    monkeypatch.delenv("JARVIS_WORKFLOW_PERSIST")
    assert engine.persist_enabled() is False


def test_strict_egress_default_on_junk_stays_on(monkeypatch):
    """Default-ON strict flag: unknown spellings must NOT relax the posture."""
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "definitely")
    from agents.core.http_client import strict_egress_enabled

    assert strict_egress_enabled() is True
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "off")   # explicit falsy honored
    assert strict_egress_enabled() is False
    monkeypatch.setenv("JARVIS_HARDENED", "1")           # hardened still forces it
    assert strict_egress_enabled() is True


def test_oauth_env_truthy_stays_importable():
    """tests/test_trust_api.py imports oauth._env_truthy directly — keep the name."""
    from agents.core.routers.oauth import _env_truthy

    assert _env_truthy("on") is True and _env_truthy("nope") is False
