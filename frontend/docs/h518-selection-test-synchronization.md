# Gallery selection assertion synchronization

Goal: make the existing continuation-authorization regression wait for its actual postcondition.
Base: 88b19d117810e229336ae8d62208e0668b21b1cf. Generated: 2026-09-15.
Evidence: PR 1122 HUD CI job 104428039157 failed at media-gallery-panel.test.tsx:114; 1,265 other frontend tests passed. The retry button is committed before the item-dependent selection cleanup effect necessarily commits. Waiting for that button does not synchronize the selection assertion.

Plan: keep runtime behavior unchanged and wrap both selection-empty/disabled and old-record-absent assertions in Testing Library waitFor. Run the focused gallery/lifecycle tests, both TypeScript checks and full frontend suite. Update only matching test evidence hashes. This preserves the failure if selection cleanup never happens and does not relax the export limit or authorization contract.

Runtime inspection: failed 400/401/403 continuation clears catalog items; the selection effect removes unavailable keys. Export derives IDs from currently available items before download and returns without a request when none remain. No stale ID is exported during the intermediate render. Rollback: revert this isolated test/doc correction.

Verification: 13 focused gallery/lifecycle tests and both TypeScript configurations pass. Independent review repeated all nine gallery tests and confirmed export intersects current available records. Full frontend and affected generated-evidence checks run before merge.
