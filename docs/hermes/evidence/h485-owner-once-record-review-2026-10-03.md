# Owner-once collateral record review

Goal: continue all 697 accepted Hermes capabilities without counting changed or
unverified evidence as completion. Base/head before this local increment:
`aec4348cf96f92d2b384dbba4b8e3a5b7e438a11`, branch
`codex/h277-provider-discovery-20261002`.

The owner-once changes invalidated 17 reviews whose complete evidence matched
the preceding HEAD. Their changed source paths and claim boundaries were reread:
H117, H153, H176, H262, H277, H298, H309, H315, H468, H485, H515, H594, H595,
H660, H667, H677 and H681. This preserves ten equivalent, six partial and one
missing verdict; it does not close ten new capabilities. The 85 reviews already
stale at the preceding HEAD were not refreshed by this operation.

The Telegram batching and shutdown descriptions now acknowledge the bounded,
registered owner-once callback exception to ordinary chat-lane ordering. H277
and H485 record the actual Telegram continuation and remaining producer/transport
and broader capability gaps. H468 remains missing: owner-once task states do not
implement the separate work-review Kanban workflow.

Generated Hermes reports now agree at 180/697 equivalent (25.8%), 262 partial,
63 missing, 192 requiring review and zero excluded. Of the 180 equivalent rows,
72 have current explicit reviews and 108 retain inherited baseline verdicts.
This is code assessment, not complete live functional acceptance.

The record/reference/count regression union passed 231 cases with zero failures,
errors or skips. H468 queue/inbox collateral regressions passed 20 cases. The
33 source/test hashes in the actuation checkpoint still match. Backend collection
now records 21,970 cases; frontend/mobile counts are retained, not freshly rerun.

Next action: freeze the current source/configuration and run the guarded full
backend serially, validate its terminal result and exact count, and record the
source-bound outcome. No full-suite result for this increment is claimed here.
The change remains local; no push, merge, deployment or runtime activation.
