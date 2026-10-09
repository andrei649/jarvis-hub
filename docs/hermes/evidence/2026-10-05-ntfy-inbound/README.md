# H099 ntfy local acceptance

The accepted ntfy code contract is implemented: opt-in receiving, configured-topic
identity, shared pairing and Inbox, bounded dedup/reconnect, echo suppression,
and approved replies with revocation/configuration checks through pinned egress.
Real owner server/phone acceptance has not been exercised.

Corrected backend: **23,594 passed**, 34 ordinary skips, one existing xfail,
zero failures/errors across 23,629 cases. Serial frontend: **1,912 passed**.
All 4,689 frozen inputs were unchanged after both runs. The first backend attempt
had nine failures; its sanitized derivative and outcomes are retained alongside
the corrected proof. `report.json` records raw hashes, transformations and boundaries.

Parameterized testcase names are replaced with stable hashes in shared XML;
method/class/outcome/type/timing are unchanged. `frozen-inputs.json` preserves
every original hash as path/hash entries. Strict source and proof scans found no
secrets. No push, merge, deployment, provider call or live worker activation occurred.
The full original 697-capability mission remains active.
