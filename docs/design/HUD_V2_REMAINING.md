# HUD v2 — Remaining work (next PR)

## The HUD's structure: the Ledger frame (Phase B, 2026-11-24, branch `claude/hud-redesign`, not merged)

The HUD v2 shell is deleted: the top bar with its badges and 40px clock, the scrolling ticker and
"ALL NOMINAL", the sixteen-mode rail with its phone drawer and tabs, the roster and context
columns, the command palette with its globe menu, Ambient, the Console overlay and the fixed
CONSOLE and WORLD buttons. Every theme now draws one structure, the **Ledger frame**
(`frontend/src/frame/`; specification `docs/design/hud-next/PHASE_B_PLAN.md`, interfaces
`docs/design/hud-next/PHASE_B_INTERFACES.md`):

- **Masthead:** nine areas (Home, Work, Agents, Memory, Trust, Build, Connect, Observe, Settings)
  with their attention notes, **Search or run a command · Ctrl K**, EN | RO, the scheme toggle,
  Glance and **Stop all agents** (one click; resuming is only on Trust › Emergency stop, typed).
  From 1100px the row measures itself and gives up words in a fixed order (every word stays in the
  control's name and tooltip); below 760px the areas open as a drawer.
- **Running head:** six signals (egress, local route, microphone, model, data on screen, audit
  chain), each with its basis and the time it was checked, then the approval mode (a stricter mode
  is one click, a looser one two steps, also when the mode is folded into a button) and the
  interrupts; from 1100px it is one line that measures itself and gives up words in a fixed order
  (each stays in the item's name, title or popover); below 760px it is one line of marks.
  **Running foot:** agents by exception, the machine's meters (from 1680px), the channels and
  sessions (at every width; below 2200px the session count without its window), the version.
  **Notices** sit under the head; the demo notice gives the sample's address (`/v2/?demo=1`).
- **Home** (`/v2/cockpit`) is Today in three registers: **the day** (a verdict computed from real
  readings, today, while you were away), **the conversation** (a multi-line composer with To, Mode,
  Attach, Voice, Options and Send; the working reply shows only what the chat stream reports) and
  **the docket** (the blocked requests, signed with friction by risk tier: one click, two steps or
  a typed phrase; no key ever signs). At 2200px and wider a fourth register shows the agents by
  exception and the record's newest entries.
- **Ctrl K** finds every area, page and Console panel, every agent ("Open …" and "Write to …") and
  the read-only actions; the HUD v2 palette's appearance rows keep their words. It never signs,
  rejects, defers, stops or changes a mode.
- **Routes** are unchanged and four are added (`/v2/work`, `/v2/timeline`, `/v2/artifacts`,
  `/v2/glance`). `/v2/console` is **All pages**, a site map; `/v2/console/<id>` is that panel as a
  page of its area, beside the area's contents column; the World page was removed on 2026-11-25; Glance
  replaces Ambient (`a`); Cinema (`m`) keeps the mesh, the orb and the wall. The number keys follow
  the masthead.
- **Retired for honesty:** the cockpit's cognition trace and its live scoring subscription (stages,
  timings and routed agents the chat stream does not report; `GET /api/cognition/stream` is still
  served and the parity gate lists it as uncalled), "ALL NOMINAL", "EGRESS SEALED" and the bare
  "% LOCAL" figure.

*Verified 2026-11-25 by the final gate after the final round, on the final build.* The bundle in `agents/web/v2`
and `agents/web/workspace` is this gate's `npm run build` of 2026-11-25 09:32:17 (Vite 8.3.6; entry
`assets/index-lG61P7Tc.js` and `assets/index-Dq-NCigC.css`, with `assets/pages-HdAx9YSN.css`; 46 asset files,
3,576,605 bytes; `index.html` SHA-256 `F024B896…A039836524`). The gate rebuilt once, under the shared build lock,
for its one product change (`frontend/src/docket/Docket.tsx`, the docket's first-paint scroll; *Fixed in the final
round*, below): against the build step's bundle of 09:10:27 (`index-Ct8IRirK.js`, byte for byte the final round's
own build of 08:24:25) only the main chunk differs (20 bytes shorter) and 14 lazy chunks are renamed at the same
sizes; every stylesheet is the same file. An adversarial verifier was reading the worktree and running its own
browser on other ports at the same time, so its runs overlapped this rebuild. Before the runs below no file under
`frontend/src` or `frontend/e2e` was newer than this bundle apart from the lanes' own output; the newest source is
`frontend/src/docket/Docket.signature.test.tsx` and the newest spec `frontend/e2e/ledger-shots.spec.ts` (both this
gate's, written before the build). What ran on these sources and this bundle:

- **Types:** `npx tsc --noEmit` in `frontend`, `npx tsc --noEmit -p .` in `mobile` and
  `npm run typecheck:e2e`: no errors (TypeScript 7.0.2), before and after the gate's change.
- **Vitest,** the full frontend suite (`npx vitest run --reporter=dot`): 442 files, 5,023 tests, all passed (346 s); the two more than before are this gate's, in `src/docket/Docket.signature.test.tsx`. On the build step's sources,
  before the gate's change, it had passed with 442 files and 5,021 tests.
- **pytest:** `test_hud_v2_parity`, `test_design_manifest`, `test_pwa_v2`,
  `test_appearance_preferences`, `test_route_parity_guard`, `test_openapi_parity_guard`,
  `test_route_auth_matrix`, `test_web_base_path`, `test_h12_5_autonomy_dryrun`, `test_observer_since`
  and `test_codeql_posture` (`-q -o addopts="" --timeout=300 -p no:cacheprovider`): 153 passed.
  `node --experimental-strip-types frontend/scripts/generate-desktop-routes.mjs --check`: the native route
  list is current (exit 0). Both ran before the rebuild; after it, and after these documents were written,
  `test_hud_v2_parity` and `test_codeql_posture` ran again (27 passed), and so did
  `npx vitest run src/test/hud-p3-2-reconciliation` (3 passed).
- **The render matrix** (`frontend/e2e/ledger-shots.spec.ts`, every gate: `sec-heads`, `register-inset`,
  `area-frame`, `docket-1280` and `docket-sign` among them): 507 tests passed in 1.6 hours (93 minutes, slowed by the verifier's runs and this gate's other lanes on the same machine). `frontend/e2e/artifacts/ledger/runs/gf-20261125-093223` holds 523 records with 0 failed gates (`report.json`: that run, 523 shots, failed `[]`). One walk reloaded a page once, as the matrix's `mounted()` does and records (`area-frame-threshold-dark-ro`; a second miss fails); it passed. Its gates, records each, none failed: overflow, page scroll, minimum font, contrast, console, external requests and the running head 255 (every page shot); masthead 237; `sec-heads` 319 and `register-inset` 319 (the 255 page shots and the group's 64); `area-frame` 248 (the 216 area-page shots and its own group of 32, whose every record found 64 area columns, 8 pages at 4 widths, live and demo, drawn with their top rule only; in the card looks the registers in them are cards from 760px, none inside another, and none is framed at 390px); `docket-1280` 3; `docket-sign` 32 (448 measures of the open entry's sign line and first line, in the walk at 1280×800 and 1440×900 and on fresh loads at 1280×800, 1340×900, 1440×900, 390×844 and 1100×800, demo and 128 entries; the docket's body was scrolled in 6 of them, 3–4px in Classic in Romanian at 1280×800 and 21px in Classic in English at 1100×800, each time the whole entry and its signature then in view); masthead-fit 42, runhead-fit 28, runhead-held 16, runhead-marks 16, runhead-popovers 6, runhead-window 12, runhead-surroundings 28, runfoot-phone 20 and frame-ellipsis 32. `register-inset` held, in the page shots, 2,906 texts, 322 controls and 11 totals in 90 framed registers (Classic · Obsidian, 52 shots; the nearest 16px from each edge) and found the 180 ruled ones unpadded; in the group's walks 73,869 texts, 10,805 controls and 780 totals in 2,120 framed registers (the nearest 8px, the 760–1099px cap) and 2,040 drawn with rules, none framed below 760px. `sec-heads` measured 93 section heads, 270 register heads, 33 totals and 57 rows of heads side by side in the page shots, and in the group 4,672, 4,160, 1,762 and 1,152 with 0 problems. Its 70 fit records (`masthead-fit-*`, `runhead-fit-*`) took exactly the steps of the 04:13 final gate's run (`runs/gi-20261125-042933`): the masthead's worst case is 5 steps at 1100px in Classic · Obsidian in Romanian (`notes tight brand stop find`), no running-head case takes two lines, and the looks that read the running head's labels at 1340–1440px are those listed under *Known limits*.
- **The main lane's specs** (`hud`, `a11y`, `a11y-modes`, `reachability`, `layout`, `contrast` and
  `status-chrome-layout`, with the main config's project, timeouts and workers): 47 passed in 7.5 minutes (`hud` 6, `a11y` 3, `a11y-modes` 6, `reachability` 10, `layout` 7, `contrast` 5, `status-chrome-layout` 10), against the fixture
  hub, not serve.py.
- **The eleven fixture-backed lanes** (TEMP and TMP in the gate's own scratch folder): routing 6 (its 4 desktop-width checks are skipped in its phone project, by design), base path 16, appearance 6, appearance fonts 2, composer images 6, turn latency 2, image failure 2, mediation 2, gallery 2, dispatch 1 and cloud image 2: 47 passed. Routing and base path ran after the matrix: routing's first try, while the matrix ran, could not start its server (its app port is the matrix's 45130) and ran no test.
- **The Home registers lane** (`frontend/playwright.home-registers.config.ts`: `home-registers.spec.ts` and
  `talk-recipient.spec.ts`): 49 passed in 3.0 minutes (42 in `home-registers.spec.ts`, 7 in `talk-recipient.spec.ts`).
- **Lane isolation,** checked statically: every main-lane project of `frontend/playwright.config.ts` that can
  collect them (the browser matrix's chromium, firefox, webkit and mobile-chrome, and the default chromium) has
  `HOME_LANE_SPECS` (`talk-recipient.spec.ts`, `home-registers.spec.ts`) in its `testIgnore`; the footage project
  exists only under `FOOTAGE=1` and matches only `footage.spec.ts`; and `home-registers.spec.ts`,
  `talk-recipient.spec.ts` and `ledger-shots.spec.ts` each skip in a file-level `beforeEach` outside their own
  project (`home-registers`, `home-registers`, `ledger-shots`). And by listing (`--list` with the web server removed): no main-lane project collects a Home-lane test (573 tests in the default chromium project, 2,292 under `E2E_BROWSER_MATRIX=1`); the footage project collects only its 5; and the 507 `ledger-shots.spec.ts` tests each project collects are the ones it skips.

Every Playwright run drove this bundle through an isolated fixture server with its own temporary data home under
the gate's scratch folder (`e2e/support/base_path_server.py`, or the lane's own server), never the live hub, and
`agents/web/v2/index.html` kept its 09:32:17 modification time from before each run to after it. Where it ran:
Windows, Chromium only, through the cached `chromium_headless_shell` build 1228 (the repo's Playwright expects
build 1254, which is not installed). The verifier's browser and fixture hubs ran on the same machine at the same
time, on other ports; no run here used them.

**Not run on this build:**
- CI;
- Firefox;
- WebKit;
- a real device;
- the native app;
- serve.py's own main lane. The main lane's specs ran only against the fixture hub, which starts
  without the hub's lifespan, so no model, channel or scheduler was running;
- the owner's screen, 2560×1353 at 1.5×. The matrix renders that size and scale in headless Chromium,
  not on the owner's display;
- a card look at the compact or the comfortable density. The register's margin follows the density there (the
  spacing steps a look's `--n-panel-pad` and Classic's `--n-s-4` are made of), but no run renders a card look at
  either density.

`ChatMode`, `TrustMode` and the variant-less `Conversation` and `InputBar` layouts are deleted; their
feature tests render the Ledger components.

*Seen by eye on this gate's run* (cropped and zoomed). Taken for this gate on the same fixture hub and the final
bundle, each a fresh load (so the docket is as it first paints, not after a gate scrolled it), with every
register's and area column's padding, its nearest text and control, and the docket's sign line against its body's
view measured (scratch files, not kept in the repo): Home in Atlas light, Threshold dark and Classic · Obsidian dark
at 1920×1080 and 1280×800, English, live and demo; Home in Ledger dark at 1920px, live and demo; Trust, Work and
Timeline in Atlas light and Classic · Obsidian dark at 1920 and 1340px; Home in Romanian at 1340×900 and 320×720
(Ledger dark, Classic · Obsidian dark and Atlas light, live and demo) and, in the demo, Classic · Obsidian and
Graphite at 1280×800, 1340×900 and 1440×900.
- **Home in the card looks.** In Atlas light at 1920px the day, the conversation and the docket are three rounded
  sheets; every title, meta, row and control keeps 20px from the sheet's sides ("Wednesday 25 November" 20px in from
  the left, "09:33" ending 20px in from the right; "Docket" and its "Unknown — switched off on the hub"), the rule
  under each head stops at that margin, and the composer sits 20px in from the sides and 20px above the sheet's
  bottom (its own 16px and the sheet's 20px collapse; 36px before the repair). Threshold dark and Classic · Obsidian
  dark draw the same with 16px, at 1920 and 1280px. "More in Home · 10 pages" sits under the day's sheet, outside it.
- **The docket at first paint** (demo). At 1280×800 in Atlas light, Threshold dark and Classic · Obsidian dark the
  open entry is whole in the docket's body as first drawn, the body unscrolled: in Obsidian "IRREVERSIBLE STEVE CTO /
  BUILDS RAISED …", the title on two lines, the why, the three request ids, "IF YOU SIGN", "TO UNDO" and "IF YOU WAIT"
  each on one line (the term column grows to Classic's widest term), then the sign box "SIGN HERE — TYPE restart",
  its field and "SIGN" whole, then "Other things waiting: …" and the total with its double rule, 16px above the frame.
  Threshold shows the reason, Preview, Edit, then sign, Defer, Reject and Reject group as well. In Romanian at
  1280×800 in Classic · Obsidian and Graphite the body is scrolled 4px (the gate's scroll), and the state line "Mostră
  demo — semnarea este dezactivată.", "IREVERSIBIL …", the title, "DACĂ SEMNEZI", "CA SĂ ANULEZI", "DACĂ AȘTEPȚI",
  the sign box with "SEMNEAZĂ" and the total "6 INTRĂRI · 9 CERERI / 4 CU SEMNĂTURĂ SCRISĂ 2 ÎN DOI PAȘI 0 DINTR-UN
  CLIC" are all whole; at 1340×900 and 1440×900 nothing is scrolled and nothing hidden. The closed titles there are
  133.2px wide in both Classic looks at 1280px (one 16px margin since the repair; Graphite's were 125.2px with its
  20px), 168.7px at 1340px and 213.2px at 1440px, each cut with an ellipsis.
- **Home at 320px in Romanian** (demo, Ledger dark, Classic · Obsidian dark and Atlas light). The two-row masthead,
  the running head as marks, the day band stacked, then "6 așteaptă semnătura ta" drawn with rules (no frame in any
  look below 760px), its body unscrolled: "Mostră demo — semnarea este dezactivată.", then "Ireversibil Steve CTO /
  Builds cerută la … 3 cereri grupate de hub" and the open entry's title. Before this gate's change the same loads
  opened the body scrolled 88px (Ledger) to 124px (Obsidian), the title at its top and the state line and the tier
  word above it out of view. The page does not scroll sideways, and the running foot is pinned under the column.
- **Area pages** (Trust, Work, Timeline; Atlas light and Classic · Obsidian dark; 1920 and 1340px). The page's own
  title ("Trust", "Work", "Timeline") stands on the page ground under the area column's top rule, 0px from the
  column's left edge like the contents column beside it, and the registers are cards in that column, no card inside
  a card: Trust's "The record" and "Your authority", Work's four registers in two rows, Timeline's "Today by agent",
  every title and meta 20px (Atlas) or 16px (Obsidian) inside its card. In Obsidian at 1920px Trust's two heads are
  level, Work's two rows of heads level.
- **Home in Ledger dark at 1920px: unchanged.** The three registers drawn with rules, no boxes and no padding (0px on
  every side), as before the register-inset round; the matrix's `home-1920-ledger-dark.png` shows the same.
- **Romanian Home at 1340px.** The masthead and the running head each on one row; the conversation's and the
  docket's heads on one line, level; in Atlas and Obsidian every title, meta and control 20 or 16px inside its frame,
  in Ledger none padded; in the demo the open entry and its sign line whole in every look (above).

*Seen by eye on the 00:46 final gate's run* (cropped and zoomed; the 00:46:06 build, which draws the rule
looks exactly as this one does, while its Classic shots show the registers without their margin; what this
gate looked at again is above). The matrix's screenshots are in `frontend/e2e/artifacts/ledger/`; the "While you
were away" heads, the register heads at the widths where a head wraps, the day band's popovers at 320px,
Trust's heads and the demo's heads beside the docket's figure were taken for that gate on the fixture hub
(scratch files, not kept in the repo), with what each head measured. That day was a Wednesday too, so the day
register's title reads "Wednesday 25 November", longer than the "Tuesday 24 November" of the earlier gates'
shots.
- **"While you were away"**, with the fixture hub's answers. Ledger dark, English, at 1920 and 2560px
  (1.5×): the title is whole on one line, and its aside, "since 00:00 (start of today)" and "Unknown —
  switched off on the hub", sits whole on the line under it, starting under the title (it ends 43px inside
  the register at 1920px, 52px at 2560px). Classic · Obsidian dark, English, at 1920px: "WHILE YOU WERE
  AWAY" on one line, then the aside wrapped between its two parts, "since 00:00 (start of today)" and
  "UNKNOWN — SWITCHED OFF ON THE HUB", each whole on its own line from the left; nothing cut (the 18:12
  final gate had seen the title one word per line and the label cut after "SWITCHED"). Classic · Graphite
  dark, Romanian, at 1680px: "CÂT AI LIPSIT" on one line, and "din 00:00 (începutul zilei)" with
  "NECUNOSCUT — OPRIT PE HUB" whole on the line under it. No part had to be cut, so none carries a tooltip.
  The matrix's own `home-1920-ledger-dark.png` and `home-2560-ledger-dark.png` show the same.
- **At 320px, the day band's popovers** (Ledger and Classic · Obsidian, dark, English and Romanian): each
  opens inside the window, the verdict's and Today's at 20–320px and While you were away's at 0–300px, and
  no word of theirs lies outside it. "While you were away" / "Cât ai lipsit" keeps its first letter and its
  "since 00:00 (start of today)" / "din 00:00 (începutul zilei)" line, and Today's "Empty · checked 01:57" /
  "Gol · actualizat la 01:57" keeps its end (the round's first verifier had read "ât ai lipsit" and "HILE
  YOU WERE AWAY", and the end of "checked" cut, in the same places). In Classic · Obsidian in English the
  source label under "WHILE YOU WERE AWAY" is wider than the popover's row, so it is cut with an ellipsis at
  its reason, "UNKNOWN — SWITCHED OFF ON THE …", its mark and state word whole, as the kit's rule says (the
  matrix's `sec-heads` (c) checks that such a cut keeps its whole text in a tooltip or name).
- **Home's register heads side by side**, Ledger dark. In English at 1680px the conversation's meta ("with
  Jarvis · Routing policy unknown" and "Search earlier conversations") drops under its title at the right,
  and the day, conversation and docket heads are all 71px, their rules on one line. In Romanian at
  1100px ("cu Jarvis · Politica de rutare necunoscută", "Caută în conversațiile anterioare") both heads
  are 69px and level, and at 1680 and 1800px all three are 71px and level. Where nothing wraps the heads
  keep their own height (52px to 1339px, 58px from 1340px), and in the demo sample too (the repair; they
  were 59px from 1340px before it). In the demo sample in English at 1680–1920px, the day's head is the one
  that wraps today: "Demo sample" and the time do not fit beside "Wednesday 25 November" in the 396px day
  register, so they drop under the date at the right, and the three heads are 73px (75px in Classic ·
  Obsidian at 1680px) with their rules on one line; that is the shared row doing its work, not the
  docket's figure (in Romanian, "miercuri 25 noiembrie" fits, and every head is 58px).
- **The docket's figure** (demo): in Presence dark at 2560px (1.5×) the four heads (the day, the
  conversation, "6 await your signature", the agents) are each on one line and 66px, level; the large "6"
  sits on the title's baseline and its top stays about 5px under the register's top rule. In
  `home-demo-1280-obsidian-dark.png` (the matrix) the "6" also sits on the title's baseline, inside its
  head, level with the conversation's head.
- **Trust's heads** (Classic · Obsidian and Graphite, dark, live, English at 1340 and 1440px, Romanian at
  1340px): the record's meta ("Audit chain · every action, sealed" and "UNKNOWN — SWITCHED OFF ON THE HUB";
  in Romanian "Lanț de audit · fiecare acțiune, sigilată", "NECUNOSCUT — OPRIT PE HUB") drops under "The
  record" / "Registrul" from the left, and "Your authority" / "Autoritatea ta" beside it takes the same
  74px, so the rules under the two heads lie on one line. The matrix's Trust shots at 1920 and 2560px have
  both heads on one line each, level, and its Work shots show both rows of Work's 2×2 heads level.
- **The floating window in Romanian** (`runhead-window-floating-ledger-dark-ro.png`, 420×620): the
  controls the last round translated wrap onto a second row ("NERVA · CONVERSAȚIE" on two lines inside its
  button, "Deschide în aplicație", "Resetează poziția și mărimea", then "Ascunde conversația"), and the
  compositor's sentence takes two lines; it starts with ": " because the matrix's mock bridge names no
  compositor (the real shell always does). Nothing is drawn over anything (`runhead-surroundings` passes
  on the whole window).

The PNG files in `frontend/e2e/artifacts/ledger/` that this gate's matrix run did not write are failure shots of
old code, kept because those gates save a picture only when they fail: when that run ended, 283 of the 716 there
were older than it (187 `sec-heads-*`, the red runs of the section-heads round, its repair, the register-inset
round, its repair and the final round, each on the bundle from before its round; 68 `runhead-held-*` and 8
`frame-ellipsis-*`, the frame writer's demonstration of 2026-11-24; 20 `area-frame-*`, the final round's red run),
and 30 written during it are this gate's red run on the build step's bundle
(`sec-heads-home-*-demo-fresh-390x844.png`, the docket scrolled at first paint). The matrix run itself failed no
gate, and `report.json` and the run folder `runs/gf-20261125-093223` are its record. The verifier ran its own
browser at the same time and may have written here too.

*Fixed in the final round (2026-11-25; built 08:24:25 and, byte for byte, 09:10:27) and by its final gate
(rebuilt 09:32:17).*
- **The area page's own frame** (variant A). `frontend/src/frame/frame.css` `.n-areapage__main` drew the look's panel
  treatment with no inner margin, so in every card look the page's title sat 0px from its frame on every area page
  and the registers inside were cards inside a card. Now the column draws only the look's top rule
  (`border-top: var(--n-panel-top)`; transparent ground, `border: 0 solid transparent`, no radius, no shadow) in every
  look: the values Ledger, Briefing and Presence already had, so nothing moves there. Evidence: new unit tests
  (`src/frame/kit/kit-css.test.ts` › "the area page's column is not a card", 2 tests) and a new gate, `area-frame`
  (`frontend/e2e/ledger-shots.spec.ts`: on every area page shot, (a) no fill, no side or bottom border and no shadow
  on the column; (b) no register drawn as a card with a framed ancestor up to the column; and its own group of 32
  walks, eight area pages × the 16 looks and schemes × English and Romanian, live and demo, at 1920, 1280, 760 and
  390px). On a copy of the repair's bundle (`index-fJ6wzuz6.js`, served through a scratch wrapper of the fixture hub)
  `area-frame` failed in 38 of 86 records (`frontend/e2e/artifacts/ledger/runs/d15-red-2`: all 20 card-look walks and
  the 18 Classic · Obsidian Trust, Work and Timeline shots; the 12 rule-look walks passed); on the round's build all
  86 passed (`runs/d15-green-1`), and on the final build all 248 records pass (*Verified* above).
- **The Classic docket's sign line** (the register-inset round's *Still open* item). In Classic, at 1280×800, the
  open entry's signature lay below what the docket's body shows at first paint (in the demo 22px in English, 49px in
  Romanian; 12px in Romanian at 1340–1440×900). Where Classic spent the height: each consequence term ("IF YOU SIGN"
  92px, "CA SĂ ANULEZI" 109px wide in a 74px column) took two lines, 21px (English) to 44px (Romanian); the risk line
  took a second line (16px); the foot wrapped (18–22px). The fix is a theme role, `--n-term-max`
  (`frontend/src/theme/CONTRACT.md` §3; `0px` by default, `max-content` in Classic's bridge block), which the kit's
  consequence column grows to where a page opts in (`--consequence-term-max`; only the docket's open entry does, so
  Trust's emergency-stop sheet does not move). That closes every case but Classic in Romanian at 1280×800 (3px
  short, from Classic's mono capitals on the risk line and the total); there `frontend/src/docket/Docket.tsx`
  `useSignatureInView` scrolls the docket's body by what is hidden, at first paint and when the window resizes, until
  the owner scrolls or opens another entry (it scrolls 4px; nothing else moves). Evidence: unit tests
  (`theme-contrast.test.ts` › "a consequence's term column", `kit-css.test.ts` › "a consequence's term column",
  `docket/docket-css.test.ts`, `docket/Docket.signature.test.tsx`) failed 12 of 122 on the earlier sources (a mirror)
  and pass; `docket-1280` and `docket-sign` (below) failed on the repair's bundle (`runs/d15-red-2`:
  `home-demo-1280-obsidian-dark`, and the 4 Classic Home walks with 49, 22 and 12px hidden) and pass on the round's
  build and on the final one.
- **The docket's first-paint scroll, at phone widths and in one column** (found by this gate). As the round built it,
  `useSignatureInView` scrolled the body at most until the open entry's title reached the top of the view. Where the
  signature cannot fit at all (at 320 and 390px in every look; at 1100px in Romanian in Atlas and both Classic looks) it therefore
  scrolled 51–124px at a phone and 62–67px at 1100px, which hid the docket's state line ("Demo sample — signing is
  disabled.") and the entry's first line, its tier word ("Irreversible"), who asked and when, at first paint, and at
  a phone showed no more of the signature. Now it scrolls only where the whole open entry, from its first line to its
  signature, then stays in view (`signatureScroll(view, signBottom, entryTop)`); elsewhere it scrolls nothing, and
  Classic in Romanian at 1280×800 still scrolls 4px. Evidence: `src/docket/Docket.signature.test.tsx` (9 tests; two
  new, two rewritten) failed 4 on the round's `Docket.tsx` (served from a mirror in memory, the working tree
  untouched) and passes 9 on the new one; the gate's probe of fresh loads in the demo found the body scrolled 88px
  (Ledger, 320 and 390px), 106px (Atlas, 320px) and 62px (Obsidian, Romanian, 1100px) on the build step's bundle, and
  0 at each on the final one. `docket-1280` and `docket-sign` now also require the open entry's first line in the
  body's view, and `docket-sign` adds a fresh load at 390×844 and 1100×800 where the body must not be scrolled past
  that line unless the signature is then whole: on a copy of the build step's bundle (`index-Ct8IRirK.js`) `docket-sign` failed in 30 of the 32 Home records of the `sec-heads` group (`frontend/e2e/artifacts/ledger/runs/gf-red-20261125-093301`; every look but Console in English: on a fresh load the body was scrolled 51–104px at 390×844 and, in Romanian in Atlas and both Classic looks, 62–67px at 1100×800, the entry's first line 12–64px above the view), while `sec-heads` and `register-inset` passed in all 32;
  on the final build it passes (*Verified* above).

*Fixed in the register-inset round's repair (2026-11-25, after that round's gate; `index-fJ6wzuz6.js`, rebuilt by its
build step at 07:37:41).* The round's gate and its adversarial verifier found the margin, as first drawn, cutting and
squeezing columns that had been whole, and taking room from the docket's body.
- **Registers are drawn with rules below 760px in every look.** At a phone's 280px column a 12px margin a side cut
  Work's "switched off on the hub" at 320px, ran Timeline's source labels 27px past the frame and squeezed Trust's
  capabilities into overlapping columns at 320–390px. Now `frontend/src/frame/kit/kit.css` draws a register below
  760px with its top rule only (no frame, fill, radius, shadow or margin), in every look.
- **The margin is capped at `--n-s-2` from 760 to 1099px** (one column; 16px a side had made Health's figures 7px
  wider than their register at 760px).
- **The foot takes a footed register's bottom margin.** A register with a foot pads no bottom of its own; an empty
  block after the foot carries the margin and collapses with the foot's last part's own margin (the docket's total,
  the composer: 16px each), the larger of the two rather than their sum. Added, they had taken 16–20px from the
  docket's body at 1280×800 (Atlas in Romanian lost 5px of the open sign line), and the composer sat 36px above
  Atlas's frame (20px now).
- **Classic takes `--n-s-4`** (16px in both looks, `theme/bridge.css`), not its `--pad` (Graphite's 20px wrapped the
  docket's foot in Romanian at 1280px).
- **The gates.** `docket-1280` measures the open entry's sign line against the docket body's view as first drawn,
  not only against the window (it had passed with 38px of it below the view in Classic · Obsidian); a new gate,
  `docket-sign`, measures it in the `sec-heads` group's Home walks at 1280×800 and 1440×900 in every look and
  scheme, English and Romanian, demo and 128 entries; `register-inset` (a) requires a footed register's foot to
  end its margin or more above the frame, (b) counts each total's box with the texts and controls, and a new (d)
  requires that below 760px no register is framed; and the walks wait until no animation or transition runs
  before they measure.
  Evidence: the repair's unit tests failed 4 of 102 on the round's stylesheets (a mirror; `kit-css.test.ts`: the
  `--n-s-2` cap, the rules below 760px, the foot's margin; `theme-contrast.test.ts`: Classic's one `--n-s-4`) and
  pass; on a copy of the round's bundle (the 04:13:13 build, `index-C8Y5Dl7Z.js`) the repaired gates failed in 41
  of 118 records (`runs/r2-red-2`: `register-inset` in the 40 card-look records of the `sec-heads` group, by (a),
  (b) and (d); `docket-1280` in `home-demo-1280-obsidian-dark`; `docket-sign` in 6 Home records), and on the
  repair's build `register-inset` passed in all 118 (`runs/r2-green-3`: in the page shots 54 framed and 108 ruled
  registers, 1,187 texts, 113 controls and 10 totals held, the nearest 16px from each edge), while `docket-1280`
  (1 record) and `docket-sign` (4: Classic, English and Romanian) still failed: the Classic sign line, which the
  final round fixed (above).

*Fixed in the register-inset round (2026-11-25, after the 00:46 final gate; built at 02:46:05 and again,
byte for byte the same, at 04:13:13).*
- **A register's words and controls no longer touch its frame in the card looks.** The final screenshots after
  the 00:46 final gate showed a defect no gate measured: in every look that draws its panels as cards (Atlas,
  Console, Threshold and Workbench, light and dark; Classic · Obsidian and Graphite) a register is a framed or
  filled card, and its title, meta, rows and controls sat on the frame (Atlas light at 2560px: "Wednesday 25
  November" 1px inside the day register's left border and "02:19" ending at its right one; Trust's "The record"
  flush with its frame in Classic · Obsidian), and a total's double rule sat on the frame's bottom edge. Now a
  theme role, `--n-register-pad` (`frontend/src/theme/CONTRACT.md` §3), is the register's inner margin: `0px`
  by default (`theme/tokens.css`), set by each card look in its base block from its own `--n-panel-pad` (Atlas
  20px, Console 12px, Threshold and Workbench 16px) and for Classic in `theme/bridge.css`'s Classic block (as the
  round built it from `--pad`, 16px in Obsidian and 20px in Graphite; since the repair `--n-s-4`, 16px in both).
  Ledger, Briefing and Presence draw registers with rules and leave it at 0, so nothing moves in them.
  `frontend/src/frame/kit/kit.css` makes it the register's own padding on the sides and at the bottom (not the
  top: the head's strut already sets the title well under the top edge, so Home's shared row of heads and
  Trust's `useHeadRow` are unchanged), so the rule under the head, every row's hairline, a total's rules and a
  scrolling body's scrollbar stay with the register's column and the frame keeps its margin outside them;
  as the round built it, below 760px it took at most `--n-s-3` (12px; the repair, above, draws registers with
  rules there and caps the margin at `--n-s-2` from 760 to 1099px). No kit or page stylesheet asks which look is
  on. The cost is the margin's room: at 1280px the docket's closed titles are 24px (Console) to 40px (Atlas)
  narrower, every cut title keeping its ellipsis and its whole text in its tooltip and accessible name, and, as
  the round built it, a register's scrolling body showed 12–20px less, which in Classic hid more of the docket's
  open sign line at first paint (the repair gave the bottom margin to the foot, and the final round closed the
  sign line, above).
  Evidence: the round's new unit tests (`src/test/theme-contrast.test.ts`, "the register's inner margin", 3
  tests; `src/frame/kit/kit-css.test.ts`, "a register keeps its words off its frame", 4 tests) failed in 6 of 7
  on the stylesheets from before the round (read from a mirror; the seventh, no stylesheet asks for the look,
  held already) and all pass now. A new gate, `register-inset` (`frontend/e2e/ledger-shots.spec.ts`, on every
  page shot and at every width and pass of the `sec-heads` group): a framed register must keep a margin above
  0 on the left, the right and the bottom, no visible text or control may come closer to the frame than that
  margin less 0.5px, and a register drawn with rules must have none. On the bundle from before the round (the
  00:46:06 build, a copy served through a scratch wrapper of the fixture hub, `agents/web/v2` untouched) it
  failed in 58 of 118 records (`frontend/e2e/artifacts/ledger/runs/in-red1-20261125-025627`: all 18 Classic ·
  Obsidian page shots of Home, Trust and Work at 1280–2560px and the 40 card-look records of the `sec-heads`
  group; 2,654 problems, text 0.0px from the frame and −0.39px at worst), while the 60 rule-look records and
  `sec-heads` passed; on the round's build all 118 passed (`runs/in-green1-20261125-031922`; the nearest text
  12px from the left edge, 11.8px from the right and 12px from the bottom), and so did the other 67 Obsidian
  page shots (`runs/in-green-rest-20261125-040345`). In the rule looks the renders did not change: of 108
  (Home, Trust and Glance; Ledger, Briefing and Presence, dark and light; 1280, 1920 and 2560px; live and demo)
  shot with a fixed page clock, 97 were byte-identical and 11 differed by 5–55 pixels with every element box
  identical, as two loads of the same bundle differ. That round's final gate ran the full matrix on its build of
  04:13:13 (`runs/gi-20261125-042933`: 475 tests, 491 records, 0 failed gates); what it saw by eye then (the
  docket's sign line partly hidden in Classic, the area page's title on its frame) is what the repair and the final
  round fixed (above). This gate's full matrix on the final build is under *Verified* above.

*Fixed in the last round (2026-11-24, after the 18:12 final gate), and in its repair (after the round's first
gate; built at 23:24:37 and again, with `confirm.tsx`, at 00:46:06).*
- **"While you were away" and the other section heads.** The 18:12 final gate found by eye a defect that no
  gate covered (it is also in a render from 11:25): the day register's "While you were away" head could not
  fit its aside ("since 00:00 (start of today)" and the source label "Unknown — switched off on the hub"), so
  the title was squeezed to one word per line and the aside ran past the section, in English in every look
  measured but Threshold and Console (by 1.4px in Ledger up to 128px in Classic at 1680 and 1920px) and in
  Romanian in Classic (21–57px); in Classic · Obsidian at 1920px the label was cut off after "SWITCHED". The
  cause was the kit's `.n-sec__aside` (`white-space: nowrap`, with no wrap and no ellipsis). Now one rule
  in the kit (`frontend/src/frame/kit/kit.css`, `Register.tsx`), at every width and with no breakpoint,
  draws every section head, register head and total as a row of a title and the words beside it: where
  they do not fit together, the words beside the title take the line under it, so the title keeps the row
  and is never squeezed or cut; words wider than the row wrap between their parts; a part still wider than
  the row alone is cut with an ellipsis (a source label only at its reason, never at its state word or
  mark; links and buttons never) and keeps its whole text in a tooltip while it is cut (`useCutTitles`).
  The same rule fixed its siblings: a register title is never cut any more (it wraps, on its strut), which
  mends Trust's record at 320–390px (its title squeezed to nothing, its meta running up to 247px past the
  row) and at 1440px in Classic · Obsidian ("The reco…").
- **"While you were away" at 320px** (moved here from *Other*). The day band's popovers (the verdict, Today,
  While you were away) are at least 320px wide (`frontend/src/home/day/day.css`) and open from their cell at
  the page's 20px margin without `contain`, so at a 320px window they reached 20px past it and the window cut
  their section heads with no ellipsis, in every look, English and Romanian, live and demo: the first letter
  of "While you were away" / "Cât ai lipsit" and the start of its "since 00:00…", its mark, and the end of
  Today's "· checked HH:MM" (the round's first verifier read "ât ai lipsit" and "HILE YOU WERE AWAY" in its
  shots). It was so before the last round too. The repair keeps every popover inside the window: below a
  340px window `frontend/src/frame/kit/kit.css` lets a day-band popover drop its minimum width and take at
  most its cell and the margin (`.n-disclosure > .n-dayband__panel`), so the three now sit at 20–320px and
  0–300px; from 340px day.css's 320px stands. Evidence: on the round's own bundle (`index-Bt-Rj1xJ.js`) the
  repaired `sec-heads` group found 380 popover lines past the window, all at 320px, in 32 records, and 188
  words cut around them (`frontend/e2e/artifacts/ledger/runs/h2-red-r1b-20261124-234225`); on the repair's
  build none (`runs/h2-green-20261124-235818`), and none on the 00:46:06 build or on the final build
  (*Verified* above; the 00:46 final gate's shots at 320px are described under *Seen by eye*).
- **The register heads line up** (item 7). On **Home**, from 1100px the heads of the registers side by side
  share one row (a CSS subgrid in `frontend/src/home/home.css`, the last round), so the rules under them lie
  on one line whichever head wraps: in Ledger at 1680px in English the conversation's meta drops under its
  title, and the rules, 13px apart before (heads of 58, 71 and 58px), are level, all three heads 71px. On
  **Trust** (the repair), whose two registers keep their own heights, the heads share one height through a
  new kit hook, `useHeadRow` (`frontend/src/frame/kit/Register.tsx`, called once in `TrustOverview.tsx`): in
  Classic · Obsidian and Graphite at 1340 and 1440px in English and 1340px in Romanian, where the record's
  meta drops under its title, both heads are 74px and their rules level (the round's first verifier had
  found them 74 and 58px, 16px apart, in those 6 cases; before the round they were level only because the
  record's title was cut to "The reco…"). **The docket's figure** (the repair) no longer makes heads taller:
  nothing inside a register title takes a taller line than the title's (`kit.css`), so the docket's title
  sits on the strut's line with the others and, with nothing wrapping, every head beside it is 52, 58 or
  66px as before; the shared row had made them 1–8px taller in the demo sample and whenever the docket draws
  its figure live (66 to 74px in Presence at 2560px). When nothing wraps the heads are as tall as before;
  below 1100px, and in a browser without subgrid, each of Home's heads keeps its own height.
- **The gate.** `sec-heads` in `frontend/e2e/ledger-shots.spec.ts`, on every page shot of the matrix and as
  its own group of 64 (Home and Trust, every look and scheme, English and Romanian, 12 widths from 320 to
  2560px, the fixture hub's answers and then the demo sample, the day band's popovers below 1680px): a
  title takes no more lines than it would alone and is not cut where alone it would be whole; nothing of a
  head is drawn past its row or over its title; a cut text ends in an ellipsis drawn in its row and keeps
  its whole text in a title or a name. The Home lane's `heads` tests now also check that the rules under
  the heads side by side are level (within 0.5px). Both fail on the old code: the round's writer served the
  bundle from before the round (`index-xBl5R8XK.js`) through a scratch copy of the fixture hub, and the
  `sec-heads` group failed 64 of 64 with 2,021 problems, every one of the 42 cases the 18:12 gate had
  measured among them, while 8 of the run's 36 Home and Trust page shots failed it
  (`frontend/e2e/artifacts/ledger/runs/heads-red-matrix2-20261124-202555`), and the Home lane's four Home
  `heads` tests failed (rules 1–13px apart). On the round's bundle the same records passed
  (`runs/heads-green-matrix-20261124-203911`). **The repair** made the gate find what its first verifier
  found by eye and by probe: (d) the rules under the heads of registers side by side (Home from 1100px,
  Trust's and Work's columns from 1340px) must be level within 0.5px, whichever head wraps; (e) where none
  of them wraps, each must be exactly a register head's height (`--register-head-h`); the day band's
  popovers are gated, not only reported (a popover past the window, or a word in it cut by the window or the
  page, fails); and Home gets a third pass, a stubbed live docket of 128 entries from 1100px, so the
  docket's figure is measured live as well as in demo. The Home lane's `heads` tests got the same
  no-wrap height check. On the round's own bundle (`index-Bt-Rj1xJ.js`) `sec-heads` failed in 38 of 100
  records (`runs/h2-red-r1b-20261124-234225`: the 6 Trust cases by (d), 252 cases beside the docket's figure
  by (e), the 320px popovers) and the Home lane's two demo `heads` tests on Home failed; on the repair's
  build all passed (`runs/h2-green-20261124-235818`, 140 records, and the Home lane's 49). The final gate's
  run on the final build is under *Verified* above.
- **Two leftovers.** The floating desktop window's controls (Float chat, the drag handle, Open in app,
  Reset layout, Hide chat, the resize button's name and the compositor's status line) now follow the HUD's
  language (`frontend/src/desktop.tsx`, `DESKTOP_STRINGS`; "Open in app" in the conversation's own words);
  and the line about a dropped change of recipient now ends only where a turn is really sent (`runTurn`
  after its refusal checks, `runVision` after its busy check), so a hands-free voice turn that is sent ends
  it, and one refused while a reply is being written ends nothing. The doc comment above `RUNHEAD_FIT_STEPS`
  in `frontend/src/frame/RunningHead.tsx` no longer quotes the second round's measured savings. Their tests
  (`src/test/desktop.test.tsx`, `src/test/chat-routing-app.test.tsx`) were shown failing on the old code by
  their writer, with the old files served in memory.
- **The Vitest test that failed now and then** (`src/frame/RunningHead.test.tsx` › "below 760px closes its
  popover on Escape (back to its button) and on a press outside, dropping a choice not confirmed"; the round's
  first gate traced it). The cause was in `frontend/src/confirm.tsx`, not in the test: `ConfirmAction` moved
  the focus onto a confirmation in a passive effect, a commit after drawing it, so an Escape arriving in
  between had `RunningHead` put the focus on the mode's button, then React ran the pending effect, the
  confirmation took the focus back and was removed in the same update, and the focus fell to the page. In a
  browser that needs an Escape within the few milliseconds before the confirmation takes the focus. The
  focus now moves in layout effects, in the commit that draws the confirm button or the phrase box; nothing
  else changed, and the test is as it was. New tests in `src/test/confirm.test.tsx` (the focus is on the
  confirmation as soon as it is drawn, two steps and typed) failed on the old file; the RunningHead test,
  run alone, failed in 4 of 8 runs on the old file and in none of 24 on the new one (its writer's runs); the
  00:46 final gate ran it alone 10 more times on its sources (10 passed; neither `confirm.tsx` nor the test
  has changed since), and the full suite passes on the final sources (*Verified* above).

*Fixed in the polish rounds (2026-11-24).* **Running head:** it now fits on one line at every width from
1100px and its items can no longer overlap. The head measures itself (`frontend/src/frame/fit.ts`) and takes
steps in order: source, short, egress, values, tight, labels, mode, cut, lines (PHASE_B_PLAN.md §4.2,
amendment); the egress and model items are grids whose value column never narrows below the mark plus an
ellipsis, so a line that is too long overflows, which the fit detects, instead of colliding. The earlier
overlap at 1340–2200px (an early render at 1920px in Classic · Obsidian drew "Egress" over "sent to local
runners") is gone; that render was not kept, because `frontend/e2e/artifacts/ledger/home-1920-obsidian-dark.png`
is overwritten by every matrix run and now holds the fixed render. The record that it is gone is the gate:
the 20 `runhead-fit-*` records of `runs/r5-final-20261124-171109` (excluding the resize cases) show all eight
items whole, apart and on top at every measured width (`"ok": true`). Folding the approval mode into a
button (the `mode` step) keeps the same two-step loosening in its popover. Evidence: the running-head fit
cases of the matrix (Ledger, Classic · Obsidian, Presence and Atlas; English and Romanian; the widest values
and the hub's own answers) in `frontend/e2e/artifacts/ledger/runs/matrix-final2-20261124-120824`, the
rerun in `runs/runhead-final-20261124-123235` and `runs/atlas-final-20261124-124142`, the 17:00 bundle's
in `runs/r5-final-20261124-171109`, the 21:05 build's in `runs/lg-20261124-213020`, the 00:46:06 build's in
`runs/fz-20261125-010015` and the final build's in `runs/gi-20261125-042933` (`runs/r4-final-20261124-151248`, on
the 15:12 build, is superseded). **Masthead:** with
every attention note at its widest at once (128 need you, 12 services down, the record broken at entry
412907; stubbed readings) the nine areas fit the row at every measured width from 1100px through the ten
measured steps (`FIT_STEPS`; the first, `search`, applies only from 1680px); on the 17:00 bundle, the 21:05
one, the 00:46:06 one and the final one the worst case, 1100px Obsidian in Romanian, takes 5 of them (`notes`,
`tight`, `brand`, `stop`, `find`), as does the comfortable density in Romanian at 1100px, and no case reaches
`tighter` or the scrolling fallback (`masthead-fit-*.json` in `runs/r5-final-20261124-171109`,
`runs/lg-20261124-213020`, `runs/fz-20261125-010015` and `runs/gi-20261125-042933`; the second round's worst
case took 7, before the fit took steps back). **Phone and floating window:** below 760px
the running head is one compact line of marks; in the main window the approval mode stays changeable in its
popover, with the same two-step loosening, and only the marks variant (the 420px floating window, Glance) shows
it as a read-only button; below 1100px the head takes no fit step (a looser choice asked in a popover keeps the mode folded). The foot's groups wrap without
dividers; register heads on Home and the chat page keep their whole title (the meta wraps under it).
**Talk:** a change of recipient asked for while a reply is written stays as a question when the reply ends
(reworded, Send held) instead of being carried out, and survives leaving Home and coming back; a roster the
hub did not serve reads "Routing policy unknown", never "Unavailable".

*Fixed in the third polish round (2026-11-24).* **Fit:** after the walk fits, each step it took is tried back,
the lossiest first, and stays back only where the line still fits without it and without cutting a value
further or adding a line (`frame/fit.ts` `fitRow`, `stepBack`), for the masthead and the running head; the
second round's cumulative walk kept `tight` together with `labels` where the labels alone would have
fitted. **Folded approval mode:** a looser choice waiting for its second step holds the mode where it was
asked (`data-hold`: from 1100px a refit neither folds a choice asked in the line nor unfolds one asked in a
popover; below 1100px a choice asked in a popover keeps the mode folded); the head still follows the window,
so below 760px what waits goes with the mode into the marks' popover, which opens with it; the hub's answer
holds nothing (where a fit folds the mode while it is on screen, the popover opens with it). The mode's box,
confirmation and answer are kept inside the window like the other popovers (at 390px with a held fold they
had run off the left edge, as the last review found); a press
outside the fold's popover never drops a confirmation or refusal drawn in the line; a focus inside the mode
follows it to the fold's button or the checked radio, and after a write it goes to the radio of the mode in
force, not to the page. **Glance:** in a short window (the 420×800 floating size, a half-height browser) the
sheet scrolls from its top and nothing is drawn over anything; every popover of the running head's marks
opens inside the window (`Disclosure` `contain`: below its button, above it where below would leave the window, as at the bottom of Glance's screen; below 760px below the whole head, inset from its sides); the
interrupts are a button with a popover like the other marks. **Stop:** the halted stop carries a tooltip with
its whole sentence (it had only the accessible name); this was listed with the third round, but it is an
earlier round's change: `StopButton.tsx` last changed at 10:49, before the round's frame changes of
16:48–16:57. **Docket:** the rows sit in one subgrid table, so the
tier word, the title and the hand line up across rows and the tier column grows to the widest tier word of
the look and the language; below 760px a closed row is two lines; at 320 and 390px the total no longer
draws "9 requests" over "4 typed". **Talk:** with the roster not served and a selected agent that cannot be
confirmed, the composer says so, the head reads "not confirmed" and the To offers Jarvis (nothing switches by
itself); a change of recipient dropped because a served roster no longer offers the agent is said on one
line with Dismiss; a refusal and a question name the agent as the owner knew it (the last name the roster
gave). **Ctrl K:** "Write to <agent>" uses the conversation's own words (Romanian "Scrie-i lui Frigga");
the sheet's "Scrie către" is gone. **Fixture hub:** the proxy keeps its connections to the app alive and
reuses them, which removes the socket exhaustion (`WinError 10048`) that left a page unmounted in long
runs; the render matrix still reloads a page that never mounts once and records it. Evidence: the render
matrix of the 17:00:15 build (`index-xBl5R8XK.js`, after the last change to `frontend/src` at 16:57 and to
the matrix spec at 16:58; the final gate of 18:12 rebuilt the same files and ran the matrix again,
`runs/fg-20261124-181737`, 427 records, 0 failed gates), `frontend/e2e/artifacts/ledger/runs/r5-final-20261124-171109`:
427 records, 0 failed gates, status `passed`, no page reloaded, and `agents/web/v2/index.html` kept its
modification time through the run (the number of Playwright tests was not recorded in the run folder). Its
records include `runhead-window-*` (12: Glance and the floating window, Ledger dark, Obsidian and Atlas light,
English and Romanian), `runhead-popovers-*` (6: every popover of the main window's head inside the window, on
top and opaque, at 1280, 1920 and 390px), `runhead-held-*` (16: the confirmation of a looser choice asked in
the line, in the fold and below 760px, and a refusal, while the window is resized), `runhead-fit-*` and
`masthead-fit-*`. The earlier run `runs/r4-final-20261124-151248` (373 records, 0 failed gates) ran on the 15:12
build, before the 15:42 rebuild and the 16:48-16:57 frame changes, and is superseded. The final gate of 18:12
re-ran the Home lane (49 passed; before it, last run at 15:44 on the 15:42 build) and the full Vitest suite on
these files (441 files, 4,967 tests passed). All of these runs, and the last round's first gate's on the
21:05 build (`runs/lg-20261124-213020`), are superseded by the final gate's on the final build (*Verified*
above). The Home lane is `frontend/playwright.home-registers.config.ts` with `e2e/home-registers.spec.ts` (the
register heads at 13 widths from 320 to 1920px, the held question at four widths, the docket's rows in 16
look-and-scheme pairs at five widths, English and Romanian) and `e2e/talk-recipient.spec.ts`, a manual lane
on its own port that the main lane ignores and that writes no record files (its result is the run's own
output); the Vitest suites that cover this round's changes are those of `frame/`, `docket/`, `home/talk/`,
`nav/` and `src/test/chat-*`.

*Still open:* a native-speaker review of the Romanian copy (the composer's question, the Dossier and the
Ctrl K sheet now all say "Scrie-i lui <agent>"; the Romanian labels of the attention notes, the kit and the
running head are also unreviewed, and so are the floating window's controls the last round put into
Romanian: "Deschide conversația plutitoare", "Resetează poziția și mărimea", "Ascunde conversația",
"NERVA · CONVERSAȚIE" and the compositor's sentence); the native app has none of this structure (`mobile/PARITY.md`, "HUD
structure"). **Not verified:** the owner's real screen (2560×1353 at 1.5×), Firefox, WebKit, CI, a real
device, the native app, serve.py's own main lane and a card look at the compact or comfortable density; every browser run was the cached Chromium 1228 headless shell (`layout.spec.ts`
records the sub-760px phone surface as an open owner call). **Known limits of the running head:** with the
hub's own answers the labels are read, not drawn, at some widths from 1340 to 1440px, because the line does
not fit without that step. On the newest runs (the measured widths 1340, 1366 and 1440px;
`runhead-fit-*-fixture-*.json` in `runs/r5-final-20261124-171109`, in the 18:12 final gate's
`runs/fg-20261124-181737`, in the last round's first gate's `runs/lg-20261124-213020` on the 21:05 build, in
the 00:46 final gate's `runs/fz-20261125-010015` on the 00:46:06 build and in this final gate's
`runs/gi-20261125-042933` on the final build, which all agree) that is Classic · Obsidian in English at
1340 and 1366px and in Romanian at all three, Atlas in English at 1340px and in Romanian at all three,
Ledger in Romanian at 1340px, and Presence in Romanian at 1340 and 1366px; Ledger and Presence in English
keep their labels (at most with closer spacing) at all three. With the widest values (a cloud model with the
ledger's count and a 47-character model id) every look reads its labels at 1340–1440px, and some also fold
the mode or cut a value there. The step order is the second round's measured one and the step back only
removes steps, so a look that needs `labels` to fit keeps it. The doc comment above `RUNHEAD_FIT_STEPS` no
longer quotes the second round's measured savings: the last round rewrote it to describe the walk, the step
back and the sub-pixel cut, and to point to the run records for the steps each width keeps. "Offline · last good reading" cannot be drawn together with the long model id (an offline hub
reports no model), so the gate measures it on its own, at every width. **Other:** the docket's hand column is shared by all closed rows below 1680px, so the widest hand sets every title's
width (Classic Romanian at 1280px: "DESCHIDE CA SĂ SEMNEZI" leaves titles 133.2px in both Classic looks since the
register-inset round and its repair gave them a 16px margin, 165px before; cut with an ellipsis and a tooltip), and an engine without subgrid (before Chromium 117, Safari 16, Firefox 71) falls back to
fixed columns where Classic's wide tier word can still overlap the title; "Request 2" drawn over
"REVERSIBLE" in Obsidian docket rows at 600 and 740px was reported by the frame writer before the rows were
lined up; the docket check now covers 740px and passes, 600px is not measured, and the frame gates' paint
check (`runhead-surroundings`, 28 records) covers the floating window, Glance's sheet and, within 32px of the
head, the marks below 760px, not every page of the main window; that paint gate's limits stand (in-flow pseudo-elements
such as Find's key cap, box shadows, outlines, clashes only in ascenders or descenders, and scroll
positions between first shown and the end); the floating window's "scrolled to the end" check finds no
scroller with the fixture's empty transcript, so a populated transcript is not exercised; the fixture proxy
still prints `ConnectionAbortedError` (`WinError 10053`) when a browser aborts a request mid-answer, and its
browser-facing side still opens one connection per request; a hands-free voice turn made while a recipient
question is open is refused while the reply that opened the question is still being written (`runTurn`
refuses every voice turn while any reply is in flight, so nothing is sent), and it goes to the current
recipient only after that reply has ended, leaving the question open (PHASE_B_PLAN.md §12 item 12, the
default until the owner decides); with busy readings the running foot can take a second line at some widths
(not re-measured since the third round). Left by the last round and its repair: Work's 2×2 registers
(`frontend/src/pages/WorkOverview.tsx`) do not share a head height (the repair gave Trust `useHeadRow`, not
Work); `sec-heads` measures their two rows of heads at 1920 and 2560px in every matrix shot of Work (Ledger
dark and light, Classic · Obsidian, live and demo) and they are level, but a Work head that wraps where its
neighbour does not would put them apart, and the gate would fail; the
kit's stylesheet names a day-band class (`.n-dayband__panel`, below 340px) whose better place is
`frontend/src/home/day/day.css` or `contain` on the day band's disclosures; the docket's large figure now
takes the title's line height at every width, a visible change where the docket stands alone too (its
title on the strut's line, the figure's ink 5–9px under the register's top rule); the cost of `useHeadRow`'s
observers on Trust was not measured; `frontend/src/frame/kit/index.ts` re-exports none of `useCutTitles`,
`CUT_TITLE_ATTRIBUTE`, `useHeadRow` and `HEAD_ROW_PROPERTY` (`TrustOverview.tsx` imports `useHeadRow` from
`frame/kit/Register`, as other modules import the kit's marks and strings directly), while
`frontend/src/theme/CONTRACT.md` §8b lists Phase A's primitives only and Phase B's register classes and hooks
(`.n-register__main` and those four among them) are recorded in `docs/design/hud-next/PHASE_B_INTERFACES.md`
§7; the floating window's drag
handle is named "Move floating chat" ("Mută conversația plutitoare"), which does not contain its visible
words (WCAG 2.5.3), and it is mouse-only; the native decision notification's title and the tray menu are
English only, and `desktop/README.md` names only the English labels. The register-inset round's two open items (the docket's sign line
at first paint in Classic; the area page's own frame) are closed by its repair and the final round (*Fixed*, above).
Left by the final round (2026-11-25): Projects' Kanban section (`frontend/src/panels/kanban/kanban.css`) fills
itself with `--n-bg`, which is now the page ground under the transparent area column, so its inset well no longer
shows (it still reads); Trust's emergency-stop consequence keeps the fixed 74px term column (it does not opt in to
`--n-term-max`), so in Classic its terms still take two lines ("WOULD / HALT"); in Classic in English at 1280×800 the
open entry's signature fits by about 1px with no scroll (with other fonts the docket's scroll would take it); at
1100px (one column) in Romanian in Atlas and Classic part of the signature lies below the docket body's view at
first paint (62px in Classic · Obsidian)
(the plan promises it whole at 1280×800 and from 1340px; the docket no longer scrolls there, since that hid the
entry's tier word); the final round's survey of the 159 area pages ran English live and Romanian demo only, not all
four language × sample pairs. **Smaller:** "More in Home · 10 pages", under the day's sheet and outside it, starts at
the sheet's outer edge, not at its margin; the floating window, which draws no register, starts its docket line and
the compositor's status line 2–10px from its left edge (the register-inset round's writer's measure, not
re-measured here). The `a11y-modes` lane
still surfaces, without failing on them, axe's "needs review" findings: the EN | RO radios and a
few icon buttons (label in name), and an `aria-label` on an element with no role in the Jobs
blueprint gallery (the final gate's run listed only these; a main-lane run on the morning of 2026-11-24
also listed one in a Decision Inbox row, which the fixture-hub runs since have not listed). The main and `gap` chunks of the built bundle are each above
Vite's 500 kB warning (on the final build `index-lG61P7Tc.js` is 929,774 bytes and `gap-DJPyrv3U.js` 955,795; the workspace's `workspace-CsQlVwPq.js` 551,521).

## Search chat history

Owners can find retained messages from the Chat and Cockpit composer using
**Search chat history**. Reviewing a result opens its exact saved turn, including
turns older than the recent recap. **Continue this conversation** selects the session.
**Use in this chat** attaches an eligible passage to the current draft and keeps
its recipient. Sending rechecks the source. The saved question carries a citation.
Native Chat offers the same action through **History → Search messages**. The
citation is also visible in the mobile chat after reconnecting to the same account.

## Saved facts in Memory

The live Memory view lists the curated Agent notes and User profile. An owner
can save, correct or forget an exact entry and undo a removal. A fresh owner conversation can
include those facts in its selected model's prompt. The built-in memory switch
controls inclusion. In live Chat and Cockpit, **Remember message** opens an editable
copy of the user's text. An explicit save uses the credentials of that chat.
In web and native Chat, **Replace a saved fact** shows the chosen store so the
owner can select a previous entry and review its replacement. The editor keeps
the correction draft if the selected entry changes elsewhere. A new owner
conversation can use the revised fact. The original message stays in history.
The same dialog can forget a selected Agent notes or User profile entry after
confirmation. It offers undo for the confirmed removal until the rings change.

## Save a reply to Obsidian

Chat and Cockpit let the owner review a completed reply, edit the title and
body, and save the note in the connected vault inbox. The dialog obtains the
destination from `GET /api/os/status` and submits the reviewed text through
`POST /api/os/brain/chat-note`. The receipt shows the relative note path and
offers a native Obsidian link when the vault and filename support one.

## Kanban tasks from chat

Chat and Cockpit can turn a user message or a completed assistant reply into a
triage card. The owner chooses a board and edits the text before saving. Attached
vault excerpts and images stay out of the draft. Creating the card does not run a worker.

From Projects, **Discuss result in Chat** opens a completed task for review.
Chat and Cockpit also offer a board picker. The owner chooses the full result
or a passage for one message, with the latest summary labelled when used.
Saved questions in the web HUD link to verified board sources. The owner can
open each current result and see whether the full output has changed since
the original send. A revoked or missing source leaves the current draft intact.

## Models called for a reply

In focused and floating Chat, the agent picker lists enabled agents from the
authenticated roster. Switching recipients preserves the draft. After a page
reload, the same tab restores the recipient for that conversation when the
hub confirms the agent is still available. Chat and the Cockpit conversation
show the selected agent's routing policy before sending.
An older hub can omit the policy, in which case the HUD shows **Unknown**.

**Compare agents** opens from a plain text draft in Chat and Cockpit. Pick two
enabled agents, review the question and see each result under its own name.
The comparison starts when you submit the dialog and keeps the chat draft intact.
Use **Save to Obsidian** on an answer to review it in the vault note editor.
Its saved path appears on that answer's card.

Choose **Direct reply** before sending a text message to ask a supported model to
skip extended thinking for that reply. The composer resets the choice after sending.
For an ordinary text turn, a local Ollama model that spends its entire budget
thinking can retry once in Direct reply mode when the same model supports it.
Turn usage includes both generations.

The chat shows the measured provider and model beside a reply when the hub has
a complete per-turn record. The details list includes each distinct pair. The
same record travels with the saved assistant turn. The separate cognition panel
remains a hub-wide view. Older turns can have no model record.

Chat and Cockpit also show the hub's measured agent tool executions beside the
reply. Queued and failed attempts have separate counts. The counts stay with
the original reply when another turn finishes and when the owner reopens a
saved native conversation with recorded counts. Imported history, older replies
and turns marked untrusted can lack a saved measurement.

## Editable Blender meshes

Chat and Cockpit also offer **Make editable Blender model**. A supported OBJ
reply shows a projected mesh and object counts. Its review dialog also works on
narrow screens and flags inconsistent face winding or a closed shell facing inward.
An owner can download it as
a native Blender project through the connected hub. Native Chat still needs
the preview and file-sharing controls.

## Office documents in chat

Chat and Cockpit accept Word (.docx) and Excel (.xlsx) files for preview on
the hub through `POST /api/canvas/office-preview`. Owners can review selections
from multiple documents, remove individual passages and compare the retained
passages in a single message. Each selection carries its filename and, for an
Excel workbook, the sheet name. A comparison that exceeds the combined
attachment budget can be shortened and retried.
Long Word documents can be paged in 12,000-character windows. Changing the
preview page leaves the chat draft intact. Only attached passages go to the agent.
Native mobile document selection and review remain open.

Chat and Cockpit also inspect native Blender projects. Artifacts opens the
same review in Chat. Choosing **Inspect with Blender** sends the project to the
owner's hub. The owner can preview an embedded thumbnail when available and
attach selected inventory text to the conversation.

Chat and Cockpit also read Godot scenes, GDScript and `project.godot` in the
browser. Owners can attach a selected source passage and download individual
Godot scene or script blocks from a completed reply.

The **Photoshop** action under a completed reply in Chat and Cockpit opens a
local composition preview. The downloaded PSD contains editable title and body
text and an optional image layer. Oversized text can be edited before download.

The live HUD exports completed assistant replies as Word documents. Bold
phrases in the answer become editable bold text in Word. Each Markdown
table can be downloaded as a separate Excel worksheet. Canvas markdown and table
cards also offer the applicable download. These actions use the authenticated
`POST /api/canvas/export`. The response goes directly to the browser and creates
no saved Canvas item. Native mobile export remains open.

## ANDREI OS (post-merge review, 2026-11-17)

The Artifacts tab opens the 3D workshop at `/os/?studio=robot`. Both workshop
models offer editable GLB downloads for Blender and Godot, including the furnished miniature. The house
also exports a 1:100 SVG floor plan from its current walls, floors, deck and
pools. Its Illustrator button and text command download a JSX script that creates
the grouped drawing in Illustrator, where the owner can save it as `.ai`. The hub
workshop applies local model edits through `POST /api/os/workshop/edit`. These
controls live in the browser workshop, including saving a version to the Obsidian
inbox with `POST /api/os/workshop/projects`. The HUD Artifacts tab, chat and task
comments use `GET /api/os/workshop/projects` and `GET /api/os/workshop/project`
to open a version, review it for one message, or draft a task handoff. The text composer
calls `/api/os/brain/retrieve` for scoped note excerpts. A result can open its
canonical note in Obsidian. For an indexed, readable source, the composer uses
`/api/os/brain/note` with the search question to open the matching part of
a long note. It checks the text and its position again before sending. During review
the sender can include the relative note path as text in the saved message.
Console → Memory → Vault (`VaultPanel`) now calls `/api/os/status`, `/api/os/brain/reindex`,
`/api/os/brain/retrieve`, `/api/os/brain/note` and `POST /api/os/brain/capture` directly from HUD V2
with Second Brain readiness badges and an `Open /os/` link, while `/api/os/brain` (the 3D galaxy) and
`POST /api/os/workshop/edit` remain in the standalone `/os` client (`HUD_GAP:jarvis-os`).
Native Chat also uses `/api/os/brain/retrieve` to review and
recheck excerpts before sending them with a question. Vault graph navigation,
passage selection and inbox capture remain frozen on mobile per 2026-11-25 decision (BACKLOG H18.38).

Standalone AI Connections and its default-off cloud chat consent are confined to
the standalone server. Hub `/os` hides those settings and uses the hub's separate
`/chat` policy; no hub bypass is demonstrated by the standalone finding.

Messaging platforms other than Telegram (Slack, Discord, SMS, ntfy, email, Matrix and
the webhook channels) were removed on 2026-11-25 by owner decision
(`docs/decisions/2026-11-25-nerva-finish-line.md`): the Channels panel lists Telegram
only, the Comms mode offers a governed reply for Telegram and web threads only, the
Integrations panel has no channel kind and webhook deliveries go to the log, Telegram
or voice. The `/nerva` command fallback stays. The
`channels.max_inbound_media_bytes` limit uses existing generic admin settings;
no dedicated media control or frontend/device acceptance is claimed.

H079 single-skill slash loads and `/commands [page]` use existing chat surfaces.
The live chat composer’s Skills button lists approved skills for the selected agent.
Its review action drafts `/refine` with an optional focus. The owner can read the
proposed instructions in Console → Pending skills, approve that version, and select
the skill in another chat. The picker shows the recipient and searches the loaded
catalog by name. Selecting a skill preserves the current task text. Changing
recipients drops the selected skill prefix and retains the edited task.
On a completed reply, **Teach skill** lets the owner edit a procedure for the replying
agent. The review link opens that procedure in Console even when the queue exceeds
ten entries. Approval signs the version the owner inspected. To revise a procedure
learned from a reply, select **Edit steps** in the agent’s Skills picker. The Console
link opens the proposed diff. The current instructions remain active until approval
and application succeed.
Local V24 extends the HUD command catalog with owner-only quick commands,
web-enabled unambiguous skills and explicit `/bundle <slug>` entries. It shows fixed
metadata and partial/truncated notices without executing or loading skill bodies.
The combined catalog is capped at256 rows, registry first; skill inventories over512
are omitted rather than resolving against an incomplete pool. H069 now tests App SSE final replacement (including empty final); device acceptance
is unrun. Main chat SSE labels/prose use outbound safety; opaque secret redactors
withhold incremental prose until whole-response verification.

Owner `/reload-skills` uses the shared chat registry and existing command catalog;
no dedicated reload screen is added. Telegram static sticker caption/cache is a
host channel feature. Native/mobile media and reload acceptance remain unrun.
Owner `/debug` returns a local report path through existing chat; it has no upload
or new screen and currently refuses on Windows.

Local candidates, 2026-11-03: H220 adds Usage/Billing estimates, measured
local/cloud/unknown aggregates, a Command Center link, and current-turn usage
in the existing shared context strip. Explicit owner field selections remain
unchanged; fresh defaults expose the context meter. Historical usage without
route evidence remains unknown, and unpriced cost is not presented as free.
H696 adds bundled/optional catalog tiers and explicit installation of optional
repository skills into quarantine. Native aggregate usage and native skill
installation controls remain gaps; integration acceptance is still pending.

H334 local import update (2026-11-04): Skills Import uses current admin and
kernel admission, with immutable commit, entry and reference digest fields for
generic sources. The built-in Hermes selection uses its server-owned pin.
Grant and queue responses identify a quarantined copy awaiting separate owner
review. No native install control or live upstream acceptance is implied.

H027 local candidate (2026-11-04): `nerva curator` and the admin `/api/curator`
domain expose lifecycle inspection, exact reviewed owner requests and recovery.
The existing action approval inbox decides curator cards; the CLI prepares their
targets and reports pending until approval actually applies them. There is no
dedicated curator browser panel or native control. Dry-run requests do not queue
or mutate. Full H027 integration is still pending; no new capability credit is
claimed from wiring alone.

SEC-B6 local client/security source (2026-11-03): twelve content-bearing GETs
now require user access: `/api/oracle/status`, `/agents`, the three
`/api/eval/datasets` list/runs/compare reads, `/learning/stats`,
`/api/local-docs`, `/skills/imported`, `/api/arena/leaderboard`,
`/api/metrics/kernel`, `/api/metrics/capabilities`, and `/sandbox/status`.
Existing v2 `apiGet`/`useApi` callers send the user token; legacy v1 reads use
the stored-token fetch wrapper. That wrapper now resolves URL origin and copies
request options/headers per local attempt, preventing its token injection from
following protocol-relative external URLs or reused options. The standalone
`/admin` page does not load that wrapper: its Agents and Oracle status/conflicts
GETs use the existing admin-token `afetch` helper. Admin credentials satisfy
user-read guards. This is a read-access change; existing mutation contracts
remain separate.

The successful public `GET /api/security/kill-switch` is an exact three-field aggregate:
`{global, any_halted, halted_count}`. Scope names and reasons are available on
admin-only `GET /api/security/kill-switch/details` as `{global, halted}`. Trust
and Console distinguish a global halt from scoped halts; the global button
still acts only on global scope. Missing, failed, and contradictory aggregates
show unknown and preserve the safe engage direction. Trust also remains
unknown when a successful POST cannot be verified by a subsequent GET. Mobile
consumes only the aggregate in a read-only Status row, with the same global,
scoped, and unknown distinctions. Focused source tests and typechecks support
these claims; a served browser, credentialed network Hub, and native device
have not been accepted in this documentation slice.

> What's intentionally **left out** of the P0–P6 build (PR #156 / merged to `main`) and queued for
> the next pass. **Update 2026‑06‑08: the cutover happened — V2 is the default HUD at `/`** (legacy
> at `/v1`, override `JARVIS_HUD=v1`); §8 below is done, the rest is the depth punch‑list.
> Companion: `HUD_V2_IMPLEMENTATION_PLAN.md`, `HUD_V2_COVERAGE_AND_PLAN.md`. Generated 2026‑06‑05;
> **re‑audited 2026‑06‑10** (see §10).

H456 local candidate (2026-10-10): the shared web Jobs form adds requested
reasoning effort and the installed tool catalog. Existing Settings controls
author the cron default and operator restrictions. These do not close the
separate operations/context controls below or native-mobile authoring.

H453/H454 local candidate (2026-10-10): CLI/admin API can configure cross-job
`context_from`; complete safe script stdout is separate from bounded history and
context excerpts. Dedicated web source selection, latest-output inspection and
continuity controls remain open. Existing diagnostics and legacy note editing do
not constitute those controls. See `docs/automations-operations.md`.

H015 local candidate (2026-10-10): admin API/CLI add durable incident acknowledgement,
named job notes, explicit continuity and historical runs after job removal. The
current Jobs panel shows incident JSON and retains its legacy note editor. Dedicated
acknowledgement, KV, continuity and deleted-job history controls remain open; no new
web control is claimed. See `docs/automations-operations.md`. H049 named log reading
is a host CLI capability; the existing web Logs selector remains supported.

H002 local candidate (2026-10-10): JSON chat replies and SSE end events add a
request-owned generation-usage snapshot. Existing HUD chat rendering is retained;
this batch does not add a spend panel. Atomic usage-file export belongs to the
host CLI. Generated API types include the additive field and the earlier H441
resume/import routes. See `docs/cli-chat-receipts.md` for measured, estimated and
unknown values.

H660 (2026-09-15): session kernels now use detached Docker internally. Existing
sandbox status/reset controls remain the operator surface; backend status labels
identify `docker-detached`. Complete Python cell streams use existing tool-result
file references. Failed teardown stays visible as unconfirmed; reset can be retried
without claiming the worker is gone. Real Linux and native macOS Docker tests now
pass, including reset/cancellation and context/proxy isolation; SSH/Modal/TLS
provisioning remains open. See docs/hermes/evidence/2026-09-15-docker-containment.json.

## 0. Do this first

H441 local candidate (2026-10-10): owner CLI/API selectors and Claude Code/Codex
transcript imports extend the existing free Sessions recap. Imported/derived
sessions are owner-only at the shared server boundaries; guest session and
checklist lists omit them. Browser import/selector controls are not added in
this batch. Foreign source discovery remains CLI-host administration; see
`docs/foreign-session-resume.md`. H398's fixed completeness notice and internal
risk advisory affect model tool results, with no new public chat field. H667's
existing temporary-directory setting now describes standard environment fallback.

H329 local update (2026-10-10): Skill Switches renders HTTP 202 as pending
owner approval and retains the disabled state until the worker applies the
exact request. Global and channel settings remain distinct. Canonical approver
audit is transactional; the IntentLog projection is optional. Missing or corrupt
state returns an unavailable response. The existing approval inbox is the
review surface; the interactive `nerva skills config` picker uses the same API.
H299/H397 default to guidance with an explicit runtime setting for stall stops.

H413/H689 local update (2026-10-10): existing Sessions displays retain instant
and background-upgraded titles; automatic naming now uses a dedicated small
local model. An unavailable model keeps the instant title. Profiles share the
installation identity while their stores and credentials remain isolated.
Existing node-registration and sender-link APIs return 503 when identity is
unavailable; reconciliation and re-pairing remain host administration, with no
new identity-repair panel. See `docs/install-identity.md` and
`docs/plans/2026-10-10-hermes-closure-02.md` for migration and verification limits.

H256 local update (2026-10-10): existing owner consent actions refuse corrupt
settings before audit or grant/revoke, including the preflight-to-lock race.
The existing error response remains the UI boundary; no repair panel is added.

Session ID validation (local backend candidate, 2026-10-09): existing chat and
session routes reject a terminal newline through the corrected shared validator,
before session or memory work. Valid IDs keep their exact value; no new HUD
control or response schema is needed. See docs/project-session-id-validation-20261009.md.

Media catalog integrity (local backend candidate, 2026-10-09): new cloud-completion, ComfyUI and local OpenAI PNG catalog rows carry their producer SHA-256 checked on `md-*` delivery/export. Gallery previews remain metadata hints until download; export metadata distinguishes verified and unbound rows. No new HUD control or native negotiation is added, and legacy/other unsupplied producer rows plus standalone generated URLs remain outside this digest binding. H477 stays partial.

Client protocol discovery (local candidate, 2026-10-09): `GET /v1/capabilities` now exposes the mounted chat/session wire contracts for external clients. This is a machine-readable API, with no new HUD control; existing browser and native transports keep their tested contracts. Live readiness remains `/api/capabilities`, and `/v1` remains the legacy HUD. Wider API discovery and compatibility negotiation remain open under H477.

Native local integration (2026-10-09): completed command, memory-neighbor, advisory,
generated-image and selected-image candidates are combined with voice orb, dictation and
briefing controls. Mobile284/native137, TypeScript and Android/iOS exports pass;
mode transitions fence old dictation and image reviews. Camera permission remains absent,
while the selected-photo plugin preserves the explicit dictation microphone permission.
This does not modify browser/backend behavior or close device/live-Hub acceptance.
See mobile/docs/mobile-integration-20261009.md.

HUD text contrast (local candidate, 2026-10-09): secondary text moves from the
decorative `--ink-3` token to the existing readable `--ink-2` foreground across
CSS and inline text, including status/consent labels and SVG text. Icon-only,
stroke and background uses retain their decorative colour. Browser measurement
and remaining exclusions are recorded in `docs/hud-muted-text-contrast-20261009.md`;
this is not a claim of complete WCAG conformance or native-device parity.

H277 recovery (2026-10-08): the active chat, floating chat and cockpit image composers now review the actual selected local Ollama agent/model/session. Reviewable prior image handles are bounded to that session and cleared on restart/reload. A selected turn with an unresolved conversation ID stays disabled; changing topic or agent invalidates pending work. Owner-only selected prepare/send/history routes preserve legacy standalone VLM behavior. H18.31 now has a local native candidate for bounded photo-library snapshots, exact selected model/session review, explicit send and process-local active-history choices. It records ambiguous delivery before dispatch and requires explicit History inspection before retry; no browser or backend behavior changed. Device/live-Hub acceptance remains open. See mobile/docs/h1831-selected-images.md.

H078 recovery (2026-10-08): existing Admin Settings exposes commands.quick_commands as an initially empty JSON map. Owner /help lists valid aliases and fixed commands. Execution queues through existing approval tasks and terminal gates; no new command editor or argument templates are added. Native H18.26 catalog code is locally implemented; device/live-Hub acceptance remains open.

H063 recovery (2026-10-08): typed /new, /reset and /undo are owner commands. Chat follows the concrete ID returned by /chat or the SSE end event; Sessions reopens the exact selected transcript, and desktop synchronization keeps the selected topic. Admin exposes reset policy, channel/type overrides and stall settings. Old transcripts are retained; empty sessions restart correctly and malformed snapshots fail closed. H18.30 local continuation adds native mobile ID transitions, scoped restart persistence and stale-response fences; device/live-Hub acceptance remains open. Direct web/CLI automatic reset/stall observation remains open.

H595/H660 recovery (2026-10-08): existing Admin settings now expose the execute-code opt-in, persistent-session setting, digest-pinned session image, project/strict mode, project directory and allowed environment names. Existing sandbox status/reset remains the operator surface. Complete project context is projected read-only; unconfirmed one-shot Docker teardown retains its snapshot and reports uncertainty. Native mobile configuration and live Windows Docker acceptance remain open.

Hermes runtime (2026-10-06, PR #1233): Admin now has private runtime start/stop,
session/RPC/event controls and exact queued-action approve/deny controls. The
operator CLI uses the same authenticated API. This is intentionally owner desktop
administration. Upstream REST/PTY/SPA and native-device acceptance remain outside
this controlled headless surface; see `docs/hermes/OPERATOR.md`.

H063 (2026-10-05): channel reset/index/stall policies run on the host through
existing settings and channel ingress. No dedicated lifecycle configuration panel
was added. HUD/API chat paths retain their current lifecycle; gateway validation
does not claim new browser or native controls, live adapter acceptance, or mobile
device verification.

The Vault console displays the connected Obsidian vault, note count, exclusions,
skipped hard links, last index time and local Memory Copilot availability.
Reindex refreshes the same incremental index used by chat.

H227 inspector (2026-10-04): the existing Inspector panel now shows the resolved
model/route and distinguishes unresolved base, legacy and withheld previews.
Refresh replaces stale route/prompt details. Its estimate is a fixed empty-turn
preview; history, user input, tool schemas and active cache state are omitted.

H075/H581 Kanban (2026-10-05, partial): the pinned durable SQLite state and local
tool handlers are registered behind `llm.kanban` (default off) in the existing
owner ToolRPC/chat path. The adapted Hermes CLI is available as `nerva kanban`
and the typed owner `/kanban` command. The 46 donor HTTP method/path pairs and
command endpoint are mounted under `/api/kanban` with admin authentication;
the separate event WebSocket checks host, origin, current admin authority and
board scope. CLI/API board selection is shared and persistent. ProjectsMode now
mounts a Kanban board and task drawer. The panel reads scoped board, project,
profile and orchestration data; supports board/task CRUD, bulk task changes,
comments, local attachment upload/download and an explicit dispatch request;
it refreshes on the authenticated board event WebSocket, reconnects and polls.
The active-worker list opens each current task directly. A prerequisite task
shows its children's saved results, or their latest run summaries when the
worker left the result field empty.
Completed board cards also show a result excerpt with its source. Chat and
Cockpit can compare passages from several completed tasks in one turn. Each
passage keeps its board and task ID, and all selected sources are rechecked
before the chat request starts.
The same selection can be saved directly to the connected Obsidian inbox.
The owner reviews the passages and their source fingerprints in the note editor.
There is no tenant configuration UI yet.
Approved worker intake (`POST /api/autonomy/kanban/dispatch`) is available through
`AutonomyControlPanel` (`frontend/src/panels/autonomy-legacy.tsx`), the admin API
and coordinator with a separate default-off dispatch flag; approvals use the
existing inbox. The coordinator runs approved workers concurrently within total
and per-agent caps. A new approval can use a free slot while another board task
is running. The same stop and tier policies apply to this admission. Explicit
owner chat dispatch uses the same signed queue;
the ordinary inbound model-tool restriction is unchanged.
Advanced worker controls remain required Hermes work. Owner project CRUD is now
reachable through `nerva project`, typed `/project` and its authenticated command
transport; the project inventory reads the real scoped store. Workspace proposals
bind board/project/owner roots before approval, and registered file reads and
project conventions use the claimed worker's isolated workspace. Registered file
mutations and local-host terminal commands now create independent signed child
approvals and atomically park the parent as `needs_input`. Execution opens a fresh
scope at the persisted cwd, checks the exact source run and directory identity,
and refuses revoked roots or board inputs. Cleanup preserves active child approvals.
Automatic governed resume, crash reconciliation of incomplete intake, scoped remote
terminal targets and goal judging remain unfinished integration. URL attachments now propose
separate signed egress approvals behind `llm.kanban_network_attachments`; each
redirect requires another approval. The chat tool uses the existing Decision
Inbox. The drawer handles local files and dependency links. Worker history shows each
attempt's outcome, start, end and recorded result. For supported native attempts the
owner can check whether the worker has stopped. Recovery holds unfinished work for
review before another dispatch. Durable history remains available for older attempts.
The drawer also offers task reassignment/estimate/specify/decompose and home-channel subscriptions;
board switcher, telemetry and orchestration views consume board switch/export/import,
assignees, stats, active workers, diagnostics, runtime config, model options, draft
estimation and profile descriptions. The Nerva board reads registered agents for task
assignment; profile descriptions can be edited only on backends that support edits.
URL attachment review, backend Nerva
adapters for the 503-gated worker/config/archive routes, and native board/worker
controls remain open. This is not full Hermes parity.

The Projects board uses `/api/kanban/*` for task management and worker history.
Raw worker logs, direct process inspection and termination lack native adapters.
Governed board intake (`POST /api/autonomy/kanban/dispatch`) has its admin HUD consumer in
`AutonomyControlPanel` (`frontend/src/panels/autonomy-legacy.tsx`). Native Kanban
controls (`H18.34`) remain open even for the routes consumed by the browser. Host
CLI/chat and API bindings above are local progress; registered but unbound effects
retain explicit HTTP 503/409 refusals in the HUD until their Nerva adapters land.

Kanban client route gaps:

None — `/api/kanban/runs/{run_id}/inspect`, `/api/kanban/runs/{run_id}/terminate` and `/api/kanban/tasks/{task_id}/log` are backed by durable run/event state and wired into `TaskDrawer` (2026-11-27).

H011 checkpoints (2026-10-04): authenticated owner status/list and exact
maintenance previews now use typed `/checkpoints` and bare `/rollback` through
the existing chat routes; the host CLI uses the same owner notice contract.
These commands do not enter backend conversation history or attached context.
Owner typed commands and host CLI now support diff, selected/force restore and
index maintenance. Effects require a signed current human task, the live kernel,
exact intent/root checks and the original session lease. Only complete file
restore commits the current-last-user conversation rewind; partial effects keep
undo and conversation history. Dedicated checkpoint controls, size/retention
settings and complete checkpoint-owned payload cleanup remain open. Shared blobs
are retained. No browser or native acceptance run is claimed.

H487 terminal consent (2026-10-04): Decision Inbox shows only server-projected
reviewed categories and current session/always/deny choices. Choices submit the
exact offer revision through the admin route; changed offers reload for review.
Session-only categories retain their bound even when always is chosen. Ordinary
once/edit/reject/defer remain. Native reusable controls, Telegram cards and all
other accepted consent producers remain open; terminal-only delivery is not
full H487 or live/device acceptance.

H277 (2026-09-27): Decision Inbox renders advisory risk scores, escaped rationale,
judge identity/locality and truncation/flag warnings. Pending opinions poll with
an independent wall-clock limit per task; decision controls remain available.
Role configuration is shown beside Model Fingerprints through authenticated
`/api/llm/roles`; a role settings editor remains open. Offline component tests cover
late results, refreshes, failed reads and browser-throttled timers; this is not a
claim of a live model or native mobile acceptance run.

H18.29 native candidate (2026-10-09): the existing Approvals cards now show the
optional advisory opinion and pending state, with manual pull-to-refresh. A separate
read-only model roles view names configuration and says connectivity has not been
checked. Automatic native polling is deferred; #1233 decision-lifecycle integration,
physical-device review and live hub/judge acceptance remain open.

H277 terminal guardian (2026-10-03): trusted owner opt-in can apply a signed
one-operation smart approval to terminal tasks. Decision Inbox distinguishes
guardian DENY/ESCALATE from advisory risk scores and preserves owner controls;
pending guardian reviews have their own label. Advisory defaults remain.
Native labels/configuration remain H18.29; no live-provider/device proof is claimed.

H277 video continuation (2026-10-02): the default-off `video_analyze` tool uses the
existing Decision Inbox approval surface. Security Posture has an independent
Video analysis consent row and independent Video fallback 1–4 controls for configured
candidates. A dedicated video picker/preview, an in-HUD role editor,
inbound video ingestion, and live native-video model acceptance remain open.
The optional primary transient retry and valid-empty full-chain retry use existing
task notices/results; there is no in-HUD editor for either environment setting.
Enabled empty recovery reports its consumer-call index separately from each
route's attempt index. A malformed or blocked result does not permit this restart.

H277 OpenRouter video (2026-10-04): primary, inherited vision and fallback routes
use the same Decision Inbox and role-consent controls. The request emits the
approved provider privacy block. An in-HUD video-role/preferences editor and
video picker remain open; offline verification does not prove live model support.

H277 local auxiliary models (2026-10-02): server-side title generation, recall
rewriting, conversation review, compression and governed acquisition capability/plan
generation can use independent local model IDs. Existing output surfaces are
unchanged. The six `JARVIS_AUX_*_MODEL` environment settings have no in-HUD editor
or configuration listing yet. Acquisition retains its existing governed routes. The server can retry five nonstreaming auxiliary calls after a typed LM Studio temperature rejection; the requested temperature is initial, and the repaired call uses the provider default. No new HUD control is needed or claimed.

- **Runtime verification.** Nothing was verified against a *running* backend (the build sandbox has
  no `fastapi`). Run `python serve.py` → open `/v2`, click **every mode + every Console (▦) panel**,
  and compare against `/` (v1) / known values. The **mock‑fallback** design hides wrong‑but‑not‑
  failing wiring (a bad field map shows seed data, not an error), so this pass is essential. File
  shape‑mismatch fixes as found.

## 1. Make real‑vs‑mock visible
- ~~Surface the loader's existing `live` flag as a **● LIVE / ○ SEED** indicator (top bar + per‑panel).~~
  ✅ **DONE (verified 2026-07-04):** mode-level `LiveSourceChip` plus per-panel `PanelChip`
  make LIVE/SEED visible, and `panel-chip-coverage.test.ts` pins every Console card.

## 2. Deepen the P4c Console panels (read/basic → full)
- ✅ **Chat-command discovery (HA-4i-catalog):** the Quickbar panel reads `GET /api/commands`
  from the live registry, with usage and owner markers filtered by chat's principal. Loading,
  empty and unavailable states are distinct. This is a catalog; commands execute through chat.
  Native H18.26 now has a locally implemented Chat catalog modal using the same endpoint and
  principal credentials. It shows command, usage, description and owner tier, distinguishes
  loading/empty/error/unavailable states, supports retry and inserts a choice into the composer.
  Native device/live-Hub acceptance remains open; actual Send follows the guarded chat session path.
- ✅ **Ambient Watch (H33.6):** the Home cluster now reads the redacted live ambient runtime,
  showing monitor/source health, last policy decision, rung counts, and the single global
  attention budget. Monitor administration remains in the separately authenticated admin API;
  event content, subjects, predicates, recipients, and delivery ids are never rendered.
- ✅ **Settings DB**: full inline editor (toggle/slider/select/text per key) saves through
  `PUT /api/admin/settings/{cat}` in `SettingsPanel`.
- ✅ **Prompt versions**: `PromptsPanel` has A/B, diff, rollback, edit, preview, and commit controls
  over `/api/admin/prompts/{id}/*`.
- ✅ **Data Spaces**: list/create/delete plus assign/unassign controls are live in `DataSpacesPanel`
  over `/api/memory/spaces` and `/api/memory/spaces/{assign,unassign}`.
- ✅ **Secrets / Capabilities**: the secret store form is live in `SecretsPanel`, and
  `CapabilitiesPanel` can issue tokens, keep recent grants visible, and check a
  token/capability pair through `GET /api/security/capabilities/check`.
- ✅ **Capability Registry**: `ReadinessPanel` reads canonical `GET /api/capabilities` and
  shows readiness, risk, supports, and confidence without fabricating verification.
- ✅ **Rooms**: create + send with `@mentions` are live in `RoomsPanel`, and the selected-room
  history drawer reads `GET /api/rooms/{id}/history`.

## 3. Per‑mode live‑wiring depth
`api/live.ts` wires the headline data for Memory / Observe / Interop / Autonomy / Trust / Admin.
PR #505 adds base LIVE/SEED gates for Build / Comms / Finance / Health / Knowledge / Family,
with plugin-configured checks instead of seeded success. Still open:
- **Build**: base live wiring reads workflow DAG + skills marketplace + sandbox from
  `/api/workflows`, `/api/skills/marketplace`, and `/sandbox/status`. Create/edit is closed
  (DRA-28): the Console's `WORKFLOW BUILDER` panel replaces the read-only step generator —
  generate a step, append it to a draft, and save through `POST /api/workflows` /
  `PUT /api/workflows/{id}` (admin), with the 422/401 refusal rendered inline. The steps
  textarea stays the editor of record for the advanced `router`/`critic`/`loop`/`subflow`
  configs; a graphical DAG canvas for v2 was **dropped by owner decision 2026-09-01** (BUG-2b.2):
  the JSON-paste `WORKFLOW BUILDER` panel is the v2 editing surface of record; the legacy v1 HUD's
  `WorkflowCanvas` (`agents/web/static/workflows.js`) does exist and retires together with the v1
  HUD (§8 / AUD-15) — ported only on demonstrated demand, as a fresh spec with its own id.
- **Memory**: DW-1 replaces the live mode's sample graph with read-only entity search,
  selection and connected-entity navigation over `GET /api/kg/entities` and
  `GET /api/kg/entities/{name}`. Reads use current user credentials, a ten-second deadline,
  a one-MiB response bound and 100 displayed entities/relationships; cancelled or superseded
  reads cannot replace the current selection. Empty/unavailable data stays explicit. Recalls
  use real search results with no sample fallback, and headline statistics remain unchanged.
  The sample graph, recalls, topic freshness bars and historical slider appear only in explicit
  Demo. Live decay ranking and bitemporal as-of navigation remain open. Relationships are
  presented without directional or semantic-distance claims; this is no 3D embedding map.
  Native H18.28 has local Graph navigation and stale-read guards over the same KG routes;
  focused native/API tests pass, while device/live-Hub acceptance and integration remain open.
  React Native verifies the one-MiB response bound after `Response.text()` on transports
  without a reliable stream reader, and rejects an oversized `Content-Length` before reading.
- **Trust**: real `%‑local` meter (needs a locality/cost summary endpoint, §6).
- **Autonomy**: per‑agent AUTO/ASK/OFF **policies** (settings‑backed).
- **Comms**: rooms and the live channel inbox feed the mode. The Console now
  has a Safe Comms draft surface over `GET/POST /api/integrations/social`, so X post/reply/DM drafts
  enter the existing approval queue/preview path instead of sending directly. #551 adds
  channel inbox transport v0 for telegram/web: inbound threads persist through
  `GET /api/channels/inbox*`, live rows show a governed reply composer, and replies queue through
  `POST /api/channels/inbox/{thread_id}/reply` before approved sends use the live channel manager.
- **Finance / Health / Knowledge / Family**: base mode switching is plugin-gated. Finance reads saved
  watchlist/payments and keeps `balance` mock payloads as SEED; Health waits for the Apple Health LAN
  bridge; Knowledge waits for configured websearch backend; Family has no live source
  (the WhatsApp bridge plugin was removed on 2026-11-25).
- **Dossier**: wire to `/api/agents/{id}/soul` + `/memory/{id}` + run history `/api/agents/{id}/history`
  (currently reads the `DOSSIER` mock).

## 4. Cockpit / signature interactions
H18.24 native continuation (2026-10-09): a local SVG orb candidate in Chat follows
actual TTS playback events, labels preparation separately, and cancels late playback
after stop or a hub change. Reduced motion and background state pause animation.
Native Chat now has a local explicit dictation candidate: bounded capture, fresh
mic trust and permission checks, stopping state, and local STT draft insertion.
The H18.25 local wall candidate now adds a bounded SVG tier field, source-backed
stat cards and chips, and a default-hidden spoken line in Chat. It preserves
unknown-source semantics and cancels background/scope-stale updates. Physical
device/live STT acceptance remains open. The separate source-card candidate adds
returned approvals, a calendar sample, local-model/voice reports and heartbeat
schedule counts, with unknown data kept explicit and private details discarded;
see `mobile/docs/h1825-briefing-wall.md` and `mobile/docs/h1825-briefing-sources.md`.

- ~~**Network task‑fan**: v2 `NetworkBrain` doesn't render per‑agent task dots from `/tasks` (v1 did) —
  the old task fan exists in `network.tsx`, but the current cockpit renders `NeuralMesh`; integrate
  live `/tasks` dots into the current mesh or retire the stale `NetworkBrain`.~~
  ✅ **DONE (2026-07-04, #521):** `app.tsx` passes the existing live `/tasks` state into
  `NeuralMesh`, which renders honest task spokes/dots plus a visible task count; empty or
  unknown-owner queues render no invented fan.
- ~~**Per‑message TTS** (🔊 → `/tts`) + **browser mic / SpeechRecognition** input + voice auto‑speak.~~
  ✅ **DONE (verified 2026-07-04):** `cockpit.tsx` renders per-message replay via `playTts`,
  `InputBar` toggles the `useVoice` loop, and `app.tsx` wires mic → local STT → turn → speak.
- ~~**Sentence-level TTS streaming** (H5.16)~~ ✅ **DONE (verified 2026‑07‑02)** — `voice.ts`
  `speak()` tries `streamTts` first (framed chunks played back-to-back, `voice.ts:206`) and falls
  back to whole-reply `/tts` on 409 when the server opt-in is off. *Remaining H5.16 tail lives in
  BACKLOG (synthesize mid-stream; browser wake-word).*
- ~~**Streaming cognition**: upgrade to a real SSE stream.~~ ✅ **DONE (verified 2026-07-04)**, then
  **retired (2026-11-24, Phase B):** the cockpit trace that drew the stream's frames as four stages,
  with timings and routed agents the chat stream does not report, went with the HUD v2 shell; the
  working reply shows what the stream says. The route stays served and is on the parity gate's
  uncalled list (`tests/test_hud_v2_parity.py`).
- ~~**Strict-local / mic trust badge** (H12.10).~~ ✅ **DONE (verified
  2026-07-04)**; since Phase B the running head's Egress and Microphone items say it, from the
  trust payload read fail-closed (`frontend/src/signals/trust-signals.ts`).

## 5. Settings / preferences UI
- ~~The design‑only `TweaksPanel` was dropped. Accent + language persist (palette toggles), but
  **look / density / motion / scanline / dotgrid** aren't user‑changeable in‑app (defaults only) —
  add a small settings menu (or a gated tweaks panel) that changes + persists them.~~
  ✅ **DONE (2026-07-04, #523):** the command palette now exposes look, density
  (compact/normal/comfy), motion (lively/calm), scanline, and dotgrid controls; all are
  client-side HUD preferences persisted by `App`.
- **Themes and Personalisation (2026-11-23, branch `claude/hud-redesign`, not merged):** the
  HUD moved to the **Ledger** design as its default and every screen takes its visual language
  through a theme system (`frontend/src/theme/`, contract in `frontend/src/theme/CONTRACT.md`).
  Nine looks: Ledger (default), Presence, Briefing, Workbench, Threshold, Console and Atlas, each
  with a dark and a light scheme, plus Classic Obsidian and Graphite (dark only). A new
  `scheme` preference (`dark` · `light` · `system`) syncs with the other appearance fields
  (server `agents/core/appearance.py`, `PUT /api/preferences/appearance`). The owner switches
  theme, scheme, density, motion, typeface, language and the Classic accent on **Settings →
  Personalisation** (`/v2/console/appearance`), a page with live previews; the command palette
  keeps its Look rows and adds the new looks, the scheme rows and "Personalisation…".
  Native follows the look's palette but not the scheme (`mobile/PARITY.md`).
  The Ledger page structure (masthead, Home with the day, the conversation and the docket, nine
  areas) is built (Phase B, 2026-11-24; "The HUD's structure" at the top of this file); the
  palette's rows live on in the Ctrl K sheet, word for word.
  *Still open:* Literata and Barlow are self-hosted (`frontend/src/theme/fonts.css`); Barlow Semi Condensed
  (Threshold, Console) and Source Sans 3 (Briefing) are not, and render in their stand-ins.

## 6. Toolchain / CI hardening
- ~~**CI frontend‑build + stale‑bundle guard**~~ ✅ **EXISTS** — the `hud-v2-build` job in
  `.github/workflows/ci.yml` runs `npm ci` → `tsc --noEmit` → vitest → `vite build` and fails
  if the committed `agents/web/v2` differs from a fresh build. *(This line was stale — noticed
  2026‑06‑10 while re‑checking the punch‑list.)*
- ~~**OpenAPI types**~~ ✅ **DONE 2026-07-03** — `frontend/src/api/schema.gen.ts` is generated from
  the live FastAPI `/openapi.json` via pinned `openapi-typescript`; CI boots the backend,
  regenerates, and fails on a schema diff. Consumer migration remains gradual by design.
- ~~**Self‑host fonts**~~ ✅ **DONE (2026-07-04, #525):** HUD v2 now vendors
  local Latin-variable WOFF2 assets for Space Grotesk + JetBrains Mono and loads them
  through `@font-face` in `frontend/src/styles.css`; runtime font-network dependency is removed.
- **ESM cleanup**: the ported prototype files keep an `import { … } from './ui'` barrel + loose types;
  tighten to real per‑module imports + TS types over time.

## 7. Backend additions (from the plan §6)
- ~~`GET /api/cognition/stream` (SSE)~~ ✅ **DONE** and consumed by the cockpit. Provenance on the
  chat stream is already surfaced via the existing provenance chip/modal.
- ~~`GET /api/analytics/locality`~~ ✅ **DONE 2026‑06‑10** — computes %‑local from the run‑history route field; HUD Trust meter prefers it, falls back to strict‑local proof, never fabricates a split (`local_pct` null until real routed runs exist).
- Howard ingestion API — only if we ever surface the digital twin (currently `NOT_IN_HUD`).
- ~~Emergency-stop control~~ ✅ **DONE 2026-08-29** (2026‑08‑28, hermes v2026.8.27 port): Admin
  mode now carries the "AUTONOMY PAUSE (ESTOP)" card over `GET /api/ops/estop` +
  `POST /api/ops/estop/{engage,resume}` — two-step confirm with optional reason, engaged
  reason/timestamp shown, single-click resume; typed wrappers in `frontend/src/api/actions.ts`,
  the three routes removed from the parity punch list. Named distinctly from the Trust
  kill-switch ("EMERGENCY STOP · halt all agents"), since estop only pauses NEW autonomous work.

## 8. Cutover (P6 follow‑through)
- Once verified, flip the default: `JARVIS_HUD=v2` (or hardcode) so `/` serves v2; keep `/v1` as the
  escape hatch; then archive the old `agents/web/` HUD and update `README` / `STATUS.md` / `NERVA.md`.

## 9. Known infra issue — ✅ resolved (2026‑08‑31)
- The old note here said CI **`Analyze (python)` (CodeQL)** intermittently failed because code
  scanning was unavailable on a private repo. That is overtaken: the repo is public, code scanning
  is enabled, and the analyze step uploads SARIF successfully (run 33384718270 logs *"Analysis
  upload status is complete."*). Settled posture: **CodeQL = advisory, push‑to‑main + weekly, not a
  required check, fails loudly on analysis/upload errors** (`continue-on-error` removed
  2026‑08‑31). The only remaining action is owner‑side — drop `Analyze (python)` / `CodeQL` from
  required status checks and delete the code‑scanning merge‑protection ruleset
  ([`OWNER_TASKS.md`](../OWNER_TASKS.md) §GitHub settings).

## 10. Parity re‑audit — 2026‑06‑10 (backend moved ahead again)

H022 host dependency audit (local, 2026-11-04): `nerva security [audit]` inventories
the invoking host, then uses admin `POST /api/security/dependencies/audit` for
kernel-mediated OSV lookup. This CLI contract intentionally has no HUD/native
inventory panel: those clients run in different environments. Offline, skipped
and incomplete coverage are reported separately from a completed audit. The
endpoint is classified as machine-facing in the parity gate; no live OSV or native
acceptance follows from the repository's synthetic transport tests.

The 2026‑06‑09 backend waves (PR #178/#180) shipped new surfaces **with no HUD controls**, on top of
the still‑open depth items above. Snapshot: backend ≈299 routes; HUD v2 actively calls ~50, partially
~10; **~37 write/recent endpoints lack any UI control**. New since the 2026‑06‑05 plan:

- `GET /api/cognition/stream` (SSE, NTH‑1 ✅ backend) — consumed by the HUD v2 cockpit trace until
  Phase B retired that trace (2026-11-24); still served, now uncalled.
- Sender pairing gate (H12.19, 4 routes) — not in Comms.
- Cloud auth‑profile rotation (H12.20, `GET /api/llm/auth-profiles`) — not in Admin.
- Transcript → governed tasks (H12.25, `POST /api/transcripts/ingest`) — no surface.
- A2A approval inbox (H16.2 `/api/a2a/inbox*`), payments lifecycle actions (H16.3
  approve/reject/settle), marketplace review (H12.12) — read‑only or absent in Trust/Build.
- Still missing interactive controls (carried from §2–§5): preference-learning suggestions.

**Conclusion:** coverage gate still green (nothing silently dropped), but the *depth* gap regrew.
Tracked as **TASK‑2** in `BACKLOG.md`; estimated 3–5 PRs (~2–3 weeks part‑time) to "nothing missed".

### 2026‑06‑10 depth pass (same day, PR #181) — the control gap is CLOSED

All ~37 missing **write/recent controls** above now have live HUD surfaces (Console panels in
`frontend/src/gap.tsx` + Trust mode + cockpit):
cognition SSE stream (cockpit live trace) · payments approve/reject/settle (Trust) · sender
pairing approve/reject/block + code (H12.19) · injection scan (H17.1) · transcript→tasks ingest
(H12.25) · escalation targets+send (H12.11) · reflection status+run · heartbeat run/start/stop ·
bench promotion (`/learning/promote`) · marketplace review ✓/✕ (H12.12) · eval runs + compare ·
AI step builder (H10.7) · sandbox execute (DEV_MODE‑gated, honest 403) · agent templates
(H10.29) · LM Studio server/load/unload · cloud auth profiles (H12.20). Admin‑guarded calls now
send the admin token (`actA`). +7 frontend tests (19 total).

**Still open (the tail of TASK‑2, re‑verified 2026‑07‑05):** O26-P3.1 closes the §3 plugin-gated
base wiring in #505 (Build/Comms/Finance/Health/Knowledge/Family), and the Safe Comms draft panel (#527)
closes the draft-before-send UI over existing governed social actions. #551 adds
channel inbox transport v0 for telegram/web. Remaining:
owner live-data/plugin setup (bank/broker/quotes, Apple Health bridge, websearch backend, WhatsApp
bridge/frigga live data) and non-v0 inbox channels.
Estimated 1–2 PRs after #505 for owner-gated/plugin work.
*Since‑closed items previously listed here:* CI stale‑bundle guard ✅ (`hud-v2-build` in `ci.yml`),
§7 locality endpoint ✅ (`GET /api/analytics/locality`, consumed in `app.tsx`/`shell.tsx`), and the
BUG‑17 audit‑verify Trust chip ✅ (`modes.tsx:117-165` renders the live
`GET /api/security/audit/verify` verdict), the 0.39 saved‑watchlist `WatchlistPanel` ✅, and
per-panel LIVE/SEED chips ✅ (58/58 Console cards declare a `PanelChip` signal). Data Spaces
assign/unassign controls ✅. Rooms selected-history drawer ✅. Capability issue/check UI ✅.
Current-mesh task fan ✅. Preferences/tweaks UI ✅. Self-hosted fonts ✅. Safe Comms draft UI ✅ (#527).
Safe Comms channel inbox transport v0 ✅ (#551).
O26-P3.2 adds a Vitest reconciliation guard so this document cannot re-list shipped
TTS/mic/cognition/trust or Console controls as missing.

**O29 Media Director (2026-07-13):** the default-off `/api/media/*` device, session, present,
and restore surface is live in the Console Build cluster. `MediaDirectorPanel` separates the
read board, explicit user presentation/restore controls, and admin-authenticated registry
controls; queued approval, kernel refusal, nested `output.ok=false`, and driver-verified success
are rendered as distinct outcomes. The panel displays bounded metadata only and never embeds
remote media. `tests/test_hud_v2_parity.py` pins every Director route to the live Build surface.

**H30.5 House Brain / H31.5 Camera Intelligence:** removed 2026-11-25 by owner decision (`docs/decisions/2026-11-25-nerva-finish-line.md`). `HousePanel`,
`CameraPanel`, their console routes and the `/api/house/*` and `/api/cameras/*` surfaces no longer exist.

**H32.6 Capability Acquisition (2026-07-13):** the default-off `/api/acquisition/*` surface is
live in the Build cluster. `AcquisitionPanel` separates user-readable lifecycle/reuse/package and
hash-only audit state from the admin-authenticated revoke, rollback, export, and exact-confirmation
purge controls. It never renders request goals, source extracts, receipt bodies, package paths, or
full correlation hashes. Native parity is deliberately read-only over the same bounded user APIs.

**H28.4 Operator depth (completed 2026-07-14):** Console → Build now hosts a dedicated
`OperatorPanel` over the four existing browser check/plan-preview and desktop preview/run routes;
no route or governance bypass was added. Browser policy and plan checks are dry-run only and expose
no Run control. Desktop submission is preview-first: editing invalidates the preview, and submit
uses the deep-cloned canonical snapshot. The result reducer distinguishes proposed, queued,
blocked, failed, partial, and executed outcomes, with an explicit warning against whole-plan retry
after partial execution. Native mobile hides `toolrpc.desktop_run` payloads and omits Approve while
retaining Reject/Defer. Evidence: `operator-contract.test.ts`, `operator-panel.test.tsx`,
`gap-panels.test.tsx`, `approvalsDesktopBoundary.test.ts`, and the strengthened
`tests/test_hud_v2_parity.py` caller gate.

**H34.1 Mission Control (2026-07-24):** the swarm cockpit ships as a **standalone
brain.html-pattern page** at `/mission-control` (self-contained dark HUD; polls the new read-only
`GET /api/swarm/summary`; steering reuses the existing governed autonomy/missions/A2A endpoints
with the shared `hud.admin_token`). Both routes are mapped to `observe` in the parity RULES.

**H34.4 SwarmPanel (2026-08-10, done):** a React `SwarmPanel` inside Console → Observe reads the
same `GET /api/swarm/summary` feed read-only — kernel halt/armed status, the autonomy funnel,
workspace counts (missions/workflow runs/sub-agents), the A2A inbox when enabled, and which
dev-swarm agent (`claude`/`codex`/`opencode`/`antigravity`) currently holds a `lock.py` lock — then
links out to the standalone `/mission-control` page for the full HITL controls. Zero new backend
route; the cockpit is now one keystroke from chat, and the standalone page stays either way.

---
**HA-4i local images (2026-09-09):** the optional ComfyUI backend is reachable through
the governed `image_generate` proposal and existing approval queue. **Composer and selected
result view delivered:** Console → Build → Images shows configuration as untested, proposes
the exact prompt, hands approval to the existing Inbox and observes one exact task through
an admin-only state projection. Only a validated successful artifact is fetched as bounded,
authenticated PNG bytes for a revocable browser preview/download. Lost POST responses remain
uncertain with no automatic retry. Reopening/hard refresh clears panel state; entering the
known task ID resumes observation without resubmission. A persistent gallery, owner-host
ComfyUI proof and native presentation (H18.27) remain open. The production approval
bridge supports `off` and `enforce`; `hold` intentionally refuses execution.
Per-conversation access isolation is not added by this surface.

H18.27 native continuation (2026-10-09): a local Media-screen candidate adds
configuration-only local status, exact-prompt proposals through the existing approval
queue, task restoration across the approval handoff, manual status refresh and
authenticated PNG preview/save. It does not initiate cloud generation or repeat a
proposal automatically. Real-device/live-generator acceptance stays open. The server
projects three exact, normally completed cloud provider-response failures, five
typed local OpenAI-compatible response failures and the documented ComfyUI history
error shape as `failed`. Local adapters persist fixed producer markers; legacy
rows without them stay uncertain. The ComfyUI marker requires the matching prompt
history with exact error/false status fields; malformed or incomplete history is
not enough. Verified cloud artifact recovery keeps precedence. Web/native readers
state that no usable image was verified and add no preview or automatic proposal.
Generic failures, malformed results, ambiguous delivery and withheld output remain
`uncertain`; native cloud proposal controls are unchanged. See
[cloud evidence](../project-image-provider-failure-20261009.md),
[typed local evidence](../project-local-image-response-20261009.md) and
[ComfyUI history evidence](../project-comfyui-response-20261009.md).

**HA-4i extension inspection (local V44/V46/V47, 2026-11-13):**
Console → Build → Extensions now reads user-guarded `GET /api/plugins/extensions`.
It separates declared and currently callable tools/commands, required arguments,
observation events, signature verification and approval. Disabled/uncomposed/error
states remain explicit; failed refreshes hide previous metadata. Mobile Status has an
opt-in equivalent. Neither view activates code or grants consent. Offline tests and
build checks cover these surfaces; live browser/device acceptance remains unverified.
Native third-party UI injection remains excluded. See `docs/EXTENSIONS.md` and the
cumulative local continuation checkpoint for exact executed evidence.

*Parity gate (`tests/test_hud_v2_parity.py`) tracks all routes → every one is mapped to a v2
surface or `NOT_IN_HUD`, so nothing above can silently disappear — these items are about depth, not
coverage.*


<!-- models-context-2026-09-15 -->
Model/session context: backend clock and request shaping apply across channels. Existing /admin metadata exposes compatible provider/model, explicit cache/effort capability toggles, per-model vocabularies and Ollama num_ctx. Dedicated mobile/HUD model controls remain a UI gap; no new routes or mobile controls are claimed.

### H178 native floating chat — 2026-09-15

Desktop-only: Tauri tray/main controls open a frameless chat using the existing HUD
conversation and authentication; geometry recovery and handoff are implemented.
Mobile retains its normal chat. macOS host validation covers the bounded window
surface; Windows/Linux, compositor-exclusive overlays, transparency/frost, click-through,
global shortcuts, move-to-pointer and underlying-window capture remain unverified or unimplemented.
See `desktop/README.md`; full Hermes H178 remains partial.

### 2026-09-15 — scheduled automation depth (H146/H449)
Jobs now wires all admin diagnostics/tick/notepad routes and adds a sixteen-card typed
blueprint gallery, custom four-action builder, full action/options editing and visual schedules.
Per-job repeat counts attempts, including failures; manual runs cannot exceed the bound.
Explicit configured channel names retain owner destinations and existing delivery gates.
Remaining: isolated per-job provider/model/workdir/toolsets/skills, cross-profile listing and
real scheduler/channel proof. Tick uses the active application timezone (including DST) and refuses to compete with a live scheduler.

H146 followup: the topbar Automations entry now opens a roomy dedicated Jobs workspace;
Console integration remains. (Since Phase B the top bar is gone: the workspace is Work › Scheduled
jobs, `/v2/jobs`, also found by Ctrl K under "Automations".) Custom creation uses a native modal with initial focus,
Tab containment, Escape/cancel and focus restoration. Browser proof uses mocked job reads;
no live channel was enabled. Generated OpenAPI types now include all four added job routes.

2026-09-15 — H12.26: Artifacts now includes default-off binary upload, authenticated
preview/download, pin/delete and honest errors. Supported magic-sniffed image,
audio, video and PDF only; active formats and office documents remain refused.

2026-09-15 — H515/H518: Images exposes configured local backend/checkpoint selection, up to four blended references and explicit 2× bicubic upscale. Media Gallery searches and downloads supported catalog/cache/attached files through authenticated object URLs and exports visible supported rows to ZIP. Runtime ComfyUI proof remains unperformed.

2026-09-27 — H517 local provider slice: Images reads per-backend protocol/model
and edit/upscale capabilities. A configured `openai_images` service can generate
through the same Inbox/worker/artifact path; switching from ComfyUI clears
incompatible edit/upscale fields. Default-backend models no longer assume ComfyUI.
See [configuration and limits](../hermes/local-image-providers.md). Arbitrary
adapters, other media registries, live service proof and native controls remain open.

2026-09-15 — H684: Jobs doctor displays the additive structured health report through the existing diagnostic control. Backend and CLI detect scheduler stalls and stored failures. Script/no_agent/workdir options and production-host proof remain open.

H129 (2026-09-15): all 18 existing HUD modes and 113 console panels have explicit URLs, history, titles and lazy loading, with selected-panel focus and mobile navigation. Profile/plugin routing remains outside the implemented single-owner route registry. Browser smoke is local and backend-stubbed.

### 2026-09-27 — H487/H513 integration

Decision Inbox supports bounded human reasons, verified owner-submission group cards,
one-use approval with follower promotion, and atomic group rejection. Legacy Actions
provides the same grouping controls for action requests. Model-originated and browser
requests without a trusted grouping context remain separate; full H487 is partial.

Security Posture shows declared provider policy, warnings that persist after consent,
and allow/revoke controls bound to the configuration displayed. Unavailable or
ambiguous consent cannot be granted. Routed agent/tool-loop/cache dispatch rechecks
consent; independent direct provider clients are outside this increment.

The approval judge now has its own consent row and allow/revoke controls. Provider
and role setting failures disable their respective controls independently. The role
acknowledgment never enables remote judging and never inherits a provider grant.

Governed image empty recovery (H277, 2026-10-02) discloses its optional one-call
retry budget in the composer before remote acknowledgment, and beside policy notes
in local describe/screen panels. Refreshing a changed binding clears the previous
acknowledgment. The environment setting has no HUD editor; native mobile rendering
and live model acceptance remain open.
Native image/video normalization now supplies visible text first, then typed
reasoning fallback through the existing answer surfaces. This requires no new HUD
control or schema; provider errors/malformed mixed output remain failures rather
than displayed model answers. Browser/device acceptance is separate.

Composer image status and successful results now retain a visible data-policy
warning. The existing per-destination remote checkbox remains request-scoped;
provider/judge consent cannot replace it. No unattended vision grant was added.

Decision Inbox displays an explicit approval deadline when the owner task API
supplies one. A missing or unreadable field preserves legacy cards. Approval stays
single-use, with the backend deciding whether the deadline has passed; the UI adds
no client-side authority or automatic approval. There is no general task creation
form in this panel, so deadline authoring remains the existing owner task API.

The independent VLM Describe and Screen Reflex panels show declared policy notes
and retain response warnings. Both align with strict loopback inference on the
Nerva server; the legacy describe remote checkbox is removed. Failed or empty
inference does not render as a successful description. These interactive routes
now have scoped dispatch checks; the standalone screen-locator has no verified production caller.

Trust now includes a separate Telegram image-description role, with local-server
requirements and independent configuration-bound acknowledgment/revocation. Unknown
role IDs have no controls. Judge/provider compatibility and unavailable-store
feedback are retained.

The camera-description model-data controls were removed with camera intelligence (2026-11-25).

2026-09-27 — Voice → Command providers now works with task mediation set to
`enforce`, using the existing Decision Inbox card and human approval. `hold`
continues to refuse registration. No new provider picker is delivered by this
backend prerequisite: multiple named speech providers and the shared media
registry remain open under H517/H613.

2026-09-27 — The subsequent named-provider slice adds independent TTS/STT rows,
registration/update requests, per-name clear (including pending-only requests),
explicit STT selection and exact name/revision on Inbox cards. Missing saved
selections remain visible as unavailable. Image and speech dispatch now use the
common registry. Full vendor/plugin/setup breadth remains open under H517/H613;
native mobile provider configuration is still a gap.

Task 10A/10B (2026-10-28/29) provides owner-only encrypted credential management
at GET/PUT/DELETE `/api/admin/llm/provider-credentials`, and explicit signed-model
selection at GET/PUT/DELETE `/api/admin/llm/provider-selection`. Responses expose
only configuration, revision and generation metadata. The selected runtime now
covers all six declared cloud dialects through guarded DNS/IP/Host/SNI sends and
body-lifetime mutation fences, with local synthetic owner/Kernel/Vault evidence.
HUD package review, key entry, risk acknowledgements, select/status/clear and
lifecycle controls remain open. A package-status `selects_model: false` means that
installation itself makes no selection; read the separate selection API for the
current binding. No live provider, billing, Docker or native-device readiness is
claimed by these API controls. H361 remains partial.

H512 authentication audit continuation (2026-10-09): the existing admin audit reader
shows typed HTTP guard and managed token lifecycle events through `GET /api/admin/audit`.
No new route or dashboard control is added. The native audit reader remains open
in `mobile/PARITY.md`; native bearer requests are covered by the shared server guards.
The broader login/session/WebSocket/native-auth event contract remains incomplete.

H161/H328 closure (2026-10-10): the existing pressure banner receives the same
response shape, with recovery now confirmed per volume even when another probe
fails. Existing skill offers recognize the native Kanban and other supported
toolset members. No new HUD control or route is needed; native pressure-banner
and dismissal presentation remains a mobile gap.

H450 closure (2026-10-10): schedule preview, job creation/editing, cron triggers,
status and fallback tick share the runner's active application timezone. Saving
a new timezone applies to running jobs after restart; absolute one-shot instants
stay unchanged. The existing Jobs workspace uses the corrected preview route.
Native job administration remains open in `mobile/PARITY.md`.

H512 MCP token continuation (2026-10-10): successful `/api/mcp/token` signing adds
a `token_issued` row with literal `surface=mcp` to that same admin audit reader.
The admin authorization row remains separate; minted credential tier is `user`.
No endpoint or UI control changes. The native audit reader and broader H512 event
coverage remain open, and the bounded audit queue still permits dropped events.

DRA-59 local observability (2026-10-09): Autonomy Control now reads admin-only
`GET /autonomy/mediation` and displays the effective queue mode separately from
evidence validity. Only verified recorded event counts are shown; unavailable,
malformed and refreshing states hide numbers. The section has no enable, approval
or raw-event control. B7 operational acceptance and broader task coverage remain
open. H18.32 now provides the local native Status counterpart with strict snapshot
validation and connection/read-order fences; physical-device/live-hub acceptance
remains open in [native evidence](../../mobile/docs/h1832-task-mediation-status.md).

### H686 current-turn duration — 2026-10-09 local candidate

Cockpit and focus chat share a duration strip from the optional `outcome.latency_ms`
on the current SSE end. The measured interval is the public orchestrator invocation,
including cleanup; it is not network round-trip time or model-only generation time.
A normally returned command or refusal may have a duration. Errors, cancellation and
uninstrumented turns have none. Selection is applied by the backend from the ordinary
Admin Settings `display.status_bar_fields` list (default `latency`; empty hides it).
The strip clears on new work or session/agent/demo changes and is not transcript history.
TPS and the complete H686 model/context/cache/compression vocabulary remain open;
Task33 extends the same outcome after its own review. H396 now supplies the whole-turn
completion/accounting fields described below. H18.33 adds a local native current-turn strip
using the server-selected SSE outcome, with strict validation and ephemeral state.
It clears on work/context changes and never enters stored history; physical-device
and live-Hub acceptance remain open. See `mobile/docs/h1833-turn-duration.md`.

H396 whole-turn outcome — current local source (2026-10-29): cockpit and focus chat
consume one request-owned `outcome` on JSON replies, SSE progress and SSE end. The
strip presents a consolidated source-assigned reason, proposed/queued/executed tool
counts and observed provider output or an explicitly labeled visible-text estimate.
Accepted tool results without a successful consuming model completion produce WARNING;
a normal answer does not claim objective success. Approved file attempts carry a
signed task/turn origin and physical-attempt identity. Bounded no-follow readback at
the effect boundary distinguishes verified, unverified and unknown; only a later
verified same-target attempt supersedes a failure. The footer uses ordinal/operation
and disposition, never a path or file contents. Closed replies cannot be rewritten by
later owner approvals. Native mobile currently reads latency only; the new completion,
accounting, output-flow and file-footer counterpart remains a mobile surface gap.
Synthetic source and mounted HUD tests are recorded separately from a live owner run.



### H444/H576 document input limit — 2026-10-09 local candidate

Parser-backed file_read now refuses observed PDF/DOCX inputs above 50,000,000
bytes before parser discovery. Existing tool-result handling carries the named
refusal and raw byte paging remains available. This is a backend admission check.
See `docs/project-document-input-limit-20261009.md`.

PDF reads now report significant ranges without extracted text in separate,
bounded tool-result metadata: more than 20% of pages or at least ten pages,
first 16 ranges, preceding 160-character source excerpts and explicit omitted
range counts. Text bytes and pagination are unchanged. Existing model/tool
handling carries the warning; a dedicated HUD PDF coverage card is not added.
This does not identify scanned content or run OCR. See
`docs/project-pdf-text-coverage-20261009.md`.

Explicit OpenRouter vision (H277, 2026-10-02): the existing composer model,
destination and policy display covers the new server-side provider. Its remote
checkbox still names the destination; live routing changes invalidate that
binding. The composer now displays separate unchecked training/cost confirmations
when requested by the server, requires all of them before send, and clears them
on image changes, refresh or draft clear. Unknown/malformed disclosures refuse;
remote acknowledgment is independent. Signed OpenRouter video remains unfinished.

Explicit DeepInfra vision (H277, 2026-10-02) now uses the existing composer. With
no explicit model, opening image status prepares a catalog selection; Refresh vision
destination forces a new catalog lookup and clears confirmations. Failed refresh
revokes the old selection. Metadata discovery sends no images, and remote inference
still needs the reviewed destination and any separate training/cost confirmations.
Native mobile acceptance remains open.

Nous account lifecycle (H277, 2026-10-02) is currently CLI plus owner API only:
login/status/poll/logout. The HUD has no Nous account-management controls yet.
This is explicit UI debt; account authentication alone does not select a provider.
Explicit Nous vision now uses the existing image composer, model/destination
display, refresh and confirmation controls. Status prepares an account-bound
recommendation; image POST only uses that prepared selection. Chat/Messages wire
changes invalidate confirmation. No account-management UI is claimed by this
server integration.

Opt-in automatic image selection (H277, 2026-10-02) shows the chosen provider
alongside its model and destination before remote confirmation. The server tries
OpenRouter, Nous and DeepInfra in order when available; the composer has no
selected main conversation route to reuse. Refresh may prepare metadata, while
image POST makes no replacement discovery. A provider or policy switch clears
the reviewed binding. Native provider controls and live acceptance remain open.
The composer now prepares a destination review for its current prompt and agent
and uses a one-use token for image submission. Prompt or agent edits invalidate
the visible review; a changed route, key or policy requires another review
before image bytes leave the server. This preparation still selects the
configured vision route rather than inheriting the active conversation backend.
Native image-review parity and live-provider acceptance remain open.

Selected main image turns (H277, 2026-10-02) now commit through
`/api/vlm/composer/chat-prepared` after the one-use review, session lease and
physical destination guard. The HUD restores the answer from `GET /memory`
using bounded image provenance. Standalone and auxiliary image descriptions
remain transient; native mobile image intake and live-provider acceptance are
still open.

H067 HUD stream continuation (2026-10-05): the actual /chat/stream emits live
clarification questions. The HUD offers choices, multiple selection, Other,
free text and cancellation, using the guarded /chat/pending/{prompt_id}/answer
route to resume the same model call. Only the original currently authorized
credential/role can answer; disconnect, expiry or credential revocation retire
the wait. Enable the existing Chat clarification preview and restart to use it.
Question delivery is acknowledged by the SSE generator before human-wait credit.
Rejected or failed answers remain visible for retry. Stop cancels the stream.
This closes the streaming HUD producer slice only; nonstream HTTP, email, CLI
and busy prose/other commands remain open under partial H067.

H067 nonstream HTTP continuation (2026-10-05): /chat uses the same authenticated
pending runtime. Concurrent GET /chat/pending (optional session_id, bounded
offset/limit) returns only the caller's live questions; the existing answer route
continues the original request. Delivery acknowledgement follows the discovery
response body, so failed sends cannot permit answers or human-wait credit.
The responsive HUD continues to use SSE. Native mobile has no pending question
picker/poller or answer UI; this API addition does not establish mobile parity.
CLI/email producers and busy prose/other commands remain open under partial H067.

Final inventory assessment (2026-10-05): H067's canonical gateway contract is
accepted as equivalent. The HTTP/HUD adapters above remain implemented. CLI,
email and ordinary busy-message improvements belong to their own contracts;
they were mistakenly treated as additional H067 gates in earlier checkpoints.
Native mobile interaction and full697/live acceptance remain open separately.

H660 resident execution continuation (2026-10-05): once code execution is enabled
and a pinned isolated image is configured, the existing kernel panel reports the
resident mode without a second opt-in. Explicit sessions=false remains an owner
override. Code cells and model-requested reset require an explicit GRANT; policy
is rechecked after the interpreter lock. No HUD/API schema or native-mobile
control is added. SSH/Modal/remote TLS and full integrated acceptance remain open.
# H595 new-message interruption — 2026-10-05

Backend HTTP/SSE and admitted channel routing now interrupt same-session code and
preserve bounded partial output/count/duration after teardown. The responsive HUD now sends intentional typed follow-ups during a text stream.
Each stream owns its reply bubble, controller and completion; Stop/unmount abort
and settle all pending streams. Pending answers retain their original controller,
and delayed callbacks cannot overwrite another reply. Vision remains exclusive
and voice does not open overlapping voice requests.
No new endpoint or fresh Docker/native-mobile acceptance is claimed here.


## FAL image provider (2026-10-06)

The registered image tool and media API dispatch approved FAL generation/edits
through the common worker. `/api/media` returns unprobed FAL configuration and
catalog IDs. The Images HUD now offers FAL, OpenAI and Codex provider/model
selection with capability-based reference entry, size and legacy OpenAI quality.
Decision Inbox cards show the actual provider and edit references; lost provider
metadata blocks a proposal instead of falling back to another provider.
Local artifact-reference upload to FAL, Clarity and managed OAuth setup remain open.
See `docs/hermes/openai-codex-image-guide.md`; no live provider acceptance is claimed.

## Image provider continuation (2026-10-06)

Images now offers OpenRouter, Krea, xAI and DeepInfra with explicit model controls
and provider-specific options. A saved inactive Krea job can queue a fresh GET
approval without another generation POST. DeepInfra's catalog refresh is an
approved GET with a local cache; it is not watched as an image task. Decision
Inbox shows the fixed endpoint, selected model or catalog operation, and immutable
Krea source job. Pending or rejected continuations cannot inherit ready artifacts.
See `docs/hermes/openrouter-krea-image-guide.md`. Explicit Krea Enhance is now
connected through a separate immutable source approval, 4K pixel/proof-bound
download/gallery/export and GET-only job continuation; original preview cleanup
and ambiguous submission are covered locally. Other donor
catalogs, FAL upload/Clarity, managed OAuth and native/mobile acceptance remain open.

## Signed model-provider installation (H361 source candidate)

The default-off owner API can stage a server-managed candidate, show a redacted
signed summary, record an exact permanent owner decision, promote and revoke it.
No dedicated HUD install/review flow is present yet. Package installation alone
does not change the active model or make another native dialect available; owner
selection, credential controls and live runtime/provider acceptance remain open.

## Named compatible endpoints — local integration (2026-10-29)

Console → Admin → Custom Endpoints now provides durable named `custom:<key>` entries, display-name aliases, create/rename/delete, exact revision/choice-epoch activation and clear, endpoint-scoped credential metadata/set/rotate/delete, and an explicit bounded `/models` validation. All ten routes under `/api/admin/llm/custom-endpoints` require the admin owner credential. Creation does not probe the destination; LAN/public creation and activation require an explicit destination grant. Validation displays a negative outcome as failure. A valid old signed selection is authenticated and rebound during upgrade; raw or stale selections remain inert. The CLI mirrors these operations under `nerva provider custom`; secret input uses stdin.

The new panel is a local implementation, with synthetic owner/Kernel/Vault/DNS/HTTP and mounted frontend checks. It does not close the separate signed-package HUD controls above, native-mobile configuration, live endpoint/device acceptance or the broader H361/H633 requirements. Capability proof classification and complete batch integration remain explicit gates.

## Governed browser sessions — local integration (2026-10-29)

On 2026-11-22 an isolated native Windows host completed a signed one-shot action
and a separately approved session action against a loopback fixture. After the
owner process exited, a fresh coordinator reclaimed Chrome, its controller and its
private profile. An unrelated process survived recovery.

Operator retains one-shot approval and adds fresh-profile start/act/close, bounded owner session/ref display and later browser-task outcome. The three session/task/close routes require the owner admin credential; generic availability remains user-tier. Grounded refs, scroll/back/press, frame/focus/native form semantics, current registration and exact per-step Kernel receipts are implemented. Local Chrome coverage includes unchanged-registration lifetime and changed-control native/journal cleanup. Console/get_images now add bounded completed-task untrusted observations through separate owner-approved reads, with conservative console invalidation and atomic image row/ref semantics. Vision/dialog/JS/CDP, other engines, real profiles, recording/spill, mobile controls and owner-host/live-platform acceptance remain required separately.


2026-11-12 local continuation v5: shared chat handlers add owner /egress, /reload-mcp, /diff and /profile, plus /version. No dedicated native-mobile or HUD maintenance panel was added; live-device acceptance remains unrun. /diff session and saved-config MCP reread remain unsupported. Native provider menu descriptions are sanitized before truncation and unsafe command identifiers are withheld. See docs/hermes/evidence/2026-11-12-local-continuation.md for tested scope.

2026-11-12 local continuation v6: owner shared chat now exposes failed-channel `/platform` controls and `/update` approval intake. No dedicated HUD/native-mobile maintenance UI was added; no device/live-channel acceptance is claimed. Update intake still refuses in strict Kernel mode until exact registration exists, and requester progress/restart notifications remain open.

2026-11-12 local continuation v7 supersedes the v6 strict-intake limitation: exact hub.update mediation is implemented with current signed/human/AUTO execution checks; no dedicated maintenance UI or live-device proof is added. /pause recovery spelling and confirmed Slack/Discord disconnect controls share the existing chat surfaces. Requester update progress/restart notification and other recorded gaps remain.

2026-11-12 local continuation v8 supersedes the earlier saved-MCP reread gap: shared owner chat now previews and confirms exact saved-config reconciliation. Boot load-set and owner disconnect intent persist; new servers remain disconnected. The confirmation is one-time and expires; no permanent always preference or dedicated native mobile/HUD panel is implemented. Provider/device reconnect acceptance remains unrun.

2026-11-12 local continuation v9: owner chat `/diff session [--stat]` now reads the earliest retained full-project terminal checkpoint against current allowed project files. Explicit approximation/exclusions and missing/corrupt-history refusals; no Git required. Existing chat command surface only; no dedicated checkpoint-diff UI or live mobile/device acceptance claimed.

2026-11-12 local v10: existing owner `/update` chat/approval flow now reports pending-or-running when the shared queue atomically refuses another executable update card. No dedicated UI change; requester progress and post-restart notification remain open, and no live mobile/device acceptance is claimed.

2026-11-12 local v11: keyed channel replies and Telegram/Discord attachments now withhold transport when a durable claim cannot be obtained; shared-database claims and recovery are conditional/atomic. Recent keyed evidence has a500protected-row quota for24h, with new keyed claims refused on capacity. Existing receipts API remains; no new receipt panel/mobile UI or live device acceptance in this slice.

2026-11-12 local v12: HUD Admin Channels now has a lazy owner-only Delivery receipts disclosure with recent50 metadata rows, retained counts, explicit uncertain outcomes and manual refresh. It reads the existing authenticated endpoint, bounds response data, hides stale results on failed refresh and has no send/retry/clear controls. This closes the HUD receipt-reading gap only; native mobile receipt UI, live device/platform acceptance and dead-target-clear UI remain open.

2026-11-12 local continuation v13 (H084 prerequisite): ephemeral restart admission/drain counts existing work and refuses fresh job/subagent/turn starts before claims or budgets; emergency commands retain owner checks. No restart endpoint/command or mobile/HUD restart behavior added. Worker admission, signed completion, physical restart and requester notification remain open; full restart is not claimed.

2026-11-12 local v14 (H084 prerequisite): worker admission covers ordinary/consent/owner-once claims, and original Telegram owner-DM command provenance carries bot-scoped provider identity through paired inbox to registry. No restart command/effect or new HUD/mobile endpoint yet; signed completion and requester notice remain open.

2026-11-12 local v15 (H084): original owner Telegram /restart now creates an exact signed human-approval card. Atomic DONE completion precedes a one-use physical claim, bounded drain and late authority checks; a different boot may attempt one fixed keyed same-owner availability notice. No real restart or Telegram send was performed. Service-manager/provider acceptance remains open; this is a chat-only command with the existing approval surface, no new HUD/mobile endpoint. Supersedes the v14 command/completion/notifier implementation gaps; full H084 remains partial.

2026-11-12 local v16 (H084): bounded private Telegram restart phrases route to the fixed owner command before pending input and conversation context. Original inbox text is preserved and signed in v2 source tickets; historical v1 literal commands remain verifiable. Only the verified original human control intent receives scoped manual classification for signed intake; generic taint and human approval stay enforced. Group prose and other services are unchanged. Historical boot cleanup works with execution disabled without granting a stop or send. Full real ingress/Kernel/approval/DONE pipeline uses a mocked stopper; live acceptance remains open.

2026-11-12 local v25: Mobile Status adds an opt-in Delivery receipts disclosure backed by the existing owner-guarded endpoint. It validates and projects at most50 metadata rows, explains retained counts and uncertain delivery states, and offers refresh/close only. No fetch before opening; connection/credential changes remount closed and erase owner data. Refused refresh, close and unmount clear/abort/fence stale results. No resend or dead-target mutation. Native TypeScript and full mobile Jest are now verified locally; real device/platform acceptance remains open.

Local V44 (2026-11-13): extension inspection/host CLI now distinguish exact live declarations from currently callable tools and commands, using consent/package/registry checks. The dedicated HUD and mobile extension-inspection views remain pending; this diagnostic change adds no activation control.

### Local V51 — signed extension restart routes

Backend startup now restores owner-only command routes from saved activation hints and current consent, without running an extension or composing promotion. The first owner command revalidates package bytes and the exact consent grant before activation. Explicit admin activation may compose acquisition; read-only inspection still does not. Activation/revoke responses expose `restart_restore` separately from live success; `nerva extensions` prints persistence warnings. Build → Extensions remains read-only: no new HUD activation/revoke control is claimed. Native menu updates are queued after explicit activation/revoke and preserve the channel manager's pause/ownership guards. Live Docker/channel/browser acceptance remains unverified.

H697 local continuation (2026-11-13, V53): initial transcript rehydration and desktop cross-window refresh share exact missing-session recovery, coalescing current fallback reads and latching healed ids. A changed selection or started/completed turn fences late reads; malformed fallback snapshots cannot change selection. 403/409/503/network/proxy failures do not rebind. Reclaimed-session push integration remains open; this adds no new route or control.


2026-11-13 local V55 (H624/H695): existing updater status/receipts expose `data_restore_staged` separately from `data_restored`; private archive identity stays hidden. Required data restoration is confirmed only by an exact successful backup result. The existing host-maintenance surfaces retain their scope; no new HUD/mobile restoration control or live device acceptance is claimed.


2026-11-13 local V56 (H624/H695): updater receipts distinguish `stash_restored`; refused or failed automatic owner-stash replay provides recovery guidance through the existing maintenance status. No new HUD/mobile controls or live device proof; host-only maintenance scope remains.


2026-11-13 local V57 (H695): host updater/bootstrap refuse unsafe POSIX venv mutation with named diagnostics through existing logs/errors. No new HUD/mobile controls. Windows ownership is explicitly unchecked; device/native ACL acceptance remains open.


2026-11-13 local V59 (H697, still partial): mobile now offers explicit Start new chat after an exact selected-session-missing response. The unsent message persists until Add to draft or Dismiss; adding preserves newer composer text and never sends automatically. A per-turn server marker confirms successful governed /new before selection changes. Older hubs without that marker preserve the old selection and show guidance. Authorization, busy/corrupt/network errors and stale owner/selection responses cannot trigger recovery. Native device acceptance, automatic terminal-pull and reclaimed-session push remain open.


2026-11-13 local V60 (H141/H195, still partial): mobile History adds a local filter over loaded recent conversations by title, summary, session identifier and agent. Search scope is explicitly limited to the loaded recent list (the current API returns up to 20 rows); it is not full-history or transcript search. Clearing restores the list, refresh retains the query, closing or changing connection resets it, and choosing a match still explicitly resumes its lineage target. Browser search/paging, full-history indexing and live native acceptance remain separate.


2026-11-13 local V61 (H141/H195, still partial): web Sessions now exposes all loaded recent rows instead of silently truncating the list to12. Local title/summary/identifier/agent filtering has explicit loaded-list scope, clear and no-match states; tab changes reset the query and query changes dismiss pending rename/delete confirmation. Existing governed session actions remain explicit. The API still returns up to20 rows; full-history transcript indexing/pagination and device acceptance remain separate. Mobile loaded-list search was already implemented in V60 and is unchanged.


2026-11-13 local V62 (H141/H195, still partial): owner web history now loads older sessions beyond20 through a bounded keyset API. Pages retain archive/lineage filtering and deterministic date+ID ordering; local search covers all loaded pages. Failed later pages retain the list and support retry; stale requests cannot cross tabs/reload. Guests and older hubs retain the recent-list fallback. Mobile pagination, full-text indexing and live device acceptance remain open; pagination is not a fixed historical snapshot. Existing mobile GET/sessions stays unchanged; web initial owner-route refusal can use the independently authorized legacy recent list.


2026-11-13 local V63 (H141/H195, still partial): mobile History adopts the existing owner keyset API and explicitly loads older conversations. Local search includes all loaded pages; retry preserves rows after later failures. Initial401/403/404/405 alone falls back to the legacy recent list. Refresh, close, connection changes and explicit resume fence late responses. No backend or Windows changes; physical-device acceptance and full-text indexing remain open. Guest/older-server fallback remains recent-only; no live device or deployment claim.

2026-11-13 local V64 (H141/H195, still partial): owner web Sessions adds per-row retained-text preview and explicit JSON download without resuming, changing the default session or unarchiving. The admin-only read uses existing identity, turn-lease, import and rewind fences; bounds and automatic secret redaction fail closed. Only retained user/assistant text is included, not compacted archives, tool/media/system content. Mobile preview/export, full-archive export and live device acceptance remain separate.

2026-11-13 local V65 (H141/H195, still partial): mobile History adds explicit retained-transcript preview separate from resume and user-initiated JSON save to the app documents folder. It uses the existing owner-only V64 read with strict exact-session/schema/UTF8-size validation and a field whitelist. Close, search, refresh, resume and connection changes retire private preview/save status. The UI states retained-only automatic redaction; full compacted archives, external sharing and real-device acceptance remain separate.

2026-11-13 local V66 (H141/H195, still partial): web and mobile history add conjunctive agent/date filters over loaded metadata and adjacent local-day group labels without reordering keyset results. All/exact/unassigned agents and all/last7days/last30days/unknown dates are explicit; reset, pagination and retained-transcript privacy fences are preserved. This is loaded-history navigation; full-text/source filters, server-wide filtering and live device acceptance remain separate. Legacy complete archive export is blocked by missing instance/branch provenance and incomplete capture; old logs must not resurrect rewound messages.

2026-11-13 local V67 (H005, still partial): `nerva sessions transcript ID [-o PATH]` exports the owner-authorized V64 retained-current-history JSON with strict identity/schema/UTF8 bounds and a field whitelist. Stdout contains JSON only; diagnostics are generic on stderr. File output is owner-only and create-only, published from a flushed temporary file without clobbering existing files or symlinks. Existing opt-in training `sessions export` is unchanged. Full historical capture/archive, JSONL and other session administration remain separate. This is CLI parity with existing web/mobile retained JSON, with no endpoint or UI change.

2026-11-13 local V68 (H005, still partial): CLI session organization adds rename, pin/unpin, archive/unarchive and archived listing through existing protected routes. Inputs are checked before requests, titles use backend normalization, and strict exact-session/action receipts prevent false success. Malformed success receipts report that the change may have applied; no automatic retry. JSON output includes only known receipt fields. Existing lineage/import ownership, transcript/trajectory exports and default listing are preserved; delete/prune and full historical capture remain separate. CLI parity only; existing web/mobile behavior and endpoints unchanged.

2026-11-13 local V69 (H005, still partial): `sessions history` adds bounded owner keyset traversal beyond the recent20 list, with exact-agent/unassigned, age and loaded metadata query filters. Explicit result/page caps, cursor continuation and stop reasons distinguish exhausted pages from a partial scan. Strict bounded whitelisted pages, dedup/order preservation and buffered output refuse malformed/repeated cursors or late failures without false completion. Default recent listing and existing session mutations/exports remain unchanged. Filtering is client-side within the scanned pages; source/tool-call filters, interactive browse and fixed snapshot isolation remain separate. CLI-only parity; existing UI/endpoints unchanged.

2026-11-14 Lot 2 HUD reachability + H032 MoA presets: wired 13 previously uncalled backend routes into HUD v2 (`UNCALLED_BACKLOG` 54 -> 41) and added Console → Admin → MoA Presets (`MoaPresetsPanel`). `SubAgentsPanel` now exposes incremental transcript inspection (`/api/subagents/{id}/transcript`), final result lookup (`/api/subagents/{id}/result`), and batch completion claim (`/api/subagents/claim`). `A2AInboxPanel` adds outbound peer registry CRUD (`DELETE /api/a2a/peers/{name}`). `OAuthPanel` adds Nous Portal account status, PKCE login start, poll, and logout (`/api/oauth/nous/{status,login,poll,logout}`). `McpPanel` renders pending host elicitation cards and posts schema-typed answers (`/api/admin/mcp/elicitations/{card_id}/answer`). `ChannelDeliveriesDisclosure` adds `dead_targets` listing and `lift gone flag` (`/api/channels/dead-targets/clear`). `JobsPanel` adds durable incident acknowledgement (`/api/jobs/incidents/{incident_id}/ack`), cross-job recent runs (`/api/jobs/runs`), and structured KV notepad editing (`/api/jobs/{job_id}/notepad/keys`). `MoaPresetsPanel` manages `moa:<name>` committee presets, global activation, recent quorum/speedup telemetry, and one-shot governed synthesis over `/api/llm/moa/*`. Verified via backend parity/auth/OpenAPI gates and Vitest; live external provider and physical mobile device acceptance remain separate.
