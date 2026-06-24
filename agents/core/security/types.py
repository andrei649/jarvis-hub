"""
types.py — Security data types: scan results, threats, events.
"""

from dataclasses import dataclass, field
from enum import Enum


class ThreatLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RedactionMode(str, Enum):
    WARN = "warn"
    REDACT = "redact"
    BLOCK = "block"


class SecurityEventType(str, Enum):
    SECRET_DETECTED = "secret_detected"
    PII_DETECTED = "pii_detected"
    SSRF_BLOCKED = "ssrf_blocked"
    AUDIT_LOG = "audit_log"
    LLM_CALL = "llm_call"
    SETTINGS_CHANGE = "settings_change"


@dataclass
class ScanFinding:
    pattern_name: str
    matched_text: str
    threat_level: ThreatLevel
    start: int
    end: int
    description: str = ""


@dataclass
class ScanResult:
    findings: list[ScanFinding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return len(self.findings) == 0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.threat_level == ThreatLevel.CRITICAL)


@dataclass
class SecurityEvent:
    event_type: SecurityEventType
    timestamp: float
    findings: list[ScanFinding] = field(default_factory=list)
    content_preview: str = ""
    action_taken: str = ""
