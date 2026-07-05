# H18.17 Mobile Knowledge Graph Plan

## Files
- `mobile/src/api/client.ts`
- `mobile/src/api/__tests__/knowledgeGraph.test.ts`
- `mobile/src/screens/MemoryScreen.tsx`
- `mobile/PARITY.md`
- `mobile/README.md`
- `BACKLOG.md`
- `STATUS.md`
- `docs/SPRINT.md`

## Steps
1. Add failing mobile API tests for KG entity list/detail/facts/history helpers.
2. Implement typed client helpers and normalizers over the existing read endpoints.
3. Extend the Memory screen with a Turns/Graph segmented view and read-only graph cards.
4. Update H18.17 parity/backlog/status/sprint/README docs.
5. Run focused Jest, full mobile Jest, `npx tsc --noEmit`, status sync, and diff checks.
6. Publish a draft PR and only mark ready after CI is green.

## Rollback
Revert the H18.17 PR. The backend routes already exist and no backend behavior changes are planned.
