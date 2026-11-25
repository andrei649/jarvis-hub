<!-- Phase B spec, written 2026-11-23 by the planning agent from the Ledger mockups, frontend/src/theme/CONTRACT.md and the discovery research. The defaults in the owner-questions section apply until the owner says otherwise. -->

# Nerva HUD · Phase B spec: the Ledger structure

> **Status note, 2026-11-24.** Stages 1–5 are done on branch `claude/hud-redesign` (local, not merged). The Ledger frame is the only frame: the frame switch (`frame/flag.ts`, `?frame=`, `hud.frame`, the classic default) no longer exists, and the classic shell was deleted in stage 5. What follows is the historical spec; where the code differs (the cutover and its review changed some details, e.g. §4.3), the code and `PHASE_B_INTERFACES.md` §7 are right. References to the switch, "classic" and `frame=ledger` below describe the staged rollout, not the present build.
>
> **Amendment, 2026-11-24 and 2026-11-25 (polish rounds, the last round, its repair, the register-inset round, its repair and the final round):** §4.1 and §4.2's width tables are the starting point, not the whole fit: from 1100px the masthead and the running head each measure themselves and take steps while their row spills, and, once it fits, take back the steps it no longer needs (§4.2 below; `PHASE_B_INTERFACES.md` §7, "Changed by the third polish round"). The Talk register's pending change of recipient is kept by App and is never carried out when a reply ends (§12 item 11); while the reply that opened the question is still being written, `runTurn` refuses a hands-free voice turn, and a voice turn goes to the current recipient only after that reply has ended (§12 item 12). The last round drew every section head, register head and total by one rule (where a title and what sits beside it do not fit, the latter takes the line under the title, so no title is squeezed or cut) and gave Home's register heads one row from 1100px; its repair gave Trust's two register heads one height (`useHeadRow`), kept the docket's large figure from making register heads taller, kept the day band's popovers inside a 320px window, and made `confirm.tsx` move the focus in the commit that draws a confirmation (`PHASE_B_INTERFACES.md` §7, "Changed by the last round"). The register-inset round gave a register an inner margin in the looks that draw their panels as cards (a theme role, `--n-register-pad`, `frontend/src/theme/CONTRACT.md` §3; 0 in Ledger, Briefing and Presence, so nothing moves there) and the render matrix a gate for it, `register-inset`; its repair draws registers with rules below 760px in every look, caps the margin at `--n-s-2` from 760 to 1099px, lets a footed register's foot take its bottom margin, sets Classic's to `--n-s-4`, and measures the docket's sign line against the docket body's view (`docket-1280`, the new `docket-sign`). The final round drew the area page's column with only its top rule in every look (no card inside a card; the gate `area-frame`) and gave the docket's open entry the room §9.5 and §5.1 ask for in Classic (a theme role, `--n-term-max`, and, for the one case left, a scroll of the docket's body at first paint, which the final gate limited to where the whole open entry stays in view) (`PHASE_B_INTERFACES.md` §7, "Changed by the register-inset round", "Changed by the repair" and "Changed by the final round"). **Phase B is closed on the final bundle** in `agents/web/v2` (this final gate's build of 2026-11-25 09:32:17, `index-lG61P7Tc.js` and `index-Dq-NCigC.css`): its render matrix passes with every gate, `frontend/e2e/artifacts/ledger/runs/gf-20261125-093223` (507 tests, 523 records, 0 failed gates, `area-frame` and `docket-sign` among them; one page reloaded once and recorded), and so do the main lane's specs on the fixture hub, the fixture-backed lanes, the Home lane and the full Vitest suite on the same sources. Every earlier run (`gi-20261125-042933` on the 04:13:13 build, `fz-20261125-010015` on the 00:46:06 build, and before them `lg-20261124-213020`, `fg-20261124-181737`, `r5-final-20261124-171109` and `r4-final-20261124-151248`) ran on an older bundle and is superseded. What was and was not verified (no CI, Firefox, WebKit, real device, native app, serve.py main lane, the owner's 2560×1353 screen at 1.5×, or a card look at the compact or comfortable density), with the numbers, is in `docs/design/HUD_V2_REMAINING.md`.

Inputs used: `docs/design/hud-next/ledger/` (README §1–8, cockpit.html, secondary.html, glance.html, ledger.css, the shots), `frontend/src/theme/CONTRACT.md`, and the research notes (cockpit-anatomy, modes-and-patterns, gap-2, gap-3, gap-5, guards-and-rollout, plus parts of gap-1, gap-4 and gap-6). Code was read in the `claude/hud-redesign` worktree with Phase A's edits in progress. Functions and endpoints are named; line numbers are avoided because they are moving.

---

## 0. The decisions on one page

1. **One structure.** The Ledger page frame replaces the cockpit shell for every theme. Masthead, running head, page body and running foot are drawn only with `--n-*` roles, so every theme renders the same structure.
2. **Routes do not change. Four are added.**
   - All 18 mode routes and all 137 `/v2/console/<id>` routes keep their exact URLs. They are now rendered inside their area's page frame, not in an overlay.
   - New ids in `HUD_MODES`: `work` (Work overview), `timeline` (day lanes), `artifacts` (saved replies) and `glance`.
   - The native allowlist regenerates from those ids, so no Rust change is needed.
   - Home stays at `/v2/cockpit`. Connect's landing page is `/v2/interop` and Settings' is `/v2/admin`.
3. **The Console stops being a place.**
   - `/v2/console` becomes "All pages", a site map.
   - `/v2/console/<id>` renders that panel in its area.
   - The backtick key opens the search sheet already filtered to panels.
   - `w` goes to the Observe › World signals page. World is no longer an overlay.
4. **Search and command (Ctrl K) indexes everything.** It covers areas, pages, all 137 panels, agents and read-only actions. It can never run a verdict. The current palette's appearance row labels stay word for word.
5. **The docket is real.**
   - It reads the same feed as the Decision Inbox: `GET /autonomy/tasks?status=blocked&limit=200`, admin.
   - It decides through `POST /autonomy/tasks/{id}/decision` and `POST /autonomy/tasks/groups/{id}/reject`.
   - Friction is graded by `confirmStyle(tier)` from `confirm.tsx`: tier 0 one click, tier 1 two steps, tiers 2–3 a typed phrase.
   - No chord, and no Enter in the signature field, ever signs anything.
   - The Decision Inbox page gets the same grading, so it cannot be used to bypass it.
6. **Honest wording replaces three claims.**
   - The hard-coded "ALL NOMINAL" becomes a verdict computed from real readings.
   - "EGRESS SEALED" becomes a statement about configuration: "No cloud model configured".
   - "% LOCAL 100%" becomes a count with a time window and its basis: "115 of 121 runs · all time · by route". A bare percentage is never shown large.
7. **Agents are shown by exception, using only states the hub can actually prove.** The words *idle*, *ready* and *active* are retired until per-agent activity stamps exist in the backend.
8. **Legacy components stay exported until cleanup.** Their own unit tests keep passing. App-level tests and e2e checks are migrated at cutover.
9. **A temporary development switch** (`?frame=ledger` or `localStorage['hud.frame']`) lets the new frame be built behind the old one. It flips at cutover and is deleted in the cleanup PR. It is never shown to the owner as a setting.
10. **Backend work in Phase B is two tiny additive items:** the dry-run reports `cmd` and `service`, and the observer reports a `since` time. Everything else is deferred, and the page shows a stated fallback meanwhile (§7).

---

## 1. Preconditions and ground rules

### 1.1 Start point
- Phase B branches from the commit where Phase A's work (theme system, legibility pass, AppearanceProvider, `scheme`, the `appearance` panel) is merged into `claude/hud-redesign`.
- No Phase B edits to the files Phase A is touching until then. That includes `app.tsx`, `cockpit.tsx`, `gap.tsx`, `confirm.tsx`, `modes*.tsx`, `panels/*`, `shell.tsx`, `pointer.tsx`, `turn-tools.tsx` and `world_app.tsx`.
- New files can start earlier (§9.3, Stage 1).
- Phase B never edits `styles.css` or anything under `src/theme/`. Needs from those go to Phase A as requests (§9.2.8).

### 1.2 Scaffolding and cutover
- `frontend/src/frame/flag.ts` exports `frameChoice()`: `'ledger' | 'classic'`, read once from `?frame=` or `localStorage['hud.frame']`. The default is `'classic'` until cutover.
- `App` renders the legacy tree (unchanged) or the new `Frame` tree.
- **Cutover PR:** the default becomes `ledger`, App-level unit tests and e2e checks are migrated (§8), and the bundle is rebuilt.
- **Cleanup PR:** legacy components and their tests are deleted together, along with the flag (§2.4).

### 1.3 Styling rules (all engineers)
- **Colours and type.** Colours only through `--n-*` roles. Type only through `--n-fs-*`, `--n-lh-*`, `--n-font-*` and the label voice: `LABEL`, `MONO`, `PROSE` and `fs()` from `src/theme/type.ts`. No colour literals, no font size under 12px, no `text-transform`/`letter-spacing` on labels.
- **The accent colour (`--n-accent`) means the owner's hand only.** It is used for "awaits your signature", "signed" and the Work count. The stop uses `--n-stop`. Status is shown by a mark plus a word, never by colour alone.
- **New markup never reuses a legacy class name from `styles.css`** (`.topbar`, `.rail-btn`, `.inputbar`, `.transmit`, `.msg`, `.bubble`, `.convo`, `.dcard`, `.panel`, `.badge`, …). Otherwise legacy layout rules would bleed into the new markup. Test hooks are `data-*` attributes and ARIA roles:

  | Hook | Where |
  |---|---|
  | `data-frame="masthead"`, `"runhead"`, `"runfoot"`, `"page"` | the frame regions |
  | `data-register="day"`, `"talk"`, `"docket"`, `"record"` | Home registers |
  | `data-composer` (kept), `data-composer-bar`, `data-composer-send` | the composer |
  | `data-turn="owner"`, `"reply"`, `"system"`, `"vision"`, plus `data-turn-body` | transcript turns |
  | `data-docket-entry=<taskId>` | docket entries |
  | `data-chrome="gateway"`, `"sessions"`, `"version"` (kept) | the running foot |
  | `data-anchor` | agent tips and tours (§3.8) |

- **Class ownership** (agree it with Phase A's lead before coding).
  - Phase A's `kit.css` owns the primitives: `n-btn` (variants `--sm`, `--ink`, `--accent`, `--bare`), `n-seg`, `n-input`, `n-textarea`, `n-link`, `n-kbd`, `n-tag`, `n-row`, `n-state`, `n-card`, the focus ring.
  - Phase B owns the structural blocks: `n-masthead`, `n-areas`, `n-runhead`, `n-signals`, `n-runfoot`, `n-notices`, `n-spread`, `n-register`, `n-sec`, `n-total`, `n-contents`, `n-toc`, `n-key`, `n-cmd`, `n-docket`, `n-entry`, `n-signline`, `n-transcript`, `n-turn`, `n-working`, `n-steps`, `n-footnote`, `n-composer`, `n-verdict`, `n-causes`, `n-dayband`, `n-schedule`, `n-away`, `n-machine`, `n-agents`, `n-chain`, `n-lanes`, `n-glance`, `n-areapage`, plus `n-mk` marks and `n-tier` glyphs.
  - If a primitive is missing when it is needed, E2 defines it under Phase A's name in `frame/kit.css` and hands it over.
- **CSS files sit beside the components and are imported by them,** as `chat-history-search.css` is today.
- **Shared breakpoints** (these are the Ledger's):

  | Width or height | Change |
  |---|---|
  | ≥ 2200 px | four registers on Home; reading sizes step up (Phase A, theme file) |
  | 1680–2199 px | three registers |
  | 1340–1679 px | the day folds into a band; two registers |
  | ≤ 1339 px | tighter version of the two-register layout |
  | ≤ 1099 px | one column |
  | ≤ 759 px | masthead areas move into a drawer |
  | height ≤ 1199 px | items marked "tall" are hidden |

- **Responsive text.** Long and short label variants are rendered side by side and switched by CSS. Tests must not assume a single text match (use `getAllBy…` or `data-*` hooks).
- **Motion.** 120 ms (`--n-dur-1`) on hover and press, 180 ms (`--n-dur-2`) when a row opens. Nothing else animates: no pulses, spinners or marquees.

### 1.4 Honesty rules (they decide what gets drawn)
- **Every reading has a state:** `live`, `stale`, `unknown`, `refused`, `offline`, `demo`, `empty` or `disabled`.
  - "Stale" means older than 2.5 times its polling interval.
  - Unknown is drawn as a dashed mark and the word *Unknown*, with a reason. It is never 0, never a default, never an all-clear.
- **Every locality readout carries its basis:** `measured`, `declared`, `derived`, `seeded` or `unknown`, as defined in gap-5 §7.
- **Titles from the queue are plain text** (they may come from untrusted producers): no Markdown and no markup. Kinds become words only through fixed lookup tables, never generated copy.
- **A row is drawn only if its field exists.** That covers rollback, deadline, judge opinion, `asked_under`, `delegated_by`, taint flags, consent, groups and preview effects.
- **Demo data carries a "Demo sample" label at section level,** and every decision control is disabled while demo is on.

### 1.5 Branch and bundle rules
- Engineers do not commit `agents/web/v2` or `agents/web/workspace`. E2 rebuilds and commits the bundle at each integration point and in the cutover and cleanup PRs. CI's drift check (`hud-v2-build`) only has to pass on those.
- `tests/test_hud_v2_parity.py` pins strings that must survive. Its route-caller ratchets also apply: when Phase B adds the first caller of a route listed in `UNCALLED_BACKLOG` or `MACHINE_FACING` (`/api/status/slots` is one), remove that entry in the same PR.

  | Pinned string | Must stay in |
  |---|---|
  | `PANEL_COMPONENTS[selected.component]` | `gap.tsx` |
  | `./composer-vault` and `<VaultNoteReview draft={vault}/>` | `cockpit.tsx` |
  | `<HermesRuntimePanel/>` inside `function AdminMode` | `modes3.tsx` |
  | `<SavedFacts` | `modes.tsx` |
  | the CONSOLE_PANELS literal shape | `console-routes.ts` |

---

## 2. Component tree and files

### 2.1 Tree (`frame=ledger`)

```
main.tsx → WorldAwareApp (world_app.tsx; now a thin wrapper) → App (app.tsx)
└─ AppearanceProvider (Phase A)
   └─ div.hud-root [data-look, data-scheme, data-accent, …] [data-frame-root]
      ├─ texture layers (kept; Nerva themes hide them via bridge.css)
      ├─ PendingQuestion (kept)
      ├─ Glance                                  ← route `glance`: full screen, no frame
      └─ Frame                                   ← every other route
         ├─ SkipLink ("Skip to the conversation" on Home; "Skip to the page" elsewhere)
         ├─ Masthead
         │  ├─ BrandMark (ring + N; links to /v2/cockpit)
         │  ├─ AreaNav (9 areas + attention notes)   │  AreaDrawer (≤759 px)
         │  ├─ FindButton (Ctrl K)                    data-anchor="console"
         │  └─ Tools: LangSeg (EN|RO) · SchemeToggle · GlanceButton · StopButton
         ├─ RunningHead: Signal ×6 (egress, local route, microphone, model, data, chain)
         │              · ApprovalModeSeg · Interrupts
         ├─ Notices: SafeModeBanner · PowerChip · PressureBanner · DemoNotice · FirstRunNotice
         │           · appearance sync error · route notice · StopRefusal · ActionFailureBanner
         ├─ main[data-frame="page"] → RouteBoundary → one of:
         │  ├─ Home (/v2/cockpit)
         │  │  ├─ DayBand (1340–1679 px and below)
         │  │  └─ Spread.home
         │  │     ├─ DayRegister:    DayHead · Verdict(+Causes, Remedy) · ThisMachine (≥2200)
         │  │     │                  · TodayList · AwayList · "More in Home" link
         │  │     ├─ TalkRegister:   TalkHead (recipient · routing policy · search earlier)
         │  │     │                  · Transcript (Turn · WorkingReply · ReplyFootnote · ApprovalSlip)
         │  │     │                  · Composer
         │  │     ├─ Docket:         DocketHead · DocketCols · DocketEntry ×n (open entry:
         │  │     │                  Consequence · Members · SignLine · EntryActs)
         │  │     │                  · OtherWaiting · DocketTotal
         │  │     └─ AgentsRecordRegister (≥2200): AgentsByException · RecordTail
         │  ├─ ChatPage (/v2/chat): AreaPage(home) with TalkRegister at full width
         │  ├─ AreaPage(area, page): PageHead (title · SourceLabel · PageHeaderBar)
         │  │  · ContentsColumn · PageBody
         │  │  └─ PageBody is one of: WorkOverview · Timeline · TrustOverview · ArtifactsPage
         │  │     · AllPages (/v2/console) · PanelPage(→ gap.ConsolePanel)
         │  │     · ModePage(AgentsMode | MemoryMode | AutonomyMode | BuildMode | ObserveMode
         │  │       | InteropMode | CommsMode | AdminMode | Finance/Health/Knowledge/FamilyMode
         │  │       | ProjectsMode | JobsWorkspace | WorldIntelligenceMode)
         └─ RunningFoot: AgentsSummary · MachineMeters · (≥2200) Channels + key hint · Version
      Overlays (kept): ProvModal · Dossier (+ "Talk to") · FirstRunGate · PointerOverlay
                       · PetCompanionOverlay · CommandSheet (replaces Palette) · ShortcutsPanel
                       · CinemaMesh (unchanged; `m`)
Floating desktop window: App floating → ChatPage(variant="floating"): DesktopControls
                         · RunningHead variant="marks" · DocketLine · TalkRegister
```

### 2.2 New files (owner in brackets)

| Path under `frontend/src/` | Responsibility |
|---|---|
| `nav/areas.ts` [E1] | The registry: 9 areas, their groups and pages (modes, views, panels) with en/ro labels, aliases, the `primary` flag and attention or count keys. The placement table in §3.3 lives here. |
| `nav/placement.ts` [E1] | Which area a panel belongs to: an explicit map, else a default by the panel's `group` in CONSOLE_PANELS (§3.3). |
| `nav/routes.ts` [E1] | `pageForRoute(route)` returns the area, the page entry and the page kind; `pathOf(ref)`; `pageTitle(route, lang)`; `areaOfMode`; `areaOfPanel`. |
| `nav/commands.ts` + `nav/search.ts` [E1] | The command index and its ranking (diacritic- and case-insensitive; prefix-of-word; aliases; recent items). `defineCommands()` throws if an *action* command matches `FORBIDDEN_TARGET`. |
| `nav/CommandSheet.tsx`, `nav/sheet.css` [E1] | The Ctrl K sheet: a dialog with a combobox and listbox; can open filtered to panels. |
| `nav/ContentsColumn.tsx`, `nav/AllPages.tsx`, `nav/contents.css` [E1] | Second-level navigation and the `/v2/console` site map. |
| `frame/flag.ts` [E2] | The development switch. |
| `frame/kit/*` [E2] | Building blocks for every engineer: `Mark` (marks sprite), `TierGlyph`, `SourceLabel`, `Register`, `SecHead`, `Total` (single rule above, double below), `Consequence` (dl), `Disclosure`, `MarksKey`, plus `kit.css`. |
| `frame/Frame.tsx`, `Masthead.tsx`, `AreaNav.tsx`, `AreaDrawer.tsx`, `RunningHead.tsx`, `RunningFoot.tsx`, `Notices.tsx`, `StopButton.tsx`, `useKillSwitch.ts`, `AreaPage.tsx`, `PanelPage.tsx`, `ModePage.tsx`, `frame.css` [E2] | The frame on every page. |
| `home/Home.tsx`, `home/ChatPage.tsx`, `home/home.css` [E2] | The Home spread grid per width; the chat page; the floating variant's frame. |
| `signals/types.ts` [E3] | The shared types: `Reading<T>`, `Basis`, `HubSnapshot`, `SignalView`, `Verdict`, `Cause`, `AgentState`, `MachineReading`, `AwayEntry`, `ReplyMarker`, `Attention`. |
| `signals/poll.ts` [E3] | `usePolled(path, {admin, intervalMs, enabled})` returns a `Reading`. Requests are shared by path, pause while the document is hidden, and tell refused (401/403) apart from offline. Has a reset helper for tests. |
| `signals/trust-signals.ts`, `verdict.ts`, `agents-exception.ts`, `machine.ts`, `away.ts`, `provenance.ts`, `attention.ts`, `agents-policy.ts` [E3] | Pure derivations, each with tests. `agents-policy.ts` holds the shared lists: local-only `frigga`, `ultron`, `howard`, `hestia`; cloud-only `athena`. |
| `signals/hooks.ts` [E3] | `useApprovalMode` (`/autonomy/mode`), `useInterrupts` (`/autonomy/interrupts`), `useAuditVerify` (`/api/security/audit/verify`), `useObserver` (`/autonomy/observer`), `useAway` (`/api/dashboard/today`), `useHeartbeats` (`/heartbeat/status`), `useSlots` (`/api/status/slots`), `useSubagents` (`/api/subagents`), `useRunningTasks` (`/autonomy/tasks?status=running`), `useEgressLedger` (`/api/admin/network/calls`, admin, optional), `useAttention`. |
| `home/day/DayRegister.tsx`, `Verdict.tsx`, `TodayList.tsx`, `AwayList.tsx`, `ThisMachine.tsx`, `DayBand.tsx`, `day.css` [E3] | The day register and the folded day band. |
| `api/decisions.ts` [E4] | The single decision client: `decide(id, action, {payload, reason})`, `rejectGroup(group, reason)`, `preview(id)`, `listBlocked()`. It is the only module that posts to `/autonomy/tasks/*`. |
| `docket/types.ts`, `model.ts`, `phrases.ts`, `kinds.ts`, `useDocket.ts`, `demo.ts` [E4] | Feed, grouping, ordering, friction, typed phrases, the kind→words map, the demo corpus. |
| `docket/Docket.tsx`, `DocketEntry.tsx`, `SignLine.tsx`, `PayloadEditor.tsx`, `docket.css` [E4] | The docket register. |
| `home/talk/TalkRegister.tsx`, `RecipientPicker.tsx`, `WorkingReply.tsx`, `ReplyFootnote.tsx`, `ReplyActions.tsx`, `ApprovalSlip.tsx`, `talk.css` [E5] | The conversation register. Transcript turns stay inside `cockpit.tsx` (below). |
| `pages/WorkOverview.tsx`, `Timeline.tsx`, `TrustOverview.tsx`, `RecordTable.tsx`, `AgentsRecordRegister.tsx`, `ArtifactsPage.tsx`, `Glance.tsx`, `PageSection.tsx`, `pages.css` [E6] | Area landing pages, Glance, the record table, and the section wrapper that replaces the per-mode panel wrappers. |
| `e2e/ledger-shots.spec.ts`, `playwright.ledger-shots.config.ts` (under `frontend/`) [E2] | The render matrix and its gates (§9.5). |

### 2.3 Changed files

| File | Owner | Change |
|---|---|---|
| `hud-modes.ts` | E1 | Add `work`, `timeline`, `artifacts`, `glance`. |
| `desktop/src-tauri/hud-routes.json` | E1 | Regenerated by `frontend/scripts/generate-desktop-routes.mjs` (the script is unchanged). |
| `hud-routing.ts` | E1 | Titles come from `pageTitle`. `isOverlay()` becomes `glance` only: World and Console become pages. Validity rules unchanged. |
| `shortcuts.ts` | E1 | Defaults remapped (§3.6). `FORBIDDEN_TARGET` unchanged and exported for `commands.ts`. |
| `pointer.tsx` | E1 | Fallback anchors in `anchorRect` (§3.8). `POINTER_ANCHORS` unchanged. |
| `app.tsx` | E2 only | Flag switch; Frame tree; hub snapshot with check times; three timing stamps on the reply bubble that `runTurn` reserves (`_askedAt` when reserved, `_startedAt` on the first `start` event, `_firstTokenAt` on the first `token`); `openDossier` without changing the recipient; wiring for the command sheet, artifacts page, Dossier "Talk to", Glance and the per-component clock (the 1-second clock moves into Cinema and Ambient; App keeps a minute clock). |
| `world_app.tsx` | E2 | Remove the fixed WORLD button, the World overlay and the `.rail` style injection under `frame=ledger`. Exports stay until cleanup. |
| `gap.tsx` | E2 | Add `export function ConsolePanel({ panelId })`. It renders `<ActionFailureBanner/>` plus the panel chosen by `PANEL_COMPONENTS[selected.component]` (that exact expression is pinned). `ConsoleOverlay` stays until cleanup. |
| `gap.tsx` (`DecisionInboxPanel` only) | E4 | Accept / approve once / save and approve go through `ConfirmAction` at the task's tier; "Allow always" and "reject group" become two-step; the decision POSTs route through `api/decisions.ts`. |
| `confirm.tsx` | E4 | Additive props: `enterConfirms` (default `true`, so `confirm.test.tsx` passes unchanged), `plain` (no inline colours, classes only), `inputClassName`, `groupClassName`. |
| `api/loaders.ts` | E3 | Additive: keep `slots`, `llm_backend`, `configured_model` and `residency_state` from `/status`; return `checkedAt`. `decisionCard()` is unchanged (still used by the wall and Ambient). |
| `cockpit.tsx` | E5 | Re-lay `Conversation` (new turn markup, `role="log"` region, footnote, action budget) and `InputBar` (multi-line composer, five visible controls, Attach and Options menus) in place. Props, logic and accessible names are kept. `<VaultNoteReview draft={vault}/>` stays. |
| `turn-tools.tsx` | E5 | `TurnApprovals` becomes the approval slip: it links to the docket entry, or to `/v2/console/decision-inbox?card=<id>` if the entry is not on the docket. In-app navigation via `navigateHud`. |
| `modes3.tsx` | E5 + E6 | E5 moves `ChatMode` into `home/ChatPage.tsx` and leaves a re-export. E6 owns the rest of the file. |
| `data.ts` (I18N) | E5 | `transmit` becomes 'Send' / 'Trimite'; `placeholder` becomes 'Message {agent}…'. The `channel` key is no longer rendered; the key stays. |
| `modes.tsx`, `modes2.tsx`, `modes3.tsx` (non-chat), `modes4.tsx`, `modes_world.tsx`, `api/live.ts` | E6 | Replace the five panel wrappers (`ModePanel`, `MP`, `Panel`, the hand-written `.panel` and `.bk` blocks) with `PageSection`. `TrustMode` becomes `TrustOverview`. Optional: the gate fix for Autonomy (gap-2 defect D1). |
| `agents/core/autonomy/dry_run.py` | E3 | Add `"cmd"` and `"service"` to `_EFFECT_KEYS`; test in `tests/test_h12_5_autonomy_dryrun.py`. |
| `agents/core/autonomy/observer.py` | E3 | `Observer.status()` returns `since` (ISO) for each unhealthy key, recorded when the key flips to unhealthy; plus a test. |

### 2.4 Retired (cutover stops rendering them; cleanup deletes them and their tests)

| Retired | Replaced by |
|---|---|
| `TopBar`, the badges, the 40px clock | Masthead and running head; the time sits in the day register's head and in Glance |
| `Ticker` and "ALL NOMINAL" | Verdict, Causes and While you were away |
| `Rail`, `RailDrawer`, `Tabs`, `MODES` | AreaNav, AreaDrawer and ContentsColumn |
| `RosterColumn` and the System panel | Agents by exception (foot, 2560 register) and the machine meters |
| `NeuralMesh` on Home | Remains only in Cinema (`m`) |
| Centre tabs: Cognition, Artifacts | The working reply's steps; `/v2/artifacts` |
| `ContextColumn` (queue, weather, today, heartbeat) | Docket, TodayList; Heartbeat is dropped because it is always empty |
| `Palette`, `LangMenu` | CommandSheet, LangSeg |
| `Ambient` | Glance |
| `ConsoleOverlay` and the fixed CONSOLE and WORLD buttons | AllPages, PanelPage, the World page |
| `ModeEmpty`, `ModeStub` | The area-page empty state |
| `CognitionStream`, `buildTrace`, `traceFromCognition` and the `/api/cognition/stream` subscription in App | Retired (honesty defects D11 and D15). The Observe › Cognition panel remains. |

---

## 3. Navigation and routing

### 3.1 The page model
- An **area** is one of nine entries in the masthead.
- A **page** is one route: a mode id (`/v2/<mode>`) or a panel id (`/v2/console/<id>`).
- Each area has a **landing page** and **groups** of pages shown in its contents column.
- `pageForRoute()` resolves every valid `HudRoute` to `{ area, entry, kind: 'home' | 'chat' | 'glance' | 'mode' | 'panel' | 'allPages' }`.

### 3.2 Route table

| Route | Area › page | Rendered by |
|---|---|---|
| `/v2`, `/v2/`, `/v2/cockpit` | Home › Today | `Home` (the root fallback stays cockpit) |
| `/v2/chat` | Home › Conversation | `ChatPage` (also the floating window) |
| `/v2/work` (new) | Work › Overview | `WorkOverview` |
| `/v2/timeline` (new) | Work › Timeline | `Timeline` |
| `/v2/projects` | Work › Projects | `ProjectsMode` |
| `/v2/jobs` | Work › Scheduled jobs | `JobsWorkspace` |
| `/v2/autonomy` | Work › Autonomy | `AutonomyMode` |
| `/v2/agents` | Agents › Roster (landing) | `AgentsMode` (opens the Dossier without changing who you write to) |
| `/v2/finance`, `/v2/health`, `/v2/knowledge`, `/v2/family` | Agents › Gecko · Finance, Hercules · Health, Vision · Knowledge, Frigga · Family | the existing mode components |
| `/v2/memory` | Memory › Overview | `MemoryMode` |
| `/v2/artifacts` (new) | Memory › Saved replies | `ArtifactsPage` (wraps `ArtifactsPanel`) |
| `/v2/trust` | Trust › Overview | `TrustOverview` |
| `/v2/build` | Build › Overview | `BuildMode` |
| `/v2/interop` | Connect › Overview | `InteropMode` |
| `/v2/comms` | Connect › Inbox | `CommsMode` |
| `/v2/observe` | Observe › Overview | `ObserveMode` |
| `/v2/world` | Observe › World signals | `WorldIntelligenceMode`, now a page |
| `/v2/admin` | Settings › Overview | `AdminMode` |
| `/v2/glance` (new) | Glance (a Home view, full screen) | `Glance` |
| `/v2/console` | All pages | `AllPages` |
| `/v2/console/<id>` | owning area › panel | `PanelPage` → `gap.ConsolePanel` (query and hash kept, e.g. `?card=`, `?doc=`, `?install=`) |

`?demo=1`, `?world=1`, `#world` and `?desktop=floating` keep their current meaning.

### 3.3 Area contents: where all 137 panels live

Rule: a panel's area is the explicit entry below. A panel that has no entry — any new panel added later — lands in the default area for its CONSOLE_PANELS `group`, under "More pages":

| CONSOLE_PANELS group | Default area |
|---|---|
| Start | Home |
| Home | Home |
| Memory | Memory |
| Trust | Trust |
| Interop | Connect |
| Observe | Observe |
| Build | Build |
| Autonomy & Agents | Work |
| Admin | Settings |

**Test invariants:**
- Every `CONSOLE_PANELS` id resolves to exactly one area.
- Every explicit entry exists in `CONSOLE_PANELS`, except `appearance`, which is marked optional with a reason until Phase A lands it.
- Every `HUD_MODES` id appears exactly once.
- Duplicates are declared: the panel `jobs` is a `duplicateOf` the mode `jobs`; both URLs work, and the contents column lists only `/v2/jobs`.

The assignment starts from modes-and-patterns §6.5. Deviations:
- `today` ("Today in Jarvis") moves from Work to Home, because Home is the day and its While you were away list opens it.
- The Phase A panel `appearance` goes in Settings.

| Area (landing) | Groups → pages (labels as shown; panel id in parentheses) |
|---|---|
| **Home** (`cockpit`) | Today · Conversation (`chat`) · *Your day:* What Nerva did today (`today`), Today's receipt (`today-receipt`), Usage and cost (`usage`), Presence inbox (`presence-inbox`) · *Around you:* Ambient watch (`ambient-watch`), House (`house`), Camera (`camera`) · *Start here:* Command center (`command-center`), Documentation (`docs`). **9 panels** |
| **Work** (`work`) | Overview · Timeline · Decisions (`decision-inbox`) [count from the docket] · *Projects:* Projects (`projects`), Missions (`missions`), Mission canvas (`mission-canvas`), Sessions (`sessions`), Transcript (`transcript`) · *Scheduled:* Scheduled jobs (`jobs` mode; panel `jobs` is its duplicate), Schedule (`schedule`), Heartbeats (`heartbeat`) · *Autonomy:* Autonomy (`autonomy`), Autonomy control (`autonomy-control`), Escalation (`escalation`), Learning (`learning`), Quickbar (`quickbar`), Context meter (`context-meter`). **13 panels** |
| **Agents** (`agents`) | Roster · *Agent homes:* finance, health, knowledge, family · *How they work:* Agent autonomy (`agent-autonomy`), Company room (`company-room`), Sub-agents (`sub-agents`), Swarm (`swarm`), Committees (`moa-presets`) · *Shape them:* Prompts (`prompts`), Templates (`templates`), Agents arena (`agents-arena`), Companions (`pets`). **9 panels** |
| **Memory** (`memory`) | Overview · Saved replies (`artifacts`) · *What it knows:* Knowledge graph (`kg`), Long-term memory (`long-term-memory`), Notes (`notes`), Note documents (`note-docs`), Local documents (`local-docs`), Vault (`vault`), Data spaces (`data-spaces`) · *How it learns:* Write to memory (`memory-write`), Capture (`capture`), Reflection (`reflection`), Consolidate (`memory-consolidate`), Hygiene (`memory-hygiene`) · *Checks:* Memory evaluation (`memory-eval`), Provenance (`provenance`). **14 panels** |
| **Trust** (`trust`) | Overview · *The record:* Audit anchors (`audit-anchors`), Governance (`governance`), Kernel metrics (`kernel-metrics`) · *Your authority:* Emergency stop (`kill-switch`) [word: armed / halted / unknown], Payments (`payments`) [count waiting], Permissions (`permissions`), Capabilities (`capabilities`), Skill switches (`skill-switches`) · *Secrets and access:* Secrets (`secrets`), Pairing (`pairing`), Trust operations (`trust-ops`) · *Boundary:* Posture (`posture`), Signal governance (`signal-governance`), Network monitor (`network-monitor`), Outbound rate (`comms-rate`), Safe drafts (`safe-comms-draft`), Injection scan (`injection-scan`) · *Defences:* Security skills (`security-skills`), Security skills map (`security-skills-map`), Loop breaker (`loop-breaker`), Readiness (`readiness`). **21 panels** |
| **Build** (`build`) | Overview · *Create:* Images (`images`), Creative (`creative`), Media director (`media-director`), Media gallery (`media-gallery`), Publish readiness (`publish-readiness`) · *Automate:* Workflows (`workflows`), Workflow builder (`workflow-builder`), Workflow traces (`workflow-traces`), Operator (`operator`), Browser broker (`browser-broker`), Screen reflex (`screen-reflex`), Sandbox (`sandbox`) · *Skills:* Import skills (`skills-import`), Marketplace (`marketplace`), Marketplace admin (`marketplace-admin`), Skill history (`skill-history`), Packs (`packs`), Pending skills (`pending-skills`) · *This machine:* Host readiness (`host-readiness`), Desktop allowlist (`desktop-allowlist`), Extensions (`extensions`), Acquisition (`acquisition`). **22 panels** |
| **Connect** (`interop`) | Overview · Inbox (`comms`) · *Channels:* Channels (`channels-config`), Rooms (`rooms`), Remote members (`remote-members`), Integrations (`integrations`), OAuth sign-ins (`o-auth`) · *Agents elsewhere:* A2A inbox (`a2-a-inbox`), Mesh peers (`mesh-peers`), Satellites (`satellites`), Device sync (`device-sync`) · *Tools and feeds:* MCP servers (`mcp`), Webhooks (`webhooks`), Hooks (`hooks`), Oracle (`oracle`), OSINT (`osint`), Watchlist (`watchlist`), Signal routing (`signal-routing`), Writeback digest (`writeback-digest`). **17 panels** |
| **Observe** (`observe`) | Overview · World signals (`world`) · *Health:* System map (`system-map`), Logs (`logs`), Performance (`apm`), Model info (`model-info`), Design manifest (`design-manifest`) · *Quality:* Evaluation (`eval`), Review (`review`), Review quality (`review-quality`), Arena (`arena`), Quality (`quality`), Coach (`coach`), Feedback (`feedback`) · *Learning:* Cognition (`cognition`), Self-improvement (`self-improvement`), Code intelligence (`code-intel`), Onboarding (`onboarding`). **16 panels** |
| **Settings** (`admin`) | Overview · Personalisation (`appearance`, Phase A) · *Models:* Model setup (`model-setup`), LM Studio (`lm-studio`), Model routing (`llm-routing`), Custom endpoints (`custom-endpoints`), Provider packages (`provider-packages`), Provider check (`provider-check`), Provider quota (`provider-quota`), Image description model (`vlm-describe`), Auth profiles (`auth-profiles`) · *System:* All settings (`settings`), System profile (`system-profile`), Restart and update (`restart-update`), Backup (`backup`), Files (`files`), Inspector (`inspector`), Voice support (`support-voice`). **16 panels** (17 with `appearance`) |

Total: 9 + 13 + 9 + 14 + 21 + 22 + 17 + 16 + 16 = **137**.

**Labels.** The table's labels are display labels. `CONSOLE_PANELS` labels and ids stay as they are, because tests and bookmarks use them. Old labels are search aliases ("Kg", "O Auth", "A2 A Inbox", "Llm Routing", "Vlm Describe", "Console", "Cockpit", "Interop", "Admin", "Ambient").

**"More pages".** E1 sets `primary: false` on the rarely used technical pages so each contents column shows at most about 12 (about 9 at 800px height). The rest go behind "N more pages", which also says "Ctrl K finds any of the N".

**Home's sub-pages.** Today itself has no contents column. Home's sub-pages appear in the contents column on every Home sub-page, behind a quiet "More in Home · 10 pages" link at the foot of the day register, and in Ctrl K.

### 3.4 Titles, overlays and history
- **Titles** come from `pageTitle(route, lang)`:
  - Home: `Today · Nerva`
  - a landing page: `<Area> · Nerva`
  - a sub-page: `<Page> · <Area> · Nerva`
  - All pages: `All pages · Nerva`
  - The `· Console · Nerva` titles go away.
- **Glance is the only overlay route.** Esc runs `closeHudOverlay()` and returns to where the owner was; a direct load returns to `/v2/cockpit`. World and Console become ordinary pages, so Back and Forward work through normal history.
- Analytics keep calling `trackPageview(route.path)`, unchanged.

### 3.5 Native allowlist
- Add the 4 ids to `HUD_MODES` and run `node --experimental-strip-types frontend/scripts/generate-desktop-routes.mjs`.
- `src/test/desktop-route-sync.test.ts` then passes unchanged.
- The Rust tests in `desktop/src-tauri/src/policy.rs` iterate the JSON, so they still pass: `/v2/unknown` and 3-segment paths remain refused.
- No path gains a third segment: second-level pages are the existing `/v2/console/<id>` paths.

### 3.6 Hotkeys and the shortcuts rule (`shortcuts.ts`)

| Key | Today | Phase B (action id kept unless noted) |
|---|---|---|
| `1`–`9`, `0` | cockpit, agents, trust, memory, autonomy, build, observe, interop, chat, comms | masthead order: 1 Home (`mode.cockpit`), 2 Work (`mode.work`, **new id**), 3 Agents, 4 Memory, 5 Trust, 6 Build, 7 Connect (`mode.interop`, label "Go to Connect"), 8 Observe, 9 Settings (`mode.admin`, label "Go to Settings"), 0 Conversation (`mode.chat`). `mode.autonomy` and `mode.comms` are removed: `readOverrides` already drops stored overrides for unknown ids, and both pages stay one click away in their contents columns and in Ctrl K. |
| `w` | World overlay | `view.world`: go to Observe › World signals |
| `` ` `` | open or close Console | `view.console`, label "Find a panel": opens the sheet filtered to panels |
| `a` | Ambient | `view.ambient` (id kept), label "Glance": goes to `/v2/glance` |
| `m` | Cinema | unchanged (Cinema keeps the mesh, orb and wall: the owner asked for those) |
| `/`, mod+K, mod+/ | composer, palette, shortcuts | unchanged; mod+K opens the sheet |

- `FORBIDDEN_TARGET` and `defineActions()` stay as they are.
- No docket verb is ever registered, and no sheet command is ever a verdict.
- Single keys still do nothing while the focus is in a field or in `[role="log"]` (current App logic).

### 3.7 Search and command (Ctrl K), `CommandSheet`

**What it finds**

| Kind | Entries |
|---|---|
| Areas | the 9 areas |
| Pages and panels | the 18 modes, 4 views and all 137+ panels; the hint shows "Area › Group" |
| Agents | per agent in the roster: "Open <Agent>" opens the Dossier without changing who you write to; "Write to <Agent>" calls `selectChatAgent` and focuses the composer |
| Actions (navigation and read-only only) | Glance, Cinema, Keyboard shortcuts, Verify the record again, Refresh live data, Demo sample on/off, Personalisation…, and every appearance row Phase A has added — word for word: `Look · …`, `Scheme · …`, `Accent · …`, `Density · …`, `Motion · …`, `Font · …`, `Scanline · …`, `Dot grid · …`, `Language · …` |

**Never in the sheet:** sign, approve, reject, defer, consent, stop, mode changes. `defineCommands()` throws if an *action*'s id or label matches `FORBIDDEN_TARGET`. *Navigation* entries may mention decisions ("Decisions"), because they only navigate.

**Interaction**
- Arrow keys move, Enter runs, Esc closes and returns focus to where it was.
- Matching ignores case and Romanian diacritics (ș, ț, ă, â, î).
- The 5 most recent items are kept in `localStorage['nerva.sheet.recent']`.
- Backtick opens it with the "Panels:" filter applied.

### 3.8 Agent tips and tours (`pointer.tsx`)
- The hub's anchor list (`POINTER_ANCHORS`, mirrored by `agents/core/canvas.py`) does not change.
- `anchorRect(target)` first looks for an exact `[data-anchor=target]`. If none is found, it falls back:

  | Anchor | Falls back to |
  |---|---|
  | `mode.<id>` | the masthead link of that mode's area (`data-anchor="area.<areaId>"`), or the contents-column link if present |
  | `decisions` | the docket register |
  | `console` | the Find button |
  | `composer` | stays on the composer textarea |

### 3.9 Attention counts (masthead and contents)

Counts appear only when a provider returns a *live* positive value. Unknown means no number at all.

| Where | Provider | Shown as |
|---|---|---|
| Work | docket entries | "N need you" (≥1680px) or "N" (narrower), in the accent colour |
| Observe | unhealthy observer probes (`/autonomy/observer` if admin, else WARNING/ALERT items in `/ticker`) | "■ N services down" |
| Trust | audit chain invalid → "■ record broken"; else payments waiting (`/api/payments`) → "N waits" (accent) | as stated |
| Contents column | `decision-inbox` (docket count), `payments` (waiting), `kill-switch` (Armed, Halted or Unknown) | as stated |

---

## 4. The frame on every page

### 4.1 Masthead (`Masthead`, E2)
- **Brand:** the ring-and-N mark at 28px (30px at xl) plus "Nerva" in `--n-font-title` bold; links to `/v2/cockpit`. The spinning reactor and the subtitle are retired; the version moves to the foot.
- **AreaNav:** `nav[aria-label="Areas"]` with nine links, `aria-current="page"` on the current area, the attention notes from §3.9, and `data-anchor="area.<id>"`. Below 760px it collapses to an "Areas" button that opens `AreaDrawer`, a dialog that reuses `RailDrawer`'s focus and Escape behaviour.
- **FindButton:** "Search or run a command · Ctrl K" (the key shown comes from `displayChord(chordOf(overrides,'session.palette'))`); carries `data-anchor="console"`.
- **LangSeg:** a radiogroup EN | RO that calls `setPreference('lang')`.
- **SchemeToggle:** switches the resolved scheme. Its aria-label says the current and next scheme. It is disabled with the reason "Classic looks are dark only" when the theme's `schemes` list has one entry. The "system" option stays in Personalisation and Ctrl K.
- **GlanceButton:** goes to `/v2/glance`.
- **StopButton** (`useKillSwitch`):

  | Kill switch state | Button |
  |---|---|
  | Armed or Unknown | "■ Stop all agents" |
  | Global halt on | "Halted · resume in Trust", which links to Trust › Emergency stop |

  - Stop is one click: `POST /api/security/kill-switch {engage:true, scope:'global', reason:'hud'}` (admin), then the state is read again. An unknown state still offers the stop, because stopping is the safe direction.
  - Resume is only on Trust › Emergency stop, typed `DISENGAGE` (tier 2).
  - A refused POST raises the alert notice "Stop was refused — {refusalReason(err)}. Nothing was halted." This matters: the July QA run hit "403 kernel denied" on this route.

### 4.2 Running head (`RunningHead`, E2; wording from E3's `trust-signals.ts`)

The running head is visible at every width.

| Width | Form |
|---|---|
| ≥ 1680 px | long labels |
| 1340–1679 px | short labels |
| ≤ 1339 px | compact (all eight items still on one line) |
| 760–1099 px | wraps to two lines |
| ≤ 759 px, and the 420px floating window | one line of marks and short words |

Every item has a disclosure (title plus a click or keyboard popover) that gives its basis and the time it was checked.

> **Amendment, 2026-11-24.** The width forms above are where the line *starts*. From 1100px the running head then measures itself (`frame/fit.ts`; `RunningHead.tsx` `RUNHEAD_FIT_STEPS`) and, while the row still spills, takes these steps in order, the least loss first, skipping a step that would change nothing at that width, and writes them in `data-fit`:
> 1. `source`: a source label's reason is read, with the sentence in its title (from 1680px);
> 2. `short`: the short labels, the interrupts without "used today" (from 1680px);
> 3. `egress`: the egress value's short form (from 2200px);
> 4. `values`: every value's short form (from 2200px);
> 5. `tight`: the items sit closer (no word lost);
> 6. `labels`: the six labels are read, not drawn; each button is named "Label: value" (from 1340px);
> 7. `mode`: the approval mode folds into a button with its word, and its choice opens in a popover with the same two-step loosening;
> 8. `cut`: the egress statement and the model id may be cut with an ellipsis (the model id first, then its backend, then the egress statement), the whole value kept in the button's name, title and popover;
> 9. `lines`: two lines, the last resort.
>
> **Amendment, 2026-11-24 (third polish round).** Once the walk fits, the steps it took are tried back, the lossiest first, and each stays back only where the line still fits without it (`fit.ts` `fitRow` = walk + `stepBack`), so a width keeps no step a later one made unneeded (at 2560px the egress statement's short form frees more than the long labels the walk gave up first). A step back never makes a cut deeper or adds a line: `labels`, `tight` and `mode` are not given back by cutting a value further. A line that does not fit even with every step keeps them all. Every fit starts afresh, so the same width takes the same steps going down and going up. The masthead takes its steps back the same way. Which steps a width keeps therefore differs from the cumulative list above: with the hub's own answers some looks still read the labels (not draw them) at 1340–1440px because the line does not fit without that step; the measured steps per width are in the run records (`frontend/e2e/artifacts/ledger/runs/`, `runhead-fit-*.json`). While the approval mode's looser choice waits for its second step the `mode` step is held where the choice was asked (`data-hold="line"` or `"fold"`): from 1100px a refit neither folds a choice asked in the line nor unfolds one asked in a popover, and below 1100px a choice asked in a popover keeps the mode folded, until it is answered or closed. The head itself always follows the window: below 760px it is the marks and what waits goes with the mode into the marks' popover, which opens with it. The hub's answer to a write holds nothing; where a fit folds the mode while it is on screen, the popover opens with it. A press outside the fold's popover closes it and never drops a confirmation or refusal drawn in the line. The interrupts are a disclosure in every form like the other signals (a button named "Interrupts: 1 of 4 used today"). Every running-head popover, and the approval mode's box, confirmation and answer, is kept inside the window (below its button, above it where below would leave the window, moved in from an edge). Below 760px the popovers open below the whole head, inset from its sides; they open above it only where below would leave the window, as in Glance's foot at the bottom of its screen.
>
> Items cannot overlap: a line that is too long overflows, which the fit detects, instead of colliding. Where the form table says "compact (all eight items still on one line)", read it as the form the walk starts from. Below 1100px no step is taken: two lines from 760px, and below 760px one line of marks. In the main window's running head (`variant="full"`) that one line keeps the approval mode changeable, in its popover, with the same two-step loosening. Only the marks variant (`variant="marks"`: the 420px floating window and Glance) shows the mode as a read-only button, with its meaning in its popover; from 1100px only `source`, `tight`, `cut` and `lines` apply to that variant. The masthead takes measured steps in the same way (`FIT_STEPS`: `search`, `notes`, `glance`, `hand`, `tight`, `brand`, `stop`, `find`, `tighter`, `scroll`). Every word a step takes off the screen stays in the control's accessible name and a tooltip or popover.

| Item | Source | Words (EN; RO in the strings module) |
|---|---|---|
| **Egress** | `GET /api/trust/status` (`cloud_available`, `claude_available`, `strict_local`); optional `GET /api/admin/network/calls` (admin) | "No cloud model configured" (short "No cloud model"), basis *declared*. Detail: "A setting, not a network measurement; plugins such as weather can still reach the internet." Readable ledger: add "· 42 requests left this machine today, 0 from models" (*measured*). Cloud configured: "◐ Cloud model configured · Anthropic / Gemini or compatible". Unknown: "Unknown — trust status did not answer". "Sealed — nothing can leave this machine" is **never** used. |
| **Local route** (long: "Sent to local runners") | `GET /api/analytics/locality` plus `localityFigure()` | "115 of 121 runs · all time · by route". Detail: "Counted from each run's route label: where the hub sent the prompt, not where the model computed. 6 runs recorded no route and are not counted. Local includes runners on your home network." Derived: "No runs recorded · derived from configuration". Demo: "Demo sample". Never a bare %. |
| **Microphone** | `trust.mic` (already parsed fail-closed by the loader) | "On", "Muted" or "Unknown". Detail: "The hub's microphone permission" plus "listening now" from `voice.status`. |
| **Model** | `/status`: `model_state`, `loaded_model`, `llm_backend` | `<model id>` in mono plus "· <backend>"; "■ No model loaded"; "■ No local backend reachable"; "Unknown". |
| **Data on screen** | hub snapshot `checkedAt` / `lastGoodAt` | "Live · checked 10:50"; "Stale · checked 10:44"; "Offline · last good reading 10:44"; "Demo sample"; "Checking…" before the first answer (this replaces "roster offline", gap-2 defect D9). |
| **Audit chain** | `GET /api/security/audit/verify` (every 5 min and on demand) | "Intact · 921 sealed · verified 10:50" (short "Chain · Intact"); "■ Broken at entry 412"; "Unknown — could not verify". Kept at every width (the owner's requirement overrides the mockup, which hides it below 1680px). |
| **Approval mode** | `GET/POST /autonomy/mode` (admin) via `getAutonomyMode` / `setAutonomyMode` and `modeRefusalNote` | Segmented Auto / Ask / Off. Tooltips give the hub's own meaning of each mode (copied from `agents/core/autonomy/mode.py`). A stricter mode is one click. A looser mode is two steps through `ConfirmAction` tier 1, with "Auto lets reversible actions run without asking". Refused read: disabled, "Unknown — needs the owner credential". No shortcut. |
| **Interrupts** | `GET /autonomy/interrupts` → `{used, per_day, remaining}` (admin) | "1 of 4 used today" or "Unknown". |

### 4.3 Running foot (`RunningFoot`, E2, using E3's derivations)
- **Agents by exception:** "Agents 18 · ▶ 1 working · ⊛ 2 waiting on you · ✓ 3 finished today · ⊘ 1 unavailable · 11 no activity reported". The word "idle" is never used (§5.5 gives the sources). *(Amended 2026-11-24, third polish round: "waiting on you" counts agents, not requests. The masthead's attention notes and the docket count requests, and one agent can have several; the render matrix's stubbed foot draws 32 agents waiting against 64 entries.)*
- **Machine:** RAM, VRAM and GPU load as percentages with meters, from `/status.sys`. A reading with no total is unknown, not 0. "Latency p50 · unknown — not measured" (the hub never fills it).
- **Channels, at every width** (amended 2026-11-24 per §8.2 row 27 and the cutover review): "● 2 of 2 running · 1 session in the last 15 min" from `readStatusChrome`, with `data-chrome="gateway"` and `"sessions"` kept. Below 2200px the form is compact: the session count drops its window ("12 sessions", the full sentence in its title). Below 1680px the meters, the latency item and the "no activity reported" remainder are left out of the foot; the channels stay.
- **≥ 2200px:** the key hint "Ctrl K finds every area, panel, agent and action · No keyboard shortcut signs or rejects".
- **Version:** "Nerva <version>" with `data-chrome="version"`.

### 4.4 Notices
- One stacked region under the running head: ruled lines with a mark and a sentence. No striped colour bars.
- Contents: `SafeModeBanner` (cannot be dismissed), `PowerChip`, `PressureBanner`, the demo notice ("Demo sample on screen · Exit demo"), the first-run notice, the appearance sync error with Retry, the route notice ("Page not found. Returned to Today."), stop refusals, and `ActionFailureBanner`.
- `ActionFailureBanner` is now on every page instead of only inside the Console (modes-and-patterns §2).

### 4.5 Area page (`AreaPage`)
- **Page head:** register title (the page label), a `SourceLabel` (from `liveSourceState()` for modes, the panel's own state for panels), and `PageHeaderBar` as the toolbar slot (Jobs uses it).
- **ContentsColumn:** 232px (264 at xl, 200 at ≤1679, 176 at ≤1339).
- **Page body:** scrolls by itself. When a mode has no live data, the area-page empty state replaces `ModeEmpty`: "Nothing to show yet — this page's source has not answered. It fills in when it does." plus "Show a demo sample" (sets `?demo=1`). The contents column stays usable.
- **PanelPage** moves focus to its heading on navigation, as `ConsoleOverlay` did.

---

## 5. Home

### 5.1 Layout by width (CSS grid in `home/home.css`; widths from ledger.css)

| Viewport | Layout |
|---|---|
| **2560 × 1353 at 1.5×** (≥ 2200) | day 432px · conversation 1fr (prose capped at 660px) · docket 712px · agents and record 404px. The day register gains *This machine*. Reading sizes step up one (Phase A theme breakpoint). |
| **1920 × 1080** (1680–2199) | day 396px · conversation 1fr · docket 664px. Agents and machine move to the foot. The page itself never scrolls; registers scroll inside. |
| **1440 × 900** (1340–1679) | DayBand (3 cells) · conversation 1fr · docket `minmax(500px, 44.5%)`. The open docket entry is shown in full; every other entry becomes one ruled line. |
| **1280 × 800** (≤ 1339) | Same, tighter: docket `minmax(480px, 43.5%)`, the signature instruction moves beside the line, the composer is 1 line and grows to 6. **All entries stay signable**: each has its control on its row, and the docket scrolls inside when it holds more than fits. |
| 760–1099 | One column: DayBand, docket (one-line entries plus the open entry), conversation. |
| < 760 | Same column; the masthead drawer and the running head as marks. Send stays reachable (keeps the e2e layout check at 320/390px). |
| 420 × 620 floating | The conversation alone, the running head as marks, and one docket line: "⊛ N await your signature — sign in the main window" with the existing "Open in app" handoff. No signing in the floating window in Phase B. |

### 5.2 The day (E3)

| Region | Today's code and source | Honestly drawable now | Needs backend | Phase B / fallback |
|---|---|---|---|---|
| Head: date and HH:MM | `useClock()` (App) | yes | — | A minute clock replaces the root's 1-second ticker. |
| **Verdict** | `loadJarvisData` (`/status`: serverUp, `model_state`, `safe_mode`, `sys`), `/ticker`, `usePressure` (`/api/system/pressure`), `useKillSwitch`, `useAuditVerify`, `useObserver` (`/autonomy/observer`, admin), `GET /api/health/components` (`failed`) | yes: state, headline, causes, checked time | a "since" time for the state (B2) | Include B2. Without it: "checked 10:50" only, no "since". |
| Causes | observer `unhealthy[{key, detail, severity}]`, else ticker items whose verb is WARNING/ALERT | key (mono) plus the probe's own detail | — | The consequence line comes from a fixed map and only where code supports it. lmstudio/ollama: "Not blocking: replies are served by <llm_backend>" (computed from `/status`). qdrant/neo4j/n8n: no consequence until E3 confirms the behaviour in backend code. |
| Remedy | the docket model | a link to the matching entry when a `restart_service` entry's `payload.service` is a down key | — | Otherwise no remedy line. |
| This machine (≥2200) | `/status.sys` | yes | latency p50 is never measured | "Unknown — not measured". |
| Today | `/dashboard.calendar` and `.weather` via the loader (`normCal`, `normWeather`) | events (time, title, venue; "in 9 min" computed); weather "București · 9° · Mist" | connected-but-empty vs not connected (gap-2 defect D10) | "Nothing on the calendar today, or the calendar is not connected." |
| While you were away | `GET /api/dashboard/today?days=1&limit=50` (user) — items `{entry_id, ts, kind, title, agent}`; plus docket entries raised since; plus current problems | yes | — | "Since" = this browser's last visit (`localStorage['nerva.home.lastSeenAt']`, written on hide and pagehide), labelled "since 06:00 (this browser)"; start of today if absent. Exceptions in semibold. Total: "N entries · a done · b held or blocked · c problems". Link: "Open the day's record" → `/v2/console/today`. |
| DayBand | the same derivations | yes | — | Three cells (verdict · next event · away summary), each a disclosure button that opens the full list as a popover. |

**Verdict rules** (`signals/verdict.ts`; first match wins):

| # | Condition | State word | Headline |
|---|---|---|---|
| 1 | demo | — | demo verdict, labelled "Demo sample" |
| 2 | first poll not yet answered | Checking | "Checking…" |
| 3 | hub stopped answering | Offline | "The hub is not answering · last good reading HH:MM" |
| 4 | kill switch global halt | Halted | "All agents are stopped" (+ link to Trust › Emergency stop) |
| 5 | safe mode | Degraded | "Running in safe mode · left out: …" |
| 6 | model offline / no model | Problem | "No local backend is reachable" / "No model is loaded — replies cannot be written" (+ link Settings › Model setup) |
| 7 | pressure critical | Problem | the pressure detail |
| 8 | pressure elevated | Degraded | the pressure detail |
| 9 | audit chain invalid | Problem | "The record is broken at entry N" |
| 10 | unhealthy probes | Degraded | "Working, with N local services not responding" |
| 11 | failed optional components | Degraded | "Working, with N optional components that did not start" |
| 12 | every required reading is live | Normal | "Working normally" |
| 13 | otherwise | Unknown | "Unknown — <which readings> did not answer" |

Marks: ok ●, attention ◐, problem ■, unknown dashed ○.

### 5.3 The conversation (E5)

| Region | Today's code and source | Phase B |
|---|---|---|
| Register head | `RoutingPolicyLabel`; the recipient is App's `activeId` | "Conversation" · "with **Jarvis** · Prime Orchestrator · Orchestrated" (declared routing policy). "Search earlier conversations" opens `ChatHistorySearch` (the same opener as Options). |
| Transcript | `Conversation` (`cockpit.tsx`); messages from `/chat/stream` (`runTurn`), `POST /sessions/resume` / `GET /memory` | One `role="log"` region, focusable, labelled, bottom-anchored on the composer. Turn grid: time · who · body. The owner's words in `--n-font-ui` semibold; replies in `--n-font-text`, with the measure capped. System and vision turns are kept, with their warnings. All dialogs (remember, task, teach, Obsidian, Blender review) and receipts keep their logic. |
| **Working reply** | `/chat/stream` events in `runTurn`: `start {agent}`, `token`, `tool {event}` (`mergeToolEvent`), `clarify`, `outcome_progress`, `end`; `thinking`; plus the new stamps `_askedAt`, `_startedAt`, `_firstTokenAt` (E2) | Steps as ruled segments: **Sent** ✓ → **Started — asked <Agent>** → **Tools** (only if tool cards exist: names and states, ▶ running, ✓ done, ■ failed) → **Writing** (word count so far). The current step has a dotted rule. Status line in italic serif ("Waiting for Jarvis to start…", "Running web_search…", "Writing — 214 words so far", "Waiting for your answer"). Meta: "asked 10:48 · 3 min so far" (a local 1-second interval while in flight); where it runs is "reported when the reply ends", or "model <id> (reported)" if `outcome_progress` carried one. One control: "Stop this reply" ("Stop the replies" when more than one is in flight) → `stopTurn`. **Not drawn:** Classify/Route/Gather/Synthesize and "asking Pepper and Stark" — the stream does not report routed agents (gap-2 §5.2). |
| Reply footnote | `m.prov.models` (`modelCalls`), `m.toolActivity` (`toolActivity`), `m.tools`, the outcome's `cost_basis` / `usage_basis` | Where it ran, from E3's `replyMarker()` (gap-5 §7.1): "Sent to Anthropic (cloud) · <model>"; "Sent to Ollama on this computer · <model> · where it ran is not verified"; "⚠ <model> names a cloud model" for `:cloud` / `-cloud` ids; "No model call"; "Where it ran: not reported". With several pairs: the least private one plus "+N more", which opens `ProvModal` (its wording is kept). Tools: "2 tool calls · ✓ web_search · ■ file_write failed". The old `StatusStrip` lines move into "Turn details" on the newest reply. |
| Approval slip | `approvalIds(evt.pending_approvals)` → `TurnApprovals` | "⊛ 1 action waits for your decision — <title from the docket cache> · On the docket". It links; it never decides. |
| Reply actions | `SaveArtifactButton`, `OfficeExportButton`, Photoshop, Obsidian, Create task, Teach skill, `TtsButton`, Blender review | A fixed set: **Copy · Save · Read aloud · Create task · More** (More holds Download Word, Photoshop, Save to Obsidian, Teach skill, Review Blender model, Turn details). Shown on the newest reply and on hover or focus elsewhere. Owner turns: **More** (Remember message, Create task) on hover or focus. |
| **Composer** | `InputBar` (`cockpit.tsx`) and the `composer-*` hooks | **Head:** To (`RecipientPicker`: `selectableChatAgents` → `onSelectAgent = selectChatAgent`, which does not open the Dossier; it warns before stopping an in-flight reply) · Mode (from `useApprovalMode` plus the hub's words, or "Mode unknown"). **Body:** a multi-line textarea (`data-composer`, `data-anchor="composer"`); Enter sends, Shift+Enter adds a line, nothing sends during IME composition; Tab still accepts an `@file:` completion; 4,096-character limit with a count after 3,500. **Bar (the fixed visible set):** Attach ▾ · Voice (mic toggle; "speech-to-text on this machine" only when `voice.caps.stt === true`) · Options ▾ · `/` commands and `@` files hints · Send (`data-composer-send`). When Send is disabled, a visible line says why, built from the existing 12 conditions. **Attach menu:** Images… (the existing file input), Document passage… (`OfficeButton`), Vault notes (`useVaultNotes`; disabled until text is typed), Board result… (`useBoardResult`). **Options menu:** Direct reply (with its help text), Search chat history…, Compare agents…, Make editable Blender model, Skills… (`ComposerSkills`), Voice settings…, Use previous image. Staged items (thumbnails, passages, vault review, board review, history passage, the cloud-consent checkbox) keep rendering above the textarea when present. Removed: `▸` and "VOICE · LOCAL" (gap-2 defect D11). |
| Local-only list | hard-coded `['frigga','ultron','howard']` in `cockpit.tsx` and `chat-history-search.tsx` | Both import `signals/agents-policy.ts`, which adds the missing `hestia` (`agents/core/llm/hybrid_router.py`). |

### 5.4 The docket (E4)

**Feed.**
- `useDocket()` reads `GET /autonomy/tasks?status=blocked&limit=200` (admin) — the exact feed `DecisionInboxPanel` uses, groups included — through the shared poller.
- It refreshes every 30s, on window focus, and after every decision.
- It also reads `GET /api/autonomy/tasks/{id}/preview` (admin): automatically for the open entry, on request for the others.
- Payments (`/api/payments`) and skill proposals (`/api/skills/proposals`) are *not* signable here in Phase B. They appear under the entries as "Other things waiting: 1 payment — Trust › Payments · 3 skill changes — Decisions" (counts only when live).

**Model** (`docket/model.ts`):
- **Entry types:**
  - a hub group: validated as in the inbox (leader, members, count, all visible);
  - a display collapse of identical requests (same kind, title, agent and stable payload hash), shown as "×N identical";
  - a single request.
- **Order:** tier descending, then the soonest `approval_deadline_at`, then oldest first.
- **Totals:** "N entries · M requests" and the friction mix "a typed · b two-step · c one click".
- **Header figure:** the number of entries, in the accent colour. No "actions" figure: the hub never groups distinct asks.
- **Special kinds open in Decisions** (`/v2/console/decision-inbox?card=<id>`) instead of being signed inline: image proposals, consent offers, retention, voice commands, guardian verdicts (`judge.advisory === false`). Their predicates are imported from or mirrored by `gap.tsx`, with tests. This way every verdict the inbox can give remains reachable.

**Entry anatomy**

| Part | Field (only when present) | Words |
|---|---|---|
| Risk | `risk_tier`, `tier_name`, `agent` (+ role from the roster), `created_at`, collapse count, `delegated_by` | `TierGlyph` + "Read only", "Reversible", "External", "Irreversible", or "Money" (tier 3 with `payload.amount` or a money kind); "Steve · raised 2 Jul · waiting 140 days · ×14 identical"; "asked by a sub-agent of X" |
| Title | `title` | plain text, verbatim |
| Why | `approvalModeNote(approval_mode, asked_under).why` | the hub-backed sentence; "Not sent to your phone" when `pushed` is false |
| If you sign | preview `summary`, `effects` (after B1 these include `cmd` and `service`), `would_execute`; the kind→words map | "Would run: `<cmd>`"; "Would queue for the worker". Without a preview: "Runs <kind in words>". **R4 note** for terminal, checkpoint, browser and provider kinds outside auto: "Your approval is recorded, but this kind runs only in Auto mode (now Ask)." |
| To undo | `rollback.description`, `.limitations` | otherwise "Not reported by the hub" (no "undo after" claim) |
| If you wait | `approval_deadline_at` | "Expires unanswered at <time>"; otherwise "Nothing runs. It stays here until you decide." |
| Taint | `payload.injection_flags`, `payload.untrusted_source` | "Raised from untrusted content" (the HUD inbox lacks this today) |
| Opinion | `judge` | "Model opinion · advisory only · you decide · 72/100 · <provider>/<model> · local/remote" |
| Members | hub group or collapse | ids and targets (mono), one line each |

**Friction and verbs** (all through `ConfirmAction`, `plain` styling, `enterConfirms={false}`)

| Tier | Sign |
|---|---|
| 0 Read only | one click "Sign" |
| 1 Reversible | two steps: "Sign" → "Sign: <title>" shows what it does, then confirm; "Cancel" |
| 2 External / 3 Irreversible or money | **SignLine**: the page's one bordered sheet, "Sign here — type <phrase>"; the input's placeholder is the phrase; the button is an outline until the phrase matches exactly, then fills with the accent. Enter does nothing. |
| unknown | treated as tier 3 (`confirmStyle`) |

- **Phrase** (`phrases.ts`, a fixed map): `restart_service` → "restart"; any delete → "delete"; money → the amount in digits; send, post or message kinds → "send"; deploy → "deploy"; book → "book"; anything else → "sign".
- **The other verbs:**
  - **Preview** (read only).
  - **Edit, then sign** (`PayloadEditor`: JSON validated; the same tier friction; `action:'edit'` with the payload; the server re-checks it). Not offered for special kinds.
  - **Defer** (one click). Copy: "Leaves the docket; it does not expire and can still hold dependent work. Listed in Work › Autonomy control."
  - **Reject** (one click; an optional reason up to 280 characters in an "Add a reason" disclosure placed *before* the verbs in focus order).
  - **Reject group** (hub group: `rejectGroup` with snapshot and member ids; two steps).
  - **Reject all N identical** (collapse: N sequential rejects; two steps; reports "Rejected 12 of 14; 2 refused: <reason>").
- **Groups are signed one request at a time:** "Applies to this request; 13 identical requests stay waiting". There is no sign-all (owner question 1).
- **"No keyboard shortcut signs or rejects"** is printed beside the verbs.

**States**

| State | What the docket shows |
|---|---|
| loading | "Checking…" |
| live | entries as above |
| empty | "Nothing is waiting for you." over a double rule reading "0 entries"; no figure |
| **refused** (401/403) | "Unknown — sign in as the owner to see what is waiting". On a networked origin a "Sign in" button calls `requireSignIn()`; on loopback, "This browser has no owner credential — set it in Trust › Trust operations". No "0", no "nothing waits". |
| offline | "Unknown — the decisions feed did not answer · last good 10:44"; previous entries stay in the stale style with signing disabled ("Refresh before signing") |
| demo | the `docket/demo.ts` corpus (the mockup's six entries), "Demo sample", all signing disabled |

**After a decision:** the feed is re-read; no optimistic removal. Refusals show the backend's own words via `refusalReason()` — expired, changed, owner-once and so on (gap-3 R12). The hash `#docket-entry-<id>` on `/v2/cockpit` opens and scrolls to that entry.

### 5.5 Fourth register at ≥ 2200px (E6, using E3)

**Agents by exception** (`agents-exception.ts`). Each agent gets one state from a named source:

| State | Proved by |
|---|---|
| Waiting on you | holds docket entries (agent field) |
| Working | a `running` task (`/autonomy/tasks?status=running`, admin) or a sub-agent (`/api/subagents`, with "stalled" shown as a stale variant); or "Answering you (asked)" from this tab's in-flight turn |
| Finished today | `/api/dashboard/today` actions by that agent |
| Unavailable | cloud-only `athena` when no cloud model is configured |
| Halted | the kill switch |
| Scheduled | `/heartbeat/status` `next_run` → "next check 18:00" (shown in the Agents page and the Timeline, not as a state on Home) |
| No activity reported | everyone else, as one line of names |

Turns running elsewhere are counted without a name ("1 reply running elsewhere", from `/status.slots`). The word "idle" is never used.

**The record:** the newest 5 entries of `GET /api/security/audit/intent` (time, action, why, hash prefix, sealed mark). Only fields that exist are shown: no agent or tier unless the endpoint returns them (E6 maps fields from the route handler). Footer: "Chain intact · Open the record" → `/v2/trust`.

### 5.6 Polling budget

| Feed | Cadence |
|---|---|
| Loader | 30s (unchanged) |
| Docket | 30s |
| Approval mode, interrupts, observer | 60s |
| Audit verify | 5 min |
| Kill switch | 30s |
| Dashboard/today | 60s |
| Heartbeat | 5 min |
| Slots, sub-agents, running tasks | 30s, and only while a page that shows them is mounted |

Everything pauses while the document is hidden; identical paths share one request.

---

## 6. Other pages (E6 unless noted)

- **Work overview `/v2/work`.** Gap-2 §9C, composed in the browser; each section has its own source label and refused-vs-empty handling.
  - *Needs you:* docket summary plus the top 3 entries, payments waiting, skill changes pending, an open mid-turn question in this tab.
  - *Running now:* turn slots (`/status.slots` counts; `/api/status/slots` holders show surface and age, no agent), running tasks, sub-agents.
  - *Scheduled:* heartbeats with their next run (unguarded), jobs (`/api/jobs`, admin).
  - *Done today:* `/api/dashboard/today` actions.
  - Missions and sessions are links, not merged in (gap-2 §9F). There is no cross-source ordering until the backend aggregate exists (B3).
- **Timeline `/v2/timeline`** (the Console direction's lanes).
  - Hours from the start of the day to now; one lane per agent with something today.
  - Done marks from `/api/dashboard/today` (agent, time, title).
  - Holds: from `max(created_at, start of day)` to now, with a "since 2 Jul" stub when older, and a numbered pin linking to the docket entry.
  - Running bars from running tasks and sub-agents; this tab's turn as "asked <Agent>".
  - Next heartbeats as ticks.
  - Problems on a separate **System** lane, because observer probes name no agent (gap-2 defect D17).
  - Cloud-only Athena as a dashed lane.
  - Folded row: "11 with no activity reported today: names". A "Now" column with the agents-by-exception states.
  - No magnifying lens (cut).
- **Trust overview `/v2/trust`** (secondary.html).
  - *The record:* the verify verdict with "Verify again" (read only), the entries table (`RecordTable` over `/api/security/audit/intent`), and payments (`/api/payments`).
  - *Your authority:* the stop sheet (`useKillSwitch`; Resume is typed DISENGAGE). Capabilities show live data only; the seed `V2.CAPABILITIES` list appears only in demo, labelled. Where work ran: the count, the basis ladder Unknown / Derived / **By route** / Verified (dashed, "not available yet"), "Local only, enforced by code: Frigga · Ultron · Howard · Hestia", "Cloud only: Athena".
  - **Payment friction:** approve becomes tier 3 typed (the amount), reject one click, settle two-step. Today it is a one-click ✓ (`TrustMode.payAct`).
  - **Kill switch:** the one-click disengage in `TrustMode` becomes typed, the same as `KillSwitchPanel`.
- **Glance `/v2/glance`** (glance.html), read only.
  - Clock and date, plus weather.
  - Four cells:
    - Need you: docket figure plus the friction mix plus "Signing happens on the page, never from here".
    - Health: the verdict state word, the headline and the checked time.
    - Where work ran: **"115 of 121 runs · sent to local runners · by route · all time"** — a count, never a large %, per gap-5 §7.4.
    - Next: the next calendar event.
  - This tab's working-reply line; the running head as marks; Stop all agents.
  - Large figures in `--n-text-2`; the whole sheet steps a few px every 10 minutes (instantly; off with reduced motion). Esc returns to the page.
  - Replaces Ambient on `a` and in the masthead.
- **Saved replies `/v2/artifacts`:** `ArtifactsPanel`. "Discuss in chat" stages the project and goes to `/v2/cockpit`. With no composer mounted, `onInspectBlend` returns false and the panel shows its own message.
- **Every other mode** (`AgentsMode`, `MemoryMode`, `AutonomyMode`, `BuildMode`, `ObserveMode`, `InteropMode`, `CommsMode`, `AdminMode`, Finance/Health/Knowledge/Family, `ProjectsMode`, `JobsWorkspace`, `WorldIntelligenceMode`):
  - Inside `ModePage`, each mode's outer wrappers are replaced by `PageSection` (a register head and a body using the panel roles). Inner content and copy are kept.
  - `AgentsMode` card clicks open the Dossier only; the Dossier gains "Write to <Agent>".
  - Optional: fix the Autonomy live gate (`api/live.ts`, gap-2 defect D1).
  - Console panels keep their `Card` (styled by Phase A) inside `PanelPage`. A duplicated title (page head plus card title) is accepted in Phase B.

---

## 7. Backend items: in Phase B or deferred

| # | Item (source) | Phase B | What the UI shows meanwhile / why |
|---|---|---|---|
| B1 | Dry-run reports `cmd` and `service` (gap-3 §5, §7.5) | **Include** (`dry_run.py`, one tuple plus a test) | Enables "Would run: `<cmd>`"; without it the entry says "Runs <kind in words>". |
| B2 | Observer `since` for each unhealthy key (gap-2 §8) | **Include** (`observer.py` plus a test; additive JSON, no OpenAPI change) | Without it the verdict shows "checked" only. |
| B3 | `GET /api/work` aggregate (gap-2 §9A) | Defer | Work overview builds per-source lists with per-source states; no merged ordering. |
| B4 | Per-agent activity stamps: routed agent and turn kind on turn slots, heartbeat in-flight mark and real result, a derived `activity` field (gap-2 §5.4) | Defer | "Working" only from named sources; other turns counted without a name; "last check not recorded". |
| B5 | `groups` on `/autonomy/approvals`; one server definition of "needs you" including proposed and deferred (gap-2 §2.2, gap-3 §7.5) | Defer | The docket uses the inbox feed (blocked plus groups); the deferred-items copy points to Autonomy control. |
| B6 | Record the deciding surface; expose decision time without a reason (gap-3) | Defer | Not needed by the UI. |
| B7 | One reversibility verdict (feed and preview disagree on 15 live cards) | Defer | The entry shows only the tier verdict; the preview's own reversible flag is not repeated. |
| B8 | Locality evidence class in the reply receipt; per-model execution in the catalog (gap-5 §8.1–3) | Defer | First-hop wording ("Sent to Ollama on this computer · not verified"); a cloud-name warning based on the model id. |
| B9 | Trust status reasons; unguarded counts from the egress ledger (gap-5 §8.5) | Defer | "No cloud model configured" (declared); measured counts only when admin can read them. |
| B10 | `/tasks?view=running` only looks at the newest 30 rows (gap-2 defect D2) | Defer | Use `/autonomy/tasks?status=running` (admin, filtered in SQL); when refused, "Running work: unknown without the owner credential". |
| B11 | Calendar connected vs empty (gap-2 defect D10) | Defer | The combined sentence in §5.2. |

**Owner action before any design review:** clear the 35 fixture cards (gap-3 §7.2). The docket's two-step "Reject all N identical" makes that possible from Home.

---

## 8. Test migration

### 8.1 Rules
- Legacy components stay exported until cleanup, so tests that render them directly keep passing: `TopBar`, `Rail`, `ContextColumn`, `Palette`, `LangMenu`, `ConsoleOverlay`, `CognitionStream`, `Ambient`, `world_app` constants.
- Tests that render `App` or drive e2e against the old structure are rewritten at cutover.
- New markup gets new tests by its owner.

### 8.2 guards-and-rollout §1.2, rows 11–37

| Row | Pin | Action | New assertion or reason | Owner, when |
|---|---|---|---|---|
| 11 | Palette row labels (`palette-tweaks`, `appearance-sync`, `app-routing:249-251`, `language-menu:206-207`) | **Compat + rewrite** | Labels kept word for word in the sheet's appearance group. Openers rewritten to the Find button (role and name). `palette-tweaks` stays on `Palette` until cleanup, then moves to `CommandSheet`. | E1, cutover / cleanup |
| 12 | `.hud-root` `data-*`, look values, cache key | **Keep** | `.hud-root` and its attributes stay (CONTRACT §2). | Phase A |
| 13–15 | Appearance defaults, font ids, native appearance | **Keep** | Phase A's domain. | Phase A |
| 16 | WORLD button rail reservation (`hud-inline-fixes:208-224`) | **Delete** at cleanup | The fixed WORLD button and the rail no longer exist; World is a page. | E2 |
| 17 | `status-chrome` (`.brand .badges`, `data-chrome`, `.rail-gw-dot`), `rail-navigation` | **Keep until cleanup, then port** | Gateway, session and version semantics ("dashes, not zeros", unknown gateway) move to RunningFoot tests using the same `data-chrome` hooks; `aria-current` and `data-anchor` move to AreaNav tests. The badge-shedding tests are deleted with TopBar (no badges remain). | E2 |
| 18 | `test_hud_v2_parity.py` callers and named strings | **Keep** | The pinned strings in §1.5 are kept; backlog and machine-facing entries are removed when Phase B adds the first caller. | each owner |
| 19–21 | CSP, PWA, asset manifest, workspace fonts | **Keep** | No CSP, service worker or font-path change in Phase B. | — |
| 22 | Bundle drift | **Keep** | The integrator commits the rebuilt bundle. | E2 |
| 23 | Focus ring is 4px on the first focusable in `.workzone` (`reachability:118-122`) | **Rewrite** | The first focusable in `[data-frame="page"]`; still 4px (ask Phase A to keep the ring at 2px outline + 2px offset). | E2, cutover |
| 24 | `.inputbar` reachable at 5 widths (`reachability`) | **Rewrite** | `[data-composer-bar]` and `[data-composer-send]` inside the viewport at 1280/1100/1000/900/800. | E5 |
| 25 | No overflow; badges vs clock (`layout:33-84`) | **Rewrite** | No horizontal overflow at 2560/1920/1280/900/800; the eight running-head items do not overlap and are not clipped; masthead areas do not overlap the tools. | E2 |
| 26 | Vault passage → Send at 320/390px (`layout:87-150`) | **Rewrite selectors** | Open Attach → Vault notes; same assertions on `[data-composer-send]`. | E5 |
| 27 | Badges LLM/DATA/GATEWAY/EGRESS/MIC visible (`status-chrome-layout:54-110`) | **Rewrite** | All eight running-head items fully visible at 2560/1920/1536/1440/1366/1280; session count and version painted in the foot. | E2 |
| 28 | Rail gateway dot; last rail button reachable by wheel | **Rewrite / delete** | The nine areas are visible at 1366×768, 1280×800, 1024×768 (the drawer below 760). The wheel test is deleted (no rail). | E1 |
| 29 | Painted contrast on `.topbar .ticker .rail .center-tabs .inputbar`; 16 `.rail-btn`; 3 `.center-tab` (`contrast.spec`) | **Rewrite** | Parts: `[data-frame="masthead"]`, `"runhead"`, `"runfoot"`, `[data-register="docket"]`, `[data-composer-bar]`. The 9 area labels and the running-head labels must be *measured*. Run in Ledger dark, Ledger light and Obsidian. | E2 |
| 30 | Exactly 16 `.rail-btn`; hotkeys reach 16 labels (`a11y-modes`) | **Rewrite** | Walk every registry page (9 landings, 18 modes, 4 views, and all panels or a sample within the time budget) via AreaNav and ContentsColumn; axe each page; hotkeys 1–9 and 0 reach the 9 areas and the conversation. | E1 |
| 31 | `/v2` shows a lit `.nmesh canvas` (`hud.spec:25-56`, `a11y:36-37`) | **Rewrite** | The mesh check moves into Cinema (`m`); `/v2` asserts the three Home registers and no uncaught error. | E2 |
| 32 | `m` opens `.cinema`; `.inputbar input/.transmit`; `.msg.user/.agent .bubble`; push-to-talk button | **Keep + rewrite** | Cinema is unchanged. Selectors become `[data-composer]`, `[data-composer-send]`, `[data-turn="owner"] [data-turn-body]`, `[data-turn="reply"] …`. The Voice control keeps its title values ("push-to-talk" / "hands-free voice"). | E5 |
| 33 | Service worker cache name | **Keep** | — | — |
| 34 | Computed fonts per option | **Keep** | Phase A. | Phase A |
| 35 | Appearance values after palette clicks (`appearance.spec`) | **Rewrite opener** | Open the sheet from the Find button; values unchanged. | E1 |
| 36 | `gap-*` chunk, a woff2, `index-*.js` load (`base-path.spec`) | **Keep + adjust** | If Home no longer pulls the `gap` chunk, visit `/v2/console/logs` before asserting; titles become the new form. | E1 |
| 37 | `.workzone.cockpit .scrollcol` > 300px; input ≥ 100px (`routing.spec`) | **Rewrite** | At 1280/1440/1680/1920: the docket is ≥ 480px wide and inside the viewport; every entry's sign control is reachable; the textarea is ≥ 320px; the five visible controls sit inside the composer. | E4 + E5 |

### 8.3 Other pins named in the brief

| Test | Action | Owner |
|---|---|---|
| `hud-inline-fixes.test.tsx` — Dismiss-only decision card | **Keep.** `decisionCard()` stays as the read-only projection used by the wall and Ambient. **Add** `docket/Docket.test.tsx`: real verbs, never "Dismiss". | E4 |
| `approval-mode-card.test.tsx`, `markdown-adoption.test.tsx` (ContextColumn `.dcard`) | Keep until cleanup. Then the mode-note assertions move to DocketEntry; the markdown-in-card assertion is **deleted** because queue titles are untrusted plain text (gap-3 §5). | E4 |
| `app-session-recovery`, `chat-routing-app`, `turn-outcome-app` (`.inputbar .transmit`, `.msg`) | **Rewrite** to `data-composer-send` and `data-turn`. | E5 |
| `composer-vision-turn`, `selected-vision-app` (`/TRANSMIT/`) | **Rewrite** to `V2.I18N.en.transmit` (= "Send"). | E5 |
| `godot-download`, `h595-chat-followup`, `markdown-adoption` (`.msg`, `.bubble`) | **Rewrite** to `data-turn` hooks. | E5 |
| `convo-keyboard-access` (`.convo`) | **Rewrite** to `getByRole('log')`. | E5 |
| Composer tests (`chat-history-inputbar`, `composer-*`, `direct-reply`, `disabled-controls`, `blender-export`, `compare-agents`) | Accessible names kept; add one "open Options/Attach" step where a control moved behind a menu. | E5 |
| `language-menu.test.tsx` (App + globe menu) | App-level tests **rewritten** to the EN/RO radiogroup (same behaviours: persistence, `lang`/`dir`, `jarvis:locale_changed`). The direct `TopBar` test stays until cleanup. | E2 |
| `app-routing.test.tsx` | **Rewrite**: masthead and contents navigation, the sheet, the new hotkeys, panel pages, the World page with Back/Forward, Glance Esc return. The H209 rebinding cases keep using `w`. | E1 + E2 |
| `hud-routing.test.tsx`, `base-path.test.ts` | **Rewrite** titles; the overlay return-chain case becomes Glance; route validity unchanged. | E1 |
| `console-routing.test.tsx` | Keep until cleanup; then port to AllPages and PanelPage (a link for every panel without mounting it; focus on the selected panel; History navigation). | E1 |
| `shortcuts.test.tsx` — default table | **Rewrite** to the §3.6 table; the forbidden-target tests are unchanged. | E1 |
| `app-demo-exit.test.tsx` | **Rewrite**: mock the new home, docket and signals modules; same "demo evidence is cleared" claims. | E2 |
| `decision-inbox-panel.test.tsx` | **Rewrite** accept clicks to tiered confirmation (type the phrase for tiers 2–3; two clicks for tier 1). | E4 |
| `trust-analytics.test.tsx` (TrustMode kill switch) | **Rewrite** to `useKillSwitch` (one-click stop, typed resume). | E6 |
| `cinema`, `briefing-wall`, `mesh`, `voice-orb` (`.nmesh`) | **Keep** (Cinema unchanged). | — |
| `confirm.test.tsx`, `pointer.test.tsx`, `desktop-route-sync.test.ts`, `mode-surface-a11y.test.tsx` | **Keep**, and add tests for the new props, fallback anchors and wrappers. | E4, E1, E1, E6 |

---

## 9. Work split

### 9.1 Engineers and file ownership (disjoint)

| Engineer | Owns | Size |
|---|---|---|
| **E1 Navigation and search** | `nav/*`, `hud-modes.ts`, `hud-routing.ts`, `shortcuts.ts`, `pointer.tsx`, `desktop/src-tauri/hud-routes.json`; e2e `a11y-modes`, `routing`, `base-path`, `appearance`; tests `app-routing`, `hud-routing`, `shortcuts`, `console-routing`, `base-path` | M |
| **E2 Frame and integration (lead)** | `frame/*`, `home/Home.tsx`, `home/ChatPage.tsx`, `home/home.css`, `app.tsx`, `world_app.tsx`, the `ConsolePanel` export in `gap.tsx`, the shots harness; e2e `hud`, `a11y`, `layout`, `contrast`, `status-chrome-layout`, `reachability:118-122`; `docs/design/HUD_V2_REMAINING.md` and `mobile/PARITY.md` at cutover; bundle commits; cutover and cleanup PRs | L |
| **E3 Signals and the day** | `signals/*`, `home/day/*`, `api/loaders.ts` (additive), `agents/core/autonomy/dry_run.py`, `agents/core/autonomy/observer.py` and their Python tests | M |
| **E4 Docket and decisions** | `docket/*`, `api/decisions.ts`, `confirm.tsx` (additive props), `DecisionInboxPanel` in `gap.tsx`; tests `decision-inbox-panel`, `approval-mode-card` (later) | L |
| **E5 Conversation and composer** | `home/talk/*`, `Conversation` and `InputBar` in `cockpit.tsx`, `turn-tools.tsx`, `ChatMode` (moved), `data.ts` I18N keys, `chat-history-search.tsx` (local-only list); composer, transcript and floating tests; e2e `composer-images`, `turn-latency`, `layout:87-150` | L |
| **E6 Pages and Glance** | `pages/*`, `modes.tsx`, `modes2.tsx`, `modes3.tsx` (all but ChatMode), `modes4.tsx`, `modes_world.tsx`, `api/live.ts` (D1, optional); tests `trust-analytics`, `mode-surface-a11y`, `seeded-corpora-honesty`, `interop-live-honesty` | L |

With five engineers: E3's pure signals and hooks go to E2 in Stage 1, and E3's day-register UI goes to E6.

### 9.2 Shared interfaces, settled first in one reviewed "interfaces" PR
1. **E1** — `nav/areas.ts` types (`AreaId`, `PageRef`, `PageEntry`, `Area`, `Group`), the full §3.3 table, the placement test, `pageForRoute`, `pathOf`, `pageTitle`; the 4 new `HUD_MODES` ids plus the regenerated `hud-routes.json`.
2. **E2** — `frame/kit`: the `Mark` kinds (ok, attn, problem, unknown, stale, held, blocked, work, done, idle, seal-open, seal, chain, here, key), `TierGlyph`, `SourceLabel` (from a `Reading`), `Register`, `SecHead`, `Total`, `Consequence`, `Disclosure`; `frame.css` with breakpoints and visibility helpers; the strings convention (each module exports `{en, ro}` tables and has a completeness test like `i18n-completeness.test.ts`); the class ownership list (§1.3); `frame/flag.ts`.
3. **E3** — `signals/types.ts` (`Reading`, `Basis`, `HubSnapshot`, `SignalView`, `Verdict`, `Cause`, `AgentState`, `MachineReading`, `AwayEntry`, `ReplyMarker`, `Attention`) and the `usePolled` signature.
4. **E4** — `docket/types.ts` (`DocketEntry`, `DocketModel`, `DocketSummary`, `Verb`), `docketHref(taskId)`, the anchor rule `docket-entry-<id>`, `useDocketSummary()` (used by AreaNav and Glance), `useDocketTitle(id)` (used by the slip).
5. **E5** — the `TalkRegister` props (today's `Conversation` plus `InputBar` props, `onSelectAgent`, `variant: 'home' | 'chat' | 'floating'`), the three message stamps, and the composer and turn hooks.
6. **E2** — the App→Frame contract: `Frame` props (route, page entry, hub, lang/setLang, scheme/setScheme, navigation, onFind, onGlance, children); how App builds `HubSnapshot` from the loader commit.
7. **E2** — the stamps in `runTurn` (`_askedAt`, `_startedAt`, `_firstTokenAt`), so E5 is not blocked.
8. **Requests to Phase A** (E2 files them):
   - Ledger's ≥2200px reading-size step-up in `themes/ledger.css`;
   - the `kit.css` primitives listed in §1.3, with a focus ring of 2px plus 2px offset;
   - the `appearance` panel id;
   - optional `--n-mark-*` roles so other themes can tint marks;
   - the Literata and Barlow subsets, or documented stand-ins.

### 9.3 Order
- **Stage 0.** Phase A merged. Owner clears the fixture cards (recommended before reviews).
- **Stage 1 — interfaces PR (§9.2).** Pure work can start the same day: E1 registry and tests; E3 derivations, poller and B1/B2; E4 model, phrases, decision client and confirm props.
- **Stage 2 — build in parallel behind `?frame=ledger&demo=1`.**
  - E2: Frame, masthead, running head and foot, AreaPage, PanelPage, the Home grid with placeholder registers.
  - E1: CommandSheet, ContentsColumn, AllPages, hotkeys, pointer.
  - E3: day register and band.
  - E4: docket UI and SignLine; then the inbox grading.
  - E5: composer re-lay first (it also works in the classic cockpit), then transcript, working reply, footnote, slip, floating.
  - E6: Trust overview, Glance, Work overview, Timeline, fourth register; then the mode wrappers.
- **Stage 3 — integration.** E2 wires each region as it lands, in this order: E1 → E4 → E5 → E3 → E6. The render matrix runs on every integration build.
- **Stage 4 — cutover PR.** Flip the default; each owner's migrations from §8; the full PR lane (`npm run typecheck`, `npm run typecheck:e2e`, `npm test`, `npm run build`, the Python pins listed in guards-and-rollout §7); the nightly lanes run locally with the fixture-backed configs.
- **Stage 5 — cleanup PR.** Delete the §2.4 components with their tests (or port them, per §8); delete the flag and the WORLD constants. Leave legacy CSS rules in `styles.css` (they keep `tests/test_design_manifest.py` green) until a later manifest update.

### 9.4 Acceptance per engineer

Every engineer, on every PR: typecheck clean; their own and touched tests green; no colour literal or sub-12px size in their new files; the strings completeness test passes; renders (§9.5) at **2560×1353 at 1.5×, 1920×1080, 1280×800** in **Ledger dark, Ledger light and Classic · Obsidian**, with all gates green. Atlas is spot-checked for card-style panels.

| Engineer | Unit tests to write | Renders (the 3 sizes × 3 themes) |
|---|---|---|
| E1 | `nav/areas.test.ts` (137 placed once, modes once, labels non-empty, ≤12 primary); `nav/routes.test.ts` (every legacy and new route resolves; titles); `nav/commands.test.ts` (every area, page and panel findable by label, id, alias and RO without diacritics; agents; no verdict command; `defineCommands` throws); `CommandSheet.test.tsx`; `ContentsColumn.test.tsx`; pointer fallback tests | Sheet open over Home; Trust and Settings sub-pages with contents; All pages at 1920 |
| E2 | `frame/kit.test.tsx` (every mark has its word; SourceLabel states); `Masthead.test.tsx` (order, `aria-current`, counts only when live, EN/RO radiogroup, scheme toggle disabled for Classic, Stop posts then re-reads, refusal alert); `RunningHead.test.tsx` (all eight items render; stricter mode one click, looser two-step, refused disabled); `RunningFoot.test.tsx`; `useKillSwitch.test.ts`; an App smoke test rendering every registry route under `frame=ledger` | Home (demo and live-empty), `/v2/build`, `/v2/console/logs`, the notices stack (safe mode + demo) |
| E3 | `verdict.test.ts` (each rule and its precedence); `trust-signals.test.ts` (never "Sealed — nothing can leave", never a bare %, never 0 for unknown); `agents-exception.test.ts` ("idle" never produced, cloud-only unavailable, halted); `machine.test.ts`; `away.test.ts`; `provenance.test.ts` (every gap-5 §7.1 row); `poll.test.ts` (dedupe, refused vs offline, stale, pause when hidden); day components per state; Python tests for B1 and B2 | Day register (2560/1920); DayBand at 1280 with a popover open; the verdict in ok, degraded, problem, offline and unknown |
| E4 | `docket/model.test.ts` (ordering, hub groups, identical collapse, phrases, special kinds open in Decisions, optional rows only when present, titles plain); `decisions.test.ts` (exact POST bodies for accept, reject, defer, edit, group reject; reason; refusal text; no POST in demo; a source-scan test that only `api/decisions.ts` posts to `/autonomy/tasks/`); `Docket.test.tsx` (every state; tier 0/1/2/3 friction; Enter in SignLine does nothing; document-level keydown of Enter, Space, a, r, d never posts; Reject all N two-step and partial results; refresh before signing when stale); `confirm.test.tsx` additions | Docket at 1920 (open tier-3 SignLine, before and after the phrase); 1280 (one-line entries, open entry signable, no page scroll); 2560; empty, refused, stale and demo |
| E5 | `Composer.test.tsx` (exactly To, Mode, textarea, Attach, Voice, Options, Send visible; Enter, Shift+Enter, IME; disabled reason; local-only list includes hestia); `WorkingReply.test.tsx` (steps from stamps, tools, writing; elapsed; stop label); `ReplyFootnote.test.tsx`; `ApprovalSlip.test.tsx`; transcript accessibility; floating variant | Conversation at 3 sizes; working reply mid-stream (demo); Attach and Options menus open; floating 420×620 |
| E6 | `TrustOverview.test.tsx` (verify states; typed resume; typed payment approve; no seed capabilities outside demo; basis ladder); `WorkOverview.test.tsx` (refused never "0"; source labels); `Timeline.test.tsx` (lanes only from real events; System lane; holds with stubs); `Glance.test.tsx` (no sign or stop-resume controls; count not %; Esc returns); wrapper regressions | Trust overview (secondary.html parity); Work overview; Timeline; Glance 1920/2560 dark and light; Agents and Memory pages |

### 9.5 Render harness (E2, Stage 1)
- **Files:** `frontend/e2e/ledger-shots.spec.ts` with `frontend/playwright.ledger-shots.config.ts` (manual lane).
- **Server:** the fixture hub `e2e/support/base_path_server.py`. It isolates `JARVIS_HOME`, returns fixture answers to writes, touches no owner data, and serves the built bundle. Alternatively Vite on 5173 with `?demo=1`.
- **Theme selection:** seeded before load through Phase A's cache format (`hud.appearance.v1:/`, `version: 2`, `look`, `scheme`), or Phase A's development parameter if one exists. `frame=ledger` is set the same way.
- **Matrix:** pages × 3 sizes (2560×1353 with `deviceScaleFactor: 1.5`) × 3 themes, plus `?demo=1` vs live-empty.
- **Output:** `frontend/e2e/artifacts/ledger/<page>-<w>-<look>-<scheme>.png` (gitignored) and `report.json`.
- **Gates:**
  - no horizontal overflow;
  - no page-level vertical overflow on Home and Glance at 1920, 2560 and 1280×800;
  - smallest rendered font ≥ 12px in Nerva themes (reported only for Obsidian);
  - axe colour-contrast failures = 0 in all three themes;
  - zero console errors and zero external requests;
  - at 1280×800, the open entry's SignLine is fully visible and every other entry's sign control becomes hit-testable after scrolling inside the docket.
- Curated sets are copied to `docs/design/hud-next/ledger/build/` at each milestone for the owner.

---

## 10. Risks

1. **`app.tsx` turn handling regresses.** `runTurn` and session recovery are dense and heavily tested. Mitigation: E2 is the only editor; changes are additive stamps; the full App test set runs on every integration.
2. **Decision correctness.** Wrong task, stale view, group semantics, phrase mismatch, keyboard bypass. Mitigation: one decision client; exact-body tests; refresh before signing when stale; no sign-all; the "no keyboard verdict" tests; the fixture hub e2e; the inbox gets the same grading.
3. **Conflicts with Phase A.** Phase A touches 107 files. Mitigation: Stage 0 gate, the ownership table, no edits to `styles.css` or `theme/*`, and the requests list.
4. **The volume of test migration.** Mitigation: the flag lets legacy tests pass throughout; the per-owner lists in §8; cutover is a single PR.
5. **New honesty slips** (new readings that invent values). Mitigation: E3's pure derivations, each with unknown, stale, refused and demo tests; the copy rules in §4.2.
6. **More polling.** Mitigation: shared requests, pausing when hidden, polling only on pages that need it; the root 1-second clock goes away.
7. **Layout at the extremes** (2560 four registers; 1280×800 signability; 36 entries). Mitigation: CSS grid copied from ledger.css; the harness geometry gates.
8. **Fonts and render drift.** Literata and Barlow ship self-hosted since 2026-11-23 (`src/theme/fonts.css`); Barlow Semi Condensed and Source Sans 3 do not, and their stand-ins differ by OS. Mitigation: final review renders on the owner's Windows machine at 2560 and 1.5×.
9. **Rulings that are open with the owner** (§12). Mitigation: conservative defaults that the backend can always enforce.

## 11. What to cut first (no route or test is left broken)

1. The Timeline: do not add `timeline` to `HUD_MODES`; the Work overview keeps "Running now" and "Scheduled".
2. The fourth register at 2560: three wider registers; agents and machine stay in the foot.
3. The per-reply action budget: keep the current reply buttons with Phase A's styling.
4. Glance: keep `Ambient` on `a` (Phase A styling); do not add the `glance` id.
5. The Work overview: do not add `work`; the masthead's Work link goes to `/v2/console/decision-inbox`, and `2` goes there too.
6. The Trust overview rewrite: `TrustMode` inside the frame. Its typed-resume and payment-friction fixes stay — they are small and safety-relevant.
7. Inner wrappers of the other modes: frame and title only.
8. Edit, then sign in the docket: "Edit in Decisions" (the inbox's JSON editor).

**Never cut:** the nine-area masthead with Ctrl K over every panel and Stop; all eight running-head items at every width; the real docket with tiered friction and its refused, empty and stale states; the computed verdict; the multi-line composer with the fixed control set; route compatibility; the test migration.

## 12. Owner questions (Phase B proceeds on the default)

1. Sign one group with N members in a single typed signature? **Default: no.** One request at a time; reject-all allowed in two steps.
2. Tier 1: Ledger's "one click, undo after" vs `confirm.tsx`'s two steps? **Default: two steps.** The hub has no undo for decisions.
3. Loosening the approval mode from the running head requires two steps. **Default: yes.**
4. Locality wording follows gap-5 ("Sent to local runners · 115 of 121 · by route"), not "Runs on this machine 100%". **Default: gap-5.**
5. Home's URL stays `/v2/cockpit` (no `/v2/home` alias). **Default: keep.**
6. Payments and skill proposals signable from the docket. **Default: Phase C.**
7. Hotkeys remapped to masthead order. **Default: yes.**
8. Clear the 35 fixture cards before reviews.
9. A native-speaker review of the Romanian copy.
10. The live visible-output estimate (H686) and the recall line (H430) are shown in "Turn details" after the reply, with the other old `StatusStrip` lines (§5.3), not inside the reply while it is written. **Owner, 2026-11-24: keep the spec.**
11. A change of recipient asked for while a reply is being written, and still unanswered when that reply ends. **Default: the question stays, without its "stops the reply" clause, until the owner answers it.** Nothing switches by itself, so the finished reply keeps its Turn details on screen.
12. A hands-free voice turn made while a recipient question is open. **Default: while the reply that opened the question is still being written, `runTurn` refuses a hands-free turn (as it refuses every hands-free turn while any reply is in flight): nothing is sent, and the refused turn is not kept for later. Only after that reply has ended can a hands-free turn be sent, and then it goes to the current recipient, whom the head names, and the question stays open.** Only Send and Enter are held by the question; the owner who speaks after the reply has ended is writing to the recipient the head shows, so the voice turn is not taken as the answer, and it neither switches the recipient nor drops the question (a turn that is sent ends only the line saying that an earlier change of recipient was dropped, as every sent turn does). After that reply has ended a hands-free turn is still refused, and nothing sent, while another reply or an image turn is being written, or while there is no recipient `runTurn` can send to.

---

### Critical Files for Implementation
- `C:\dev\jarvis-hub\.claude\worktrees\hud-redesign\frontend\src\app.tsx`
- `C:\dev\jarvis-hub\.claude\worktrees\hud-redesign\frontend\src\cockpit.tsx`
- `C:\dev\jarvis-hub\.claude\worktrees\hud-redesign\frontend\src\gap.tsx`
- `C:\dev\jarvis-hub\.claude\worktrees\hud-redesign\frontend\src\hud-routing.ts`
- `C:\dev\jarvis-hub\.claude\worktrees\hud-redesign\frontend\src\confirm.tsx`
