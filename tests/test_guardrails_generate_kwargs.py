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

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.base import LLMBackend
from agents.core.security.guardrails import GuardrailsEngine
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
