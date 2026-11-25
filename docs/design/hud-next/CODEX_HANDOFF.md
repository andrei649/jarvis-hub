# HUD redesign — handoff to Codex

| Field | Value |
|---|---|
| Generated | 2026-11-25 11:40 local (UTC+2) |
| Goal | Take over the HUD redesign (themes, phase A and phase B) and bring it to a publishable state |
| Worktree | `C:\dev\jarvis-hub\.claude\worktrees\hud-redesign` |
| Branch | `claude/hud-redesign` |
| Base and head SHA | `77d6db88` for both: nothing is staged or committed |
| Working tree | 355 changed paths (243 modified, 26 deleted, 86 untracked); 299 of them outside the built bundles |
| Built bundle | `agents/web/v2/index.html`, built 11:22:24, SHA-256 `FACFFD06…2E14B6`, entry `assets/index-PRAZa8uN.js` and `assets/index-Dq-NCigC.css` |
| Next action | Step 1 of "What to do next" below |

The previous agent (Claude) was stopped by the owner on 2026-11-25 at about 11:30, in the middle of a
repair. Nothing is running: no test server, no build lock, no browser. Only the read-only preview
server on port 4180 is left, and it belongs to the Claude session.

## Update, 2026-11-25 afternoon

The work is now committed and pushed: commit `82f03d5f` on `claude/hud-redesign`, draft PR #1386
into `main`. The branch is stacked on the 10 commits of draft PR #1380
(`codex/harness-agent-selector`). The owner decided **not to merge yet**: #1386 stays a draft until
#1380 lands and CI is green.

Findings after publication (the owner's check on commit `82f03d5f`, Chromium, synthetic data):

- **Step 1 below is done.** The Classic docket repair works: all four Chromium tests for Obsidian and
  Graphite, in Romanian and English, pass. At 1100×800 the first line stays in view; the whole
  signature still needs a 21px scroll in English and 62px in Romanian (already listed as open).
- **Demo mode shows live hub data in the run foot.** With `?demo=1`, the foot's "Channels • N of N
  running" and "N sessions in the last 15 min" come from the hub and carry no "Demo sample" label,
  while the rest of the page is labelled demo. A synthetic answer with 41 sessions and a fictitious
  channel appeared there. Fix this before any screenshot is shared publicly: in demo mode the foot
  must draw seeded values with the demo label, or draw nothing.
- **CI on #1386:** four checks fail — `test (ubuntu-latest)`, `hud-v2-build`,
  `SAST (bandit — blocking gate)` and `vault-containment`. The same four fail on #1380, so part of
  this is inherited from the base. The redesign itself adds 10 lint problems. Read the check logs
  before changing anything; `hud-v2-build` compares the committed bundle with a fresh build.

## What the owner decided

- Ledger is the default look. Every screen follows Ledger's style.
- All seven directions are installed as themes, switchable in Settings → Personalisation. Classic
  (Obsidian, Graphite) is kept. That gives nine looks and 16 look-and-scheme pairs.
- The old brand book is not binding. The fonts Literata and Barlow are approved and already in the repo.
- `PHASE_B_PLAN.md` §12 item 10: the H686 estimate and the H430 recall line stay in Turn details.
- §12 items 11 and 12 are defaults the owner may change: the recipient question stays when a reply
  ends, and a voice turn while a question is open goes to the current recipient.
- Clearing the 35 leaked fixture cards in the approval queue is the owner's decision. Do not clear them.

## Where the truth is

- `docs/design/hud-next/PHASE_B_PLAN.md` — the plan. Line 7 is the status note; §12 lists the decisions.
- `docs/design/hud-next/PHASE_B_INTERFACES.md` — the contracts between the parts (§6 requests, §7
  register inset, §8b).
- `docs/design/HUD_V2_REMAINING.md` — the ledger of what is open.
- `frontend/src/theme/CONTRACT.md` — theme contract v1 (`--n-*` roles, `[data-look][data-scheme]`).
- `frontend/e2e/ledger-shots.spec.ts` — the render matrix and its gates. Its header describes each gate.

These three docs describe the 09:32 build. They are one small change behind the tree; see the next section.

## State of the tree

### Verified on the 09:32 build (bundle SHA `F024B896…`)

A full gate ran on that build and passed:

- TypeScript: frontend, mobile and e2e typechecks, 0 errors.
- Vitest: 442 files, 5,023 tests, all passed.
- Render matrix (`ledger-shots.spec.ts`): 507 tests passed, 523 records, 0 failed gates, 93 minutes.
- Playwright: main-lane specs on the fixture hub 47 passed; Home lane 49 passed; fixture-backed lanes
  47 passed; routing 6 passed and 4 skipped by design; base path 16 passed.
- Pytest: the 11 HUD-related files, 153 passed; `tests/test_hud_v2_parity.py` and
  `tests/test_codeql_posture.py`, 27 passed.
- `frontend/scripts/generate-desktop-routes.mjs --check`: current.

An independent check on the same round confirmed:

- The area page no longer draws its own frame in the card looks. The page title sits on the page
  ground and the registers stay cards, with no card inside a card. Covered: 14 pages, 10 card
  look-and-scheme pairs, English and Romanian, seven widths from 320 to 2560.
- In Classic, the docket's signature is whole inside the docket body at 1280×800, 1340×900 and
  1440×900 (192 cases).
- Ledger, Briefing and Presence are unchanged from the previous build (432 pairs; differences are
  render noise only).

### Changed after that gate, and not verified in a browser

At 11:20–11:22 a repair changed three files and rebuilt the bundle:

- `frontend/src/docket/Docket.tsx` — `signatureScroll(view, signBottom, firstLine)` now scrolls the
  docket body only by the blank space above the body's first drawn line (about 12px; 9px in compact
  density). If the signature needs more, it does not scroll at all. A new helper `firstLineTop` finds
  that first line.
- `frontend/src/docket/Docket.signature.test.tsx` — tests for the above.
- `frontend/e2e/ledger-shots.spec.ts` — the `docket-sign` gate was extended for the state line at 1100×800.

What was run on this last change: `npx tsc --noEmit` passed, and the full Vitest suite passed
(5,025 tests). What was not run: the render matrix and every other Playwright lane. The new
`docket-sign` checks have never been run to completion, neither red on the old bundle nor green on
the new one.

The defect this repair targets: in Classic (Obsidian, Graphite), English demo, fresh load at
1100×800, the docket scrolled itself 21–22px and cut the line "Demo sample — signing is disabled."
under the register head's rule.

## What to do next

1. **Check the last repair in a browser.** Run the Home group of the matrix on the current bundle
   (the tests whose names start with `sec-heads-home-`), then the Home lane. Expected: `docket-sign`
   and `docket-1280` pass in all 16 pairs; the docket body is not scrolled at 1100×800 in Classic;
   Classic Romanian at 1280×800 still scrolls about 4px with nothing cut. If it fails, the simplest
   safe fallback is to make `signatureScroll` return 0 always and accept the open item
   "signature below the view" listed under Classic below.
2. **Bring the three docs up to date** for that change: `HUD_V2_REMAINING.md`, `PHASE_B_PLAN.md`
   line 7 and `PHASE_B_INTERFACES.md` §7 still say the body scrolls 21px in Classic English at 1100×800.
3. **Refresh the status counters.** In `project-status.json`, `tests.frontend` is 4998 and must
   become the current Vitest total (5,025 if step 1 changes no tests). Backend stays 37707 and mobile
   535 unless you change them. Then, from the worktree root with the 3.12 venv:
   `python scripts/status_sync.py --reuse-test-counts`, then
   `python scripts/status_sync.py --check --reuse-test-counts`.
4. **Decide what to do with the open items below.** None of them blocks a functional HUD.
5. **Publication is a separate lane.** Nothing here authorises a commit, push, PR or merge; follow
   `AGENTS.md`. If the Hermes ledger rows drift after touching `orchestrator.py`, `web.py` or
   `telegram.py`, re-pin them in the same change.

## Open items

### Introduced by this work

- **Projects (Work › Projects), every card look:** the legacy Kanban section
  (`section.nerva-kanban`, `panels/kanban/kanban.css`) is filled with `--n-bg`, which now equals the
  page ground. Its inset well is gone and its content floats about 38px in from the page title with
  no visible container. It is readable. Fix in `kanban.css` or with a kit hook.
- **Classic, Romanian and English, 1100×800:** part of the signature lies below the docket body's
  view at first paint (62px in Obsidian Romanian). The plan promises the signature whole only at
  1280×800 and from 1340px wide.
- **Classic English at 1280×800** fits with about 1px to spare.
- **Trust's emergency-stop sheet** still wraps "WOULD / HALT" in Classic: that sheet does not opt in
  to `--n-term-max`.
- **Owner's own data in the docket** is not covered. A live entry with a long three-line title and a
  typed sign line in Classic Romanian at 1280×800 gets no scroll, so its signature may be below the
  view. The gates use only the demo sample and 128 one-click entries.
- **About 20 new three-word wraps:** the docket foot's "Lucru › Decizii" at 1100 and 1280 in
  Romanian; Health and Observe stat labels at 760–1100 in Classic.
- **Matter of taste:** the register head rule and row hairlines stop at the inner margin, unlike
  phase A's `.n-card`; the scrollbar sits inside the frame.

### Older, still open

- Atlas, Briefing and Presence in Romanian: the terms "Dacă semnezi / Ca să anulezi / Dacă aștepți"
  break onto two lines in the 74px column (only Classic was widened).
- Timeline's source reasons at 320px in Classic run past the column.
- Trust › Capabilities at 320px: the marks touch "Modify" and "Persist".
- The floating window's compositor line starts with ":" about 8px from the edge; its Romanian
  controls take two or three rows.
- "More in Home" sits at the day card's outer edge; the day head wraps.
- Ledger Romanian at 2560: the docket buttons wrap.
- The demo weather is in English in the Romanian UI.
- `useCutTitles` rarely fires; Work's 2×2 registers do not use `useHeadRow`.
- The drag handle does not meet WCAG 2.5.3 (label in name).
- The native notification and the tray menu are English only.
- The Romanian copy has had no native review.
- Two bundle chunks are over 500 kB (`index-*.js` about 930 kB, `gap-*.js` about 956 kB).
- BACKLOG H18.x rows are not updated for this work.

### Gaps in the gates

- `area-frame` does not measure the page title's alignment with the registers' edges, and its walk
  covers only 1920, 1280, 760 and 390.
- The matrix's page shots cover only Ledger and Classic Obsidian. The card looks (Atlas, Console,
  Threshold, Workbench) are covered by the group walks, not by page shots, so check them by eye.
- Card looks were not checked at compact or comfortable density.
- The spec writes its PNGs and `report.json` relative to the current directory, into
  `frontend/e2e/artifacts/ledger` (git-ignored). Stale files from several runs are there.

### Never run

CI, Firefox, WebKit, a real device, the native app, `serve.py`'s own main lane, and the owner's
screen (2560×1353 CSS px at 1.5×).

## How to run things on this machine

- **Python:** `C:\dev\jarvis-hub\.venv\Scripts\python.exe` (3.12.16). Set `PYTHONDONTWRITEBYTECODE=1`.
- **Node modules:** the worktree uses the main checkout's `node_modules`. Run `npx` from `frontend/`,
  never from the worktree root (from the root it downloads packages from npm).
- **Build:** `npm run build` in `frontend/`. It rewrites `agents/web/v2` and `agents/web/workspace`.
  A Playwright run counts only if `agents/web/v2/index.html` keeps its modification time through
  the run, so never build while a browser run is in progress.
- **Playwright:** no `playwright install` was done. Use the cached Chromium (headless shell 1228)
  through `executablePath`, and set `NERVA_TEST_PYTHON` to the venv python.
- **Render matrix:** about 95 minutes serial for all 507 tests. Use a `--grep` on the group you
  touched while iterating, and run the whole matrix once at the end.
- **Known noise on Windows:** six backend tests are red at HEAD on this machine (file modes, symlink
  privilege, one taint test). CI is Linux.
- **Do not** start `serve.py` or touch port 8080: the owner's hub runs there. Do not send POST or PUT
  to the live hub during QA.

## A warning about process

After phase B was functionally complete (2026-11-24 07:32), six polish rounds took about 28 hours.
Each round ended with an independent verifier told to look for problems across 16 look-and-scheme
pairs, two languages and seven widths; it always found something, every finding was treated as
blocking, and each fix added code that the next round had to verify. Do not repeat that. Decide in
advance which sizes and looks are promised (the plan names them), fix only what breaks a promise,
and record the rest in `HUD_V2_REMAINING.md`.
