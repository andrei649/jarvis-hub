# H011 Windows private store, lock and SQLite parity spike

Unit 2 adds isolated Windows primitives for a fresh H011 private store on local
NTFS and tests whether ordinary Python SQLite preserves the accepted H011 lock,
claim and uncertainty sequence there. It does not connect Windows history,
FileTools, inventory or maintenance callers. `HISTORY_SUPPORTED` stays false on
Windows. The Unit 1 native read suite passed on published `b5134e9a` in job
`123389933746` (Windows 2025 Server build 10.0.26100, Python 3.12.10 x64,
NTFS flags `65482495`): 40 passed, zero failures/errors/skips. Unit 2 source
work began after this plan's independent fidelity review approved it.

## Private store and lock

Create the store and `history.lock` one component at a time beneath Unit 1 held
directory handles. Creation is exclusive and uses an explicit protected security
descriptor for the current user, with only required SYSTEM/Administrators access.
Never create with a null DACL or adopt a broad generic SnapshotStore. Existing
nodes are accepted only after full file ID, type, single-link where required,
reparse, current-owner ACL and parent/name checks. Unknown capability or an
uncertain close refuses and preserves handle ownership as in Unit 1. The
configured store name and lock name are re-opened against held identities before
and after acquiring the lock.

An exclusive `LockFileEx` byte range stays held for the entire isolated store
operation. Same-thread reentry is keyed by canonical store spelling and complete
`WinFileId`; a same-spelling changed ID refuses. Other processes contend; normal
exit and process death release the lock. This coordinates cooperative H011
writers and does not claim to exclude every same-owner filesystem writer.

## Ordinary SQLite parity

With the private lease held, probe `sqlite3.connect(path)` on a disposable index:
exclusive first creation under the held store, reopen, read-only inventory,
`PRAGMA synchronous=FULL`, and committed `BEGIN IMMEDIATE` transactions. The
store, DB and any `-journal`, `-wal` or `-shm` names are checked at available
pre/post fences for regular local files, full IDs, private ACLs and containment
under the held store. The supported spike mode is SQLite's ordinary `DELETE`
rollback journal. An unsafe reparse, hard-linked or broadly accessible sidecar
refuses; an ordinary private hot journal is allowed so SQLite can recover it.
Record the actual journal mode and sidecar outcomes. SQLite-created sidecars
may inherit restricted ACEs from the protected store; require effective access
only for the current user, SYSTEM and Administrators, without imposing Unit 1's
explicit protected-DACL rule on those sidecars. The store, lock and precreated
index retain that strict rule.

Use synthetic rows and an operation journal to test a separately committed
`running` claim before any synthetic asset effect, exact selected-row comparison
and commit, then an immediate guard transaction across the asset phase. A crash
after claim remains `running` or `uncertain` and is not replayed on restart;
failure after row commit is partial/uncertain. Incomplete bounded inventory,
changed rows/names, revoked authority or failed lock refuses before claim or
stays uncertain after claim. No real checkpoint payload is changed in Unit 2.

At deterministic precheck, connect, claim and guard barriers, substitute the
store, lock, DB or SQLite sidecar name with a disposable alternate or reparse.
Record which connection and rows were used, full IDs and ACLs, claim state,
refusal/uncertainty outcome, and outside sentinel bytes. A detected substitution
must not write the sentinel. The tests do not claim that pathname checks defeat
every uncooperative same-owner race. A connection-file-ID hook, pinned DB handle
or custom VFS becomes a separate reviewed change only if a native probe shows a
concrete Windows-specific containment, locking or durability failure. Leaf-ID
compare-and-swap is likewise outside this unit.

Windows proof uses disposable NTFS trees and two bounded worker processes. The
focused PR job runs every new native case with zero skips, failures and errors;
its report records Windows build, Python version, NTFS flags, exact commands,
file IDs, ACLs, journal mode, rows, crash points and unsupported cases. Passing
Unit 2 does not enable Windows capture, restore, effects, GC, schema migration or
maintenance.

The isolated implementation candidate uses `WindowsHistoryFs` for exclusive
child creation and shared name probes, `WindowsPrivateStore` for the private
store lease, and synthetic tests for ordinary SQLite `DELETE` journal
recovery. Local fake and ABI checks cannot establish the native outcome;
the expanded zero-skip Windows job is the acceptance gate.
