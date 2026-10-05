# Resident code execution — local checkpoint

H595/H660 remain partial; the accepted total remains129/697 (18.5%).
This batch fixes required cell authorization and the resident default, without
claiming complete remote transport or full697 parity.

One invocation earns one consuming GRANT. The existing bound kernel revalidate
checks live permission after lock acquisition and before safe fallback, without
charging its budget or loop twice. QUEUE/absent/malformed decisions and revoked
policy cannot mutate the worker. Refused reset keeps existing variables.

Final resident/RPC regression:525 passed, one Linux /proc-only skip on macOS,
zero failures/errors. Separate earlier shared-impact553, API/doc gates54 and
HUD7 passed; counts overlap. No live provider/remote Docker or whole-suite claim.
Scoped Ruff, Bandit and strict Gitleaks passed; source hashes, localized AST/doc
impact and exact preimage-only assessment refresh are recorded alongside.
Graft graph is current; its context index remains intentionally uninitialized.

See report.json, scoped-inputs.json and reviewed-pin-impact.json for the bounds
and reproducible evidence. All work is local and uncommitted; no publication.
Next: compare H595 against its pinned12 entries, then reuse donor remote kernel
transports for H660 and finish H515. Preserve inherited work and verdicts.

Final metadata/status/doc/API regression:211 passed, zero failures/errors/skips
(final-records-result.xml). Generated Hermes reports are in sync at129/697.
