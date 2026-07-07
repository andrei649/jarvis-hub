# H18.18 Mobile Security Posture Design

## Goal
Catch the native mobile app up to the browser HUD's Trust/Security read surfaces while keeping operator controls out of scope.

## Non-goals
- No kill-switch engage/disengage from mobile.
- No capability token issue/check form from mobile.
- No audit anchoring or reset actions from mobile.
- No backend route changes.

## Surface
- `GET /api/security/governance` for public governance scorecard.
- `GET /api/security/posture` for packaged posture. This is admin-guarded and uses the existing mobile admin-token setting.
- `GET /api/security/kill-switch` for current halt state.
- `GET /api/security/loop-breaker` for loop-circuit status.

## UX
The existing Status tab gains a Trust card. Status is where the phone already shows system posture, so this avoids another bottom tab and keeps security telemetry near model/system health.

The Trust card is read-only and resilient:
- governance/kill-switch/loop-breaker may show even if admin posture is unavailable;
- posture absence is visible but non-fatal;
- no write/reset/halt buttons are rendered.

## Tests
- Red mobile API tests prove no `fetchSecurity*` helpers exist before implementation.
- Focused Jest covers auth/header behavior and sparse-payload normalization.
- Full mobile Jest and TypeScript check before PR.
