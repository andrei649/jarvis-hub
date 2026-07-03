---
name: jarvis-add-plugin
description: Use when adding a new third-party integration / plugin to the jarvis hub (agents/core/plugins/*), or wiring an external API an agent can call. Triggers on "add a plugin", "integrate <service>", "new integration", or "let an agent call <API>".
---

# Adding a plugin

1. **Create** `agents/core/plugins/<myplugin>.py` with a class `MyPlugin`. Keep the live HTTP/SDK client injectable (the network client is the host seam) so logic stays offline-testable — mirror an existing plugin (e.g. `weather.py`, `n8n.py`).
2. **Instantiate** in `Orchestrator.load_agents()` (`orchestrator.py`):
   ```python
   self.plugins["myplugin"] = MyPlugin(key=os.environ.get("MYPLUGIN_KEY", ""))
   ```
3. **Trigger** it in `agents/core/plugin_gatherer.py:_eligible_plugins` — add a keyword/permission branch that appends a `(result_key, lambda: plugin.call(...))` spec. The fan-out runs eligible plugins concurrently; never `await` inline there.
4. **Permission:** gate access with `any_agent_can(orch, "myplugin", intent)`; log `E_PLUGIN_BLOCKED` when denied.
5. **Toggle (optional):** add `plugins.<name>` to `settings_db.py:DEFAULTS`. Per-plugin secrets go under category `"plugins"`; prefer resolving them via `secrets_vault.py`, not raw `.env`.
6. **Test:** `tests/test_<plugin>.py` with a fake client — no real network.

## Common mistakes
- `await plugin.x()` inline in the gatherer → reintroduces serial fan-out; append a spec instead.
- Hardcoding a secret instead of env/vault resolution.
