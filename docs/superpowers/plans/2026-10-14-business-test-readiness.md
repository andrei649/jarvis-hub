# Business pilot: evening test readiness

Generated 2026-10-14. Goal: make tonight's first company-data test easy to start,
interpret and share. Base/head at start: `3d100ac` (feature branch
`feat/nerva-business-platform`, clean). Owner explicitly requested autonomous
improvements. No push, merge, deployment, paid provider calls or customer writes.

## Deliverable and boundaries

- Visible first-use steps and explicit synthetic CSV examples in the Business UI.
  Choosing an example fills the form; the user still imports it explicitly.
- Optional single-source filter for all reports and inclusive UTC calendar-date
  boundaries for sales only. Honest handling of missing dates and bounded source
  snapshots. Report coverage includes relevant sources only.
- Saved report download as JSON and formula-safe CSV of visible rows, with the
  100-row limit and metadata/warnings made explicit. No new dependency.
- AI can answer about the selected saved report by optional `report_id`; current
  aggregate behavior remains available explicitly. Saved reports are historical.
- Useful safe CSV row/field errors and provider connection errors; no raw provider
  body, URL credentials, CSV cell content or secret values in errors.

No scheduled transactional automations, new SaaS providers, department ACLs,
tenant changes, billing or hardware capacity promises in this increment.

## Interfaces and ownership

Backend report implementer owns `agents/core/business/reports.py` and
`tests/test_business_reports.py` only. `build_report(workflow_id, snapshots, *,
start_date=None, end_date=None)`; optional strict YYYY-MM-DD inclusive UTC dates
for sales. Other report kinds reject supplied dates. `ReportFilterError(ValueError)`
exposes only safe messages. Result adds `filters: {start_date,end_date}`. Parse
offset timestamps to UTC; naive date/time interpreted as UTC with an explicit
warning during filtering; missing/invalid dates excluded and counted separately.
Do not alter existing unfiltered totals. Relevant source discovery uses `kind`
(CSV), `provider` (remote) or nonempty records of the report kind.

Frontend implementer owns `frontend/src/panels/business*`,
`frontend/src/api/business.ts` and any new `business-export*` helpers/tests.
POST `/api/business/reports/{id}/run` optional body
`{connection_id?:string,start_date?:string,end_date?:string}`; omitted means all
sources/dates. Dates apply only to sales. Result includes `filters` and
`source_selection: {connection_id: string|null}`. POST `/api/business/ask` accepts
`{question,report_id?:string}`. UI clearly offers selected report vs all current
data. Synthetic examples mirror `examples/business/*.csv` in a small frontend
module because Vite disallows those outside-root raw imports.

Coordinator owns service/router/store projection as needed, connectors and their
tests, route tests, integration, generated bundle/schema/status, docs and parity.
No new routes. API dependencies and default local-only policy remain unchanged.
At most two gpt-6-sol/high implementation agents; optional read-only reviewer;
no subdelegation. Tools for repository graph/navigation are unavailable here;
current source and `rg` suffice for this bounded module.

## Verification and rollback

Red/green tests for report boundaries, source coverage, CSV safe row errors,
source/report selection, expiry/refusal, exports and frontend interactions.
Run Business and affected integration suites, typecheck, production build,
repository lint, schema/status guards and real browser flow at desktop/mobile.
Reuse the previous full frontend baseline unless changes/failures justify a new
full run; full backend collection updates the tracked count, not a full-run claim.
One coherent local commit; rollback by reverting it with company data preserved.

## Implementation and review

The planned interfaces and UI are implemented. Separate gpt-6-sol/high agents
owned report logic and frontend work; the coordinator owned API/service/errors
and integration. A gpt-6-luna/medium read-only review found a question-edit race;
the fix invalidates both late answers and late errors when question/scope/report
changes. Meaningful regressions cover it. No agent subdelegated.

Report/API integration: 208 selected backend tests passed; 73 tests in the
Business module passed. This includes safe CSV diagnostics, historical report
context, source selection, calendar boundaries and existing policy/guard tests.
Schema/status tests passed (43). Full backend collection: 25,614 tests; the full
backend suite was not executed. TypeScript typecheck, Vite build, repository-wide
Ruff and diff checks passed. Vite reports the existing large-chunk advisory.

No model/provider credentials or DGX hardware were available for live acceptance.
The optional toolkit's Graft/codebase-memory integration was not callable here;
source navigation used rg. Optional linked skill reference files could not be
read; the main coordination instructions and repository files were available.

Full frontend suite: all 2,198 tests passed. A real Chromium flow verified explicit
example import, totals of 339.40 RON and filtered 249.90 RON, downloaded JSON/CSV
contents, stock metrics, selected report context, model-unavailable refusal and
reload persistence. Desktop (1440 px) and mobile (390 px) had no page errors or
document overflow. Visual inspection prompted stacking report filters on narrow
screens; the production bundle was rebuilt and the browser flow repeated.

Tracked test counts are synchronized; the existing remote CI stamp is preserved.
Delivery is one local commit on the feature branch. The next action is the
owner's manual test using [the ten-minute scenario](../../BUSINESS_TEST.md).
Live accounts, actual AI responses and DGX capacity remain unverified.
