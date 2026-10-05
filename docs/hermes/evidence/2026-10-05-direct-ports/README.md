# Direct Hermes ports — local acceptance, 2026-10-05

Accepted complete pinned contracts: H034 external Bitwarden/1Password sources,
H078 owner quick commands, H256 unreadable configuration recovery. Donor commit
59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e; MIT attribution is in adapted modules and
`docs/hermes/licenses/hermes-direct-ports-MIT.txt`.

H034 is available through `nerva secrets`, encrypted bootstrap storage, and the
real hub SecretBroker factory. Approved kernel injection resolves sources;
revocation, cache/session expiry and background/no-prompt refusal are covered.
Bitwarden region also applies to candidate-token verification. 1Password child
calls disable biometric unlock and disk caching. No raw token/value is printed
by setup/status/sync, stored in .env, or injected into the parent environment.
Provider responses and installation archives are synthetic, not live evidence.

H078 enters CommandRegistry before the model. Built-ins win, aliases recheck
access, cycles/limits fail closed, literal exec does not interpolate chat args.
The existing terminal ToolRPC creates a durable task; signed human approval and
kernel authorization precede physical execution. /bin/pwd verifies the signed
cwd and synthetic printf verifies output redaction before result persistence.

H256 validates YAML and settings SQLite/JSON before startup/writes. Running
reads preserve last-good policy; fresh reads refuse unavailable policy. Corrupt
bytes are copied privately without following planted links, warnings deduplicate
by path/mtime/size, and already-initialized hubs revalidate persisted settings.

Verification is cumulative, with RED evidence retained: the initial affected
batch had 615 cases/one failure (generic redaction masked a valid cwd). The
final correction batch has 207 cases, zero failures/errors/skips; it corrects
that regression without weakening the cwd assertion. The separate lifecycle/
ntfy impact batch has 248 cases, zero failures/errors/skips. Counts overlap and
must not be added. Initial inputs and current source hashes are separate.

Five existing reviews receive bounded impact updates: H063/H099 retain their
accepted contracts after healthy behavior probes and startup/broker diff review;
H515/H595/H660 retain partial status, since their producer bodies are unchanged by
the localized terminal redaction diff. Other stale reviews are not restamped.

Raw scanner findings are disclosed in report.json: Bandit six LOW and one MEDIUM
controlled pinned-HTTPS download call; Gitleaks one inherited empty GA4 setting
declaration (verified by AST). The artifact scan also matches six public SHA256 source digests; these are not
credentials. No scanner baseline/rules were weakened. Full
backend/frontend and H277 mutations belong to the next integration milestone;
older suite results do not verify this final snapshot. No publication occurred.
