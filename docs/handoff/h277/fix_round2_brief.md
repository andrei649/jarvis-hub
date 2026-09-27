# H277 fix round 2 — binding brief

Worktree h681-wip at 72e89628 (round 1). The verifier's report is h277_fix_verify.md: new defects
N1..N7 plus two NIT notes (F4 deep scan unpinned; F6/F7 lm-studio-on-LAN label). Fix all of them
red-first (a test that fails at 72e89628 for the right reason, then the fix). Same rules as round 1.

Decisions (binding):
- N1 (treat as MAJOR): the judgement decision is re-made at the moment a call is about to be sent.
  After a slot is acquired, re-check judge.status() is configured, wants(item) still holds (so
  ALLOW_REMOTE / strict-local / cloud_fallback / safe mode / taint are re-read), and the item is
  still pending on disk; otherwise send nothing, leave the item unannotated and count
  skipped_revoked in the public judge status. Tests: revoke ALLOW_REMOTE, set cloud_fallback=never,
  enable safe mode, and decide() an item — each while items wait for a slot — and assert the fake
  remote backend receives no further calls for them.
- N2: the server tells the HUD whether an item's judgement is still coming: the public item carries
  judge_pending: true while it is queued or running (in-memory set, cleared on finish/skip/decide).
  The HUD keeps re-polling a card while the server says judge_pending, with a hard per-card cap of
  (ceil(32/2)+1) * timeout + 5 seconds; once not pending and no opinion, it shows "not available".
  Vitest: a card whose judgement lands after timeout+5 s still shows it.
- N3: values are capped only when the whole snapshot exceeds the 4000-char limit; the budget is
  shared out so small values stay whole and the largest are cut first; truncated only when
  something was actually cut. Test: a 1600-char write_file body within the limit is sent whole and
  not truncated; a call over the limit keeps every key and is truncated.
- N4: no silent depth limit. Past the walk limit the scan fails closed: add the flag
  "nesting_too_deep", mark truncated, and a remote judge refuses the item. FLAGS.md says so.
- N5: _sanitise_why NFKC-normalises first, then replaces every quote-like character (Unicode
  categories Pi and Pf, ASCII '"' and "'", U+05F4, U+3003, U+02DD, U+FF02) with "'" and every
  dot-like separator (U+00B7, U+0387, U+2022, U+2027, U+2219, U+22C5, U+2E31, U+30FB, U+FF65) with
  "-". Parametrised test over each.
- N6: the snapshot converts bytes (utf-8, errors=replace) and sets/tuples (sorted list when
  sortable) to real strings/lists before JSON, so their text is scanned as text. Tests with a
  bytes value and a set value holding the wrapped injection phrase.
- N7: the approval_judge import in request() is guarded (a failing import leaves the request
  working exactly as before the row, logged once); the tainted mark is stored only while a judge is
  configured, so with no judge an item stays byte-identical to the pre-H277 shape. Tests for both.
- F4 note: pin the deep scan in wants() with a test where the item has no top-level tainted key
  (constructed directly) but args hold a nested taint flag.
- F6/F7 note: the vision row's data-policy label comes from the host's locality, not the provider
  name: an lm-studio server on a LAN host is "(remote, unknown)". Test it.

Then run the two H277 test files 3x, the related suites of round 1, npx vitest run tests/frontend
(symlink node_modules if needed, remove before commit), ruff, bandit with the baseline. Commit as
'fix(H277): verify round — <summary>' with a body listing N1..N7 and exactly these trailers:
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FCWSJRUg9xJvyr2Cy1WHjF
