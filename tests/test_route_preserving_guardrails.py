"""Guardrail bindings must preserve the router's per-request backend choice."""

import inspect
from types import SimpleNamespace

import pytest

import agents.core.orchestrator as orchestrator_module
from agents.core.agent import Agent
from agents.core.llm.base import LLMBackend
from agents.core.llm.hybrid_router import (
    HybridRouter,
    LocalBackendUnavailableError,
)
from agents.core.orchestrator import Orchestrator
from agents.core.security.guardrails import GuardrailsEngine

EXPECTED_LOCAL_UNAVAILABLE_REPLY = (
    "⚠️ No local language model is available. "
    "Start LM Studio or Ollama and try again."
)


class RecordingBackend(LLMBackend):
    supports_tools = True

    def __init__(self, answer: str):
        self.answer = answer
        self.calls = []

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        self.calls.append(
            {
                "kind": "generate",
                "model": model,
                "prompt": prompt,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        return self.answer

    async def generate_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        on_token=None,
    ) -> str:
        self.calls.append(
            {
                "kind": "stream",
                "model": model,
                "prompt": prompt,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if on_token is not None:
            emitted = on_token(self.answer)
            if inspect.isawaitable(emitted):
                await emitted
        return self.answer


class StaticRouter:
    model_manager = None

    def __init__(self, backend: RecordingBackend, route: str = "local"):
        self.backend = backend
        self.route = route

    def select_backend(self, agent_id: str, prompt: str):
        return self.backend, f"{self.route}-model", self.route


class RecordingToolRuntime:
    def __init__(self):
        self.backends = []

    def can_run(self, backend) -> bool:
        return backend.supports_tools

    async def run(self, **kwargs) -> str:
        backend = kwargs["backend"]
        self.backends.append(backend)
        return await backend.generate(
            model=kwargs["model"],
            prompt=kwargs["prompt"],
            system=kwargs["system"],
            max_tokens=kwargs["max_tokens"],
            temperature=kwargs["temperature"],
        )


def streamed_orchestrator_for(agent: Agent, router, security: GuardrailsEngine):
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator._session_id_default = None

    class Memory:
        async def add_turn(self, *args, **kwargs):
            return None

    class Intent:
        target_agents = [agent.id]
        is_general = True
        confidence = 1.0
        context = {"keywords_found": [], "scores": {}, "source": "test"}

    async def classify(text, agents):
        return Intent()

    async def empty_mapping(*args, **kwargs):
        return {}

    async def empty_text(*args, **kwargs):
        return ""

    async def prepared_turn(*args, **kwargs):
        return "prepared turn"

    async def complete_turn(**kwargs):
        return None

    orchestrator.memory = Memory()
    orchestrator.skills = SimpleNamespace(parse_command=lambda text: None)
    orchestrator._chat_control_enabled = lambda: False
    orchestrator.router = SimpleNamespace(classify=classify)
    orchestrator._gather_plugin_data = empty_mapping
    orchestrator._history_for_prompt = empty_text
    orchestrator._recall_block = empty_text
    orchestrator._runtime_state_block = lambda: ""
    orchestrator._build_agent_turn_text = prepared_turn
    orchestrator._route_candidates = lambda intent: intent.target_agents
    orchestrator.agents = {agent.id: agent}
    orchestrator.llm_router = router
    orchestrator.checkpoints = SimpleNamespace(
        load=lambda agent_id, session_id: None,
    )
    orchestrator.security = security
    orchestrator.context_cache = None
    orchestrator.get_setting = lambda key, default=None: default
    orchestrator._agent_gen_params = lambda selected_agent, route_name: (128, 0.0)
    orchestrator._complete_llm_turn = complete_turn
    return orchestrator


def build_agent(
    agent_id: str,
    *,
    local: RecordingBackend,
    gemini: RecordingBackend,
    claude: RecordingBackend,
) -> Agent:
    router = HybridRouter(
        gemini_api_key="configured-for-test",
        anthropic_api_key="configured-for-test",
    )
    router._local_available = True
    router._backend = local
    router._local_model = "local-model"
    router._cloud_available = True
    router._gemini_backend = gemini
    router._gemini_model = "gemini-model"
    router._claude_available = True
    router._claude_backend = claude
    router._claude_model = "claude-model"
    router._ollama_available = False
    router._deep_model_available = lambda: False

    agent = Agent(agent_id, {"name": agent_id.title(), "model": "configured"}, router)
    agent.soul = {"content": "test policy"}
    agent.build_prompt = lambda text, context: text
    agent._gen_params = lambda route_name: (128, 0.0)
    return agent


@pytest.mark.parametrize("agent_id", ["frigga", "ultron", "howard"])
@pytest.mark.asyncio
async def test_local_only_agents_never_call_cloud_after_guardrail_binding(agent_id):
    local = RecordingBackend("local answer")
    gemini = RecordingBackend("gemini answer")
    claude = RecordingBackend("claude answer")
    agent = build_agent(agent_id, local=local, gemini=gemini, claude=claude)
    agent.guardrails = GuardrailsEngine(backend=claude)

    assert await agent.process("private request", {"session_id": "s"}) == "local answer"
    assert len(local.calls) == 1
    assert gemini.calls == []
    assert claude.calls == []


@pytest.mark.asyncio
async def test_tool_runtime_receives_wrapper_bound_to_selected_backend():
    selected = RecordingBackend("tool answer")
    boot_backend = RecordingBackend("boot answer")
    agent = Agent("jarvis", {"name": "Jarvis"}, StaticRouter(selected))
    agent.soul = {"content": "test policy"}
    agent.build_prompt = lambda text, context: text
    agent._gen_params = lambda route_name: (128, 0.0)
    agent.guardrails = GuardrailsEngine(backend=boot_backend)
    runtime = RecordingToolRuntime()
    agent.tool_runtime = runtime

    assert await agent.process("use a tool", {"session_id": "s"}) == "tool answer"
    assert len(runtime.backends) == 1
    assert isinstance(runtime.backends[0], GuardrailsEngine)
    assert runtime.backends[0] is not agent.guardrails
    assert runtime.backends[0]._backend is selected
    assert agent.guardrails._backend is boot_backend
    assert len(selected.calls) == 1
    assert boot_backend.calls == []


@pytest.mark.asyncio
async def test_synthesis_uses_selected_backend_not_boot_backend():
    selected = RecordingBackend("selected synthesis")
    boot_backend = RecordingBackend("boot synthesis")
    agent = Agent("jarvis", {"name": "Jarvis"}, StaticRouter(selected))
    agent.soul = {"content": "test policy"}
    agent._gen_params = lambda route_name: (128, 0.0)
    agent.guardrails = GuardrailsEngine(backend=boot_backend)

    # Contributors are deliberately NOT strict-local. This test is about route
    # preservation (the selected backend wins over the boot one), and it used to pass
    # frigga + ultron — which meant it was also asserting that jarvis may synthesize a
    # strict-local agent's raw output through a cloud-eligible backend. That was the
    # SEC-B1 hole, encoded as expected behaviour. The floor is covered on its own below.
    result = await agent.synthesize(
        {"stark": "engineering report", "athena": "strategy report"},
        intent=None,
    )

    assert result == "selected synthesis"
    assert len(selected.calls) == 1
    assert boot_backend.calls == []


@pytest.mark.asyncio
async def test_synthesis_pins_local_when_any_contributor_is_strict_local():
    """SEC-B1: the floor is over CONTRIBUTORS, not over the synthesizing agent.

    `Agent.synthesize` embeds every responder's raw text in its prompt and then routed as
    `self.id` — "jarvis" — so LOCAL_ONLY_AGENTS was enforced on the agent that *answered*
    and never on the merge. A family agent's output could leave the box inside a synthesis
    prompt, which breaks the one rule the documentation calls non-negotiable.
    """
    local = RecordingBackend("local synthesis")
    routed = RecordingBackend("routed synthesis")

    class _RouterWithLocal(StaticRouter):
        active_model = "local-model"

        def __init__(self, cloudish, local_backend):
            super().__init__(cloudish, route="cloud")
            self._local = local_backend

        @property
        def local_backend(self):
            return self._local

    agent = Agent("jarvis", {"name": "Jarvis"}, _RouterWithLocal(routed, local))
    agent.soul = {"content": "test policy"}
    agent._gen_params = lambda route_name: (128, 0.0)

    result = await agent.synthesize(
        {"frigga": "family report", "stark": "engineering report"},
        intent=None,
    )

    assert result == "local synthesis"
    assert len(local.calls) == 1
    assert routed.calls == [], (
        "a strict-local contributor's raw text was merged through the routed "
        "(cloud-eligible) backend"
    )


@pytest.mark.asyncio
async def test_synthesis_falls_back_to_the_join_when_no_local_backend_exists():
    """Fail-closed: no strict-local backend must mean no model call at all.

    Falling through to select_backend here would recreate the hole exactly.
    """
    routed = RecordingBackend("routed synthesis")
    agent = Agent("jarvis", {"name": "Jarvis"}, StaticRouter(routed))   # no local_backend
    agent.soul = {"content": "test policy"}
    agent._gen_params = lambda route_name: (128, 0.0)

    result = await agent.synthesize(
        {"frigga": "family report", "ultron": "systems report"},
        intent=None,
    )

    assert routed.calls == []
    assert result == "[frigga]: family report | [ultron]: systems report"


@pytest.mark.asyncio
async def test_streaming_uses_selected_backend_not_policy_prototype():
    selected = RecordingBackend("selected stream")
    boot_backend = RecordingBackend("boot stream")
    router = StaticRouter(selected)
    agent = Agent("jarvis", {"name": "Jarvis"}, router)
    agent.soul = {"content": "test policy"}
    agent.build_prompt = lambda text, context: text
    security = GuardrailsEngine(backend=boot_backend)
    orchestrator = streamed_orchestrator_for(agent, router, security)
    emitted = []

    result = await orchestrator.handle_input_stream(
        "private stream",
        channel="web",
        on_token=emitted.append,
        session_id="stream-session",
    )

    assert result == "selected stream"
    assert emitted == ["selected stream"]
    assert len(selected.calls) == 1
    assert boot_backend.calls == []


@pytest.mark.asyncio
async def test_boot_without_backend_then_redetect_guards_first_request(
    monkeypatch,
    tmp_path,
):
    selected = RecordingBackend("contact alice@example.com")
    router = HybridRouter()
    router._deep_model_available = lambda: False
    detect_calls = 0

    async def detect():
        nonlocal detect_calls
        detect_calls += 1
        router._backend = selected if detect_calls > 1 else None
        router._local_available = detect_calls > 1
        router._backend_name = "test-local" if detect_calls > 1 else "none"
        router._cloud_available = False
        router._claude_available = False
        router._ollama_available = False

    router.detect = detect

    class StopAutonomySetup:
        def initialize(self):
            raise RuntimeError("stop after agent wiring")

    def fail_reviewer(*args, **kwargs):
        raise RuntimeError("reviewer not needed in route test")

    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator._session_id_default = "boot-session"
    orchestrator.llm_router = router
    orchestrator.security = None
    orchestrator.agents = {}
    orchestrator.permission_gate = None
    orchestrator.config = SimpleNamespace(
        agents={
            "frigga": SimpleNamespace(
                status="active",
                name="Frigga",
                model="local-model",
                has_heartbeat=False,
                channel="internal",
                plugins=[],
                tier="foundation",
            )
        }
    )
    orchestrator._configure_cognition_roster = lambda: None
    orchestrator.capabilities = None
    orchestrator.plugin_manager = SimpleNamespace(build=lambda owner: None)
    orchestrator.autonomy_queue = StopAutonomySetup()
    orchestrator.skills = SimpleNamespace(discover=lambda: None, skills={})
    orchestrator.checkpoints = SimpleNamespace(
        initialize=lambda: None,
        restore=lambda owner: False,
    )
    orchestrator.load_runtime_settings = lambda: None
    orchestrator.heartbeat_scheduler = SimpleNamespace(
        load_all=lambda: None,
        load_from_config=lambda config: None,
        _heartbeat_configs={},
    )

    monkeypatch.setattr(orchestrator_module, "env_flag", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        "agents.core.settings_db.get_value",
        lambda category, key, default=None: {
            "security.guardrails_mode": "REDACT",
            "security.scan_input": True,
            "security.scan_output": True,
        }.get(f"{category}.{key}", default),
    )
    monkeypatch.setattr(
        "agents.core.learning.background_review.BackgroundReviewer",
        fail_reviewer,
    )
    monkeypatch.setattr(
        "agents.core.paths.data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )

    await orchestrator.load_agents()

    assert orchestrator.security is not None
    assert orchestrator.security._backend is None
    agent = orchestrator.agents["frigga"]
    assert agent.guardrails is orchestrator.security

    await router.detect()
    agent.build_prompt = lambda text, context: text
    agent._gen_params = lambda route_name: (128, 0.0)
    reply = await agent.process("first private request", {"session_id": "first"})

    assert reply == "contact [REDACTED:email]"
    assert len(selected.calls) == 1


@pytest.mark.parametrize("agent_id", ["frigga", "ultron", "howard"])
@pytest.mark.asyncio
async def test_local_unavailable_paths_share_stable_reply_and_zero_cloud_calls(
    agent_id,
):
    local = RecordingBackend("local answer")
    gemini = RecordingBackend("gemini answer")
    claude = RecordingBackend("claude answer")
    agent = build_agent(agent_id, local=local, gemini=gemini, claude=claude)
    router = agent.llm_router
    router._local_available = False
    router._backend = None
    router._ollama_available = False
    agent.guardrails = GuardrailsEngine(backend=claude)

    process_reply = await agent.process("private request", {"session_id": "normal"})
    emitted = []
    orchestrator = streamed_orchestrator_for(agent, router, agent.guardrails)
    stream_reply = await orchestrator.handle_input_stream(
        "private stream",
        channel="web",
        on_token=emitted.append,
        session_id="stream",
    )

    assert process_reply == EXPECTED_LOCAL_UNAVAILABLE_REPLY
    assert stream_reply == EXPECTED_LOCAL_UNAVAILABLE_REPLY
    assert emitted == [EXPECTED_LOCAL_UNAVAILABLE_REPLY]
    assert local.calls == []
    assert gemini.calls == []
    assert claude.calls == []


@pytest.mark.asyncio
async def test_unavailable_synthesis_returns_constituent_reports():
    class UnavailableRouter:
        model_manager = None

        def select_backend(self, agent_id: str, prompt: str):
            raise LocalBackendUnavailableError("strict-local backend unavailable")

    agent = Agent("jarvis", {"name": "Jarvis"}, UnavailableRouter())
    result = await agent.synthesize(
        {"frigga": "family report", "ultron": "systems report"},
        intent=None,
    )

    assert result == "[frigga]: family report | [ultron]: systems report"


@pytest.mark.parametrize("agent_id", ["frigga", "ultron", "howard"])
@pytest.mark.asyncio
async def test_local_only_synthesis_uses_local_and_never_calls_cloud(agent_id):
    local = RecordingBackend("local synthesis")
    gemini = RecordingBackend("gemini synthesis")
    claude = RecordingBackend("claude synthesis")
    agent = build_agent(agent_id, local=local, gemini=gemini, claude=claude)
    agent.guardrails = GuardrailsEngine(backend=claude)

    result = await agent.synthesize(
        {"frigga": "family report", "ultron": "systems report"},
        intent=None,
    )

    assert result == "local synthesis"
    assert len(local.calls) == 1
    assert gemini.calls == []
    assert claude.calls == []


@pytest.mark.parametrize("agent_id", ["frigga", "ultron", "howard"])
@pytest.mark.asyncio
async def test_local_only_unavailable_synthesis_returns_reports_without_cloud(
    agent_id,
):
    local = RecordingBackend("local synthesis")
    gemini = RecordingBackend("gemini synthesis")
    claude = RecordingBackend("claude synthesis")
    agent = build_agent(agent_id, local=local, gemini=gemini, claude=claude)
    agent.llm_router._local_available = False
    agent.llm_router._backend = None
    agent.llm_router._ollama_available = False
    agent.guardrails = GuardrailsEngine(backend=claude)

    result = await agent.synthesize(
        {"frigga": "family report", "ultron": "systems report"},
        intent=None,
    )

    assert local.calls == []
    assert gemini.calls == []
    assert claude.calls == []
    assert result == "[frigga]: family report | [ultron]: systems report"
