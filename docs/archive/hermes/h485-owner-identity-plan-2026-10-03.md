# H485 Telegram owner identity prerequisite

Generated: 2026-10-03T13:13:52.868065+00:00
Goal: preserve authenticated once-only owner override before extending smart DENY continuation. Full objective remains all 697 capabilities.
Base/head: ce34558179a7fc267555952f8a3856b40c3317f6; repo /Users/andrei649/Projects/nerva-pr-worktrees/integration; branch codex/h277-provider-discovery-20261002. Prior terminal delivery: 29 committed files, exact manifest matched, clean checkout verified; full backend 21703 pass/34 skip/1 xfail, record gates 228 pass, nine faults killed. No live suite remains.

Bounded design: trusted Telegram sender identity, not group destination alone, authorizes approval/admin commands. Preserve explicitly allowlisted owners and configured callback destination checks. When the sender list is empty, only the configured private owner chat with positive Bot API user-dialog ID equal to both sender and chat is a fallback. Negative group/channel destinations do not identify an owner. Reject missing, boolean, malformed or out-of-range IDs. Treat a supplied nonempty malformed sender list as fail-closed, not as an absent list. Bot API ID ranges verified from https://core.telegram.org/api/bots/ids (user dialog IDs 1..0xffffffffff; group/channel IDs negative). Keep ordinary inbound guest chat available. No new global policy setting, provider, runtime activation or transport credential.

Shared contract: new pure agents/core/telegram_owner.py exports is_telegram_owner_sender(user_id, *, chat_id, owner_chat_id, allowed_user_ids). Explicit configured valid sender membership may identify an admin in any chat as before; the coordinator additionally enforces its configured destination before permitting a task decision. Empty-list private fallback requires all three positive IDs equal. No mutable registry/cache or model-controlled presence flag.

Writers: Sol High helper implementer owns the new helper plus tests/test_h485_telegram_owner_identity.py. Coordinator owns integration into autonomy_coordinator._callback_is_owner and orchestrator._channel_principal, precise binding-callsite position refresh, integration regressions in SEC-B3/slash-command tests, record adjudication and final review. A second Sol High reviewer may inspect the completed diff and propose red-first cases without editing shared files. No child delegation.

Red-first tests: group owner destination with empty list cannot call apply_decision or gain administrative slash-command authority; private owner fallback succeeds only with exact sender/chat; explicit owners keep prior behavior; wrong destination denies callback; missing sender/bool/invalid list fail closed; guest read/chat remains available. Reuse real callback/command entry points rather than only helper mirrors. Run existing SEC-B3, slash commands, H117/H487 Telegram reason lanes, H277/H485 approval regressions and orchestrator binding inventory. Refresh only exact existing callsite positions after reviewed coordinator line movement; preserve names/columns.

Verification: focused tests after each step; record/count/reference gates after final records; Graft rebuild/check after relevant source changes; exact staged secret scan and manifest/commit/clean checks. Expensive full backend serially at the next integrated milestone, retaining pytest.ini socket/timeouts. Keep H277/H485 partial until context-bound once-only owner wait/actuation, nested/scheduled policy, native controls and required acceptance are proved.

Rollback: separate coherent local security commit, no schema/dependency migration. No push, merge, deployment, paid provider call or activation. Next action: revalidate clean ce345581 checkout, write failing group callback and administrative command regressions, then implement the helper/integration.

## Execution checklist

- [x] Reproduce unauthorized group callback and administrative command behavior.
- [x] Implement shared identity helper and integrate the two authority entry points.
- [x] Verify explicit owner/private fallback, guest chat and reason-reply compatibility.
- [x] Review exact existing binding positions, refresh Graft and run focused regressions.
- [x] Refresh affected records/counts and scan exact local delivery bytes.

This prerequisite alone does not complete H277/H485 or increase equivalent capability credit.

## Evidence-driven integration amendment

The first guarded integration run reproduced 21 H117 failures (207 passed): its
real Telegram adapter admitted guests with an empty ingress list, while its owner
sender 99 differed from private destination 42. Group tests also intentionally
exercise owner reason replies alongside other members' ordinary chat. Adding only
the owner to the ingress list would filter those members before batching; adding
members to that list would grant them administrative identity.

Preserve that required behavior by declaring `autonomy.owner_user_ids` as a
persisted JSON setting, independently of Telegram ingress admission. Its shipped
`null` preserves legacy owner identity from the adapter allowlist. An explicit
list identifies owners only; valid empty lists retain the exact private fallback,
and malformed explicit values fail closed rather than falling back to legacy
members. The pure resolver handles typed lists and serialized JSON lists without
reading environment, settings or mutable state. The settings declaration is a
necessary configuration surface, not a change to channel admission.

Use the existing environment-first owner destination resolver for decision-card
wiring, callback authorization and private administrative fallback. A callback
requires a currently configured destination, so clearing it revokes stale cards.
Explicit owner identity still permits administrative commands in other chats as
before. Both settings are trusted server configuration, never inbound model data.

Additional root-owned paths: `agents/core/settings_db.py` and
`tests/test_h485_telegram_owner_settings.py`. Red-first regressions reproduced
environment mismatch (four callback/reason cases and one admin case), separated
group-owner behavior (three cases), destination removal (one case), and the real
settings store skipping the undeclared owner key (one case). The H117 fixture now
declares its owner independently while retaining real guest admission and all
batching/order checks. The previous test assuming every group member is an owner
now requires the unauthorized member's rejection to leave the pending task untouched.

Final review reproduced persisted owner revocation bypassing the runtime cache.
Authority now reads both owner fields in one read-only SQLite snapshot, with
`timeout=0`, no initialization or writes. A missing, unreadable or busy store
refuses authority, including environment/private fallback. An exclusive-lock
regression reproduced the old 5.346-second wait; the corrected path refuses in
under one second. Ordinary settings retain their existing watcher behavior.
The settings HUD preserves explicit JSON `null`, and Telegram acknowledges a
decision only when the coordinator actually applied it.

Current execution state: the final guarded focused union passes 400 tests.
The earlier 2,109-case H277/H485/safe-mode run predates the final authority fixes.
All 53 parent-current records were reread, with no status promotions; 60
already-stale impacted rows retain their need for reassessment. Real count sync
records 21,825 backend cases, 1,886 frontend tests and 142 mobile tests. The first
complete backend run was explicitly interrupted after review demonstrated the
cache-revocation flaw; it is not a complete-suite result. The fresh guarded full
backend passes 21,790 tests with 34 skips, one existing xfail, zero failures/errors
and matching count/frozen hashes. Next action: finalize records/scans and the local
checkpoint, then execute the context-bound owner-once continuation plan red-first.
The full goal remains all 697 capabilities;
this prerequisite does not implement interactive once-only DENY continuation.
