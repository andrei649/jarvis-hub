# Skill commands in chat

As the owner, type `/<skill-name> [instruction]` to load one installed skill's
instructions into the current turn. Names use lowercase slugs: `My Skill` becomes
`/my-skill`; `/my_skill` also works. An installed folder name can identify the
skill. Ambiguous names are refused. This loads guidance through the same checks
as viewing a skill; it does not directly execute the skill's code.

Built-in commands, their aliases, owner shortcuts and named bundles take
precedence. `/bundle NAME` explicitly selects a bundle. Disabled, quarantined,
unsupported or unreadable skills do not reach the model. Each agent prompt checks
the skill again; untrusted content retains its taint and action approval rules.
Only clean eligible reads carry into later turns through the existing skill ledger.

Use `/commands` and `/commands 2` to browse pages of at most 20 entries. Owners see
command, bundle and available skill shortcuts. Other users see only commands
their channel policy permits and cannot load skills. Telegram shows skill names
with underscores; collisions are checked for that exact spelling. The full
canonical name remains on other channels.

You can stack up to five leading skills: `/weather /news morning briefing`.
A sixth token, a command/bundle collision or an unreadable member refuses the
entire request. Every prompt still rechecks each skill. A path such as
`/tmp/report.txt` in the instruction is not a skill token.

Plugin commands share the guarded command registry. A dedicated HUD skill-command
picker remains open. Use a named bundle for a predefined group of skills.

Native discovery: Telegram appends eligible skills only to the configured private
owner-chat command menu, within its 100-entry cap. Discord exposes a generic
`/skill` command with owner-only autocomplete; the global tree does not contain
private skill names. Catalog gates and namespace collisions are rechecked at
selection and queued dispatch. Slack retains typed skill commands without listing
private names globally. Native provider registration has only offline SDK tests.

As the owner, use `/reload-skills` (also `/reload_skills`) after changing installed
skills. It reports additions, removals, changes, skipped folders and unverified
entries. A failed scan or changed policy keeps the current registry. A successful
reload keeps the loader object used by other services and swaps its completed
registry. Approved Python modules may run import-time code during discovery; the
command does not promise to roll back those side effects.

Use `/reload-mcp` (also `/reload_mcp`) as the owner to preview a reread of saved
MCP server definitions. Confirm the displayed one-time token with
`/reload_mcp confirm <token>`, or use `/reload_mcp cancel`. The confirmation is
short-lived and bound to the owner, serving manager, saved configuration and
current server state; changed state requires a fresh preview. No permanent
“always approve” preference is stored.

Reload retains the load-set selection captured at hub startup. New servers are
registered disconnected; servers previously disconnected by the owner stay
disconnected. Existing wanted servers may reconnect after confirmation. Changed
or removed transports are closed before replacement; a failed close stops that
replacement. Session-scoped servers are preserved. The result reports actual
connection and tool-definition changes, including partial failures. Reload does
not write the saved settings. Live provider reconnect proof remains separate
from the offline lifecycle tests.

Use `/debug` as the owner to save a diagnostic report under the hub's private
`support_reports/` data directory. The reply gives the local file path; the
command never uploads it. The report includes system information and up to 50
recent warning-or-higher log records when file logging is available. Log text
and the finished report pass the existing secret redactors. If redaction or the
local write fails, no report path is announced. `/debug` takes no path or URL
argument.
On platforms without safe directory-relative file creation (including Windows),
`/debug` reports that private local output is unavailable and saves no file.

Use `/egress` as the owner for a read-only snapshot of recorded external/model
attempts, the local ledger's completeness, configured outbound proxy variable
names, credential name/environment layers, and stored secret handles. The
environment layer does not establish the credential's original vault or
integration source. The command never shows credential or proxy values or asks
the broker to resolve or inject handles; the ordinary outbound redactor may
consult locally held known secret values before sending. A configured proxy variable does
not prove that a request used it: transports differ, and the command cannot
attest the actual route. Ledger counts cover instrumented model/plugin attempts,
not every possible network path; zero is not proof of no egress. The reply includes a next check appropriate to the
observed state. `/egress status` is the same snapshot; other arguments are refused.

Use `/diff` as the owner to view unstaged tracked changes in the current session
worktree, or `llm.project_dir` when no session worktree is active. `/diff staged`
shows staged changes; `/diff all` compares staged and unstaged changes to `HEAD`.
Add `--stat` to any mode for a compact summary. Untracked names are listed
separately, without reading their contents. `/diff session` compares the earliest
retained full-project terminal checkpoint with current files, even without Git.
It requires terminal checkpoints enabled and an allowed project root. This is an
approximate project comparison: its baseline may predate this chat or postdate
its start after pruning. Excluded paths are reported; missing or corrupt history
is refused, never treated as a clean project. Arbitrary path arguments are
refused. Git modes reject unsafe Git configuration. All modes report read/output
bounds and redact the full bounded result before display truncation.
It does not run a model or change the repository.

`/version` (also `/v`) shows the running hub's canonical version. `/profile`
shows the owner the active profile ID, its effective display label, and the
profile-local data home. The label is the canonical ID; this hub has no
separate profile display-name metadata. Both commands take no arguments.


Owner maintenance additions (2026-11-12 local): `/platform [list|pause <name>|resume <name>]` shows loaded adapters and controls only confirmed failed retry loops. A healthy channel or an SDK startup without a recorded failure cannot be paused through this command. Pause intent stays in this process, the adapter remains registered, and unsafe/unfinished teardown blocks restart. Safe mode refuses resume. `/update` accepts no arguments and requests the existing irreversible approval card for the locally known trusted target with dirty-tree refusal; it never applies an update itself. Authenticated owner web chat and Telegram/Discord/Slack/Matrix can request it. The exact `hub.update` kind is now registered for strict Kernel intake. Execution requires AUTO mode, current signed task authority and a human tier-three approval; ask/off do not authorize the host effect. The shared queue database atomically refuses a second still-executable update card, including approved, running and deferred cards. It never reuses an existing card ID for a newly planned target. This guarantee covers processes sharing that database; progress streaming and post-restart notification remain open.


`/pause off` (also the exact words `resume`, `stop`, `disengage` after `/pause`) uses the existing owner-only recovery path. Bare `/pause` preserves an existing engagement; an explicit new reason updates it. `/stop off` still engages the stop. Slack/Discord platform pause now recognizes a disconnect after confirmed live readiness; initial readiness and failed health probes do not count as confirmed disconnects.
