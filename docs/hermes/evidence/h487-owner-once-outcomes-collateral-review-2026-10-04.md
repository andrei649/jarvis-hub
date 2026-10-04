# H487 owner-once outcome collateral review

Coordinator reviewed the seven-path patch at base31a1d193. Queue, kernel, proof,
grants, ToolResultStore and project-context handlers retain their bytes. Only
exact OwnerOnceClaim reaches the existing signed run branch; observations are
frozen nonauthority values checked against process-local prompt identity.
Durable owner-denial reconciliation additionally checks task birth, offer nonce
hash/deadline, origin/principal, verified delivery, generation and matching
human decision ID. Machine denial and forged public fields cannot qualify.

Root RED:12 failures among14 cases,zero setup errors. Root GREEN:82 focused
and367 adjacent cases pass. A deterministic post-CAS/pre-publication barrier
reproduced the earlier race in the isolated prototype and passes after the
exact durable reconciliation. Queue revocation still settles abandoned offers;
physical gates and cancellation behavior remain unchanged.

H298 and H594 cite the actuation test whose authenticated human-denial label
changes to owner_denied. Its zero-spawn, CAS, control and queue expectations
remain, and the underlying spill/paging/convention implementations are unchanged.
H487 keeps its partial verdict; only its registered native terminal owner-once
outcome gap is closed offline. Free-text denial, remaining producers and live
acceptance remain open. Already-stale H277/H485 reviews are not refreshed.
