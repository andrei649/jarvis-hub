# Decision: REA (morluto/rea) is not adopted to reverse-engineer Hermes/OpenClaw or to rewrite Nerva

> **Status: assistant verdict, 2026-10-20 (evaluate-external-tool).** Not an owner ratification.
> Installing REA into the agent loop would be an owner decision under any outcome (point 3).

## The proposal

Use [REA: Reverse Engineer Anything](https://github.com/morluto/rea) (MIT, `rea-agents` on npm;
read at `c374c2f`, 2026-10-20) to reverse-engineer Hermes and OpenClaw, then rewrite Nerva as a
better solution.

## What REA is

REA is an MCP server plus agent skills. It drives Hopper, Ghidra and IDA for native binaries, and
it also analyses JavaScript/Electron and .NET apps and websites, **for software whose source you do
not have**. `npx rea-agents setup` registers it with the agent's client configuration and installs
workflow instructions (`src/application/Setup*`, `ClientConfigurationDocument.ts`). Its
`DISCLAIMER.md` names "copying proprietary software or reproducing its protected code" as a use it
does not support.

## Verdict: no value for this goal

1. **We already have both sources, so there is nothing to reverse-engineer.** Hermes is
   open-source (MIT runtime). This repo already holds:
   - a pinned Hermes commit (`agents/core/skills/importer.py`, `HERMES_PIN_COMMIT`);
   - a source-level inventory (`docs/research/hermes-inventory-v2026.8.31/`);
   - the 697-row capability ledger compared against that source (`docs/hermes/assessment.json`).

   OpenClaw is open-source too (`openclaw/skills`), with a feature analysis in
   `docs/research/2026-06-05-openclaw-feature-analysis.md`. Binary-level analysis of software
   whose code we can read only loses information.
2. **The bottleneck is building, not understanding.** As of 2026-10-20, a triage of the 429
   open partial rows found:
   - 78 closable with S/M work;
   - 122 closable with L/XL work;
   - 229 blocked on hardware, live accounts, protected paths or owner decisions.

   None of them is blocked on not knowing how Hermes does something. The per-row "remaining" text
   already names the concrete gap.
3. **Install shape.** `setup` writes MCP and skill configuration into the agent client. Under
   `selfdev-policy.json` / `AGENTS.md`, anything that writes `.mcp.json` or `.claude/**` runs
   inside the loop that authorises unattended merges, so it is an owner decision, never an adopt.
4. **A rewrite contradicts the plan of record.** Nerva has ~26k backend tests, the Action Kernel,
   the security posture and a ledger that measures equivalence row by row. A rewrite would reset
   all of that. The roadmap (`docs/NERVA_2_ROADMAP.md`) and the Hermes strategy in
   `NERVA_VISION.md` (criteria S1–S8, "superior to Hermes") are incremental, and the rows
   are being closed with adversarial verification on PR #1249.
5. **Licence and posture.** Hermes' MIT licence already allows reading and adapting the code with
   attribution, and the four Anthropic-termed skill subtrees stay excluded
   (`2026-09-01-hermes-evaluation-scope-and-anthropic-skill-terms.md`). REA adds nothing there.

## Where REA could fit later

It could fit if Nerva ever needs to interoperate with a **closed** binary or app that has no
public source (for example a vendor's desktop client a channel adapter has to talk to). That would
be a fresh, scoped evaluation, run outside the self-dev loop, with owner approval for the install.
