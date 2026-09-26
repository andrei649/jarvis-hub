# Hermes build queue — the 93 small-effort rows, re-evaluated 2026-09-22

Generated from the 2026-09-22 HEQ-1 re-evaluation of every small-effort (`S`) row that still carried only the 2026-09-07 audit verdict: 16 read-only assessors read the requirement and the code on `main` at 6578cd3c, a skeptic stood ready for every claimed promotion (none was claimed — the old audit held up), and a cross-row critic checked the plans against each other and against the code. The verdicts are in [assessment.json](assessment.json); this page keeps what the ledger does not: how each gap would close.

**How to use it.** Pick from the top (smallest honest estimate first), read the row with `python3 scripts/hermes_status.py show <ID>`, then its plan here **and every critic note it links** — 60 of the 93 plans overlap another plan or rest on a premise the critic corrected, and building two of them separately would collide. Estimates are hours for a careful engineer including tests, not a schedule. A plan is a starting point, not a contract: the requirement in the frozen inventory wins. When a row closes, its ledger entry changes in the same PR and it leaves this page.

**Closed by lot 1** (#1204, 2026-09-23): H691, H661, H344, H583, H368, H242, H503, H313 — each built red-first, adversarially reviewed, fixed and independently verified on the integrated head; their plans left this page with their ledger entries. 85 rows remain.

**Closed in #1207** (2026-09-24): H327, H433, H687, H428, H165, H200 + H153 (built once, per critic note 7), H273, H315, and on 2026-09-25 H666, H318 + H340 (built once, per critic note 21) and H465 — built red-first one at a time in the single integration PR; plans left this page with their ledger entries. 72 rows remain.

**Re-opened and closed again in #1207** (2026-09-24): H428. Its review round made the recall bound hold for the turn: a separate store lock, and background turn embeddings. It found the next-turn warm-up half missing, and that half was then built as a per-session warm context that stands in when a turn's own recall times out or is skipped.

**Re-opened and closed again in #1207** (2026-09-24): H153. Its review found the per-hook switch leaked for a delivery already in flight (fixed: the switch is read live after the body), and that its equivalence rested on a narrowing of scope nobody decided. The missing parts were then built: a receiver switch that refuses every delivery at once (the setting `webhooks.receiver_enabled`, with a card and a banner in the panel), a per-hook event list (deliveries of other events are answered 202 and never run) and a prompt template. Per-subscription skills and deliver-only are adapted, and the ledger entry says why. H200 stays closed with the review's fixes and gains the receiver banner. 77 rows remain. A second review then found that deliver-only had not been adapted at all: Hermes' Deliver to and deliver-only were unbuilt and unmentioned, and a create carrying them was answered 200 with the fields dropped. It also found that the receiver switch failed open when the settings store could not be read. Both were built: a hook delivers to the log or to one of the owner's own direct-send channels (email, a GitHub comment, Discord and Slack are refused by name), deliver-only skips the agent, and the switch fails closed. H153 closed a third time.

**Reviewed and fixed in #1207** (2026-09-24): H315, twice. The first review found three problems. The plan was keyed on the shared default session, so a widget visitor, a webhook, a job, a subagent and a direct tool call read and replaced the owner's plan. A plan carried injected text into a later, clean turn. The repeat detector ended a turn that followed the tool's own re-read advice. All three were fixed: on the shared session only an owner's turn keeps a plan; each item records its writer and whether its text is untrusted, and a tainted item makes the answer fenced DATA; and `todo` left the repeat detector and the per-tool cap. `todo` reaches an inbound guest through the default `llm.guest_tools` instead of a session-local exemption (critic note 22 is updated).

The second review found that a sandboxed script still laundered untrusted text into the plan. A script that read a page wrote it as clean text, and a session kernel carried it into a later, clean turn. Now the broker that services a script's calls raises the origin after an untrusted read. A script's writes are data even to the turn that ran it, and a kernel that held untrusted text taints every later cell until a reset. Its minors are fixed too:
- the new guest default reaches an install seeded by an earlier build, once;
- a turn keeps the shared verdict it resolved its session with;
- text a turn that is not the owner's writes is untrusted to the owner;
- a turn reads its own writes unfenced;
- a script's reach is narrowed as the turn's offer is;
- the repeat detector keys a plan read on the plan the model last saw, so reading an unchanged plan again is a repeat once more, while `todo` stays off the per-tool cap.

The row stays closed.

**Reviewed and fixed in #1207** (2026-09-24): H273, a second time. The review found three problems: the doctor sent the admin credential through a redirect or a proxy; more keys than serve.py's four are read before any .env is loaded; and a one-case line of value material could still be printed as a name. Fixed: the credential goes only to a loopback hub and never through a redirect or a proxy; the before-load list is measured by spying on the hub's import; and the doctor prints a name only when the hub reads it, it is prefixed or declared, or it is a plain name with a real value. The nits are fixed too. The row stays closed.

**Reviewed and fixed in #1207** (2026-09-24): H273, a third time. The review found three problems. The start read 31 more names before any .env was loaded, so ten .env knobs showed as in effect while they were not; the audit key and the public-profile gate were among them. Two read-again entries were false: the tokens in the bind guard, and the OAuth ids behind a second module copy. And the MCP transport checked a user token frozen at import. Fixed:
- the hub loads its .env files first, once per process, in serve.py, the lifespan and the plugin manager;
- what locates its files is taken from the process environment only;
- log redaction stays the boot environment's alone;
- the MCP transport and the OAuth routes read after the load;
- both lists are measured by where each name is used, over the whole start.

The doctor now keeps the admin token on this machine, decided by address; reads a local hub's own files; withholds value-shaped names; and scans pools, descriptors and private constants. The nerva CLI got the doctor's transport rules. The row was partial for one commit and is closed again.

**Re-opened and closed again in #1207** (2026-09-24): H153, by its third review. Deliver to reached none of the owner's channels as shipped: a push to telegram, voice or ntfy answered 500 after the turn, web has no receiver, and ntfy refused the label. Fixed with a real send on each channel, tested down to the adapter: the quiet-hours rule imports the right function and runs on a fixed clock in the tests, a delivery that fails is recorded and never a 500 after the turn, web is refused by name, ntfy gets an ASCII title, the text goes as plain text (Telegram: no markup, link preview or voice note), each hook pushes at most 30 times an hour, the hook and the receiver are read again after the turn, deliver-only needs a channel, and a workflow delivers its last step or nothing. H153 closed a fourth time.

**Re-opened in #1207** (2026-09-25): H315, by its third review (review-H315d). The second round fixed a script or cell that writes the plan itself, but not what a script prints. A script or cell that prints a page and then fails answers not ok, and the loop fences only a result that is ok. The taint the broker and the kernel raise stays in the handler's own task. So the page reaches a clean turn as plain text, and what the model plans from it is stored clean. The minors: the kernel's writable mount outlives a reset, a crash and a restart, while its taint lives on the record; and eleven of the review's 76 mutants are not caught. The row is partial until the fix round.

**Closed again in #1207** (2026-09-25): H315, after the third review's fix round. An execute_code result says tainted whenever the run printed anything, read untrusted text or ran on a kernel that held some, so the loop fences it and taints the turn that ran it whether it succeeded or failed. Each kernel interpreter gets a mailbox directory of its own, removed with it, and a start clears what an earlier process left. The broker reads an answer as the loop does (a successful untrusted answer, a declared taint, a scanner flag). A same-text merge is no write, and a script that made tool calls ends the repeat detector's last seen plan. The eleven surviving mutants each have a test or were made equivalent. H315 closed a third time.

**Re-opened in #1207** (2026-09-24): H153, by its fourth review (review-H153d). The two majors of the third are fixed on the real path. The review found a new major and five minors. The major: a push renders the whole text with to_plain before cutting it, and to_plain is quadratic on one long line and holds every thread, so one GitHub-sized body freezes the hub for about 40 s. The minors: to_plain rewrites addresses and file names; a workflow hook can answer 500 after its push; a burst after a start is refused while the receiver's first read runs; useApi starves a slow poller; and three behaviours are unpinned. The row is partial until the fix round, which is next.

**Closed again in #1207** (2026-09-25): H153, after the fourth review's fix round. A push is the text as written: nothing is rendered or rewritten, what hides or reorders text is dropped, and it is cut before it is sent, so a delivery costs linear time. Every renderer the hub uses bounds its marker spans, so one long line renders in linear time too. A burst after a start waits for the receiver's first read. A workflow hook answers with the steps that ran, never the run's context, and every answer is encodable. useApi shows an answer unless a newer one is shown. The twelve unpinned behaviours each have a test, and the nits are fixed or recorded. H153 closed a fifth time.

| Row | Name | Now | Est. h | Critic notes |
|---|---|---|---:|---|
| [H586](#h586) | Paste or attach a screenshot into the conversation (vision & image paste) | partial | 5 |  |
| [H667](#h667) | Never assume /tmp is real storage; prune only the cache you own | missing | 5 | [14](#critic-note-14) |
| [H670](#h670) | The default identity prompt is a behavior contract, and it lives in one file | partial | 5 | [29](#critic-note-29) |
| [H145](#h145) | Read the system logs from the UI | missing | 6 | [32](#critic-note-32) |
| [H157](#h157) | Edit every configuration key from the UI | partial | 6 | [6](#critic-note-6) |
| [H283](#h283) | Know what kind of machine this is, and tell the model | partial | 6 | [29](#critic-note-29), [31](#critic-note-31) |
| [H285](#h285) | Choose which skills, plugins and MCP servers load at startup | partial | 6 | [8](#critic-note-8), [24](#critic-note-24) |
| [H296](#h296) | Adapt a tool's advertised schema to the live configuration | missing | 6 |  |
| [H314](#h314) | Let the model decide what to remember | partial | 6 | [22](#critic-note-22) |
| [H350](#h350) | Skill authoring linter and validator | missing | 6 |  |
| [H441](#h441) | Getting back into a conversation: continue, resume, and a free recap | partial | 6 | [3](#critic-note-3), [4](#critic-note-4) |
| [H501](#h501) | Warn about a dangerous deployment posture before it becomes an incident | partial | 6 |  |
| [H504](#h504) | Fail loudly when TLS trust is misconfigured instead of silently not verifying | partial | 6 |  |
| [H512](#h512) | See who authenticated, who failed, and when | partial | 6 |  |
| [H526](#h526) | Make a spoken reply sound like speech rather than read-out markdown | partial | 6 |  |
| [H696](#h696) | A small default skill bundle with a large on-demand catalog, re-pinned to the current release | partial | 6 | [21](#critic-note-21), [25](#critic-note-25) |
| [H117](#h117) | Message batching and debounce (treat a burst as one turn) | missing | 7 | [1](#critic-note-1), [16](#critic-note-16) |
| [H275](#h275) | Boot into a known-good state when customizations break the install | missing | 7 | [8](#critic-note-8), [24](#critic-note-24) |
| [H328](#h328) | Conditional skill visibility (OS platform, runtime environment, channel, tool availability) | missing | 7 | [23](#critic-note-23) |
| [H334](#h334) | Importing skills from an upstream project at a verified pin | partial | 7 | [25](#critic-note-25) |
| [H380](#h380) | Prove a configured cloud provider actually works | missing | 7 | [26](#critic-note-26) |
| [H450](#h450) | Say when in plain words (schedule syntax) | partial | 7 | [15](#critic-note-15) |
| [H659](#h659) | A retried external request returns the original run instead of starting a second one | missing | 7 | [7](#critic-note-7), [27](#critic-note-27) |
| [H674](#h674) | Compression cannot stall the user: bounded holds, inactivity deadlines and derived thresholds | partial | 7 | [11](#critic-note-11), [13](#critic-note-13) |
| [H677](#h677) | Boot warm-up before accepting work, and every shutdown wait has a short explicit budget | partial | 7 | [1](#critic-note-1), [11](#critic-note-11), [16](#critic-note-16) |
| [H156](#h156) | Edit an agent's persona and description from the UI | partial | 8 |  |
| [H161](#h161) | Warn when the box is running out of memory or disk | partial | 8 |  |
| [H168](#h168) | Shared UI primitives the pages lean on (markdown, destructive-action confirmation, schema-driven fields) | partial | 8 |  |
| [H209](#h209) | Keyboard shortcut customisation with a recorder and conflict detection | missing | 8 |  |
| [H227](#h227) | "What can it do right now" inspector: live status line plus a session panel of tools, skills, resolved system prompt and MCP servers | partial | 8 |  |
| [H247](#h247) | Wake word arming per surface, push-to-talk capture, TTS, and liveness/config primitives | partial | 8 |  |
| [H259](#h259) | Reset to defaults, scoped and previewed, plus export/import of the whole configuration | partial | 8 | [6](#critic-note-6), [28](#critic-note-28) |
| [H262](#h262) | Config-driven data lifecycle — prune, archive, vacuum on an interval-gated sweep | partial | 8 | [5](#critic-note-5), [14](#critic-note-14), [28](#critic-note-28) |
| [H309](#h309) | Show the user where something is, in their UI | missing | 8 | [22](#critic-note-22) |
| [H373](#h373) | See how much provider quota is left before hitting the wall | missing | 8 | [26](#critic-note-26) |
| [H378](#h378) | Be warned before choosing a model that is very expensive or trains on your data | partial | 8 | [9](#critic-note-9) |
| [H410](#h410) | Universal secret redaction on every log record | partial | 8 | [32](#critic-note-32) |
| [H427](#h427) | Fail-closed pre-compression checkpoint — never discard a transcript unless the extraction durably landed | missing | 8 | [13](#critic-note-13) |
| [H464](#h464) | Park a run on real async work instead of poking it | partial | 8 |  |
| [H507](#h507) | Warn the model when the code it just wrote contains a known-dangerous pattern | missing | 8 |  |
| [H613](#h613) | Choose how it sounds and how it hears (TTS / STT provider matrix) | partial | 8 |  |
| [H681](#h681) | Per-child API settings for delegated subagents, and a batch report that names the real reason they all failed | partial | 8 |  |
| [H689](#h689) | One stable identity for this install, and per-profile isolation of its runtime artifacts | missing | 8 |  |
| [H277](#h277) | Separate models for separate jobs (vision, video, approval judging) | partial | 9 |  |
| [H487](#h487) | Ask a human on whatever surface they are on, carry their reason back, and fail closed on silence | partial | 9 | [27](#critic-note-27) |
| [H513](#h513) | Restrict a capability to the surface it belongs on, and let the owner acknowledge a data-handling tradeoff without silencing the warning | partial | 9 | [9](#critic-note-9) |
| [H114](#h114) | Per-channel personality, skills and verbosity | partial | 10 | [17](#critic-note-17), [18](#critic-note-18), [29](#critic-note-29) |
| [H174](#h174) | Uninstall from inside the app, with a pre-flight summary of exactly what goes | partial | 10 | [28](#critic-note-28) |
| [H220](#h220) | Usage and cost accounting surface | partial | 10 | [10](#critic-note-10) |
| [H222](#h222) | Always-visible microphone / wake-word state indicator | missing | 10 | [31](#critic-note-31) |
| [H243](#h243) | Completions (filesystem paths, slash commands) and provider/model options (list, save key, disconnect) | partial | 10 | [26](#critic-note-26) |
| [H329](#h329) | Turning individual skills off without uninstalling them | missing | 10 | [23](#critic-note-23), [24](#critic-note-24) |
| [H413](#h413) | Session auto-titling | missing | 10 | [4](#critic-note-4) |
| [H425](#h425) | Destructive forget: retract a fact and everything derived from it | partial | 10 | [28](#critic-note-28) |
| [H440](#h440) | Automatic session titles and continuation lineage | partial | 10 | [4](#critic-note-4) |
| [H490](#h490) | Start with zero customization to prove a bug is not your own setup | missing | 10 | [8](#critic-note-8) |
| [H594](#h594) | Have the agent pick up a project's conventions automatically (context files) | missing | 10 | [29](#critic-note-29) |
| [H596](#h596) | Keep working when one API key is rate-limited (credential pools) | partial | 10 | [26](#critic-note-26), [30](#critic-note-30) |
| [H063](#h063) | Session reset policy and expiry/stall watchers | partial | 12 |  |
| [H204](#h204) | Capabilities hub — skills and toolsets management | partial | 12 | [24](#critic-note-24) |
| [H218](#h218) | Archived chats, auto-archive of stale chats, and a default project directory | missing | 12 | [4](#critic-note-4), [5](#critic-note-5), [28](#critic-note-28) |
| [H461](#h461) | A standing instruction that re-enters this session on a cadence | partial | 12 | [1](#critic-note-1), [2](#critic-note-2), [3](#critic-note-3), [15](#critic-note-15) |
| [H468](#h468) | Review as a state, not a block (request-review / request-changes / reopen) | missing | 12 |  |
| [H472](#h472) | Subscribe a chat to a work item's terminal events — including waking the agent | partial | 12 | [2](#critic-note-2), [3](#critic-note-3) |
| [H478](#h478) | Bot-to-bot messaging between machines | partial | 12 |  |
| [H579](#h579) | Pull a file or slice of a file into a message inline (@ context references) | missing | 12 |  |
| [H686](#h686) | The operator can see how the model is actually performing right now, and choose which fields to see | partial | 12 | [10](#critic-note-10) |
| [H182](#h182) | Keep the machine awake through a turn, and be aware of power/battery state | missing | 14 | [31](#critic-note-31) |
| [H396](#h396) | Turn exit reasons, a completion explainer and per-turn accounting | partial | 14 | [10](#critic-note-10) |
| [H409](#h409) | Outbound signed lifecycle webhooks | partial | 14 | [7](#critic-note-7) |
| [H416](#h416) | Unified deadline and budget layer | partial | 16 | [11](#critic-note-11) |
| [H545](#h545) | Let the editor hand the agent MCP servers that exist only for that session | missing | 16 |  |

## H586

**Paste or attach a screenshot into the conversation (vision & image paste)** (docs-features) — partial, ~5 h.

Files: `agents/cli/nerva.py`, `tests/test_nerva_cli_vision.py (new)`, `tests/test_cli_fish_completion.py (only if the command-tree snapshot changes)`

Plan: In agents/cli/nerva.py, add `nerva chat --image PATH` (repeatable, at most 8) and `--clipboard`. `--clipboard` reads the image with `wl-paste --type image/png` or `xclip -selection clipboard -t image/png -o`, or `pngpaste -` on macOS: argv lists, no shell, a 5 s timeout and a 4 MiB cap. Check PNG/JPEG/GIF/WebP magic bytes locally and build data URIs. GET /api/vlm/composer/status to learn the destination and binding, and require `--remote-ok` when status.local is false. Then POST /api/vlm/composer/describe with {prompt, images, expected_destination, expected_binding, remote_ack}. Print the response on stdout, and the model/destination provenance on stderr under -z. Map 503 to exit 1, 409 and 403 to exit 1 with a named reason, and a missing clipboard tool to exit 2. Tests in tests/test_nerva_cli_vision.py use an injected fake HubClient. The first red test is test_chat_image_posts_to_composer_describe. Then cover: a remote destination without --remote-ok refused before any POST; an oversized or non-image file refused; a 409 binding change surfaced; a fake clipboard executable on PATH read correctly.

## H667

**Never assume /tmp is real storage; prune only the cache you own** (delta) — missing, ~5 h. Critic notes: [14](#critic-note-14).

Files: `agents/core/sandbox.py`, `agents/core/orchestrator.py`, `agents/core/paths.py`, `agents/core/retention.py`, `agents/core/scheduler_service.py`, `agents/core/settings_db.py`, `tests/test_exec_temp_root.py`

Plan: Add exec_temp_root() (in agents/core/paths.py or a new agents/core/exec_cache.py). Resolution order: settings security.sandbox_temp_dir / env JARVIS_EXEC_TEMP_DIR (owner-pointed, flagged unmanaged), else data_path('cache','exec') (managed, created 0o700). Change Sandbox.__init__ to Path(tempfile.mkdtemp(dir=exec_temp_root())) and have the orchestrator construction use it. Add prune_exec_cache(max_age_hours=72, root=None, live=()): return immediately unless the root is the managed dir; treat each top-level sandbox dir as a group whose age is the newest mtime inside it; skip dirs in `live` (the orchestrator's current sandbox.work_dir); rmtree stale groups; return counts. Wire it into run_retention or an hourly SchedulerService job. The first red test in tests/test_exec_temp_root.py: with JARVIS_HOME=tmp_path, Sandbox(allow_wasm=False).work_dir is under tmp_path/'cache'/'exec' (it fails today with /tmp/...). Then add: a stale group containing one fresh .log survives; a fully stale group is removed; the live dir survives; an owner-pointed root is never pruned.

## H670

**The default identity prompt is a behavior contract, and it lives in one file** (delta) — partial, ~5 h. Critic notes: [29](#critic-note-29).

Files: `agents/_system/IDENTITY.md`, `SOUL.md`, `agents/core/agent.py`, `agents/core/orchestrator.py`, `agents/core/soul_versioning.py`, `agents/core/prompt_size.py`, `tests/test_identity_contract.py`

Plan: Create agents/_system/IDENTITY.md with the behaviour spec (reply sizing, the four named prohibitions, anti-sycophancy line, earned-depth rule) and an HTML maintainer comment banning 'be targeted and efficient in your exploration'. Add a repo-root SOUL.md with the same text, or a pointer to it. In agents/core/agent.py, add _load_identity_contract(), resolving user_souls_dir()/IDENTITY.local.md first and then agents/_system/IDENTITY.md, passed through _scan_soul_body and _cap_soul_body. Expose the combined system prompt as contract + '\n\n' + soul body, and use it at orchestrator.py:1985 and in Agent.generate_response/stream so the cached prefix stays stable. Record the contract in SoulVersionStore under a reserved id '_identity'. Update prompt_size.py so the shared cost counts it once. The first red test in tests/test_identity_contract.py: for every active agent built by Orchestrator.load_agents, the system prompt passed to the backend contains the reply-sizing sentence (it fails today). Also add: an override file wins; the contract file does not contain 'efficient in your exploration'; the injection-scan quarantine applies to the contract.

## H145

**Read the system logs from the UI** (web) — missing, ~6 h. Critic notes: [32](#critic-note-32).

Files: `agents/core/log.py`, `agents/cli/nerva.py`, `agents/core/routers/admin.py`, `frontend/src/panels/logs.tsx`, `frontend/src/console-routes.ts`, `tests/test_admin_logs_route.py`, `frontend/src/panels/logs.test.tsx`, `tests/_snapshots/route_surface.json`, `tests/_snapshots/route_auth.json`, `tests/_snapshots/openapi_surface.json`, `frontend/src/api/schema.gen.ts`

Plan: Reader: move `log_path` from agents/cli/nerva.py into agents/core/log.py. Add `tail_log(lines, level=None, component=None, file_index=0, max_lines=500)` there. It reverse-reads in blocks (never the whole file) and parses `_LOG_FORMAT` into {ts, level, component, text}. It runs each returned line through the same SecretScanner that SecretRedactionFilter uses. The CLI `cmd_logs` switches to this reader. Endpoint: add `GET /api/admin/logs` (admin_guard) with params file (jarvis.log or rotation N), level, component and lines (500 or fewer). It returns {enabled, file, lines[]}; when file logging is off it returns `enabled:false` plus the `system.log_to_file` hint. Page: add frontend/src/panels/logs.tsx with segmented Level/Component/Lines filters, regex level colouring and a 5 s auto-refresh toggle with a Live badge, and register it under Admin in frontend/src/console-routes.ts. Regenerate the route snapshots and schema.gen.ts. First red test: tests/test_admin_logs_route.py. Without an admin token the route is refused. A 10k-line file returns only the newest 500 lines. A line holding a synthetic `ghp_...` token comes back masked. level=ERROR drops INFO lines. A missing file returns enabled:false.

## H157

**Edit every configuration key from the UI** (web) — partial, ~6 h. Critic notes: [6](#critic-note-6).

Files: `agents/core/routers/admin.py`, `agents/core/settings_db.py`, `frontend/src/gap.tsx`, `tests/test_admin_settings_io.py`, `tests/_snapshots/route_surface.json`, `tests/_snapshots/route_auth.json`, `tests/_snapshots/openapi_surface.json`, `frontend/src/api/schema.gen.ts`

Plan: Export: add `GET /api/admin/settings/export` in agents/core/routers/admin.py. It returns {schema:'nerva.settings.v1', exported_at, values:{category:{key:value}}}; secret-kind and secret-hint keys are left out and named under `omitted`. Import: add `POST /api/admin/settings/import`. Validate every category with `validate_category` before writing anything. Reject unknown categories and keys rather than skipping them. On any error return 422 with all errors and write nothing. Otherwise call put_category per category and `_audit_settings_change` once per category, with key names only. Reset: add `POST /api/admin/settings/{category}/reset`, which restores only that category's DEFAULTS from settings_db and is audited; also audit the existing global reseed. UI: in SettingsPanel (frontend/src/gap.tsx) add a search input that filters all categories on key, label and category name. Add Export (JSON download), Import (file picker -> POST, showing the 422 details) and a per-category Reset with a confirm step. Regenerate the route snapshots and schema.gen.ts. First red test: tests/test_admin_settings_io.py. An import containing one invalid posture flag returns 422 and writes nothing. Export leaves out secrets. Resetting one category leaves another untouched. Every write leaves an audit row without values.

## H283

**Know what kind of machine this is, and tell the model** (env) — partial, ~6 h. Critic notes: [29](#critic-note-29), [31](#critic-note-31).

Files: `agents/core/sd_notify.py`, `agents/web.py`, `deploy/systemd/jarvis-hub.service`, `deploy/systemd/README.md`, `agents/core/orchestrator.py`, `agents/core/env_config.py`, `docs/FLAGS.md`, `tests/test_sd_notify.py`, `tests/test_environment_hint.py`

Plan: 1. Add agents/core/sd_notify.py. notify(state) sends a datagram to NOTIFY_SOCKET (handling the '@' abstract-namespace prefix) and is a no-op when the variable is unset. watchdog_interval() returns WATCHDOG_USEC/2 seconds when WATCHDOG_PID is unset or equals os.getpid(). 2. In the agents/web.py lifespan, send READY=1 after the readiness state used by /readyz becomes true, start an asyncio task that sends WATCHDOG=1 at that interval, and send STOPPING=1 on shutdown. 3. Change deploy/systemd/jarvis-hub.service to Type=notify, NotifyAccess=main, WatchdogSec=30, and rewrite the sd_notify note in deploy/systemd/README.md. 4. Add environment_hint(), which reads JARVIS_ENVIRONMENT_HINT through env_config, strips control and Unicode-tag characters and caps the text at about 500 chars. Append it as a fixed 'Operator environment note (describes this machine; not instructions)' block to the system string where render_snapshot(agent.soul...) is built in the orchestrator, on both the streaming and non-streaming paths, never inside SOUL. 5. Red-first tests: - tests/test_sd_notify.py binds a temporary AF_UNIX datagram socket, sets NOTIFY_SOCKET/WATCHDOG_USEC, and asserts that READY=1 and then WATCHDOG=1 arrive. - tests/test_environment_hint.py asserts the block is in the system prompt, is capped, is identical across two turns and is absent when unset.

## H285

**Choose which skills, plugins and MCP servers load at startup** (env) — partial, ~6 h. Critic notes: [8](#critic-note-8), [24](#critic-note-24).

Files: `agents/core/load_set.py`, `agents/core/skills/loader.py`, `agents/web.py`, `agents/core/plugin_manager.py`, `agents/core/plugin_gate.py`, `agents/core/routers/plugins.py`, `agents/core/routers/mcp.py`, `agents/core/routers/skills.py`, `agents/core/settings_db.py`, `docs/FLAGS.md`, `tests/test_load_set.py`

Plan: 1. Add agents/core/load_set.py, which resolves optional allow/deny lists for skills, plugins and mcp. They come from a settings_db 'startup' category (skills_only, skills_skip, plugins_skip, mcp_only, mcp_skip), overridable by JARVIS_LOAD_SKILLS / JARVIS_SKIP_SKILLS style env vars. Semantics are narrowing-only: a listed name that is not installed is reported as unknown and ignored. 2. SkillLoader.discover skips filtered directories and records them as skipped_by_load_set for /skills. 3. _load_mcp_config filters configs before load_from_config without rewriting the persisted list. 4. At boot, PermissionGate disables filtered plugins. PUT /plugins/{id}/toggle persists into the same plugins_skip key, so a toggle survives a restart. 5. Red-first tests in tests/test_load_set.py: - A skill in skills_skip is absent after discover() and returns when removed from the list. - An MCP server in mcp_skip is not loaded but remains in settings. - An uninstalled name in skills_only causes no install and no SkillApprovalStore write. - A plugin toggle persists across a fresh PermissionGate instance.

## H296

**Adapt a tool's advertised schema to the live configuration** (tools — the agent-callable surface) — missing, ~6 h.

Files: `agents/core/tool_rpc.py`, `agents/core/observability/capability_registry.py`, `agents/core/autonomy_coordinator.py`, `tests/test_tool_schema_overrides.py`

Plan: agents/core/tool_rpc.py register_tool: add schema_override: Callable[[], dict] | None = None and store it on the spec. In tools(), compute effective = deepcopy(static). If an override is set, call it and require a dict. Shallow-merge its top-level keys, merging 'properties' key by key so that enum narrowing works as in Hermes. On an exception or a non-dict result, log a warning (rate-limited per tool) and use the static schema. Validate call args in handle() against the same effective schema, so a narrowed enum is also enforced. In agents/core/observability/capability_registry.py (the ToolRPC-derived record at the input_schema read), take the effective schema from server.tools() at snapshot time so registry mode advertises the same narrowed schema. Wire overrides in agents/core/autonomy_coordinator.py: terminal_run gets a 'target' enum of the currently registered governed terminal targets (no enum when there are none); desktop_run gets steps.items.properties.action as an enum of the desktop driver's supported actions on this OS. Red-first tests in tests/test_tool_schema_overrides.py: an override returning an enum shows up in tools(); changing the backing value changes the next tools() without re-registration; an override that raises yields the static schema plus one warning; AgentRuntime's ToolSpec receives the narrowed schema; terminal_run's advertised target enum equals the registered targets.

## H314

**Let the model decide what to remember** (tools — the agent-callable surface) — partial, ~6 h. Critic notes: [22](#critic-note-22).

Files: `agents/core/memory/write_tool.py`, `agents/core/autonomy_coordinator.py`, `agents/core/cognition/memory.py`, `tests/_snapshots/tool_profiles.json`, `tests/test_memory_write_tool.py`

Plan: Add agents/core/memory/write_tool.py with register_memory_write(server, living_getter, memory_getter, audit_getter, kernel_getter). The tool is `memory`, with schema {operations: array maxItems 8 of {target: enum, action: add|remove, text: string maxLength 300}}. At call time, narrow the target enum and the description to the stores that are enabled: core and user when cognition memory_enabled is on, note when orch.memory.remember exists. Preflight injection-scans every text (quarantine.detect_injection_normalized) and refuses the whole batch on any flag or invalid op, so nothing partial is applied. Apply the ops by adding a CoreMemory.remove(fact) alongside put, or through memory.remember for notes. Append one SecurityEvent per op to the audit chain (orch.intent_log / AuditLogger) holding the store, action and a hash of the text, so the write can be undone. Graph edges are out of scope unless they go through the kernel-mediated kg.write with a capability token. Return the full current contents of each touched store. Register it next to register_search_memory as ungated (reversible tier), withhold it from inbound/guest postures in tool_profiles, and update the snapshot. First red test, in tests/test_memory_write_tool.py: `memory` is in the registry. Then test that the target enum is narrowed when cognition memory is off, that a flagged op rejects the whole batch, that each applied op writes an audit row, and that remove undoes add.

## H350

**Skill authoring linter and validator** (skills) — missing, ~6 h.

Files: `agents/core/skills/validator.py`, `agents/core/skills/importer.py`, `agents/core/skills/marketplace.py`, `agents/core/skills/proposals.py`, `agents/core/skills/loader.py`, `scripts/skill_lint.py`, `tests/test_skill_validator.py`

Plan: Add agents/core/skills/validator.py with validate_skill_md(text, *, expected_name=None) -> list[Issue(field, code, message, severity)]. Hard errors: missing or unclosed '---' fence; YAML error or non-mapping; missing name; a name that fails importer._safe_slug or differs from expected_name; missing description; a description over 1024 chars or with line breaks; empty body; text over 256 KiB. The heading dialect gets its own branch requiring '# name' and '> description', or switch generate_skill to frontmatter output. Add lint_skill_md(text) for advisory warnings: no usage/'When to use' section, description over 200 chars, missing version, undocumented commands. Wire the hard validator, before any disk write, into: SkillImporter._save_skill and _import_local_skill (return False / status 'rejected', reason 'invalid_skill_md'); SkillMarketplace.publish_skill and install_from_zip (raise ValueError carrying the issues); SkillProposalStore.apply (refuse and mark rejected before writing rec['proposed']); SkillLoader.generate_skill (validate the rendered text before mkdir). Add scripts/skill_lint.py <path...> that prints issues and exits non-zero on errors. Red-first tests in tests/test_skill_validator.py: a broken-fence SKILL.md passed to _save_skill returns False and leaves the tree untouched (today it writes and then loads as name=<dir>, description=''); an approved proposal with an empty description is refused; install_from_zip with a nameless frontmatter raises; the pinned Hermes fixture in tests/test_hermes_import.py still validates.

## H441

**Getting back into a conversation: continue, resume, and a free recap** (memory) — partial, ~6 h. Critic notes: [3](#critic-note-3), [4](#critic-note-4).

Files: `agents/core/session_recap.py`, `agents/core/routers/sessions.py`, `agents/core/commands.py`, `agents/core/memory/conversation.py`, `frontend/src/gap.tsx`, `mobile/src/components/SessionsModal.tsx`, `tests/test_session_recap.py`, `frontend/src/test/sessions-panel-recap.test.tsx`

Plan: 1. Add agents/core/session_recap.py with render_recap(turns, max_exchanges=10, max_chars=280). It is a pure function with no LLM or router import. It pairs user and assistant turns, keeps the last N exchanges, truncates each side, and collapses tool calls to '[k tool calls: a, b]' when the assistant turn carries a 'tools' list. Persist that list by adding an optional tools field to Turn and to_dict in agents/core/memory/conversation.py, filled from the tool-loop trace. 2. Return {recap: render_recap(history)} alongside turns from resume_session in agents/core/routers/sessions.py. 3. Register SlashCommand('recap', ...) in build_default_registry. It renders the current session (ctx.orch.session_id) from orch.memory.get_history, so it works on Telegram, Slack and Discord through the existing command plane. 4. In frontend/src/gap.tsx SessionsPanel, show the returned recap after resume and add a recap button. Show the recap in the mobile SessionsModal. 5. Tests. Red first in tests/test_session_recap.py: '/recap' dispatch currently returns None/unknown, and the resume response lacks 'recap'. Then assert exchange bounding, truncation and tool collapsing. Assert that no LLM is called by monkeypatching the router's generate to raise. Add a vitest test for the HUD panel.

## H501

**Warn about a dangerous deployment posture before it becomes an incident** (security) — partial, ~6 h.

Files: `agents/core/host_posture.py`, `agents/core/boot_guards.py`, `agents/core/routers/security.py`, `scripts/doctor.py`, `frontend/src/gap.tsx`, `tests/test_host_posture.py`, `tests/test_doctor.py`

Plan: 1. Create agents/core/host_posture.py with pure, injectable functions: - `running_as_root(geteuid=os.geteuid)`, which reuses host_probe._process_elevated for Windows; - `sshd_password_auth(root=Path('/etc/ssh'))`: parse sshd_config line by line, expand `Include` globs relative to /etc/ssh in place, apply sshd's first-obtained-value-wins rule outside Match blocks, and return True, False or None, where None means unreadable. A missing directive means True, the sshd default; - `ephemeral_data_root(data_root, mountinfo=Path('/proc/self/mountinfo'), markers=...)`: in a container, find the longest mount point prefixing data_root. If it is the overlay root (mount point '/'), the data root is ephemeral. 2. Add `host_posture_report()` returning {root, ssh_password_auth, ephemeral_data_root, warnings[]}. 3. Call it once from the web lifespan next to enforce_boot_posture, and log each warning with the Hermes-style consequence text. It never raises and never blocks. 4. Add a `host` section to /api/security/posture. 5. Add doctor checks that report WARN or FAIL-with-reason without failing the install gate, and show the warnings on the HUD security page. Red-first tests with a tmp /etc/ssh tree: - a PasswordAuthentication no line in a .d fragment included before the main file's yes resolves per sshd precedence; - an absent directive resolves to True; - a fake mountinfo with only an overlay '/' plus /.dockerenv flags ephemeral, and one with a bind mount covering data_root does not; - geteuid=0 produces a warning; - the posture JSON contains the host section.

## H504

**Fail loudly when TLS trust is misconfigured instead of silently not verifying** (security) — partial, ~6 h.

Files: `agents/core/tls_trust.py`, `agents/core/http_client.py`, `agents/core/llm/egress.py`, `agents/core/boot_guards.py`, `agents/core/llm/providers/__init__.py`, `docs/FLAGS.md`, `tests/test_tls_trust.py`, `tests/test_plugin_egress.py`, `tests/test_llm_egress_ledger.py`

Plan: 1. Create agents/core/tls_trust.py. - Move tls_verify here; http_client re-exports it for compatibility. - Add `validate_ca_environment(environ=None, certifi_where=...) -> list[Problem]`. For each of JARVIS_CA_BUNDLE, SSL_CERT_FILE, REQUESTS_CA_BUNDLE and CURL_CA_BUNDLE, check that it exists and is a file, that ssl.create_default_context(cafile=...) loads it, and that len(ctx.get_ca_certs()) >= 1, tolerating NotImplementedError. For SSL_CERT_DIR, check that it is a directory. For certifi, also require at least 1024 bytes. Each Problem carries the variable name and a repair string such as `unset SSL_CERT_FILE` or `export JARVIS_CA_BUNDLE=/path/to/corp-root.pem`. - Name the variable that actually supplied the value in the warning. - Add `verify_for(target_id, base_url)`. It returns tls_verify() unless an explicit per-target setting (e.g. JARVIS_TLS_INSECURE_TARGETS, a comma list of provider ids or hosts) names this target. In that case it returns False and logs WARNING 'TLS verification DISABLED for <base_url> (<target>)' once per client. 2. Call validate_ca_environment from the lifespan. A set-but-broken variable raises SystemExit with the repair lines, matching Hermes' fail-loudly behaviour. 3. In llm_async_client, default trust_env=False and pass verify=verify_for(backend, kwargs.get('base_url')) unless the caller passes verify or a transport. 4. Update docs/FLAGS.md. Red-first tests: - validate_ca_environment with SSL_CERT_FILE pointing at a missing file, and at a file with zero PEM certs, returns a Problem naming SSL_CERT_FILE; - llm_async_client('anthropic') with JARVIS_CA_BUNDLE set to a self-signed CA gets an SSLContext that includes it; - verify_for with the target listed returns False and emits a WARNING containing the URL; - a bad CA path never yields False.

## H512

**See who authenticated, who failed, and when** (security) — partial, ~6 h.

Files: `agents/core/security/types.py`, `agents/core/security/auth_audit.py`, `agents/web.py`, `agents/core/security/token_store.py`, `agents/core/routers/admin.py`, `tests/test_auth_audit_events.py`

Plan: 1) agents/core/security/types.py: add SecurityEventType members AUTH_SUCCESS, AUTH_FAILURE, TOKEN_ISSUED, TOKEN_ROTATED and TOKEN_REVOKED. 2) New agents/core/security/auth_audit.py with record_auth_event(kind, *, tier, outcome, reason, client, token=None, **meta). It builds a dict and drops _REDACTED_FIELDS = {token, access_token, refresh_token, x-admin-token, x-user-token, authorization, cookie, code, code_verifier, state, ticket} before it serialises anything. The token itself is represented only as sha256(token)[:8]. It writes through the orchestrator AuditLogger (or an injected sink) under a lock, wraps everything in try/except and logs a WARNING on failure; it never raises. Successes are deduplicated per (tier, token-hash, client) in a bounded TTL map. 3) agents/web.py: in _admin_guard and _user_guard, call it on every 401/403 branch (reasons: missing, invalid, network_disabled) and on success. 4) agents/core/security/token_store.py: emit TOKEN_ISSUED/TOKEN_ROTATED/TOKEN_REVOKED from issue/rotate/revoke_all (so the CLI is covered), with scope, label and count and never the raw token. 5) Switch admin_rotate_tokens to TOKEN_ROTATED. Red-first tests in tests/test_auth_audit_events.py: a wrong X-Admin-Token from a network client yields an AUTH_FAILURE row whose content/findings never contain the supplied token; a sink that raises still yields 401 (not 500) and a valid token still passes; rotate/revoke via the CLI _main writes TOKEN_ROTATED/TOKEN_REVOKED; verify_chain stays True after the auth rows. The first test to go red: AuditLogger.query(event_type='auth_failure') is empty after a failed _admin_guard call.

## H526

**Make a spoken reply sound like speech rather than read-out markdown** (media) — partial, ~6 h.

Files: `agents/core/voice/speech_text.py`, `agents/core/voice/tts.py`, `agents/core/channels/spoken_reply.py`, `agents/core/routers/voice.py`, `frontend/src/sentences.ts`, `frontend/src/voice.ts`, `tests/test_speech_text_normalize.py`, `tests/test_spoken_reply.py`, `frontend/src/test/voice-stream-speak.test.tsx`

Plan: 1. Create agents/core/voice/speech_text.py with normalize_for_speech(text, lang='ro'). Move speakable()'s cleaning there and extend it: - drop fenced code, including an unclosed fence to end of text - apply channels/render.to_plain - strip leading list markers (-, *, +, 1.) and heading hashes - drop table separator rows and turn cell pipes into commas - remove emoji (Unicode So/Sk and variation selectors / ZWJ) - remove <think>...</think> and an unclosed <think> to end - replace URLs with 'link' without consuming a trailing ')' (e.g. r'https?://[^\s)]+') - expand & % -> → ° + = per lang (ro: și/la sută/spre; en: and/percent/to) - fold newlines - leave the twelve Fish [emotion] tags untouched. 2. Call it at the top of TTSEngine.speak() in agents/core/voice/tts.py, before the Fish branch. That covers /tts, /tts/stream, VoicePipeline, VoiceChannel.send and SpokenReply. Have speakable() delegate to it and keep only the length cap. 3. In frontend/src/sentences.ts SentenceAggregator (used by voice.ts pushSpeakDelta), suppress text inside an open ``` fence so code streamed across deltas is never enqueued. The first red test is new tests/test_speech_text_normalize.py: POST /tts via TestClient with a stub TTSEngine recording its text, body '## Plan\n- **one** 😀 & 50%'. The recorded text must contain no '#', '*', leading '-' or emoji, and must contain 'și'/'la sută'. Add a vitest case in frontend/src/test/voice-stream-speak.test.tsx: a fenced block pushed as deltas produces no /tts call.

## H696

**A small default skill bundle with a large on-demand catalog, re-pinned to the current release** (delta) — partial, ~6 h. Critic notes: [21](#critic-note-21), [25](#critic-note-25).

Files: `agents/core/skills/hermes_pin_v1.json`, `agents/core/skills/importer.py`, `frontend/src/panels/skills-import.tsx`, `tests/test_hermes_import.py`, `tests/test_hermes_pin_doc_consistency.py`, `docs/nerva2/EXECUTION_PROVIDER_E8_1A.md`, `docs/HERMES_ABSORPTION.md`

Plan: 1. Read upstream's current release tag (v2026.8.31 or newer) from the public GitHub API: tag → commit → tree. Record every SKILL.md under skills/ and optional-skills/ plus each skill's reference files with their content sha256, still excluding EXCLUDED_HERMES_SUBTREES. Download bytes only and execute nothing. 2. Write hermes_pin_v2.json (schema_version 2). Each entry gains 'tier': bundled|optional and an optional 'files': [{path, content_sha256}]. 3. Update the importer: - Update HERMES_PIN_RELEASE_TAG/COMMIT/TREE/PATH. - Extend _safe_pin_path to accept 'optional-skills' as the root and reference paths under the skill directory. - Make import_from_hermes and sync fetch and digest-verify every listed file before any write, and write the references next to SKILL.md atomically. - Surface the tier in the skills-import panel. 4. Red tests first: - test_repository_hermes_pin_is_exact_release_inventory asserts the new tag, commit and tree, that 'github' and 'grill-me' are present, and that github-auth, plan, session-librarian and blogwatcher are absent. - A new pinned_hermes fixture test shows that importing 'github' writes SKILL.md plus its references with verified digests, and refuses before any write when one reference digest mismatches. 5. Update PIN_* constants, PIN_FILE_SHA256, and the docs that tests/test_hermes_pin_doc_consistency.py reads.

## H117

**Message batching and debounce (treat a burst as one turn)** (platforms) — missing, ~7 h. Critic notes: [1](#critic-note-1), [16](#critic-note-16).

Files: `agents/core/channels/burst.py`, `agents/core/channels/gateway.py`, `agents/core/channels/telegram.py`, `agents/core/settings_db.py`, `tests/test_gateway_burst_debounce.py`

Plan: 1. Add agents/core/channels/burst.py with a BurstCoalescer keyed on (channel, chat_id, sender). It buffers fragments for a sliding window (setting channels.burst_debounce_seconds, default 0.35) under a hard cap (1.0s, and a maximum fragment count and byte size), then releases one merged text joined with newlines. 2. Call it in Gateway.route before _inbound_meta and the handler, so taint and detect_injection run on the merged text. The absorbed fragments return None (no reply). Only the final caller gets the handler's answer. 3. Make Telegram's _poll_loop dispatch without blocking on each receive, so fragments from one getUpdates batch can coalesce. Group photos by media_group_id. 4. Tests. Red first: three route() calls within the window invoke the handler once with the merged text. Then: injection flags are computed on the merged text (a phrase split across two fragments is flagged); different chat_ids never merge; the hard cap flushes a long burst; observe_only messages are not merged into answered turns.

## H275

**Boot into a known-good state when customizations break the install** (env) — missing, ~7 h. Critic notes: [8](#critic-note-8), [24](#critic-note-24).

Files: `agents/core/safe_mode.py`, `agents/core/skills/loader.py`, `agents/web.py`, `agents/core/agent.py`, `agents/core/heartbeat.py`, `agents/core/plugin_manager.py`, `agents/core/routers/ops.py`, `serve.py`, `frontend/src/gap.tsx`, `docs/FLAGS.md`, `tests/test_safe_mode.py`

Plan: 1. Add agents/core/safe_mode.py with safe_mode_enabled(), which reads JARVIS_SAFE_MODE through env_config. 2. Consult it at each load site: - SkillLoader.discover loads only SKILLS_DIR (skip the user root and generated skills). - _load_mcp_config returns before load_from_config, and _save_mcp_config must refuse to persist while safe mode is on so the saved server list is not overwritten with an empty one. - soul_path_for skips both SOUL.local.md candidates, and the heartbeat overlay lookup does the same. - PluginManager.build / extension activation skips owner-activated extensions. 3. Add safe_mode: true to the /status and /readyz payloads and show a HUD banner. 4. Add a --safe-mode flag to serve.py that sets the env var before the app imports. 5. Red-first tests in tests/test_safe_mode.py: - With the flag set, a skill in the data-home skills dir is absent from discover(). - A settings-stored MCP server is not loaded and is still present in settings after boot. - soul_path_for returns the shipped SOUL.md even when SOUL.local.md exists. - PermissionGate/kernel/egress decisions for a fixed set of actions are identical with and without the flag.

## H328

**Conditional skill visibility (OS platform, runtime environment, channel, tool availability)** (skills) — missing, ~7 h. Critic notes: [23](#critic-note-23).

Files: `agents/core/skills/loader.py`, `agents/core/skills/visibility.py`, `agents/core/agent.py`, `tests/test_skill_visibility.py`

Plan: After H327, add agents/core/skills/visibility.py with readiness(skill, *, os_name) -> ('ready'|'unsupported', reason) for the platforms hard gate (sys.platform mapped to macos/linux/windows, plus a Termux escape) and offer_visible(skill, *, environment, surface, offered_tools) -> (bool, reason) for the soft gates. Environment detection covers docker (/.dockerenv), s6 and kanban. The surface comes from tool_profiles.classify_turn. Tool gating uses requires_toolsets/requires_tools (hide when absent) and fallback_for_* (hide when the premium tool IS offered). Call offer_visible and readiness in SkillLoader.prompt_catalog, with a new surface/offered_tools argument threaded from Agent.build_prompt, and log each hidden name at INFO. In parse_command/Skill.execute, refuse only the platforms gate, with the message 'unsupported on <os>'. Soft-hidden skills still execute when named explicitly. Expose readiness in Skill.to_dict and /skills. Red-first tests in tests/test_skill_visibility.py: a platforms:[macos] skill is absent from prompt_catalog on linux and its command refuses; an environments:[docker] skill is hidden outside docker but still executes when named; session_platforms:[telegram] is hidden on the operator surface; a fallback_for_tools:[web_search] skill is hidden when web_search is offered and shown when it is not. The first test to go red: the macOS skill is not in prompt_catalog() on linux.

## H334

**Importing skills from an upstream project at a verified pin** (skills) — partial, ~7 h. Critic notes: [25](#critic-note-25).

Files: `agents/core/routers/skills.py`, `agents/core/skills/importer.py`, `agents/core/skills/hermes_pin_v1.json`, `tests/test_skills_api.py`, `tests/test_hermes_import.py`, `tests/_snapshots/route_auth.json`

Plan: 1. agents/core/routers/skills.py skills_import: remove the app_state.dev_mode() check. Before any importer call, build a skill.install Action (reuse SKILL_INSTALL_CONTRACT_KIND and the _enforce_skill_contract pattern from agents/core/skills/marketplace.py; payload {action:'import', source, name, pinned, release_tag, commit}) and decide it through the bound Action Kernel. On DENY return 403. On ASK enqueue the approval and return 202 {status:'approval_required', task_id}, then run import_from_hermes only from the approved-task executor. There must be no GRANT path that skips the owner-approval floor. Refuse unpinned sources, or send them through the same gate with an explicit 'unpinned' class on the approval card. 2. agents/core/skills/importer.py: move the fetches in import_from_hermes, _sync_from_hermes and _import_from_github onto the SSRF-guarded PluginHTTPClient (agents/core/http_client.py). Keep follow_redirects=False and the URL-equality, digest and identity checks. 3. Regenerate agents/core/skills/hermes_pin_v1.json against upstream release v2026.8.31: new commit, tree and per-file content_sha256 for the allowlist, still excluding the Anthropic-terms subtrees. Update PIN_* in tests/test_hermes_import.py and any doc that calls v2026.8.27 current. Red-first: replace tests/test_skills_api.py::test_skills_import_blocked_without_dev_mode with a test that, with DEV_MODE=False, the route returns approval_required and the importer is not called before approval. Add a test that a kernel DENY makes no network call and leaves the skills tree untouched. Update test_repository_hermes_pin_is_exact_release_inventory to the v2026.8.31 constants.

## H380

**Prove a configured cloud provider actually works** (providers) — missing, ~7 h. Critic notes: [26](#critic-note-26).

Files: `agents/core/llm/provider_probe.py`, `agents/core/llm/providers/__init__.py`, `agents/core/routers/models_llm.py`, `frontend/src/gap.tsx`, `scripts/doctor.py`, `tests/test_provider_probe.py`

Plan: 1. Create agents/core/llm/provider_probe.py with `async probe_provider(profile, *, client=None, now=...)`. Use a client built by llm_async_client(f"probe:{profile.id}", timeout=10, follow_redirects=False, trust_env=False) and a real User-Agent. Map profile ids to endpoints: anthropic GET https://api.anthropic.com/v1/models with x-api-key and anthropic-version headers; gemini GET v1beta/models with the x-goog-api-key header, never in the query string; openrouter, openai-compatible, openai-responses and xai GET {base}/models with a Bearer token. Add a `supports_health_check` field to ProviderProfile so local and unsupported profiles are skipped. Return {id, state: ok|auth_failed|forbidden|rate_limited|unreachable|error|not_configured, http_status, model_count, checked_at}. The result carries no key and no body text. Use `fallback_models` when the listing is unsupported. Keep a module-level TTL cache (about 10 min) and a per-provider asyncio.Lock with a minimum interval, so concurrent callers share one request. 2. Add admin routes: GET /api/llm/providers (catalog plus cached probe state) and POST /api/llm/providers/{id}/probe (forced, rate-limited). Follow the jarvis-add-route skill and regenerate the schema. 3. Add a 'Test key' control per provider in the HUD model panel. 4. Optionally add a `providers` check to scripts/doctor.py that reads the route. 5. Write tests with httpx.MockTransport. These go red first: a 401 must yield auth_failed; the serialized result must not contain the key string or a body canary; a second call inside the TTL must make no second request; the probe must create an `llm:probe:*` row in EGRESS_MONITOR; an unconfigured profile must return not_configured without any request.

## H450

**Say when in plain words (schedule syntax)** (automation) — partial, ~7 h. Critic notes: [15](#critic-note-15).

Owner gate: none

Files: `agents/core/autonomy/nl_schedule.py`, `agents/core/autonomy/jobs.py`, `agents/core/routers/jobs.py`, `frontend/src/panels/jobs.tsx`, `tests/test_h10_27_nl_schedule.py`, `tests/test_owner_jobs.py`

Plan: Extend resolve_schedule in agents/core/autonomy/jobs.py so it returns a typed schedule {kind: cron|once, cron|run_at, description}, checking families in a fixed order. (a) `every <N><m|h|d>` and bare `<N><m|h>`: recurring interval, still subject to the 5-minute floor. (b) EN/RO natural phrases, as nl_schedule does today. (c) Raw five-field cron. (d) ISO date/datetime: a naive value is anchored to JobRunner.scheduler_timezone(), a past instant is refused, and the result is a one-shot. (e) `in <N> <unit>`: a one-shot at now+delta. Make nl_schedule refuse any text containing a date or `tomorrow` instead of dropping it into the bare-time→daily branch. Add a `run_at` column to the jobs table with a migration. Register one-shots with APScheduler's 'date' trigger in JobRunner.register, make tick() fire a due one-shot exactly once via claim_tick, and have Job.runnable return false after it fires. Add normalize_repeat(value) in validate_options that maps 'forever'/None→null, 'once'/'1x'→1 and digits→int, as the single chokepoint. Show run_at in the HUD jobs list. Red-first test in tests/test_h10_27_nl_schedule.py: resolve_schedule('in 30m') returns kind 'once' (currently raises), and resolve_schedule('2026-10-01 09:00') does not return '0 9 * * *'. Add store/tick tests in tests/test_owner_jobs.py covering a one-shot firing once and a naive timestamp anchored to the scheduler zone.

## H659

**A retried external request returns the original run instead of starting a second one** (delta) — missing, ~7 h. Critic notes: [7](#critic-note-7), [27](#critic-note-27).

Files: `agents/core/idempotency.py`, `agents/core/routers/actions.py`, `agents/core/routers/webhooks.py`, `agents/core/routers/a2a.py`, `agents/core/a2a.py`, `tests/test_idempotency.py`

Plan: 1) New agents/core/idempotency.py with IdempotencyStore(sqlite at data_path('idempotency.db'), WAL). Table idempotency(scope TEXT, key TEXT, fingerprint TEXT, status TEXT, result_ref TEXT, created_at REAL, PRIMARY KEY(scope,key)). reserve(scope, key, fingerprint) runs inside BEGIN IMMEDIATE and returns ('new', None), ('replay', row) or ('conflict', row) on a fingerprint mismatch. complete(scope, key, status, result_ref); a TTL prune; a `durable` property that is True only for file-backed storage. The fingerprint is the sha256 of method, path and canonical body. Store no bodies. 2) validate_key(): ^[\x21-\x7e]{1,255}$, otherwise 400 {'error':'invalid_idempotency_key'}. 3) Wire into POST /api/actions/request (scope 'actions:'+principal), POST /api/webhooks/{hook_id} (scope 'webhook:'+hook_id, after auth and before mark_called/handle_input) and POST /api/a2a/task (scope 'a2a:'+peer_id, after the signature check and before the inbox append). A replay returns the stored action id / inbox id / response summary with 200 and never calls q.request, handle_input or receive_task again; a conflict returns 409/422. 4) Red-first test in tests/test_idempotency.py: two POST /api/actions/request calls with the same Idempotency-Key produce one pending action and the same id. It fails today with two. Add tests for invalid keys (400), scope isolation between two webhooks, and survival across a store reopen.

## H674

**Compression cannot stall the user: bounded holds, inactivity deadlines and derived thresholds** (delta) — partial, ~7 h. Critic notes: [11](#critic-note-11), [13](#critic-note-13).

Files: `agents/core/orchestrator.py`, `agents/core/context_compressor.py`, `agents/core/settings_db.py`, `agents/core/llm/base.py`, `tests/test_compression_timing.py`

Plan: Add settings memory.compression_max_turn_hold_seconds (default 10) and memory.compression_inactivity_seconds (default 60) in settings_db.py. In _compression_summarizer, use the backend's streaming generate (on_token) wrapped in an inactivity watchdog that resets on every token and raises TimeoutError after the inactivity window with no tokens, so compress() falls back to the digest. In ContextCompressor.compress, or in _history_for_prompt around compressor.compact, wait on the summarizer task with asyncio.wait_for(asyncio.shield(task), hold). On expiry use _fallback_digest for this turn, append a runtime notice ('context summary deferred'), and attach a done-callback that stores the eventual summary in _ctx_summary_cache[sid] only. Do not call commit_clock for the deferred summary. The first red test in tests/test_compression_timing.py: an orchestrator stub with compression_summarizer=True and a never-returning backend.generate must return from _history_for_prompt within hold+0.5s with a digest (it hangs today). Also add: a summarizer yielding a token every 0.2s for 2s with inactivity=0.5s is kept; a silent one is cut at 0.5s.

## H677

**Boot warm-up before accepting work, and every shutdown wait has a short explicit budget** (delta) — partial, ~7 h. Critic notes: [1](#critic-note-1), [11](#critic-note-11), [16](#critic-note-16).

Files: `agents/web.py`, `agents/core/orchestrator.py`, `agents/core/channels/manager.py`, `agents/core/channels/telegram.py`, `agents/core/routers/status.py`, `agents/core/settings_db.py`, `tests/test_boot_warmup_gate.py`, `tests/test_shutdown_budgets.py`

Plan: In agents/web.py lifespan, after `await orch.load_agents()` and before `await orch.start_channels()`, add: if orch._warmup_task: try await asyncio.wait_for(asyncio.shield(orch._warmup_task), timeout=get_value('agent','startup_warmup_timeout',20)) except TimeoutError: log the timeout and keep going. Set orch.warmup_state to 'ready' or 'warming' and surface it in the status route. Tag replies with a 'served_while_warming' flag while the task is not done. In ChannelManager.stop_all, wrap each ch.stop() in asyncio.wait_for(..., channel_stop_budget) and log overruns. In Orchestrator._cancel_task, wrap `await task` in asyncio.wait_for(asyncio.shield(task), interrupt_grace default 1.5s). Wrap plugin_manager.close_all and each aclose step in the same way. Lower the lease wait for channel turns from Telegram, or dispatch Telegram updates per chat in tasks. The first red test in tests/test_boot_warmup_gate.py: a TestClient lifespan whose router.warm_up sleeps 0.3s must see warm-up done before the first request is served (it fails today). Also add: warm_up sleeping 10s with timeout=0.2 lets startup finish in under 1s. In tests/test_shutdown_budgets.py: a channel whose stop() never returns does not keep lifespan teardown past the budget.

## H156

**Edit an agent's persona and description from the UI** (web) — partial, ~8 h.

Files: `agents/core/routers/agents_api.py`, `agents/core/routers/admin.py`, `agents/core/soul_versioning.py`, `agents/core/agent.py`, `frontend/src/modes.tsx`, `frontend/src/gap.tsx`, `tests/test_soul_edit_route.py`, `tests/_snapshots/route_surface.json`, `tests/_snapshots/route_auth.json`, `tests/_snapshots/openapi_surface.json`, `frontend/src/api/schema.gen.ts`

Plan: Edit route: add `PUT /api/admin/agents/{agent_id}/soul` {content, message} (admin_guard). Resolve the agent directory by enumeration, as the GET does. Run `_scan_soul_body` and answer 422 if the content is blocked. Seed SoulVersionStore with the current on-disk SOUL as v1 when its history is empty, then commit. Write the file atomically to user_souls_dir()/<id>/SOUL.local.md (or the repo-local SOUL.local.md when there is no data home). Call `_load_soul()` on orch.agents[id] so the next turn uses the new persona. Emit a SecurityEvent with agent id, version and hash, never the content. Rollback: `/api/admin/prompts/{id}/rollback` must go through the same apply path. Description: add a `description` front-matter field, and `POST /api/admin/agents/{id}/description/draft`, which asks the router for a one-paragraph description and returns it as a proposal without saving it. Saving goes through the PUT. UI: add an Edit button in the Dossier (frontend/src/modes.tsx) that loads the live SOUL into the PromptsPanel editor, with Preview then Apply. Regenerate the route snapshots and schema.gen.ts. First red test: tests/test_soul_edit_route.py. After a PUT, GET /api/agents/{id}/soul returns the new text and the agent's system prompt contains it. Blocked content gets 422 and changes nothing. An audit row is written. A rollback rewrites the file.

## H161

**Warn when the box is running out of memory or disk** (web) — partial, ~8 h.

Files: `agents/core/resource_pressure.py`, `agents/core/routers/status.py`, `agents/core/autonomy/observer.py`, `frontend/src/pressure-banner.tsx`, `frontend/src/app.tsx`, `frontend/src/api/schema.gen.ts`, `tests/test_resource_pressure.py`, `tests/_snapshots/route_surface.json`, `tests/_snapshots/route_auth.json`, `tests/_snapshots/openapi_surface.json`, `frontend/src/test/pressure-banner.test.tsx`

Plan: 1. Add agents/core/resource_pressure.py with a pure classify(sample, state) that returns ranked conditions in Hermes order: disk_critical > memory_critical > oom_restart_suspected > disk_elevated > memory_elevated. Reuse observer.DEFAULT_THRESHOLDS and probe the data-dir volume as well as '/'. 2. Read the boot id from /proc/sys/kernel/random/boot_id, falling back to psutil.boot_time(). Persist a small atomic state file under the data dir holding the last sample, the boot id and a clean-shutdown marker. Flag oom_restart_suspected when the process starts on the same boot id without a clean-shutdown marker after a sample with elevated/critical memory. 3. Clear a condition only after N consecutive samples below the elevated threshold minus a margin (confirmed recovery). 4. Expose GET /api/system/pressure (user_guard, nocache) returning {boot_id, conditions, worst} and POST /api/system/pressure/dismiss {condition, boot_id}. Store dismissals keyed by (condition, boot_id) so a new boot re-arms them, and do not block on autonomy.mode or ESTOP. 5. Add frontend/src/pressure-banner.tsx: poll the route, show only the worst undismissed condition with a dismiss control, and mount it in app.tsx beside ActionFailureBanner. 6. Tests to write red-first: tests/test_resource_pressure.py for ranking/worst-only, a dismissal re-arming on a new boot id, a flapping sample not clearing, and the OOM-restart suspicion after an unclean restart; route snapshot updates; frontend/src/test/pressure-banner.test.tsx for worst-only rendering and dismiss.

## H168

**Shared UI primitives the pages lean on (markdown, destructive-action confirmation, schema-driven fields)** (web) — partial, ~8 h.

Files: `frontend/src/markdown.tsx`, `frontend/src/cockpit.tsx`, `frontend/src/shell.tsx`, `frontend/src/artifacts.tsx`, `frontend/src/confirm.tsx`, `frontend/src/panel-kit.tsx`, `frontend/src/gap.tsx`, `frontend/src/modes3.tsx`, `frontend/src/panels/trust-ops.tsx`, `frontend/src/panels/marketplace-admin.tsx`, `frontend/src/test/markdown.test.tsx`, `frontend/src/test/confirm.test.tsx`, `frontend/src/test/kill-switch-refusal.test.tsx`

Plan: 1. Add frontend/src/markdown.tsx exporting <Markdown text/>. Use a line-based block parser (headings, bullet and ordered lists, ``` fences as <pre><code>, pipe tables as <table>, paragraphs) and an inline tokenizer (bold, italic, inline code, [label](url)). Emit React elements only; anything unrecognised stays as a text node. Render links only for http(s) or same-origin paths, with target=_blank rel='noopener noreferrer'. 2. Replace renderRich in cockpit.tsx (both bubble sites) and shell.tsx, and MarkdownBody in artifacts.tsx, keeping artifacts' 4,000-char bound. 3. Add frontend/src/confirm.tsx exporting <ConfirmAction tier={RiskTier} phrase? onConfirm/>. Tiers 0-1 take a two-step click; tiers 2-3 take a typed phrase with the confirm button disabled until it matches. Export the tier constants mirroring agents/core/autonomy/policy.py RiskTier. 4. Migrate KillSwitchPanel (HALT ALL two-step, disengage typed), forget-me, acquisition purge, marketplace remove, trust-ops rotate and the modes3 ESTOP pause onto it. 5. Tests to write red-first: frontend/src/test/markdown.test.tsx (a list, fence and table render as ul/pre/table; '<script>', '<iframe>' and 'javascript:' links stay inert text; no dangerouslySetInnerHTML in the source); frontend/src/test/confirm.test.tsx (a tier-3 action does not fire until the phrase matches, and a tier-1 action needs two clicks); update kill-switch-refusal.test.tsx so HALT ALL requires the second click.

## H209

**Keyboard shortcut customisation with a recorder and conflict detection** (desktop) — missing, ~8 h.

Files: `frontend/src/keybinds.ts`, `frontend/src/panels/keyboard-shortcuts.tsx`, `frontend/src/app.tsx`, `frontend/src/shell.tsx`, `frontend/src/test/keybinds.test.ts`, `frontend/src/test/keyboard-shortcuts-panel.test.tsx`, `frontend/src/test/app-routing.test.tsx`

Plan: Create frontend/src/keybinds.ts, exporting: an ACTIONS registry of {id:'nav.cockpit'…'nav.comms','palette.toggle','ambient.open','cinema.open','console.toggle','cinema.orb','cinema.mesh','cinema.brain','shortcuts.open', category, label, defaultChord}; eventToChord(e), which normalises mod (meta or ctrl); loadOverrides/saveOverrides, with localStorage wrapped in try/catch; resolveBindings(overrides), returning chord→actionId plus a conflicts map; and setBinding(id, chord), which throws on an unknown id. The registry holds no approval/decision action, and setBinding refuses any id whose category is 'approval'. Refactor app.tsx onKey and the shell.tsx Cinema effect to look up eventToChord(e) in resolveBindings() and dispatch by action id; keep the input/textarea and role=log bail-outs. Add panels/keyboard-shortcuts.tsx: a modal opened by mod+/ with category sections and a search box. Clicking a row enters record mode ('Press a key…'): the next keydown sets the binding and Esc cancels. Add a reset button per row, reset-all, and an 'Also bound to <label>' note when conflicts are non-empty. Red-first tests: keybinds.test.ts asserts that rebinding nav.memory from '4' to 'g' makes 'g' switch to memory and '4' no-op, that conflict detection works, and that an approval id is refused. Then a panel test for the recorder and reset. Keep app-routing.test.tsx green.

## H227

**"What can it do right now" inspector: live status line plus a session panel of tools, skills, resolved system prompt and MCP servers** (tui) — partial, ~8 h.

Files: `agents/core/inspector.py`, `agents/core/routers/status.py`, `agents/cli/nerva.py`, `frontend/src/panels/inspector.tsx`, `frontend/src/console-routes.ts`, `tests/test_inspector.py`, `tests/test_nerva_cli.py`, `frontend/src/panels/inspector.test.tsx`, `tests/_snapshots/route_auth.json`

Plan: Add agents/core/inspector.py with build_inspector(orch, agent_id, surface, principal). It returns a dict with these sections. status: version, backend, model/state from project_llm_status, and context budget from llm.tool_loop_context_tokens. tools: the ToolProfileResolver.resolve result for this agent, surface and principal, each entry with gated/untrusted_output. skills: prompt_catalog(agent_id) rows plus a count by skill. mcp: MCPManager servers with transport, trust tier, connected flag and visible tool count. system_prompt: the text Agent.build_prompt would send for an empty user turn, including the frozen core block, the skills block and _runtime_state_block, with secrets redacted and capped at 64 KB. Serve it at GET /api/admin/inspector?agent=jarvis (admin_guard; record it in the route_auth snapshot). Add a `nerva inspect [--section tools|skills|prompt|mcp] [--json]` verb that renders those sections read-only from the same payload, and a HUD InspectorPanel that reads the same route with collapsible sections. First red test, in tests/test_inspector.py: the payload's tools equal ToolProfileResolver's set for a guest principal, not the raw registry. Then test that system_prompt contains the skills block and core-memory header, and that tests/test_nerva_cli.py inspect output matches the --json payload.

## H247

**Wake word arming per surface, push-to-talk capture, TTS, and liveness/config primitives** (tui) — partial, ~8 h.

Files: `agents/core/voice/mic_arbiter.py`, `agents/core/voice/pipeline.py`, `agents/core/channels/voice.py`, `agents/core/routers/voice.py`, `agents/core/settings_db.py`, `frontend/src/voice.ts`, `tests/test_mic_arbiter.py`, `frontend/src/test/voice.test.tsx`, `tests/_snapshots/route_surface.json`, `tests/_snapshots/route_auth.json`, `tests/_snapshots/openapi_surface.json`, `frontend/src/api/schema.gen.ts`

Plan: Arbiter: add agents/core/voice/mic_arbiter.py, a process-wide MicArbiter with arm(surface, client_id), pause(surface), resume(surface), stop(surface) and status() -> {holder, since, armed:[...]}. A second surface arming while another holds the mic is refused and told who the holder is; there is no silent preemption. Routes: add `POST /api/voice/wake/{arm,pause,resume,stop}` and `GET /api/voice/wake/status` (user_guard) to agents/core/routers/voice.py. Consent and audit: arm requires a new capture-consent setting (`voice.mic_capture_consent`, default off, in settings_db). Every arm and stop writes a SecurityEvent with surface and action, never audio. Host pipeline: VoicePipeline/VoiceChannel.start takes the 'host' lease before opening the device and releases it on stop/pause. Browser: frontend/src/voice.ts calls arm when hands-free/PTT starts and stop on release, and shows 'mic held by <surface>' when refused. Regenerate the route snapshots and schema.gen.ts. First red test: tests/test_mic_arbiter.py. While the host holds the mic, a hud arm gets 409 naming 'host'. Once host pauses, the hud arm succeeds. Without consent, arm is refused. Each arm/stop leaves an audit row. Add a vitest for the refusal path in voice.ts.

## H259

**Reset to defaults, scoped and previewed, plus export/import of the whole configuration** (config) — partial, ~8 h. Critic notes: [6](#critic-note-6), [28](#critic-note-28).

Files: `agents/core/settings_db.py`, `agents/core/routers/admin.py`, `frontend/src/gap.tsx`, `tests/test_admin_settings_mutations.py`

Plan: 1) In settings_db add defaults(category=None), built from DEFAULTS, and reset_category(cat), which rewrites only that category's rows to their defaults. 2) Add GET /api/admin/settings/defaults returning {category: {key: default}}. Add POST /api/admin/settings/reset/preview {category}, returning [{key, current, default}] for differing keys with secret values masked. Change POST /api/admin/settings/reset {category|'all'} (and re-route /reseed) so it enqueues a 'settings.reset' task at the irreversible/ask tier through the autonomy worker, and apply reset_category only when the approved task executes. /reseed must stop calling init_db(force=True) directly. 3) Add GET /api/admin/settings/export, returning non-secret values as JSON with secret-kind keys omitted or redacted. Add POST /api/admin/settings/import/preview, which runs validate_category per category and returns the diff without writing; the HUD loads it into the dirty form state and the existing PUT saves it. 4) In the HUD SettingsPanel add changed-vs-default markers, a per-category 'reset to defaults' that only edits the form (like Hermes), and export/import buttons. Red-first test: set a value, POST /api/admin/settings/reseed, and assert the value survives until the queued reset is approved. It fails today because the wipe is immediate.

## H262

**Config-driven data lifecycle — prune, archive, vacuum on an interval-gated sweep** (config) — partial, ~8 h. Critic notes: [5](#critic-note-5), [14](#critic-note-14), [28](#critic-note-28).

Files: `agents/core/retention.py`, `agents/core/security/audit.py`, `agents/core/scheduler_service.py`, `agents/core/settings_db.py`, `agents/core/routers/admin.py`, `tests/test_retention.py`

Plan: 1) Add settings retention.archive_days (0 = off), retention.vacuum_after_prune (True), retention.min_vacuum_interval_days (30) and retention.min_interval_hours (24). 2) In run_retention, first read a persisted marker, written atomically under a file lock (e.g. data_path('retention_state.json') holding last_run and last_vacuum). Skip with {'skipped': 'interval'} when the last run is younger than min_interval_hours, and record last_run afterwards. 3) Archive tier: transcripts past archive_days move to data_root/'archive'/'sessions' (restorable through a restore helper and route). Pinned sessions are exempt (add a pin marker file or list). Only archived items past conversation_ttl_days are deleted. 4) VACUUM: when prune_before deleted rows and vacuum_after_prune is on, and last_vacuum is older than min_vacuum_interval_days, run VACUUM on the audit connection outside the transaction and record last_vacuum. 5) Route retention-category PUTs that enable the sweep or shorten a TTL through the approval queue's irreversible tier, not an immediate write. Red-first tests in tests/test_retention.py: (a) after pruning a large audit table, the audit DB file size decreases (fails today, no VACUUM); (b) a second run_retention inside min_interval_hours is skipped; (c) an archived transcript can be restored before its TTL deletes it.

## H309

**Show the user where something is, in their UI** (tools — the agent-callable surface) — missing, ~8 h. Critic notes: [22](#critic-note-22).

Files: `agents/core/canvas.py`, `agents/core/autonomy_coordinator.py`, `frontend/src/hud-pointer.tsx`, `frontend/src/app.tsx`, `frontend/src/test/hud-pointer.test.tsx`, `tests/test_h12_18_canvas.py`

Plan: agents/core/canvas.py: add a 'tip' element type {target: anchor id matching ^[a-z0-9][a-z0-9._-]{0,63}$, title at most 80 chars and text at most 200 chars, both through _s} and a 'tour' type {steps: at most 12 of {target, title, text}}, and add both to ALLOWED_TYPES. Register an ungated read-only ToolRPC tool 'ui_point' (args: target, text, title?, steps?) in agents/core/autonomy_coordinator.py next to the other read-only tools. It posts through orch.canvas.post(agent, 'tip'|'tour', payload) and returns the element id; add it to the default tool profile. Frontend: put data-hud-anchor attributes on the main panels and settings controls. Add a HudPointerOverlay component (frontend/src/hud-pointer.tsx), mounted in app.tsx, that reads /api/canvas. It shows the newest undismissed tip as an arrow bubble anchored to document.querySelector('[data-hud-anchor="<target>"]') and pages tour steps with Next/Prev; an unresolved anchor falls back to a toast showing the caption. No screen dimming. Red-first: in tests/test_h12_18_canvas.py, post('tip') with script-bearing text comes back sanitised and a malformed target is rejected (today both fail with 'unknown element type'); a tool test asserts 'ui_point' is offered to the model and posts exactly one element; the vitest frontend/src/test/hud-pointer.test.tsx renders the bubble next to a stub anchor and pages a two-step tour.

## H373

**See how much provider quota is left before hitting the wall** (providers) — missing, ~8 h. Critic notes: [26](#critic-note-26).

Files: `agents/core/llm/rate_limit_tracker.py`, `agents/core/llm/egress.py`, `agents/core/llm/hybrid_router.py`, `agents/core/routers/models_llm.py`, `agents/core/commands.py`, `frontend/src/gap.tsx`, `tests/test_provider_rate_limit_tracker.py`, `tests/_snapshots/route_surface.json`, `tests/_snapshots/route_auth.json`, `tests/_snapshots/openapi_surface.json`

Plan: 1. Add agents/core/llm/rate_limit_tracker.py. It parses OpenAI, OpenRouter and xAI x-ratelimit-{limit,remaining,reset}-{requests,tokens}, Anthropic anthropic-ratelimit-{requests,tokens,input-tokens,output-tokens}-{limit,remaining,reset}, and retry-after into a per-(provider, profile) snapshot. 2. Feed the tracker from an httpx response event hook added in llm_async_client, so every backend reports without per-backend code. 3. Persist a 429 with its retry-after to an atomic shared file under the data dir. HybridRouter._cloud_permitted and the backend request path check that file before sending, which stops retry amplification across processes. 4. Expose admin GET /api/llm/rate-limits and a /usage slash command, and show usage bars in the HUD LLM status panel. 5. Tests, red first: a MockTransport response carrying ratelimit headers yields a snapshot with remaining and reset; a 429 with retry-after written by one router instance makes a second instance refuse before any request.

## H378

**Be warned before choosing a model that is very expensive or trains on your data** (providers) — partial, ~8 h. Critic notes: [9](#critic-note-9).

Files: `agents/core/llm/selection_guards.py`, `agents/core/llm/providers/__init__.py`, `agents/core/routers/admin.py`, `agents/cli/nerva.py`, `agents/core/llm/job_selection.py`, `frontend/src/gap.tsx`, `tests/test_model_selection_guards.py`

Plan: 1. Add a data_policy field ('no-training' | 'trains-on-inputs' | 'unknown') to ProviderProfile, with an optional per-model override, sourced from the vendors' published terms (e.g. OpenRouter ':free' variants and the free Gemini tier). 2. Add agents/core/llm/selection_guards.py with a registry of guards run once per selection, returning ok, confirm_required or ack_required with details: - cost_guard reads cost_estimator.MODELS and requires confirm_expensive above a $/M threshold setting. - data_policy_guard requires acknowledge_training for trains-on-inputs and writes a SecurityEvent consent row to orch.audit. 3. Call the registry server-side in admin_put_category for llm model and provider keys before put_category (409 with guard details), in agents/cli/nerva.py settings set, and in job_selection.validate_pins. 4. Add a confirm dialog to the HUD settings. 5. Tests, red first in tests/test_model_selection_guards.py: PUT llm.claude_model=claude-fable-5 without confirmation currently returns 200 and must return 409; with confirmation it returns 200. A trains-on model without acknowledgement gets 409; with acknowledgement there is an audit consent row.

## H410

**Universal secret redaction on every log record** (agent-core) — partial, ~8 h. Critic notes: [32](#critic-note-32).

Files: `scripts/coordinator.py`, `scripts/nerva_mcp_stdio.py`, `agents/core/security/scanner.py`, `agents/core/security/log_redaction.py`, `tests/test_log_redaction.py`

Plan: (1) In scripts/coordinator.py main() and scripts/nerva_mcp_stdio.py main(), call agents.core.log.setup_logging(level) in place of the bare basicConfig; in nerva_mcp_stdio, keep the stderr stream and format, and call install_log_redaction_everywhere() after basicConfig. (2) Add a sensitive-key catalogue pattern to SecretScanner covering unquoted values of at least 8 characters after query, form or JSON keys (access_token, refresh_token, id_token, token, client_secret, api_key, apikey, secret, signature, sig, password), plus headers X-Api-Key, X-Auth-Token and Authorization: Token/Basic. Mask only the value, and update _BUILTIN_MIN_MATCH_LEN if needed (test_shortest_builtin_match_is_not_below_length_floor pins it). (3) In SecretRedactionFilter.redact_text, also run the checksum-validated ro_cnp and ro_iban from PIIScanner. Red-first tests in tests/test_log_redaction.py: a handler-level record 'GET /cb?access_token=abcdef1234567890' is emitted masked; a record containing a checksum-valid CNP is masked; importing scripts/coordinator.main with basicConfig patched leaves the root handler carrying a SecretRedactionFilter.

## H427

**Fail-closed pre-compression checkpoint — never discard a transcript unless the extraction durably landed** (memory) — missing, ~8 h. Critic notes: [13](#critic-note-13).

Files: `agents/core/context_compressor.py`, `agents/core/orchestrator.py`, `agents/core/memory/episodes.py`, `tests/test_compaction_checkpoint.py`

Plan: 1. In agents/core/context_compressor.py, define a CheckpointProvider protocol: async checkpoint(evicted_turns, *, session_id, api_version) -> receipt dict with a durable id. Add a CHECKPOINT_API_VERSION constant and new compact() kwargs: checkpoints=(), require_checkpoint=False, audit=None. 2. On the summarize tier, compute the older slice with the same keep_first/keep_recent bounds compress() will use. Call each provider before compress(). 3. If require_checkpoint is set and any provider raises or none returns a receipt: return {'compressed': False, 'kept': rows, 'tier': 'checkpoint_refused', ...} and emit audit('compaction.checkpoint_failed', session_id, evicted count, sha256 of evicted text, error class). 4. On success, emit 'compaction.checkpoint_ok' with the receipt ids. 5. In Orchestrator._history_for_prompt (agents/core/orchestrator.py), pass a provider that synchronously writes an episode/LivingMemory record for the evicted turns, plus require_checkpoint from a new setting memory.compression_checkpoint_required (default False). The audit sink is security/audit. If a refused compaction leaves the prompt over the hard window, raise the existing clock-refusal-style reply instead of sending an over-window prompt. The first red test is new tests/test_compaction_checkpoint.py: a required provider that raises makes compact() return compressed False with the original turns and exactly one checkpoint_failed audit row. A succeeding provider receives exactly the evicted turns before the summarizer stub is called.

## H464

**Park a run on real async work instead of poking it** (automation) — partial, ~8 h.

Owner gate: none

Files: `agents/core/autonomy/work_runs.py`, `agents/core/autonomy/schedule_runtime.py`, `agents/core/autonomy/company_supervisor.py`, `agents/core/autonomy/work_judge.py`, `tests/test_schedule_runtime.py`, `tests/test_company_supervisor.py`, `tests/test_work_run_ledger.py`

Plan: 1. Add a nullable `barrier` JSON column to the runs table in work_runs.py: {kind: pid|trigger|deadline, target, set_at}. Add WorkRunLedger.set_barrier(run_id, kind, target) and clear_barrier(run_id), each logged as a zero-budget step or event. 2. Add barrier_active(run), which clears the barrier itself when it is stale: the pid no longer exists (os.kill(pid, 0) raises ProcessLookupError), the trigger id has fired (injected predicate), or now ≥ deadline. 3. In ScheduleRuntime.due, return a new 'waiting' skip reason before the budget check while barrier_active(run) is true. Add 'waiting' to SKIP_REASONS. 4. In CompanySupervisor.tick, return TickResult('waiting', ...) before _plan_next and before _grade, so no step, budget or judge call is spent. 5. Let the planner return Action(kind='wait', barrier=…), which sets the barrier instead of enqueueing. Let the judge return a `wait` outcome that does the same. Include the run's registered background pids in the judge's input. 6. Red-first test in tests/test_schedule_runtime.py: a run with barrier {kind: deadline, target: now+600} reports 'waiting' and is not ticked. It currently has no barrier concept and is ticked. 7. Also test that a dead pid clears on the next sweep, that the supervisor spends no budget and makes no judge call while waiting, and that an elapsed deadline resumes the run.

## H507

**Warn the model when the code it just wrote contains a known-dangerous pattern** (security) — missing, ~8 h.

Files: `agents/core/security/code_guidance.py`, `agents/core/file_tools.py`, `agents/core/skills/marketplace.py`, `agents/core/skills/loader.py`, `docs/FLAGS.md`, `tests/test_code_guidance.py`, `tests/test_file_tools_code_guidance.py`

Plan: 1) New agents/core/security/code_guidance.py: a frozen tuple of Rule(id, category, regex, extensions, message) with about 25 rules as in the Hermes row. Include per-extension filters (.py/.js/.ts/.go/.yml under .github/workflows/, .html) and lookbehind guards so `model.eval()` / `.eval(` method calls and `yaml.load(..., Loader=SafeLoader)` do not match. Add scan(path, content) -> list[Finding] with bounded output (cap findings and chars), and render_guidance(findings) -> short string. Env kill switch JARVIS_CODE_GUIDANCE (default on, warn-only; no blocking mode). 2) FileTools.classify_mutation: when the path/content matches, add labels `security_guidance` (bounded string, within ToolRPC _MAX_LABEL_CHARS) and extend/merge `notice` so the owner's approval card title says it. The function must stay a pure function of the args so the H506 intake/execute label match still holds, and it must merge with instruction_labels instead of overwriting `class`. 3) FileTools._mutate success result: add `security_guidance` (list of {rule, line, message}) so the model sees it in the tool result. 4) Run the same scan over SKILL.md/main.py in SkillMarketplace.install_skill/install_from_zip and SkillLoader.generate_skill, and include the findings in their results and the review/approve payloads. 5) Document the flag in docs/FLAGS.md. Red-first tests: tests/test_code_guidance.py (each rule positive and negative, `model.eval()` negative, extension filter) and tests/test_file_tools_code_guidance.py (write_file of `pickle.load(f)` returns security_guidance; classify_mutation returns a security_guidance label; a SOUL.md write keeps class=agent_instructions; kill switch off yields no key). The first test to go red: assert 'security_guidance' in (await ft.write_file({...pickle.load...}, approved=True)).

## H613

**Choose how it sounds and how it hears (TTS / STT provider matrix)** (docs-features) — partial, ~8 h.

Files: `agents/core/voice/tts.py`, `agents/core/voice/stt.py`, `agents/core/settings_db.py`, `tests/test_tts_piper_command.py (new)`

Plan: 1) agents/core/voice/tts.py: add `_speak_piper(text, voice)` for `piper:<model>` voices, or a voice.piper_model setting. Use the piper Python package when it imports, otherwise the `piper` binary through asyncio.create_subprocess_exec: argv list, text on stdin, --output_file under TEMP_DIR, 30 s timeout. On failure, fall back to _safe_default_voice. When voice.local_only is set, try Piper before edge. 2) Command providers: add admin-only settings voice.tts_command and voice.stt_command, each a JSON argv template with {text_file}, {output}, {audio} and {lang} placeholders. Run them without a shell, with a bounded timeout and output size, and confine the output path to TEMP_DIR. `command:` voices dispatch to the TTS command. STTEngine.transcribe uses the STT command when faster-whisper is absent or when voice.stt_engine=command. Leave the consent gate unchanged: piper and command voices are not persona markers, and xtts/elevenlabs/fish stay gated. 3) Tests in tests/test_tts_piper_command.py use fake executables in tmp_path. The first red test is test_piper_voice_invokes_piper_argv. Then cover: command TTS and STT happy paths; timeout and non-zero exit falling back; text never interpolated into a shell; consent still blocking xtts without owner consent.

## H681

**Per-child API settings for delegated subagents, and a batch report that names the real reason they all failed** (delta) — partial, ~8 h.

Files: `agents/core/subagents.py`, `agents/core/autonomy_coordinator.py`, `agents/core/routers/mesh.py`, `agents/core/orchestrator.py`, `agents/core/settings_db.py`, `tests/test_subagent_request_overrides.py`, `tests/test_subagent_batch_failure.py`

Plan: Extend SubAgentManager.spawn(..., model=None, provider=None, overrides=None). Record them on the spawn record and pass them to runners that accept a `selection` kwarg (the same additive contract as blocked/steer). Add model/provider/overrides fields, validated with job_selection.validate_pins, to SubAgentSpawnBody. Add settings autonomy.subagent_model and autonomy.subagent_provider. In _subagent_runner, resolve explicit, then setting, then none, and run orch.process inside selection_scope({...}). Give process a variant, or a sibling method, that returns (text, error) so the runner can raise SubAgentProviderError(error) on '' or a degraded reply; the manager then records failed with {'error': 'provider_failed', 'detail': ...}. Add spawn_batch(tasks, ...) and a POST /api/subagents/batch route. After gather, if every child failed and each detail matches /model.*(not found|does not exist|unknown)/i AND contains the configured subagent model name, return a single notice {'kind': 'subagent_model_rejected', 'model': ..., 'setting': 'autonomy.subagent_model', 'fallback': bool}. The first red test in tests/test_subagent_request_overrides.py: spawn('t', model='m1') must reach the runner with current_selection().model == 'm1' (TypeError today). In tests/test_subagent_batch_failure.py: a runner returning '' gives status failed; a batch in which all errors are "model 'foo' not found" with configured foo yields one notice; errors naming 'bar' yield none.

## H689

**One stable identity for this install, and per-profile isolation of its runtime artifacts** (delta) — missing, ~8 h.

Files: `agents/core/install_identity.py`, `agents/core/paths.py`, `agents/core/first_action.py`, `agents/core/node_mesh.py`, `agents/core/satellite_hub.py`, `agents/core/channels/pairing.py`, `agents/core/environments/__init__.py`, `agents/web.py`, `tests/test_install_identity.py`, `tests/test_node_mesh_h12_17.py`

Plan: 1. New module agents/core/install_identity.py with get_install_id() -> str | None, backed by data_root()/install_id (exactly 32 lowercase hex characters). - Mint only if the file is absent: take an exclusive lock on data_root()/install_id.lock (fcntl.flock on POSIX; msvcrt.locking on Windows after a 1-byte pre-write; plus a module threading.Lock), then re-check inside the lock. - Write secrets.token_hex(16) via tempfile.mkstemp in the same directory, fsync, os.replace, fsync the directory on POSIX, then re-read and compare. - Return None, and log, when the file is unreadable or malformed or cannot be persisted. Never overwrite a malformed file and never return an unpersisted value. 2. Wire the consumers: - node_mesh.register_node records the hub install id in each registration and in the grant's source/scope. - satellite_hub pairings and channels/pairing.py link records carry it. - first_action.mark_installed takes its install_id from get_install_id() instead of uuid4. 3. Isolation: at web lifespan start, take an exclusive hub lock and PID file under data_root(). Refuse a second hub on the same root with a named error, and detect a stale PID. Either implement JARVIS_PROFILE as data_root()/profiles/<name> (data, token store/vault, PID) or drop it from JARVIS_CHILD_ALLOWED_ENV. 4. Red tests first, in tests/test_install_identity.py: - Two multiprocessing workers minting concurrently get the same id. - A read-only directory returns None and leaves no file. - A corrupted file returns None, not a new id. - The id is stable across calls and restarts. - A second hub-lock acquisition on the same root fails. - first_action reuses the stored id.

## H277

**Separate models for separate jobs (vision, video, approval judging)** (env) — partial, ~9 h.

Files: `agents/core/llm/model_roles.py`, `agents/core/llm/vlm.py`, `agents/core/llm/model_config.py`, `agents/core/autonomy/action_approvals.py`, `agents/core/settings_db.py`, `frontend/src/gap.tsx`, `docs/FLAGS.md`, `tests/test_model_roles.py`, `tests/test_action_approval_judge.py`

Plan: 1. Add agents/core/llm/model_roles.py with a frozen ROLES table (main, deep, vision, video, approval_judge). Each role resolves {provider_id, model, base_url} from JARVIS_ROLE_<NAME>_PROVIDER/_MODEL/_BASE_URL and falls back to the existing JARVIS_VLM_* / JARVIS_DEEP_MODEL names, so current installs behave the same. provider_id is validated against the ProviderProfile ids in agents/core/llm/providers. 2. Route resolve_vlm_config and deep_model_name through it. 3. Add an optional judge step, invoked from ActionApprovalQueue.request (or its caller), that runs only when approval_judge is configured. It asks the judge model for a risk score and a one-line rationale and stores {score, rationale, judge:{provider, model}} on the item. The same judge identity goes into the audit row for that action. The judge never changes status. 4. Show the score on the HUD approval card. 5. Red-first tests: - tests/test_model_roles.py: the vision role falls back to JARVIS_VLM_MODEL; an unknown provider is rejected. - tests/test_action_approval_judge.py: a configured fake judge annotates the item with its model id and the audit entry carries it; an unconfigured judge leaves the item byte-identical; a judge that answers 'approve' does not change the pending status.

## H487

**Ask a human on whatever surface they are on, carry their reason back, and fail closed on silence** (security) — partial, ~9 h. Critic notes: [27](#critic-note-27).

Files: `agents/core/autonomy/action_approvals.py`, `agents/core/autonomy/worker.py`, `agents/core/autonomy/queue.py`, `agents/core/routers/autonomy.py`, `agents/core/routers/actions.py`, `agents/core/autonomy/inbox.py`, `agents/core/autonomy_coordinator.py`, `agents/core/autonomy/pending_requests.py`, `agents/core/browser_agent.py`, `agents/cli/nerva.py`, `frontend/src/gap.tsx`, `tests/test_h10_18_action_approvals.py`, `tests/test_pending_requests.py`, `tests/test_approval_reason_coalesce.py`

Plan: (a) Reason: - Add `reason: Optional[str] = Field(None, max_length=280)` to AutonomyDecisionBody and a `reason` parameter to Worker.apply_decision. Strip control characters and store it in the task `result` as {"human_reason": ...}; the column already exists. - Add `reason=` to ActionApprovalQueue.decide and store item['reason']. Accept `reason` in the /api/actions/{id}/decide body and add `--reason` to `nerva approvals reject`. - Telegram: after a reject tap, accept the next text reply within a short window as the reason. - PendingRequests.classify puts the reason in the detail of the 'refused' step. BrowserAgent returns {'status':'denied','reason':'rejected','human_reason':...}. (b) Coalescing: - In ActionApprovalQueue.request, compute a fingerprint as sha256 of agent + tool + canonical JSON args. If a pending item has the same fingerprint, return it with `coalesced: true` and increment a waiters count. All awaiters share one Event. - For TaskQueue tasks, reuse execution_fingerprint to attach a duplicate blocked task to the leader instead of pushing a second card. Keep the mediation checks intact. (c) Expiry: - On await_decision timeout, set status='expired' under the lock only if the item is still pending, save, and return 'expired'. decide() must refuse to change an expired item. Add stats['expired']. - Tool, browser and run-step results must say 'expired_unanswered', not 'rejected'. Red-first tests: rejecting with reason 'use the staging address' must show that exact text in the browser step result and in the PendingRequests refused-step detail; two identical request() calls must yield one pending item; a timed-out item must be 'expired', and a later decide(approved=True) must leave it expired.

## H513

**Restrict a capability to the surface it belongs on, and let the owner acknowledge a data-handling tradeoff without silencing the warning** (security) — partial, ~9 h. Critic notes: [9](#critic-note-9).

Owner gate: Owner confirms the default tier assigned to each cloud provider/plan from provider terms; code can ship with 'unknown' (treated as warn) where unsure.

Files: `agents/core/llm/providers/__init__.py`, `agents/core/llm/hybrid_router.py`, `agents/core/routers/security.py`, `agents/core/settings_db.py`, `frontend/src/gap.tsx`, `frontend/src/test/governance-posture-panel.test.tsx`, `tests/test_data_handling_tier.py`, `tests/_snapshots/route_auth.json`, `tests/_snapshots/route_surface.json`, `docs/FLAGS.md`

Plan: 1) Add a `data_handling: str = 'unknown'` field to ProviderProfile ('local', 'no_training', 'may_train', 'unknown'); set local for the local profiles and conservative defaults for cloud ones. The compatible-endpoint config can override it through a setting. 2) In HybridRouter.select_backend, when the route starts with 'cloud', look up the profile tier. For may_train/unknown, log a WARNING and record a posture counter every time. On internal/unattended surfaces (tool_profiles SURFACE_INTERNAL / no principal), refuse or downgrade to local unless settings `security.data_training_ack` contains the provider id. The acknowledgement never suppresses the warning. 3) Add POST /api/security/data-handling/ack {provider, acknowledged} behind admin_guard. It writes the settings list and an audit row (SETTINGS_CHANGE); update the route snapshots. 4) Extend GET /api/security/posture with `data_handling: [{provider, tier, acknowledged, last_used}]`, and render it in PosturePanel with the warning still visible when acknowledged. Red-first tests in tests/test_data_handling_tier.py: select_backend on a may_train cloud route emits the warning with and without ack; an unattended turn with no ack is refused or routed local; the ack route rejects a non-admin; the posture JSON carries tiers. A vitest in governance-posture-panel.test.tsx asserts the row renders. The first test to go red: 'data_handling' in security_posture() output.

## H114

**Per-channel personality, skills and verbosity** (platforms) — partial, ~10 h. Critic notes: [17](#critic-note-17), [18](#critic-note-18), [29](#critic-note-29).

Files: `agents/core/channels/descriptor.py`, `agents/core/channels/display_tier.py`, `agents/core/orchestrator.py`, `agents/core/settings_db.py`, `agents/core/channels/ntfy.py`, `agents/core/channels/telegram.py`, `tests/test_channel_display_tier.py`, `tests/test_channel_prompt_hint.py`

Plan: 1. Add a `permanent: bool` field and a `platform_hint` property to ChannelDescriptor. Derive the hint from the dialect and length cap, e.g. plain gives 'This channel shows plain text only; do not use markdown. Keep replies under N characters.' 2. Add agents/core/channels/display_tier.py with resolve_tier(descriptor). It maps supports_edit, permanent and max_message_length to tiers LOW, MEDIUM or HIGH that control streaming, tool-progress, interim and heartbeat messages. Use it in _begin_channel_draft instead of the bare supports_edit check. 3. Inject the hint, plus an operator-set per-channel prompt, into the system prompt assembled for a channel turn in handle_input/handle_input_stream. Store the prompt in the new settings row channels.prompts (JSON {channel or channel:chat_id: text}), written only through the admin_guard settings PUT. 4. Add a channels.skill_bindings setting ({channel:chat_id: skill}) that the channel turn applies. 5. Tests. Red first: a Telegram turn's system prompt contains no platform hint; ntfy resolves to LOW and Telegram to HIGH. Also assert that an inbound message cannot change channels.prompts.

## H174

**Uninstall from inside the app, with a pre-flight summary of exactly what goes** (desktop) — partial, ~10 h. Critic notes: [28](#critic-note-28).

Files: `agents/core/uninstall.py`, `agents/core/routers/uninstall.py`, `agents/core/kernel/registry.py`, `uninstall.sh`, `UNINSTALL.bat`, `frontend/src/gap.tsx`, `frontend/src/api/schema.gen.ts`, `tests/test_uninstall.py`, `tests/test_uninstall_routes.py`, `frontend/src/test/uninstall-panel.test.tsx`

Plan: 1. agents/core/uninstall.py: - Add uninstall_summary(root). It is side-effect free and returns plan_uninstall targets with sizes, plus the data root path, whether it exists, its size and whether a backup-first purge is possible. - Add a `--gui-summary` CLI flag that prints it as JSON without needing --confirm and touches nothing. 2. Routes (new admin-guarded router; follow the jarvis-add-route skill and update the route parity snapshot): - GET /api/admin/uninstall/summary. - POST /api/admin/uninstall with body {mode: 'software'|'software+data', confirm: 'UNINSTALL'}. 3. Kernel gate: register 'system.uninstall' as Mediation.KERNEL in agents/core/kernel/registry.py at the irreversible tier. The POST creates an approval-queue item and removes nothing. Only the approved task's execution spawns a detached cleanup. 4. Detached cleanup: uninstall.sh / UNINSTALL.bat gain a `--wait-pid <pid>` mode that polls until the hub PID exits, then runs `python -m agents.core.uninstall --confirm [--purge-data]` from a system interpreter. 5. HUD: a Danger-zone section beside BackupPanel's FORGET in frontend/src/gap.tsx. It fetches the summary, lists only targets that exist, offers the two modes, and enables the button only after UNINSTALL is typed. 6. Red tests first: - tests/test_uninstall.py: `--gui-summary` reports existing and absent targets and leaves every target on disk. - tests/test_uninstall_routes.py: the summary route is admin-only; a POST without the typed confirmation is 400; a confirmed POST returns a pending approval and nothing is removed; approving it invokes a fake detach launcher with the hub PID and the right mode. - Frontend test: the button stays disabled until UNINSTALL is typed, and absent targets are not offered.

## H220

**Usage and cost accounting surface** (desktop) — partial, ~10 h. Critic notes: [10](#critic-note-10).

Files: `agents/core/cost_tracker.py`, `agents/core/routers/admin.py`, `agents/core/orchestrator.py`, `agents/web.py`, `frontend/src/panels/usage.tsx`, `frontend/src/panels/usage.test.tsx`, `frontend/src/gap.tsx`, `frontend/src/console-routes.ts`, `frontend/src/cockpit.tsx`, `tests/test_h10_16_apm.py`

Plan: Backend: extend apm_summary with by_locality = {local, cloud, unknown}, each {runs, input_tokens, output_tokens, cost_usd, unpriced_calls}. Classify from the per-(agent, model) tally using the LLM router's knowledge of local model ids (not a substring match; unknown ids go to 'unknown'). Red-first test in tests/test_h10_16_apm.py: record one local and one cloud call and assert that the by_locality split and the totals agree. Frontend: fix APMPanel to read d.totals (red-first vitest: the current panel renders '—' for a real apm_summary payload). Add panels/usage.tsx (console id 'usage', group Observe) with totals, a local-vs-cloud spend/token bar, and by_agent and by_model tables with unpriced counts. Add a Usage row in CommandCenterPanel linking to it. Per-turn meter: have the orchestrator expose the last turn's routed model, input/output tokens and estimated cost. Add an optional `usage` field {input_tokens, output_tokens, context_used, context_max, context_percent, cost_usd|null, cost_basis} to ChatResponse, with context_max taken from the routed model's context window, and render a small context meter in the cockpit InputBar. Read-only; the budget stays in the call broker.

## H222

**Always-visible microphone / wake-word state indicator** (desktop) — missing, ~10 h. Critic notes: [31](#critic-note-31).

Owner gate: a visual check of the native always-on-top indicator window on a real desktop session (macOS/Windows/X11) is hardware-bound; code and unit tests are not

Files: `agents/core/voice/state.py`, `agents/core/voice/pipeline.py`, `agents/core/routers/voice.py`, `desktop/src-tauri/src/main.rs`, `desktop/src-tauri/src/policy.rs`, `desktop/src-tauri/hud-routes.json`, `frontend/src/indicator.tsx`, `frontend/src/test/indicator.test.tsx`, `tests/test_voice_state.py`, `tests/_snapshots/route_auth.json`

Plan: Add agents/core/voice/state.py with a VoiceStateBroker singleton: {state: idle|listening|wake_detected|capturing|speaking|muted, source: 'local'|'satellite:<id>', since}, plus subscribe(). Update it from VoicePipeline.start/stop/_on_wake_word/_capture_and_process, from TTS playback, and from satellite hub audio sessions; the JARVIS_MIC_MUTED env flag forces 'muted'. Expose GET /api/voice/state and an SSE stream at /api/voice/state/stream (user_guard), both read-only. Desktop: in main.rs setup(), build a small undecorated, always-on-top, non-focusable 'indicator' WebviewWindow loading the HUD route /indicator (add it to hud-routes.json and the policy.rs allow-list). Update the tray tooltip, e.g. 'Nerva — listening', from a Tauri command the indicator page calls on each state change, and add indicator_show/indicator_hide commands. Frontend: frontend/src/indicator.tsx renders a dot and label from the SSE stream, with no mic toggle. Red-first tests: tests/test_voice_state.py (pipeline start gives listening; the wake callback gives wake_detected; the env mute gives muted; the route returns the broker state); a Rust unit test in policy.rs allowing the indicator label/URL; a vitest for indicator rendering and read-only behaviour.

## H243

**Completions (filesystem paths, slash commands) and provider/model options (list, save key, disconnect)** (tui) — partial, ~10 h. Critic notes: [26](#critic-note-26).

Files: `agents/core/routers/models_llm.py`, `agents/core/llm/hybrid_router.py`, `agents/core/llm/auth_rotation.py`, `agents/core/secrets.py`, `frontend/src/gap.tsx`, `frontend/src/panels/quickbar.tsx`, `frontend/src/cockpit.tsx`, `tests/test_llm_providers_route.py`, `tests/_snapshots/route_surface.json`, `tests/_snapshots/route_auth.json`, `tests/_snapshots/openapi_surface.json`, `frontend/src/api/schema.gen.ts`

Plan: Provider list: add `GET /api/admin/llm/providers` (admin_guard) in agents/core/routers/models_llm.py. Return one entry per cloud provider HybridRouter knows (anthropic, gemini, openai, openrouter) with: a configured flag, the masked key count from its pool, the key source (env or store), and models with per-1M-token price hints from cost_tracker.MODEL_PRICES. Add a `local` group from `_list_local_models`. Save-key: add an `AuthProfilePool.from_keys(...)` constructor and make HybridRouter merge env keys with keys from SecretStore (agents/core/secrets.py). Add `POST /api/admin/llm/providers/{provider}/key`: it stores the key encrypted, rebuilds that provider's pool and returns the refreshed provider list. Disconnect: add `DELETE /api/admin/llm/providers/{provider}/key`, which removes the stored key and rebuilds the pool. A key that lives in the environment is reported as 'set in environment', not silently kept. Audit: both writes emit a SecurityEvent naming the provider only. UI: extend AuthProfilesPanel with a password input + Save and a Disconnect button per provider. Slash completion: typing '/' in the chat composer (frontend/src/cockpit.tsx) and in QuickbarPanel shows prefix matches from `/api/commands` with `usage` as the argument hint; Tab accepts. Regenerate the route snapshots and schema.gen.ts. First red test: tests/test_llm_providers_route.py. Saving a fake key makes the provider configured with pool size 1. Disconnect empties the pool. Both routes return 401 without admin, and both write an audit row that does not contain the key. Add a vitest that '/mem' completes to '/memory'.

## H329

**Turning individual skills off without uninstalling them** (skills) — missing, ~10 h. Critic notes: [23](#critic-note-23), [24](#critic-note-24).

Files: `agents/core/settings_db.py`, `agents/core/skills/loader.py`, `agents/core/routers/skills.py`, `agents/core/kernel/registry.py`, `frontend/src/gap.tsx`, `tests/test_skill_disable.py`, `tests/_snapshots/route_auth.json`, `tests/_snapshots/route_surface.json`, `tests/_snapshots/openapi_surface.json`

Plan: 1) Settings: add skills.disabled (JSON list) and skills.platform_disabled (JSON map from surface to list) in settings_db, plus an ESSENTIAL_SKILLS frozenset in loader. 2) SkillLoader: add is_disabled(name, surface=None). prompt_catalog skips disabled skills and logs the name. parse_command/Skill.execute return a named refusal ('skill <name> is disabled') instead of running. Skill.to_dict and GET /skills carry `disabled`. 3) Routes: POST /api/skills/{name}/disable {surface?} behind admin_guard makes a direct settings write plus a SETTINGS_CHANGE audit row, and refuses essential skills. POST /api/skills/{name}/enable submits a permission.grant Action to the kernel and applies the settings write only on GRANT or approved QUEUE, so the audit carries the approver. Support category toggles by matching metadata.hermes.category. Update the route snapshots. 4) HUD: a per-skill toggle and a category toggle in the skills panel in frontend/src/gap.tsx that calls these routes. 5) Nothing is deleted: the skill directory, usage store rows, signature and approval must be untouched. Red-first tests in tests/test_skill_disable.py: a disabled skill is absent from prompt_catalog and its command refuses; SKILL.sig, usage counters and the approval row are unchanged after disable→enable; enable crosses permission.grant (kernel stub sees kind permission.grant); an essential skill cannot be disabled; a platform_disabled entry for 'inbound' hides the skill only on that surface. The first test to go red: POST /api/skills/<name>/disable returns 404.

## H413

**Session auto-titling** (agent-core) — missing, ~10 h. Critic notes: [4](#critic-note-4).

Files: `agents/core/session_titles.py (new)`, `agents/core/checkpoint.py`, `agents/core/memory/manager.py`, `agents/core/orchestrator.py`, `frontend/src/gap.tsx`, `mobile/src/components/SessionsModal.tsx`, `tests/test_session_auto_title.py (new)`

Plan: Add agents/core/session_titles.py. instant_title(text) returns the first ~8 words with whitespace collapsed and control characters stripped, capped at 60 characters. Write it to sessions.summary (or a new title column with a migration) when the first user turn of a session is recorded, and only if empty. Schedule upgrade_title(session_id, first_turns) once per session (a metadata flag guards re-fire) on a background task. It picks a local backend only and refuses any cloud or openrouter backend, using the prompt 'Give this conversation a short title of at most 6 words. Do not answer it.' Accept a non-empty single line of at most 60 characters. Render s.summary || s.id in the HUD SESSIONS card (gap.tsx); mobile already renders summary. Red-first test (tests/test_session_auto_title.py): after the first handle_input on a fresh session, checkpoints.get_sessions()[0]['summary'] equals the first words. With a fake local backend the title is replaced once and never again. With only a cloud backend configured, the upgrade is skipped and the instant title remains.

## H425

**Destructive forget: retract a fact and everything derived from it** (memory) — partial, ~10 h. Critic notes: [28](#critic-note-28).

Files: `agents/core/memory/decay.py`, `agents/core/kernel/registry.py`, `agents/core/capability_manifests.py`, `agents/core/routers/memory_kg.py`, `frontend/src/gap.tsx`, `tests/test_memory_forget_governance.py`, `tests/test_h14_4_decay_forgetting.py`, `frontend/src/test/kg-panel.test.tsx`, `frontend/src/test/memory-hygiene-panel.test.tsx`

Plan: 1. Add DecayMemory.forget_preview(item_id) -> list[str] in agents/core/memory/decay.py: the same walk as forget(), with no deletion. 2. Register 'memory.forget': Mediation.KERNEL in agents/core/kernel/registry.py and correct the :73 comment. Add an action manifest in agents/core/capability_manifests.py (irreversible risk, no rollback). 3. In memory_decay_forget (agents/core/routers/memory_kg.py): - compute the preview (404 if empty) - cross make_action_kernel/authorize with Action(kind='memory.forget'), payload ids only; DENY returns 403 - otherwise enqueue an approval task on the irreversible QUEUE floor, following the terminal.exec/file.write pattern, carrying {item, dependents} - return 202 {pending: task_id, dependents: [...]}. 4. The approved-task executor calls decay.forget(item) and, for each removed id that LivingMemory holds, cognition memory.forget(id). It writes one audit row with the removed ids and counts. 5. KgPanel and MemoryHygienePanel render 'queued for approval · N dependents' from the 202. The first red test is new tests/test_memory_forget_governance.py: with the kernel enabled, POST /api/memory/decay/forget {id:'a'} where 'b' depends on 'a' returns 202, both items are still in DecayMemory, and the payload lists 'b'. Approving the task deletes both, calls LivingMemory.forget and emits exactly one audit row. Update test_decay_endpoints, which currently expects immediate deletion.

## H440

**Automatic session titles and continuation lineage** (memory) — partial, ~10 h. Critic notes: [4](#critic-note-4).

Files: `agents/core/checkpoint.py`, `agents/core/session_titles.py`, `agents/core/orchestrator.py`, `agents/core/session_continuation.py`, `agents/core/routers/sessions.py`, `frontend/src/gap.tsx`, `mobile/src/api/client.ts`, `mobile/src/components/SessionsModal.tsx`, `tests/test_session_titles.py`

Plan: 1. agents/core/checkpoint.py: add title TEXT and title_source TEXT ('derived'|'model'|'human') columns via an idempotent ALTER migration, like session_continuation.initialize. Add set_title(session_id, title, source) that refuses to overwrite source='human' unless the caller is 'human'. 2. New agents/core/session_titles.py: - derive_title(text): strip markdown/URLs/whitespace, at most 48 chars cut on a word boundary, '' for empty. - async upgrade_title(first_user_text, generate): strict-local backend. Input is capped at 1,000 chars. Ask for structured output with schema {type: object, properties: {title: {type: string, maxLength: 60}}, required: [title], additionalProperties: false} (Ollama format / OpenAI-compatible response_format json_schema). Validate by strict json parse and return None on any failure. 3. When the orchestrator records the first user turn of a session, call derive_title synchronously before the model call. After the first reply, schedule exactly one upgrade_title that writes source='model' only if the source is still 'derived'. 4. In ContinuationStore.create, set the child title to '<root title> #N', where N = 1 + the count of continuations sharing root_id. 5. Routes: GET /sessions returns title and omits sessions that have a newer continuation in the same lineage (or flags them hidden). POST /sessions/resume accepts {title} and resolves it to the newest lineage member. PATCH /sessions/{id}/title (user_guard) sets source='human'. 6. The HUD SessionsPanel in frontend/src/gap.tsx and mobile SessionsModal render the title. The first red test is new tests/test_session_titles.py: - after the first turn of a new session, with the LLM stubbed to hang, GET /sessions shows the derived title - a model upgrade never replaces a human title - continuing 'Trip plan' yields 'Trip plan #2', which is hidden from the list, and resume by 'Trip plan' lands on it.

## H490

**Start with zero customization to prove a bug is not your own setup** (security) — missing, ~10 h. Critic notes: [8](#critic-note-8).

Files: `agents/core/safe_mode.py`, `agents/core/env_config.py`, `agents/core/agent.py`, `agents/core/heartbeat.py`, `agents/core/file_tools.py`, `agents/core/orchestrator.py`, `agents/core/mcp/client.py`, `agents/core/routers/security.py`, `agents/serve.py`, `frontend/src/gap.tsx`, `docs/FLAGS.md`, `tests/test_safe_mode.py`

Plan: 1. Create agents/core/safe_mode.py with `safe_mode_enabled()`, which reads env_flag('JARVIS_SAFE_MODE'), and `SAFE_MODE_SKIPS`, a documented tuple of the extension points it disables. 2. Gate each extension point on safe_mode_enabled(): - soul_path_for and the heartbeat overlay use only the shipped template; - file_tools skips instruction-file and .local overlay injection; - the orchestrator skips SkillLoader.discover() of user and marketplace skills, plugin registration, MCPManager startup, hooks and webhooks, memory recall and WorldView context; - the runtime autonomy-level overrides from the settings DB are ignored in favour of the code defaults. The worker must use the stricter of the two, never looser. 3. Make the launch path accept `--safe-mode` by setting the env var before load_agents. 4. Log one boot WARNING and add `safe_mode: {enabled, skipped: [...]}` to GET /api/security/posture. Show a HUD banner. 5. Document it in docs/FLAGS.md. Red-first tests in tests/test_safe_mode.py: - with JARVIS_SAFE_MODE=1, a tmp SOUL.local.md is not used by soul_path_for; - a tmp skill dir yields zero discovered skills; - MCPManager.start is never called; - instruction files are not injected; - the posture payload reports enabled=True; - ANTHROPIC_API_KEY is still readable; - no autonomy level is looser than the default.

## H594

**Have the agent pick up a project's conventions automatically (context files)** (docs-features) — missing, ~10 h. Critic notes: [29](#critic-note-29).

Files: `agents/core/context_files.py (new)`, `agents/core/orchestrator.py`, `agents/core/file_tools.py (record touched directories)`, `agents/core/settings_db.py`, `tests/test_context_files.py (new)`

Plan: 1) New agents/core/context_files.py with `discover(cwd, scope: FileScope) -> list[ContextFile]`. Find the git root (the nearest ancestor with .git, clamped to the FileScope root) and walk root→cwd collecting AGENTS.md (plus its .local overlay, matching file_tools naming), .cursorrules and .cursor/rules/*.mdc. SOUL.md is never loaded. Resolve each file with FileScope.resolve. Cap each file at 16 KiB with a truncation marker and the total at 48 KiB, ordered with the nearest directory last. Run detect_injection on each file; a flagged file becomes `[BLOCKED context file <path>: <reason>]`. `render_project_context(files)` emits a header plus a caveat line, in the same way core_block does. 2) Orchestrator: add a `_project_context_block()` next to _living_core_memory_block, cached per (session, cwd, file mtimes). For progressive discovery, FileTools and terminal environments record the directories they touch, and the next turn includes those directories' AGENTS.md. When a non-empty block is injected, call mark_turn_recall_tainted(). 3) Add a cognition toggle project_context_files (default on) and list the loaded files in the turn's cognition trace. 4) Tests first in tests/test_context_files.py. The first red test is test_walks_git_root_to_cwd. Then cover: budgets and truncation; .mdc compatibility; SOUL.md ignored; an injection line blocked; outside-scope and symlink files refused; the taint mark set; a subdirectory discovered after a file-tool touch.

## H596

**Keep working when one API key is rate-limited (credential pools)** (docs-features) — partial, ~10 h. Critic notes: [26](#critic-note-26), [30](#critic-note-30).

Files: `agents/core/llm/auth_rotation.py`, `agents/core/llm/anthropic.py`, `agents/core/llm/gemini.py`, `agents/core/llm/hybrid_router.py`, `agents/core/secrets_vault.py`, `frontend/src/gap.tsx`, `tests/test_h12_20_auth_rotation.py`, `frontend/src/test/honesty-fix-panels.test.tsx`

Plan: 1) auth_rotation.py: make 402 rotatable and give report_failure `status` and optional `retry_after` parameters. A 402 gets a cooldown of max(3600 s, backoff). A 429 whose body says the plan or quota is exhausted rotates immediately with the long cooldown. A generic 429 retries once on the same key, then rotates. Update the anthropic.py and gemini.py call sites to pass the status and a short error-body classification. 2) OAuth: give AuthProfile an optional async `refresher`. On a 401, the backend calls it once, swaps the credential and retries before rotating. Refreshed tokens are stored in the SecretStore and never logged. 3) Vault: add `AuthProfilePool.from_sources(single, multi, provider, resolver)`, which resolves *_API_KEYS and *_API_KEY through VaultResolver/SecretStore first and the environment second. hybrid_router uses it in place of from_env, and keys go through log_safe. 4) AuthProfilesPanel renders `healthy/size` and per-profile cooldown. Fix the honesty-fix-panels fixture to the real {size, healthy:int, profiles} shape. Tests extend tests/test_h12_20_auth_rotation.py. The first red test is test_402_rotates_with_one_hour_cooldown. Then cover: refresher-then-rotate on 401; generic 429 retried once; plan-limit 429 rotated immediately; vault-first resolution with env fallback; no key text in logs. Add a frontend test that a partially cooled pool is not rendered green.

## H063

**Session reset policy and expiry/stall watchers** (gateway) — partial, ~12 h.

Files: `agents/core/channels/session_reset.py`, `agents/core/channels/session.py`, `agents/core/orchestrator.py`, `agents/core/scheduler_service.py`, `agents/core/settings_db.py`, `tests/test_session_reset_policy.py`, `tests/test_stall_watcher.py`

Plan: 1. Add agents/core/channels/session_reset.py with: - ResetPolicy(mode none|idle|daily|both, idle_minutes, daily_hour), resolved from settings keys sessions.reset_mode, sessions.idle_minutes and sessions.daily_hour, with per-type (dm/group/thread) and per-channel overrides. - should_reset(last_activity, now, policy). - A small persisted JSON store mapping each base key to {generation, last_activity}. 2. Extend build_session_key (or wrap it) to append a generation suffix, so a reset rotates to a new session id without deleting the old transcript. 3. In Orchestrator.channel_handler, before resume: - If the text matches sessions.reset_triggers (default '/new', '/reset'), bump the generation and return a short acknowledgement without running a turn. - Otherwise, if should_reset(...) is true, bump the generation before resuming. 4. Add a SchedulerService interval job (every 5 min) that applies the idle/daily policies and evicts stale _channel_sessions entries. 5. Stall watcher: record inbound_at when channel_handler receives a message and progress_at on the first token or at turn end. The same job notifies the owner exactly once per stalled message via the existing outbound notify path when now - inbound_at exceeds sessions.stall_seconds with no progress. 6. Red-first tests: - tests/test_session_reset_policy.py, using a fake clock: an idle reset rotates the key after idle_minutes; '/new' rotates the key and returns the acknowledgement; the daily reset fires at the boundary; a per-channel override wins. - tests/test_stall_watcher.py: a pending message older than the threshold yields exactly one notification; progress clears it.

## H204

**Capabilities hub — skills and toolsets management** (desktop) — partial, ~12 h. Critic notes: [24](#critic-note-24).

Files: `agents/core/permission_ledger.py`, `agents/core/skills/loader.py`, `agents/core/skills/usage.py`, `agents/core/routers/skills.py`, `frontend/src/panels/skill-grants.tsx`, `frontend/src/panels/skill-grants.test.tsx`, `frontend/src/console-routes.ts`, `frontend/src/gap.tsx`, `tests/test_skill_agent_grants.py`, `tests/_snapshots/route_auth.json`

Plan: Add a 'skill' surface to permission_ledger SURFACES with key '<agent>:<skill_name>', keyed by the loader/manifest name, not the folder. Enabling goes through ledger.request, which queues permission.grant and needs owner approval. Disabling is ledger.revoke or a 'never' row (narrowing, no approval). Enforce in SkillLoader.prompt_catalog(agent_id), where a skill disabled for the agent is not advertised, and in SkillLoader.execute via context['agent'], which refuses with 'skill_disabled_for_agent'. Admin-guarded routes in routers/skills.py: GET /api/skills/grants (matrix of skills x agents with state and last_used_at from usage.py); POST /api/skills/{name}/agents/{agent}/disable (plus agent '*' for the All switch); POST /api/skills/{name}/agents/{agent}/enable (returns the pending approval id); POST /api/skills/disable-unused {idle_days, dry_run}, which disables for all agents every skill whose latest_activity_at is older than idle_days and returns the list. Every mutation is audited. HUD: panels/skill-grants.tsx with the matrix, per-cell toggle, All switch, and a 'Disable unused' button that previews with dry_run before confirming; register it in console-routes.ts. Red-first tests in tests/test_skill_agent_grants.py: (a) a disabled skill is missing from prompt_catalog('jerome') but present for another agent; (b) execute refuses for the disabled agent; (c) enable creates a pending permission.grant and changes nothing until it is applied; (d) disable-unused with dry_run lists without changing anything, and without dry_run disables only idle skills. Regenerate the route_auth snapshot.

## H218

**Archived chats, auto-archive of stale chats, and a default project directory** (desktop) — missing, ~12 h. Critic notes: [4](#critic-note-4), [5](#critic-note-5), [28](#critic-note-28).

Files: `agents/core/checkpoint.py`, `agents/core/routers/sessions.py`, `agents/core/data_purge.py`, `agents/core/scheduler_service.py`, `agents/core/settings_db.py`, `frontend/src/gap.tsx`, `tests/test_session_archive.py`, `tests/_snapshots/route_auth.json`

Plan: Add a nullable archived_at column to the checkpoint sessions table, with an idempotent migration. Add CheckpointManager.set_archived(sid, archived: bool) and a get_sessions(limit, archived=False) filter. In routers/sessions.py add: POST /sessions/{sid}/archive and /sessions/{sid}/unarchive (user_guard, validated with is_valid_session_id, reversible, audited); GET /sessions?archived=1; and POST /sessions/{sid}/purge. The purge route enqueues an irreversible-bucket action and returns its approval id. Its executor calls a new data_purge.purge_session(sid, backup_first=True), which snapshots, verifies and then deletes that session's transcript and checkpoint rows. Settings in settings_db: sessions.auto_archive_days (0 = off) and sessions.default_project_dir (must exist and lie under an allowed file root). Add a daily scheduler_service job that archives sessions idle longer than auto_archive_days, and have jobs fall back to default_project_dir when no workdir is given. HUD: SessionsPanel gets an Archive button and an Archived tab with Unarchive and 'Delete permanently' (confirm, then approval). Red-first tests in tests/test_session_archive.py: an archived session is absent from GET /sessions and present with archived=1; unarchive restores it; purge creates a pending approval and deletes nothing until it is applied; the auto-archive job honours the setting and skips when it is 0.

## H461

**A standing instruction that re-enters this session on a cadence** (automation) — partial, ~12 h. Critic notes: [1](#critic-note-1), [2](#critic-note-2), [3](#critic-note-3), [15](#critic-note-15).

Owner gate: none

Files: `agents/core/commands.py`, `agents/core/session_heartbeat.py`, `agents/core/orchestrator.py`, `agents/core/scheduler_service.py`, `tests/test_session_heartbeat.py`

Plan: 1. Add agents/core/session_heartbeat.py with a SQLite/WAL store. Table: session_heartbeats(session_id PK, channel, chat_id, prompt ≤2000 chars, interval_s ≥ floor, paused, anchor_at, last_fired_at). Every store method catches DB errors and returns 'no heartbeat'. 2. Give CommandContext the calling session_id and channel/chat, and pass them from each channel's slash-command dispatch. 3. Register SlashCommand('heartbeat') in agents/core/commands.py. It takes `every <interval> <prompt>` (reuse the jobs interval parsing) or `pause|resume|clear|status`, at ADMIN tier. 4. Add a per-session in-flight marker in Orchestrator.process: a set of session_ids entered and exited in a finally block. 5. Add a sweep job every 60 s on the existing scheduler. For each due, unpaused heartbeat whose session is idle, CAS last_fired_at and anchor_at=now in one UPDATE before the turn runs (this also coalesces missed ticks). Then run orchestrator.process(prompt, session=that session_id, channel=origin) so the turn lands in that conversation's history. Deliver the reply to the originating chat through the channel adapter. Enforce the interrupt budget and night window as the jobs lane does. 6. Red-first test in tests/test_session_heartbeat.py: '/heartbeat every 10m check the build' currently returns an unknown-command reply. Then cover: a busy session is skipped; the fire is recorded before a slow turn, so no double fire; three missed ticks produce one fire; an interval below the floor is refused; and a store raising sqlite3.Error yields no heartbeat instead of an exception.

## H468

**Review as a state, not a block (request-review / request-changes / reopen)** (automation) — missing, ~12 h.

Owner gate: none (depends on row H466's board/claim model being chosen; row decision is already copy)

Files: `agents/core/autonomy/queue.py`, `agents/core/routers/autonomy.py`, `agents/cli/nerva.py`, `frontend/src/panels/autonomy-legacy.tsx`, `tests/test_autonomy_review_state.py`

Plan: This builds on the unit that row H466 settles on; if that is still the TaskQueue, extend queue.py. 1. Add TaskStatus.REVIEW with transitions RUNNING→REVIEW (request_review), REVIEW→APPROVED (request_changes back to the implementer) and REVIEW→DONE (reviewer accepts). Allow DONE→REVIEW only through reopen_review, a deliberate exception to terminal-no-reentry that is recorded as an event. Exclude REVIEW from blocked and ready counts. 2. Add nullable columns assignee, reviewer and handoff (JSON: summary, changed files, open questions), plus a task_events rows table for review events and comments. 3. Add request_review(task_id, reviewer=None, summary, handoff, force=False), request_changes(task_id, required_changes: list[str], by) and reopen_review(task_id, by). Each refuses to move a RUNNING task that holds a live claim unless force=True. 4. Expose them as admin routes under /api/autonomy/tasks/{id}/request-review|request-changes|reopen-review, `nerva tasks` CLI verbs, and HUD buttons. 5. Red-first test in tests/test_autonomy_review_state.py: queue.request_review(t) moves the task to 'review' and it is not counted as blocked. This currently fails with AttributeError. Also cover request_changes recording an event and a comment and returning the task to its implementer, reopen_review, and the force guard on a running task.

## H472

**Subscribe a chat to a work item's terminal events — including waking the agent** (automation) — partial, ~12 h. Critic notes: [2](#critic-note-2), [3](#critic-note-3).

Owner gate: none (live delivery uses channels the owner already configured; tests use fake adapters)

Files: `agents/core/autonomy/work_subscriptions.py`, `agents/core/autonomy/queue.py`, `agents/core/autonomy/worker.py`, `agents/core/autonomy/work_runs.py`, `agents/core/commands.py`, `agents/core/routers/autonomy.py`, `tests/test_work_subscriptions.py`

Plan: 1. Add agents/core/autonomy/work_subscriptions.py with a SQLite store. Table subscriptions(id, item_kind task|run|mission, item_id, platform, chat_id, thread_id, mode notify|notify+wake|wake, last_event_id, created_at, finished_at). 2. Record terminal events as they happen: a task_events row on the queue's DONE/FAILED/REJECTED transitions, and use existing step/verdict rows or mission_events for runs and missions. 3. A notifier sweep on the existing scheduler runs every minute. For each subscription it reads the events with id > last_event_id and does, in one transaction: claim by advancing last_event_id with a CAS on the old value, then deliver. 4. notify sends a status line through the channel adapter with channel.reply semantics and goes through the attention delivery broker/InterruptBudget. wake and notify+wake call orchestrator.process in that chat's session with the item's result as context and deliver the reply, spending one interrupt, deferred while is_night_window(hour) unless urgent. 5. Auto-subscribe the creating chat when a task or run is created from a chat (setting-gated), and prune subscriptions finished more than 30 days ago. 6. Entry points: /subscribe <task|run> <id> [notify|wake|notify+wake] and /unsubscribe in agents/core/commands.py, plus admin routes. 7. Red-first test in tests/test_work_subscriptions.py: subscribe chat C to task T, transition T to DONE, run the sweep, and a fake adapter receives exactly one message. This fails today because no module exists. Also cover: a second sweep after a simulated restart sends nothing (the cursor held); wake mode calls process in C's session and is deferred at night; the budget is spent; and pruning after 30 days.

## H478

**Bot-to-bot messaging between machines** (automation) — partial, ~12 h.

Owner gate: none for code; a live two-machine proof is a separate owner-host probe

Files: `agents/core/a2a.py`, `agents/core/routers/a2a.py`, `frontend/src/gap.tsx`, `agents/cli/nerva.py`, `tests/test_a2a_hf16_2.py`

Plan: 1) Add an optional `endpoint` to the peer record (add_peer and A2APeerBody). Add A2ARegistry.send(peer_id, task), which signs the body with the peer secret and POSTs it to {endpoint}/api/a2a/task with X-A2A-Peer set to our own id. Expose it as POST /api/a2a/peers/{peer_id}/send (guarded, kernel-mediated as an outbound action) and return the remote inbox id. 2) On the receiving side, decide(approve=True) enqueues one governed run through the existing worker/subagent path (kind e.g. 'a2a.run', tier ask already satisfied by the owner decision) and stores run_id, status and result on the inbox record. Add GET /api/a2a/inbox/{id} and POST /api/a2a/inbox/{id}/stop (admin). Add a peer-facing GET /api/a2a/task/{id}, authenticated by the same peer HMAC over the id and restricted to the originating peer, which returns status/result so the sender polls instead of holding a connection. 3) Add HUD send/status controls in gap.tsx next to the peer and inbox panels, and optionally `nerva peer send|status|stop`. Red-first tests in tests/test_a2a_hf16_2.py: approving an inbox item yields a run handle with status; the originating peer's signed poll returns the result while another peer's poll gets 401; stop cancels; a task is never run before owner approval. Use two in-process registries/TestClients to test send→receive round-trip.

## H579

**Pull a file or slice of a file into a message inline (@ context references)** (docs-features) — missing, ~12 h.

Files: `agents/core/context_refs.py (new)`, `agents/core/orchestrator.py`, `agents/web.py`, `agents/core/routers/ (new user-guarded completion route)`, `frontend/src/cockpit.tsx`, `tests/test_context_refs.py (new)`, `frontend/src/test/context-refs-completion.test.tsx (new)`

Plan: 1) New agents/core/context_refs.py with `expand_references(message, scope: FileScope, per_ref_bytes=64 KiB, total_bytes=256 KiB) -> Expansion(text, attached, warnings)`. Grammar: `@file:<path>`, optionally followed by `#L<a>-<b>` or `#L<a>`; quoted paths are allowed for spaces. Resolve each path with FileScope.resolve and turn FileScopeError reasons (outside_scope, symlink_escape, secret_path, bad_path) into inline `[warning: ...]` lines; never raise. Reject binary files (a NUL byte in the first 8 KiB, or undecodable UTF-8). Slice by a 1-based inclusive line range, truncate with a marker, and append `\n\n--- Attached Context ---\n` blocks headed `path#Lrange`. 2) Call it in Orchestrator.handle_input, inside the turn's action-origin binding and before routing and memory save. When anything is attached, call mark_turn_recall_tainted() so kernel GRANT decisions become QUEUE. 3) Completion: add user-guarded GET /api/context-refs/complete?prefix= returning at most 50 in-scope entries with secret names filtered, and an `@` popup in InputBar (frontend/src/cockpit.tsx). `nerva chat` is covered by the server-side expansion. 4) Tests first in tests/test_context_refs.py. The first red test is test_expands_line_range, which fails because the module is missing. Then cover: outside-root, `..`, symlink and secret refusals rendered as warnings; binary detection; size caps; the taint mark set only when content is attached; and a GRANT-class action queued in a turn that attached a reference. Add a frontend test for the @ popup.

## H686

**The operator can see how the model is actually performing right now, and choose which fields to see** (delta) — partial, ~12 h. Critic notes: [10](#critic-note-10).

Files: `agents/core/orchestrator.py`, `agents/web.py`, `agents/core/settings_db.py`, `frontend/src/cockpit.tsx`, `frontend/src/app.tsx`, `frontend/src/test/status-bar.test.tsx`, `tests/test_turn_status_readout.py`

Plan: In Orchestrator, after each streamed turn, build self._last_turn_stats[session], leaving out any field without data: latency_ms from the turn wall clock; tps = provider output_tokens (or the estimate, marked) / (end - first_token); context_pct = measured prompt tokens / _compaction_policy().window(model); compressions = per-session count of committed compactions. Compute cache_hit_pct from per-session accumulators (cache_read and input since the last invalidation) that reset when _last_models[agent] changes or commit_clock accepts a compaction; omit it when the accumulated cache_read is 0. Add settings display.status_bar_fields (list validated against the vocabulary model, context_pct, cache_hit, latency, tps, compressions, bg_tasks, duration). In agents/web.py, add 'stats': filtered stats to the SSE end event and a stats field to ChatResponse. In the frontend, add a StatusStrip under InputBar in cockpit.tsx that reads end.stats, renders only fields present and selected, and colours cache_hit green at 70 or above, amber at 40 or above, red below. The first red test in tests/test_turn_status_readout.py: a stubbed stream turn with provider usage (input 1000, cache_read 800, output 50) must emit an end event whose stats include cache_hit_pct=80 and tps (it fails today, since there is no stats key). Also: after a model switch the delta resets; with cache_read 0 the key is absent. Add a vitest test that the strip hides absent fields.

## H182

**Keep the machine awake through a turn, and be aware of power/battery state** (desktop) — missing, ~14 h. Critic notes: [31](#critic-note-31).

Owner gate: Optional owner smoke test on a real laptop (on battery, lid/idle sleep) to confirm each OS honours the assertion; all logic is testable with mocks.

Files: `agents/core/power.py`, `agents/core/orchestrator.py`, `agents/core/hardware.py`, `agents/core/system_profiles.py`, `agents/core/kernel/registry.py`, `agents/web.py`, `desktop/src-tauri/src/main.rs`, `desktop/src-tauri/tauri.conf.json`, `frontend/src/gap.tsx`, `docs/FLAGS.md`, `tests/test_power.py`

Plan: 1. New module agents/core/power.py. - A reference-counted KeepAwake guard: - Linux: a `systemd-inhibit --what=idle:sleep --who=Nerva --why=turn sleep infinity` child, or a logind DBus Inhibit fd. - macOS: `caffeinate -i -w <hub pid>`. - Windows: ctypes SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED), released with ES_CONTINUOUS. - Default off behind JARVIS_KEEP_AWAKE (documented in docs/FLAGS.md). Turning it on from the HUD crosses the kernel as host.control. - The guard is released when the last concurrent turn ends, on exception, on lifespan shutdown and at exit. - power_state() reads psutil.sensors_battery() (percent, plugged; None → 'unknown'). - A poller publishes battery and resume changes on the existing SSE/event bus, and a posture knob pauses or throttles background autonomy (heartbeats/jobs) on battery below a threshold. 2. Wrap Orchestrator.process and the streaming chat path in the guard. 3. Desktop shell: disable the webview's background throttling while a stream is active (Tauri window background-throttling setting / command invoked by the HUD on stream start and end). 4. Red tests first, in tests/test_power.py with mocked subprocess, ctypes and psutil: - Flag off → no inhibitor is ever created. - Flag on → exactly one inhibitor is held across two overlapping turns and released after the last. - The inhibitor is released when a turn raises and on shutdown. - A desktop with no battery → 'unknown', not an error. - On battery below the threshold, background work is skipped with a named reason. - The HUD toggle route requires the host.control kernel decision.

## H396

**Turn exit reasons, a completion explainer and per-turn accounting** (agent-core) — partial, ~14 h. Critic notes: [10](#critic-note-10).

Files: `agents/core/agent_runtime.py`, `agents/core/agent.py`, `agents/core/orchestrator.py`, `agents/web.py`, `frontend/src/ (chat end-event rendering)`, `tests/test_turn_exit_reasons.py (new)`

Plan: Add a TurnExitReason str-Enum and a small TurnOutcome(reply, exit_reason, pending_tool_result, failed_mutations, tool_calls, tokens) in agents/core/agent_runtime.py. _run_loop and run record the reason at every return site (the seven *_REPLY constants, the safety limit and the deadline) and keep the existing str API through a thin wrapper, so callers do not break. Log one line per turn at INFO, or at WARNING when the last message is an unanswered tool result. Track file_write/file_delete observations with ok=False per path, clear an entry on a later success for the same path, and append a footer naming the remaining failures. Thread the outcome through Agent._generate_response and the orchestrator into ChatResponse, and into the SSE end event as exit_reason plus accounting. Render the explainer line and accounting in the HUD chat bubble. Red-first tests: run() hitting the deadline yields exit_reason == 'deadline' and a WARNING record when a tool result is pending; a turn whose file_write failed and was never retried ends with a footer naming the path; the SSE end payload contains exit_reason.

## H409

**Outbound signed lifecycle webhooks** (agent-core) — partial, ~14 h. Critic notes: [7](#critic-note-7).

Files: `agents/core/observability/lifecycle_webhooks.py (new)`, `agents/core/extensions/events.py`, `agents/core/routers/admin.py (or a new router)`, `agents/cli/nerva.py`, `tests/test_outbound_lifecycle_webhooks.py (new)`

Plan: Create agents/core/observability/lifecycle_webhooks.py with a JsonStore-backed subscriber registry (id, url, secret, events, enabled), following WebhookStore. Add a delivery sink that ExtensionEventBus.emit, or a sibling hook at the same four emit sites, feeds the same allowlisted payload. Delivery runs on its own bounded queue: json.dumps(sort_keys) body; header X-Nerva-Signature = compute_signature(secret, body) plus X-Nerva-Event and an event_id; http_client with follow_redirects=False; up to 3 attempts with exponential backoff; 4xx other than 429 is not retried. Before each attempt, skip if estop.is_engaged() and route the request through the plugin.egress kernel hook. Run the body through SecretScanner.redact. Add POST/GET/DELETE /api/admin/webhooks/outbound (admin_guard) and a `nerva webhooks` verb. Red-first test: emitting session.started with one subscriber delivers exactly one POST to a mock transport whose signature verifies with compute_signature. Further tests: an engaged estop delivers nothing; a 302 is not followed; a 500 is retried at most 3 times; a token-shaped field value arrives masked.

## H416

**Unified deadline and budget layer** (agent-core) — partial, ~16 h. Critic notes: [11](#critic-note-11).

Files: `agents/core/iteration_budget.py`, `agents/core/agent_runtime.py`, `agents/core/orchestrator.py`, `agents/core/tool_rpc_runtime.py`, `agents/core/plugin_gatherer.py`, `agents/core/resilience.py`, `tests/test_turn_deadline.py (new)`

Plan: Extend agents/core/iteration_budget.py with a RunBudget(max_iterations, wall_seconds, clock=time.monotonic) exposing consume(), remaining_seconds(), fraction_spent() (max of the iteration and wall fractions), timeout_for(kind, default), and a contextvar current_run_budget(). The orchestrator creates one per agent call from _agent_call_timeout. AgentToolRuntime.run and _run_loop use it in place of IterationBudget(limit) and effective_wall_seconds, and tool/ToolRPC/plugin timeouts become min(own default, budget.remaining_seconds()). In _run_loop: when fraction_spent() >= 0.8 for the first time, append one user message asking the model to wrap up and deliver from what it has. When consume() returns False, append one notice, make one final backend call with tools=[], and return its text; if that text is empty, return a summary built from the last tool results. Tag the outcome with the H396 exit reason. Red-first tests (tests/test_turn_deadline.py) with a scripted backend that always requests a tool: the wrap-up message appears exactly once, at the 80% iteration; on exhaustion the final call receives no tools and its text is returned instead of the safety-limit string; an empty final text yields a non-empty forced summary; a fake clock past 80% of wall_seconds also triggers the nudge.

## H545

**Let the editor hand the agent MCP servers that exist only for that session** (acp-mcp-dev) — missing, ~16 h.

Files: `agents/core/mcp/client.py`, `agents/core/mcp/session_scope.py (new)`, `agents/core/acp/ (new, H542 surface)`, `tests/test_acp_session_mcp.py (new)`

Plan: Prerequisite: H542's ACP stdio server (effort L), which is not counted in this estimate. Add a SessionMCPScope in agents/core/mcp/session_scope.py that wraps the global MCPManager. Each session gets its own dict of MCPServer objects built from the mcpServers array passed to session/new|load|resume|fork. Registration runs through asyncio.to_thread with asyncio.wait_for(discovery, mcp_discovery_timeout=1.5). A server that misses the join is left pending, and a follow-up task re-runs tool discovery and refreshes the session's tool list once it completes. get_tools(session_id) returns global tools plus session tools; other sessions never see them. Scope teardown on session end disconnects the servers. Route every session-server call through the same outbound authorization path as configured servers, with trust clamped to at most the configured-server default. Red-first test (tests/test_acp_session_mcp.py): session A's tools include the mcp-<name> tools while session B's do not; a server whose connect sleeps 5 s does not delay session/new beyond ~1.5 s, and its tools appear after the late refresh; a session server marked with a wider trust tier is clamped.

## Critic notes

Cross-row findings over the plans above. Rows named without a link (H068, H071, H104, H130, H135, H523, H683) are not on this page — they are among the eleven rows re-read for drift in the same pass — and appear because a plan here collides with them.

### Critic note 1

Rows: [H461](#h461), H465 (closed in #1207), [H117](#h117), [H677](#h677).

H461 and H465 both state that the orchestrator has no per-session turn-in-flight marker, and their gap_specs add a new in-flight set to Orchestrator.process. H117 and H677 cite the marker that already exists. Orchestrator.turn_lease (agents/core/orchestrator.py:1547) keeps a per-session asyncio.Lock table (_turn_leases, keyed by _lease_key) with a re-entrant held set (_held_turn_leases). It is taken by channel turns (_channel_turn, :1498, taking it at :1505), by /chat and /chat/stream (agents/web.py:1161, :1214) and by session_continuation.py:354. Process() is not keyed by session at all. A naive lock.locked() check would also always refuse /refine, because slash commands dispatch inside handle_input (orchestrator.py:1794), which already holds that session's lease.

**Fix.** Correct the H461 and H465 summaries: the marker exists as turn_lease. Rewrite both gap_specs to reuse it. Busy means _turn_leases[key].locked() and key not in _held_turn_leases.get(), which excludes the command's own turn. The H461 heartbeat sweep acquires turn_lease(session_key) with a short wait and skips on False. Drop 'add a per-session in-flight set in process()' from both.

**Done in #1207 (2026-09-25) for H465.** `/refine` reuses the lease; no in-flight set was added. Every path that dispatches `/refine` holds the session's turn lease first, so a `/refine` sent while another turn runs waits for that turn (up to the lease's bound) and then reviews the conversation as it stands. `Orchestrator.refine` answers `turn_in_flight` only to a direct caller that holds no lease while another turn does (the lock is held and the key is not among this context's held leases). H461 should reuse the same check.

### Critic note 2

Rows: [H461](#h461), [H472](#h472).

Both gap_specs run the injected or wake turn with orchestrator.process in the target session (H461 step 5: process(prompt, session=that session_id, channel=origin); H472 step 4). Orchestrator.process(prompt, agent, channel) (orchestrator.py:1526) has no session parameter. It calls _call_agents_parallel directly, outside handle_input, so the turn is never added to that conversation's history. H461's accepted requirement is exactly to inject a user turn into that conversation. H461 also re-implements pause/resume, anchor and CAS claiming, estop, quiet hours and interrupt budget in a new session_heartbeats store, although the jobs lane (JobRunner claim/_fire_once, quiet_hours) already provides all of them.

**Fix.** Specify one shared helper, e.g. Orchestrator.run_turn_in_session(session_key, channel, chat_id, text). It sets _active_session, takes turn_lease(session_key), calls handle_input and delivers through the DeliveryRouter/ChannelManager. H461 and H472 use it. Consider building H461 as a job blueprint bound to a session instead of a second scheduler lane, and state the choice in the gap_spec.

### Critic note 3

Rows: [H461](#h461), H465 (closed in #1207), [H472](#h472), [H441](#h441).

H461's summary says CommandContext (commands.py:50) 'carries no session or chat identity', and step 2 adds channel/chat to it. CommandContext.principal is already a Principal with channel and chat (agents/core/commands.py Principal, used by /voice). ctx.orch.session_id already resolves to the bound channel session, because channel_handler sets _active_session before handle_input dispatches commands (orchestrator.py:1687). H461, H465 and H472 each plan the same CommandContext change separately.

**Fix.** Correct the H461 summary: only an explicit session_id is missing, and ctx.orch.session_id already yields it. Make one shared prerequisite change: optionally add session_id to CommandContext, and otherwise use ctx.principal.channel/chat plus ctx.orch.session_id. Reference it from H461, H465, H472 and H441 (/recap) instead of four separate edits.

**Done in #1207 (2026-09-25) for H465.** `/refine` needed no CommandContext change: `Orchestrator.refine` resolves the session through `_lease_key` (the bound channel session, as `ctx.orch.session_id` would). H461, H472 and H441 can do the same.

### Critic note 4

Rows: [H413](#h413), [H440](#h440), [H441](#h441), [H218](#h218).

H413 and H440 are the same feature with conflicting gap_specs, and both create agents/core/session_titles.py. H413 has instant_title (~8 words, 60 chars) written into sessions.summary, with a free-text single-line upgrade prompt. H440 has derive_title (48 chars) in new title and title_source columns, a JSON-schema-constrained upgrade and a human-title-never-overwritten rule. Four rows (H413, H440, H441 recap, H218 archive tab) edit the same SessionsPanel (frontend/src/gap.tsx:2369) and mobile SessionsModal.

**Fix.** Merge into one spec: H440's columns plus provenance, the JSON-schema upgrade and one length cap, plus H413's refusal of cloud or openrouter backends for the upgrade. H413 closes with the same PR. Sequence the SessionsPanel changes for titles, recap and the archive tab in one frontend change.

### Critic note 5

Rows: [H218](#h218), [H262](#h262).

Two incompatible archive tiers and duplicate knobs. H218 adds an archived_at column (a metadata hide), a sessions.auto_archive_days setting and a daily auto-archive job. H262 adds retention.archive_days, which moves transcripts to data_root/archive/sessions with a restore route and pinned-session exemption. Built independently, an H262-moved transcript breaks H218 unarchive and resume, H218-archived rows are not what H262 deletes, and there are two 'days until archive' settings.

**Fix.** Use one archive state: sessions.archived_at, set by the owner (H218) or by the retention sweep after a single archive_days setting. Restore means unarchive. H262 deletes only archived, unpinned sessions past conversation_ttl_days, through H218's data_purge.purge_session backup-first path. Write it in one spec and name the dependency in both rows.

### Critic note 6

Rows: [H259](#h259), [H157](#h157).

The settings reset and import specs contradict each other. H259's governance puts reset behind the approval queue's irreversible tier and makes import a no-write preview followed by the existing PUT. H157's gap_spec adds POST /api/admin/settings/{category}/reset, which writes immediately, and POST /api/admin/settings/import, which writes all-or-nothing. That is the token-gated irreversible write H259 exists to remove. Both define GET /api/admin/settings/export with different secret handling ('omitted' list in H157 versus 'omitted or redacted' in H259).

**Fix.** Write one spec for both rows. Export omits secret-kind keys and names them. Import is preview-only, uses validate_category and returns every error as 422, then the batch PUT applies it. Per-category reset is a preview plus a settings.reset task queued at the irreversible tier. H157's reset route must enqueue, not write. H157's cross-category search stays separate.

### Critic note 7

Rows: [H200](#h200), [H153](#h153), [H659](#h659), [H409](#h409).

H200 and H153 specify the same frontend/src/panels/webhooks.tsx, console route and create/delete audit. H200's create form offers workflow targets and its summary treats them as working. H153 found, and I confirmed, that trigger_webhook calls engine.run(hook['target'], {'input': text}) (agents/core/routers/webhooks.py) while WorkflowEngine.run(pipeline, initial_input) expects a Pipeline, so every workflow-target trigger raises outside the inbound origin. H659 says the trigger 'runs orch.handle_input on every delivery', which is true only for agent targets. H409 introduces a `nerva webhooks` verb for outbound hooks only, while H200 lists the missing inbound CLI.

**Fix.** Build once from H153's spec: enabled toggle, audit, workflow fix under bind_action_origin(INBOUND), and the panel. H200 closes with it, and its remaining must name the workflow bug or restrict creation to agent targets. H659 places the idempotency reservation before both branches. Make the CLI `nerva webhooks inbound|outbound`.

**Done in #1207 (2026-09-24):** H153 and H200 closed together (the workflow-target fix landed first, under the inbound origin). H659 and H409 remain; the CLI verb was not built. After review, H153 was partial again until its event filter, prompt template and receiver switch were built; it closed again with them. A second review found Deliver to missing and the receiver switch failing open; both were built and it closed a third time. A third review found that no delivery reached a channel for real; each offered channel now receives one, tested down to the adapter, and it closed a fourth time.

### Critic note 8

Rows: [H275](#h275), [H490](#h490), [H285](#h285).

H275 and H490 are the same safe-mode feature with separate estimates (7h and 10h). Both create agents/core/safe_mode.py with safe_mode_enabled(). They differ in reporting surface (/status and /readyz versus /api/security/posture) and in skip set: H490 also disables instruction files, memory recall, WorldView, hooks and webhooks and forces stricter autonomy defaults, while H275 adds a _save_mcp_config refusal. H490's files_to_touch lists agents/serve.py, which does not exist; the launcher is serve.py at the repo root. H285 depends on safe mode.

**Fix.** Merge into one spec with the union of skip sets and both reporting surfaces, one flag and one SAFE_MODE_SKIPS tuple. Fix the path to serve.py. Close H275 and H490 together and keep H285 depending on it.

### Critic note 9

Rows: [H378](#h378), [H513](#h513), H583 (closed in lot 1).

H378 and H513 each add a data-training tier with incompatible vocabularies and acknowledgement stores. H378 has ProviderProfile.data_policy ('no-training'|'trains-on-inputs'|'unknown'), an acknowledge_training flag on the settings PUT and a consent SecurityEvent. H513 has ProviderProfile.data_handling ('local'|'no_training'|'may_train'|'unknown'), a security.data_training_ack list and POST /api/security/data-handling/ack audited as SETTINGS_CHANGE. H583's openrouter_data_collection (default deny) changes OpenRouter's effective tier, and neither spec reads it. H513 carries an owner_gate for the vendor-tier defaults; H378 needs the same vendor facts and has none.

**Fix.** Use one field (H513's vocabulary) and one acknowledgement store whose write emits the consent audit event H378 requires. Derive the OpenRouter tier from openrouter_data_collection. Give H378 the same owner_gate, or remove it from both.

### Critic note 10

Rows: [H220](#h220), [H686](#h686), [H396](#h396).

Three rows add overlapping per-turn payloads and meters on the same surfaces. H220 adds ChatResponse.usage {input/output tokens, context_used/max/percent, cost} and a context meter in the cockpit InputBar. H686 adds a 'stats' field on the SSE end event (agents/web.py:1182) and ChatResponse (web.py:945) {latency_ms, tps, context_pct, compressions, cache_hit_pct}, plus a StatusStrip under InputBar. H396 adds a TurnOutcome with exit_reason and accounting (tool calls, failures, tokens) on the same two payloads, plus a HUD accounting line. Token and context counts would be computed three times.

**Fix.** Build one per-turn outcome object in the orchestrator, carried as a single field on ChatResponse and the SSE end event. H686's display.status_bar_fields vocabulary selects what the single strip renders. H220's context meter is the context_pct field. H396's exit_reason and accounting are fields of the same object. Record the dependency in all three rows.

### Critic note 11

Rows: [H416](#h416), H428 (closed in #1207), [H674](#h674), [H677](#h677).

H416's accepted requirement is one budget primitive whose timeout_for(kind) replaces site-local constants. H428 (memory.recall_timeout_s) and H674 (compression_max_turn_hold_seconds, compression_inactivity_seconds) add new site-local timeouts inside the turn, which H416 would then have to chase down again. H677 adds boot and teardown budgets, which sit outside a turn.

**Fix.** Specify in H428 and H674 that their in-turn waits use min(own setting, current_run_budget().remaining_seconds()) once H416 lands, or sequence H416 first. Leave H677's boot and teardown budgets as settings, noted as out of H416's scope.

### Critic note 12

Rows: H428 (closed in #1207), H433 (closed in #1207).

Both rows modify Orchestrator._recall_block. H433 adds a strict-local rewrite call (max_tokens 96, no timeout) before memory.recall. H428 bounds only memory.recall with its hard timeout and gates trivial prompts. A hung local backend in the rewrite would stall the turn outside H428's bound, and trivial prompts would still pay for a rewrite.

**Fix.** Build both in one change, applying H428's is_trivial_prompt before the rewrite and putting rewrite plus recall under the single hard timeout. Add a test where the rewrite backend hangs and _recall_block still returns '' within the bound.

### Critic note 13

Rows: [H427](#h427), [H674](#h674).

Both rows change the compaction boundary in ContextCompressor.compact/_history_for_prompt. H427 calls the checkpoint only on the summarize tier before compress(). When H674's hold expires, it evicts the same turns through _fallback_digest and finishes the LLM summary in the background. The digest path would therefore evict turns without the H427 checkpoint, and a refused required checkpoint would not block it.

**Fix.** Specify one ordering: the checkpoint runs once before any summary or digest replaces turns, its time counts inside H674's hold, a failed required checkpoint also blocks the digest path, and the deferred background summary does not re-checkpoint.

### Critic note 14

Rows: [H667](#h667), [H262](#h262).

H667's gap_spec wires prune_exec_cache into run_retention. SchedulerService.run_retention_purge returns 'skipped' unless retention.enabled is set, and it defaults off (agents/core/scheduler_service.py). H262 also adds a min_interval gate to run_retention. Under that wiring the exec cache under data_root is never pruned on a default install, which defeats the row.

**Fix.** Give prune_exec_cache its own hourly SchedulerService job, independent of retention.enabled and the H262 marker, and state it in the H667 gap_spec.

### Critic note 15

Rows: H687 (closed in #1207), [H450](#h450), [H461](#h461).

H687 queues an immediate first run through request_run and _fire_once. _fire_once calls store.reserve_attempt, which consumes options.repeat (agents/core/autonomy/jobs.py _fire_once, 'repeat limit exhausted'). H450 adds one-shot run_at jobs and normalize_repeat, which maps 'once'/'1x' to 1. Combined, a new repeat=1 or one-shot job fires immediately, spends its only attempt, and its scheduled slot is skipped. Separately, H461's red test uses '/heartbeat every 10m', but H450 shows resolve_schedule refuses compact intervals ('every 30m') today, so H461 depends on H450's interval family and does not declare it.

**Fix.** In H687, exclude one-shot/run_at jobs and repeat-limited jobs from the automatic first run unless first_run is true, or have the first run not reserve an attempt, and add tests for both cases. Add H450 as a dependency of H461, or change its red test to 'every 10 minutes'.

### Critic note 16

Rows: [H117](#h117), [H677](#h677).

Both gap_specs change Telegram _poll_loop so it stops awaiting receive() per update (telegram.py:459). H117 does it for burst coalescing; H677 does per-chat concurrent dispatch or a shorter lease wait. Done separately, the two changes conflict: coalescing needs ordered per-chat buffering, and concurrent dispatch must preserve per-chat order.

**Fix.** Make one change: a per-chat ordered dispatch queue with one worker per chat_id that feeds H117's BurstCoalescer, satisfying both rows. Reference it from both rows.

### Critic note 17

Rows: H104, H068, H683, [H114](#h114).

The Slack and Discord descriptors declare supports_edit=True (agents/core/channels/slack.py:102, discord.py:32), but neither adapter implements begin_stream or any edit call: Slack send posts only via chat_postMessage, and no chat_update or PATCH exists. The H104 and H068 remainings name the missing channel.reply approval contract as the only blocker for Slack/Discord streaming; H683 correctly says the edit path is also missing. H114's display-tier resolver derives its tier from supports_edit, so it would rate Slack and Discord as edit-capable. The approval contract that would let one channel.reply decision cover output not yet generated is a governance decision.

**Fix.** Add the missing Slack/Discord edit implementation to the H104 and H068 remainings. Either set supports_edit=False on both descriptors until an edit call exists, or have H114 derive the tier from an implemented edit method. Record the streaming-approval contract in docs/OWNER_TASKS.md as an owner decision rather than AI-executable work.

### Critic note 18

Rows: H068, H683, [H114](#h114).

The gaps overlap. H068's 'no typing indicator on an ordinary text turn' is H683's gap (3), acknowledge at ingest. H068's tool-progress message with 'cleanup after the final answer' needs H683's delete_message on channels/base.py. H068's quiet/show-tools levels and long-running 'still working' message per channel are the interim and heartbeat messages H114's display tier is meant to govern.

**Fix.** Order the build as: base edit_message/delete_message plus the loud stub (H683), then the display tier (H114), then tool-progress, heartbeat, log and /verbose (H068). Count ack-at-ingest once, under H683, and have H068's remaining reference it rather than duplicate it.

### Critic note 19

Rows: H104, H068.

The evidence lists miss files the summaries rely on. Both rows describe Orchestrator._begin_channel_draft and ChannelDescriptor.supports_edit. H104 names MatrixChannel. H068 names the slash-command registry and the hardcoded decision-card labels. Yet evidence lists only slack.py, discord.py, telegram.py and three tests, while H683, which covers the same code, lists orchestrator.py, base.py and descriptor.py.

**Fix.** Add agents/core/orchestrator.py and agents/core/channels/descriptor.py to H104 and H068. Add agents/core/channels/webhook_channels.py to H104. Add agents/core/commands.py and agents/core/autonomy/inbox.py to H068.

### Critic note 20

Rows: H071, H130, H135, H523.

The H071 and H130 keep verdicts retain Romanian summary/remaining, while the ledger rule is English and the other drifted rows (H068, H104, H108, H683) were rewritten in English. H071 also keeps the unverified claim '15/15 mutanți uciși'. The H135 and H523 keep verdicts carry run-together numbers ('All19', 'Fresh148', 'independent98', 'full1,315', 'collected11,428 tests with11,404 passes,23 skips') and suite counts that this catch-up did not reproduce.

**Fix.** Re-express H071 and H130 in English with no substantive change. Fix the spacing in H135 and H523, and either drop the unreproduced run counts or date them as historical.

### Critic note 21

Rows: H318 and H340 (both closed in #1207), [H696](#h696).

Both rows add a `skill_view` ToolRPC tool. H318 puts it in agents/core/skills/tools.py with args {name, file?}, trust gates and taint; H340 registers it in autonomy_coordinator with {name} and returns loader.render_body with template substitution. Built separately, the two definitions collide. H696's reference files are what H318's `file` argument reads.

**Fix.** Build one skill_view in H318's module that returns H340's rendered body under H318's gates, and close H340 with that PR. Make `file` read the H696-imported references, confined to the skill directory.

**Done in #1207 (2026-09-25).** One `skill_view` in agents/core/skills/tools.py returns H340's rendered body under the catalog's gates, and H340 closed with it. `file` reads a file of the skill as captured at load: one of up to 64 KiB, within 1 MiB for the whole skill (a larger one, or one past that total, is listed and refused as too large). H696's imported references will be readable once H696 imports them, within those limits.

### Critic note 22

Rows: [H309](#h309), H313 (closed in lot 1), [H314](#h314), H315, H318 and H340 (closed in #1207).

Six rows register new ToolRPC tools and each regenerates tests/_snapshots/tool_profiles.json, with inconsistent posture rules. H315 offers todo in every posture. H313 limits speak to operator/owner. H314 withholds memory from inbound/guest. H309 adds ui_point to the 'default tool profile', which would let an inbound Telegram sender post HUD canvas pointers. H318 and H340 leave skills_list/skill_view posture unspecified, so skill bodies would be exposed to inbound turns.

**Fix.** Decide one posture table for all six tools in agents/core/tool_profiles.py (at least ui_point, skills_list and skill_view withheld from inbound/guest), write it into each gap_spec, and regenerate the snapshot once.

**Done in #1207 (2026-09-24), in part:** H315 wrote the rule into agents/core/tool_profiles.py. Its review corrected the first version, which had made `todo` "session-local" (offered in every posture because its only effect was the calling session's own list). A turn with no session of its own runs on the owner's shared session, so that premise was false. `todo` is now an ordinary ungated tool that reaches inbound/guest through the default `llm.guest_tools` (echo, time, todo). An install seeded by an earlier build gets that default once, at start, and an owner's own list is left alone. It is session-scoped (`SESSION_SCOPED_TOOLS`): on the shared session only an owner's turn is offered it, a script's reach is narrowed the same way, and the tool refuses anyone else. Any tool that acts on the owner's HUD, memory or skills (ui_point, a memory write, skills_list, skill_view) stays off inbound/guest unless the owner names it in `llm.guest_tools`. `speak` is gated and follows the gated rows. H309, H314, H318 and H340 should follow this rule when they are built, and each regenerates the snapshot. H318 and H340 did (2026-09-25): `skills_list`, `skill_view` and `skill_propose` are ungated, off inbound/guest unless named in `llm.guest_tools`, and `skill_propose` refuses any turn that is not the owner's.

### Critic note 23

Rows: [H328](#h328), [H329](#h329).

Both rows gate skills by platform using the wrong vocabulary. H328 checks metadata.hermes.session_platforms against the surface from tool_profiles.classify_turn, whose values are operator/inbound/internal (tool_profiles.py SURFACE_*), not platform names; its red test 'session_platforms:[telegram] hidden on the operator surface' mixes the two. H329's skills.platform_disabled is keyed by surface ('inbound' in its red test). Hermes keys both on platform or gateway channel (telegram, discord, cli).

**Fix.** Define one platform key, taken from Principal.channel or the action-origin channel (telegram, hud, cli, ...), separate from posture. Use it in both H328 and H329 and fix their red tests.

### Critic note 24

Rows: [H329](#h329), [H204](#h204), [H285](#h285), [H275](#h275).

Three separate skill-disable stores all filter prompt_catalog and execute. H329 uses settings skills.disabled/platform_disabled, with a direct disable and re-enable through permission.grant. H204 uses a permission_ledger 'skill' surface '<agent>:<skill>' with agent '*' as the All switch, which duplicates H329's global disable. H285 uses startup.skills_skip/skills_only plus JARVIS_SKIP_SKILLS, and safe mode (H275) adds a fourth filter. No precedence order is defined.

**Fix.** Specify one SkillAvailability resolver in the loader with an explicit precedence: safe mode > boot load-set > global/platform disable > per-agent grant. Keep a single store for owner disables (ledger rows, with '*' serving as H329's global switch) and settings only for the boot load-set. Reference the resolver from all four rows.

### Critic note 25

Rows: [H334](#h334), [H696](#h696), H344 (closed in lot 1).

Both H334 and H696 re-pin the Hermes catalog to v2026.8.31, in conflicting formats: H334 regenerates hermes_pin_v1.json, H696 writes hermes_pin_v2.json (schema_version 2, tier, files). Both estimates (7h, 6h) include the re-pin work. H334 (route) and H344 (nerva_import CLI) each add a skill.install crossing for imports.

**Fix.** Re-pin once, in H696's v2 format. Limit H334 to the kernel crossing and the SSRF egress seam, and lower its estimate. Add one shared authorize-skill-import helper used by POST /skills/import (H334) and ImportRunner (H344).

### Critic note 26

Rows: [H243](#h243), [H380](#h380), [H596](#h596), [H373](#h373).

The provider-credential work overlaps. H243 adds GET /api/admin/llm/providers plus key save and disconnect, and AuthProfilePool.from_keys over SecretStore (agents/core/secrets.py). H380 adds a second catalog route, GET /api/llm/providers, with POST .../probe. H596 adds AuthProfilePool.from_sources resolving through VaultResolver (agents/core/secrets_vault.py), which its governance field names. That is two catalog routes, two pool constructors, two secret paths, and three edits to AuthProfilesPanel (gap.tsx:2592). H596 also changes 429 rotation and adds retry_after, while H373 persists 429 retry-after in a cross-process guard; neither specifies how the two interact.

**Fix.** Use one route family under /api/admin/llm/providers (list with probe state, key POST/DELETE, probe POST), one AuthProfilePool.from_sources through secrets_vault, and one panel change. Parse retry-after in one place and key H373's shared guard per (provider, profile), so H596's rotation to another key is not blocked.

### Critic note 27

Rows: [H487](#h487), [H659](#h659).

Both rows add deduplication to ActionApprovalQueue.request (agents/core/autonomy/action_approvals.py). H487 coalesces identical pending asks by sha256(agent+tool+args) and fans the decision out to waiters. H659 adds an Idempotency-Key reservation in front of the same enqueue, with its own request fingerprint and a 409/422 on mismatch. The order of the two layers and their different fingerprints are not reconciled.

**Fix.** Specify the order: route-level idempotency replay first, returning the stored id without calling request(); then coalescing inside request(). Keep the fingerprints distinct and named, and add a combined test: same key replay versus a different key with identical args coalescing.

### Critic note 28

Rows: [H259](#h259), [H218](#h218), [H425](#h425), [H174](#h174), [H262](#h262).

Five gap_specs each invent their own 'enqueue at the irreversible tier, apply only in the approved-task executor' path for a new kind: settings.reset, session purge, memory.forget, system.uninstall and retention TTL writes. Each needs an ACTION_REGISTRY entry, a capability manifest and a worker executor, and each row's estimate counts that plumbing again.

**Fix.** Build a shared irreversible-action helper (enqueue(kind, payload), an executor registry and the audit row) in the first of these PRs. Have the other four gap_specs reuse it and lower their estimates.

### Critic note 29

Rows: [H670](#h670), [H283](#h283), [H594](#h594), [H114](#h114).

Four rows add system-prompt blocks with no agreed order: identity contract (H670), operator environment hint (H283), project context files (H594) and platform hint plus per-channel prompt (H114). H670 names only the streaming site (orchestrator.py:1985) and Agent.generate_response. The non-streaming parallel path builds `system` via render_snapshot at orchestrator.py:3165, which H283 does name. H670 and H283 require a stable cached prefix, while H114's hint varies per channel and H594's varies per cwd and taints the turn.

**Fix.** Define one assembly order in a single helper used by both paths: contract → SOUL → environment hint → per-channel hint/prompt → project context → runtime blocks. Add the render_snapshot site to H670's gap_spec. Count each block once in prompt_size.py.

### Critic note 30

Rows: [H596](#h596).

Closability is mis-estimated. The accepted OAuth-refresh branch has no OAuth credential type in Nerva. The gap_spec adds only an injectable async `refresher` on AuthProfile with no concrete provider refresher, which is a seam that would not close the branch. A real refresh needs a provider OAuth client registration and owner consent. It is marked ai_executable at 10h with no owner_gate.

**Fix.** Split the row: 402/429 branches, vault resolution and the panel stay AI-executable. Mark the OAuth refresh owner-gated (client registration and consent) or re-scope it through the row decision, and raise the estimate.

### Critic note 31

Rows: [H283](#h283), [H182](#h182), [H222](#h222).

Closability is inconsistent. H283 switches the shipped systemd unit to Type=notify with WatchdogSec=30, which changes deployment behaviour: a hub that never sends READY=1 is killed at TimeoutStartSec, and a stalled loop is restarted. An AF_UNIX unit test cannot prove this. H182 and H222 carry owner_gates for their host-bound proofs; H283 has none.

**Fix.** Add an owner_gate to H283 for a live systemd smoke test on the owner host, or ship Type=notify as an opt-in unit and keep Type=simple as the default until proven.

### Critic note 32

Rows: [H410](#h410), [H145](#h145).

H145's log reader re-redacts with 'the same SecretScanner that SecretRedactionFilter uses', but H410 puts the CNP/IBAN pass inside SecretRedactionFilter.redact_text, not in SecretScanner, so tail output would skip it. H410 replaces the coordinator's basicConfig (scripts/coordinator.py:122) with setup_logging(). When system.log_to_file is on, setup_logging also attaches a RotatingFileHandler to data_path('logs','jarvis.log'), so a second process would rotate the hub's file (RotatingFileHandler is not multiprocess-safe), which is also the file H145 reads.

**Fix.** H145 calls SecretRedactionFilter.redact_text. H410's coordinator calls install_log_redaction_everywhere() after basicConfig, or logs to a distinct coordinator file that H145's file filter then lists.

