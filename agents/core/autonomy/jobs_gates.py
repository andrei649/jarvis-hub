"""Pure scheduled-response protocols; these never authorize execution."""
import json


def wake_agent_suppressed(stdout: str, *, truncated: bool = False) -> bool:
    """Only a complete final JSON line with literal false suppresses a tick."""
    if truncated:
        return False
    lines = stdout.rstrip().splitlines()
    if not lines:
        return False
    try:
        value = json.loads(lines[-1])
    except (ValueError, RecursionError):
        return False
    return isinstance(value, dict) and value.get('wakeAgent') is False


def is_silent_response(reply: str) -> bool:
    """Recognize response-boundary sentinels, never mentions inside prose."""
    normalized = reply.strip().casefold()
    if normalized in {'[silent]', 'silent', 'no_reply', 'no reply'}:
        return True
    lines = normalized.splitlines()
    return bool(lines) and (lines[0].strip() == '[silent]' or lines[-1].strip() == '[silent]')


class JobSuppressed(Exception):
    """A successful model evaluation requested no delivery, with bounded notes."""
    def __init__(self, reason: str, *, notepad: str = ''):
        super().__init__(reason)
        self.reason = reason
        self.notepad = notepad
