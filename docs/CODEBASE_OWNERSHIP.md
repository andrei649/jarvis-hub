# Codebase ownership map

This map answers **which source area and governing document to open first**. It assigns review responsibility by subsystem, not exclusive file ownership or permission to merge. A change crossing rows needs the corresponding guides and tests from each row. [NERVA.md](../NERVA.md) is the short architecture overview; [ARCHITECTURE.md](ARCHITECTURE.md) has entry points, request/data flows, module symbols and recipes. [AGENTS.md](../AGENTS.md) controls the current workflow.

| Subsystem / entry | Start in these source directories | Read before changing |
|---|---|---|
| Hub entry, HTTP and route guards | `serve.py`, `agents/web.py`, `agents/core/routers/` | [Architecture: request flow and routes](ARCHITECTURE.md#2-request-lifecycle), [AGENTS: verification and parity](../AGENTS.md#verification-and-parity), [security](../SECURITY.md) |
| CLI entry and command clients | `agents/run.py`, `agents/cli/` | [Architecture: entry points and recipes](ARCHITECTURE.md#1-tldr--orientation), [compatibility](COMPATIBILITY.md), [security](../SECURITY.md) |
| Agent registry and turn orchestration | `agents/_system/`, `agents/core/orchestrator.py`, `agents/core/agent.py`, `agents/core/llm/` | [Architecture: orchestration and model routing](ARCHITECTURE.md#3-module-index), [AI context loading](AI_CONTEXT.md) |
| Authorization, Action Kernel and audit | `agents/core/security/`, `agents/core/kernel/`, `agents/core/routers/security.py` | [Threat model](THREAT_MODEL.md), [security policy](../SECURITY.md), [Architecture: Action Kernel](ARCHITECTURE.md#action-kernel--budgets) |
| Memory, sessions and local persistence | `agents/core/memory/`, `agents/core/session_*`, `agents/core/persistence/` | [Architecture: memory flow](ARCHITECTURE.md#4-memory--recall-subsystem), [privacy](PRIVACY.md), [compatibility and migration](COMPATIBILITY.md) |
| Local/cloud model adapters and egress | `agents/core/llm/`, `agents/core/routers/` | [Architecture: model routing](ARCHITECTURE.md#5-llm-routing--model-tiering), [privacy](PRIVACY.md), [security](../SECURITY.md) |
| Channel ingress and owner replies | `agents/core/channels/`, `agents/core/routers/` | [Architecture: channels](ARCHITECTURE.md#channels), [threat model](THREAT_MODEL.md) |
| Skills, plugins and capability discovery | `agents/core/skills/`, `agents/core/plugins/`, `skills/`, `optional-skills/`, `agents/core/routers/skills.py` | [Architecture: skills and plugins](ARCHITECTURE.md#skills), [Hermes absorption](HERMES_ABSORPTION.md), [security](../SECURITY.md) |
| Jobs, autonomy and governed workflows | `agents/core/autonomy/`, `agents/core/routers/jobs.py`, `agents/core/routers/workflows.py` | [Automation operations](automations-operations.md), [automation scripts](automations-scripts.md), [Architecture: autonomy](ARCHITECTURE.md#autonomy--proactive) |
| House, media and physical effects | `agents/core/house/`, `agents/core/media_*.py`, `agents/core/media_backends/`, `agents/core/routers/house.py`, `agents/core/routers/media_director.py` | [Architecture: subsystem index](ARCHITECTURE.md#3-module-index), [threat model](THREAT_MODEL.md), [security](../SECURITY.md) |
| Voice and ingestion | `agents/core/voice/`, `agents/core/ingestion/`, `agents/core/routers/voice.py` | [Architecture: voice and ingestion](ARCHITECTURE.md#3-module-index), [privacy](PRIVACY.md) |
| HUD source and shipped bundle | `frontend/src/`, `frontend/scripts/`, `agents/web/v2/` | [HUD remaining/parity](design/HUD_V2_REMAINING.md), [Architecture: HTTP surface](ARCHITECTURE.md#3-module-index), [contributing](../CONTRIBUTING.md) |
| Mobile client | `mobile/src/`, `mobile/App.tsx`, `mobile/scripts/` | [Mobile parity](../mobile/PARITY.md), [mobile guide](../mobile/README.md), [compatibility](COMPATIBILITY.md) |
| Desktop shell | `desktop/src-tauri/` | [Desktop host guide](../desktop/README.md), [compatibility](COMPATIBILITY.md) |
| Packaging, install and deployment | `scripts/bootstrap.py`, `scripts/build_*.py`, `packaging/`, `deploy/`, `install.sh`, `INSTALL.bat` | [User guide](USER_GUIDE.md), [compatibility](COMPATIBILITY.md), [security](../SECURITY.md) |
| Tests, generated API/route metadata and Hermes accounting | `tests/`, `scripts/status_sync.py`, `scripts/hermes_*.py`, `docs/hermes/` | [Architecture: testing](ARCHITECTURE.md#testing), [Hermes objective](hermes/autonomous-development-objective.md), [contributing](../CONTRIBUTING.md) |

The map is a starting point. Verify actual imports, callers, route mounts, storage and UI clients before claiming a subsystem is covered. A route, schema, approval or action often crosses multiple rows. Use `rg` or the relevant graph for a bounded trace; the Markdown map is not an executable dependency graph.
