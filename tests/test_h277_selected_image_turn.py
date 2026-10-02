"""An image preview selects a route from the actual agent/session prompt without egress."""

import asyncio

from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.llm.vision_turn import prepare_selected_image_turn
from agents.core.orchestrator import Orchestrator


async def test_image_route_uses_prior_session_history_without_persisting_preview():
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    sid = await orch.memory.new_session("image_route_history")
    await orch.memory.add_turn(sid, "user", "Earlier project context")
    before = await orch.memory.get_history(sid)
    default_session = orch.session_id
    selected = []
    backend = object()

    def choose(agent, prompt):
        selected.append((agent, prompt))
        return backend, "local-vision" if "Earlier project context" in prompt else "local-text", "local"

    orch.llm_router.select_backend = choose
    preview = await prepare_selected_image_turn(
        orch, question="What is in this image?", agent_id="jarvis", session_id=sid)

    assert preview.backend is backend
    assert (preview.model, preview.route, preview.agent_id, preview.session_id) == (
        "local-vision", "local", "jarvis", sid)
    assert selected and selected[0][0] == "jarvis"
    assert "Earlier project context" in selected[0][1]
    assert "What is in this image?" in selected[0][1]
    assert await orch.memory.get_history(sid) == before
    assert orch.session_id == default_session

    await orch.memory.add_turn(sid, "assistant", "Context changed", agent_id="jarvis")
    changed = await prepare_selected_image_turn(
        orch, question="What is in this image?", agent_id="jarvis", session_id=sid)
    assert changed.prompt_digest != preview.prompt_digest


async def test_concurrent_image_previews_do_not_cross_session_or_call_model():
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    sid_a = await orch.memory.new_session("image_route_A")
    sid_b = await orch.memory.new_session("image_route_B")
    await orch.memory.add_turn(sid_a, "user", "Private context A")
    await orch.memory.add_turn(sid_b, "user", "Private context B")
    prompts = []

    def choose(agent, prompt):
        prompts.append(prompt)
        return object(), "model-A" if "Private context A" in prompt else "model-B", "local"

    async def no_model(*_args, **_kwargs):
        raise AssertionError("preview attempted model or plugin work")

    orch.llm_router.select_backend = choose
    orch.router.classify = no_model
    orch._gather_plugin_data = no_model
    orch._recall_block = no_model
    first, second = await asyncio.gather(
        prepare_selected_image_turn(orch, question="Describe it", agent_id="jarvis", session_id=sid_a),
        prepare_selected_image_turn(orch, question="Describe it", agent_id="jarvis", session_id=sid_b),
    )
    assert (first.model, second.model) == ("model-A", "model-B")
    assert any("Private context A" in prompt and "Private context B" not in prompt for prompt in prompts)
    assert any("Private context B" in prompt and "Private context A" not in prompt for prompt in prompts)
    assert len(await orch.memory.get_history(sid_a)) == len(await orch.memory.get_history(sid_b)) == 1
