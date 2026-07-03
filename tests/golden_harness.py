"""Golden-loop harness (ORIZONT 26 · O26-P0.1).

Builds a REAL Orchestrator — real IntentRouter, real agents from
``agents/_system/agents.yaml``, real memory/learning/bench/run-history/entity
stores, real guardrails and audit — with exactly ONE fake: an ``LLMBackend``
whose ``generate()`` returns a canned deterministic reply. The fake sits at the
same seam a live LM Studio/Ollama backend does (installed via the router's
``detect()``), so a green golden loop means the production turn pipeline is
actually bolted together end to end, not that a stub happened to line up.

This is deliberately the opposite of the ``__new__``-style unit tests: nothing
above the ``generate()`` seam may be stubbed here (no ``_call_agents_parallel``
/ ``classify`` / ``_synthesize`` replacement). New golden loops (approval
funnel, morning brief, kill-switch, onboarding posture) should reuse
``make_golden_orchestrator`` and only script the FakeBackend's replies.

Used by: tests/test_golden_loop_chat.py (loop #1). Not collected by pytest
(no ``test_`` prefix) — it is a shared fixture library.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.config import JarvisConfig  # noqa: E402
from agents.core.llm.base import LLMBackend  # noqa: E402
from agents.core.orchestrator import Orchestrator  # noqa: E402

FAKE_MODEL = "golden-fake-model"
FAKE_BACKEND_NAME = "fake-local"
DEFAULT_REPLY = "Certainly, sir — the golden loop is alive."


class FakeBackend(LLMBackend):
    """Deterministic stand-in for a local LLM server.

    Records every ``generate()`` call (model/prompt/system) so loops can assert
    on what actually reached the LLM seam (e.g. "turn 2's prompt carries turn
    1's history"). ``generate_stream`` is inherited from ``LLMBackend`` — the
    default emits the full reply through ``on_token``, which is precisely the
    streaming contract at this seam.
    """

    def __init__(self, reply: str = DEFAULT_REPLY):
        self.reply = reply
        self.calls: list[dict] = []

    async def generate(self, model: str, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> str:
        self.calls.append({"model": model, "prompt": prompt, "system": system,
                           "max_tokens": max_tokens, "temperature": temperature})
        return self.reply


async def make_golden_orchestrator(monkeypatch, tmp_path,
                                   reply: str = DEFAULT_REPLY):
    """A fully-loaded real Orchestrator with the LLM faked at ``generate()``.

    - ``JARVIS_HOME`` → tmp_path: every store that resolves its path at
      construction time isolates into the test dir (stores whose module bound a
      default path at import keep the suite-wide location; golden tests must
      therefore assert deltas, never store emptiness).
    - ``detect()`` is replaced so the router "detects" the FakeBackend as the
      live local backend — the same wiring a real install gets from LM Studio.
      Cloud/Claude/Ollama stay unavailable: routing exercises the local path.

    Returns ``(orch, fake)``.
    """
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    # No fire-and-forget warm-up task — it would race the test's event loop.
    monkeypatch.setenv("JARVIS_LLM_WARMUP", "0")

    fake = FakeBackend(reply=reply)
    orch = Orchestrator(JarvisConfig())

    async def _fake_detect():
        r = orch.llm_router
        r._backend = fake
        r._backend_name = FAKE_BACKEND_NAME
        r._detected_model = FAKE_MODEL
        r._local_model = FAKE_MODEL
        r._local_available = True
        r._ollama_available = False
        r._cloud_available = False
        r._claude_available = False

    monkeypatch.setattr(orch.llm_router, "detect", _fake_detect)
    await orch.load_agents()
    return orch, fake
