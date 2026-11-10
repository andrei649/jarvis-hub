# Pinned Hermes runtime in Jarvis Hub

PR #1233 adds the complete upstream Hermes source as an owner-provisioned runtime,
with a private profile and its own upstream-PM-managed Python 3.14. Jarvis keeps
Python 3.12, authentication, operator controls and Action Kernel authority.
The source pin is `9c0560f8e6856bc14c11bfe6d666df06be14d2de` (2026-11-10) from
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/tree/9c0560f8e6856bc14c11bfe6d666df06be14d2de).
It replaced `0808ed8ec0420ef2c8e1363d919ef1d83fc4e5e7`; see [Pin 9c0560f8](#pin-9c0560f8-2026-11-10)
and, for moving it again, [Moving the pin](#moving-the-pin).

## Setup and use

From a Jarvis checkout with its dependencies installed:

```bash
export JARVIS_HOME=/absolute/path/to/private/jarvis-data
python scripts/hermes_runtime.py install
python scripts/hermes_runtime.py status
```

Installation downloads the complete SHA-256-pinned archive and uses upstream
`pm.cli install` for the locked interpreter, Python extras and browser/device
tools. It does not install Hermes into Jarvis's environment. The install requires
network access and disk space for those tools. This is a substantial runtime,
not a few-line or ultralight dependency. An existing owner profile and provider
credentials are not imported. Configure providers in the private Hermes home
under `$JARVIS_HOME/hermes-runtime/home`, using upstream's documented configuration.

Set `JARVIS_HERMES_ENABLED=1`, `JARVIS_ACTION_KERNEL=1` and
`JARVIS_TASK_MEDIATION=enforce` in the Hub environment. Governed approvals also
require global autonomy **AUTO** and the persistent signed IntentLog/TaskQueue.
Start the Hub and open **Admin → Hermes Runtime**. The panel starts/stops the
runtime, creates/lists sessions, submits JSON arguments to pinned RPC methods,
streams events, and answers interactive server requests. HTTP and WebSocket
access require the Hub's admin identity. Safe mode disables this runtime.

The same authenticated controls are available to subsequent coding-agent sessions
through `scripts/hermes_control.py`: `status`, `start`, `stop`, `catalog`, `rpc`,
`approvals`, `approve` and `deny`. Load `JARVIS_ADMIN_TOKEN` through a private
environment; the CLI has no credential argument. See [OPERATOR.md](OPERATOR.md)
for setup, exact command examples and interpreting outcomes.

`prepare` downloads and verifies source only. `install` also provisions the
environment and atomically writes a private `runtime.json`. No HTTP endpoint
accepts a source path, executable, upstream URL, shell command for launching, or
an imported profile. The packaged Hub includes the pin, catalog, license notice
and worker bridge files; upstream dependencies remain in the owner's data root.
Provisioning currently runs from the checkout CLI, rather than the frozen Hub.

## Protocol and authorization

The catalog includes every pinned OpenRPC method: **262 client methods, 16
server requests and 78 notification types**. An exhaustive classification file
matches that catalog; new/unclassified methods fail closed. At this pin,
87 read methods have tier 0, 15 session/prompt operations have tier 2, and the
remaining 160 methods retain a tier-3 approval floor. This is a single-owner
operator surface: all authenticated administrators control the same private
Hermes installation. It does not claim multi-user session isolation.

The worker runs Hermes's headless server and wraps its registered RPC handlers
and actual tool/connector dispatch boundaries. Jarvis asks the enabled, live
Kernel before execution. A DENY, QUEUE, unavailable broker, stale generation,
unclassified target or replayed bridge nonce never executes the guarded call.
The classification is server-owned; RPC/tool arguments cannot lower its tier.
Kernel audit payloads include owner, session identifier, target, arguments and
runtime generation. Native Hermes policy and hooks still run inside that gate.

The broker credential is private and removed from the worker environment after
bootstrap. Server-request responses must match a pending request and generation
and are consumed once. Lost RPC replies produce an unknown-outcome error; the
adapter never automatically repeats an accepted mutation. A new connection can
read session history/events or explicitly issue a new request.

The worker accepts only private `/api/ws` and authenticated readiness. Its REST,
PTY, original SPA and plugin HTTP routes are refused: they have separate effect
paths requiring further mediation. `hermes serve` and `hermes dashboard` are
different products surfaces; this integration uses the headless protocol and the
Jarvis HUD. Desktop/device clients and optional integrations still require their
own dependencies, configuration and capability adapters.

## Availability and remaining work

The complete engine is provisioned; catalog coverage does not prove executable
equivalence for every feature. Tier-3 effects now enter the canonical signed
TaskQueue and appear in the Hub's **Action approvals** panel and operator CLI.
An owner decision binds the exact operation, target, arguments, private owner,
session, runtime generation and deadline. Accepted RPCs receive a one-use claim
and live Kernel revalidation before the original native handler executes.
Native tool calls wait in their original call frame; losing that continuation
rejects the card. Generic Hub task runners cannot consume these tasks.

Denial, expiry, kill switch, disabled policy, changed arguments and revoked
generation prevent dispatch. A private completion acknowledgement records the
handler's return; a lost acknowledgement leaves a consumed, unknown outcome and
never triggers an automatic retry. Stopping the runtime revokes its pending
cards. A new runtime cannot use cards from an earlier generation.

The previous pin (`0808ed8`) was exercised with harmless shell execution and a
paused ToolRegistry invocation. The current pin has **not** been installed or
exercised end to end yet (see [Pin 9c0560f8](#pin-9c0560f8-2026-11-10)). Provider-backed turns, payments, real devices,
delegation and optional connector families still need their own configured
dependencies and acceptance probes. No provider credentials are imported.

All **697** Hermes parity contracts remain in scope in the existing inventory.
Adding an upstream runtime does not increase the native-equivalence count or
close unproved rows. Runtime-backed availability and native Jarvis equivalence
must be tracked separately. No provider-cost or real device probe is implicit
in setup or the tests.

## Verification and rollback

The focused suite covers source/archive/executable substitution, private
environment, readiness redirects, failed startup cleanup, replay/generation
checks, unknown targets, Kernel refusal, RPC disconnect/no replay, interactive
responses, authenticated HTTP/WS, concurrent server replies and HUD states.
`tests/test_hermes_runtime_live.py` is an opt-in test of the real pinned runtime
when `JARVIS_HERMES_SMOKE_ROOT` names an already provisioned test installation.

Stop the runtime in Admin, or stop the Hub, to revoke its broker generation and
terminate its owned process group. Disable `JARVIS_HERMES_ENABLED` to remove the
runtime from use while retaining private session data. Keep that profile out of
Git and backups intended for public sharing. The MIT attribution is retained
in `runtime/hermes/NOTICE.md`; upstream's original LICENSE remains in the verified
complete source archive.

## Moving the pin

`python scripts/hermes_runtime.py bump --commit <full sha>` (code in
`scripts/hermes_runtime_bump.py`) is the only supported way to move the pin. It:

1. fetches the archive of the **current** pin and refuses unless its SHA-256 and
   source identity still match the lock, and unless `gateway-catalog.json` is
   exactly what the generator produces from that pin's contract (no hand edits);
2. fetches the new archive from codeload.github.com, checks that the commit
   recorded inside it is the requested one, extracts it with the product extractor
   and computes every lock field the way `distribution.py` verifies them:
   `archive_sha256` (the gzip'd bytes), `tree_sha1` and `source_sha256` (the
   extracted tree, with executable modes restored from `executable-paths.json`,
   itself read from the archive's file modes), `git_tree_sha1` (upstream's tree id,
   from the GitHub API, `--git-tree` or `--git-dir`);
3. regenerates `gateway-catalog.json` from `apps/shared/src/gateway-contract.openrpc.json`
   (methods in contract order with their params schema, server requests and
   notifications verbatim, `contract_sha256` of the file bytes);
4. prints the contract diff with every `$ref` resolved, so a change inside a shared
   schema shows on each method that uses it: methods, server requests and
   notifications added, removed, with changed params, results or summaries;
5. writes the lock, catalog, executable list, `NOTICE.md` and the two code anchors
   (`distribution.PINNED_COMMIT`, `worker.SOURCE_SHA`), and drops policy entries
   for removed methods.

It never classifies. New methods are left out of `rpc-policy.json` and the policy
keeps the previous `source_sha`, so `policy.catalog()` raises "classification is
incomplete" and every Hermes RPC is refused until a reviewer has classified the
new methods from their handlers, re-checked the methods whose params changed and
set `source_sha` to the new commit. Exit status 3 means that review is pending.
`--dry-run` verifies and prints without writing; `--json` prints the full report.

If codeload.github.com is unreachable, `--git-dir <clone>` rebuilds both archives
with `git archive --format=tar --prefix=hermes-agent-<sha>/ <sha> | gzip -n`. That
is accepted only because step 1 must reproduce the pinned codeload SHA-256 of the
current pin byte for byte; the runtime's `prepare` checks the new hash against
codeload again before it extracts anything, so a format difference would fail
closed, never open. The clone needs both commits
(`git fetch --depth 1 origin <old> <new>` is enough).

## Pin 9c0560f8 (2026-11-10)

Moved from `0808ed8` with the bump script in `--git-dir` mode: codeload refused this
environment (HTTP 403), and `git archive | gzip -n` of `0808ed8` reproduced its pinned
codeload SHA-256 (`4174aa76…`) exactly. Lock: `archive_sha256 e8090f15…`,
`tree_sha1 d3f99f48…`, `source_sha256 686a92ea…`, `git_tree_sha1 b7c44de5…`.
The runtime's own `prepare_source` path, pointed at that archive by file URL,
verified it against the new lock. 125 files are executable (102 before).

**Contract diff** (`0808ed8` → `9c0560f8`):

| | added | removed | params changed |
|---|---|---|---|
| methods (251 → 262) | 18 (below) | `browser.controller.detach`, `.heartbeat`, `.register`, `.result`; `onboarding.ensure_setup_profile`, `onboarding.reset_setup_profile`; `profiles.remember_onboarding` | 15 (below) |
| server requests (13 → 16) | `setup_beat`, `theme.apply`, `theme.pick` | — | `preview.act`, `tour` (result: `clarify`) |
| notifications (75 → 78) | `agent.print`, `free_tier.challenge`, `onboarding.ended`, `skills.changed`, `tool.progress`, `voice.partial` | `browser.controller.cancel`, `browser.controller.command`, `layout.apply` | `connection.request`, `connection.update`, `gateway.ready`, `message.complete`, `message.delta`, `message.interim`, `message.start`, `notification.show`, `session.info`, `session.usage`, `tool.complete` |

48 methods changed only their result schema; results do not affect the tier.
Server requests are answered by request id, not by name, so the new ones need no
Hub change; the HUD shows them like the others. The seven removed methods had
tier 3 and were dropped from the policy; nothing in the Hub called them.

**New methods**, classified from their handlers in `tui_gateway/` at `9c0560f8`:

| method | tier | handler and reason |
|---|---|---|
| `billing.keep_going_on_credits` | 3 | `methods_session.py`: `PATCH /api/billing/keep-going-on-credits`; turning it off skips the spending gates. Billing write. |
| `connectors.accounts.rename` | 3 | `methods_connectors_account.py`: renames a connected account at the portal; `creates_guest=True` may mint a guest identity. Credential-adjacent write. |
| `free_tier.challenge_result` | 3 | `methods_free_tier.py`: records a host challenge outcome (`url`, `outcome`) for the free-tier identity. Free-tier write. |
| `free_tier.claim_nudge` | 3 | `methods_free_tier.py`: claims the due sign-in offer, so it is shown once. Free-tier write. |
| `groups.attachment.download` | 3 | `methods_groups.py` → `read_download`: returns a committed room file. File download. |
| `groups.attachment.upload` | 3 | `methods_groups.py` → `store_upload`: stores a file for a later `groups.send`. File upload. |
| `groups.context` | 3 | `methods_groups.py` → `set_room_context`: sets a room's purpose, notes and routing. Write. |
| `groups.continue` | 3 | `methods_groups.py` → `continue_room`: grants a paused discussion another budget of rounds and messages. Spends. |
| `groups.discard` | 3 | `methods_groups.py`: discards an indeterminate room task; at this pin the local handler only refuses, but the contract is a destructive operation. Conservative. |
| `image.render` | 3 | `methods_images.py`: reads any local image file named by `path` and returns its pixels. Arbitrary local file read. |
| `machine.facts` | 0 | `methods_machine.py` → `hermes_platform.host.summary`: OS, CPU, RAM, GPU class, locale; the account's full name is removed. Read only. |
| `onboarding.set_run` | 3 | `methods_onboarding.py` → `set_run`: writes `onboarding.run` to the root `config.yaml`. Onboarding write. |
| `onboarding.skip` | 3 | `methods_onboarding.py`: ends the run record and cancels the waiting `setup_beat` request. Onboarding write. |
| `onboarding.start` | 3 | `methods_onboarding.py`: may claim the free trial, creates or deletes onboarding chats and submits the opening prompt. Free-tier claim, writes, model spend. |
| `onboarding.state` | 3 | `methods_onboarding.py` → `_run_state`: reads the root config, `.env`, `auth.json` and the shared Nous store to decide whether a trial or provider can carry the first chat. Read, but of the credential stores, and onboarding state: conservative. |
| `plugins.catalog.lookup` | 3 | `methods_plugin_catalog.py` → `load_catalog_live`: fetches the published plugin catalogue over the network and rewrites its cache under `HERMES_HOME/cache`. Network plus write: conservative (a candidate for tier 0 after review; `plugins.list`, tier 0, may reach the same refresh). |
| `subagent.roster` | 0 | `methods_subagents.py`: counts live sub-agents and background processes per stored conversation of the requested profile. Read only. |
| `vault.preview.fill` | 3 | `methods_vault.py` → `browser_vault_fill`: reads a saved login from the vault and fills it into a browser tab. Vault and credentials. |

**Methods whose params changed**, re-checked against their handlers (tiers unchanged):

| method | tier | change | still right because |
|---|---|---|---|
| `pet.cells` | 0 | `terminal` (kitty or unicode) | chooses the output encoding of the pet frames; still a read |
| `rollback.list` | 0 | `undo_message_id`, `undo_since` | the handler only lists checkpoints and does not read them |
| `session.events.since` | 0 | `replay_epoch` | compares the replay epoch; still a read |
| `prompt.submit` | 2 | `voice_turn`, `confirm_deep_truncate` | marks a voice turn; the new flag *adds* a confirmation before a history cut that already existed (warn-only at this pin) |
| `browser.manage` | 3 | `use` action and `enabled` removed | narrower |
| `client.capabilities`, `connection.respond`, `connectors.connect`, `file.attach`, `groups.peer.invite`, `groups.retry`, `plugins.manage`, `profiles.create`, `reload.env`, `rollback.restore` | 3 | new fields or actions (`desktop_local`; a `said` answer; `alias`/`connection_id`; `staged_upload`; `status_ttl_seconds`; `member_id`/`execution_generation`; `inspect`, `install_desktop`, `remove_desktop`, `presence`, `update_all`, `auto_update`, `names`; `profile`/`session_id`; `all`), and for `profiles.create` a documented `share_auth` default | already at the approval floor |

**Worker change.** Upstream now calls `dispatch_connector_call(name, args,
tool_call_id, turn_id, task_id)`. The worker's connector guard accepted only three
arguments, so every connector call would have failed with a `TypeError`; it now
forwards the extra arguments unchanged. The other boundaries the worker patches
(`tui_gateway.server._methods`/`register_method`, `ToolRegistry.dispatch`,
`web_server.start_server(..., headless=True, isolated=True)`) are present with the
same shape, and every method module still registers through `register_method`.

**Found, not fixed (also true at `0808ed8`).** `agent/inline_tool_executors.py`
runs a table of tools (`memory`, `session_search`, `todo_list`, `message_agent`,
`clarify`, `manage_connections`, `manage_catalog`, `setup_mcp`, the preview tools,
and new at this pin `set_theme`, `setup_beat`) without going through
`ToolRegistry.dispatch`, so the worker's tool guard does not see them; RPC methods
are still all guarded. Gating them changes how the sidecar behaves (a `memory` or
`clarify` call would wait for approval) and needs a live probe, so it is left for
the governed-availability work rather than slipped into a pin bump.

**Not verified.** `install` (upstream `pm.cli install` of Python 3.14 and the
locked tools) was not run: it needs a large download. Nothing here shows the
runtime starting, answering readiness, or running a call on this pin; the opt-in
`tests/test_hermes_runtime_live.py` is the check for that.
