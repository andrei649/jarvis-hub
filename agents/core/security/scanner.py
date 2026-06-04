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

import re
from typing import Callable

from .types import ScanFinding, ScanResult, ThreatLevel


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
        "openai_key": (r"sk-[A-Za-z0-9_-]{20,}", ThreatLevel.CRITICAL, "OpenAI API key"),
        "anthropic_key": (r"sk-ant-[A-Za-z0-9_-]{20,}", ThreatLevel.CRITICAL, "Anthropic API key"),
        "aws_access_key": (r"AKIA[0-9A-Z]{16}", ThreatLevel.CRITICAL, "AWS access key"),
        "github_token": (r"(?:ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{36,}", ThreatLevel.CRITICAL, "GitHub token"),
        "password_assignment": (r"""(?:password|passwd|pwd)\s*[=:]\s*['"]?([^\s'"]{4,})['"]?""", ThreatLevel.HIGH, "Password assignment"),
        "db_connection_string": (r"(?:postgres|mysql|mongodb|redis)://[^\s]{10,}", ThreatLevel.HIGH, "Database connection string"),
        "private_key": (r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", ThreatLevel.CRITICAL, "Private key"),
        "slack_token": (r"xox[bpors]-[A-Za-z0-9\-]{10,}", ThreatLevel.HIGH, "Slack token"),
        "stripe_key": (r"(?:sk|pk)_(?:test|live)_[A-Za-z0-9]{20,}", ThreatLevel.CRITICAL, "Stripe key"),
        "generic_api_key": (r"""(?:api_key|secret_key|auth_token)\s*[=:]\s*['"]([^'"]{8,})['"]""", ThreatLevel.HIGH, "Generic API key/secret"),
        "jwt": (r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", ThreatLevel.HIGH, "JWT"),
        "bearer_token": (r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}", ThreatLevel.HIGH, "Bearer token"),
    }

    def __init__(self):
        self._compiled: list[tuple[str, re.Pattern, ThreatLevel, str]] = []
        for name, (pattern, threat, desc) in self.PATTERNS.items():
            try:
                self._compiled.append((name, re.compile(pattern, re.IGNORECASE), threat, desc))
            except re.error:
                pass

    def scan(self, text: str) -> ScanResult:
        result = ScanResult()
        for name, pattern, threat, desc in self._compiled:
            for match in pattern.finditer(text):
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
