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

import json
import logging
import sys
from pathlib import Path
from typing import get_type_hints

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.base import LLMBackend
from agents.core.llm.tool_protocol import ToolCall, ToolSpec, ToolTurn
from agents.core.security.guardrails import (
    GuardrailsEngine,
    SecurityBlockError,
    bind_guardrails,
)
from agents.core.security.scanner import PIIScanner, SecretScanner
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


class _CompletionAwareEchoBackend(_EchoBackend):
    """Records whether callbacks run before the provider completes."""

    def __init__(self, response="ok"):
        super().__init__(response)
        self.completed = False

    async def generate_stream(
        self,
        model,
        prompt,
        system="",
        max_tokens=1024,
        temperature=0.7,
        on_token=None,
    ):
        self.seen = {"prompt": prompt, "system": system}
        if on_token:
            for char in self.response:
                on_token(char)
        self.completed = True
        return self.response


async def test_unbound_policy_rejects_generation():
    from agents.core.security.guardrails import GuardrailBindingError

    policy = GuardrailsEngine(backend=None)
    with pytest.raises(GuardrailBindingError):
        await policy.generate("m", "hello")


def test_bind_returns_distinct_wrapper_with_same_policy():
    policy = GuardrailsEngine(backend=None, mode=RedactionMode.REDACT)
    first = policy.bind(_EchoBackend("one"))
    second = policy.bind(_EchoBackend("two"))
    assert first is not second
    assert first._backend is not second._backend
    assert first.policy_fingerprint() == second.policy_fingerprint()
    assert policy._backend is None


def test_bind_guardrails_return_annotation_matches_runtime():
    backend = _EchoBackend()
    policy = GuardrailsEngine(backend=None)

    assert get_type_hints(bind_guardrails)["return"] == (
        GuardrailsEngine | LLMBackend
    )
    assert bind_guardrails(None, backend) is backend
    assert isinstance(bind_guardrails(policy, backend), GuardrailsEngine)


def test_policy_fingerprint_is_deterministic_for_equivalent_scanners():
    first = GuardrailsEngine(
        backend=None,
        scanners=(SecretScanner(), PIIScanner()),
    )
    second = GuardrailsEngine(
        backend=None,
        scanners=(SecretScanner(), PIIScanner()),
    )

    assert first.policy_fingerprint() == second.policy_fingerprint()


def test_policy_fingerprint_changes_with_mode_flags_and_scanners():
    fingerprints = {
        GuardrailsEngine(backend=None).policy_fingerprint(),
        GuardrailsEngine(
            backend=None,
            mode=RedactionMode.REDACT,
        ).policy_fingerprint(),
        GuardrailsEngine(
            backend=None,
            scan_input=False,
        ).policy_fingerprint(),
        GuardrailsEngine(
            backend=None,
            scan_output=False,
        ).policy_fingerprint(),
        GuardrailsEngine(
            backend=None,
            scanners=(PIIScanner(),),
        ).policy_fingerprint(),
    }

    assert len(fingerprints) == 5


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


async def test_generate_stream_redact_buffers_before_callback():
    emitted = []
    engine = GuardrailsEngine(_EchoBackend(f"mail {_EMAIL}"), mode=RedactionMode.REDACT)
    result = await engine.generate_stream("m", "safe", on_token=emitted.append)
    assert _EMAIL not in result
    assert emitted == [result]


async def test_generate_stream_block_emits_nothing():
    emitted = []
    engine = GuardrailsEngine(_EchoBackend(f"mail {_EMAIL}"), mode=RedactionMode.BLOCK)
    with pytest.raises(SecurityBlockError):
        await engine.generate_stream("m", "safe", on_token=emitted.append)
    assert emitted == []


async def test_generate_stream_warn_forwards_tokens_before_provider_completion():
    backend = _CompletionAwareEchoBackend("safe")
    completion_states = []
    emitted = []

    def on_token(token):
        completion_states.append(backend.completed)
        emitted.append(token)

    result = await GuardrailsEngine(
        backend,
        mode=RedactionMode.WARN,
    ).generate_stream("m", "safe", on_token=on_token)

    assert result == "safe"
    assert emitted == list(result)
    assert completion_states == [False] * len(result)


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
    assert turn.tool_calls is not backend.turn.tool_calls
    assert turn.tool_calls[0].id == "call-echo"
    assert turn.tool_calls[0].name == "echo"
    assert _EMAIL not in turn.tool_calls[0].raw_arguments
    assert turn.finish_reason == "tool_calls"


async def test_generate_tool_turn_redacts_arguments_consistently():
    backend = _RecordingToolBackend()
    engine = GuardrailsEngine(backend, mode=RedactionMode.REDACT)

    turn = await engine.generate_tool_turn(
        model="local-model",
        messages=[{"role": "user", "content": "safe"}],
        tools=[ToolSpec("echo")],
    )

    original = backend.turn.tool_calls[0]
    guarded = turn.tool_calls[0]
    assert guarded.id == original.id
    assert guarded.name == original.name
    assert _EMAIL not in guarded.raw_arguments
    assert json.loads(guarded.raw_arguments) == guarded.arguments


async def test_generate_tool_turn_non_string_finding_fails_closed():
    backend = _RecordingToolBackend()
    backend.turn = ToolTurn(
        tool_calls=(
            ToolCall(
                id="call-card",
                name="charge",
                raw_arguments='{"card":4111111111111111}',
                arguments={"card": 4111111111111111},
            ),
        ),
        finish_reason="tool_calls",
    )
    engine = GuardrailsEngine(backend, mode=RedactionMode.REDACT)

    with pytest.raises(SecurityBlockError):
        await engine.generate_tool_turn(
            model="local-model",
            messages=[{"role": "user", "content": "safe"}],
            tools=[ToolSpec("charge")],
        )


async def test_generate_tool_turn_warn_preserves_string_findings():
    backend = _RecordingToolBackend()
    original = backend.turn.tool_calls[0]
    engine = GuardrailsEngine(backend, mode=RedactionMode.WARN)

    turn = await engine.generate_tool_turn(
        model="local-model",
        messages=[{"role": "user", "content": "safe"}],
        tools=[ToolSpec("echo")],
    )

    assert turn.tool_calls[0] is original
    assert turn.tool_calls[0].arguments == {"value": _EMAIL}
    assert turn.tool_calls[0].raw_arguments == '{"value":"alice@example.com"}'


async def test_generate_tool_turn_warn_observes_non_string_finding(caplog):
    backend = _RecordingToolBackend()
    backend.turn = ToolTurn(
        tool_calls=(
            ToolCall(
                id="call-card",
                name="charge",
                raw_arguments='{"card":4111111111111111}',
                arguments={"card": 4111111111111111},
            ),
        ),
        finish_reason="tool_calls",
    )
    original = backend.turn.tool_calls[0]
    engine = GuardrailsEngine(backend, mode=RedactionMode.WARN)

    with caplog.at_level(logging.WARNING, logger="jarvis.security"):
        turn = await engine.generate_tool_turn(
            model="local-model",
            messages=[{"role": "user", "content": "safe"}],
            tools=[ToolSpec("charge")],
        )

    assert turn.tool_calls[0] is original
    assert turn.tool_calls[0].arguments == {"card": 4111111111111111}
    assert turn.tool_calls[0].raw_arguments == '{"card":4111111111111111}'
    assert "credit_card_visa" in caplog.text


def test_prepare_cache_material_redacts_copy_without_mutation():
    history = (f"user {_EMAIL}", "assistant safe")
    original_history = tuple(history)
    engine = GuardrailsEngine(backend=None, mode=RedactionMode.REDACT)

    material = engine.prepare_cache_material(f"system {_EMAIL}", history)

    assert _EMAIL not in material.system_instruction
    assert all(_EMAIL not in part for part in material.history)
    assert material.history is not history
    assert history == original_history
    assert material.policy_fingerprint == engine.policy_fingerprint()

    cache_writes = []
    blocking = GuardrailsEngine(backend=None, mode=RedactionMode.BLOCK)
    with pytest.raises(SecurityBlockError):
        cache_writes.append(
            blocking.prepare_cache_material(f"system {_EMAIL}", history)
        )
    assert cache_writes == []


def test_prepare_cache_material_redacts_when_input_scan_is_disabled():
    engine = GuardrailsEngine(
        backend=None,
        mode=RedactionMode.REDACT,
        scan_input=False,
    )

    material = engine.prepare_cache_material(
        f"system {_EMAIL}",
        (f"user {_EMAIL}",),
    )

    assert _EMAIL not in material.system_instruction
    assert _EMAIL not in material.history[0]


def test_prepare_cache_material_blocks_when_input_scan_is_disabled():
    engine = GuardrailsEngine(
        backend=None,
        mode=RedactionMode.BLOCK,
        scan_input=False,
    )

    with pytest.raises(SecurityBlockError):
        engine.prepare_cache_material(f"system {_EMAIL}", ("safe",))
