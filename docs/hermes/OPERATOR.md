# Hermes Hub operator guide

The Hub owns the pinned Hermes process, method catalog, identity and Action Kernel checks. Use **Admin → Hermes Runtime** or `scripts/hermes_control.py` to operate it. Both clients call the same admin-authenticated Hub API; neither calls the private Hermes worker directly.

## Prepare the local Hub

Provision the pinned runtime once, outside Git, as described in [RUNTIME_INTEGRATION.md](RUNTIME_INTEGRATION.md):

```bash
export JARVIS_HOME=/absolute/path/to/private/jarvis-data
python scripts/hermes_runtime.py install
python scripts/hermes_runtime.py status
```

Configure any desired provider in the private Hermes profile under `$JARVIS_HOME/hermes-runtime/home`. In the Hub environment, set `JARVIS_HERMES_ENABLED=1`, `JARVIS_ACTION_KERNEL=1`, and `JARVIS_TASK_MEDIATION=enforce`; start the Hub normally. Set the Hub's global autonomy mode to **AUTO** in Admin (the `/autonomy/mode` setting). `off` refuses canonical approval dispatch. Governed approval also requires the Hub's signed IntentLog and canonical TaskQueue in the same private data root; keep their persistent state intact across restarts. The runtime stays default-off without setup, and safe mode disables it. The CLI requires the Hub admin credential in `JARVIS_ADMIN_TOKEN`; load it through your usual private environment or secret manager. The CLI has no token argument and never prints the credential.

## Inspect and operate

Run these from the repository root with the Hub on its default `http://127.0.0.1:8080` address:

```bash
python scripts/hermes_control.py status
python scripts/hermes_control.py start
python scripts/hermes_control.py catalog
python scripts/hermes_control.py rpc session.list
python scripts/hermes_control.py approvals
python scripts/hermes_control.py stop
```

Use `--base-url http://127.0.0.1:PORT` before the command for a different local Hub port. Plain HTTP accepts only a loopback address; an explicitly supplied `https://HOST[:PORT]` origin can be remote and must have a valid TLS certificate. Redirects are refused. The URL cannot contain credentials, a path, query or fragment. Calls are single-attempt, including start, stop, RPC and decisions.

RPC arguments must be a JSON object within the Hub's 128 KiB request limit. Omit `--params-file` for `{}`, or supply a UTF-8 file or `-` to read stdin. Input is read with a size cap before any request is sent:

```bash
python scripts/hermes_control.py rpc session.create --params-file ./session-params.json
printf '%s\n' '{"limit":5}' | python scripts/hermes_control.py rpc session.list --params-file -
```

Consult `catalog` for the method names and required parameters of the installed pin. The CLI prints successful Hub JSON on stdout. On refusal, it prints JSON to stderr and exits nonzero. A queued RPC can return `{"error":"approval_required","status":409,"task_id":17,"disposition":"queued"}`. That is an approval request, not evidence that the operation ran.

## Review a queued action

Open **Action approvals** in Admin → Hermes Runtime, or run `python scripts/hermes_control.py approvals`. Read the task's operation, exact target and JSON arguments before deciding. A task with both `status: "blocked"` and `disposition: "queued"` is decision-ready. Revoked or expired tasks can remain visible but cannot be approved. The Hub can continue to show the task after the original RPC client disconnects.

```bash
python scripts/hermes_control.py approve 17
# or
python scripts/hermes_control.py deny 17
python scripts/hermes_control.py approvals
```

Task IDs are positive integers. Approval applies only to that frozen TaskQueue operation. The Hub rechecks current authority at dispatch and consumes the decision once. `approved` or `running` means execution is still unresolved; inspect the subsequent task status and `result` or `error`. Native JSON-RPC errors are recorded as failed actions; successful results are bounded and redacted. A denial, expiry, stopped or restarted runtime, changed authority, or lost reply may prevent a result. `consumed_outcome_unknown` means the outcome cannot be confirmed; inspect the target before considering a new RPC. Neither the panel nor CLI automatically resubmits a mutation.

The **Event stream** server-request reply form is for Hermes protocol requests and provider or user confirmations. It is separate from the Hub task approval controls. Only the Action approvals list and the `approve`/`deny` commands decide governed queued actions.

## After the pin moves

When a Hub update moves the Hermes pin (the CHANGELOG says so), stop the runtime in Admin, then run `python scripts/hermes_runtime.py install` again. The old source tree no longer verifies; `install` moves it aside to `$JARVIS_HOME/hermes-runtime/source.stale-<time>` (delete it once the new install works), downloads and verifies the new pin, and lets upstream's PM update the private environment. Your private Hermes home and its sessions stay. Until you reinstall, `status` reports a stale source identity and the runtime does not start.

## Move the pin (maintainers)

The pin changes only through the bump script, in a branch, with a reviewer:

```bash
python scripts/hermes_runtime.py bump --commit <full 40-character sha> --dry-run   # check and read the diff
python scripts/hermes_runtime.py bump --commit <full 40-character sha>             # write it
```

1. The script refuses before writing anything if the current pin's archive no longer matches its SHA-256 or source identity, if `gateway-catalog.json` was edited by hand, or if the new archive records a different commit. Read the reason; do not edit the lock to get past it.
2. It writes `runtime/hermes/upstream.lock.json`, `gateway-catalog.json`, `executable-paths.json`, `NOTICE.md`, `distribution.PINNED_COMMIT` and `worker.SOURCE_SHA`, drops policy entries for removed methods, and prints the diff: methods, server requests and notifications added, removed, or with changed params, results or summaries.
3. Exit status 3 means review is pending, and every Hermes RPC is refused until it is done. For each method under **UNCLASSIFIED**, read its handler in the new source (`tui_gateway/`) and add a tier to `runtime/hermes/rpc-policy.json`: 0 read only, 2 a session or prompt operation, 3 anything that writes, spends, sends, moves files, touches credentials, vault, billing, free-tier or onboarding state, or runs code. When unsure, 3. Re-read each method under **RE-CHECK** (its params changed) and confirm its tier.
4. Set `source_sha` in `rpc-policy.json` to the new commit. This is your sign-off; the runtime keeps failing closed until it matches.
5. Add the tier table with one reason per method to `docs/hermes/RUNTIME_INTEGRATION.md`, update the counts and the pinned commit in `tests/test_hermes_runtime_policy.py` and `tests/test_hermes_runtime_distribution.py`, and check that the worker's patched boundaries (`tui_gateway.server`, `ToolRegistry.dispatch`, `tools.connectors.dispatch_connector_call`, `hermes_cli.web_server.start_server`) still have the same shape upstream.
6. Run `pytest tests/test_hermes_runtime_*.py`. Before claiming the runtime works on the new pin, run `install` and the opt-in live test (`JARVIS_HERMES_SMOKE_ROOT=… pytest tests/test_hermes_runtime_live.py`).

If codeload.github.com is unreachable, add `--git-dir <clone>` (a clone holding both commits, e.g. after `git fetch --depth 1 origin <old> <new>`). The script then builds the archives with `git archive | gzip -n`, and accepts them only if the current pin's rebuilt archive matches its pinned codeload SHA-256 byte for byte. `--git-tree <sha>` supplies upstream's tree id when the GitHub API is unreachable too.
