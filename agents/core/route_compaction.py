"""Request-owned specialist dispatch contracts for shared history compaction."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace

from .conversation_clock import CompactionClockRefused
from .llm.effective_window import EffectiveWindow, resolve_effective_window


class RouteRefused(CompactionClockRefused):
    def __init__(self):
        super().__init__("Specialist context route could not be safely prepared")


@dataclass
class _Lifetime:
    session: str
    active: bool = True
    parent: object = None

    def check(self):
        if not self.active:
            raise RouteRefused()
        if self.parent is not None:
            self.parent.check()


_lifetime = ContextVar("route_compaction_lifetime", default=None)


@contextmanager
def planning_scope(session, *, enabled=True):
    parent = _lifetime.get()
    if parent is not None:
        parent.check()
    if not enabled and parent is None:
        yield
        return
    life = _Lifetime(session, parent=parent)
    token = _lifetime.set(life)
    try:
        yield
    finally:
        life.active = False
        _lifetime.reset(token)


def _identity(backend):
    from .llm.job_selection import current_selection

    selection = current_selection()
    if selection is not None and selection.lifetime.resolved is not None:
        return selection.lifetime.resolved[0]
    return backend


@dataclass(frozen=True)
class PreparedRoute:
    backend: object
    identity: object
    model: str
    route: str
    prompt: str
    agent_id: str
    lifetime: _Lifetime
    window: EffectiveWindow
    estimated_window: bool
    capacity: int
    max_tokens: int
    temperature: float
    output_reserve: int | None
    tool_output_reserve: int = 0
    input_text: str | None = None

    @property
    def input_budget(self):
        return self.capacity - max(self.output_reserve or 0, self.tool_output_reserve)

    def check(self, router, agent_id, prompt, session):
        from .llm.request_context import ensure_reasoning_active

        ensure_reasoning_active()
        self.lifetime.check()
        if (
            _lifetime.get() is not self.lifetime
            or session != self.lifetime.session
            or agent_id != self.agent_id
            or prompt != self.prompt
        ):
            raise RouteRefused()
        selected = router.select_backend(agent_id, prompt)
        if (
            not isinstance(selected, tuple)
            or len(selected) != 3
            or _identity(selected[0]) is not self.identity
            or selected[1:] != (self.model, self.route)
        ):
            raise RouteRefused()
        current = resolve_effective_window(selected[0], self.model)
        if (
            not current.valid
            or (current.tokens is None and not self.estimated_window)
            or (current.tokens is not None and current.tokens < self.capacity)
        ):
            raise RouteRefused()


async def prepare_route(router, agent_id, prompt, max_tokens, temperature, session):
    from .context_compressor import window_for
    from .llm.base import OllamaBackend, cloud_cap
    from .llm.job_selection import selected_window
    from .llm.request_context import ensure_reasoning_active

    ensure_reasoning_active()
    life = _lifetime.get()
    if life is None:
        raise RouteRefused()
    life.check()
    if life.session != session:
        raise RouteRefused()
    selected = router.select_backend(agent_id, prompt)
    if not isinstance(selected, tuple) or len(selected) != 3:
        raise RouteRefused()
    backend, model, route = selected
    if not isinstance(model, str) or not model or not isinstance(route, str):
        raise RouteRefused()
    if callable(max_tokens):
        max_tokens, temperature = max_tokens(route)
    if type(max_tokens) is not int:
        raise RouteRefused()
    pinned = selected_window(model)
    window = resolve_effective_window(backend, model)
    if not window.valid:
        raise RouteRefused()
    if pinned is None and isinstance(backend, OllamaBackend):
        ceiling = await backend.resolve_context_window(model)
        if ceiling is not None:
            if type(ceiling) is not int or ceiling <= 0:
                raise RouteRefused()
            window = EffectiveWindow(min(window.tokens, ceiling) if window.tokens else ceiling)
    estimated = window.tokens is None
    capacity = window.tokens or window_for(model)
    if pinned is not None:
        max_tokens = min(max_tokens, pinned // 4) if max_tokens > 0 else pinned // 4
    reserve = (
        (max_tokens if max_tokens > 0 else None)
        if route.startswith(("local", "ollama"))
        else cloud_cap(max_tokens)
    )
    from .llm.responses import ResponsesBackend

    if isinstance(_identity(backend), ResponsesBackend):
        reserve = min(cloud_cap(max_tokens), 32768)
    if capacity - (reserve or 0) <= 0:
        raise RouteRefused()
    life.check()
    return PreparedRoute(
        backend,
        _identity(backend),
        model,
        route,
        prompt,
        agent_id,
        life,
        window,
        estimated,
        capacity,
        max_tokens,
        temperature,
        reserve,
    )


@dataclass
class HistoryStage:
    text: str
    accept: object
    accepted: bool = False

    def publish(self):
        if self.accepted:
            raise RouteRefused()
        self.accept()
        self.accepted = True


@dataclass(frozen=True)
class SharedPlan:
    history: str
    routes: dict
    prompts: dict
    anchor_rows: tuple = ()
    instance: str = ""


async def plan_shared(history, router, build, stage, parameters, session):
    """Monotonic bounded planning; no summary/clock publishes on instability."""
    from .llm.tokenizer import estimate_tokens

    async def routes_for(value):
        prompts = await build(value)
        routes = {}
        budget = None
        for aid, value in prompts.items():
            prompt, overhead = value[:2]
            route = await prepare_route(
                router, aid, prompt, lambda selected, aid=aid: parameters(aid, selected), 0, session
            )
            if (
                len(value) > 3
                and value[3]
                and route.output_reserve is None
                and route.window.tokens is not None
                and getattr(route.backend, "supports_tools", False)
            ):
                # Existing optional tool runtime uses this cap for known windows.
                # Keep the direct backend local-auto parameter unchanged.
                route = replace(route, tool_output_reserve=max(1, route.window.tokens // 4))
            # Reserve headroom for fixed system/schema/current-prompt material
            # before spending the shared history allowance.
            available = int(0.85 * route.input_budget) - overhead
            if available <= 0:
                raise RouteRefused()
            budget = min(budget, available) if budget is not None else available
            routes[aid] = replace(route, input_text=value[2]) if len(value) > 2 else route
        if budget is None:
            raise RouteRefused()
        return routes, prompts, budget

    floor = None
    for _ in range(3):
        candidates, _, candidate = await routes_for(history)
        floor = min(floor, candidate) if floor is not None else candidate
        staged = await stage(floor, candidates)
        routes, prompts, needed = await routes_for(staged.text)
        if needed < floor:
            floor = needed
            history = staged.text
            continue
        if estimate_tokens(staged.text) > floor:
            raise RouteRefused()
        for aid, route in routes.items():
            route.check(router, aid, route.prompt, session)
        staged.publish()
        return SharedPlan(staged.text, routes, prompts)
    raise RouteRefused()


@dataclass(frozen=True)
class _RouteAnchor:
    owner: object
    model: str
    instance: str
    prefix: str
    count: int
    tokens: int


def _prefix(rows):
    import hashlib
    import json

    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def remember_usage(store, session, agent_id, route, rows, instance, usage):
    if not isinstance(instance, str) or not instance:
        return
    counts = [getattr(usage, key, 0) for key in ("input_tokens", "cache_read", "cache_write")]
    if any(type(value) is not int or value < 0 for value in counts) or not sum(counts):
        return
    key = (session, agent_id)
    store[key] = _RouteAnchor(
        route.identity, route.model, instance, _prefix(rows), len(rows), sum(counts)
    )
    store.move_to_end(key)
    while len(store) > 256:
        store.popitem(last=False)


def trusted_anchor(store, session, routes, rows, instance):
    from .context_compressor import UsageAnchor

    if not isinstance(instance, str) or not instance:
        return None
    best = None
    for aid, route in routes.items():
        anchor = store.get((session, aid))
        if (
            anchor is None
            or anchor.owner is not route.identity
            or anchor.model != route.model
            or anchor.instance != instance
            or anchor.count > len(rows)
            or anchor.prefix != _prefix(rows[: anchor.count])
        ):
            continue
        if best is None or anchor.tokens > best.prompt_tokens:
            best = UsageAnchor(anchor.tokens, anchor.count)
    return best
