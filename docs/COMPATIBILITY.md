# Compatibility & Versioning Contract

> What "a version" promises, which versions are supported, how things are
> deprecated, and which platforms are supported. (H23.14)
>
> The canonical version is **`agents.__version__`** (single-sourced; surfaced in
> `GET /status` and the OpenAPI metadata — CDX-4). The current release line is
> tracked in [`STATUS.md`](../STATUS.md); the forward plan is the version roadmap
> in [`BACKLOG.md`](../BACKLOG.md#version-roadmap).

## Versioning scheme — Semantic Versioning

Jarvis Hub follows [Semantic Versioning 2.0.0](https://semver.org): `MAJOR.MINOR.PATCH`.

- **MAJOR** — incompatible API/behavior changes.
- **MINOR** — backward-compatible features.
- **PATCH** — backward-compatible fixes.

**Pre-1.0 caveat (we are here).** Per SemVer §4, while the version is `0.y.z`
*anything may change*: a `0.MINOR` bump (e.g. `0.11 → 0.12`) may include breaking
changes. We still aim to call them out in the release notes / UPGRADE notes, but
do not treat a `0.x` minor as a stability guarantee. The strong compatibility
promises below take full effect at **1.0.0**.

### What the public surface is

The compatibility contract covers:

- the **HTTP API** (the route + OpenAPI surface, frozen by the parity guards in
  `tests/test_route_parity_guard.py` / `tests/test_openapi_parity_guard.py`),
- documented **environment variables** and **`/admin` settings**,
- on-disk **data formats** (covered forward by the migration framework, H23.7).

Internal modules, private helpers (leading `_`), and anything marked experimental
are **not** part of the contract and may change at any time.

## Supported versions

During the `0.x` beta, only the **latest minor** receives fixes (security and
otherwise). Older minors are not back-patched — upgrade to the latest `0.MINOR.x`.

| Version line | Status |
|--------------|--------|
| `0.11.x` (current) | ✅ Supported |
| `< 0.11` | ❌ Not supported — upgrade |

At 1.0.0 this expands to a rolling window (the current MAJOR.MINOR plus the prior
minor for a defined window); that policy is finalized as part of the 1.0 release.

## Deprecation policy

When a public surface (an endpoint, env var, setting, or documented behavior) is
going away:

1. It is **marked deprecated** in the release notes / [UPGRADE notes](#upgrade-notes)
   and keeps working for **at least one full minor release**.
2. While deprecated it emits a **runtime warning** (log line / response header /
   `/admin` note) so operators see it before it's removed.
3. It is **removed no earlier than the next minor** after deprecation, and the
   removal is called out in that version's UPGRADE notes.

Security-critical changes may move faster; those are documented in
[`SECURITY.md`](../SECURITY.md).

### Upgrade notes

Per-version migration notes (breaking changes, required actions) live in the
release notes and the forthcoming `UPGRADE.md` (H23.18). On-disk schema changes are
applied forward automatically on startup by the migration framework (H23.7); the
pre-upgrade backup (H23.8) is your rollback.

## Platform matrix

| Component | Supported | Notes |
|-----------|-----------|-------|
| **Python** | **3.12+** | Hard floor: a core dependency (`numpy >= 2.5`) requires Python ≥ 3.12. 3.11 and older are **not** supported. |
| **OS (hub)** | Linux · macOS (incl. **Apple Silicon M1–M4**) · Windows 11 | Pure-Python + FastAPI. `install.sh` covers macOS/Linux; Windows has a one-click launcher. On Apple Silicon, run local models via LM Studio/Ollama on unified memory (owner M-series smoke = FB1). The CI matrix runs Ubuntu + Windows; macOS is community-validated. Windows 10 is untested (Win 11 is the supported baseline). Service templates: [`deploy/`](../deploy/). |
| **Local LLM** | LM Studio or Ollama | Local-first; cloud is opt-in, per-agent. |
| **Model providers** | LM Studio · Ollama · Anthropic · OpenAI · Gemini · **OpenRouter** · any **OpenAI-compatible** endpoint | Keys stay local (`.env`), called directly — no owner relay (see [`SECURITY.md`](../SECURITY.md)). Switch with `/model`; OpenRouter via `agents/core/llm/openrouter.py`. A **subscription (ChatGPT Plus / Claude Pro) is not an API key** and cannot be used. |
| **Usage profile** | `balanced` (default) · `gaming` · `ai` · `multimedia` · `admin` · **`headless`** | `JARVIS_SYSTEM_PROFILE=…`. `headless` = lean server/TUI/low-VRAM (8GB) posture: heavy media features off, autonomy on, local-light models. |
| **Node.js** | 20+ | Only for the optional WorldView (4D OSINT) sub-app. The hub runs without it. |
| **Docker** | optional | Required only for the containerized code **sandbox** and the WorldView infra. |
| **GPU** | optional | CPU/quantized models work; GPU-gated features (fine-tune, speculative decoding) are a separate track (0.18). Measured per-tier throughput: [`HARDWARE_BENCHMARKS.md`](HARDWARE_BENCHMARKS.md). |

## See also

- [`STATUS.md`](../STATUS.md) — current version + counts (snapshot source of truth).
- [`BACKLOG.md`](../BACKLOG.md#version-roadmap) — the forward version roadmap.
- [`SECURITY.md`](../SECURITY.md) — supported versions for security fixes + reporting.
- [`deploy/`](../deploy/) — service templates (systemd / Windows).
