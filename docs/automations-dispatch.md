# Manual automation runs

`nerva jobs run JOB_ID` now accepts a durable request rather than waiting for the model or effect inside the HTTP request. It prints a receipt ID. Inspect it with:

```
nerva jobs status JOB_ID --request RECEIPT_ID
```

The Automations page displays acceptance, restores outstanding receipts when reopened, and polls until the outcome is known. `queued` means the dispatcher has not claimed it; `running` means firing started; `waiting` means the existing script/monitor approval or execution is pending. `completed` includes the actual run status, which may still be skipped or failed. `unknown` never means success and is never automatically replayed. `cancelled` means the queued job was deleted or its configuration changed.

Manual runs preserve the existing explicit override of pause/disable. They still obey repeat limits, e-stop, interrupt budgets and per-effect approvals. Repeated clicks while a receipt is outstanding return the same receipt. The dispatcher runs every five seconds while the scheduler is active. With the scheduler stopped, requests remain queued; the existing offline `nerva jobs tick` drains them. No new standing execution authority is granted.

The store retains up to 200 finished receipts and 256 outstanding requests. A request claimed before a crash becomes unknown after restart; unclaimed requests remain queued. Deleting an executing job cannot retract an effect already underway. Its receipt is marked unknown if deletion is observed when execution returns. Effects are not replayed to guess the outcome.

API callers receive HTTP 202 and `request` from `POST /api/jobs/{job_id}/run`. This receipt is distinct from an eventual `run`. Read it through `GET /api/jobs/{job_id}/requests/{request_id}`; both routes require the existing admin guard. An unavailable or stopped scheduler is not proof of completion.
