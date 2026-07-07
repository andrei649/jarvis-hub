# R3-B3 A2A and Escalation Contract Gates Design

## Goal

Close the next R3 contract-less seams by making inbound A2A task intake and autonomy escalation broadcast evaluate live automation contracts before they mutate state or send to channels.

## Scope

This slice covers:

- `agents.core.a2a.A2ARegistry.receive_task(...)`
- `agents.core.autonomy.escalation.EscalationRouter.escalate(...)`

This slice does not cover MCP route-tool mutation or generic channel-send transports. Those stay separate R3-B4/R3-B5 waves.

## Design

Add an `A2A_INBOUND_CONTRACT` in `agents/core/a2a.py`. It runs after the existing enable, peer allowlist, HMAC signature, and JSON parse checks, but before a pending inbox record is appended. The contract payload is sanitized: contract kind, `peer_id`, whether the task field is present, whether the task is a dict/list/scalar, task key names when the task is a dict, and a bounded JSON length. It never receives the raw body or task text. A denied contract raises `PermissionError("contract denied: <reason>")`; the public route already maps permission failures to a closed 401.

Add an `ESCALATION_CONTRACT` in `agents/core/autonomy/escalation.py`. `EscalationRouter.escalate(...)` resolves governed targets exactly as today, then evaluates the contract before any adapter `send(...)` call. The payload is sanitized: contract kind, target channel ids, requested channel ids, `message_len`, and target count. A denied contract returns the same result shape as delivery, with every target listed as failed and no adapter called. If there are no targets, behavior remains the existing empty-success shape.

Default contracts are permissive for existing valid flows and only add admissibility checks. Human/admin gates and allowlists remain the primary control surfaces; this PR makes the contracts reusable and patchable like the rest of 0.45.

## Risks

- A2A route status remains 401 for contract denials because the route deliberately does not reveal whether peer auth or contract policy rejected the request.
- Escalation denial uses the existing result shape instead of raising, preserving the best-effort/no-throw contract.
- Contract payloads must not contain message text, raw task bodies, or arbitrary task values.

## Tests

- Add R3-B3 regression tests that monkeypatch `A2A_INBOUND_CONTRACT` and `ESCALATION_CONTRACT` with denying contracts.
- The A2A test proves a signed valid inbound task is rejected before the inbox changes.
- The escalation test proves a denied broadcast does not call any channel adapter and reports every resolved target as failed.
- Existing A2A and H12.11 escalation tests stay green.
