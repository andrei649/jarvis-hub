# Troubleshooting — diagnose a broken install from a symptom

> For the owner, or whoever helps them, **without a screen-share**: every step below is a
> command whose output can be pasted into a message. Start with the
> [recovery sequence](#recovery-sequence); if you already know the symptom, jump to the
> [symptom table](#symptom-cause-fix). `nerva doctor` links the section that fits each red
> row (`see docs/TROUBLESHOOTING.md#…`). Every command, setting and route named here is
> checked against the code by `tests/test_troubleshooting_docs.py`.
>
> Settings are read and changed with `nerva config get llm.default_model` /
> `nerva config set llm.temperature 0.7` — every `category.key` setting the same way — or
> in **Admin → settings** in the HUD. The online
> verbs need the hub running and a token in the shell: `JARVIS_ADMIN_TOKEN` (or
> `JARVIS_USER_TOKEN` for the user-level reads).

## Recovery sequence

Always in this order — each step assumes the ones before it passed. Stop at the first step
that fails and fix that one; the later steps would only report its consequences.

1. **Check the install.** `nerva doctor` (or `python scripts/doctor.py` when the CLI itself
   will not start). Any `FAIL` row (`python`, `venv`, `locks_in_sync`, `bind_is_loopback`,
   `data_root_writable`) means the hub cannot start — fix it first. `python_too_old:…` →
   install Python 3.12+. `venv_missing` or a `lock_stale:` / `lock_missing:` row: re-run
   `python scripts/bootstrap.py`. `source_missing:…` → a `requirements*.txt` the lock is
   built from is gone from the checkout: restore it (`git status` shows it deleted), then
   re-run the bootstrap.
2. **Is the hub up?** The `readyz` row: `server_not_running` → start it with
   `python serve.py`; `readyz_status:503` → it is still starting or a dependency is not
   ready (`GET /readyz` says which); `hub_url_invalid` → fix `NERVA_HUB_URL`;
   `readyz_bad_reply` → something listens on the hub's port but does not answer HTTP:
   another program holds `JARVIS_PORT`, or `NERVA_HUB_URL` points at the wrong port.
3. **Does the model route resolve?** The `runtime_resolves` row, or `nerva status`
   (its `runnable:` line). Anything but `resolves:PROVIDER/MODEL` → the
   [local model servers](#local-model-servers) section, or the cloud rows of the
   [symptom table](#symptom-cause-fix).
4. **Does a turn complete end to end?** `nerva chat -z "say hello"`. Exit 0 with an answer
   is a working install; exit 1 names why the turn did not complete; exit 2 is a usage
   error (the prompt is too long, or a flag that needs an image); exit 3 is no hub; exit 4
   is not authorised — the hub refused the token, or none was sent: set
   `JARVIS_USER_TOKEN` (or `JARVIS_ADMIN_TOKEN`). The CLI withholds `JARVIS_ADMIN_TOKEN`
   over plain http to another machine — the message says so; see
   [Permissions](#permissions).
5. **Does it boot without your customizations?** `python serve.py --safe-mode` leaves out
   every skill, MCP server, plugin, overlay and job you added. If the problem disappears,
   one of those is the cause: re-add them one at a time (`nerva skills list`,
   `nerva jobs list`).
6. **Read the log.** `nerva logs -n 100` prints the newest records, redacted (offline; a
   traceback counts as one record).
7. **Run the full smoke.** `nerva doctor --smoke` boots a throwaway hub and runs one fake
   turn (~30 s). If it passes while your hub fails, the difference is your data root or
   configuration: `nerva config check` validates every stored value. If the `smoke` row
   warns: `smoke_failed` → the throwaway hub exited non-zero or reported a failed turn; the
   row's detail is the last line of its error output — usually a broken venv, so re-run
   `python scripts/bootstrap.py` and run the smoke again. `smoke_output_unparseable` → the
   smoke printed no readable result (a crash before it reported); re-run the bootstrap,
   then `nerva logs -n 100`. `venv_missing` → the smoke runs in the venv: bootstrap first.
8. **Hand it over.** Paste `nerva doctor --json` plus `GET /api/support/bundle` (admin; an
   allow-listed, non-sensitive snapshot: version, posture, readiness counts, audit counts
   — never content, keys or tokens). If an upgrade caused it, restore the pre-upgrade
   backup ([MAINTENANCE_RUNBOOK](MAINTENANCE_RUNBOOK.md) §4).

## Symptom, cause, fix

| Symptom | Cause | Fix |
|---|---|---|
| `runtime_resolves` ok: `resident` or `cloud_selected` | the route works: the local model is loaded, or the cloud provider accepted the key | nothing to fix here — look further down this table |
| `nerva doctor` row `python` FAIL (`python_too_old:…`) | interpreter below the 3.12 floor | install Python 3.12+, then `python scripts/bootstrap.py` |
| row `venv` FAIL (`venv_missing`) or `locks_in_sync` FAIL | no `.venv`, or a `requirements*.lock` out of sync with its `.txt` | `python scripts/bootstrap.py` (re-creates the venv from the locks) |
| row `bind_is_loopback` FAIL (`non_loopback_without_token`) | `JARVIS_HOST` names a LAN address and no token is set: the hub refuses to boot | unset `JARVIS_HOST`, or set `JARVIS_ADMIN_TOKEN` before exposing it |
| row `data_root_writable` FAIL (`data_root_not_writable`) | the data root (`JARVIS_HOME`, else `memory_logs/`) is read-only or on a full disk | fix the folder's permissions / free space, or point `JARVIS_HOME` at a writable folder |
| HUD does not load; `readyz` = `server_not_running` | the hub is not running, or listens on another port | `python serve.py`; check `JARVIS_PORT` / `NERVA_HUB_URL` match what you open |
| `readyz` = `readyz_status:503` for minutes | a boot dependency is not ready | `GET /readyz` names it; `nerva logs -n 100` shows why |
| `runtime_resolves` = `needs_token` | the route read is user-guarded | set `JARVIS_USER_TOKEN` (or `JARVIS_ADMIN_TOKEN` for a hub on this machine) |
| `runtime_resolves` = `hub_unreachable` / `malformed_reply` / `command_center_status:500` | the hub died mid-reply, or something else listens on its port | `nerva logs -n 100`; restart with `python serve.py` |
| `runtime_resolves` = `cloud_auth_failed` / `cloud_forbidden` / `cloud_refused` | the cloud provider rejected the key the route uses | replace the key in **Admin → settings**, or route locally: `nerva config set llm.cloud_fallback never` |
| `runtime_resolves` = `cloud_not_configured` | a cloud route was chosen but holds no key | add the provider's key, or `nerva config set llm.cloud_fallback never` |
| `runtime_resolves` = `cloud_rate_limited` (still ok) | the provider answered 429; turns wait, the key stands | wait, or lower cloud use with `llm.daily_cost_cap_usd` |
| `runtime_resolves` = `cloud_unreachable` / `cloud_error` / `cloud_no_listing` | the provider said nothing usable about the key (network, outage, no model list) | check the network; `GET /api/security/posture` shows the egress policy |
| `runtime_resolves` = `hub_url_invalid` | `NERVA_HUB_URL` (or `JARVIS_HOST` / `JARVIS_PORT`) does not make a valid address | fix `NERVA_HUB_URL`, as in step 2 of the [recovery sequence](#recovery-sequence) |
| `runtime_resolves` = `route_unselected` / `provider_unresolved` / `router_unavailable` | no route chosen, an indirect fallback, or the router did not start | `nerva config get llm.backend_type`; set it to `lm-studio` or `ollama` explicitly; restart |
| `runtime_resolves` = `unreported` | the hub answered "not ready" without naming why — an older or partly started hub | restart with `python serve.py`, then re-run `nerva doctor`; `nerva logs -n 100` if it stays |
| `runtime_resolves` = `inventory_unavailable` / `residency_unknown` | the runtime would not list its loaded models | see [Ollama](#ollama) / [LM Studio](#lm-studio) |
| replies say "LLM unavailable" / degraded bubble | the local server stopped or the model was unloaded; or, with the tool loop on, an Ollama model without tool support (the log says "does not support tools") | [local model servers](#local-model-servers); for the tools case the "model has no tool support" row under [Ollama](#ollama) |
| answers got worse, shorter or forgetful | wrong model, truncated context, or a fallback | the ["feels dumber" checklist](#my-agent-feels-dumber) |
| forgot what I told it last week | memory is off (it is by default), the fact was never written, or it was written after this session started | step 11 of the ["feels dumber" checklist](#my-agent-feels-dumber) |
| `voice` = `voice_command_not_ready` | a TTS/STT command provider is configured but not armed, changed since approval, missing, or safe mode is on | the row names which; re-approve it in **Admin → settings** |
| `voice` = `capabilities_status:401` / `capabilities_status:403` | the hub refused the voice read: a hub reached from another machine may want a token, and the doctor sends `JARVIS_ADMIN_TOKEN` only to a hub on this machine | set `JARVIS_USER_TOKEN` (or `JARVIS_ADMIN_TOKEN` for a hub on this machine) |
| `voice` = `capabilities_status:500` (any other code) / `hub_unreachable` / `malformed_reply` | the hub failed the voice read, died mid-reply, or something else listens on its port | `nerva logs -n 100`; restart with `python serve.py` |
| `config_sources` = `env_not_utf8:…` / `withheld_env_names:…` | a `.env` file is not UTF-8, or holds a mis-quoted multi-line value | re-save the file as UTF-8; quote the multi-line value |
| `config_sources` = `provenance_unavailable` / `provenance_unavailable:…` | the doctor could not load the hub's configuration code to build the table — a broken or partial install | `python scripts/bootstrap.py`, then re-run `nerva doctor`; the rest of the report is unaffected |
| `model_roles` = `model_roles_attention:…` | a role's provider is unknown/unsupported, or a variable is ignored | the row names the variable; fix it, see the [checklist](#my-agent-feels-dumber) |
| a scheduled job did not fire / did not arrive | timing, delivery, permission or skill problem | the [scheduled jobs tree](#scheduled-jobs) |
| autonomy did something unwanted | — | `nerva estop engage --reason "investigating"`, or `POST /api/security/kill-switch`; `nerva estop resume` lifts it |

## "My agent feels dumber"

Quality regressions are almost always configuration, not the model getting worse. Check in
this order — the first ones are the most common and the cheapest to rule out:

1. **Is it the model you think it is?** `nerva status` (`model:` and `runnable:` lines) and
   the doctor's `runtime_resolves` row (`resolves:PROVIDER/MODEL`). A swapped default
   (`nerva config get llm.default_model`) or the wrong backend
   (`nerva config get llm.backend_type`) is the most common cause.
2. **Did routing degrade to a smaller model?** Over the daily cloud cap
   (`llm.daily_cost_cap_usd`) routing degrades to local; prompts above
   `llm.hybrid_local_max` input tokens leave the local model; `llm.cloud_fallback` decides
   whether a cloud model may stand in. Check all three with `nerva config list llm`.
3. **Is the context window truncated?** On Ollama, a model without a `num_ctx` parameter
   runs at the server's small default and silently drops the start of the conversation:
   set `nerva config set llm.ollama_num_ctx 32768`. On LM Studio the context length is
   chosen when the model is loaded — reload it with a larger one.
4. **Is the fixed prompt eating the window?** `nerva prompt-size --window 8192` (use your
   model's window) compares what a fresh turn costs before anyone speaks against the
   window. A floor near the window leaves no room for the conversation.
5. **Is the answer length capped?** `llm.max_tokens` (0 = auto: the loaded model's context)
   — a small value cuts answers short. `nerva config set llm.max_tokens 0`.
6. **Sampling and reasoning.** `llm.temperature` (default 0.7; high values ramble) and
   `llm.reasoning_effort` (empty asks for nothing; cloud models only).
7. **Are its tools and skills there?** `nerva inspect jarvis --section tools` and
   `nerva inspect jarvis --section skills`; a skill switched off shows in
   `nerva skills list`. The agent tool loop is opt-in: `llm.tool_loop_enabled`. With it on,
   two symptoms point at the model rather than the tools. On Ollama, a model without tool
   support fails every turn with "The local Ollama model can't call tools" (the hub log
   says "does not support tools") — see the "model has no tool support" row under
   [Ollama](#ollama). A reply that shows a tool call as text (`{"name": …, "arguments": …}`)
   instead of running it means a model that takes tools wrote the call into its answer —
   see the "tool calls appear as text" rows under [local model servers](#local-model-servers).
8. **Is it in safe mode?** Safe mode drops your skills, overlays and the memory a turn is
   given. `GET /healthz` says so; restart without `--safe-mode`.
9. **Is a role pointed somewhere unexpected?** The doctor's `model_roles` row lists which
   model does which job (deep, vision, approval judge); `model_roles_attention:…` names the
   role whose provider is unknown or unsupported, or whose variable is ignored — fix that
   variable. On LM Studio
   `JARVIS_ROLE_APPROVAL_JUDGE_MODEL=active` reuses the loaded model instead of loading a
   second, smaller one next to it.
10. **Is the session simply long?** A long conversation is compacted; start fresh with
    `/new` (the `sessions.reset_triggers` setting), or
    `nerva sessions continue SESSION_ID --request-id REQUEST_ID` to carry the retained
    context into a new session.
11. **Did it forget something you told it?** Memory is a few selected facts, not a
    transcript: two bounded rings — the agent's notes and your profile, 20 facts each —
    shown to every turn. Both need `cognition.enabled` (the cognition master switch, off
    by default) and `cognition.memory_enabled`. A fact gets in only when it is written:
    by the model's `memory` tool (your own turns in the HUD or the voice loop, with
    `llm.tool_loop_enabled` on; a full ring refuses the add rather than dropping the
    oldest fact), or by the per-turn review (`cognition.review_enabled`, off by default).
    The rings a turn sees are frozen for the session and the day, so a fact written now
    reaches the prompt at the next session (`/new`) or the next day. `GET /api/memory/core`
    lists both rings — check the fact is there. A turn that has read untrusted content (an
    inbound message, web text, a tainted recall) cannot write memory: the tool refuses with
    `memory_untrusted_turn`, so tell it the fact again in a fresh turn of your own. Older conversations are a separate,
    searched store: `memory.recall_enabled` (off by default) adds the
    `memory.recall_top_k` best hits to a turn, and only what was stored is found —
    `MEMORY_EMBED_TURNS=true` stores every turn, `POST /api/memory/remember` one fact;
    `GET /api/memory/search` (with `q`) shows what a recall would find.

## Local model servers

Two rows of the doctor look at the servers, and they look at different addresses:

- The `runtimes` row probes the **default loopback ports only** — Ollama at
  `127.0.0.1:11434`, LM Studio at `127.0.0.1:1234` — whatever the settings say. Its detail
  reads `ollama=…;lm_studio=…`. `no_local_runtime` means neither answered there.
- The `runtime_resolves` row is the hub's own verdict, made with the addresses the hub uses:
  `llm.ollama_url` / `llm.lm_studio_url` (environment overrides: `JARVIS_OLLAMA_URL` /
  `JARVIS_LM_STUDIO_URL`); `llm.backend_type` picks one (`auto`, `lm-studio`, `ollama`).

So a server on a custom port shows `=connection_refused` in `runtimes` even when the
setting is right — trust `runtime_resolves` then. And a wrong `llm.*_url` shows as
`runtimes` ok with `runtime_resolves` = `provider_offline`.

| Failure mode | What you see | Fix |
|---|---|---|
| no server on the default ports | `runtimes` = `no_local_runtime` | start Ollama or LM Studio; if one runs on a custom port, check `runtime_resolves` instead |
| the probe itself broke | `ollama=probe_error:…` / `lm_studio=probe_error:…` (the exception's name) | a local firewall or proxy intercepts loopback; re-run, then check `runtime_resolves` |

### Ollama

| Failure mode | What you see | Fix |
|---|---|---|
| server not running | `ollama=connection_refused`; `runtime_resolves` = `provider_offline` | start `ollama serve` (or the Ollama app) |
| wrong address / port in the setting | `ollama=ok` (or Ollama runs elsewhere) but `runtime_resolves` = `provider_offline` | `nerva config get llm.ollama_url`; set it to where Ollama listens: `nerva config set llm.ollama_url http://127.0.0.1:11434` (or `JARVIS_OLLAMA_URL`) |
| server busy or hung | `ollama=timeout` | the server is loading a large model or out of memory; wait, then restart it |
| server error | `ollama=http_status:500` (any `ollama=http_status:` code) | the Ollama log names it — usually a corrupt model file: re-pull it. A chat turn refused with "does not support tools" is not a corrupt file: see "model has no tool support" below |
| model not pulled / not loaded | `configured_not_resident` (the detail lists `resident=` models) | `ollama pull MODEL`, or switch to a resident one: `nerva config set llm.default_model MODEL` |
| no model list | `inventory_unavailable` / `residency_unknown` | an old Ollama, or a proxy in the way; update Ollama |
| context silently truncated | the agent forgets the start of the conversation | `nerva config set llm.ollama_num_ctx 32768` (0 = the model's own `num_ctx`) |
| slow first reply after idle | the model was evicted to make room | Nerva pins its model on warm-up; keep other Ollama clients from loading models next to it |
| model has no tool support | with `llm.tool_loop_enabled` on, every turn answers "⚠️ The local Ollama model can't call tools. Pick a model whose `ollama show` lists tools, or turn the tool loop off: nerva config set llm.tool_loop_enabled false", and `nerva logs -n 100` shows `server said: {"error":"MODEL does not support tools"}` (Ollama refuses a chat that offers tools to such a model) | `ollama show MODEL` lists `tools` under Capabilities when the model has them — pull a model that does and `nerva config set llm.default_model MODEL`, or switch the loop off: `nerva config set llm.tool_loop_enabled false` |
| tool calls appear as text instead of running | with `llm.tool_loop_enabled` on, the reply holds JSON like `{"name": …, "arguments": …}` and nothing ran | the model takes tools (`ollama show MODEL` lists `tools`) but wrote the call into its answer instead of making it — its template and Ollama's parser disagree, or the model is too small to follow the format: update Ollama and re-pull the model, use a larger or instruct variant, or switch the loop off: `nerva config set llm.tool_loop_enabled false` |

### LM Studio

| Failure mode | What you see | Fix |
|---|---|---|
| app open but server off | `lm_studio=connection_refused`; `provider_offline` | **Developer → Start Server** in LM Studio, or ask in chat "start LM Studio" (needs `llm.control_enabled` and `llm.chat_control`) |
| wrong address / port in the setting | `lm_studio=ok` (or the server runs elsewhere) but `runtime_resolves` = `provider_offline` | `nerva config get llm.lm_studio_url`; set it to where the server listens: `nerva config set llm.lm_studio_url http://127.0.0.1:1234` (or `JARVIS_LM_STUDIO_URL`) |
| server busy | `lm_studio=timeout` | a model is loading; wait |
| server error | `lm_studio=http_status:500` (any `lm_studio=http_status:` code) | the LM Studio developer log names it; reload the model |
| no model loaded | `configured_not_resident` / `residency_unknown` | load the model named by `llm.default_model`; a model unloaded mid-turn is retried once so LM Studio can load it on demand |
| context length too small | short memory, cut-off answers | reload the model with a larger context length; keep `llm.max_tokens` at 0 so answers use it |
| two models fighting for VRAM | slow turns, out-of-memory | `JARVIS_ROLE_APPROVAL_JUDGE_MODEL=active` reuses the loaded model for the approval judge |
| tool calls appear as text instead of running | with `llm.tool_loop_enabled` on, the reply holds JSON like `{"name": …, "arguments": …}` and nothing ran | the model has no native tool calling: update LM Studio and load a model it marks as tool-capable, or switch the loop off: `nerva config set llm.tool_loop_enabled false` |

## Scheduled jobs

Start every job problem with `nerva jobs doctor` (admin; `GET /api/jobs/doctor`): it exits
non-zero while `problems` is not empty, and each problem names a code. Then follow the
branch for that code. `nerva jobs status JOB_ID` and `nerva jobs runs JOB_ID` show one
job's configuration and its last attempts.

### Timing

- `scheduler_not_running` / `scheduler_unreadable` — the scheduler is stopped. Is the hub
  in safe mode (`GET /healthz`)? Safe mode puts no owner job on the scheduler: restart
  without `--safe-mode`. Otherwise restart the hub. While it is down, `nerva jobs tick`
  fires due jobs once by hand (it refuses while the scheduler runs).
- `not_registered` — the job is active but not on the scheduler: `nerva jobs pause JOB_ID`
  then `nerva jobs resume JOB_ID` re-arms it.
- `missing_next_run` / `invalid_next_run` — the schedule produced no usable next time:
  re-enter it with `nerva jobs edit JOB_ID --when "every weekday at 7"` (plain words or a
  five-field cron).
- `overdue` — the next run is in the past: the hub was asleep or blocked at that slot. There
  is no catch-up burst; it fires at the next slot, or `nerva jobs run JOB_ID` now.
- `health_recording_failed` — the scheduler could not save its outcomes (a full disk or a
  read-only data root): the doctor's `data_root_writable` row says which.
- `last_run_failed` — the last run raised or reported failure: `nerva jobs runs JOB_ID`
  shows the attempts, `nerva logs -n 100` the error.
- `last_run_missed` — the slot passed while the hub was down or the machine slept.
- `last_run_max_instances` — the previous run was still going; make the schedule sparser.
- **Fires at the wrong hour** — schedules use the scheduler's time zone, which is the
  machine's (`scheduler.timezone` in the doctor output). Fix the machine's time zone (or
  `TZ` for the service) and restart.
- **Did not fire right after creation** — by default only an ask, brief, task or script
  job on an interval cadence fires at once, and not during quiet hours or when its first
  slot is near; a calendar schedule, a reminder or a repeat-limited job waits for its
  first slot. `--first-run` on `nerva jobs create` fires a recurring job once now — never a
  one-shot job, which runs only at the time it was given. `nerva jobs run JOB_ID` fires an
  existing one.
- **A one-shot job stopped counting as runnable after it fired** — expected, not a failure:
  a one-shot runs once. It stays in `nerva jobs list` with its last run, leaves the header's
  runnable count and the scheduler, and `nerva jobs doctor` no longer checks it; running it
  again is skipped with "one-shot already ran". Create a new one for another time.
- **Paused itself** — after 3 consecutive failures a job pauses: `nerva jobs incidents`
  lists them; fix the cause, then `nerva jobs resume JOB_ID`.

### Delivery

- `channel_unavailable` — the job delivers to a channel that is not connected (the default
  is telegram). Connect it in **Admin → settings**, or deliver elsewhere:
  `nerva jobs edit JOB_ID --options '{"deliver":["ntfy"]}'` (`[]` disables delivery).
- `last_delivery_failed` — the channel refused or the transport failed: test the channel
  with `nerva send --channel telegram "test"` and read `nerva logs -n 100`.
- **Delivered but never seen** — the channel accepted the message and the target dropped
  it: the Telegram bot must be allowed to post in the target group or channel (in a
  channel, an admin with permission to post; in a group, not muted or restricted).
  `nerva send --channel telegram "test"` posts to the configured Telegram destination
  (`nerva send --list telegram` shows it) with no model call: if the test does not arrive
  either, the bot cannot post there, or the destination is not the chat you read.
- **Ran but nothing arrived at night** — during quiet hours (`ambient.quiet_hours_start` to
  `ambient.quiet_hours_end`) a job's message is held and delivered after; `nerva jobs list`
  says how many are held.
- **Urgent push did not arrive** — the daily interrupt budget (`autonomy.interrupt_budget`,
  default 4) is spent; the message waits.
- **Nothing is delivered at all** — the emergency stop holds delivery and job runs:
  `nerva estop status`.

### Permissions

- **`nerva jobs list` answers 401/403** — the jobs routes are admin-only: set
  `JARVIS_ADMIN_TOKEN` in the shell. Against a hub on another machine over plain http the
  CLI withholds `JARVIS_ADMIN_TOKEN` (it would cross the network in clear text) and says
  so: point `NERVA_HUB_URL` at an https address, or run the verb on the hub itself.
- **A script job waits** — a script needs a fresh approval on every run:
  `nerva approvals list`, then `nerva approvals accept 42` (the task id from the list).
- `script_unavailable` / `script_required` / `workdir_unavailable` — the script is missing
  or refused, `no_agent` was set without a script, or the working folder is not an approved
  one; the problem's reason names which. `nerva jobs status JOB_ID` shows the options to
  correct with `nerva jobs edit JOB_ID`.
- **Create/edit refused with a model warning (409)** — a pinned model is expensive or its
  vendor may train on prompts: rerun with `--confirm-expensive` or
  `--acknowledge-training` if you mean it.
- **Job ran but did nothing** — the emergency stop pauses new autonomous work:
  `nerva estop status`, then `nerva estop resume`.

### Skill loading

- `toolsets_unavailable` — the job names a toolset that is not installed. The doctor output
  lists the installed `toolsets`; reset with `nerva jobs edit JOB_ID --toolsets default`.
- **The skill the job needs is not used** — a job cannot pin skills (`skills` is listed under
  `unsupported_options`); it gets the skills its agent has with no human present:
  `nerva inspect jarvis --as internal --section skills`.
- **The job cannot use a tool the chat can** — a job runs with no human present (the
  `internal` posture): approval-bound tools — `file_write`, `file_delete`, `terminal_run`,
  `video_analyze`, desktop control — are offered only when `llm.internal_actuation` is on;
  the `memory` tool is never offered (only your own turns write memory). A job's toolsets
  are picked from a fixed list — `basic`, `files`, `terminal`, `video` — with no
  execute_code, delegation or plugin groups, and they only narrow what the posture allows.
- **The skill is switched off** — `nerva skills list` shows where each is off;
  `nerva skills on SKILL_NAME` switches it back.
- **The skill does not load at all** — a malformed `SKILL.md` is refused at discovery:
  `nerva skills lint PATH` names the error.
- **Only shipped skills appear** — the hub is in safe mode; restart without `--safe-mode`.
