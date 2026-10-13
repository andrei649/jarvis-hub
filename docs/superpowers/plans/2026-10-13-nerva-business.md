# Nerva Business Implementation Plan

Goal: deliver the company workspace described in ../specs/2026-10-13-nerva-business-design.md.
Architecture: reuse FastAPI, React HUD, SQLite, encrypted SecretStore, guarded HTTP and existing model router. One company per instance. No new runtime dependency.
Generated: 2026-10-13. Local branch feat/nerva-business-platform; base/head recorded in delivery handoff. Owner authorized implementation; coordinator integrates, up to two gpt-6-sol/high implementation agents, no subdelegation.

## Global constraints

Default off via NERVA_BUSINESS_ENABLED=1. No external mutations or provider charges during validation. Existing authorization, egress and data policy remain in force. Files have one writer. No push/merge/deploy. Remote data and generated text are untrusted.

## Review focus

Malformed CSV and unsafe URLs; secrets in responses/errors; concurrent persistence and failed snapshot replacement; cloud refusal with local-only policy; missing/partial/multi-currency data and honest user feedback.

- [x] Backend: first write regression tests for guards, durable profile/connections/secrets, disabled state and failed sync. Implement catalog/store/service/router using exact spec interfaces. Focused pytest then independent coordinator review.
- [x] Connectors/reports/assistant: first test unsafe URL, malformed money, currency separation, truncated snapshots and cloud refusal. Implement bounded WooCommerce/HubSpot/CSV readers, deterministic report engine and guarded model answer. Run focused tests.
- [x] UI: first test empty/error/profile/import/run interactions. Add Business panel, typed API client, styles and route registration; run focused tests and typecheck/build.
- [x] Integration: mount router, route/auth snapshots, HUD/mobile parity intent, deployment instructions, CSV example, research/license receipt and roadmap entry. Run targeted integration and full frontend suites once at milestone, inspect actual rendered UI where possible.
- [x] Handoff: record actual checks and limitations, complete local commit and provide launch instructions. No remote publication.

Verification and limitations: ../../business-delivery-2026-10-13.md. Base SHA 413a42ceedb9302f47b1dfff9f76f984cdd355e4; generated 2026-10-13. Next action: local handoff, then customer acceptance.
