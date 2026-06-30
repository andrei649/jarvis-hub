"""
scanner.py — Pure-Python PII and secret regex scanners.

Port of OpenJarvis's Rust-based scanners to pure Python.

This is a Romania-first personal system (family data on the LAN via Frigga,
banking with Raiffeisen/ING/Libra via Gecko), so the PII scanner detects
Romanian identifiers — **CNP** (national ID) and **IBAN** — alongside the
generic email / US patterns. Those two carry a checksum, so a regex match is
confirmed by its control digit (CNP) or ISO 7064 mod-97 (IBAN) before it is
reported: this keeps false positives near zero on arbitrary 13-digit numbers
or IBAN-shaped strings.
"""

import json
import logging
import math
import os
import re
from typing import Callable

from .types import ScanFinding, ScanResult, ThreatLevel

logger = logging.getLogger("jarvis.scanner")

_EXTRA_PATTERNS_ENV = "JARVIS_SCANNER_EXTRA_PATTERNS"


def _extra_patterns_from_env(env=None) -> dict:
    """User-supplied extra redaction patterns from ``JARVIS_SCANNER_EXTRA_PATTERNS``
    — a JSON object ``{name: regex}``. A missing/blank/non-JSON/non-object value
    yields ``{}`` so a bad config can never break scanning (AUD-18)."""
    raw = (os.environ if env is None else env).get(_EXTRA_PATTERNS_ENV, "")
    if not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if str(k) and str(v)}


# ── Generic secret heuristics ─────────────────────────────────────────────────
# A long, high-entropy base64-ish run is almost certainly a credential, not
# prose. We only consider runs of "secret-shaped" characters (base64 / base64url
# / hex) and require both length and entropy thresholds so English text — which
# is low-entropy and rarely produces 32-char unbroken alphanumeric runs — is not
# flagged. Mirrors the precision bar set by the CNP/IBAN checksum validators.
_HIGH_ENTROPY_RUN = re.compile(r"[A-Za-z0-9+/_-]{32,}")
# Minimum Shannon entropy (bits/char) for a run to count as a secret. Random
# base64 tends toward ~5–6 bits/char; English words sit well below ~3.5.
_MIN_ENTROPY_BITS = 3.6


def shannon_entropy(value: str) -> float:
    """Shannon entropy of `value` in bits per character (0 for empty)."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def looks_like_high_entropy_secret(value: str) -> bool:
    """True if `value` contains a long, high-entropy secret-shaped token.

    Precision-first: requires a ≥32-char base64/hex-ish run *and* a Shannon
    entropy above ~3.6 bits/char, plus a digit-or-mixed-case signal so that
    long all-lowercase identifiers (e.g. a hyphen-free German compound word or
    a 32-char slug) don't trip it. English prose, with its low per-character
    entropy and word boundaries, stays clean.
    """
    for m in _HIGH_ENTROPY_RUN.finditer(value):
        run = m.group()
        if shannon_entropy(run) < _MIN_ENTROPY_BITS:
            continue
        has_digit = any(c.isdigit() for c in run)
        has_upper = any(c.isupper() for c in run)
        has_lower = any(c.islower() for c in run)
        # Require character-class diversity typical of generated tokens; a run
        # that is purely one class (all lowercase letters) is more likely an
        # identifier/slug than a key.
        if (has_digit and (has_upper or has_lower)) or (has_upper and has_lower):
            return True
    return False


# ── Romanian identifier validators ────────────────────────────────────────────
# CNP control-digit constant (the 13th digit is derived from the first 12).
_CNP_KEY = (2, 7, 9, 1, 4, 6, 3, 5, 8, 2, 7, 9)


def is_valid_cnp(value: str) -> bool:
    """True if `value` is a structurally valid Romanian CNP (Cod Numeric Personal).

    Checks the embedded birth month/day for plausibility and verifies the
    official control digit, so random 13-digit runs are not flagged.
    """
    if len(value) != 13 or not value.isdigit():
        return False
    digits = [int(c) for c in value]
    month = digits[3] * 10 + digits[4]
    day = digits[5] * 10 + digits[6]
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    total = sum(d * k for d, k in zip(digits[:12], _CNP_KEY))
    control = total % 11
    if control == 10:
        control = 1
    return control == digits[12]


def is_valid_iban(value: str) -> bool:
    """True if `value` passes the ISO 7064 mod-97 IBAN checksum."""
    v = value.replace(" ", "").upper()
    if len(v) < 5:
        return False
    rearranged = v[4:] + v[:4]
    digits: list[str] = []
    for ch in rearranged:
        if ch.isdigit():
            digits.append(ch)
        elif "A" <= ch <= "Z":
            digits.append(str(ord(ch) - 55))  # A=10 … Z=35
        else:
            return False
    return int("".join(digits)) % 97 == 1


class BaseScanner:
    scanner_id: str = "base"

    def scan(self, text: str) -> ScanResult:
        raise NotImplementedError

    def redact(self, text: str) -> str:
        raise NotImplementedError


class SecretScanner(BaseScanner):
    scanner_id = "secrets"

    PATTERNS: dict[str, tuple[str, ThreatLevel, str]] = {
        # OpenAI keys are ≥40 chars. The negative lookahead keeps this from
        # pre-empting the more specific `sk-ant-` (Anthropic) format; Stripe
        # uses an underscore (`sk_`) so it can't collide here.
        "openai_key": (r"sk-(?!ant-)[A-Za-z0-9_-]{40,}", ThreatLevel.CRITICAL, "OpenAI API key"),
        "anthropic_key": (r"sk-ant-[A-Za-z0-9_-]{20,}", ThreatLevel.CRITICAL, "Anthropic API key"),
        "aws_access_key": (r"(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[0-9A-Z]{16}", ThreatLevel.CRITICAL, "AWS access key"),
        "github_token": (r"(?:ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{36,}", ThreatLevel.CRITICAL, "GitHub token"),
        # Quoted or bare assignment; the bare form requires a credential-ish
        # value (no whitespace, ≥6 chars) so `password = ` placeholders or short
        # words rarely fire.
        "password_assignment": (r"""(?i:password|passwd|pwd)\s*[=:]\s*(?:['"]([^\s'"]{4,})['"]|([^\s'"]{6,}))""", ThreatLevel.HIGH, "Password assignment"),
        # Require a credential-bearing URL: scheme://user:pass@host. Bare
        # `scheme://host/path` (no embedded creds) is no longer flagged.
        "db_connection_string": (r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:/@]+:[^\s:/@]+@[^\s/]+", ThreatLevel.HIGH, "Database connection string"),
        "private_key": (r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", ThreatLevel.CRITICAL, "Private key"),
        "slack_token": (r"xox[bpors]-[A-Za-z0-9\-]{10,}", ThreatLevel.HIGH, "Slack token"),
        "stripe_key": (r"(?:sk|pk|rk)_(?:test|live)_[A-Za-z0-9]{20,}", ThreatLevel.CRITICAL, "Stripe key"),
        # GCP service-account JSON key: the `"type": "service_account"` marker
        # paired with a `"private_key"` field (order-independent, whitespace
        # tolerant) is a near-unique signature.
        "gcp_service_account": (r'"type"\s*:\s*"service_account"[\s\S]{0,400}?"private_key"\s*:', ThreatLevel.CRITICAL, "GCP service-account key"),
        "azure_storage_key": (r"AccountKey=[A-Za-z0-9+/]{86}==", ThreatLevel.CRITICAL, "Azure storage account key"),
        "generic_api_key": (r"""(?i:api_key|secret_key|auth_token)\s*[=:]\s*['"]([^'"]{8,})['"]""", ThreatLevel.HIGH, "Generic API key/secret"),
        "jwt": (r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", ThreatLevel.HIGH, "JWT"),
        "bearer_token": (r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}", ThreatLevel.HIGH, "Bearer token"),
        # Telegram bot token (`<bot_id>:<35-char auth>`) — this system's primary
        # control channel runs on one (`TELEGRAM_BOT_TOKEN`), so a leak in an
        # echoed/ingested message would hand over the bot. The numeric id + colon
        # + exactly-35 base64url chars is a near-unique shape; the trailing
        # negative lookahead pins the auth length so a longer run can't slip past.
        "telegram_bot_token": (r"\b\d{6,12}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])", ThreatLevel.CRITICAL, "Telegram bot token"),
        # Google API key (`AIza` + 35 chars) — the format of this system's
        # `GEMINI_API_KEY`. The `AIza` prefix never occurs in prose, so it is
        # case-sensitive (below) and effectively zero-false-positive.
        "google_api_key": (r"AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])", ThreatLevel.CRITICAL, "Google API key"),
        # Generic catch-all for long, high-entropy tokens that don't match a
        # known vendor format. Gated by the entropy validator below to keep
        # false positives near zero.
        "high_entropy_secret": (r"[A-Za-z0-9+/_-]{32,}", ThreatLevel.HIGH, "High-entropy secret"),
    }

    # Pattern names whose regex must be matched case-sensitively. Key formats
    # (OpenAI/Anthropic/AWS/Stripe/Azure) carry meaningful case, so IGNORECASE
    # would broaden them and let `SK-…` style prose tokens false-positive.
    CASE_SENSITIVE = frozenset({
        "openai_key", "anthropic_key", "aws_access_key", "github_token",
        "stripe_key", "azure_storage_key", "google_api_key", "high_entropy_secret",
    })

    # Patterns whose regex matches must additionally pass a heuristic validator
    # to count as findings — mirrors PIIScanner's checksum gating.
    VALIDATORS: dict[str, Callable[[str], bool]] = {
        "high_entropy_secret": looks_like_high_entropy_secret,
    }

    def __init__(self, extra_patterns: dict | None = None):
        self._compiled: list[tuple[str, re.Pattern, ThreatLevel, str]] = []
        for name, (pattern, threat, desc) in self.PATTERNS.items():
            flags = 0 if name in self.CASE_SENSITIVE else re.IGNORECASE
            try:
                self._compiled.append((name, re.compile(pattern, flags), threat, desc))
            except re.error:
                pass
        # AUD-18 (opt-in): user-supplied extra redaction patterns so a deployment
        # can scrub its own secret formats. The constructor arg wins (tests); else
        # read JARVIS_SCANNER_EXTRA_PATTERNS (JSON {name: regex}). Compiled
        # IGNORECASE at HIGH threat; an invalid regex is skipped so a bad pattern
        # can't break scanning. No config → no change (default path unaffected).
        extras = extra_patterns if extra_patterns is not None else _extra_patterns_from_env()
        for name, pattern in extras.items():
            try:
                self._compiled.append((str(name), re.compile(str(pattern), re.IGNORECASE),
                                       ThreatLevel.HIGH, f"custom pattern: {name}"))
            except re.error:
                logger.debug("ignoring invalid custom scanner pattern %r", name)

    def scan(self, text: str) -> ScanResult:
        result = ScanResult()
        for name, pattern, threat, desc in self._compiled:
            validator = self.VALIDATORS.get(name)
            for match in pattern.finditer(text):
                if validator and not validator(match.group()):
                    continue
                result.findings.append(ScanFinding(
                    pattern_name=name,
                    matched_text=match.group(),
                    threat_level=threat,
                    start=match.start(),
                    end=match.end(),
                    description=desc,
                ))
        return result

    def redact(self, text: str) -> str:
        for name, pattern, threat, desc in self._compiled:
            validator = self.VALIDATORS.get(name)
            if validator:
                text = pattern.sub(
                    lambda m, _n=name, _v=validator: (
                        f"[REDACTED:{_n}]" if _v(m.group()) else m.group()
                    ),
                    text,
                )
            else:
                text = pattern.sub(f"[REDACTED:{name}]", text)
        return text


class PIIScanner(BaseScanner):
    scanner_id = "pii"

    PATTERNS: dict[str, tuple[str, ThreatLevel, str]] = {
        "email": (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", ThreatLevel.MEDIUM, "Email address"),
        "us_ssn": (r"\b\d{3}-\d{2}-\d{4}\b", ThreatLevel.CRITICAL, "US Social Security Number"),
        "credit_card_visa": (r"\b4\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", ThreatLevel.CRITICAL, "Visa credit card"),
        "credit_card_mastercard": (r"\b5[1-5]\d{2}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", ThreatLevel.CRITICAL, "Mastercard credit card"),
        "credit_card_amex": (r"\b3[47]\d{2}[\s-]?\d{6}[\s-]?\d{5}\b", ThreatLevel.CRITICAL, "Amex credit card"),
        "us_phone": (r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", ThreatLevel.MEDIUM, "US phone number"),
        # Romania-specific (this is a RO-first system).
        "ro_cnp": (r"\b[1-9]\d{12}\b", ThreatLevel.CRITICAL, "Romanian CNP (national ID)"),
        "ro_iban": (r"\b[Rr][Oo]\d{2}[A-Za-z]{4}[A-Za-z0-9]{16}\b", ThreatLevel.HIGH, "Romanian IBAN"),
        "ro_phone": (r"(?<![\d+])(?:(?:\+|00)40|0)7\d{8}(?!\d)", ThreatLevel.MEDIUM, "Romanian mobile number"),
    }

    # Patterns whose regex matches must additionally pass a checksum/structural
    # validator to count as findings — keeps false positives near zero.
    VALIDATORS: dict[str, Callable[[str], bool]] = {
        "ro_cnp": is_valid_cnp,
        "ro_iban": is_valid_iban,
    }

    def __init__(self):
        self._compiled: list[tuple[str, re.Pattern, ThreatLevel, str]] = []
        for name, (pattern, threat, desc) in self.PATTERNS.items():
            try:
                self._compiled.append((name, re.compile(pattern), threat, desc))
            except re.error:
                pass

    def scan(self, text: str) -> ScanResult:
        result = ScanResult()
        for name, pattern, threat, desc in self._compiled:
            validator = self.VALIDATORS.get(name)
            for match in pattern.finditer(text):
                if validator and not validator(match.group()):
                    continue
                result.findings.append(ScanFinding(
                    pattern_name=name,
                    matched_text=match.group(),
                    threat_level=threat,
                    start=match.start(),
                    end=match.end(),
                    description=desc,
                ))
        return result

    def redact(self, text: str) -> str:
        for name, pattern, threat, desc in self._compiled:
            validator = self.VALIDATORS.get(name)
            if validator:
                # Only redact matches that pass the validator; leave the rest
                # untouched (a non-CNP 13-digit number stays as-is).
                text = pattern.sub(
                    lambda m, _n=name, _v=validator: (
                        f"[REDACTED:{_n}]" if _v(m.group()) else m.group()
                    ),
                    text,
                )
            else:
                text = pattern.sub(f"[REDACTED:{name}]", text)
        return text
