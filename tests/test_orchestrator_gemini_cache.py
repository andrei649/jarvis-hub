"""Request-scoped Gemini cache integration regressions."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from types import SimpleNamespace

import pytest

from agents.core.llm.gemini import GeminiBackend
from agents.core.llm.gemini_context import GeminiRequestBinding
from agents.core.orchestrator import Orchestrator
from agents.core.security.guardrails import GuardrailsEngine, SecurityBlockError
from agents.core.security.types import RedactionMode

EMAIL = "alice@example.com"


class _RecordingGemini(GeminiBackend):
    """A real Gemini type with request-scope behavior but no network client."""

    def __init__(self) -> None:
        self.api_key = "test-gemini-key"
        self.model = "gemini-test"
        self.auth_pool = None
        self._request_binding = ContextVar(
            f"test_gemini_request_binding_{id(self)}",
            default=None,
        )
        self.calls: list[dict] = []
        self.lease_calls = 0

    def acquire_lease(self):
        self.lease_calls += 1
        return super().acquire_lease()

    async def generate(self, **kwargs) -> str:
        self.calls.append({**kwargs, "binding": self.current_binding()})
        return "gemini answer"


class _FakeCache:
    def __init__(self, binding_factory=None) -> None:
        self.binding_factory = binding_factory
        self.acquire_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.closed = False

    async def acquire_binding(self, **kwargs):
        self.acquire_calls.append(kwargs)
        if self.binding_factory is None:
            return None
        return self.binding_factory(kwargs)

    async def create_or_extend(self, **kwargs):
        self.create_calls.append(kwargs)
        return "cachedContents/new"

    async def close(self) -> None:
        self.closed = True


class _PolicyCache(_FakeCache):
    def __init__(self) -> None:
        super().__init__()
        self.entry_policy: str | None = None
        self.prefix_count = 0

    async def acquire_binding(self, **kwargs):
        self.acquire_calls.append(kwargs)
        if self.entry_policy != kwargs["policy_fingerprint"]:
            return None
        return GeminiRequestBinding(
            lease=kwargs["lease"],
            session_id=kwargs["session_id"],
            cache_name="cachedContents/warn",
            cached_prefix_count=self.prefix_count,
        )

    async def create_or_extend(self, **kwargs):
        self.create_calls.append(kwargs)
        self.entry_policy = kwargs["policy_fingerprint"]
        self.prefix_count = len(kwargs["history"])
        return "cachedContents/warn"


class _Memory:
    def __init__(self, history: tuple[str, ...]) -> None:
        self.history = history
        self.turns: list[tuple[str, str, str]] = []
        self.current_user: str | None = None

    async def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_id=None,
        channel=None,
    ) -> None:
        self.turns.append((session_id, role, content))
        if role == "user":
            self.current_user = content


class _Agent:
    name = "Jarvis"
    soul = {"content": "system policy"}
    config = {"model": "gemini-test"}

    async def generate_response(self, **kwargs) -> str:
        return await kwargs["backend"].generate(
            model=kwargs["model"],
            prompt=kwargs["prompt"],
            system=kwargs["system"],
            max_tokens=kwargs["max_tokens"],
            temperature=kwargs["temperature"],
        )


class _Router:
    def __init__(self, backend: GeminiBackend) -> None:
        self.backend = backend
        self.routing_prompts: list[str] = []
        self._gemini_pool = None

    def select_backend(self, agent_id: str, prompt: str):
        self.routing_prompts.append(prompt)
        return self.backend, "gemini-test", "cloud"


def _orchestrator(
    history: tuple[str, ...],
    *,
    cache: _FakeCache,
    mode: RedactionMode = RedactionMode.WARN,
) -> tuple[Orchestrator, _RecordingGemini, _Memory, _Router]:
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator._session_id_default = None
    orchestrator._cache_tasks = set()
    memory = _Memory(history)
    backend = _RecordingGemini()
    router = _Router(backend)

    class _Intent:
        target_agents = ["jarvis"]
        is_general = True
        confidence = 1.0
        context = {}

    async def classify(text, agents):
        return _Intent()

    async def no_mapping(*args, **kwargs):
        return {}

    async def no_text(*args, **kwargs):
        return ""

    async def history_text(last_n: int) -> str:
        entries = memory.history
        if memory.current_user is not None:
            entries = (*entries, f"[user]: {memory.current_user}")
        return "\n".join(entries)

    async def build_turn(
        agent_id,
        text,
        *,
        history="",
        plugin_block="",
        recall_block="",
        runtime_block="",
    ) -> str:
        return "\n".join(part for part in (history, text) if part)

    async def complete_turn(**kwargs) -> None:
        return None

    orchestrator.memory = memory
    orchestrator.skills = SimpleNamespace(parse_command=lambda text: None)
    orchestrator._chat_control_enabled = lambda: False
    orchestrator.router = SimpleNamespace(classify=classify)
    orchestrator._gather_plugin_data = no_mapping
    orchestrator._format_plugin_data = lambda data: ""
    orchestrator._history_for_prompt = history_text
    orchestrator._recall_block = no_text
    orchestrator._runtime_state_block = lambda: ""
    orchestrator._build_agent_turn_text = build_turn
    orchestrator._route_candidates = lambda intent: intent.target_agents
    orchestrator.agents = {"jarvis": _Agent()}
    orchestrator.llm_router = router
    orchestrator.checkpoints = SimpleNamespace(load=lambda agent_id, session_id: None)
    orchestrator.security = GuardrailsEngine(backend=None, mode=mode)
    orchestrator.context_cache = cache
    orchestrator.get_setting = lambda key, default=None: default
    orchestrator._agent_gen_params = lambda agent, route_name: (128, 0.0)
    orchestrator._complete_llm_turn = complete_turn
    return orchestrator, backend, memory, router


async def _drain_cache_tasks(orchestrator: Orchestrator) -> None:
    tasks = tuple(orchestrator._cache_tasks)
    if tasks:
        await asyncio.gather(*tasks)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_cache_hit_sends_tail_exactly_once():
    history = (
        "[user]: prior alpha",
        "[jarvis]: prior beta",
        "[user]: uncached gamma",
    )

    def hit(kwargs):
        return GeminiRequestBinding(
            lease=kwargs["lease"],
            session_id=kwargs["session_id"],
            cache_name="cachedContents/hit",
            cached_prefix_count=2,
        )

    cache = _FakeCache(hit)
    orchestrator, backend, _memory, router = _orchestrator(history, cache=cache)

    await orchestrator._handle_input_stream(
        "current question",
        channel="web",
        session_id="cache-hit",
    )

    assert all(part in router.routing_prompts[0] for part in (*history, "current question"))
    provider_prompt = backend.calls[0]["prompt"]
    assert "prior alpha" not in provider_prompt
    assert "prior beta" not in provider_prompt
    assert provider_prompt.count("uncached gamma") == 1
    assert provider_prompt.count("current question") == 1
    assert backend.calls[0]["binding"].cache_name == "cachedContents/hit"
    assert backend.lease_calls == 1
    assert cache.create_calls == []


@pytest.mark.asyncio
async def test_changed_or_truncated_prefix_sends_full_history():
    history = (
        "[user]: changed alpha",
        "[jarvis]: prior beta",
        "[user]: tail gamma",
    )
    cache = _FakeCache()
    orchestrator, backend, _memory, _router = _orchestrator(history, cache=cache)

    await orchestrator._handle_input_stream(
        "current question",
        channel="web",
        session_id="changed-prefix",
    )
    await _drain_cache_tasks(orchestrator)

    provider_prompt = backend.calls[0]["prompt"]
    for part in (*history, "current question"):
        assert provider_prompt.count(part) == 1
    assert backend.calls[0]["binding"].cache_name is None


@pytest.mark.asyncio
async def test_cache_miss_keeps_full_history_and_schedules_creation():
    history = ("[user]: prior alpha", "[jarvis]: prior beta")
    cache = _FakeCache()
    orchestrator, backend, _memory, _router = _orchestrator(history, cache=cache)

    await orchestrator._handle_input_stream(
        "current question",
        channel="web",
        session_id="cache-miss",
    )
    await _drain_cache_tasks(orchestrator)

    provider_prompt = backend.calls[0]["prompt"]
    for part in (*history, "current question"):
        assert provider_prompt.count(part) == 1
    assert len(cache.create_calls) == 1
    assert cache.create_calls[0]["history"] == history
    assert cache.create_calls[0]["lease"] == cache.acquire_calls[0]["lease"]
    assert backend.lease_calls == 1


@pytest.mark.asyncio
async def test_block_mode_performs_zero_cache_network_calls():
    cache = _FakeCache()
    orchestrator, backend, _memory, _router = _orchestrator(
        (f"[user]: private contact {EMAIL}",),
        cache=cache,
        mode=RedactionMode.BLOCK,
    )

    with pytest.raises(SecurityBlockError):
        await orchestrator._handle_input_stream(
            "current question",
            channel="web",
            session_id="cache-block",
        )

    assert cache.acquire_calls == []
    assert cache.create_calls == []
    assert backend.calls == []


@pytest.mark.asyncio
async def test_redact_mode_uploads_copy_without_mutating_history():
    history = (
        f"[user]: private contact {EMAIL}",
        "[jarvis]: safe prior turn",
    )
    cache = _FakeCache()
    orchestrator, backend, memory, _router = _orchestrator(
        history,
        cache=cache,
        mode=RedactionMode.REDACT,
    )

    await orchestrator._handle_input_stream(
        "current question",
        channel="web",
        session_id="cache-redact",
    )
    await _drain_cache_tasks(orchestrator)

    assert memory.history == history
    assert EMAIL in memory.history[0]
    assert EMAIL not in cache.acquire_calls[0]["history"][0]
    assert EMAIL not in cache.create_calls[0]["history"][0]
    assert EMAIL not in backend.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_warn_cache_is_not_reused_after_enforcing_restart():
    history = ("[user]: prior alpha", "[jarvis]: prior beta")
    cache = _PolicyCache()
    warn, warn_backend, _memory, _router = _orchestrator(
        history,
        cache=cache,
        mode=RedactionMode.WARN,
    )
    await warn._handle_input_stream(
        "first current",
        channel="web",
        session_id="policy-restart",
    )
    await _drain_cache_tasks(warn)
    warn_policy = cache.entry_policy

    enforcing, enforcing_backend, _memory, _router = _orchestrator(
        history,
        cache=cache,
        mode=RedactionMode.REDACT,
    )
    await enforcing._handle_input_stream(
        "second current",
        channel="web",
        session_id="policy-restart",
    )
    await _drain_cache_tasks(enforcing)

    assert warn_backend.calls[0]["binding"].cache_name is None
    assert enforcing_backend.calls[0]["binding"].cache_name is None
    assert cache.acquire_calls[-1]["policy_fingerprint"] != warn_policy
    enforcing_prompt = enforcing_backend.calls[0]["prompt"]
    for part in (*history, "second current"):
        assert enforcing_prompt.count(part) == 1


@pytest.mark.asyncio
async def test_shutdown_drains_cache_tasks_before_client_close():
    order: list[str] = []
    started = asyncio.Event()

    async def cache_work() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            order.append("task-drained")

    task = asyncio.create_task(cache_work(), name="gemini-cache:shutdown-test")
    await started.wait()

    class _Cache:
        async def close(self) -> None:
            assert task.done()
            order.append("cache-closed")

    class _RouterClose:
        async def aclose(self) -> None:
            order.append("router-closed")

    class _MCP:
        async def close_all(self) -> None:
            return None

    async def flush_checkpoint() -> None:
        return None

    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator._cache_tasks = {task}
    orchestrator._flush_checkpoint = flush_checkpoint
    orchestrator.context_cache = _Cache()
    orchestrator.llm_router = _RouterClose()
    orchestrator.mcp = _MCP()
    orchestrator.autonomy_queue = SimpleNamespace(close=lambda: None)
    orchestrator.channel_manager = SimpleNamespace(channels={})

    await orchestrator.aclose()

    assert order.index("task-drained") < order.index("cache-closed")
    assert orchestrator._cache_tasks == set()
