# Hermes in Nerva: features, not rows (proposal, 2026-11-10)

The owner asked why the Hermes work runs row by row, and to treat Hermes capabilities as
features Nerva needs, reusing code from both projects. This is the rethink, with numbers
measured on Hermes `9c0560f8` (2026-11-10) and this branch.

## What the numbers say

- **Hermes is not light.** It has about 1.08 M lines of Python without tests (agent 154 K, tools
  132 K, gateway 135 K, hermes_cli 318 K, plugins 91 K) and 1.6 M lines of tests. Nerva has
  359 K and 457 K. Hermes also moves fast: the ledger pins 59b2aeef (October), the runtime pins
  0808ed8, and upstream is already well past both.
- **Very little is actually missing.** Of the 697 rows, 148 are `equivalent`, 436 `partial` and
  58 `missing`. Most `partial` rows already work. They fall short on a sentence of a frozen contract.
- **The cost is mostly verification, not building.** Every row pins file hashes. Each merge
  re-opens every row citing a changed file: the H400 merge alone re-opened 338 rows. Each row
  also gets 2 to 6 adversarial review rounds. That tax repeats on every merge and grows with
  the codebase.
- **Nerva can already run all of Hermes.** `agents/core/hermes_runtime` (PR #1233) provisions the
  pinned upstream engine as a sidecar. Every RPC and tool call crosses Nerva's Action Kernel
  (251 methods classified, unknown methods fail closed), and approvals land in the Nerva inbox.
  The ledger deliberately gives that no credit (`RUNTIME_INTEGRATION.md`: "runtime-backed
  availability and native equivalence must be tracked separately"), and nothing tracks the
  availability side.
- **Much of Hermes can be reused as code.** Of the 45 Hermes tool modules that register tools,
  23 import five or fewer other Hermes modules. Of the 41 plugins with a `register()` entry point,
  32 do. Leaf tools such as `todo` and `clarify` need only three or four. Core modules (files,
  delegation, cron, session search) are tangled with `hermes_state`, `hermes_cli.config` and the
  gateway, and are not worth copying.

## The proposal: three lanes, chosen per feature

Group the 697 rows into the ~20 feature areas the ledger already has, and put each area in
one lane.

| Lane | What it means | Areas (rows) |
|---|---|---|
| **Own** — native Nerva | Nerva's edge; Hermes is a reference, not a source | security 34, memory 27, agent-core 36, automation 32, config 18, env 28 |
| **Adopt** — Hermes code inside Nerva | copy low-dependency Hermes modules with MIT attribution under `agents/vendor/hermes/`, loaded through a small compat layer | tools 32, skills 33, media 27, providers 27 |
| **Run** — the governed Hermes sidecar | use the pinned engine through the existing kernel-mediated bridge; bump the pin, don't re-implement | platforms 39, gateway 33, acp-mcp-dev 33, web 40, rest-api 33, and the Hermes-only CLI, TUI and desktop surfaces (cli 56, tui 25, desktop 54) |

### Adopt: the compat layer

A small `agents/vendor/hermes_compat/` package provides the handful of Hermes interfaces the
leaf modules import:
- `tools.registry.register(name, toolset, schema, handler, check_fn)` maps onto
  `ToolRPCServer.register_tool` with a risk tier from a server-owned table;
- the plugin `ctx`: `register_tool`, `register_hook`, `register_command`,
  `register_memory_provider`, `register_platform`;
- `agent.redact` maps onto Nerva's redaction filter;
- config reads go to `settings_db`.

Vendored files keep their upstream text. A sync script (`scripts/hermes_vendor.py diff|pull`)
shows the upstream diff for each vendored file, so an update is reviewed as a diff and not
re-derived. Every adopted tool still crosses the kernel like a native one. Hermes's 185
skills use the SKILL.md format that Nerva's skills loader reads, so they need an import pass
rather than a port.

### Run: make the sidecar a product feature

- Bump the runtime pin to current upstream and automate the bump: download, verify, diff the
  RPC catalog, and fail closed on new methods until they are classified.
- Track **governed availability**, a second number: a capability counts when a smoke test
  shows it working end to end through the bridge, with the kernel in the path.

### Own: finish by feature, not by sentence

Each area gets one acceptance suite of behaviour tests: what the owner can do, and what an
attacker cannot. It is reviewed once per area merge, not once per row. Evidence is the
suite passing, not file hashes, so a merge that moves code does not re-open anything.

## What changes in the bookkeeping

- The scoreboard becomes per feature area, with a lane and a status: `available (native)`,
  `available (adopted)`, `available (sidecar)` or `missing`. The 697 rows stay as the
  checklist inside each area; they are not each a unit of review.
- Hash-pinned evidence and restamping are retired. They are the main cost and protect little
  that a behaviour test does not.
- Adversarial review stays for security-sensitive areas (approvals, memory writes, execution,
  delegation, credentials) and for any adopted module that touches them.

## Decisions for the owner

1. Count runtime-backed (sidecar) and adopted-code capabilities as delivered. This reverses
   the rule in `RUNTIME_INTEGRATION.md`.
2. Take Hermes's own CLI, TUI and desktop surfaces (135 rows) out of "native" scope; Nerva's HUD
   and `nerva` CLI cover the same jobs.
3. Retire hash-pinned evidence and per-row restamping in favour of per-area acceptance suites.

## First steps once approved

1. The compat layer, plus adopting three leaf tools and two plugins end to end with kernel
   gating, to prove the lane.
2. Bump the runtime pin to current upstream, with the automated catalog diff.
3. Replace `hermes_status.py`'s headline with the per-area scoreboard.
