"""Actual local auxiliary dispatch must not inherit interactive cloud consent."""
import asyncio
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.commands import Principal
from agents.core.llm import data_handling
from agents.core.llm.job_selection import SelectionError, selection_scope
from agents.core.llm.model_config import DEFAULT_LOCAL_MODEL
from agents.core.llm.providers import get_profile
from agents.core.orchestrator import Orchestrator, bind_turn_principal, reset_turn_principal

ROLES = ["session_title", "query_rewrite", "review", "compression"]


@pytest.fixture
def auxiliary(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(data_handling, "_scope_key", lambda: b"synthetic-auxiliary-key")
    calls = []
    async def generate(**kwargs):
        calls.append(("generate", kwargs))
        return "auxiliary answer"
    async def generate_stream(**kwargs):
        calls.append(("stream", kwargs))
        await kwargs["on_token"]("auxiliary answer")
        return "auxiliary answer"
    backend = SimpleNamespace(profile=get_profile("lm-studio"), base_url="http://127.0.0.1:1234",
                              generate=generate, generate_stream=generate_stream)
    router = SimpleNamespace(local_backend=backend, active_model="qwen3-synthetic",
                             _backend=backend, _local_model="qwen3-synthetic")
    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = router
    orch.get_setting = lambda key, default=None: default
    return SimpleNamespace(orch=orch, backend=backend, router=router, calls=calls)


async def invoke(orch, role):
    if role == "session_title":
        return await orch._session_titler()(system="title system", prompt="private prompt")
    if role == "query_rewrite":
        return await orch._query_rewriter()(system="rewrite system", prompt="private prompt")
    if role == "review":
        return await orch._review_llm("private prompt")
    return await orch._compression_summarizer()("private prompt")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_copied_owner_context_cannot_authorize_offloopback_auxiliary(auxiliary, role):
    from agents.core.action_origin import bind_action_origin, reset_action_origin

    auxiliary.backend.base_url = "https://synthetic.invalid/v1"
    principal = bind_turn_principal(Principal(channel="web", admin=True))
    origin = bind_action_origin("inbound")
    try:
        with pytest.raises(data_handling.DataHandlingRefused, match="acknowledg"):
            await asyncio.create_task(invoke(auxiliary.orch, role))
        assert auxiliary.calls == []
    finally:
        reset_action_origin(origin)
        reset_turn_principal(principal)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_loopback_auxiliary_preserves_generation_contract(auxiliary, role):
    assert await invoke(auxiliary.orch, role) == "auxiliary answer"
    assert len(auxiliary.calls) == 1
    method, request = auxiliary.calls[0]
    assert request["model"] == (DEFAULT_LOCAL_MODEL if role == "session_title" else "qwen3-synthetic")
    assert request["max_tokens"] == {"session_title": 24, "query_rewrite": 96, "review": 512, "compression": 256}[role]
    assert request["temperature"] == {"session_title": 0.0, "query_rewrite": 0.0, "review": .2, "compression": .2}[role]
    assert method == ("stream" if role == "compression" else "generate")
    assert request["prompt"].endswith("/no_think") is (role in {"session_title", "query_rewrite"})


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_every_auxiliary_is_excluded_under_job_model_pin(auxiliary, role):
    with selection_scope({"model": "synthetic-model", "provider": "lm-studio"}), pytest.raises(SelectionError, match="auxiliary"):
        await invoke(auxiliary.orch, role)
    assert auxiliary.calls == []


@pytest.mark.asyncio
async def test_refused_auxiliaries_preserve_their_existing_fallbacks(auxiliary):
    from agents.core.context_compressor import ContextCompressor
    from agents.core.learning.background_review import BackgroundReviewer
    from agents.core.session_titles import instant_title

    auxiliary.backend.base_url = "https://synthetic.invalid/v1"
    manager = SimpleNamespace(set_session_title=lambda *args, **kwargs: pytest.fail("refusal replaced first-words title"))
    assert instant_title("Plan my private trip")
    assert not await auxiliary.orch._upgrade_session_title(manager, "s", "Plan my private trip", auxiliary.orch._session_titler())
    recalled = []
    async def recall(text, **kwargs):
        recalled.append(text)
        return ["hit"]
    auxiliary.orch.memory = SimpleNamespace(recall=recall)
    auxiliary.orch.get_setting = lambda key, default=None: True if key == "memory.recall_query_rewrite" else default
    assert await auxiliary.orch._recall_hits("what did I decide?") == ["hit"]
    assert recalled == ["what did I decide?"]
    review = BackgroundReviewer(auxiliary.orch._review_llm)
    result = await review.run_on_demand("private user/assistant conversation")
    assert not result["ran"] and result["reason"] == "llm_error" and result["actions"] == []
    turns = [{"role": "user", "content": "private text " * 100} for _ in range(6)]
    compressor = ContextCompressor(summarizer=auxiliary.orch._compression_summarizer(), max_tokens=100, keep_recent=1)
    compressed = await compressor.compress(turns)
    assert compressed["compressed"] and "[summary of earlier conversation]" in compressed["summary"]
    assert auxiliary.calls == []
