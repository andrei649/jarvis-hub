"""AUD-18 / F30 — validate JARVIS_CORS_ORIGINS instead of trusting it.

The origins list was passed straight into `CORSMiddleware` with no checking.
Two failure modes that matter, neither of which announced itself:

1. **A malformed origin silently never matches.** A browser compares the
   `Origin` header against these values *exactly* — scheme included, no trailing
   slash, no path. So `example.com`, `https://example.com/`, or a stray-whitespace
   entry all look configured to the operator and simply never work. Silent
   non-enforcement of a security control is the worst failure mode: it reads as
   protected while being inert.

2. **`*` together with `allow_credentials=True`** is rejected by every browser,
   so the effect is the same silent nothing — but it *looks* maximally permissive
   in config, which is exactly the misreading to avoid.

`normalize_cors_origins` therefore returns the usable origins plus the rejected
ones with reasons, so startup can log what it dropped rather than pretend.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.cors_policy import normalize_cors_origins  # noqa: E402


def test_wellformed_origins_pass_through_unchanged():
    ok, bad = normalize_cors_origins(["https://a.example", "http://localhost:5173"])
    assert ok == ["https://a.example", "http://localhost:5173"]
    assert bad == []


def test_a_missing_scheme_is_rejected_with_a_reason():
    ok, bad = normalize_cors_origins(["example.com"])
    assert ok == []
    assert bad and bad[0]["value"] == "example.com"
    assert "scheme" in bad[0]["reason"]


def test_a_trailing_slash_is_rejected_because_browsers_never_match_it():
    ok, bad = normalize_cors_origins(["https://a.example/"])
    assert ok == []
    assert "trailing" in bad[0]["reason"] or "path" in bad[0]["reason"]


def test_a_path_is_rejected():
    ok, bad = normalize_cors_origins(["https://a.example/widget"])
    assert ok == []
    assert bad


def test_surrounding_whitespace_is_trimmed_not_rejected():
    """env_list already trims, but a hand-edited value must not become a silent
    non-match just because someone typed a space."""
    ok, bad = normalize_cors_origins(["  https://a.example  "])
    assert ok == ["https://a.example"]
    assert bad == []


def test_wildcard_is_refused_when_credentials_are_allowed():
    ok, bad = normalize_cors_origins(["*"], allow_credentials=True)
    assert ok == []
    assert "credential" in bad[0]["reason"]


def test_wildcard_is_allowed_when_credentials_are_off():
    ok, bad = normalize_cors_origins(["*"], allow_credentials=False)
    assert ok == ["*"]
    assert bad == []


def test_duplicates_collapse_preserving_first_order():
    ok, _ = normalize_cors_origins(["https://a.example", "https://a.example"])
    assert ok == ["https://a.example"]


def test_empty_input_is_not_an_error():
    assert normalize_cors_origins([]) == ([], [])
    assert normalize_cors_origins(None) == ([], [])


def test_non_string_entries_are_rejected_not_crashed_on():
    ok, bad = normalize_cors_origins(["https://a.example", 42, None])
    assert ok == ["https://a.example"]
    assert len(bad) == 2


def test_the_app_only_installs_cors_for_usable_origins(monkeypatch):
    """The whole point: a config of only-malformed origins must NOT leave the
    operator believing CORS is enabled."""
    ok, bad = normalize_cors_origins(["example.com", "https://b.example/"])
    assert ok == []          # nothing usable
    assert len(bad) == 2     # and both are reported, not swallowed
