<!-- Phase B cutover (PHASE_B_PLAN.md §9.3 stage 4): what fails once the Ledger frame is the default, by owner group. Written 2026-11-24 by the cutover-flip engineer. No test was fixed in this step. -->

# Nerva HUD · Phase B cutover failures

| Field | Value |
|---|---|
| Goal | After the default flip, list every failing unit test and every e2e spec that pins the old structure, each with one owner group (PHASE_B_PLAN.md §8.2, §8.3) |
| Base | `claude/hud-redesign` at `77d6db8861cc345ba6266bcf9ecdad39392e8fdc`; Phase A and Phase B stages 1–3 are uncommitted in the worktree |
| Head | uncommitted working tree (nothing staged or committed) |
| Changed paths | `frontend/src/frame/flag.ts` (`DEFAULT_FRAME = 'ledger'`, header comment), `frontend/src/frame/flag.test.ts` (rewritten, 6 tests), this file |
| Generated | 2026-11-24, 00:58 +02:00 (full suite 00:42–00:46, control run 00:49–00:51) |
| Next action | Each group fixes its rows in §4 and §5 (stage 4); stage 5 then deletes the classic shell, its tests and the switch (§7 lists what that touches) |

Groups: **nav** = E1 (navigation and search) · **app** = E2 (frame and App integration) · **talk-docket** = E4 + E5 (decisions, conversation, composer) · **pages** = E6 (pages, modes, Glance) · **unassigned** = named in neither §8.2 nor §8.3.

## 1. The flip

`frameChoice()` returns `'ledger'` when nothing asks for a frame. `?frame=classic` and `localStorage['hud.frame'] = 'classic'` still select the classic shell until stage 5 deletes the switch; the query wins over storage, unknown words are ignored and the choice is read once per page load, as before.

`flag.test.ts` now pins: the Ledger default; classic on request, by query and by storage; the query first; storage, then the default, with unknown words ignored and a stored word surviving an unknown query word; the default when storage throws; one read per page load, for the default as for an explicit choice.

## 2. What was run

| Command (from `frontend/`) | Result |
|---|---|
| `npx vitest run src/frame/flag.test.ts` | 6 / 6 pass |
| `npx tsc --noEmit` | exit 0 |
| `npm run typecheck:e2e` (`tsc -p tsconfig.e2e.json --noEmit`) | exit 0 |
| `npx vitest run --reporter=dot` (once, with a JSON report beside it) | 440 files, 4840 tests: **22 files / 122 tests fail**, 418 files / 4718 tests pass, 241 s. The stage-3 gate was 440 / 4838 green; the 2 new tests are the switch's own. |
| Control: the 22 failing files again, with a scratch setup file (outside the repo) that makes an unset `localStorage['hud.frame']` read `classic` | **22 / 22 files, 289 / 289 tests pass** |

The control restores the pre-flip default exactly (`?frame=` still wins, then storage), so **every failure in §4 is caused by the flip**, not by concurrent edits or earlier breakage. Its config carries the project's test settings but not `@vitejs/plugin-react` (JSX comes from tsconfig's `react-jsx`).

**e2e was not run.** The Playwright lanes serve the committed bundle in `agents/web/v2`, built before the flip, so a run now would still exercise the classic default; rebuilding the bundle is E2's integration step (§1.5). §5 comes from reading every spec under `frontend/e2e/`, `frontend/cloud-image-browser/` and `frontend/dispatch-e2e/`: it is a prediction from the source, not a measurement.

## 3. Counts

| Group | Unit tests failing (files) | e2e tests pinning the old structure (specs) |
|---|---|---|
| nav | 28 (6) | 17 (5) |
| app | 38 (6) | 24 (7) |
| talk-docket | 55 (9) | 14 (6) |
| pages | 1 (1) | 0 |
| unassigned | 0 | 6 (2) |
| **Total** | **122 (22)** | **61 (16 spec files, 4 of them split between two groups, §6)** |

An e2e test is counted once per definition; the nightly browser matrix runs most of them four times.

## 4. Failing unit tests

Two causes recur, so they are named once here:

- **Classic stand-ins.** Several App tests mock `modes3.ChatMode` or `gap.ConsoleOverlay` and wait for the stand-in. Under the Ledger frame `/v2/chat` renders `home/ChatPage` (TalkRegister) and a panel route renders `PanelPage` → `gap.ConsolePanel` (absent from those `gap` mocks), so the stand-in never mounts.
- **The sheet shows no appearance rows until something is typed.** With an empty query `CommandSheet` lists the recent items, the nine areas and the actions; the appearance and language rows (`Accent · Violet`, `Font · System Serif`, `Scheme · System`, `Look · Ledger ✓`, `Language · English ✓`) keep their words (decision 4) but appear only for a query. Ctrl K followed by a click on a row therefore fails.

### nav (28)

**`src/test/hud-routing.test.tsx`** (6 of 19). Titles come from `pageTitle` (`Today · Nerva`, `Decisions · Work · Nerva`) and only Glance is an overlay, so World and a console panel no longer return to the page that opened them (`/v2/cockpit` instead of `/v2/chat`). §8.3: rewrite the titles; the return-chain case becomes Glance; route validity unchanged.
- HUD URLs > registers every console panel with unique explicit addresses (expects the `<label> · Console · Nerva` title)
- HUD URLs > replaces root/unknown routes, updates titles and reports unknown URLs
- HUD URLs > pushes navigation once, restores Back/Forward and survives remount
- overlay entry return destinations > preserves the invoking mode and unrelated state across remount at /v2/world
- overlay entry return destinations > preserves the invoking mode and unrelated state across remount at /v2/console/decision-inbox
- overlay entry return destinations > preserves the return chain when moving between overlays and console panels

**`src/test/base-path.test.ts`** (3 of 8). The same two changes under a base path: no `__nervaHudRoute` return record for World or Console, and the new title form. §8.3 (with hud-routing).
- writes public hrefs but keeps per-entry overlay origins logical
- initializes deep panel bookmarks and canonicalizes under the prefix
- preserves historical overlay close targets and popstate beneath a prefix

**`src/test/shortcuts.test.tsx`** (6 of 25). The page-load registry is now `LEDGER_ACTIONS` (§3.6: 2 Work, 3 Agents, 9 Settings, 0 the conversation, `a` Glance; no `mode.autonomy` or `mode.comms`). §8.3: rewrite the default table; the forbidden-target tests pass unchanged.
- the registry — H209 > holds every HUD shortcut with its default chord
- overrides > rebind, reset one, and a rebind back to the default is no override
- dispatch > matches the first action on a chord, in its scope only
- the Keyboard Shortcuts panel > records a new chord, ignoring lone modifiers, and Escape cancels (looks for "Rebind Ambient mode"; the Ledger label is Glance)
- the Keyboard Shortcuts panel > records Space and Ctrl+Space, and those keys then answer (F1) (same)
- the Keyboard Shortcuts panel > names a clash, resets one binding and resets all ("Also bound to Glance")

**`src/test/shortcuts-ledger.test.ts`** (2 of 5). Both assume the default page load gets `CLASSIC_ACTIONS` (line 53 says so in a comment). Pin the classic cases with `?frame=classic` until stage 5, then delete them.
- the Ledger registry > keeps the classic registry as it was, and picks one per frame
- the registry a page loads > is the Ledger one when ?frame=ledger, and drops a stored override for an id it no longer has

**`src/test/pointer-fallback.test.tsx`** (1 of 8). `anchorRect`'s `fallbacks` argument defaults to `isLedgerFrame()`, now true. Pass classic explicitly until stage 5.
- anchorRect in the Ledger frame > does nothing extra in the classic frame

**`src/test/appearance-sync.test.tsx`** (10 of 14). Row 11's file, kept with one writer. Five fail on the sheet (cause above), four on the classic stand-ins (the `ChatMode` that records the shared appearance; a `gap` mock with `ConsoleOverlay` and "Close console" but no `ConsolePanel`, so the Personalisation page never mounts), one on boot order.
- hydrates appearance from the server without writing at boot (the accent stays `cyan`. Likely cause, not verified: its `fetch` mock returns one shared `Response`, the Ledger frame's own feeds read its body first, and the appearance read then fails; each call needs its own `Response`)
- saves an explicit palette choice to the narrow preference endpoint (sheet)
- shows failed explicit saves without reopening the palette (sheet)
- applies a palette font to the HUD root with only a finite font patch (sheet)
- starts System from the OS reading of now, not one taken before another scheme was chosen (sheet; its commit recorder lives in the `ChatMode` stand-in)
- shares the one appearance instance with the tree through AppearanceProvider (`ChatMode` stand-in)
- offers every theme and the scheme in the palette and syncs a scheme choice (sheet)
- leaves a sync failure to Personalisation while it is open, and the shell says it again after (`ConsoleOverlay` stand-in; under Ledger the page is left by navigating, and the shell's notice is the Frame's)
- lets Personalisation say it in Romanian, with no English copy from the shell (same)
- keeps the shell notice on every other Console panel (same)

### app (38)

**`src/test/app-routing.test.tsx`** (20 of 23). Mocks `modes3.ChatMode` ("Chat route loaded"), `gap.ConsoleOverlay` ("Console route …") and the World overlay; World's title is now `World signals · Observe · Nerva`, and F3 clicks a palette row. §8.3: rewrite to masthead and contents navigation, the sheet, the new hotkeys, panel pages, the World page with Back/Forward, Glance's Esc return; the H209 rebinding cases keep using `w`. The F2/F3 palette rows are row 11's labels (the sheet is E1's).
- connects rail, palette, hotkeys, console and desktop handoff to the same URL
- loads World bookmarks and restores its overlay through Back/Forward
- loads a selected console bookmark and clears form state across route changes
- keeps floating desktop on canonical chat and preserves its query context
- restores the invoking mode of a historical World visit
- restores the invoking mode of a historical console visit
- closes a prefixed console through the same toggle hotkey
- closes prefixed World with Escape and restores the invoking mode
- H209: mod+/ opens the shortcuts panel, a rebinding moves the key, and it persists
- H209: a rebound World key opens World and the old one no longer does
- H209: a rebinding made in the panel reaches the World button beside the app
- H209: Ctrl+Space on the panel itself opens it, and a stored "mod+" no longer locks it out (F1)
- H209: the palette still opens the panel when its chord is taken (F2)
- H209: a palette rebound to a bare key never fires while typing (F3)
- H209: a HUD action on a rebound chord is not also the browser's (F4)
- H209: World's key waits while the panel is open (F5)
- H209: with storage off, a World rebinding still takes for this page (F6)
- H209: the HUD's key hints follow a rebinding (F7)
- H209: the Escape that closes the panel leaves World open beneath it (F8)
- H209: in Cinema the panel does not open unseen; stage keys and hints follow the registry (F10, F4, F7)

**`src/test/language-menu.test.tsx`** (9 of 14). The globe menu (`LangMenu`, a button named /language/) and the TopBar's brand line ("INTELIGENȚĂ PERSONALĂ · OS") are not drawn; the last case clicks a sheet row. §8.3: rewrite the App-level cases to the masthead's EN/RO radiogroup with the same claims (persistence, `lang`/`dir`, `jarvis:locale_changed`); the direct `TopBar globe menu` cases pass and stay until stage 5. The palette-row case is row 11's (language-menu:206-207).
- App language preference > switches the strings and the document lang from the globe menu and saves it like the other preferences
- App language preference > keeps the chosen language across a reload from the local cache before the server answers
- App language preference > hydrates the language saved by another browser of the same owner
- App language preference > shows the pre-sync hud.lang choice on an unconfigured server without uploading a default
- App language preference > keeps a legacy hud.lang=ro through hydration from a configured server and uploads it once — no v2 cache on this browser
- App language preference > keeps a legacy hud.lang=ro through hydration from a configured server and uploads it once — a v1 cache written before lang existed
- App language preference > does not upload a legacy hud.lang twice across reloads
- App language preference > follows the v1 shell: jarvis:locale_changed and a hud.lang storage event reach the HUD
- App language preference > offers every language as a palette row and switches from there

**`src/test/app-demo-exit.test.tsx`** (1 of 1). Mocks the classic regions (TopBar, Ticker, RosterColumn, ContextColumn, …) and waits for "DEMO DATA"; the Ledger notice reads "Demo sample on screen — seeded data, not your live hub." §8.3: mock the new home, docket and signals modules; keep the "demo evidence is cleared" claims.
- App demo-to-live provenance > clears seeded evidence with the URL and rejects a late demo refresh

**`src/frame/classic-frame.test.tsx`** (4 of 4). Asserts the default page load is classic. Add `?frame=classic` until stage 5 deletes the file.
- the classic shell draws its cockpit at /v2/work, and keeps the URL
- the classic shell draws its cockpit at /v2/timeline, and keeps the URL
- the classic shell draws its cockpit at /v2/artifacts, and keeps the URL
- the classic shell draws its cockpit at /v2/glance, and keeps the URL

**`src/frame/ledger-app.test.tsx`** (3 of 19). Its "switch off" cases start without `?frame=`. Add `?frame=classic` until stage 5 deletes them.
- App under the Ledger frame > opens no cognition stream: nothing draws the trace under the Ledger frame (the classic tree still does) (its second half renders `/v2/cockpit` expecting the classic tree)
- App with the switch off > draws the legacy shell as before, and asks none of the Ledger's own feeds
- App with the switch off > keeps the legacy console overlay and the World overlay off the Ledger pages

**`src/test/desktop.test.tsx`** (1 of 10). Not named in §8; the fixed CONSOLE button (the classic tree in `app.tsx`, retired by §2.4) is gone. Keep the native "Float chat" opener claim; move the console claim to the Find button or delete it with the button. See §6.1 for the floating case beside it, which still passes.
- normal app retains its console and native opener

### talk-docket (55)

**`src/test/turn-outcome-app.test.tsx`** (22 of 70). The turn's status lines (`Request model`, `Turn outcome`, `Battery`, `Turn duration`, `Output token flow`, `Memory recall`) sat under the composer; on a Ledger reply they are drawn only once More → Turn details is opened (`ReplyActions`). Several cases also read `.msg.agent`, and one clicks the TopBar's "toggle demo data" button (retired; the sheet's demo command or Exit demo replaces it). §8.3 composer and transcript rewrites (E5).
- mounts long status values beside a reachable composer floating=false
- mounts long status values beside a reachable composer floating=true
- allocates remaining chat-pane height to scrollable status while preserving composer floating=false
- allocates remaining chat-pane height to scrollable status while preserving composer floating=true
- forwards local battery into mounted ChatMode floating=false
- forwards local battery into mounted ChatMode floating=true
- shows only measured whole-turn duration in /v2 after the current end
- shows only measured whole-turn duration in /v2/chat after the current end
- renders live visible-output estimate, then reconciles observed usage and failed-file footer
- pins recorded tool activity to the correct /v2/chat reply, including concurrent ends
- pins recorded tool activity to the correct /v2/cockpit reply, including concurrent ends
- restores native assistant tool receipts, but ignores user and foreign history metadata
- does not treat assistant prose as a tool receipt or copy a receipt into reply text
- shows exact zero and clears a prior duration synchronously when another turn starts
- does not retain an old duration after an error end or a failed stream
- clears on Stop and ignores an end delivered after the cancelled turn
- clears on topic selection and ignores the old topic reply
- clears on agent selection, even when a prior turn completed
- clears when entering demo mode and never presents an old live duration as demo evidence
- ignores a late live end after the user switches into demo mode (the TopBar demo toggle)
- recall indicator > renders the stream end outcome in the mounted HUD turn
- recall indicator > shows the line from the live progress event, before any token arrives

**`src/test/chat-routing-app.test.tsx`** (14 of 14). The recipient is chosen with `RecipientPicker`, not a combobox named "Selected agent"; "Teach skill" moved into the reply's More menu. §8.3: same claims through the picker and the menus.
- keeps a reviewed Office passage and the question after a size refusal and sends them on explicit retry
- only offers to teach from restored assistant turns with a recorded author
- sends two reviewed board references as structured owner input and renders their recorded source controls
- shows the specific unavailable-agent refusal with a next action
- drops the live picker and policy immediately across Demo and live loading boundaries
- selects an authenticated agent from false floating Chat and sends to it without losing the draft
- selects an authenticated agent from true floating Chat and sends to it without losing the draft
- restores the exact next recipient after a same-tab reload and sends to it
- does not reuse a saved recipient across guest credentials
- requires a new choice when a saved recipient leaves the authenticated roster
- requires a new choice when guest credentials change in the same tab
- shows pending recipient verification and preserves the draft in /v2/chat
- shows pending recipient verification and preserves the draft in /v2/cockpit
- clears the saved recipient on an explicit conversation switch

**`src/test/composer-vision-turn.test.tsx`** (8 of 8). Captures `onSubmit` from a `modes3.ChatMode` stand-in (seven fail on "submit is not a function"); the first also waits for the classic label "VISION ANALYSIS" (the Ledger vision turn says Vision, titled "Vision analysis"). §8.3: transmit becomes `V2.I18N.en.transmit`; capture the submit from the Ledger tree.
- sends a vision turn from the actual shared input and labels actual provenance
- owns one turn synchronously across image and text submissions
- uses the returned generation after /new and reopens an exact older topic
- discards a late streamed reply after selecting another topic
- stops a vision turn and ignores a late response even if transport ignores abort
- renders a structured vision failure without invented agent provenance
- aborts an owned image turn on unmount
- keeps a successful vision policy warning separate from its answer

**`src/test/direct-reply.test.tsx`** (4 of 10). A composer test (§8.3): looks for the "Selected agent" combobox.
- sends reasoning none only for the checked text turn and consumes the choice
- keeps direct reply in the current draft and out of voice, commands, and another agent
- sends only explicitly reviewed vault text with the choice and never adds a prompt suffix
- sends a reviewed history reference as a top-level owner request with a plain question

**`src/test/h595-chat-followup.test.tsx`** (3 of 11). Reads `.msg.agent … .prov-chip` and the "Stop generating" button; the Ledger reply's stop reads "Stop this reply" / "Stop the replies" and its models line is in `ReplyFootnote`. §8.3: `data-turn` hooks.
- keeps both replies in their own bubbles when the older stream finishes later
- shows only a validated receipt, even when usage is mixed or incomplete
- Stop aborts every pending stream and settles the voice turn

**`src/test/app-session-recovery.test.tsx`** (1 of 9). Reads `.msg.agent .prov-chip` (§8.3: `data-turn`).
- restores measured model calls on a saved reply without deriving a badge from missing evidence

**`src/test/selected-vision-app.test.tsx`** (1 of 3). Selects the agent through a mocked `NeuralMesh` ("Select Frigga"); the mesh is no longer on Home (§2.4: Cinema only). Select through the recipient picker.
- uses the selected agent and aborts its image answer when the agent changes

**`src/test/pending-question.test.tsx`** (1 of 6). Not named in §8; the "Stop generating" control is the working reply's (E5).
- Stop aborts the stream and removes the pending question without posting an answer

**`src/test/turn-tools.test.tsx`** (1 of 4). Not named in §8 (`turn-tools.tsx` is E5's); captures `onSubmit` from a `modes3.ChatMode` stand-in.
- browser chat shows what the turn ran and what it queued > asks for tool events, renders one card per call and lists the queued approvals

### pages (1)

**`src/test/mode-surface-a11y.test.tsx`** (1 of 4). `AgentsMode` now draws through `PageSection`, which under Ledger renders a register instead of `.panel-body`. Re-pin the same contract on the new markup (the scrollable roster is in the tab order, has a name, and a role that permits it); §8.3 keeps the file with E6.
- mode surfaces keep their accessibility contract > puts the AGENTS roster — a scrollable region whose cards are non-focusable divs — in the tab order, with a name

## 5. e2e specs that pin the old structure

"Also red in classic" marks a test that already fails without the flip, because the composer re-lay (stage 2, both frames) removed `.inputbar` or E4's grading replaced a one-click accept. Inferred from the source; not run.

### nav (17)

**`e2e/a11y-modes.spec.ts`** (row 30). Walks `.rail-btn` (expects 16), the old number keys and `.workzone`, and waits for `ModeEmpty`. Rewrite: walk every registry page through AreaNav and ContentsColumn, axe each, keys 1–9 and 0 reach the nine areas and the conversation.
- no critical/serious accessibility violations in any HUD mode (live · 1280x720)
- no critical/serious accessibility violations in any HUD mode (live · 1440x900)
- no critical/serious accessibility violations in any HUD mode (demo · 1280x720)
- no critical/serious accessibility violations in any HUD mode (demo · 1440x900)
- Admin axe scan waits for EstopCard after the old quiet window (clicks the Admin rail button)

**`e2e/appearance.spec.ts`** (row 35). Opens the palette by `getByTitle('command palette')` (the TopBar button) and clicks rows at once. Rewrite: open the sheet from the Find button, type, then click; values unchanged.
- appearance follows the owner across browsers at /
- appearance follows the owner across browsers at /one
- two offline tabs retain different edits after both tabs close, without Web Locks

**`e2e/appearance-fonts.spec.ts`** (row 35's opener; row 34's computed-font assertions stay Phase A's).
- local font choices persist without changing mono at /
- local font choices persist without changing mono at /one

**`e2e/base-path.spec.ts`** (row 36). Titles (`Cockpit · Nerva`, `Console · Nerva`, `World · Nerva`, `Decision Inbox · Console · Nerva`), the backtick as a Console toggle, `w` + Escape as an overlay, the CONSOLE button, "All console panels". The gap chunk and woff2 checks stay, after a visit to `/v2/console/logs` if Home no longer pulls `gap`.
- same built HUD through proxy at /
- same built HUD through proxy at /one
- same built HUD through proxy at /two/nerva

**`e2e/status-chrome-layout.spec.ts`**, rail half (row 28). The rail gateway dot and the wheel test. Rewrite: the nine areas visible at 1366×768, 1280×800, 1024×768 (the drawer below 760); delete the wheel test.
- the rail gateway dot is on screen at 1366x768
- the rail gateway dot is on screen at 1280x800
- the rail gateway dot is on screen at 1024x768
- the rail wheel-scrolls to its last mode button on a 768px-tall screen

### app (24)

**`e2e/hud.spec.ts`**, mesh half (row 31). Waits for `.nmesh canvas` on `/v2`; the mesh is in Cinema only. Rewrite: move the paint check into Cinema (`m`); `/v2` asserts the three Home registers and no uncaught error.
- HUD v2 boots, mounts, and the Neural Mesh paints — no uncaught errors
- Cinema mode (m) opens the full-bleed mesh and Esc closes it (Cinema is unchanged; only its Home-mesh precondition breaks)

**`e2e/a11y.spec.ts`**, mesh half (row 31, a11y:36-37).
- HUD v2 cockpit has no critical/serious accessibility violations
- Cinema mode overlay has no critical/serious accessibility violations (same Home-mesh precondition)

**`e2e/layout.spec.ts`**, topbar half (row 25). `.topbar`, `.brand .badges`, `.clock`. Rewrite: no horizontal overflow at 2560/1920/1280/900/800; the eight running-head items neither overlap nor clip; masthead areas clear of the tools.
- topbar fits and does not stack at 1920px
- topbar fits and does not stack at 1280px
- topbar fits and does not stack at 900px
- topbar fits and does not stack at 800px

**`e2e/contrast.spec.ts`** (row 29). `CHROME_PARTS` = `.topbar .ticker .rail .center-tabs .inputbar`, 16 `.rail-btn`, 3 `.center-tab`, `.brand .l1`. Rewrite: the frame regions and `[data-register="docket"]`, `[data-composer-bar]`; measure the 9 area labels and the running-head labels; Ledger dark, Ledger light and Obsidian. Also red in classic (`.inputbar`).
- painted-contrast inventory: the HUD chrome
- red proof: a deliberately dimmed node is reported, not passed
- ``red proof: an invisible node lands in `unpainted`, never in `measured` ``

**`e2e/status-chrome-layout.spec.ts`**, badge half (row 27). `.brand .badges` (its shared `boot()` also waits on `.brand [data-chrome="gateway"]`). Rewrite: all eight running-head items visible at 2560/1920/1536/1440/1366/1280; session count and version painted in the foot.
- LLM, DATA and GATEWAY stay fully visible in the top bar at 1920x1080
- LLM, DATA and GATEWAY stay fully visible in the top bar at 1536x864
- LLM, DATA and GATEWAY stay fully visible in the top bar at 1440x900
- LLM, DATA and GATEWAY stay fully visible in the top bar at 1366x768

**`e2e/reachability.spec.ts`**, focus-ring half (row 23). Rewrite on the first focusable in `[data-frame="page"]`, still a 4px ring.
- the focus ring is not clipped at 1280px
- the focus ring is not clipped at 1100px
- the focus ring is not clipped at 1000px
- the focus ring is not clipped at 900px
- the focus ring is not clipped at 800px

**`e2e/routing.spec.ts`** (row 37 and §8.3 app-routing; §9.1 had given the spec to E1). The first test pins the old titles, the CONSOLE button, "All console panels" and the Decision Inbox heading; the grid tests pin `.workzone.cockpit .inputbar` and `.scrollcol` (also red in classic). Row 37's new assertions are E4 + E5's content: the docket ≥ 480px wide and inside the viewport, every sign control reachable, the textarea ≥ 320px, the five controls inside the composer, at 1280/1440/1680/1920.
- bookmarks, reload, history, focus and lazy chunks on the served HUD
- HUD grid fits 1101px without clipping its context column
- HUD grid fits 1280px without clipping its context column
- HUD grid fits 1440px without clipping its context column

### talk-docket (14)

**`e2e/hud.spec.ts`**, composer half (row 32). `.inputbar input`, `.inputbar .transmit`, `.msg.user/.agent .bubble`, the "stop generating" button. Rewrite to `[data-composer]`, `[data-composer-send]`, `[data-turn="owner"] [data-turn-body]`, `[data-turn="reply"] …`; the Voice control keeps its "push-to-talk" title. All three also red in classic (`.inputbar`).
- chat flow renders SSE tokens and the final reply
- stop button aborts an in-flight chat stream
- voice push-to-talk captures STT text and drives a chat turn

**`e2e/a11y.spec.ts`**, transcript half (row 32's selectors; §8.3 convo-keyboard-access). Seeds a user-only transcript and reads `.convo .msg.user`; the Ledger transcript is `[data-transcript]` with `role="log"` and `data-turn` turns. Keep every claim (overflowing, no focusable child, axe clean, `tabIndex` 0, role `log`, a name).
- the chat transcript stays keyboard-reachable when it holds only user turns

**`e2e/reachability.spec.ts`**, input-bar half (row 24). Rewrite: `[data-composer-bar]` and `[data-composer-send]` inside the viewport at 1280/1100/1000/900/800. Also red in classic (`.inputbar`).
- the chat input bar is reachable at 1280px
- the chat input bar is reachable at 1100px
- the chat input bar is reachable at 1000px
- the chat input bar is reachable at 900px
- the chat input bar is reachable at 800px

**`e2e/composer-images.spec.ts`**. Already on the new composer hooks, but two tests read the classic transcript: "VISION ANALYSIS" and a provenance line matched as one text (the Ledger vision turn splits it into `<code>` parts), and the "Stop generating" button.
- choose paste drop, explicit remote consent, vision provenance and unchanged text chat
- stale destination fails visibly and a cancelled late vision result is ignored

**`e2e/turn-latency.spec.ts`**. Expects the `Turn duration` line visible after the reply, as it was under the composer; on a Ledger reply it is behind More → Turn details.
- current turn duration survives layout but not reload at 1280px
- current turn duration survives layout but not reload at 390px

**`cloud-image-browser/workflow.spec.ts`** (its own lane, `playwright.cloud-image.config.ts`). Clicks the Decision Inbox's "accept" once and waits for the decision POST. Cloud image requests are enqueued at `risk_tier=3` (`agents/core/cloud_image_runtime.py`), and E4's grading (both frames) asks for the typed phrase. Independent of the flip, also red in classic. §8.3 decision-inbox-panel: rewrite to the typed confirmation; never weaken the friction.
- cloud approval roundtrip returns saved PNG and catalog export under prefix

### unassigned (6)

**`e2e/footage.spec.ts`** (manual marketing lane, `FOOTAGE=1` only; not in `npm run e2e` or the nightly). Not named in §8. Pins the legacy palette (`.pal`, `.pal-item`, `.pi-name`, the commands "Trust Center", "Autonomy", "Knowledge", "Family · local"), the active rail button's title, `.nmesh canvas` on Home, and the classic demo banner "DEMO DATA … seeded sample, not your live backend". Under Ledger its live-source honesty check (that banner `toHaveCount(0)`) would pass **vacuously**, because the Ledger notice reads "Demo sample on screen — seeded data, not your live hub."; key it to the new notice when rewriting. Suggested owner: nav (sheet and page navigation), with the Home-mesh shot following row 31.
- footage · hero
- footage · trust-center
- footage · governed-autonomy
- footage · morning-brief
- footage · strict-local

**`dispatch-e2e/dispatch.spec.ts`** (its own lane, `playwright.dispatch.config.ts`). Not named in §8. Clicks the TopBar's "Automations" button (retired with TopBar); the jobs page is reached through its area, the sheet or `/v2/jobs`. Suggested owner: nav.
- real manual request is accepted before offline dispatch and recorded through HUD

### Read and not pinned (unverified under Ledger, because e2e was not run)

Already on the new hooks or frame-independent: `layout.spec.ts` "vault passage and Send fit after resizing to 320px / 390px" (row 26, migrated), `composer-images.spec.ts` "training and cost confirmations are independent, transmitted and reset for the next draft", `image-failure-state.spec.ts` (2), `media-gallery.spec.ts`, `task-mediation.spec.ts` (2; the panels' own `Card`), `pwa.spec.ts` (4; see §6.1), `base-path.spec.ts` "cohosted workers keep separate shells and preserve unrelated caches", `hud.spec.ts` "golden-signals /metrics stays available during the HUD soak", `workshop-export.spec.ts` (`/os/`), `workspace-journey.spec.ts` (the Workspace app) and `ledger-shots.spec.ts` (asks for Ledger explicitly; self-skips outside its own project).

## 6. Notes for the groups

### 6.1 Pins that pass but no longer prove anything
- `src/test/desktop.test.tsx` "floating app renders existing chat without normal shell or world control": `queryByTitle('console (`)')` is null in every Ledger window now, so it no longer tells the floating window from the main one. Re-key it to the frame (no `[data-frame="masthead"]` in the floating window, as `ledger-app.test.tsx` already does). app.
- `e2e/a11y-modes.spec.ts` "Admin readiness accepts only the explicit empty card, not a missing or pending marker": passes on synthetic markup, but the helper it tests keys on `.rail-btn.active .rl`, `.workzone` and `ModeEmpty`; it goes with the walk's rewrite. nav.
- `e2e/pwa.spec.ts` "no /api/ response is ever written to Cache Storage": presses `3` ("Trust Center") and `1`; under Ledger `3` is Agents. The cache assertions do not depend on it; fix the comment or the key. nav.
- The footage lane's live-source banner check (§5, unassigned).

This list comes from a search of the App-rendering tests for negative assertions on classic selectors, not from a full audit of every passing test.

### 6.2 Files more than one group touches
`e2e/hud.spec.ts` (app, talk-docket), `e2e/a11y.spec.ts` (app, talk-docket), `e2e/reachability.spec.ts` (app, talk-docket), `e2e/status-chrome-layout.spec.ts` (app, nav; one shared `boot()` helper). `e2e/layout.spec.ts` is app's only, unless the migrated vault tests fail. Give each file one writer at a time.

### 6.3 Text that still says classic is the default
`frontend/src/app.tsx:65` (comment), `frontend/src/hud-routing.ts:27` and `frontend/src/shortcuts.ts:32` ("until the cutover"), `frontend/src/frame/classic-frame.test.tsx:1`, `frontend/src/test/shortcuts-ledger.test.ts:53`, and `docs/design/hud-next/PHASE_B_INTERFACES.md` lines 7 and 30 (that file's update is already a stage-5 item). PHASE_B_PLAN.md §1.2 is history and stays.

## 7. For stage 5 (cleanup)

These pass today only because they render a retired component directly (§8.1); port or delete them with the component.

| Test | Renders | Group |
|---|---|---|
| `src/test/palette-tweaks.test.tsx` | `Palette` | nav (row 11: moves to CommandSheet) |
| `src/test/console-routing.test.tsx` | `ConsoleOverlay` | nav (§8.3: port to AllPages and PanelPage) |
| `src/panels/extension-inspection.test.tsx`, `src/panels/provider-packages.test.tsx` (one case), `src/panels/usage.test.tsx` | `ConsoleOverlay` | unassigned (not named in §8; the same port to `ConsolePanel`, so nav suggested) |
| `src/test/rail-navigation.test.tsx` | `Rail`, `RailDrawer`, `Tabs`, `MODES` | app (row 17: `aria-current`, `data-anchor` move to AreaNav tests) |
| `src/test/status-chrome.test.tsx` | `TopBar`, `Rail`, `fitBadgeStrip` | app (row 17: gateway, session and version semantics move to RunningFoot tests) |
| `src/test/language-menu.test.tsx`, `TopBar globe menu` cases | `TopBar` | app |
| `src/test/jobs-entry.test.tsx` | `TopBar` (Automations) | app (deleted with TopBar) |
| `src/test/hud-inline-fixes.test.tsx`, WORLD rows | `world_app` constants | app (row 16: delete) |
| `src/test/approval-mode-card.test.tsx`, `src/test/markdown-adoption.test.tsx` | `ContextColumn` `.dcard` | talk-docket (§8.3: mode notes move to DocketEntry; the markdown-in-card case is deleted) |
| `src/test/convo-keyboard-access.test.tsx`, `src/test/godot-download.test.tsx` | classic `Conversation` markup (`.convo`; `.msg.agent .bubble`) | talk-docket (§8.3: `getByRole('log')`, `data-turn`) |
| `src/test/blender-export.test.tsx` (its `Conversation` cases) | `Conversation` without a `variant`, so the reply actions sit where the classic tree puts them | talk-docket (§8.3 composer tests: add the menu step where a control moved) |

The switch itself (paths under `frontend/`): `src/frame/flag.ts` and `src/frame/flag.test.ts` go; `src/frame/classic-frame.test.tsx` goes; the classic cases in `src/frame/ledger-app.test.tsx`, `src/test/shortcuts-ledger.test.ts`, `src/test/hud-routing-ledger.test.tsx`, `src/test/pointer-fallback.test.tsx`, `src/pages/PageSection.test.tsx` and `src/pages/mode-wrappers.test.tsx` go. Source that reads the switch: `src/app.tsx`, `src/world_app.tsx`, `src/hud-routing.ts`, `src/pointer.tsx`, `src/shortcuts.ts`, `src/modes3.tsx`, `src/pages/PageSection.tsx`. `e2e/ledger-shots.spec.ts` seeds `hud.frame` and `?frame=ledger`, which then do nothing. After that, rebuild and check the bundle size (open item 3).

**Stage 5 status (2026-11-24, local, uncommitted).** Done: the switch, `world_app.tsx` and the classic shell are deleted; every row of the table above is ported or deleted as it says, except the last two, and the switch's cases are gone from the six files named (a leftover `?frame=classic` or `hud.frame` now gets the Ledger frame and keeps its URL, which `ledger-app`, `hud-routing-ledger` and `shortcuts-ledger` pin). `e2e/ledger-shots.spec.ts` no longer seeds the switch. Not done: `convo-keyboard-access`, `godot-download` and the `Conversation` cases of `blender-export` still render the variant-less `Conversation` (they pass; App no longer draws that markup), and `ChatMode` stays in `modes3.tsx` for its feature tests. The bundle was rebuilt: its JavaScript went from 2,557.1 KiB to 2,493.2 KiB (the main chunk 933.7 → 885.6 KiB, `gap` 933.6 → 931.6 KiB); the main and `gap` chunks are still above Vite's 500 kB warning. Unit suite: 437 files, 4,795 tests, all pass. e2e was not run in stage 5.
