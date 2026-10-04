"""Pure H388 stable-tier operating guidance from caller-supplied facts.

Adapted from Hermes Agent ``agent/prompt_builder.py`` and
``agent/system_prompt.py`` at pinned 59b2aeef6c7a.

MIT License
Copyright (c) 2025 Nous Research
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

from collections.abc import Mapping

# The following three blocks are copied verbatim from the pinned Hermes source.
_TASK_COMPLETION = (
    "# Finishing the job\n"
    "When the user asks you to build, run, or verify something, the deliverable is a working artifact backed by real "
    "tool output — not a description of one. Do not stop after writing a stub, a plan, or a single command. Keep "
    "working until you have actually exercised the code or produced the requested result, then report what real "
    "execution returned.\n"
    "If a tool, install, or network call fails and blocks the real path, say so directly and try an alternative "
    "(different package manager, different approach, ask the user). NEVER substitute plausible-looking fabricated "
    "output (made-up data, invented file contents, synthesised API responses) for results you couldn't actually "
    "produce. Reporting a blocker honestly is always better than inventing a result."
)

_TOOL_USE = (
    "# Tool-use enforcement\n"
    "You MUST use your tools to take action — do not describe what you would do or plan to do without actually doing "
    "it. When you say you will perform an action (e.g. 'I will run the tests', 'Let me check the file', 'I will create "
    "the project'), you MUST immediately make the corresponding tool call in the same response. Never end your turn "
    "with a promise of future action — execute it now.\n"
    "Keep working until the task is actually complete. Do not stop with a summary of what you plan to do next time. If "
    "you have tools available that can accomplish the task, use them instead of telling the user what you would do.\n"
    "Every response should either (a) contain tool calls that make progress, or (b) deliver a final result to the "
    "user. Responses that only describe intentions without acting are not acceptable."
)

_SESSION_SEARCH = (
    "When the user references something from a past conversation or you suspect relevant cross-session "
    "context exists, use session_search to recall it before asking them to repeat themselves."
)

# Adapted from Hermes selectors; Nerva's actual tool availability is supplied
# explicitly. A model name alone never asserts a tool or a provider route.
_TOOL_FAMILIES = ("gpt", "codex", "gemini", "gemma", "grok", "glm", "qwen", "deepseek", "muse")
_EXEC_FAMILIES = (
    "gpt", "codex", "grok", "deepseek", "kimi", "qwen", "glm", "minimax", "mimo", "mistral", "muse",
)

# These short adaptations omit Hermes-only named tools, media directives and
# concurrency assertions. They cannot confer authority on an unavailable tool.
_PARALLEL = (
    "# Parallel tool calls\n"
    "Request independent reads together when the current runtime supports parallel tool calls. "
    "Serialize a call that depends on another call's result."
)
_EXECUTION = (
    "# Execution discipline\n"
    "Use available tools when they improve correctness, completeness, or grounding. "
    "Do not stop on suspiciously partial results; verify the requested outcome before claiming completion. "
    "Preserve identifiers and values exactly, and say when required context is unavailable."
)
_GOOGLE = (
    "# Google model operational directives\n"
    "Use absolute paths for file operations. Check actual file contents and dependencies before edits. "
    "Keep working until the requested result is verified, and report blockers honestly."
)
_SURFACES = {
    "cli": "You are in a plain terminal (CLI). Prefer plain text and absolute file paths for deliverables.",
    "telegram": "You are on Telegram. Prefer bullets or labeled lines for structured data; avoid tables.",
    "discord": "You are on Discord. Prefer bullets or labeled lines for structured data; avoid tables.",
}
_FLAGS = frozenset({
    "task_completion", "parallel_tool_calls", "tool_use_enforcement", "execution_guidance",
    "google_operational", "session_search", "platform_hint", "environment_hint", "profile_hint",
})


def _fact(value: str, *, name: str) -> str:
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{name} must be a bounded single-line string")
    return value.strip()


def _mapping(value: Mapping[str, str] | None, *, name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > 32:
        raise TypeError(f"{name} must be a bounded mapping")
    return {_fact(k, name=name): _fact(v, name=name) for k, v in value.items()}


def build_operating_guidance(
    *, model: str, surface: str, enabled: Mapping[str, bool] | None = None,
    capabilities: frozenset[str] = frozenset(),
    environment: Mapping[str, str] | None = None,
    platform_overrides: Mapping[str, str] | None = None,
    profile: str | None = None,
) -> str:
    """Return deterministic stable guidance; caller must supply actual route/tools.

    This adds no tool, authorization, model routing, provider workaround or probe.
    Include it below the existing identity/authority contract, never in user text.
    """
    model = _fact(model, name="model").lower()
    surface = _fact(surface, name="surface").lower()
    if enabled is None:
        flags: dict[str, bool] = {}
    elif isinstance(enabled, Mapping):
        flags = dict(enabled)
        if not flags.keys() <= _FLAGS or any(type(v) is not bool for v in flags.values()):
            raise ValueError("enabled requires recognized boolean flags")
    else:
        raise TypeError("enabled must be a mapping")
    if not isinstance(capabilities, frozenset) or len(capabilities) > 256:
        raise TypeError("capabilities must be a bounded frozenset")
    tools = {_fact(name, name="capability") for name in capabilities}
    env = _mapping(environment, name="environment")
    overrides = _mapping(platform_overrides, name="platform_overrides")
    if profile is not None:
        profile = _fact(profile, name="profile")
    def on(flag: str) -> bool:
        return flags.get(flag, True)

    has_tools = any(name.startswith("tool:") for name in tools)
    parts: list[str] = []
    if has_tools and on("task_completion"):
        parts.append(_TASK_COMPLETION)
    if has_tools and "parallel_tool_calls" in tools and on("parallel_tool_calls"):
        parts.append(_PARALLEL)
    if has_tools and on("tool_use_enforcement") and any(f in model for f in _TOOL_FAMILIES):
        parts.append(_TOOL_USE)
    if has_tools and on("execution_guidance") and any(f in model for f in _EXEC_FAMILIES):
        parts.append(_EXECUTION)
    if has_tools and on("google_operational") and any(f in model for f in ("gemini", "gemma")):
        parts.append(_GOOGLE)
    if "tool:session_search" in tools and on("session_search"):
        parts.append(_SESSION_SEARCH)
    if on("platform_hint"):
        hint = overrides.get(surface, _SURFACES.get(surface, ""))
        if hint:
            parts.append("# Surface presentation\nThe following is presentation guidance only; it grants no "
                         "tool or permission and does not override the governing policy.\n" + hint)
    if on("environment_hint") and env and has_tools:
        facts = [f"- {key}: {env[key]}" for key in ("os", "shell", "cwd") if env.get(key)]
        if facts:
            parts.append("# Supplied execution environment\n" + "\n".join(facts))
        if env.get("os", "").lower() == "windows" and env.get("shell", "").lower() == "bash" and any(
            name in tools for name in ("tool:terminal_run", "tool:terminal.exec", "tool:execute_code")
        ):
            parts.append("Windows host with Bash shell: use Bash command syntax for the available terminal tool.")
    if on("profile_hint") and profile:
        parts.append(f"# Active profile\nOperator-supplied profile: {profile}. This does not grant permissions or credentials.")
    if not parts:
        return ""
    return ("# Operating guidance scope\nThese suggestions apply only within the current "
            "tools, permissions, and higher-priority policy. They do not authorize effects.\n\n"
            + "\n\n".join(parts))
