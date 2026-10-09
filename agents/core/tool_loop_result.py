"""One settled result from the bounded model-directed tool loop.

This describes the loop's exit, not the outcome of the whole owner turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ToolLoopExitReason(StrEnum):
    MODEL_RESPONSE = "model_response"
    WINDOW_INVALID = "window_invalid"
    CONTEXT_REFUSED = "context_refused"
    TURN_REVOKED = "turn_revoked"
    REPLAY_REFUSED = "replay_refused"
    TOOL_CALL_LIMIT = "tool_call_limit"
    NO_CAPABILITY = "no_capability"
    NO_TOOLS = "no_tools"
    TOOLS_WITHDRAWN = "tools_withdrawn"
    GUARDIAN_DENIED = "guardian_denied"
    REPEATED_CALL = "repeated_call"
    APPROVAL_REQUIRED = "approval_required"
    FAILING_TOOL = "failing_tool"
    ITERATION_LIMIT = "iteration_limit"
    DEADLINE = "deadline"


@dataclass(frozen=True, slots=True)
class ToolLoopResult:
    reply: str
    exit_reason: ToolLoopExitReason
