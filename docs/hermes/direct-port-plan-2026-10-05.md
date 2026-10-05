# Direct Hermes capability ports

Goal: all 697 pinned Hermes capabilities, including H277. Local only; no staging,
commit, push, merge, deployment, paid provider or live account activation.
Base/head: a7ffad6676cfb28e7ac374d495b4a5889e5f4646. Generated 2026-10-05.
Prior goal turn made verified progress: governed native workspace clarification,
801 affected functional cases; H067 remains partial. Metadata currently has one
stale H660 source pin, to review without changing the original partial verdict.

Two independent implementation units, at most two Sol High implementers, no
child delegation. Prefer direct adaptation of pinned Hermes59b2aeef6c7a source.

1. H256: adapt config parse-failure recovery and write refusal to agents.yaml
and settings.db. Preserve last-known-good policy on running reads, snapshot
corrupt bytes securely, warn once by source signature, refuse fresh startup or
writes when policy cannot be read. Agent owns config.py, settings_db.py, a new
config_read_errors.py helper and focused new tests. No permissive default on
unreadable persisted policy and no resetting the corrupted source.
2. H034: port Bitwarden/1Password SecretSource adapters and owner CLI management.
Agent owns security/secret_sources/, secret_broker.py, a new CLI secrets module
and focused new tests. Root owns main CLI/orchestrator wiring. Map references
through existing encrypted storage; raw secrets never enter .env/audit/model
context. Owner-held sessions expire and background reads never unlock or prompt.
Provider commands and API transport are synthetic in tests; no live activation.

Root reviews compatibility/security and integrates existing entry points. Run
focused behavior tests after each implementation; one affected batch after
integration. Broader suites only for demonstrated cross-module risks, with one
final milestone run. Count equivalence only against the complete row contract;
no scaffolding credit or softened requirements. Reuse donor conformance tests.
Preserve all inherited dirty work. Immediate preimages are external at
/tmp/nerva-direct-port-baseline-20261005; rollback is localized reverse diff.
MIT attribution accompanies adapted modules. Root alone edits assessment/evidence.

3. Root H078: adapt Hermes gateway quick-command mapping and alias expansion into
existing pre-model CommandRegistry. Source general.quick_commands in agents.yaml;
built-ins retain precedence, owner-only custom commands, bounded alias recursion
and no input interpolation into shell literals. Exec delegates to existing
registered terminal_run ToolRPC, with existing target/denylist/approval/kernel
controls and redacted output. Root owns commands.py, a new quick_commands.py
and focused new tests. This is separate from agent-owned configuration recovery
and secret-source modules; no direct subprocess or fresh execution bypass.

H078 final output verification: reuse existing SecretRedactionFilter in the registered terminal handler before recording terminal observations or returning a durable worker result. Root additionally owns the localized terminal handler change in autonomy_coordinator.py; no global redaction or task-schema rewrite.

Execution ledger: H256 initial runtime-error swallow and initialized-store/invalid-opts/disappeared-YAML regressions reproduced then corrected. H034 actual main CLI plus hub component factory and kernel quarantine injection integrated. H078 actual signed approval→worker→physical terminal and pre-persistence output redaction verified. Agent H034 stopped after capacity errors with files preserved; root owns the final review/corrections. No publication.

Checkpoint: H034/H078/H256 complete locally; registry128/697. Initial615 includes one terminal cwd regression; final207 and impact248 pass. H595 terminal-only impact also preserves partial, without refreshing unrelated stale records. Active app objective updated by owner. No publication. Next started batch: H067 producer/transport completion.
