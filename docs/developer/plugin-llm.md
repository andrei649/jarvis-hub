# The plugin LLM facade

How a built-in plugin (the ones under `agents/core/plugins/`, built by
`agents/core/plugin_manager.py::PluginManager`) makes its own model call. This is the
Hermes `ctx.llm` lane, narrowed on purpose:

- **Only in-tree plugins.** Third-party extensions get no host object at all (the
  sandbox contract in `agents/core/extensions/runtime.py`), so there is no facade for
  them and none is planned.
- **Strict-local.** Every call goes through `agents/core/llm/auxiliary_text.py::run_oneshot`,
  the auxiliary rail: the router's fail-closed local backend, the auxiliary
  data-handling consent boundary, job model pins excluded, bounded budgets. The
  plugin's own `network_access` or `data_scope` never widens it; there is no cloud
  route here.
- **Stateless.** Nothing is read from or written to a session; history reaches the
  model only if the plugin puts it in the prompt.

## Declare it

The manifest opts in. `llm_access` defaults to `False`, and no shipped plugin sets it
yet (`agents/core/plugin_gate.py::PluginManifest`):

```python
PluginManifest(
    id="digest", name="Digest", version="0.1.0", description="Summarises feeds",
    network_access=NetworkAccess.NONE, data_scope=DataScope.LOCAL_ONLY,
    agents_served=["all"], llm_access=True,
)
```

## Ask for the facade

The plugin never imports the rail. `PluginManager.build` calls `attach_llm(llm)` on
each built plugin that defines it, with a facade bound to that plugin's gate id:

```python
class DigestPlugin:
    def attach_llm(self, llm):
        self.llm = llm

    async def digest(self, text: str) -> str:
        return await self.llm.complete(text, system="Summarise in two lines.", max_tokens=120)

    async def digest_live(self, text: str, on_piece) -> str:
        return await self.llm.stream(text, on_token=on_piece, max_tokens=120)
```

`agents/core/plugin_manager.py::PluginLLM.complete` returns the answer;
`agents/core/plugin_manager.py::PluginLLM.stream` also hands each piece to `on_token`.
Calls are labelled `plugin:<id>` in `agents/core/llm/auxiliary_text.py::oneshot_usage`.

## What refuses

The gate is asked at **every call**, not at attach time. A call raises
`agents/core/plugin_manager.py::PluginLLMRefused` when the plugin is unknown, switched
off (the load set, a toggle, safe mode), or its manifest does not declare
`llm_access`. A missing local model raises the rail's own `RuntimeError`, an
out-of-bounds budget `AuxiliaryConfigError`, and a backend that answers with its fixed
failure text `AuxiliaryBackendFailure`.

## Stream callbacks

The callback is not awaited inside the token loop. It runs on its own worker behind a
bounded queue (`agents/core/plugin_manager.py::_StreamObserver`, 64 pieces): a slow or
stalled callback cannot slow generation, and when it falls behind the oldest queued
pieces are dropped and counted in `PluginLLM.dropped_tokens`. A callback that raises
is logged and skipped. The value returned by `stream()` is always the whole answer.

This is a per-call callback on the plugin's own model call. It is **not** an observer
hook on the main chat stream (`on_stream_start` / `on_stream_delta` / `on_stream_end`
for the owner's conversation); Nerva has no such hook.
