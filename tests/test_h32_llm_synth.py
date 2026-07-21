"""H32.3/H32.4 — strict-local LLM callables for research drafting and generation.

``llm_synth.generate_capability``/``draft_plan`` are the concrete strict-local
implementations of the ``generate``/``draft`` seams ``StrictLocalGenerator``
(generator.py) and ``GovernedResearch`` (research.py) take by injection. These
tests exercise the callables in isolation against a fake router/backend —
downstream AST/grounding validation is already covered by
``test_h32_generation_sandbox.py`` / ``test_h32_governed_research.py`` and is
untouched here.
"""

from __future__ import annotations

import json

import pytest

from agents.core.acquisition.llm_synth import SynthesisError, draft_plan, generate_capability


class _FakeBackend:
    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.calls: list[dict] = []

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        self.calls.append({
            "model": model, "prompt": prompt, "system": system,
            "max_tokens": max_tokens, "temperature": temperature,
        })
        return self._replies.pop(0)


class _FakeRouter:
    def __init__(self, replies: list[str], model="gemma-test"):
        self.local_backend = _FakeBackend(replies)
        self.active_model = model


_PROMPT = {
    "schema": 1,
    "goal": "parse Acme API items into a normalized list",
    "entrypoint": "run",
    "contract_hash": "c" * 64,
    "plan_hash": "p" * 64,
    "requirements": ["Python stdlib allowlist only", "return JSON-serializable values"],
}

_PACKAGE_JSON = json.dumps({
    "name": "acme_item_parser",
    "entrypoint": "run",
    "code": "def run(payload):\n    return [item['id'] for item in payload.get('items', [])]\n",
    "test": (
        "import unittest\nfrom main import run\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_items(self):\n"
        "        self.assertEqual(run({'items': [{'id': 3}]}), [3])\n"
    ),
})


async def test_generate_capability_parses_plain_json():
    router = _FakeRouter([_PACKAGE_JSON])
    out = await generate_capability(_PROMPT, router=router)
    assert out["name"] == "acme_item_parser"
    assert out["entrypoint"] == "run"
    assert "def run" in out["code"]
    # The model is told the required entrypoint verbatim.
    assert '"run"' in router.local_backend.calls[0]["system"]


async def test_generate_capability_parses_fenced_json():
    fenced = f"Here you go:\n```json\n{_PACKAGE_JSON}\n```"
    router = _FakeRouter([fenced])
    out = await generate_capability(_PROMPT, router=router)
    assert out["name"] == "acme_item_parser"


async def test_generate_capability_retries_once_on_malformed_reply():
    router = _FakeRouter(["not json at all", _PACKAGE_JSON])
    out = await generate_capability(_PROMPT, router=router)
    assert out["name"] == "acme_item_parser"
    assert len(router.local_backend.calls) == 2
    # Retry uses a lower (deterministic) temperature.
    assert router.local_backend.calls[1]["temperature"] == 0.0


async def test_generate_capability_raises_after_exhausting_attempts():
    router = _FakeRouter(["nope", "still nope"])
    with pytest.raises(SynthesisError):
        await generate_capability(_PROMPT, router=router)
    assert len(router.local_backend.calls) == 2


async def test_generate_capability_rejects_non_object_json():
    router = _FakeRouter(["[1, 2, 3]", _PACKAGE_JSON])
    out = await generate_capability(_PROMPT, router=router)
    assert out["name"] == "acme_item_parser"
    assert len(router.local_backend.calls) == 2


_REFERENCES = [
    {"id": "src-aaaa", "title": "Acme item contract", "url": "https://docs.example.com/acme"},
]

_STEPS_JSON = json.dumps([{"text": "Read item ids in list order.", "cites": ["src-aaaa"]}])


async def test_draft_plan_parses_plain_json():
    router = _FakeRouter([_STEPS_JSON])
    steps = await draft_plan("parse Acme API items", _REFERENCES, router=router)
    assert steps == [{"text": "Read item ids in list order.", "cites": ["src-aaaa"]}]
    # Only the bounded id/title/url catalog is sent, not raw extracted text.
    sent = json.loads(router.local_backend.calls[0]["prompt"])
    assert sent["references"] == [
        {"id": "src-aaaa", "title": "Acme item contract", "url": "https://docs.example.com/acme"}
    ]


async def test_draft_plan_rejects_non_array_json():
    router = _FakeRouter(['{"not": "a list"}', _STEPS_JSON])
    steps = await draft_plan("parse Acme API items", _REFERENCES, router=router)
    assert isinstance(steps, list)
    assert len(router.local_backend.calls) == 2


async def test_draft_plan_raises_after_exhausting_attempts():
    router = _FakeRouter(["nope", "still nope"])
    with pytest.raises(SynthesisError):
        await draft_plan("parse Acme API items", _REFERENCES, router=router)
