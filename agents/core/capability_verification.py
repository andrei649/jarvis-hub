"""Stable reality-harness identifiers for executable capabilities."""

HARNESS_ID = "reality-v1"


def reality_ref(case_name: str) -> str:
    return f"{HARNESS_ID}:{case_name}"


def action_case_name(kind: str) -> str:
    slug = kind.replace(".*", "-wildcard").replace(".", "-")
    return f"action-{slug}-kernel-halt"


def action_verification_ref(kind: str) -> str:
    return reality_ref(action_case_name(kind))


def tool_case_name(name: str) -> str:
    return f"tool-{name}-protocol"


def tool_verification_ref(name: str) -> str:
    return reality_ref(tool_case_name(name))
