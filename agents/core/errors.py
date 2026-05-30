from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ErrorCategory(str, Enum):
    CONFIG = "config"
    PLUGIN = "plugin"
    CHANNEL = "channel"
    LLM = "llm"
    AUTH = "auth"
    MEMORY = "memory"
    NETWORK = "network"
    SECURITY = "security"
    SANDBOX = "sandbox"
    SKILL = "skill"
    INTERNAL = "internal"


class ErrorSeverity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


COUNTER = {"n": 0}


def _next_code() -> int:
    COUNTER["n"] += 1
    return COUNTER["n"]


@dataclass
class ErrorCode:
    category: ErrorCategory
    number: int
    severity: ErrorSeverity
    message: str


CODES: dict[str, ErrorCode] = {}


def register(cat: ErrorCategory, sev: ErrorSeverity, msg: str) -> str:
    n = _next_code()
    code = f"JARVIS-{cat.upper()}-{n:03d}"
    CODES[code] = ErrorCode(category=cat, number=n, severity=sev, message=msg)
    return code


# Config errors
E_CONFIG_MISSING_ENV = register(ErrorCategory.CONFIG, ErrorSeverity.WARNING, "Required environment variable '{key}' is not set")
E_CONFIG_INVALID_SETTING = register(ErrorCategory.CONFIG, ErrorSeverity.WARNING, "Invalid setting '{key}' with value '{value}'")

# Plugin errors
E_PLUGIN_IMPORT_FAIL = register(ErrorCategory.PLUGIN, ErrorSeverity.ERROR, "Failed to import plugin '{name}': {detail}")
E_PLUGIN_EXEC_FAIL = register(ErrorCategory.PLUGIN, ErrorSeverity.ERROR, "Plugin '{name}' execution failed: {detail}")
E_PLUGIN_BLOCKED = register(ErrorCategory.PLUGIN, ErrorSeverity.WARNING, "Plugin '{name}' blocked by permission gate")

# Channel errors
E_CHANNEL_START_FAIL = register(ErrorCategory.CHANNEL, ErrorSeverity.WARNING, "Channel '{name}' failed to start: {detail}")
E_CHANNEL_SEND_FAIL = register(ErrorCategory.CHANNEL, ErrorSeverity.ERROR, "Channel '{name}' send failed: {detail}")
E_CHANNEL_POLL_FAIL = register(ErrorCategory.CHANNEL, ErrorSeverity.WARNING, "Channel '{name}' poll error: {detail}")

# LLM errors
E_LLM_BACKEND_MISSING = register(ErrorCategory.LLM, ErrorSeverity.ERROR, "LLM backend '{backend}' is not available")
E_LLM_TIMEOUT = register(ErrorCategory.LLM, ErrorSeverity.WARNING, "LLM call timed out after {timeout}s")
E_LLM_RATE_LIMIT = register(ErrorCategory.LLM, ErrorSeverity.WARNING, "LLM rate limit hit, retrying in {retry_after}s")

# Auth errors
E_AUTH_TOKEN_MISSING = register(ErrorCategory.AUTH, ErrorSeverity.WARNING, "OAuth token missing for provider '{provider}'")
E_AUTH_TOKEN_EXPIRED = register(ErrorCategory.AUTH, ErrorSeverity.WARNING, "OAuth token expired for provider '{provider}'")
E_AUTH_REFRESH_FAIL = register(ErrorCategory.AUTH, ErrorSeverity.ERROR, "Token refresh failed for provider '{provider}': {detail}")

# Memory errors
E_MEMORY_WRITE_FAIL = register(ErrorCategory.MEMORY, ErrorSeverity.ERROR, "Memory write failed: {detail}")
E_MEMORY_READ_FAIL = register(ErrorCategory.MEMORY, ErrorSeverity.ERROR, "Memory read failed: {detail}")

# Network errors
E_NETWORK_TIMEOUT = register(ErrorCategory.NETWORK, ErrorSeverity.WARNING, "Network request to '{url}' timed out")
E_NETWORK_FAIL = register(ErrorCategory.NETWORK, ErrorSeverity.ERROR, "Network request to '{url}' failed: {detail}")

# Security errors
E_SECURITY_BLOCKED = register(ErrorCategory.SECURITY, ErrorSeverity.WARNING, "Security guardrail blocked: {reason}")
E_SECURITY_PII_DETECTED = register(ErrorCategory.SECURITY, ErrorSeverity.INFO, "PII detected and {action}: {pattern}")

# Sandbox errors
E_SANDBOX_EXEC_FAIL = register(ErrorCategory.SANDBOX, ErrorSeverity.ERROR, "Sandbox execution failed: {detail}")
E_SANDBOX_TIMEOUT = register(ErrorCategory.SANDBOX, ErrorSeverity.WARNING, "Sandbox execution timed out")

# Skill errors
E_SKILL_IMPORT_FAIL = register(ErrorCategory.SKILL, ErrorSeverity.ERROR, "Failed to import skill '{name}': {detail}")
E_SKILL_EXEC_FAIL = register(ErrorCategory.SKILL, ErrorSeverity.ERROR, "Skill '{name}' execution failed: {detail}")

# Internal errors
E_INTERNAL_UNEXPECTED = register(ErrorCategory.INTERNAL, ErrorSeverity.ERROR, "Unexpected error in {component}: {detail}")


class JarvisError(Exception):
    def __init__(self, code: str, **kwargs):
        self.code = code
        self.meta = kwargs
        entry = CODES.get(code)
        self.category = entry.category if entry else ErrorCategory.INTERNAL
        self.severity = entry.severity if entry else ErrorSeverity.ERROR
        self.message = entry.message.format(**kwargs) if entry else str(kwargs)
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "meta": self.meta,
        }


@dataclass
class ErrorLog:
    code: str
    message: str
    category: ErrorCategory
    severity: ErrorSeverity
    component: str
    timestamp: float
    traceback: Optional[str] = None
    meta: dict = field(default_factory=dict)
