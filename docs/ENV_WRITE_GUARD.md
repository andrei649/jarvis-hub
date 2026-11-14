# Shared Environment Persistence & Execution Denylist (`H499`)

Nerva enforces a single shared environment-variable denylist (`agents/core/security/env_write_guard.py`) across both:

1. **Child / Code Interpreter Execution** (`agents/core/code_env.py` — `H595`)
2. **Persistent `.env` Write Boundaries** (`agents/cli/env_cmd.py` — `nerva env set|unset|check|denylist`)

## Denylist Categories

| Category | Constants | Examples | Why Refused at Persistence Boundary |
|---|---|---|---|
| `control_or_loader` | `SHARED_CONTROL_ENV_NAMES`, `SHARED_CONTROL_ENV_PREFIXES` | `LD_PRELOAD`, `DYLD_INSERT_LIBRARIES`, `PYTHONPATH`, `PYTHONSTARTUP`, `NODE_OPTIONS`, `BASH_ENV`, `ENV`, `PATH`, `SSL_CERT_FILE`, `GIT_CONFIG_*`, `JARVIS_TOOL_RPC_*` | Prevents code injection into Python/Node/shell startup, dynamic linker hijacking, TLS trust replacement, and internal RPC spoofing. |
| `security_policy` | `SECURITY_POLICY_ENV_NAMES` | `JARVIS_ACTION_KERNEL`, `JARVIS_SAFE_MODE`, `JARVIS_STRICT_LOCAL`, `JARVIS_ALLOW_INSECURE_BIND`, `JARVIS_TERMINAL_LOCAL_HOST`, `JARVIS_SMART_APPROVALS`, `JARVIS_ADMIN_TOKEN`, `JARVIS_SECRET_KEY`, `DEV_MODE` (plus `NERVA_*` spellings) | Prevents automated or CLI `.env` helpers from disabling approval floors, weakening strict-local routing, exposing network binds, or rotating hub auth/signing keys. |
| `process_only_location` | `env_provenance.FROM_PROCESS_ONLY` | `JARVIS_HOME`, `JARVIS_APP_ROOT`, `JARVIS_MEMORY_DIR`, `JARVIS_PROFILE`, `JARVIS_MANAGED_DIR` | Root-locating variables must come from the process environment prior to startup so stores never split across roots. |
| `administrator_managed` | `managed_scope.env_names()` | Administrator-pinned keys | Preserves enterprise/administrator managed overrides. |

## CLI Usage

```bash
nerva env list
nerva env check LD_PRELOAD
nerva env set TAVILY_API_KEY tvly-...
nerva env unset TAVILY_API_KEY
nerva env denylist --json
```

Any attempt to persist a denylisted variable raises `EnvWriteRefusedError` naming the blocked variable and leaves the target `.env` file untouched on disk.
