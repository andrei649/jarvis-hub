"""Tests for the PII / secret scanners (agents/core/security/scanner.py).

These scanners had no direct coverage. This suite locks in:
  * the existing secret + generic-PII regex behaviour (regression guard), and
  * the Romania-specific detectors the docs promise — CNP (national ID) and
    IBAN — which are checksum-validated so they don't fire on arbitrary
    13-digit numbers or IBAN-shaped strings.

The CNP and IBAN constants below are externally verified:
  * CNP 1960620054670 has control digit 0 per the official algorithm;
    flipping it to 5 must be rejected.
  * RO49AAAA1B31007593840000 satisfies ISO 7064 mod-97 (== 1); the same
    string ending in ...0001 does not.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.security.scanner import (  # noqa: E402
    PIIScanner,
    SecretScanner,
    is_valid_cnp,
    is_valid_iban,
)
from agents.core.security.guardrails import GuardrailsEngine, SecurityBlockError  # noqa: E402
from agents.core.security.types import RedactionMode, ThreatLevel  # noqa: E402
from agents.core.llm.base import LLMBackend  # noqa: E402


VALID_CNP = "1960620054670"      # control digit 0 (verified)
INVALID_CNP = "1960620054675"    # wrong control digit
VALID_IBAN = "RO49AAAA1B31007593840000"
INVALID_IBAN = "RO49AAAA1B31007593840001"

# Real OpenAI keys are ≥40 chars after the `sk-` prefix (HF-3). Mixed-case +
# digits so it's unambiguously key-shaped.
OPENAI_KEY = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"


def _names(result):
    return {f.pattern_name for f in result.findings}


# ── SecretScanner ──────────────────────────────────────────────────────────────

class TestSecretScanner:
    def test_detects_common_secrets(self):
        s = SecretScanner()
        samples = {
            "openai_key": OPENAI_KEY,
            "anthropic_key": "sk-ant-abcdefghijklmnopqrstuvwxyz",
            "aws_access_key": "AKIAIOSFODNN7EXAMPLE",
            "github_token": "ghp_" + "a" * 36,
            "private_key": "-----BEGIN RSA PRIVATE KEY-----",
        }
        for expected, text in samples.items():
            names = _names(s.scan(text))
            assert expected in names, f"{expected} not detected in {text!r}"

    def test_detects_additional_secret_formats(self):
        """HF-3: unquoted password, broader PEM, JWT, Bearer token."""
        s = SecretScanner()
        cases = {
            "password_assignment": "password=hunter2longvalue",
            "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----",
            "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4eXoifQ.abcDEF123456",
            "bearer_token": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123",
        }
        for expected, text in cases.items():
            names = _names(s.scan(text))
            assert expected in names, f"{expected} not detected in {text!r}"

    def test_clean_text_has_no_findings(self):
        assert SecretScanner().scan("just a normal sentence, nothing secret").clean

    def test_redaction_removes_secret(self):
        s = SecretScanner()
        text = f"my key is {OPENAI_KEY} ok"
        redacted = s.redact(text)
        assert OPENAI_KEY not in redacted
        assert "[REDACTED:openai_key]" in redacted

    # ── HF-3: tightened/added secret patterns ──────────────────────────────

    def test_real_openai_key_detected(self):
        """A ≥40-char OpenAI key fires `openai_key`, not just the catch-all."""
        names = _names(SecretScanner().scan(f"OPENAI_API_KEY={OPENAI_KEY}"))
        assert "openai_key" in names

    def test_short_sk_token_not_openai(self):
        """A short `sk-xxx` token must NOT false-positive as an OpenAI key.

        Real keys are ≥40 chars; a 20-something-char `sk-` prefixed slug is
        almost certainly not a credential, so the specific detector stays quiet.
        """
        short = "sk-abcdefghijklmnopqrst"  # 20 chars after the prefix
        names = _names(SecretScanner().scan(f"see {short} here"))
        assert "openai_key" not in names

    def test_gcp_service_account_detected(self):
        """A GCP service-account JSON key blob is detected by its signature."""
        blob = (
            '{\n'
            '  "type": "service_account",\n'
            '  "project_id": "demo-123",\n'
            '  "private_key": "-----BEGIN PRIVATE KEY-----\\nMIIabc\\n-----END...",\n'
            '  "client_email": "svc@demo-123.iam.gserviceaccount.com"\n'
            '}'
        )
        names = _names(SecretScanner().scan(blob))
        assert "gcp_service_account" in names

    def test_db_connection_string_requires_credentials(self):
        s = SecretScanner()
        # Credential-bearing URL → flagged.
        assert "db_connection_string" in _names(
            s.scan("DATABASE_URL=postgres://user:s3cr3t@db.host:5432/app")
        )
        # Bare scheme://host with no embedded creds → not flagged (low noise).
        assert "db_connection_string" not in _names(
            s.scan("connect to redis://cache.local:6379/0")
        )

    def test_entropy_heuristic_catches_random_token_not_prose(self):
        s = SecretScanner()
        # A random 40-char mixed token → caught by the entropy catch-all.
        random_token = "Zk7Qp2Lm9Xr4Tv1Bn6Wc3Yd8Fg5Hj0Es2Au4Io9z"
        assert "high_entropy_secret" in _names(s.scan(f"token {random_token}"))
        # English prose, even long, stays clean (low per-char entropy, spaced).
        prose = (
            "the quick brown fox jumps over the lazy dog while the sun sets "
            "slowly behind the rolling green hills of the countryside"
        )
        assert "high_entropy_secret" not in _names(s.scan(prose))

    def test_entropy_validator_direct(self):
        from agents.core.security.scanner import (
            looks_like_high_entropy_secret,
            shannon_entropy,
        )
        assert looks_like_high_entropy_secret("Zk7Qp2Lm9Xr4Tv1Bn6Wc3Yd8Fg5Hj0Es2Au4Io9z")
        # A 40-char all-lowercase slug is low-diversity → not a secret.
        assert not looks_like_high_entropy_secret("a" * 40)
        assert not looks_like_high_entropy_secret(
            "this is just an ordinary english sentence here"
        )
        assert shannon_entropy("") == 0.0
        assert shannon_entropy("aaaa") == 0.0


# ── PIIScanner: existing patterns (regression) ──────────────────────────────────

class TestPIIScannerExisting:
    def test_email_detected(self):
        assert "email" in _names(PIIScanner().scan("write to andrei@example.com please"))

    def test_us_ssn_detected(self):
        assert "us_ssn" in _names(PIIScanner().scan("SSN 123-45-6789"))

    def test_visa_card_detected(self):
        assert "credit_card_visa" in _names(PIIScanner().scan("card 4111 1111 1111 1111"))

    def test_clean_text(self):
        assert PIIScanner().scan("the meeting is at noon tomorrow").clean


# ── PIIScanner: Romanian CNP ─────────────────────────────────────────────────────

class TestCNP:
    def test_valid_cnp_detected_as_critical(self):
        result = PIIScanner().scan(f"CNP-ul meu este {VALID_CNP}.")
        findings = [f for f in result.findings if f.pattern_name == "ro_cnp"]
        assert len(findings) == 1
        assert findings[0].threat_level == ThreatLevel.CRITICAL
        assert findings[0].matched_text == VALID_CNP

    def test_invalid_checksum_not_flagged(self):
        assert "ro_cnp" not in _names(PIIScanner().scan(f"numar {INVALID_CNP} aici"))

    def test_implausible_date_not_flagged(self):
        # month 99 — structurally impossible, must be rejected even if 13 digits
        assert "ro_cnp" not in _names(PIIScanner().scan("1999999054670"))

    def test_arbitrary_13_digits_rarely_match(self):
        assert "ro_cnp" not in _names(PIIScanner().scan("0000000000000"))

    def test_validator_direct(self):
        assert is_valid_cnp(VALID_CNP)
        assert not is_valid_cnp(INVALID_CNP)
        assert not is_valid_cnp("123")          # too short
        assert not is_valid_cnp("abcdefghijklm")  # non-digit
        # control digit == 10 maps to 1
        assert is_valid_cnp("2990101123452")

    def test_redaction_replaces_valid_leaves_invalid(self):
        s = PIIScanner()
        text = f"valid {VALID_CNP} invalid {INVALID_CNP}"
        redacted = s.redact(text)
        assert VALID_CNP not in redacted
        assert "[REDACTED:ro_cnp]" in redacted
        assert INVALID_CNP in redacted  # untouched — not a real CNP


# ── PIIScanner: Romanian IBAN ────────────────────────────────────────────────────

class TestIBAN:
    def test_valid_iban_detected_as_high(self):
        result = PIIScanner().scan(f"transfer in contul {VALID_IBAN}")
        findings = [f for f in result.findings if f.pattern_name == "ro_iban"]
        assert len(findings) == 1
        assert findings[0].threat_level == ThreatLevel.HIGH

    def test_invalid_checksum_not_flagged(self):
        assert "ro_iban" not in _names(PIIScanner().scan(f"iban {INVALID_IBAN}"))

    def test_lowercase_iban_detected(self):
        assert "ro_iban" in _names(PIIScanner().scan(VALID_IBAN.lower()))

    def test_validator_direct(self):
        assert is_valid_iban(VALID_IBAN)
        assert is_valid_iban("RO49 AAAA 1B31 0075 9384 0000")  # spaces tolerated
        assert not is_valid_iban(INVALID_IBAN)
        assert not is_valid_iban("RO")  # too short

    def test_redaction(self):
        redacted = PIIScanner().redact(f"cont {VALID_IBAN} gata")
        assert VALID_IBAN not in redacted
        assert "[REDACTED:ro_iban]" in redacted


# ── PIIScanner: Romanian phone ───────────────────────────────────────────────────

class TestROPhone:
    @pytest.mark.parametrize("number", [
        "0721234567",
        "+40721234567",
        "0040721234567",
    ])
    def test_variants_detected(self, number):
        assert "ro_phone" in _names(PIIScanner().scan(f"suna-ma la {number}"))

    def test_not_matched_mid_number(self):
        # embedded inside a longer digit run — must not be picked up
        assert "ro_phone" not in _names(PIIScanner().scan("ref 990721234567000"))

    def test_redaction(self):
        redacted = PIIScanner().redact("numar 0721234567 ok")
        assert "0721234567" not in redacted


# ── GuardrailsEngine integration (REDACT / BLOCK) ───────────────────────────────

class _StubBackend(LLMBackend):
    """Returns a canned reply and remembers the prompt it was handed."""

    def __init__(self, reply: str = "ok"):
        self.reply = reply
        self.seen_prompt = None

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        self.seen_prompt = prompt
        return self.reply


class TestGuardrails:
    async def test_redact_mode_scrubs_cnp_from_output(self):
        backend = _StubBackend(reply=f"Your CNP is {VALID_CNP}.")
        engine = GuardrailsEngine(backend, mode=RedactionMode.REDACT)
        out = await engine.generate("m", "tell me my id")
        assert VALID_CNP not in out
        assert "[REDACTED:ro_cnp]" in out

    async def test_redact_mode_scrubs_cnp_from_input(self):
        backend = _StubBackend(reply="done")
        engine = GuardrailsEngine(backend, mode=RedactionMode.REDACT)
        await engine.generate("m", f"my cnp is {VALID_CNP}")
        assert VALID_CNP not in backend.seen_prompt

    async def test_block_mode_raises_on_secret_input(self):
        engine = GuardrailsEngine(_StubBackend(), mode=RedactionMode.BLOCK)
        with pytest.raises(SecurityBlockError):
            await engine.generate("m", "key: sk-abcdefghijklmnopqrstuvwxyz0123")

    async def test_warn_mode_passes_through(self):
        backend = _StubBackend(reply="clean reply")
        engine = GuardrailsEngine(backend, mode=RedactionMode.WARN)
        out = await engine.generate("m", f"contact andrei@example.com cnp {VALID_CNP}")
        assert out == "clean reply"
