# Nerva Business pilot design

Generated: 2026-10-13. Goal: productize Nerva for Digitaholic-managed company deployments. Base SHA: `413a42ceedb9302f47b1dfff9f76f984cdd355e4`; feature branch `feat/nerva-business-platform`. Owner explicitly requested implementation in this conversation. Existing AGENTS.md authorizes local work; no publication or deployment is requested.

## Outcome and boundary

A working company workspace in the existing HUD, backed by durable local storage, real bounded read-only connectors, CSV ingestion, repeatable reports and a grounded assistant using Nerva's existing configured model router. One company per deployment/data root. This pilot does not claim separate department ACLs, SaaS tenant isolation, billing enforcement, SSO, telephone agents, autonomous external writes, or a production SLA. Keep existing personal functionality intact.

## Architecture

Extend FastAPI under `/api/business`, existing React HUD under Console → Business. New business modules live in `agents/core/business/`. Reuse SecretStore, guarded HTTP transport and HybridRouter; add no runtime framework or dependency. Operator opt-in is `NERVA_BUSINESS_ENABLED=1`; disabled reads report the state and mutations refuse. Configure/check/sync/import/remove are admin-only; shared workspace/report/question reads use existing user authentication. All authenticated workspace users share its data; deploy separately for different clients.

Persist profile, connection metadata, bounded snapshots, reports and activity in SQLite under JARVIS_HOME; secrets in a dedicated existing SecretStore instance. Serialize secret access, never return credentials or raw provider errors, and replace snapshots transactionally. No automatic network on startup or a GET. Remote connector traffic uses explicit configured HTTPS hosts, existing SSRF/DNS pinning and egress policy. Existing local-only LLM policy remains authoritative; business `local_only` adds a stricter refusal before cloud dispatch. No tools execute from generated text.

## Shared implementation interfaces

`catalog.py`: `catalog() -> dict` with `templates`, `connectors`, `workflows`. Templates ids `ecommerce`, `automotive`, `services`; fields id,name,description,departments. Connectors ids `woocommerce`, `hubspot`, `csv`; fields id,name,description,category,auth_fields (key,label,secret),base_url_required. Credentials: Woo `consumer_key`, `consumer_secret`; HubSpot `access_token`; CSV none. Workflows ids `sales_overview`, `stock_watch`, `pipeline_review`, fields id,name,description,requires (record kind: orders/products/deals).

`connectors.py` (coordinator): `validate_connection(provider: str, base_url: str, credentials: dict) -> str` returns normalized URL or raises ValueError; `async fetch_snapshot(provider: str, base_url: str, credentials: dict) -> dict`; `parse_csv(text: str, kind: str) -> dict`. Snapshot shape `{records:{orders:[],products:[],deals:[]}, complete:bool, coverage:str}`. Bounded to 500 records/kind for remote imports and 500 CSV rows. Order fields id,status,total(decimal string),currency,created_at. Product id,name,stock_quantity(number|null). Deal id,name,amount(decimal string|null),currency,stage. `ConnectorError` safe error string only. Transport injection/patch seam required for offline tests; real transport is PluginHTTPClient.

`reports.py` (coordinator): `build_report(workflow_id: str, snapshots: list[dict]) -> dict` returns `{workflow_id,title,summary,metrics:dict,rows:list,coverage:list,warnings:list}`; supplied snapshots have `connection_id`, `connection_name`, `records`, `complete`, `coverage`, `synced_at`. Never combine currencies; exact Decimal sums, exclude cancelled/refunded/failed/pending Woo orders from paid sales and state this. No snapshots gives a meaningful unavailable/empty report, never fake values. Clamp negative quantities as true stock shortages; unknown stock remains unknown.

`assistant.py` (coordinator): `async answer_question(question: str, context: dict, local_only: bool) -> dict` returns `{answer,model,route}` via current orchestrator llm_router, approved models/data handling checks, bounded context and output, 3 concurrent requests, no external write tools. Explicit unavailable errors when model isn't initialized.

`store.py/service.py` (backend implementer) owns persistence and uses interfaces above. `routers/business.py` exposes:
- GET `/api/business/catalog` → `{enabled,templates,connectors,workflows}`.
- GET `/api/business/workspace` → `{enabled,workspace:{name,industry,currency,local_only},connections:[],reports:[],activity:[]}`.
- PUT `/api/business/workspace` body `{name,industry,currency,local_only}` → workspace state.
- POST `/api/business/connections` body `{provider,name,base_url,credentials}` → `{connection:...}`. Public connection fields id,provider,name,base_url,status,last_sync_at,error,record_count; no credentials.
- POST `/api/business/connections/{connection_id}/sync` → `{connection:...}` (also serves real connection test; no false “connected” on save).
- DELETE `/api/business/connections/{connection_id}` → `{ok:true}`.
- POST `/api/business/import` body `{name,kind,csv_text}` → `{connection:...}`; creates/replaces an explicit CSV connection.
- POST `/api/business/reports/{workflow_id}/run` → `{report:...}`; persisted report includes id,created_at and build_report fields.
- POST `/api/business/ask` body `{question}` → answer_question result, context rebuilt from current snapshots, numeric aggregates plus source coverage/warnings only.

No demo data is injected silently. UI has useful empty/error/loading states and precise labels for imported/partial/stale snapshots, admin settings and shared-user scope. UI language Romanian. Reuse existing authentication/base-path helpers and accessible forms. Profile edits never implicitly grant cloud permission.

## Verification and rollback

Tests cover encrypted credential persistence/no API disclosure; guard classification and disabled mutations; bounded CSV and malformed values; currency separation and partial data; connector URL validation and HTTP failures; cloud refusal before dispatch; UI forms/errors/report run. Existing company routes baseline: 26 passing. Run targeted Python/frontend suites plus route/auth/HUD parity and production build. Real vendor accounts and DGX are unavailable; do not claim those live checks. Rollback removes new modules/router/UI entry; data is isolated in business files. No existing tables or runtime permissions change.

## Follow-on product work

Enterprise user/department authorization, scheduled sync with durable jobs, write-action approval adapters, usage accounting/contract limits, billing and SSO are separate increments. Current pilot is an installable vertical slice, not the full commercial acceptance of the proposed pricing packages.
