# H487 Telegram / CLI collateral source review

Generated2026-10-04. Goal: complete local parity with all697 pinned Hermes
capabilities. Inspected base/head42840e3d409449cb1382417c8e88999fdd14ed26
and its local uncommitted Telegram / CLI diff. This is source preservation
review, followed by separately recorded regressions; it grants no new equivalent
credit and does not recertify historical mutation or live-provider receipts.

The31 previously-current claims touching this diff are H004, H117, H145, H153,
H157, H220, H227, H242, H262, H273, H298, H309, H314, H315, H329, H350, H378,
H413, H465, H487, H515, H586, H594, H595, H660, H666, H667, H671, H677, H681,
H687. Older stale claims are outside this bounded review.

## Reviewed changes

- CLI: AST comparison limits changed functions to `build_parser`, new
  `_valid_consent_offer` and `cmd_approvals`. Other command handlers are unchanged.
  H004 must describe the added `approvals consent` command and preserve its
  parser-derived completion contract. Real fish is absent on this machine;
  optional real-shell tests may skip and are not fresh live-shell evidence.
  H145, H157, H220, H227, H242, H262, H273, H315, H329, H350, H378, H413, H465,
  H586, H666, H667, H671 and H687 keep their existing scope/verdict after their
  own regressions; they gain no new feature from a shared-file hash refresh.
- Telegram: changed methods are construction, stop, new verified consent send,
  `_handle_update` and new consent callback handling. Ordinary text, batching,
  webhook/card send, reason reply and owner-once handler bodies are retained.
  H117 and H677 need explicit prose: all reserved `autc:` callbacks intercept
  before the normal held-batch flush. A valid registered callback uses its own
  bounded32-task lane; malformed/stale/unregistered reserved callbacks refuse
  promptly there. Ordinary callbacks retain their old ordering; `aut1` keeps
  its separate post-flush lane. Stop revokes and cancels both private lanes,
  sharing the existing bounded fast-task wait before ordinary lane drain.
  H153's ordinary webhook dispatch remains unchanged.
- Coordinator and literal binding inventory: consent registry wiring and exact
  terminal-origin registration are additive. Existing registrations and callers
  remain; the14 coordinator coordinates move by40 lines without changing names
  or columns. H262, H298, H309, H314, H315, H515, H594, H595, H660 and H681 keep
  their claimed behavior after the exact inventory and original regressions.
- Queue/ledger: changes are limited to consent actor/proof/decision validation
  and the new read-only durable terminal-result verifier. Ordinary transition,
  grouping, task expiry and manual decision branches are retained. Strict v2
  attributed records distinguish the actual Telegram decider from captured
  request grant scope; v1 is recognized with its reviewed exact schema.
  H487 stays partial. Denials have durable ordinary attribution, without a
  cryptographic denial-audit claim. No grant changes the kernel/policy floors.

## Citation and verification boundary

387 existing citations were compared with their exact base source. Only the
Telegram callback range for H117/H677 was edited; those summaries are rewritten
around the actual branch. Moved CLI/coordinator citations are remapped to their
confirmed source locations. The unanchored H153 sender-range suggestion was
confirmed by reading the existing verified multipart sender in its real context.
Other anchors remain in their original unchanged functions.

Review used a narrowly scoped read-only specialist plus root AST/source review.
No concrete authority/transport bypass was established in this diff. A real
model child-task registration gap was independently demonstrated by failing
regressions and fixed before the integration milestone. Tests bind mocked native
Bot API identity/receipts and mocked physical effects; no live network/device
acceptance follows. The new milestone record supplies actual test outcomes,
source hashes, scans and full-run state. Recheck hashes after any source edit.
