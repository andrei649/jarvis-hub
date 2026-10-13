# Nerva Business — local delivery, 2026-10-13

Goal: turn the existing Nerva codebase into a concrete company-product pilot for
Digitaholic, starting with ecommerce and sales data. Base SHA:
`413a42ceedb9302f47b1dfff9f76f984cdd355e4`. Branch:
`feat/nerva-business-platform`. Verification was performed on the local candidate;
the delivery commit is available through `git log -1` on that branch. No push,
merge, customer deployment or paid provider request was performed.

## Delivered behavior

- Default-off Business workspace in Console, one company per persistent data root.
- Ecommerce/automotive/services profile choices; these are metadata templates,
  not installed department-agent bundles.
- Administrator-configured WooCommerce and HubSpot read-only adapters, public
  HTTPS/origin/DNS restrictions, encrypted credentials, bounded streamed responses,
  manual sync with last-success snapshot retention.
- Explicit CSV imports and same-kind replacement; cross-kind name reuse is refused.
- Exact decimal report totals separated by currency, excluded order statuses,
  unknown stock/amounts, partial/stale source coverage and historical reports.
- Read-only questions use aggregates rebuilt from current snapshots with coverage
  warnings. The existing Nerva router/data policy is reused. Default local-only
  requires a verified loopback endpoint; three concurrent AI requests per process.
- Responsive browser UI, generated OpenAPI types and HUD bundle, guarded API and
  desktop route registries, operator guide and synthetic CSV examples.
- Optional Compose override and Docker context exclusions for local data/secrets.

Changed areas: `agents/core/business`, `agents/core/routers/business.py`,
`agents/web.py`, Business frontend/API/registries, generated web bundle/schema,
route/auth/OpenAPI snapshots and tests, docs/examples/Compose packaging.

## Evidence

- Backend integration: **185 passed** in the final integration run, covering the
  then-current Business suite, existing company routes, route/auth/OpenAPI/HUD
  parity, full application lifespan, pinned HTTP SSRF and model data policy.
- Final new-feature suite: **51 passed**, including the concurrency regression
  verifying three active model calls and refusal of a fourth.
- Full existing frontend suite: **2,188 passed**, including browser and native
  appearance projects. Final focused Business/routing run: **35 passed**.
- TypeScript typecheck and Vite production build passed. Build reports its existing
  large-chunk advisory. Generated API schema input matched the final app schema.
- Repository-wide Ruff passed (one pre-existing invalid-noqa advisory);
  `git diff --check` passed. Desktop route generation `--check` passed.
- Docker Compose merged configuration validates. Container image build was not run.
- Real `serve.py` boot in a disposable data root reached `/readyz` 200.
- Real Chromium with the served production bundle: profile save → CSV import →
  sales report → page reload passed, no uncaught page errors. Synthetic sample:
  two included orders totaling **339.40 RON**, one cancelled order excluded.
- Browser inspected at 1440px and 390px; no document horizontal overflow at 390px.
- Process restart retained the profile, snapshot and report. With no model
  configured, `/api/business/ask` returned the expected explicit 503 refusal.

Full backend collection succeeded: **25,592 tests collected**. The tracked counts
and generated status documents were updated from collection and the frontend run.
The backend suite was not executed in full; focused integration and collection
are not a substitute for a full-run claim. Live WooCommerce/HubSpot accounts,
actual local/cloud inference, DGX capacity, VPN deployment and native mobile
Business UI were not validated.

## Review and handoff

Two implementation agents used `gpt-6-sol` / high reasoning, with disjoint backend
and frontend ownership. A `gpt-6-luna` / medium read-only reviewer found cross-kind
CSV replacement; its failing regression was corrected. Coordinator integration
also corrected body streaming limits, unknown HubSpot amounts, saved-policy UI
state, safe provider errors and route registry parity. No subdelegation occurred.

Start with [the operator guide](BUSINESS.md). GitHub reuse decisions and license
references are in [the research note](research/2026-10-13-business-open-source.md).
Next action is an actual clothing-store acceptance using scoped credentials,
followed by the BIZ-3 through BIZ-7 backlog items. Commercial billing, person/role
separation, email/phone connectors, scheduled transactional automations and
hardware sizing remain open product work.

Rollback: stop Nerva, disable `NERVA_BUSINESS_ENABLED`, and revert this coherent
local delivery commit if needed. Preserve the company's `JARVIS_HOME` and key
files; disabling the module intentionally leaves its data in place.
