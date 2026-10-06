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
