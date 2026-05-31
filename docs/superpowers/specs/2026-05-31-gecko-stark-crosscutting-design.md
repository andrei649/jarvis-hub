# Gecko + Stark + Cross-cutting Design

## Sub-projects

1. **Gecko (H2.6)** — BalanceReaderPlugin: ING API / Libra API / CSV import. Plugin pattern. Admin configurator for API keys. Mock data when unconfigured.
2. **Stark (H2.11)** — AnalyticsPlugin: GA4 Data API + Firebase Analytics. Plugin pattern. Admin configurator for Service Account JSON. Mock data when unconfigured.
3. **Plans per agent** — `.opencode/plans/<agent>_spec.md` for each active agent.
4. **Load test** — `tests/test_load.py`: 15 parallel requests, verify <30s total.

## Architecture

### Gecko — BalanceReaderPlugin
- Class: `BalanceReaderPlugin` in `agents/core/plugins/balance.py`
- Sources: ING API (REST), Libra API (REST), CSV file import
- Admin config: settings DB category `plugins`, keys: `gecko_ing_client_id`, `gecko_ing_client_secret`, `gecko_libra_token`, `gecko_csv_path`
- Mock: when no source configured, return realistic mock data
- Orchestrator wiring: auto-registered in `load_agents()`

### Stark — AnalyticsPlugin
- Class: `AnalyticsPlugin` in `agents/core/plugins/analytics.py`
- Sources: GA4 Data API v1, Firebase Analytics API v1
- Admin config: settings DB `plugins.gecko_ga4_service_account` (JSON text)
- Mock: when no SA configured, return realistic mock KPIs
- Orchestrator wiring: auto-registered in `load_agents()`

### Plans per agent
- One `.opencode/plans/<agent>_spec.md` per active agent
- Sections: Identity, Skills, Tools, Memory, Triggers

### Load test
- `tests/test_load.py` with `pytest -n 0 --no-header -q tests/test_load.py`
- 15 agents via simulated orchestrator, mocked LLM backends
