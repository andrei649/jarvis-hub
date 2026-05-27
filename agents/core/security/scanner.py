"""
scanner.py — Pure-Python PII and secret regex scanners.

Port of OpenJarvis's Rust-based scanners to pure Python.
"""

import re
from typing import Optional

from .types import ScanFinding, ScanResult, ThreatLevel


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
        "password_assignment": (r"""(?:password|passwd|pwd)\s*[=:]\s*['"]([^'"]{4,})['"]""", ThreatLevel.HIGH, "Password assignment"),
        "db_connection_string": (r"(?:postgres|mysql|mongodb|redis)://[^\s]{10,}", ThreatLevel.HIGH, "Database connection string"),
        "private_key": (r"-----BEGIN (?:RSA )?PRIVATE KEY-----", ThreatLevel.CRITICAL, "Private key"),
        "slack_token": (r"xox[bpors]-[A-Za-z0-9\-]{10,}", ThreatLevel.HIGH, "Slack token"),
        "stripe_key": (r"(?:sk|pk)_(?:test|live)_[A-Za-z0-9]{20,}", ThreatLevel.CRITICAL, "Stripe key"),
        "generic_api_key": (r"""(?:api_key|secret_key|auth_token)\s*[=:]\s*['"]([^'"]{8,})['"]""", ThreatLevel.HIGH, "Generic API key/secret"),
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
