"""Regression: GuardrailsEngine.generate must accept + forward max_tokens/temperature.

The agent wraps the LLM backend in GuardrailsEngine when guardrails are enabled
(the default) and then calls ``backend.generate(model=, prompt=, system=,
max_tokens=, temperature=)`` (agent.py process/synthesize). Before the fix the
wrapper's ``generate`` signature was ``(model, prompt, system="")`` only, so the
real call raised ``TypeError: ... unexpected keyword argument 'max_tokens'`` and
every non-streaming agent call (heartbeats, multi-agent synthesize, digests)
failed until the circuit breaker tripped. ``generate_stream`` already forwarded
them, which is why streamed chat worked and CI missed it.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.base import LLMBackend
from agents.core.llm.tool_protocol import ToolCall, ToolSpec, ToolTurn
from agents.core.security.guardrails import GuardrailsEngine, SecurityBlockError
from agents.core.security.types import RedactionMode


class _RecordingBackend(LLMBackend):
    """Records the generation params it was handed."""

    def __init__(self):
        self.kwargs = None

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        self.kwargs = {"model": model, "prompt": prompt, "system": system,
                       "max_tokens": max_tokens, "temperature": temperature}
        return "ok"

    async def generate_stream(self, model, prompt, system="", max_tokens=1024,
                              temperature=0.7, on_token=None):
        self.kwargs = {"max_tokens": max_tokens, "temperature": temperature}
        return "ok"


async def test_generate_forwards_max_tokens_and_temperature():
    backend = _RecordingBackend()
    engine = GuardrailsEngine(backend, mode=RedactionMode.WARN)
    # The exact call shape agent.py makes (the one that used to raise TypeError).
    out = await engine.generate(
        model="m", prompt="hello", system="sys",
        max_tokens=512, temperature=0.2,
    )
    assert out == "ok"
    assert backend.kwargs["max_tokens"] == 512
    assert backend.kwargs["temperature"] == 0.2
    assert backend.kwargs["system"] == "sys"


async def test_generate_defaults_when_params_omitted():
    backend = _RecordingBackend()
    engine = GuardrailsEngine(backend, mode=RedactionMode.WARN)
    await engine.generate("m", "hi")
    assert backend.kwargs["max_tokens"] == 1024
    assert backend.kwargs["temperature"] == 0.7


# ── scan / redact / block behaviour on findings (covers guardrails.py:68,80,99-120) ──
# The kwarg tests above run in WARN mode (passthrough). These exercise the parts that
# actually act on a finding: REDACT across input/system/output, the streaming path
# (whole method was untested), BLOCK raising, and the defensive unknown-mode fall-through.

_EMAIL = "alice@example.com"  # PII the scanners flag → result.clean is False


class _EchoBackend(LLMBackend):
    """Returns a fixed response and records the (post-scan) prompt/system it received."""

    def __init__(self, response="ok"):
        self.response = response
        self.seen = {}

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        self.seen = {"prompt": prompt, "system": system}
        return self.response

    async def generate_stream(self, model, prompt, system="", max_tokens=1024,
                              temperature=0.7, on_token=None):
        self.seen = {"prompt": prompt, "system": system}
        if on_token:
            for ch in self.response:
                on_token(ch)
        return self.response


async def test_generate_redacts_input_system_and_output():
    be = _EchoBackend(response=f"leaked {_EMAIL}")
    eng = GuardrailsEngine(be, mode=RedactionMode.REDACT)
    out = await eng.generate("m", prompt=f"hi {_EMAIL}", system=f"sys {_EMAIL}")
    assert _EMAIL not in out                  # output scanned + redacted (87-90)
    assert _EMAIL not in be.seen["prompt"]    # input redacted before the backend
    assert _EMAIL not in be.seen["system"]    # system redacted (guardrails.py:80)


async def test_generate_stream_scans_input_system_and_output():
    be = _EchoBackend(response=f"out {_EMAIL}")
    eng = GuardrailsEngine(be, mode=RedactionMode.REDACT)
    streamed = []
    out = await eng.generate_stream("m", prompt=f"p {_EMAIL}", system=f"s {_EMAIL}",
                                    on_token=streamed.append)
    assert _EMAIL not in out                  # guardrails.py:115-118
    assert _EMAIL not in be.seen["prompt"]    # :99-102
    assert _EMAIL not in be.seen["system"]    # :104-107


async def test_block_mode_raises_on_finding():
    eng = GuardrailsEngine(_EchoBackend("clean"), mode=RedactionMode.BLOCK)
    with pytest.raises(SecurityBlockError):
        await eng.generate("m", prompt=f"secret {_EMAIL}")


def test_handle_findings_passthrough_on_unknown_mode():
    # Defensive fall-through (guardrails.py:68): a mode outside WARN/REDACT/BLOCK
    # returns the text unchanged rather than crashing.
    eng = GuardrailsEngine(_EchoBackend("x"), mode="monitor-only")
    payload = f"keep {_EMAIL} intact"
    r = eng._scan_text(payload)
    assert not r.clean
    assert eng._handle_findings(payload, r, "input") == payload


class _RecordingToolBackend(_RecordingBackend):
    """Records guarded tool-turn input and returns a fixed structured turn."""

    supports_tools = True

    def __init__(self):
        super().__init__()
        self.messages = None
        self.tools = None
        self.turn = ToolTurn(
            content=f"leaked {_EMAIL}",
            tool_calls=(
                ToolCall(
                    id="call-echo",
                    name="echo",
                    raw_arguments='{"value":"alice@example.com"}',
                    arguments={"value": _EMAIL},
                ),
            ),
            finish_reason="tool_calls",
        )

    async def generate_tool_turn(
        self,
        model,
        messages,
        tools,
        max_tokens=1024,
        temperature=0.7,
    ):
        self.kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        self.messages = messages
        self.tools = tools
        return self.turn


def test_supports_tools_proxies_wrapped_backend():
    assert GuardrailsEngine(_RecordingToolBackend()).supports_tools is True
    assert GuardrailsEngine(_RecordingBackend()).supports_tools is False


async def test_generate_tool_turn_redacts_string_content_without_mutating_messages():
    backend = _RecordingToolBackend()
    engine = GuardrailsEngine(backend, mode=RedactionMode.REDACT)
    structured_content = [{"type": "text", "text": "leave structured content alone"}]
    messages = [
        {"role": "system", "content": f"system {_EMAIL}"},
        {"role": "user", "content": f"user {_EMAIL}"},
        {"role": "assistant", "content": structured_content},
    ]
    original_messages = [message.copy() for message in messages]
    tool = ToolSpec("echo")

    turn = await engine.generate_tool_turn(
        model="local-model",
        messages=messages,
        tools=[tool],
        max_tokens=321,
        temperature=0.2,
    )

    assert messages == original_messages
    assert all(
        guarded is not original
        for guarded, original in zip(backend.messages, messages, strict=True)
    )
    assert _EMAIL not in backend.messages[0]["content"]
    assert _EMAIL not in backend.messages[1]["content"]
    assert backend.messages[2]["content"] is structured_content
    assert backend.tools == [tool]
    assert backend.kwargs == {
        "model": "local-model",
        "max_tokens": 321,
        "temperature": 0.2,
    }
    assert _EMAIL not in turn.content
    assert turn.tool_calls is backend.turn.tool_calls
    assert turn.tool_calls[0].id == "call-echo"
    assert turn.tool_calls[0].name == "echo"
    assert turn.tool_calls[0].raw_arguments == '{"value":"alice@example.com"}'
    assert turn.finish_reason == "tool_calls"
