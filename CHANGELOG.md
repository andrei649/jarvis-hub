# Changelog

## [Unreleased]

### Wave 2026-09-06 — 17 builder slices: operator hands, live rails, activation, program contracts

Seventeen file-partitioned slices landed as one commit (`214bc5eb`, run `opus-integration`,
PR #1039), each with its own hermetic tests and its own red-proof, then registered by three
integrators working on disjoint files. **Nothing here changes default behaviour**: every new
capability is default-off behind its own flag ([`docs/FLAGS.md`](docs/FLAGS.md)), and every
privileged effect still crosses the Action Kernel and the approval queue.

- **A governed computer operator grew hands.** A consent ledger
  (`agents/core/permission_ledger.py`, `JARVIS_PERMISSION_LEDGER`) holds per-app / per-site /
  OS-input / file-root / terminal-target grants `{once, session, always, never}` over a curated
  default-deny list, widened only through the new `permission.grant` approval task. Governed **file
  tools** (`JARVIS_FILE_TOOLS`) read and list inside declared roots and write/delete only as
  approved ask-tier ToolRPC tasks that snapshot the previous bytes first (kernel kind `file.write`,
  rollback `restore`). A governed **local terminal** (`JARVIS_TERMINAL_LOCAL_HOST`) runs argv-only,
  cwd-jailed commands behind a static HARDLINE denylist evaluated *before* authorize on every
  backend — a hardline hit leaves no audit entry and never spawns — then target policy, a durable
  approved task, the new `terminal.exec` contract, and a kernel GRANT. The **browser** got the
  IP-pinned Chromium transport it needed to navigate at all (SEC-B4's browser leg): one validated IP
  per host, `MAP * ~NOTFOUND` for everything else, redirect and subresource re-validation, a
  throw-away profile per run, and accessibility-snapshot-first observation. **Visual grounding**
  falls back to a proven-local VLM with pinned open-weight presets so a model's coordinate
  convention is normalized before a click (`JARVIS_VLM_PRESET`).
- **The live rails exist, and stay off.** `JARVIS_WRITEBACK_LIVE`, `JARVIS_SOCIAL_LIVE` and
  `JARVIS_CALL_LIVE` arm the real Notion/GitHub/Calendar/Linear/Asana/Trello/Todoist/ClickUp/Sheets/M365
  write, the X post, and the Twilio/Telnyx dial — each only after an approved ask-tier task, each
  refusing `credential_not_configured` rather than sending an unauthenticated request. Approved
  transcript `create_task` items now execute through `WriteBackBroker` instead of the LLM fallback.
- **Activation is one step again.** `scripts/bootstrap.py` (stdlib-only, hash-pinned install, a
  real install smoke, loopback-bound) sits behind thin `install.sh` / `INSTALL.bat` /
  `install.ps1` wrappers and a `docker-compose.quickstart.yml`; `scripts/doctor.py` answers "why
  isn't it working" with named reasons and an exit code. New docs: [`docs/INSTALL.md`](docs/INSTALL.md)
  and [`docs/PHONE_ACCESS.md`](docs/PHONE_ACCESS.md) — the latter closes a long-standing gap where
  the supported LAN path for a phone was documented nowhere. Model setup now tiers on real hardware
  (NVIDIA → Apple Silicon → AMD) and can pull a recommended model through the kernel
  (`model.pull`, `JARVIS_MODEL_PULL`, loopback-only, size-capped).
- **Memory hygiene closed its sixth leg.** `GET /api/memory/consolidate/preview` finally answers
  where `existing` comes from, `POST /api/memory/consolidate/apply` is the apply surface, and every
  JSON recall hit is now injection-scanned, redacted when flagged, and carries provenance and a
  `tainted` verdict. The HTTP recall routes bind turn origin on entry and reset **after the response
  is built** — not the fail-open shape an earlier draft withdrew.
- **MCP speaks Streamable HTTP** behind `JARVIS_MCP_HTTP_CLIENT` (the deprecated HTTP+SSE pair
  stays refused *by name*, closing DRA-25's honesty finding), a reusable stdio loop plus
  `scripts/nerva_mcp_stdio.py` bridges Claude Desktop / Cursor to a running hub without widening a
  single gate, and `JARVIS_MCP_STDIO_ENV_BASELINE` stops stdio servers inheriting the hub's
  credentials.
- **House:** Hestia is wired onto the house modules (`observe()` / `propose()`, aggregate occupancy
  only, proposals through the approval queue) and a strict-local WLED bridge mirrors the six orb
  states — every write a kernel-mediated `house.control`, echo-verified, silent when unreachable.
- **Chaos and program contracts:** an in-process failure-injection harness for the test lane
  (`JARVIS_FAULT_INJECT`, refused under `JARVIS_HARDENED`, fenced to the data root),
  `nerva.ledger.v1` cognitive-ledger records (record_only), the #731 Continuity Core evaluation
  suite on the accepted E9.0 benchmark harness, an advisory-only Nerva program-manifest checker
  reconciled to the post-#981 posture, and the first Tier A integration adoption pass (Playwright —
  pass recorded, nothing adopted).
- **New surfaces:** `GET /api/report/today` (a redacted, payload-free day report, `?format=html`),
  `POST /api/report/today/export` (kernel kind `report.export`), `GET /api/report/receipt/{audit_id}`
  (a chain-verified Proof-of-Action receipt), `GET /api/permissions` +
  `POST /api/permissions/{id}/revoke`, `GET /api/onboarding/model-plan` +
  `POST /api/onboarding/model-pull`, `GET /api/memory/consolidate/preview` +
  `POST /api/memory/consolidate/apply`, and `POST /api/subagents/{id}/steer|stop` — with Console
  panels for the day receipt, permissions, model setup and consolidation.
- **Honest limits, recorded rather than glossed:** the browser transport, the local terminal, the
  visual-grounding presets, the model pull, all three live rails, the native installers and the
  stdio bridge are **delivered, not proven on real hardware/credentials** — they are marked 🔨 in
  [`BACKLOG.md`](BACKLOG.md) and each has an owner packet with exact commands in
  [`docs/OWNER_TASKS.md`](docs/OWNER_TASKS.md). SEC-B5 stays 🟡 on one named residual
  (`Orchestrator.process()` binds no turn origin — an approval-volume owner decision). T-0.63's
  72h soak half remains an owner lane; the harness does not replace it.

### Wave 2026-09-06 (part 2) — the operator is wired, and the company loop exists

The seventeen slices above were isolated modules. This part registers them in the running
system and adds the work-run chain the "24/7 company" goal needs. Still nothing changes by
default: every new capability is off behind its own flag.

- **The action plane went from 21 to 26 kinds.** `permission.grant`, `terminal.exec`,
  `file.write`, `model.pull` and `report.export` are registered kernel-mediated, each with a
  capability manifest carrying its real rollback contract, and each with a live exerciser in the
  action-auth matrix — so "kernel-mediated" is proved against the production entry point rather
  than asserted in a snapshot. The permission ledger's kernel hook now honours
  `JARVIS_ACTION_KERNEL` like every other hook; it was the one consulted with the flag off.
- **The operator's routes are mounted and its executors wired.** The four new routers are on the
  app (all twelve routes user-guarded); `toolrpc.file_write` / `toolrpc.file_delete` joined the
  trusted-execution kinds; `terminal_run` now crosses the kernel with a durable approval check
  whose task id reaches it through a contextvar set by the executor — deliberately *not* through
  the model-facing schema, so a model cannot forge an approval. The consent ledger is an
  orchestrator binding and `permission.grant` executes only from the owner-approved task.
- **Company mode (E5.0), default-off behind `JARVIS_COMPANY_MODE`.** A work run is one
  owner-approved goal worked across turns, sessions and reboots. Four components, each able to do
  exactly one thing: a durable **ledger** (`work_runs.py` — strict transitions, hard budgets for
  steps/seconds/deadline/owner-interrupts, one open run per goal, a fingerprint per row, and a
  refusal to open on a goal nobody approved); an evidence **verifier** (`work_verifier.py` — a
  check with no probe is `unverifiable`, never `passed`; a broken probe is a failure, not a skip);
  a goal **judge** (`work_judge.py` — fail-closed, scope a hard boundary, and an optional LLM
  rubric that can only ever *withhold* a pass); and the **supervisor** (`company_supervisor.py` —
  one tick one step, stop read before planning, a refusal recorded as a step that spends budget,
  and no way to mark a run succeeded itself). 80 hermetic tests.
  [`docs/nerva2/NIGHT_SHIFT_E5_0.md`](docs/nerva2/NIGHT_SHIFT_E5_0.md).
- **Two HUD surfaces instead of two punch-list rows.** A Host Readiness panel over the
  observe-only probe — tri-state permissions render as *unknown*, never as a guess, and each
  refusal shows the backend's own hint — and steer/stop controls on running sub-agent rows, where
  an undelivered steer reads as "recorded, not delivered" rather than as success.
- **Two honesty corrections.** `nerva.work-run.v1` had been moved to `candidate` naming four E5.0
  modules that did not exist; the claim, its manifest reference and its reconciliation row were
  withdrawn, the tests that pinned the word now read the registry, and the status was re-raised
  only once the modules shipped. Separately, the import dry-run guard compared a WAL database
  byte-for-byte, which a checkpoint breaks under load; it now compares rows, with a test proving a
  written row is still caught.
- **Company mode is reachable, and its planner is clamped.** The planner is the one place a
  model proposes rather than refuses, so scope is enforced at *proposal* time (a run never spends
  a step on work the judge would reject), a repeat of work already done is refused, and a
  proposer that crashes or answers junk proposes nothing — read as "out of ideas", not
  "finished". The morning brief makes the unflattering facts the hardest to drop: the headline is
  the verdict rather than the effort, an unauthorised step leads both its run and the whole brief,
  and "nothing ran" never renders like "company mode is off". Three user-guarded routes and a
  Console panel expose it — with **no way to start a run**, because a goal is approved in the
  decision inbox like everything else, and a start button here would be a second, weaker approval
  path. Stop is offered, since narrowing needs no approval.
- **And it keeps going on its own.** `schedule_runtime.py` decides when a run advances, and
  every rule in it is restraint rather than throughput: a terminal, stopping, blocked or
  budget-spent run is never woken (an unreadable budget fails closed as spent), concurrency is
  bounded so ten open goals are not ten simultaneous agents, and the night window is quiet hours
  for *attention* only — the work continues, the interruption waits for morning. A failed tick is
  reported but never retried there, because a second retry loop would multiply the supervisor's
  failure budget behind its back.
- **The operator grew the other two platforms.** `build_desktop_runtime` picked
  `WindowsDesktopDriver` unconditionally — which is why the desktop operator only ever worked on
  Windows. There is now a `desktop_drivers` package: a shared base holding the observe/act policy
  and every bound (a mutation re-snapshots and matches by *exact* name immediately before acting, so
  a stale handle cannot click something else; `requires_kernel` is inherited so an adapter cannot
  omit it), a macOS adapter over the AX API, a Linux adapter over AT-SPI, and per-platform capture.
  The factory chooses from the host probe's own verdict, so it can never disagree with the Host
  Readiness panel, and it never downgrades silently: an undrivable host gets a named refusal and the
  probe's hint, and the runtime binds an `UnavailableDriver` that refuses each step by name rather
  than a null driver answering "deferred". Two refusals are deliberate rather than incidental —
  Wayland input through `uinput`/`ydotool` is refused *by policy* (it works, and that is the problem:
  it bypasses the compositor's consent model), and Wayland capture refuses X11 grabbers outright
  because under Xwayland they return black frames rather than errors.
- **Company mode got its front door.** Everything else in the chain refuses; the goal contract is
  the one path that grants, so its job is to make an approval mean something specific. A draft must
  name its title, scope, budget, deadline, stop conditions and — crucially — *how anyone would know
  it was done*; an unlimited scope has to be declared rather than defaulted into by an empty field,
  and a goal with no success check is refused up front rather than at 4am when the verifier
  (correctly) will not pass it. Proposing crosses the kernel as the new `goal.approve` kind and
  lands in the decision inbox; the approved goal is minted only from a **human** accept or edit, and
  a payload fingerprint stops an edit between the card and the execution riding an approval that was
  given for a different goal.
- **The operator can now be measured, S1's way.** A twenty-task pack across desktop, browser,
  terminal, files and vision, with `scripts/operator_bench.py` to run it and two read routes to
  serve the result. Everything about it is shaped by how a benchmark usually lies: the report
  carries **two columns**, so a hermetic pass can never be read as a live one (the headline always
  says the word "hermetic", and each task names the live twin a person would run on their own
  machine); **governance outranks correctness**, so a task that reached the right answer through an
  ungoverned action fails, and one such action fails the whole pack at any rate; skipped tasks leave
  the denominator rather than flattering the score; and a stored rate carries the fingerprint of the
  questions it answered, so a changed pack reads as stale instead of being served as current. The
  pack ships a negative control — a task expected to fail — because a governance rule with no
  failing example is a rule nobody has tested.
- **Activation is measured, and measured honestly.** Time to first governed action is the adoption
  number S8 and GAP-0 both come down to, and it is the one most easily flattered — so the clock
  starts at *install* rather than first launch (someone who installed on Monday and opened it on
  Friday took five days, not ninety seconds), only an owner-**accepted** action counts (proposing
  quickly and being rejected has activated nobody, and a policy auto-approval is not the owner
  choosing to trust anything), the first recorded activation is immutable so a later faster action
  cannot improve it, and a never-activated install reports *how long it has been waiting* rather
  than a blank. It surfaces as `activation` on the north-star, where it is deliberately a property
  of the install rather than of the trailing window.
- **The operator can use a keyboard.** It could click a named button and set a field's text,
  which is not enough to do work: there is no saving a file, submitting a form or moving
  between fields without a key press, and no reading past the fold without scrolling. `key`,
  `scroll` and `focus` join the driver vocabulary on all three platforms (AX/CGEvent on macOS,
  AT-SPI on Linux; the Wayland refusals are unchanged, so a chord cannot become the one way to
  sidestep the consent check every other mutation passes). **`key` is the only mutation with no
  named element** — `Cmd+S` acts on whatever is frontmost, so the owner reading the card cannot
  see from the step what it will touch — and everything about its design follows from that: a
  finite **allowlist** in `desktop_drivers/keys.py`, **no keycode passthrough of any kind**, and
  chords that quit / close / hide / minimise / switch apps or open the system launcher refused
  **by policy with a reason**, because each makes every later step act on something the plan
  never observed ("unsupported" invites someone to add support; a reason can be argued with).
  `focus` is classified as a *mutation* although nothing visibly happens — it decides where the
  next keystroke lands, and gating it as a read would gate the wrong half of "focus this field,
  then type the password". Scrolling is bounded to 20 notches and an out-of-range amount is
  **refused, not clamped**: a step that asked for 500 meant something different from one that
  asked for 20. Two bugs found by the tests: the policy refusal table was keyed by its *human*
  spelling and looked up against the canonical one, so `ctrl+alt+delete` and `cmd+alt+escape`
  would have been pressed — exactly the synonym-shaped hole the canonicaliser exists to close,
  now normalised at import with a guard that fails there rather than at 3am; and the new seams
  first borrowed the host-probe's closed refusal vocabulary, which would have told the owner
  their *machine* could not scroll when the truth was that nobody had written the code. 74 pytest.
- **Company mode stopped being nine parts that never met.** A ledger, a planner, a supervisor,
  two graders, a reconciler and a scheduler all existed and were all tested, and no night of work
  could ever happen because nothing built them into a loop — the specific kind of dishonesty where
  the tests pass and the documentation is accurate. `agents/core/autonomy/company_runtime.py` is the
  wiring, registered by `SchedulerService.schedule_company_mode` as a `company-mode-sweep` job
  (`autonomy.company_tick_seconds`, floor 60s). **Off means nothing is constructed** — a supervisor
  that exists is one something can call. **Clearing the flag stops work at the very next tick;
  setting it needs a restart**: stopping should always be easy and starting always deliberate,
  because a capability that can begin a night of autonomous work must not start because a config
  file changed while nobody was looking. The planner is **the checklist the owner read on the
  approval card** — `GoalDraft.plan` is new, validated against the goal's own scope when the card is
  *built* rather than discovered mid-run, and inside the payload fingerprint so editing the plan
  invalidates the approval exactly as editing the budget would. A goal approved with **no** plan
  proposes **nothing** and goes straight to grading ("you approved a goal with no plan, so nothing
  happened" beats a model improvising from a one-line title), and a goal that cannot be read yields
  an **empty** plan, never an unrestricted one. A failing sweep is reported, never raised into the
  timer. One real bug fell out: `snapshot()` spread the scheduler's config last, so its `enabled`
  shadowed the runtime's own gate and a runtime with the flag cleared reported itself as enabled —
  two different facts sharing one key, now named apart. 26 pytest.
- **A browser click finally crosses the kernel.** `browser.step` is the 28th kernel kind.
  The browser agent always had two gates — an egress allowlist navigation cannot escape and
  an approval queue mutating steps must pass — but it was the one privileged surface that
  never reached `kernel.authorize`, and that gap had teeth: the **kill switch** is honoured
  by the kernel, so a halted install could still have clicked through an already-approved
  plan; **taint escalation** lives in the kernel, and a plan assembled from a page the agent
  just read is precisely the case that must be forced back to ASK, which the browser's own
  approval object cannot know; and the **policy floor** (money caps, daily ceilings) is
  applied by the kernel, while a browser is the easiest way to spend money without touching
  the payments kind. `agents/core/browser_kernel.py` binds it in the same shape as
  `desktop.step` — two surfaces meaning "one governed step on the owner's machine" should not
  be two shapes. Two orderings are deliberate: the kernel is asked **before** an approval card
  exists (a DENY must never reach the owner as a decision they cannot safely make — asking the
  queue first teaches them their approvals do not mean anything), and the kernel is asked
  about the **same payload the driver receives**, not a summary of it. Two bugs fell out:
  `NullBrowserDriver.__getattr__` answered *any* attribute with a coroutine, so a
  `requires_kernel` probe came back truthy and every offline driver would have demanded a
  binding it does not have (the flag is now stated explicitly and read with `is True`); and
  navigation's blanket "browser transport unavailable" now distinguishes **not configured**
  (the owner never enabled the pinned transport — a config fix) from `browser_playwright`'s
  *unavailable* (a configured one could not bind — a bug report), with an allowlisted
  navigation reaching the driver once a transport is bound. 35 pytest + a live kernel
  exerciser in the action-auth matrix.
- **The night shift can hear you say yes.** A company-mode run that needs something
  privileged queues a durable task and blocks — and until now that was where the story ended:
  the task got approved in the morning and the run stayed blocked forever, because nothing
  ever told it. `agents/core/autonomy/pending_requests.py` is the half that reads the answer.
  It deliberately keeps **no pending-request table**: the ledger already holds the fact — a
  queued step carrying its durable task id — and a second copy of one fact drifts into a run
  blocked on an ask nobody can find, or an ask reconciled twice. The rules are each against a
  specific way of faking an approval: **silence is never a yes** (an undecided task leaves the
  run blocked, and no amount of waiting changes that); the decision is **re-read from the task
  every time**, never cached; a **vanished task is not an approval** but a `lost` ask recorded
  as a failed step, so the repeat-failure rule can end a run whose asks keep evaporating; a
  rejection **is** an answer, so the run moves on to something else; reconciling is idempotent,
  because a decision that applies twice unblocks a run twice; and a stop outranks an answer.
  **Who decided is recorded and shown**: a run may legitimately be unblocked by a policy
  auto-approval, which is exactly why the brief has to be able to say "5 of 9 were auto-approved"
  rather than implying the owner reviewed nine things. A decision reconciles the waiting run
  **the moment it lands** (an `AutonomyWorker` hook, flag-gated and unable to fail the decision),
  and the scheduler reconciles before it lists runs so an overnight approval is eligible in that
  same pass. New read-only `GET /api/company/waiting` says what each run is waiting on and for
  how long — it never answers an ask, for the same reason there is no route that starts a run.
  58 pytest + 4 vitest.
- **Pairing became a tap.** Copying a code between two devices is where onboarding loses people, so
  the owner can now mint a single-use Telegram deeplink from the HUD and tap it on their phone. The
  convenience is only acceptable because the token behaves like a credential and is built that way:
  one use ever (a link that paired twice would pair whoever saw the screen next), a five-minute TTL
  so a screenshot in a chat log rots, wrong/spent/expired **indistinguishable** from outside because
  telling them apart tells a guesser which it was, a token minted for one channel unusable on
  another, at most twenty outstanding with the oldest dropped first, and a revoke button for "I
  pasted that in the wrong window". The `/start` message carrying it is **swallowed** — it never
  reaches the orchestrator, the transcript or a log line, including on the failure and exception
  paths, because until it is spent it is live. Minting is admin-guarded and returns the value
  exactly once; it is never readable back.
- `permissions.db` and `work_runs.db` join the purge and export sets.

## [1.0.0] — 2026-09-02

The 1.0 line: every feature horizon (H1–H23 + WorldView O19) delivered, the productionization
spine done, and the owner gates closed. Release-gate changes in this cut:

- **Relicensed MIT → Apache-2.0** (#1012), decided 2026-06-04 in `docs/LICENSE_DECISION.md` and
  deferred to pre-1.0. `LICENSE` now carries the canonical Apache-2.0 text staged in #634;
  `TRADEMARKS.md` and the CONTRIBUTING relicense grant were already in place before any outside
  contribution could land, which was the precondition for flipping. README badge follows.
- **De-gated development (owner decision).** Removed every PR-blocking CI gate and scan:
  `security.yml` (gitleaks/semgrep/pip-audit/bandit), `ai-review.yml` (three AI reviewers per PR),
  `autonomy.yml` (tier/boundary classifier), `lockfile.yml`, `park-guard.yml`, `nerva-roadmap.yml`
  (roadmap-ledger validation), the Nerva movement gate in `ci.yml`, CODEOWNERS, the machine-readable
  AI-development policy + evidence-receipt PR template, and the pre-commit hooks. PRs now run one
  fast advisory lane (`ruff` + `pytest` on ubuntu, ~3 min); the Windows matrix, sandbox-isolation,
  HUD/frontend suites and OpenAPI typegen drift check moved post-merge (push to `main`), and
  CodeQL/e2e/smoke/code-health/eval/third-party-drift dropped their `pull_request` triggers.
  Partially walked back four days later — see the next entry.
- **Partial PR re-gate and the 1.0 freeze** (#1011, CTO decisions 2026-09-02 —
  `docs/decisions/2026-09-02-cto-ci-posture-and-1.0-freeze.md`). Back on the PR path, at roughly
  zero added wall-clock because they run beside `test`: `hud-v2-build` (committed-bundle
  staleness), the four security-scan lanes, and the lockfile-drift lane (`in-sync`); the PR pytest
  run additionally verifies the tracked backend test count. Push-to-`main` runs are no longer
  cancelled by newer pushes, and the Windows matrix stays post-merge because its catch is
  probabilistic — the flaky test was fixed instead: `notes_store._now()` is now strictly monotonic,
  closing the Windows-only `list_docs` ordering tie that had turned two `main` pushes red. The
  nightly Reality Harness no longer crashes on the `agents.core.skills.discover` removed in #980,
  and `status_sync.py` gained a third horizon state (🔨 — delivered, runtime proof pending), so the
  ledger stopped over-reporting open work 3×. Dependency wave: `npm audit fix` across the three JS
  trees (all three to 0 findings) and the three Python locks regenerated.
- **A2 — the 72h soak grades itself.** `scripts/soak_report.py` gained `evaluate()`: the A2 bar is
  now written down as thresholds (availability ≥99%, zero restarts, zero audit-verify failures
  (AUD-0), zero guardrail breaches, no open circuit breaker, RSS growth ≤15%, WAL ≤64 MiB) instead
  of applied by eye. `--fail-on-verdict` turns the verdict into an exit code — PASS 0, FAIL 1, and
  **INCONCLUSIVE 3** for a window where some check had no evidence, so an ungraded soak can never
  read as a pass. The verdict is rendered into the report and written alongside it as
  `<day>-soak-verdict.json`.
- `--pid` is now optional: without it the collector records **no** RSS series rather than
  measuring its own process, and the leak check reports INCONCLUSIVE.
- **`.github/workflows/soak.yml`** runs the window unattended — boots the server, samples, grades,
  publishes the report to the run summary, uploads the evidence. A weekly canary on a hosted
  runner; the full `72h` via `workflow_dispatch` with a self-hosted `runner` label.
- Owner gate A7 (design partners) is closed and A8's owner-host proof ran on real hardware with
  good feedback. **A4 (GitHub settings)**, which the 2026-09-02 re-gate reopened, closed the same
  day: the seven PR checks above are listed as required in the `main` branch ruleset, so a red
  check now blocks a merge instead of merely stopping the auto-merge sweep. A6 (60s demo cut)
  stays open as GTM work, never a tag blocker.
- `agents.__version__` `0.11.0` → `1.0.0`.
### Q10 — the public widget door is governed like the external input it is (2026-08-02)
- **ch11 CHN-061**: `widget` no longer sits in `INTERNAL_TURN_CHANNELS`. The embed endpoint is
  tier `open` — an anonymous visitor on a third-party site — so its turns now classify
  **`inbound`**, which taint-marks them (`inbound:widget`) and makes the kernel escalate a
  GRANTed action to QUEUE (owner approval) instead of letting it auto-execute.
- **ch11 CHN-060**: `POST /api/widget/{token}/message` routes through `Gateway.route` (via the
  new late-binding `app_state.get_gateway()`), so the per-channel rate limit and injection-flag
  detection apply. Deliberately **no `sender=`** — the pairing gate fails closed and would hold
  every anonymous message for approval — and deliberately **no inbox record**, since there is no
  widget reply adapter and a thread nobody can answer would be the dishonest option.
- A `None` from the gateway (its handler-failure path) maps to the documented
  `{"reply": "", "error": "request failed"}` envelope, so the embed shows an honest failure
  rather than its `(no reply)` fallback.
### Q8 — review→dataset promotion mints a real case, not a fabricated 1.0 (2026-08-02)
- **WFL-088**: `ReviewQueue.to_eval_case` emitted `{"input","expected",…}` — keys `run_dataset`
  never reads — so every promoted case replayed an **empty prompt** with no criterion, and the
  harness's "no criterion → pass by default" turned a flagged-as-bad answer into a perfect eval
  score. It now emits the documented `{"name","prompt","expect_contains","metadata"}` contract
  (promotion is idempotent per `trace_id`; `POST /api/review/{id}/dataset` accepts an optional
  reviewer `expect_contains` gold; `prompt_source` records that the preview may be truncated).
- **A criterion-less FILE case is now UNSCORED, never a pass** — `scored:false`, `score:null`,
  excluded from the aggregate (which is `null` when everything is unscored, never `0.0`), with
  `unscored:n` on the run. `EvalHarness._evaluate`'s pass-by-default is deliberately untouched:
  it stays a smoke-test affordance for ad-hoc lanes, while in the file lane `expect_contains`
  *is* the criterion (as the module contract has always said).
- **A promotion with no prompt is refused `400`** instead of minting a case that burns a live
  inference against an empty string.
### Q7 — workflow truth pair: parallel-batch honesty + built-in restore (2026-08-02)
- **WFL-032**: a step that *returns* `[error:…]` (timeout, validator, guardrail, subflow) inside a
  PARALLEL batch now fails the run exactly like the serial branch — before, `_ok` stayed `true`
  over a failed run (golden-rule class: `✓ Run complete` above a trace showing `ok: false`).
  With `JARVIS_WORKFLOW_PERSIST=1`, such runs now retry/park-dead in the durable queue instead of
  completing — the honest outcome.
- **WFL-036**: deleting a user pipeline that shadows a built-in id now RESTORES the pristine
  built-in in the live registry (`WorkflowRegistry.unregister`, from `_BUILTIN`) instead of popping
  it until restart; the route comment is finally true.
### Q5 — SEC-065 live guardrails-mode propagation + SEC-071 audit preview redaction (2026-08-02)
- **The posture screen and the live engine now agree without a restart** — `GuardrailsEngine.apply_settings`
  (name-keyed; garbage keeps the CURRENT mode) is re-pushed by the 30s settings watcher; `bind()` copies
  the mode per request, so the next turn scans under the new mode. A live flip rotates the prompt-cache
  key via `policy_fingerprint` (expected).
- **`content_preview` is masked at rest** — `AuditLogger.log()` redacts the preview (secret+PII scanners,
  the AUD-12 `[REDACTED:<pattern>]` convention) BEFORE the chain hash so stored rows verify; the turn seam
  redacts **then** truncates (`AuditLogger.preview`) so a 100-char cap can never split a key into an
  unmatchable raw prefix. `GET /api/admin/audit`'s `summary` alias shows the masked value.
### Q2 — /chat/stream parity: session notes injected; constant error bodies (2026-08-02)
- **`/chat/stream` now injects the session's notes block (H10.21) the same way `/chat` does** —
  persistent notes silently stopped applying the moment the cockpit switched to streaming
  (ch02 CHT-073 / open gap G3).
- **Both chat error paths return constant text** (`Internal error.` / `Eroare internă.`) instead
  of live exception detail — the py/stack-trace-exposure family that blocked #750; specifics stay
  in the server log.
### Q6 — kill-switch per-agent scope at the executor seam + stuck-RUNNING reaper (2026-08-02)
- **A per-agent halt now holds that agent's tasks at the tick** (`_halted(task.agent)` per task,
  same kernel-independent seam; held ≠ lost — tasks stay `approved` and run on release; summary
  gains `held`). The global pre-check and fail-open-on-broken-switch semantics are unchanged.
- **The worker now shares the orchestrator's own `KillSwitch` instance** — its lazy fallback
  built a second store that never reloaded the file, so a halt engaged after boot never reached
  the tick until a process restart (red-proven by revert-run).
- **`TaskQueue.reap_stuck_running(ttl)`** fails crash-stranded `running` tasks past
  `autonomy.running_ttl_seconds` (default 3600, live-resynced each tick, ≤0 disables) with
  `stuck_running_ttl` + `stuck_since` and an `autonomy.reaped` audit row — run at the top of
  every tick, even under a halt (honesty about a dead task is bookkeeping, not an action).
  In-process hangs stay the executor wall-time budget's job; the reaper exists for dead processes.
### A8-ii — presence-aware media target `presence:auto` (2026-08-02)
- **`target: "presence:auto"`** on `media.present` resolves the owner room's default device —
  gated on a **fresh `present` signal** from the H34.2 owner-presence store (the temporal half)
  plus **`JARVIS_MEDIA_PRESENCE_ROOM`** (the spatial half; unset keeps the target default-off).
  Idle/away/unknown/stale presence, a missing store, or an unset room refuse `presence_unknown` —
  a guess about where the owner is would be a lie. Room-level refusals pass through unchanged,
  every other target string resolves exactly as before, and the sentinel is branched before
  device-id lookup so a registered id can never shadow it.
### A8-iii — MediaDriver registry + the LocalFileMediaDriver reference driver (2026-08-02)
- **`JARVIS_MEDIA_DRIVERS`** (env, comma-separated; whole-list fail-closed like the sibling media
  knobs) binds real drivers into the route-owned `MediaDirector` — the `drivers=` seam existed on
  the class but `_get_director()` never passed it, so `NullMediaDriver` was the only reachable
  implementation and owner gate A8's media proof was unschedulable.
- **`LocalFileMediaDriver`** (`local_file` → device kind `local`): durable now-playing state under
  `data_path("media")/now_playing.json` that passes the full present/verify/restore rails and
  really flips to `idle` past a declared duration. Honest limits documented: no sound or image —
  it proves the governed rail before hardware is bought, not playback itself.
### fastapi 0.137 upgrade unblocked — route-introspection flattener (2026-06-19)
- **`fastapi` bumped to `>=0.137.2,<0.138`** (+ `starlette>=0.46,<1.0`). fastapi 0.137 wraps
  `include_router` results in an opaque `_IncludedRouter` instead of flattening them into
  `app.routes`, which collapsed the *introspected* route surface 296→83 and failed the route-parity /
  auth-matrix guards (the app was never broken — routes served + appeared in OpenAPI).
- **Fix:** `tests/_route_introspect.py::iter_effective_routes` flattens the wrappers via fastapi's own
  `_iter_routes_with_context` — yielding effective routes with merged `.path`/`.methods`/`.dependant`
  — and falls back to plain `app.routes` on fastapi ≤0.136. `test_route_parity_guard.py` and
  `test_route_auth_matrix.py` use it; **snapshots unchanged** (validated on 0.137.1: parity 296/296,
  auth-matrix 300/300, 0 drift, include-time guards resolve). Closes the hold tracked in #247.

### Maintenance — dependency upkeep, bug-table reconciliation, fastapi 0.137 hold (2026-06-19)
- **Dependabot triage:** merged the safe bumps — `actions/checkout` v6→v7 (#222), worldview-mcp dev
  deps (#223), root `vitest` 2→4 + `jsdom` 25→29 (#224). Held for dedicated review: React 18→19
  frontend (#226), WorldView 23-update group (#228), mobile group (#227, owner-gated). #237's harmless
  `pytest-xdist`/`ruff` dev bumps were split out from its held `fastapi` bump.
- **fastapi 0.137 held + root-caused (#247):** 0.137's `include_router` wraps included routers in an
  opaque `_IncludedRouter` instead of flattening into `app.routes`, collapsing the *introspected* route
  surface 296→83 and failing the parity / auth-matrix guards. The **app is unaffected** (routes serve +
  appear in OpenAPI); remediation + repro in
  `docs/research/2026-06-19-fastapi-0.137-include-router-regression.md`. Pinned `fastapi<0.137`.
- **MCP client `asyncio` NameError fixed (#243):** `MCPServer._send` awaited `asyncio.wait_for` with
  `asyncio` imported only inside `connect()`; the NameError was swallowed by a broad `except`, so
  **every** outbound MCP request silently returned `{}`. Hoisted the import + regression test
  (`tests/test_mcp_client.py`). Surfaced by `ruff F821`.
- **BACKLOG bug-table reconciled (#245):** BUG-3/6/7/8/9/10/11 were already fixed in code (with tests)
  yet still listed open — marked ✅ with fix location + guard test; BUG-12 → 🟡 (spend race closed via
  `_spend_lock`).

### Neural Mesh — live brain visualization of the orchestrator (2026-06-17)
- **`/brain` — the JARVIS Neural Mesh**, a live canvas "brain" of agents + models firing in real
  time (core node = the orchestrator, inner shell = models sized by cost, outer shell = agents,
  with token-flow particles animating along the attribution edges; hover to isolate, click to pin,
  drag to stretch). The visualization is adapted from **Axon's "NEURAL MESH" by Daniel Tamas**
  ([github.com/danieltamas/axon](https://github.com/danieltamas/axon)), used under the MIT License
  (retained in `LICENSES/axon-MIT.txt`).
- **`GET /api/brain/summary`** (`agents/core/routers/brain.py`) feeds it from the real request
  **tracer** — per-agent / per-model token + cost rollups, by-backend (local/claude/gemini)
  attribution, and a live recent-turns feed — seeded with the full agent roster so the mesh shows
  every node even when idle, then lights up the nodes with real traffic. `?range=today|7d|30d|all`.
  Both routes are `user_guard`-gated (localhost by default). 7 new tests (`tests/test_brain_summary.py`).
- **Dashboard integration** — the Neural Mesh now **replaces the agent-ring visualizer** in the
  primary v2 HUD cockpit (`frontend/src/app.tsx`): the network panel embeds the chrome-less mesh
  (`/brain?embed=1`) instead of the legacy SVG ring. `brain.html` gained an `?embed=1` mode that
  drops all chrome and renders only the full-bleed mesh. v2 bundle rebuilt; tsc + 19 v2 tests +
  184 legacy frontend tests green. (The legacy `/v1` HUD keeps its SVG ring.)

### WorldView — API never starts on Windows (2026-06-17, #204)
- **`worldview/backend-api/src/server.ts`** gated its auto-start on
  ``import.meta.url === `file://${process.argv[1]}` ``. On Windows `process.argv[1]` is a backslash
  path (`C:\…\server.ts`) while `import.meta.url` is `file:///C:/…/server.ts`, so the concat never
  matched → `main()` skipped → `app.listen()` never called → **nothing on `:4000`** (the frontend
  sat at "Reconnecting to the live feed… API may be offline"). Switched to the platform-aware
  `pathToFileURL(process.argv[1]).href` — the guard already used in `worldview/mcp/src/server.ts`.
  tsc clean, 218 backend tests pass.

### WorldView — two frontend dev-console warnings silenced (2026-06-17, #202)
- `app/layout.tsx`: `suppressHydrationWarning` on `<body>` (Grammarly/ColorZilla inject attributes
  before hydration — not a WorldView bug). `components/DeckGlobe.tsx`: deferred the `setZoom` store
  write out of Deck.gl's render-phase `onViewStateChange` (and skip when unchanged) — fixes the
  "Cannot update AppBar while rendering DeckGLWithRef" setState-in-render warning. tsc + 140 vitest
  tests + `next build` green.

### Security — synthetic OpenAI-key fixture defused (2026-06-17, #215)
- `tests/test_h10_4_guardrail_node.py` held a hand-crafted `sk-…` placeholder (a fixture for the
  guardrail/secret-scanner, **not** a real key) that GitHub secret-scanning flagged as a public
  leak. Built it by concatenation so the `sk-`+40-char shape never appears verbatim in source; the
  runtime value (and every assertion) is unchanged. No rotation, no history rewrite.

### CodeQL — correctness, ReDoS & log-injection fixes (2026-06-17, #216)
- **#248** (`skills/calendar/main.py`): `add_event` called `create_event(start=…, end=…)` but the
  plugin signature is `(summary, start_dt, end_dt)` → `TypeError` on every call. Fixed kwargs +
  corrected the test fake that mirrored the wrong signature and masked the bug.
- **#26** (`agents/core/heartbeat.py`): `SchedulerNotRunningError` was imported from the wrong module
  with a `= None` fallback → `except None:` `TypeError` in `stop()`. Import from `.base` with a real
  `Exception` fallback.
- **#1** (`agents/core/llm/base.py` `strip_thinking`): rewrote the leading-numbered-step regex to a
  linear form (`^(?:\d+\.[ \t][^\n]*\n)+\n`) — the old `\s+.+` backtracked super-linearly.
- **#302** (`workflows/hierarchical.py`): made the `_render` template group possessive `\{([^}]++)\}`.
- **#311 / #24** (`agents/web.py`, admin-only routes): routed user input through `log_safe()` before
  logging (CR/LF log-forging). The path-injection alerts #22/#23/#431 are false positives (the
  agent-id regex `^[a-z0-9_-]{1,64}$` forbids separators) — dismissed in the UI, not patched.

### WorldView — full UX redesign implemented from the Claude Design spec (2026-06-12)
- **The complete TASK-4 WorldView redesign** (`docs/design/WORLDVIEW_UX_SPEC.md`, all 11 steps),
  on top of the tactical fixes from PR #193: brand-unified tokens (void/surface/signal `#2BB8F0`,
  Space Grotesk + JetBrains Mono via fontsource), an app bar + two-rail **zone system** (no more
  absolute-offset panel collisions), a three-signal **mode system** (2px frame + pill with GO LIVE
  + timeline restatement; DEMO watermark bound to feed source), **Legend=Layers** with the real
  map glyphs + live counts, de-collided **shape+color map encodings** (canvas icon atlas with
  circle fallback; military=amber hollow chevron, red reserved for wrong), the **negative-space
  grammar** (signal-loss ghosts, dashed dead-reckoned paths, uncertainty cones, voided-zone
  outlines — never animated, never invented), humanized **Inspector** with dark-vessel alert
  context + plain-words provenance, first-run overlay per spec copy, timeline **event markers** +
  store-lifted replay window, styled tooltips, help overlay from a shared shortcut map (+`1–5`,
  `G` bindings), and the **arrival deep link** (`?from&to&layer&id&lon&lat&zoom&agent` → camera
  pre-positioned, entity selected, REPLAY from frame one, Argus banner) + the optional demo lens.
  39 new frontend tests (140 green), tsc + `next build` green. Design package + impl: PR #194.

### UX — first-run onboarding + pre-test review (2026-06-10)
- **First-run guidance banner** (HUD `app.tsx`). Booting the real bundle in a browser confirmed a
  fresh install (server up, no model, no plugins — the manual-test starting state) showed a wall of
  "not connected" with no next step. Added a dismissible, model-aware welcome strip ("start LM
  Studio…" / "connect plugins in Admin") with one-click demo preview; remembered in localStorage.
  tsc + 19 frontend tests green, bundle rebuilt.
- **Deep UX review of both frontends** → `docs/2026-06-10-ux-review-hud-worldview.md` (triaged P1/P2/P3,
  verified the honesty system + design visually). Remaining items tracked as BACKLOG TASK-4 for a
  focused post-manual-test pass — deliberately not bulk-fixed before the human gate.

### Diagnostics — surface a silent OAuth failure + CLN sequencing (2026-06-10)
- **`oauth.load_token` no longer swallows a decrypt failure.** A rotated/missing secret key or
  corrupted token file silently left the still-encrypted token in place — the connected service
  (Gmail/Calendar/Spotify) would then fail mysteriously with no trace. Now it **warns** ("re-
  authorize the service"), so the owner can diagnose it during the manual-test run. +1 test.
- Telegram cosmetic calls (callback-ack, typing indicator) and the Qdrant collection probe:
  documented their intentional swallows (debug log / comment) so they're no longer indistinguishable
  from a missing handler. (Surveyed all 355 `except` blocks; the rest are legitimate documented
  graceful-degradation — left as-is to avoid log noise.)
- **CLN-2/CLN-3 (god-object split) sequenced post-1.0** by owner decision — a 5,000-line refactor
  carries regression risk that shouldn't land before the human manual-test gate. Recorded in
  BACKLOG + OWNER_TASKS.

### API honesty — two inconsistencies found by running the app (2026-06-10)
- **`GET /api/agents/{id}/history` 404s for unknown agents**, consistent with `/soul` (it
  was returning a misleading `200 + empty runs` for any id, so a typo'd agent looked real
  with no history). Also validates the id against the agent-id alphabet.
- **`POST /learning/promote` of a nonexistent bench agent returns 404 / `ok:false`** instead
  of the old `{ok:true, promoted:false}` that reported success for a no-op. +3 endpoint tests.

### Governance audit pass 3 — 3 promises hold, 1 defense-in-depth gap closed (2026-06-10)
Verified four governance promises against the code (the method that found BUG-14..17):
- **Autonomy risk gate ✅ holds** — ASK-tier tasks go to BLOCKED, `runnable()` queries only
  `approved`, night-shift `max_tier` is enforced at the SQL level, edits are re-gated. An
  irreversible/money task cannot execute without explicit approval.
- **Interrupt budget ✅ holds** — `consume()` gates before every push and again at execute
  time; day-rollover is atomic; the 5th interrupt is held for daily review, not dropped.
- **Capability tokens ✅ hold** — expiry is checked at USE time (not just issue), scope is
  fixed at issue, `authorize()` requires both the token and the kill-switch.
- **Injection quarantine — wired into the untrusted-input gate.** The quarantine primitives
  existed but weren't invoked on the path that turns untrusted text into actions. *Corrected
  severity:* not a critical exploit (chat agents return text, never call mutating tools; the
  only text→task path — transcript ingest — is already hard-forced to ask-tier=3, so nothing
  auto-runs). Closed the defense-in-depth gap: transcript ingest now runs `detect_injection`
  and surfaces `injection_flags` + an `untrusted_source` marker on the **approval card**, so
  the human gate is informed when content is tainted. +1 test. Broader "taint-track every
  external channel" left as a tracked finding (architecture decision — see BACKLOG TASK-3).

### Stability & UX — found by running the app as a first-time user (2026-06-10)
Booted the server and walked the journeys a new user hits before loading a model:
- **Friendly "no model loaded" message.** A fresh install with no LLM returned a raw
  `[jarvis error: No LLM backend available]` as the chat reply — the single most common
  first-run state, with the least helpful message. Now every channel (web/telegram/discord/
  CLI) returns one actionable line: "No language model is loaded yet. Start LM Studio (or
  Ollama)…". Fixed centrally in the orchestrator's agent-call handler.
- **`AGENT_COUNT` no longer drifts.** `/api/status` (consumed by the HUD) reported 16 active
  agents while the roster was 17 — a hardcoded constant. Now computed from the canonical
  registry (`agents.yaml`) with a registry-pinned regression test.
- **Blank turns rejected.** An empty/whitespace `/chat` message was accepted and spent a full
  routing + LLM turn; now rejected with 422 before reaching the orchestrator (`min_length` +
  a not-blank validator). Cheap no-op for an accidental Enter.

### Security — governance promises verified against code, 3 fixes (2026-06-10)
Second docs-vs-code audit pass (same method that found BUG-14):
- **BUG-15 — Howard could reach the cloud.** `_select_howard_backend` short-circuits
  *before* the policy gate, and its last resort was Gemini (`cloud-fallback`) — for the
  LOCAL_ONLY digital twin holding the owner's conversation archive. Now fails closed,
  like Frigga (BUG-14). +1 test.
- **BUG-16 — `llm.cloud_fallback` was a dead knob.** The /admin privacy setting
  (`never|on-demand|always`) was defined and rendered but read by NOTHING — an owner
  selecting "never" still got cloud spill. Now honored live in `HybridRouter`
  (`never` keeps auto-policy agents local even oversized; `always` prefers cloud;
  `on-demand` = previous behavior), re-synced ≤30s by the settings watcher. +6 tests.
- **BUG-17 — the Merkle audit chain was never verified.** `AuditLogger.verify_chain()`
  had zero callers — "tamper-evident" without an evidence check. New
  `GET /api/security/audit/verify` returns `{valid, first_invalid_id, entries}`;
  unit tests prove real tampering and re-linking are detected. +5 tests
  (HUD surface queued in the TASK-2 punch-list).

### Security — strict-local agents fail closed (BUG-14, 2026-06-10)
- **Frigga could reach the cloud.** `HybridRouter.select_backend` with `policy=local` fell
  back to Gemini (`cloud-fallback`) whenever the local backend was down — and a unit test
  enshrined it. This contradicted non-negotiable principle #1 (MOONSHOT §5.1, AGENTS.md:
  "no external calls, no cloud fallback — ever"). Now `policy=local` **fails closed** with an
  explicit error; tests assert frigga is never routed off-machine even with cloud available.
- **`agents.yaml` `llm_policy` is now honored** in routing (it was silently ignored —
  Argus was registered `claude` but routed `auto`). Resolution order: `LOCAL_ONLY_AGENTS`
  security floor (code-enforced, registry can't override) → registry `llm_policy` → in-code
  fallback sets → `auto`. +3 tests; ARCHITECTURE §5 updated.

### HUD v2 depth pass — UI controls for the 2026-06-09 backend wave (2026-06-10)
- **TASK-2 control gap closed** (PR #181) — the parity re-audit found ~37 backend endpoints
  with no HUD v2 control; all now have live surfaces:
  - **Cockpit:** live cognition over SSE (`/api/cognition/stream`, NTH-1) — routing decisions
    stream into the trace as they happen; the post-turn snapshot stays as fallback.
  - **Trust:** payment approve/reject/settle on the real broker ids (H16.3); sender-pairing
    approvals + pairing code (H12.19); prompt-injection scanner (H17.1).
  - **Autonomy & Agents:** heartbeat run/start/stop; transcript→governed-tasks ingest (H12.25);
    escalation targets + send (H12.11); bench promotion (`/learning/promote`); agent templates
    (H10.29).
  - **Build:** AI step builder (H10.7); sandbox execute with honest DEV_MODE 403; marketplace
    review ✓/✕ (H12.12).
  - **Memory/Observe:** nightly-reflection status + run-now; eval dataset runs + compare.
  - **Admin:** LM Studio server start / model load / unload; cloud auth-profile pools (H12.20).
- Admin-guarded Console actions now send the admin token (`actA`) instead of relying on the
  localhost exemption (kill-switch, A2A decide, capability issue, marketplace review, promote).
- `frontend/`: +7 tests (19 total) — payments/review/promote helpers, PairingPanel decide flow,
  SandboxPanel execute + 403 honesty. `tsc` clean; bundle rebuilt to `agents/web/v2/`.
- Punch-list updated: `docs/design/HUD_V2_REMAINING.md` §10 (remaining tail: plugin-gated mode
  wiring, per-panel LIVE/SEED chips, §6 toolchain, locality endpoint).

### HUD voice loop — hands-free voice in the browser (2026-06-07)
- **Browser voice loop** (PR #162) — the HUD mic button was a dead toggle and the voice
  engines only worked for a host-attached mic. New `frontend/src/voice.ts` (`useVoice`)
  captures mic audio (`getUserMedia` + `MediaRecorder`), VAD-segments an utterance, sends it
  to **local Whisper** via `POST /api/voice/stt` (raw body — deliberately no `python-multipart`),
  hands the transcript to the chat turn (`app.tsx: runTurn`, now promise-returning), and
  **speaks the reply** — server `/tts` (cloned voice) with a fully-local `speechSynthesis`
  fallback. Loops hands-free until toggled off.
- **Honest capability reporting** — `GET /api/voice/capabilities` (`{stt,tts,tts_local,providers}`)
  drives the HUD; STT returns `503` + install hint when `faster-whisper` is absent rather than
  fabricating a transcript. `tests/test_voice_stt.py` (+4 mocked, headless).
- **Voice settings** (persisted `localStorage['hud.voice']`, ⚙ popover): hands-free vs
  push-to-talk, speak via server/browser/off, language auto/RO/EN; respects `JARVIS_MIC_MUTED`.
- **Opt-in barge-in** (PR #164, default OFF, experimental) — sustained over-talk above an
  echo-resistant threshold cancels the spoken reply so the loop captures you. Renamed the SPEAK
  option `CLONED`→`SERVER` (it is your cloned voice only when XTTS is configured).
- Docs: `docs/VOICE.md` (new); `docs/ARCHITECTURE.md` §3 + Doc Map updated; BACKLOG H5.16 corrected.
- ⚠️ Live mic/audio + barge tuning need a real device — verified here by `tsc`/`vite build` +
  mocked STT test only.

### Security — Romanian PII detection (2026-06-01)
- **`PIIScanner` now detects Romanian identifiers** (`core/security/scanner.py`),
  closing the long-standing gap between the docs ("Romania-specific, CNP format")
  and the US-only implementation:
  - `ro_cnp` — national ID (CNP), **CRITICAL**, confirmed by the official
    control-digit checksum + birth month/day plausibility, so arbitrary
    13-digit numbers are not flagged.
  - `ro_iban` — Romanian IBAN, **HIGH**, confirmed by the ISO 7064 mod-97
    checksum (case-insensitive, space-tolerant).
  - `ro_phone` — Romanian mobile (`07…`, `+407…`, `0040…`), **MEDIUM**.
  Matches for the checksum-bearing patterns must pass their validator before
  being reported or redacted (a non-CNP 13-digit run is left untouched).
  Exposed `is_valid_cnp` / `is_valid_iban` helpers.
- **First direct test coverage for the scanners** — `tests/test_security_scanner.py`
  (+27 offline tests) covering `SecretScanner`, the existing generic PII patterns,
  the new RO detectors (valid vs. invalid checksum), and `GuardrailsEngine`
  REDACT/BLOCK/WARN behaviour.

### H5.17 Batch & Cache Embeddings (2026-06-01)
- **H5.17 Batch & Cache Embeddings Pipeline** (`core/ingestion/embedder.py`):
  `EmbeddingCache` — content-addressed (`sha256(namespace\x00text)`), sharded,
  crash-safe (atomic temp→rename), with hit/miss stats. `Embedder.embed_batch`
  resolves cache hits first, de-duplicates, and computes only misses (optionally
  across a thread pool). Each backend call is retried with exponential backoff
  and **degrades to the hash embedding** when the budget is exhausted, so a flaky
  rate-limited call never aborts a massive Howard ingest. Cache namespaced by
  `backend:model`; pipeline logs `cache_stats` in Phase 6. +9 offline tests.

### QA pass + Retrieval Fusion (2026-06-01)
- **H5.14 Retrieval Fusion Engine** (`core/memory/fusion.py`): `reciprocal_rank_fusion()`
  (rank-based RRF, no cross-scale normalization, with source provenance + payload
  merge) and `HybridRetriever` blending the vector store (Qdrant/in-memory) with
  the knowledge graph (Neo4j/in-memory); injected + duck-typed, so it is tested
  offline. Exposed as `MemoryManager.hybrid_search(embedding, keyword, top_k)`.
  +9 tests. Plan: `docs/superpowers/plans/2026-06-01-h5.14-retrieval-fusion.md`.
- **Test isolation fix** (CI red → green): `web.orch` leaked across test files,
  causing 2 order-dependent failures (`test_oracle_endpoints`, `test_agent_soul_endpoint`).
  Made the FastAPI `lifespan` teardown symmetric (guarded reset of `orch`/`gateway`
  on shutdown, so a closed `TestClient` context stops leaking a live orchestrator)
  and restored the global in `test_resilience_integration._admin_response`.
- **Backlog sync**: confirmed **H5.12** (Secured Shell Task Executor — `RemediationRunner`)
  and **H5.13** (Proactive Event Watchers — `EventWatcher`) were already delivered,
  wired and tested; marked done. Full suite: **749 passed, 9 skipped**.

### MCU Gap Analysis audit (2026-05-31)
- **FAZA 2 — Intent router rewrite** (`core/router.py`): replaced the v0.1
  keyword stub with a deterministic, offline-first, **scored bilingual (RO/EN)**
  classifier. Fixes substring misroutes ("car"⊄"scared"), routes Romanian
  queries ("câți bani am?"→Gecko, "cum am dormit?"→Hercules), exact-token wake
  words, confidence + score breakdown on `Intent.context`, canonical
  language-independent `keywords_found` tags, and an optional injected LLM
  fallback used only for unmatched/low-confidence input (zero hot-path latency).
  Drop-in: unchanged `classify()`/`Intent`/`ROUTING_TABLE` contract. +47 tests.
- **FAZA 3 — Proactive OS Observer** (`core/autonomy/observer.py`): the missing
  trigger layer. Samples host resources + service liveness, **debounces on state
  change**, and feeds the existing autonomy queue — plain alerts auto-approve
  (HUD/brief), remediation proposals (e.g. "restart Docker?") become tier-3 ASK
  cards in the decision inbox. Injectable probes (offline-testable). Wired into
  `_autonomy_loop` (gated by `system.observer_enabled`) + `/autonomy/observer`
  endpoints. +15 tests. Full suite: **715 passed, 8 skipped** (after reb: H5.9/H5.10).
- `docs/gap-analysis-mcu-jarvis.md` — full audit on 4 axes + OSS benchmark.

### H4 Platform
- **H4.5 Steve System Monitor** — `skills/system_monitor/` skill with 8 commands:
  - `status`, `cpu`, `ram`, `gpu`, `disk`, `temps`, `services`, `check`
  - Auto-recovery for configured services (ollama auto-restart)
  - Alert thresholds: CPU >80%, RAM >85/95%, GPU temp >85°C, disk >80/90/95%
  - Graceful degradation when psutil or nvidia-smi unavailable
  - 24 tests passing
- **H4.9 Guardrails** — already implemented and integrated (WARN/REDACT/BLOCK modes)
- **S0.2 Heartbeat Sanity** — already completed (Steve 2h, Ultron 2x/day)
### H1 Foundation (completed)
- Voice channel with wake word → STT → orchestrator → TTS pipeline
- Telegram channel with session isolation per `chat_id`
- Web channel with streaming, temperature/max_tokens/model from settings DB
- OAuth module (Google Calendar, Gmail, Spotify) with auto-refresh
- Admin DB → runtime settings with 30s refresh watcher loop
### H2 Core Agent Capabilities
- Pepper email triage routing: `email` keyword targets [pepper, veronica, stark]
- WebSearchPlugin: Tavily / SearXNG / DuckDuckGo fallback chain
- Vision agent wired with websearch plugin
### H3 Intelligence
- Heartbeat scheduler (APScheduler) wired in channel startup
- Bench agent activation — failure tracking, promotion/demotion in orchestrator
### H4 Platform
- Discord channel conditioned on `DISCORD_BOT_TOKEN`
- Email channel conditioned on `SMTP_HOST` + `IMAP_HOST`
- Slack channel conditioned on `SLACK_BOT_TOKEN`
### Cross-cutting
- 39 tests all passing

## [0.2.3] — 2026-05-30
### Fixed
- SSE deduplication: `\n\n` split across TCP chunks no longer creates duplicate messages
- Loading/offline indicators in HUD when API is down
- Admin channels panel now shows all 6 channels (including discord, email, slack)
- Deduplicated `AGENT_GLYPHS` — now uses `window.JARVIS_GLYPHS`
- Recycled `VoiceVisualizer` component (~120 lines) and dead CSS (~85 lines)
- Removed unused `SettingsPage` component

## [0.2.2] — 2026-05-30
### Fixed
- Thread-safe settings DB access with `RLock`
- Dynamic agent ring: `intent.target_agents[0]` fragile indexing
- Memory attribution — each agent's memory stays isolated
- Tests: `conftest.py` fixture isolation, `pytest.ini` config
- QA bug plan documented in `.opencode/plans/qa-bugs.md`

## [0.2.1] — 2026-05-30
### Added
- **HUD redesign**: fully offline-capable SPA with vanilla React (no JSX)
  - Admin panel at `/admin` — settings, channels, agents, audit, test LLM
  - Components: `ChatWindow`, `Sidebar`, `AgentOrchestrator`, `SystemTray`, `SettingsPage`
  - Font system: 31 custom woff2 fonts from JetBrains Mono + Cascade Code
  - Animations: network graph (`network.js`), auto-scroll, theme toggle
- **New plugins**: Apple Health, Google Calendar, Homebridge
- **Gemma 4 31B** as default LLM via Ollama
- **Settings DB**: SQLite-backed settings with admin CRUD, reseed, dynamic `force` flag
- **Security**: guardrails engine with PII detection, prompt injection blocking
- **Sandbox**: code execution isolation layer for agent tools
- **Plugin gate**: permission-based plugin access control
- **Tests**: routing, chat, sandbox/gating, startup — 39 total
- **One-click install**: `install.ps1` — virtualenv, deps, Ollama pull, startup
- **`.env.example`**: config template for all channels, OAuth, plugins

### Changed
- Monolithic `app.js` split into `components.js`, `enhancements.js`, `data.js`, `network.js`
- `style.css` reorganized: 1750 lines with density/theming support

### Removed
- JSX build step — vanilla `createElement` throughout
- External CSS/font dependencies — fully self-contained

## [0.1.0] — 2026-05-27
### Added
- Initial commit: Jarvis v0.2.1 multi-agent AI orchestration system
- Multi-agent orchestrator with routing, context, streaming
- Web UI with chat, system tray, agent status
- Plugin system: Weather, News, Gmail, Telegram, Spotify, WhatsApp
- Voice pipeline with wake word detection
