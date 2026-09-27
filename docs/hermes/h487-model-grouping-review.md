# H487 generic model notification grouping review

Generated 2026-09-27; base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus preserved local changes. Goal: review the model producer extension in
`approval_grouping.py`, `tool_rpc.py`, `worker.py` and `queue.py` before integration.
Next action: bounded human-wait accounting; standing grants remain separate.
Full backend passed 19,226 tests with 35 skips. A low-severity Bandit finding
then replaced silent provenance failure with explicit `context = None`; all 101
affected integration tests and scoped scans passed afterward. This final one-line
fallback was not followed by another full backend run. The unchanged frontend
retains its preceding 1,822-test snapshot.

The generic gated ToolRPC branch mints the context inside its existing verified
tool approval scope. The context requires the same live turn, thread and async
task, and a still-current private registration epoch. Arguments cannot supply
these values. Closing the producer invalidates copied contexts. Specialized
intakes and raw queue fallbacks remain outside this path.

The worker registers only after policy, taint, kernel handling, persisted receipt
and the initial BLOCKED compare-and-set. The queue rechecks the stored actor,
tool and canonical arguments inside its existing membership transaction. It
includes the finalized request, policy and receipt authority category in equality;
every member retains its own full snapshot and independent receipt. Notification
grouping never substitutes for an execution grant. Metadata exceptions preserve
the already-persisted independent ask and its task ID.

The independent integration tests exercise the actual ToolRPC-to-worker path:
one visible card with two pending IDs, principal/session/instance/actor/registration/
policy/taint/argument isolation, once-only decision and execution, signed receipts,
promotion, stale membership, restart and expiry. The implementation tests also
cover metadata failures and mutated finalized arguments. Neither suite calls a
live provider or grants a real permission.

Shared evidence review is limited to this localized extension. H277's judge
scheduling and independent receipts, H513's tool-profile
and provider-policy boundaries, and H595's code execution authorization are
unchanged. Only those current reviews and H487 may refresh their affected source
hashes. Older stale reviews (including H506, despite unchanged classifier labels
in this increment) are not silently revalidated.

H487 remains partial: shared session/always/deny adoption, additional proven
producers and bounded human-wait accounting need separate implementation.
The legacy permission ledger is not a safe source of model authority: disabled
lookup returns allow and its session key means process boot. Durable always
consent also needs a deliberate registration-version contract; a random process
epoch cannot honestly promise reuse after restart.
