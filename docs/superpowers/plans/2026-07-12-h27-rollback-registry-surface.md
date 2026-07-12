# H27.6 + H27.8 implementation plan

1. Add failing tests for `RollbackContract` validation, exact action coverage, registry JSON shape,
   wildcard/unknown approval projection, and the authenticated `/api/capabilities` route.
2. Implement the frozen rollback contract in `capability_manifests.py`; convert action and derived
   records without adding a second source of truth.
3. Project rollback metadata into blocked autonomy tasks and both approval clients; add red/green
   browser and mobile rendering tests.
4. Add the canonical registry route, move the HUD board to it, and add risk/supports/confidence
   columns with bounded rendering.
5. Reseed route/OpenAPI/auth snapshots and regenerate the committed TypeScript OpenAPI schema.
6. Update `BACKLOG.md`, `mobile/PARITY.md`, `docs/design/HUD_V2_REMAINING.md` if applicable, and
   generated status counts only after the implementation is proven.
7. Run focused backend, frontend, and mobile suites; lint/typecheck/build; inspect the complete diff;
   run release/parity gates; push a draft PR and self-review it before CI merge.

