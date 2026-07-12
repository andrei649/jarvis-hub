# H28.3 Named Terminal Targets — Design

## Goal

Build the missing policy plane over the existing local/docker/ssh environment profiles:
named targets, capability/agent policy per target, explicit approval outcomes, and a
tamper-evident audit chain.

## Non-goals

- No command execution, SSH connection, Docker launch, or local subprocess dispatch.
- No credentials, host addresses, commands, or payload contents in target records/audit.
- No replacement for the Action Kernel; `approval_required` must still flow through it.
- No API/HUD surface in this slice.

## Target model

`TerminalTarget` declares a safe name, one existing backend profile (`local`, `docker`,
`ssh`), enabled state, allowed agents, allowed capability tokens, and the subset that
requires approval. `TargetRegistry.authorize(target, agent, capability, correlation_id)`
returns exactly one of `allow`, `approval_required`, or `deny`; missing/disabled targets,
unknown agents/capabilities, malformed inputs, and duplicate registrations fail closed.

The built-in inventory names the roadmap targets without pretending host readiness:

- `bonobo-windows` → local, disabled until owner configuration;
- `pi-house` → ssh, disabled until owner configuration;
- `isolated-sandbox` → docker, enabled as a policy profile (transport remains separate).

## Audit chain

Every authorization decision appends a canonical JSON record containing sequence,
UTC timestamp, safe request identifiers, decision/reason, previous hash, and entry hash.
The hash is SHA-256 over the previous hash plus canonical record content. A lock makes
concurrent append ordering deterministic. `verify_chain()` recomputes the complete chain.

An optional JSONL path is loaded and verified on construction; malformed or tampered
history raises `TargetAuditCorrupt` and blocks further use. Appends flush + fsync before
return. Audit fields are length/token bounded and the API has no command/payload argument.

## Tests

- Built-in targets map exactly to local/docker/ssh and conservative enabled states.
- Agent/capability/approval policy returns the correct three-state outcome.
- Unknown, disabled, duplicate, invalid, and exception cases fail closed and are audited.
- Hash verification detects field/hash deletion or mutation.
- JSONL reload preserves the chain and corrupt files refuse startup.
- Concurrent decisions produce contiguous sequence numbers and a valid chain.
- Audit text contains no caller payload because none is accepted/stored.

## Rollback

Remove `environments/targets.py` and tests. Existing environment, sandbox, and file-RPC
primitives remain unchanged.
