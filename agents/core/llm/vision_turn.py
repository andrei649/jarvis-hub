"""Read-only selection of the active agent's image-turn route."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256

from agents.core.validation import is_valid_session_id


@dataclass(frozen=True)
class SelectedImageTurn:
    session_id: str
    agent_id: str
    prompt_digest: str
    history_digest: str
    backend: object
    model: str
    route: str
    prompt: str = field(repr=False)


def history_fingerprint(orch, session_id: str) -> str:
    """Fingerprint the entire in-process transcript and its session instance."""
    conversation = orch.memory.conversation
    turns = conversation.sessions.get(session_id)
    if turns is None:
        raise ValueError("image session unavailable")
    state = (conversation.instances.get(session_id), id(turns), [turn.to_dict() for turn in turns])
    encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return sha256(encoded).hexdigest()


async def prepare_selected_image_turn(
    orch, *, question: str, agent_id: str, session_id: str
) -> SelectedImageTurn:
    """Select from the prompt an image turn would use, without sending or saving it."""
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        raise ValueError("invalid image question")
    if not is_valid_session_id(session_id):
        raise ValueError("invalid image session")
    if agent_id not in orch.agents:
        raise ValueError("unknown image agent")

    # Orchestrator's session is request-local. Restore both context variables even
    # when prompt construction or route selection raises.
    from agents.core.orchestrator import _active_session, _session_is_shared

    session_token = _active_session.set(session_id)
    shared_token = _session_is_shared.set(session_id == orch._session_id_default)
    try:
        history_digest = history_fingerprint(orch, session_id)
        window = int(orch.get_setting("memory.context_window", 6))
        # Ordinary streaming saves the proposed user turn before fetching its
        # last N turns, then removes that turn from the rendered prompt.
        prior_turns = max(0, window - 1)
        rows = await orch.memory.get_history(session_id, last_n=prior_turns) if prior_turns else []
        history = "\n".join(
            f"[{row.get('agent_id') or row['role']}]: {row['content']}" for row in rows
        )
        intent = await orch.router.classify_deterministic(question, orch.agents)
        runtime = orch._runtime_state_block() + orch._language_block() + orch._data_grounding_block({})
        turn_text = await orch._build_agent_turn_text(
            agent_id, question, history=history, runtime_block=runtime, freeze_core=False
        )
        prompt = orch._build_agent_prompt(orch.agents[agent_id], turn_text, intent.context)
        checkpoint = orch.checkpoints.load(agent_id, session_id)
        if checkpoint:
            prompt = f"[RESUMED FROM CHECKPOINT]\n{checkpoint['prompt']}\n---\n{prompt}"
        backend, model, route = orch.llm_router.select_backend(agent_id, prompt)
        if history_fingerprint(orch, session_id) != history_digest:
            raise ValueError("image history changed during selection")
        return SelectedImageTurn(
            session_id=session_id,
            agent_id=agent_id,
            prompt_digest=sha256(prompt.encode("utf-8")).hexdigest(),
            history_digest=history_digest,
            backend=backend,
            model=model,
            route=route,
            prompt=prompt,
        )
    finally:
        _session_is_shared.reset(shared_token)
        _active_session.reset(session_token)
