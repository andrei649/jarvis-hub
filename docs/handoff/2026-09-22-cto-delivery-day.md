# Handoff — CTO delivery day, 2026-09-22

Session: `claude/cto-session-recovery-qinvkg` (Claude Code, cloud). Stopped by the owner at
~17:00 UTC to conserve subscription usage. This file is the durable record of what landed,
what is open, and what it cost, so the next session (any model) can resume without the
transcript.

## Merged today (owner merged manually — P29 keeps every check red)

| PR | Branch | What |
|---|---|---|
| #1182 | (recovered from the stuck CTO session's #1180) | unblocked and merged 2026-09-21 |
| #1183 | `tp-superpowers` | Superpowers 6.2.0 → 6.3.0 vendored copy; ruff `extend-exclude` for the vendored tests |
| #1185 | `claude/cto-session-recovery-qinvkg` | BACKLOG catch-up for #1179 (wave two of the adversarial review) |
| #1189 | `hermes/1179-hygiene` | records: the sixteen rows #1179 drifted, re-evaluated against its diff (123/697, needs_review 0 at merge time) |
| #1191 | `chore/autoupdate-artifact` | `thirdparty-autoupdate.yml` writes its `update.json` to `$RUNNER_TEMP`; stray root file removed; test pins it; OWNER_TASKS run counts corrected (10 of 13 failed) |

Also merged by the owner's other lane the same day: #1186 (Bolt, NeuralBurst), #1187
(heartbeat precedence), #1188 (H497 one pairing store per process).

## Open PRs, state at handoff

### #1193 — E, H672 compaction refresh — **ready for review**
Branch `hermes/h672-compaction-refresh`, head `357a7ff6`. Wires the two parked refreshes
(`agents/core/session_refresh.py`, parked commit 89b53e85, cherry-picked as 5150c3e5 — credit
belongs there; a squash merge drops its trailers) at Nerva's two compaction boundaries:
persona re-read fails open (`Agent._read_soul` / `refresh_soul` / `_announce_soul_verdict`,
stat-probe signature, `_refresh_souls_at_boundary` after the clock CAS), tool re-resolution
fails closed (`refresh_tools` / `_resolve_offer` / `_specs_for`, `_TOOLS_WITHDRAWN_REPLY`).
Records: H672 missing → partial; twelve rows re-stamped in round one; after #1189 the nine
rows citing `agent.py` / `agent_runtime.py` / `orchestrator.py` were re-read twice (6 kept,
3 rewritten: H387, H671, H673); headline 116/697 → 119/697; needs_review 16 on the head =
main's own #1187/#1188 drift. Verified independently on `a0517f03` (Python 3.12, 172 + 177
tests green); merged with main twice by merge commits. Full suite = CI's `test` lane on push.
Autonomous-merge eligible except for P29.

### #1190 — A, H481 hardline terminal floor — **draft, owner's call**
Branch `hermes/h481-cleared-refusals`, head `f41202c3`. Two #1177-cleared refusals closed,
then a review round (nine findings fixed: over-refusals, super-linear scans, overstated
file-exec claim), then **round two**: a bypass hunter ran 64 shapes under sh/dash/bash with a
PATH-shim stand-in and found three the floor cleared while a shell ran the body —
`cat <<EOF | (sh)` (trailing `)` read as a script name), `sh <<< reboot` (here-string WORD
never screened), `source <(cat <<EOF …)` (process substitution not modelled). All three
fixed in `60e1e6ad`, red-first, controls unchanged; `_detection_variants` disclosure
corrected; `tests/test_local_transport.py` 206 → 278 → 303; H481 re-stamped, `assessed_at`
bumped; merged with main (`24ff7ad6`), `merge-tree` clean. **Not done:** the independent
audit of the 22,304 refusals this branch clears (differential fuzz vs main, real-shell
sampling) and the CI-robustness review of the six wall-clock pins (0.25–2.0 s) — both lost
twice to container restarts; they are the most expensive runs of the day. Options: merge as
is (fixes are pinned and reproduced), or run those two reviews first.

### #1192 — B, H506 HEARTBEAT.md read-side scan — **ready for review**
Branch `hermes/h506-read-side-scan`, head `e526de6f` (merge `b1fd9c42` + records `e526de6f`).
Content verified in round one (`scan_heartbeat_config`, fail-closed walker, `blocked` in
status, spaced-copy / NFKC / U+2800+PUA detection variants in `quarantine.py`, 47 tests).
Finished 2026-09-22 evening: merged onto main 97ee1835 (only source conflict a comment in
`heartbeat.py`), **H351 rewritten** as the merge gate required, and the claim verified end to
end through `prompt_catalog` instead of assumed — five shapes that `main` advertises
(`Ignore<U+200B>all previous instructions`, the same phrase with every gap spelled U+3164 /
U+FE0F / U+FFA0 / U+2800, a `command` spelled with Hangul fillers, and the fullwidth spelling)
all lose their row here, while six legitimate English / Romanian / Arabic / Japanese /
emoji-with-tag / fullwidth descriptions keep theirs on both sides. Pinned where the row is
paid: 17 new cases in `tests/test_skills_in_prompt.py` (32 → 49), each red against the
pre-slice module. `loader.py` docstring drift corrected (two-copy scan, "eleven-entry" against
ten) — comment-only. Rows re-stamped: H288, H326, H351, H389, H506, H684. 212 tests green on
Python 3.12; `needs_review` 22 = main's own drift. Round two (false-positive sweep, bypass
hunt through the loaders, route-contract review) still never ran and is stated as such in the
PR. `agents/core/security/**` is control-plane → owner merge.

**Why it matters more than it looked.** #1187 landed this branch's refusal *bookkeeping*
without the scan that fills it. On `main` today `HeartbeatScheduler._blocked` is declared,
read by four paths (withheld agents.yaml interval, skipped `start()` job,
`get_status()["blocked"]` on the unauthenticated `GET /heartbeat/status`, the resume refusal)
and the module docstring states "an entry the injection scan refused is scheduled from neither
source" — while nothing in `agents/` ever writes to it and `_parse_heartbeat` is a bare
`yaml.safe_load`. The map is permanently empty and the documented property is absent until
this PR lands.

## Debt on main (records)
#1187 and #1188 re-stamped only their own rows (H497) and left **24 rows in `needs_review`**
on main (H060 H061 H068 H071 H104 H108 H130 H135 H139 H146 H288 H298 H363 H364 H398 H449
H477 H510 H523 H671 H673 H679 H683 H684 — drift from `pairing.py`, `telegram.py`,
`orchestrator.py`, `web.py`, `heartbeat.py`, `docs/ARCHITECTURE.md`). #1192 re-reads and
re-stamps H288 and H684 of those, so 22 remain for the catch-up once it lands. A catch-up PR in the
style of #1189 is owed: re-read each row against `git diff 3a7a039a...main -- <cited paths>`,
keep or rewrite, re-stamp, `hermes_status.py write && check`, `status_sync.py
--reuse-js-counts`, BACKLOG sentence. E and A each restore their own subset when they merge
(E: the nine `orchestrator.py` rows minus what #1187 re-drifts; A: none), so do the catch-up
after they land or expect a small conflict on `assessment.json`.

## Owner-only items (unchanged)
- **P29** — `github-advanced-security` (Copilot Autofix, model config 400) fails on every
  head, so no PR can auto-merge; disable the job or fix the model setting.
- Settings → Actions → "Allow GitHub Actions to create and approve pull requests" (the
  weekly auto-update lane still cannot open its PR; next run Thursday 07:00 UTC).
- Dependabot: 4 moderate vulnerabilities on `main` (reported by GitHub at push time).
- 62 pre-reroot branches: archive tag then delete (command handed over on 2026-09-21).
- #1162 decision (from the earlier cleanup pass).

## What it cost, and why
Five container restarts killed background agents mid-run (round-two workflow twice, the
post-C follow-up workflow, a five-agent batch, and the A fix + audit pair). Diagnosis by the
end: the cloud container is torn down whenever the session's turn ends while subagents are
still running (and a scheduled wake re-provisions it); heavy CPU load made it worse but was
not the cause. Work that survived was work done in the foreground of a single turn, or
pushed to GitHub before the turn ended. Estimated loss: 5–6 agent-runs, a few hundred
thousand tokens. Rules adopted for the next session:

1. Never end a turn with agents running; run them foreground-blocking or push partial
   results first.
2. At most 2–3 agents at once, `nice -n 10`, `pytest -n 2`, no `-n auto`, no
   CPU-saturation experiments, fuzz bounded to thousands of cases.
3. The full backend suite is CI's job on push; locally only the changed files and the
   ledger suites.
4. Push every commit as soon as its checks pass; the branch is the checkpoint.

## Resume checklist (in order, cheapest first)
1. Owner: merge #1193 and #1192; decide on #1190 (merge as is, or run the two remaining
   reviews). #1192 first if you want main's heartbeat docstring to stop describing a scan
   that is not there.
2. Records catch-up on main for the 22 drifted rows (#1187/#1188 re-stamped only their own).
3. Round two on #1190 and #1192, only if budget allows.
4. Routines: `Backlog Complete Check` (trig_01Ky7Y9wkbG7VwMGE5aSxkCP, bound to
   session_01AtEguXmhahM4PahpcgHRFe) was asked to update its own prompt; confirm at its next
   firing. The delivery-day check-in for #1190/#1192/#1193 was cancelled with this handoff.
