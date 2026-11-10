# The Adopt lane: running Hermes code inside Nerva

The Adopt lane (`feature-integration-plan-2026-11-10.md`) runs selected Hermes Agent source
files (MIT, NousResearch/hermes-agent) as they are, instead of re-writing them. Two rules hold:

1. **A vendored file stays upstream text.** The only change is a mechanical, recorded rewrite
   of its imports. A fix goes upstream, or the file is not adopted.
2. **Every effect still crosses Nerva's controls.** The rewritten imports point at the compat
   layer, and the compat layer maps each Hermes interface onto a Nerva control. Vendored code
   reaches no network client, no secret and no registry of its own.

## Layout

| Path | What it is |
|---|---|
| `agents/vendor/hermes/` | Vendored files at their upstream paths (`plugins/web/exa/provider.py` …), plus `LICENSE`, `NOTICE.md` (pinned commit) and `MANIFEST.json`. |
| `agents/vendor/hermes/MANIFEST.json` | Pinned commit, the rewrite rules, and per file: upstream sha256, vendored sha256, the rules applied. |
| `agents/vendor/hermes_compat/` | The shims vendored code imports. Nerva code, reviewed like any other. |
| `scripts/hermes_vendor.py` | `status`, `diff`, `pull`. |
| `tests/test_hermes_adopt_lane.py` | Behaviour, egress, structure and sync-script tests. |

The first slice (pinned `9c0560f8`) adopts three search providers: **Exa**, **Brave Search
(free tier)** and **Parallel**, with `plugins/web/_common.py`. Tavily, SearXNG and DuckDuckGo
are not adopted because Nerva has its own.

## The compat layer

| Hermes import | Compat module | Nerva control |
|---|---|---|
| `httpx` | `hermes_compat.httpx` | Owns no client. Each request goes to the `PluginHTTPClient` the adapter bound for the call, so the manifest allowlist, SSRF resolution with IP pinning, the breaker, the egress ledger and the kernel's `plugin.egress` hook apply. With nothing bound it refuses. The first refusal is recorded and repeated for the rest of the call, so a vendored `except Exception` cannot turn it into a retry or a rescue. Each wait is polled, so a worker stops when its caller leaves or the call's deadline passes. A request carrying a credential header is never sent with `follow_redirects`. |
| `exa_py`, `parallel` (SDKs) | `hermes_compat.sdk` | The real SDKs build their own HTTP clients, so they are never imported. Stand-ins implement the one call each provider makes (`Exa.search`, `Parallel.beta.search`) over the documented REST endpoint, through the compat `httpx`. |
| `agent.web_search_provider` | `hermes_compat.web_search_provider` | The `WebSearchProvider` base. `get_provider_env` reads a key through `agents.core.env_config` at call time, and only the key of the provider the adapter is running (`provider_scope`): Exa reads `EXA_API_KEY`, Brave `BRAVE_SEARCH_API_KEY`, Parallel `PARALLEL_API_KEY`. Any other name, another provider's key or a read outside a scope reads as unset. |
| `os` | `hermes_compat.os_env` | `getenv` only, for `PARALLEL_SEARCH_MODE` only, inside Parallel's scope. |
| `plugins.web.keyless_mcp` | `hermes_compat.keyless_mcp` | Off. Hermes's anonymous keyless tier is never used: a search goes only to a backend the owner configured. |
| `tools.interrupt`, `tools.web_tools`, `pm` | same names under `hermes_compat` | No interrupt flag (the e-stop acts at egress), the SDK cache slots, and no runtime installs. |
| plugin `ctx` | `hermes_compat.plugin_ctx` | `register_web_search_provider` wraps the provider in an adapter (`HermesSearchProvider`, a Nerva `SearchProvider`) and calls `register_search_provider`. The adapter sets the egress identity (`websearch`) and the tier from a reviewed table: all three count as paid, Brave too, since a `BRAVE_SEARCH_API_KEY` may be a paid-plan key. It never marks a provider keyless. It runs the synchronous vendored search on its own 4-thread executor, at most 3 at a time, never on the default executor the egress client needs for DNS. A search has 25 s (the tool loop cuts at 30 s) and its worker gives up when the caller leaves. It turns Hermes rows into Nerva rows (`title` / `url` / `snippet`), raises `PolicyBlock` from the recorded refusal and `ProviderFailure` with a reason code otherwise. A logging filter on each vendored logger drops records below WARNING, because upstream logs each query at INFO; a later `dictConfig` does not remove it. |

`agents/core/plugins/web_providers.py` loads the adopted providers after its built-ins
(`ADOPTED_PROVIDERS`). The hosts (`api.exa.ai`, `api.search.brave.com`, `api.parallel.ai`)
are on the `websearch` manifest allowlist, the same way the built-ins' hosts are.

## Rewrite rules

The rules live in `REWRITE_RULES` in `scripts/hermes_vendor.py` and are copied into the
manifest. `status` fails if the two differ. Each rule rewrites one import line in place, so
line numbers stay the same and upstream diffs stay readable. No replacement matches any
pattern, so the rewrite is idempotent. All rules but one rewrite an import. The exception,
`exa-integration-tag`, changes the caller name the Exa provider sends.

| Rule | Upstream line | Becomes |
|---|---|---|
| `httpx` | `import httpx` | `from agents.vendor.hermes_compat import httpx` Each wait is polled, so a worker stops when its caller leaves or the call's deadline passes. A request carrying a credential header is never sent with `follow_redirects`. |
| `os-env` | `import os` | `from agents.vendor.hermes_compat import os_env as os` |
| `web-search-provider` | `from agent.web_search_provider import …` | `from agents.vendor.hermes_compat.web_search_provider import …` |
| `keyless-mcp` | `from plugins.web.keyless_mcp import …` | `from agents.vendor.hermes_compat.keyless_mcp import …` |
| `plugins-web` | `from plugins.web.… import …` | `from agents.vendor.hermes.plugins.web.… import …` |
| `interrupt` | `from tools.interrupt import …` | `from agents.vendor.hermes_compat.interrupt import …` |
| `web-tools-slots` | `import tools.web_tools as …` | `import agents.vendor.hermes_compat.web_tools as …` |
| `pm` | `import pm` | `from agents.vendor.hermes_compat import pm` |
| `exa-sdk` | `from exa_py import …` | `from agents.vendor.hermes_compat.sdk.exa_py import …` |
| `exa-integration-tag` | `client.headers["x-exa-integration"] = "hermes-agent"` | `… = "nerva"` |
| `parallel-sdk` | `import parallel` | `from agents.vendor.hermes_compat.sdk import parallel` |

A new rule is a code change to the script and needs a compat module behind it. It is never a
hand edit to a vendored file.

## Vendoring a file / updating

```bash
# where things stand: hashes vs manifest, local edits, unlisted files
python scripts/hermes_vendor.py status
python scripts/hermes_vendor.py status --upstream ~/src/hermes-agent   # also: still == rewritten upstream?

# what an update would change, per file, with the rewrites applied (review this diff)
python scripts/hermes_vendor.py diff --upstream ~/src/hermes-agent

# take it (or vendor a new file): rewrites, writes, updates MANIFEST.json
python scripts/hermes_vendor.py pull --upstream ~/src/hermes-agent plugins/web/exa/provider.py
```

`pull` reads the clone's commit with `git rev-parse` (or takes `--commit`). It refuses a
symlink, or a path that resolves outside the clone. It refuses a file with local edits unless
you pass `--force`. It refuses a file that, after the rewrite, falls outside the
**allowlist**:

- a `.py` file may import only `SAFE_STDLIB`, the listed compat modules and vendored
  siblings;
- `os` is allowed only as `os_env as os`;
- the only relative import allowed is `from .x import y`;
- no network, process or import-machinery names, as attributes or strings;
- any other file must be YAML, JSON, Markdown or text that parses as plain data.

`status` applies the same allowlist and checks `rules_applied` against the bytes.
`tests/test_hermes_adopt_lane.py` runs it over the whole vendored tree on every CI pass. Its
output is deterministic: the manifest is written with sorted keys, and pulling the same text
twice leaves it byte-identical. After a pull:

1. Read the `diff` output. A change that adds an import, a host or a new `ctx.register_*`
   call needs the compat layer (and possibly the manifest allowlist) to cover it first.
2. Update `NOTICE.md` if the pinned commit moved.
3. Run `pytest tests/test_hermes_adopt_lane.py tests/test_h381_no_bare_model_client.py
   tests/test_websearch.py tests/test_h310_web_parity.py tests/test_plugin_egress.py`.

## What may be adopted

- **Yes:** leaf modules whose Hermes imports are few and map onto an existing Nerva control:
  search and extract providers, leaf tools such as `todo` and `clarify` (through a future
  `tools.registry` shim onto the kernel-gated tool server), plugins whose `register(ctx)` uses
  only `ctx` methods the compat layer offers, and SKILL.md skills (through the skills importer).
- **No:** anything that needs a network client, a subprocess, the filesystem or a secret store
  that is not behind a compat shim mapped onto a Nerva control. Also no modules tangled with
  `hermes_state`, `hermes_cli.config`, the gateway or the agent loop (the Run lane covers them
  through the sidecar), and no file that needs editing to work here.
- **Security-sensitive areas** (approvals, memory writes, execution, delegation, credentials)
  get adversarial review even when adopted.

## Limits of the first slice

- Only **search** is wired. The vendored files also contain Exa and Parallel `extract`. Their
  SDK calls (`Exa.get_contents`, `AsyncParallel`) are not in the stand-ins, so they would
  return an error entry. Nerva's `web_extract` uses its own reader.
- The SDK stand-ins follow the vendors' documented REST APIs and are tested against a fake
  transport only. No live call was made.
- `parallel/provider.py` reads `PARALLEL_SEARCH_MODE` with `os.getenv`. The `os-env` rule
  points that read at the allowlisted shim, but the line still counts in the AUD-14 raw-read
  ratchet.
