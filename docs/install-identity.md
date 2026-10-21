# Installation identity and profiles

One installation has one durable 32-character lowercase hexadecimal identity.
Default and named profiles share `<install root>/install_id`. The install root
uses the existing `JARVIS_HOME`, `JARVIS_MEMORY_DIR`, user-home or packaged-home
selection before the profile suffix is applied.

A named profile still stores its settings, memory, pairing records, secrets,
`.env` and `hub.lock` under `<install root>-profiles/<name>`. Sharing a machine
identity does not share these stores or credentials. Each profile may run its
own hub; a second process on the same profile root is refused. An invalid
profile name stops resolution instead of selecting the default profile.

On upgrade, a valid canonical identity wins and remains unchanged. When no
canonical file exists, the shared publication lock protects legacy discovery:
one unique valid ID in direct profile directories is adopted; with no legacy
ID, a new ID is written atomically and read back. Conflicting, malformed,
unreadable or symlinked legacy state refuses publication. Legacy files are
retained. There is no automatic choice between conflicting identities.

For a migration refusal, stop the affected hubs, preserve a backup of their
identity and pairing state, and reconcile the canonical identity from known
installation provenance. Restore the legitimate canonical file and restart.
Devices pinned to a different old identity must be paired again. Do not copy
another machine's ID or use an old ID as an automatic authority alias.

An activation record migrates only when its ID matches the selected profile's
legacy on-disk ID and its file belongs to that non-symlink profile root. It keeps
`previous_install_id` as history. Foreign records remain unchanged and report
`migration_required`; the activation projection does not present their ID as
the current installation.

Missing installation identity refuses new node grants and sender deeplinks.
Their existing owner endpoints return HTTP 503 with
`reason: install_identity_unavailable`. Old links without an installation
binding cannot approve a sender; mint a new link after resolving the identity.
Already paired sender records and code pairing are preserved.

Local verification covers Linux process races and profile separation. Windows
locking is covered by simulated byte-lock, holder-PID and reacquisition tests;
native Windows process acceptance is not claimed. The hub lock keeps the same
file inode and updates its PID in place without truncating the locked byte.

See [implementation and verification](plans/2026-10-10-hermes-closure-02.md).
