# Security and authority review

Use when a change reads personal content, admits outside input, grants a capability, stores a secret, or causes a physical, network or financial effect. The current boundaries are in [SECURITY.md](../../SECURITY.md), [the threat model](../../docs/THREAT_MODEL.md), and [AGENTS.md](../../AGENTS.md).

- [ ] Verify the actual shared user/admin guard on every entry point. Personal-data GETs need `no-store`; unknown, invalid and unauthorized requests must not disclose the content.
- [ ] For a mutation, trace permission, typed contract, Action Kernel decision and durable audit through the real executor. A kernel grant cannot substitute for separate owner review where required. Check denial and revocation before effect.
- [ ] Treat remote, skill, tool and recalled text as untrusted data. Check path/size bounds, SSRF and destination validation, taint framing, digest or snapshot binding, and quarantine before activation where applicable.
- [ ] Keep keys and owner runtime data out of logs, tests, generated artifacts and review text. Do not infer cloud/provider consent from a local test or silently call a paid service.
- [ ] Check e-stop, refusal and failure paths for no partial write or unintended side effect. Use a synthetic fixture for a sensitive-content test; do not use owner data.

State which boundary was exercised by a test and which live owner or provider condition remains unverified.
