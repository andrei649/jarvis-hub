# H18.18 Mobile Security Posture Plan

## Files
- `mobile/src/api/client.ts`
- `mobile/src/api/__tests__/securityPosture.test.ts`
- `mobile/src/screens/StatusScreen.tsx`
- `mobile/PARITY.md`
- `mobile/README.md`
- `BACKLOG.md`
- `STATUS.md`
- `docs/SPRINT.md`

## Steps
1. Add failing mobile API tests for governance/posture/kill-switch/loop-breaker helpers.
2. Implement typed client helpers and sparse-payload normalizers.
3. Extend Status with a read-only Trust card.
4. Update H18.18 parity/backlog/status/sprint/README docs.
5. Run focused Jest, full mobile Jest, `npx tsc --noEmit`, status sync, and diff checks.
6. Publish a draft PR and only mark ready after CI is green.

## Rollback
Revert the H18.18 PR. Existing hub security routes are unchanged.
