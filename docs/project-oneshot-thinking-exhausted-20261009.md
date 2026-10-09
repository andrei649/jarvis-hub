# One-shot CLI thinking-exhaustion outcome

- Generated: 2026-10-09 UTC.
- Base: 23c435caaa63a14efb9d16a9a86bee56ad24b494.
- Branch/worktree: codex/oneshot-thinking-exhausted-20261009,
  /workspace/jarvis-hub-oneshot-thinking-exhausted.
- Goal: an explicit no-visible-answer backend reply must not be one-shot success.
- Delivery: local; draft PR #1247 remains a separate published unit.
- [Contract and rollback](plans/2026-10-09-oneshot-thinking-exhausted.md).

## Behavior and bounds

The CLI refusal table contained a comment naming THINKING_EXHAUSTED_REPLY but
no entry. Its exact backend string and one fixed reason now use the existing
sanitized containment classifier. Direct replies, specialist wrappers and
control-padded forms make nerva chat -z return 1, keep stdout empty, emit the
reason on stderr and persist status refused/completed false. One request remains
one request; the CLI does not retry, approve or dispatch another action.

Interactive chat keeps its printed response and exit 0. Its optional receipt
truthfully records that this exact reply was not a completed answer. Normal
answers, other exit codes and the existing approval path are unchanged.
The literal copy preserves stdlib-only CLI startup; both drift guards import
the actual backend constant only in tests.

Root's AST comparison verifies the sole production difference is this one table
entry. Every function, import, class and other module statement is unchanged.
The inherited containment rule can also refuse an answer quoting the sentinel;
that existing conservative tradeoff remains documented. Model-rephrased or
mixed outcomes are not classified by this change. A raw responder exhausting
its budget does not prove a later synthesizer failed; no such notice or inference
is introduced. There is no backend, router, schema, HTTP, web/native, pricing or
usage-collection change. H002 remains partial.

## Verification

Before the entry was added, six selected cases failed as expected: four command/
receipt cases and the two extended drift guards. Afterward the writer's six-file
CLI union has **274 passed, one skipped**, 275 total, zero failures/errors
(5.398 seconds). It includes all 55 one-shot cases, CLI commands, import, send,
chat images and image-retry CLI coverage.

Root's four-file union passes **79/79**, zero failures/errors/skips
(2.618 seconds): send, chat images, the backend thinking-exhaustion producer and
pending-approval transport. It overlaps the writer's union by 55 cases, yielding
**299 distinct cases: 298 passed and one skipped**. The skip is the existing
live GitHub Hermes import smoke gated by NERVA_HERMES_LIVE; no live import was
requested or run. Ruff and whitespace checks pass. Python -S -m agents.cli.nerva
--help exits 0 with site-packages disabled; runpy emits its module-already-loaded
warning because the CLI package imports the module before the -m execution.

Canonical collection records 21,278 backend cases (+4), unchanged frontend/native
2,009 and mobile 306 inventories, and 555 routes. Hermes/generated-status and
whitespace checks pass. The prior complete backend milestone at source
efac393a1219c8b87478fd694af7cd01334c9ae7
has 21,237 passed and 37 skipped. That earlier result is not a newly executed
full suite for this change. The exact table-only delta is verified by the CLI
and adjacent producer/approval suites above; unchanged backend and client suites
are not repeated. No real model, provider, device or GPU was used.

## Review and evidence freshness

One gpt-6-sol/high writer and a second independent reviewer handled source and
regression review; no Critical/Important finding remains. A gpt-6-luna/medium
read-only inventory compares the exact base hashes. Root verified the AST and
reviews and owns integration/metadata/git. No nested delegation.

Named collateral reviews support **19 previously current pin refreshes**:
18 CLI pins and the H002 one-shot test pin. All **35 previously stale pins stay
stale**, including H002's whole-file CLI pin. The eight H586 CLI coordinates
below the insertion move by three lines; root verifies each still points to the
identical source line. Other current coordinates remain unchanged. No status
is promoted.

Only H002's semantic claim text is updated, plus H586's source coordinates.
The obsolete missing-sentinel statement is removed and the one-shot test count
is 55. Two stale explanations are narrowed to what the current CLI actually
does: its receipt still leaves per-turn usage fields null, without assertions
about old cost-tracker internals; it still echoes only a supplied session ID,
even though the HTTP response now returns the actual ID. These are remaining
CLI gaps, not new attribution or session-continuity work. Other claim text and
all statuses are unchanged.

Tested source SHA-256:
- agents/cli/nerva.py: 2395c1bae1192dc073bae79a632a3155de1322d77ac50a7d03696b856f07a19f
- tests/test_nerva_oneshot.py: f4eaf73c5c5442bbc6047d8e87f36f9d6cff546b0be3e139170724522336f508

Scratch evidence: oneshot-thinking-exhausted-{red,green,integration}.{xml,log},
oneshot-thinking-exhausted-stdlib-help.log,
oneshot-thinking-exhausted-status-sync.log,
oneshot-thinking-exhausted-pin-inventory.{json,md},
oneshot-thinking-exhausted-{review,collateral-review}.md and
oneshot-thinking-exhausted-ast-review.json.
