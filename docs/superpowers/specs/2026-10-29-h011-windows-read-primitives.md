# H011 Windows read primitives

This first unit supplies an isolated read-side foundation for a later native
Windows checkpoint backend. No history/FileTools/maintenance caller imports it;
Windows capture, restore, mutation, GC and the support gate remain unchanged.

The facade opens a local NTFS volume GUID root and descends one validated component
at a time beneath held directory handles. Unsupported volume capabilities, reparse
points, ambiguous names, changed root mappings and mismatched full volume/file IDs
refuse. Bounded reads compare object stamps and exact sizes. The separate ACL
validator requires the current owner and a protected explicit descriptor limited
to owner, SYSTEM and Administrators; it does not modify permissions.

Names and path bounds use strict UTF-16 units. Counted native strings preserve all
UTF-16 bytes and their terminator, including non-BMP characters. Unverified handle
cleanup remains explicit process-local ownership, with bounded failure messages;
it cannot become a clean result merely because another cleanup call failed.

Local fake tests establish control flow only. A focused Windows pull-request job
must pass every test without skips, including generated NTFS paths, reparse/name
changes, private/hostile ACLs, full identities, handle cleanup, and distinct emoji
parent/sibling names. The recorded runner/build/filesystem bounds the native proof.

The implementation plan is [the native-read plan](../plans/2026-10-29-h011-windows-native-primitives.md).
Store creation, locking, SQLite, effects, rollback and eventual production wiring
remain later units. Leaf-ID atomic compare-and-swap is not an invented prerequisite:
later Windows behavior must preserve the actual H011 preimage, anchored scope,
authorization, effect-state, atomic replacement/readback and uncertainty contract.
