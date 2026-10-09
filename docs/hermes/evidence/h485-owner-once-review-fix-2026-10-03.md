# Owner-once final review correction

An independent Sol High read-only review of the owner-once increment found one
important issue: a native DENY could commit while a generic notification waited
in the attention broker. A trusted live owner invocation deliberately retains
BLOCKED for its separate once/reject prompt, so the broker's ordinary pending-row
check could still send the generic four-choice card after DENY.

The first guarded full run was stopped with SIGINT (terminal exit 2) before any
frozen source was modified. Its partial execution is not a passing full suite.
The notification regression then reproduced one failure among three cases:
live-origin DENY sent an obsolete card; unattended DENY and ESCALATE were controls.
The worker now rechecks the exact terminal denial in the broker callback before
calling the notifier. A send already in flight cannot be recalled by this check.

After the correction, all 15 notification-module cases passed. The integrated
guardian/owner-once/Telegram/kernel/worker/transport regression union passed
1,341 cases, with 8 skipped and zero failures/errors. The
[source-bound record](h485-owner-once-review-fix-2026-10-03.json) pins the 34 changed
Python source/test files and the RED-to-GREEN counts. Earlier actuation and
mutation records retain their own earlier snapshots.

The reviewer found no other concrete issue in the bounded pass. Live Telegram,
model providers, SSH, Docker and hardware acceptance were explicitly not judged;
those remain unverified and required where applicable. H277/H485 stay partial.
This correction neither changes unrelated capabilities nor authorizes publication.

Next action: regenerate the two affected partial reviews, freeze the revised
source/configuration, and run the guarded full backend against 21,973 collected
cases. No full-suite result for this corrected snapshot is claimed here. No push,
merge, deployment, paid-provider call or runtime activation occurred.
