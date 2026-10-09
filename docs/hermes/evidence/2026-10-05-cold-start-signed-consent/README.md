# H067 cold-start undo and signed permanent consent

Goal: all 697 pinned Hermes capabilities. H067 remains partial; no equivalence credit is added.

Local offline integration: 419 tests passed. Eight physical-kernel cases exercise coordinator registration, signed enforce-mode receipt, real worker approval/execution, persistence, revocation, identity isolation and denial paths. Twenty-six command-runtime cases include cold-start history. Human approval uses the trusted worker API in synthetic tests; this is not live Telegram authentication evidence.

`/undo` loads an existing persisted transcript before its snapshot, under route leases, and rechecks authority after awaiting that load. Missing or corrupt expected history is refused. Permanent consent now uses the same final title for kernel and queue and requires recorded human approval matching action and decider. Bare owner attribution does not mint a grant.

Legacy permission tasks without the recorded human decision are refused and need a new recorded approval. Existing grants are preserved. Native workspace transports and remaining producers are still open. The earlier 2394-test snapshot remains historical; no fresh full-suite claim is made here.

Evidence: `report.json`, `scoped-inputs.json`, `integration-result.xml`. All work remains local and unpublished.
