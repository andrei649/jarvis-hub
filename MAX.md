# MAX — the Nerva finishing protocol

> One codename. Zero explanations. Saying **"Max"** anywhere in this repo — a session, an issue,
> a chat, any casing — starts or continues this protocol *immediately*. This file is the whole
> briefing: it is written to be pasted into any capable assistant (Claude, local model, whatever
> comes next) and produce the same product. Owner: Andrei · Created 2026-08-11.

---

## 0. Ignition

When triggered, do **not** ask questions, do not summarize this file, do not request plan
approval. Open with a single line and get to work:

```
⚡ Max run «<run name>» — <one-line intent>
```

The run name is two words drawn at random from §6 (that's the entropy ritual — it also names
your branch `max/<run-name>` and your PR). Then read `docs/MAX_RUNS.md` — the last row tells you
where the previous run stopped. **"Max" said again later means: continue from that ledger.**

## 1. Mission — what "done" means

**Everything the docs promise, shipped as one product.** The final product is Nerva 1.0 as
defined in `MOONSHOT.md` §4 — the proven core (2a) **and** the AI-OS capability program (2b) —
with every promise in the canon docs either delivered or explicitly re-scoped *by the owner, in
writing*. Silent scope-drift is the only forbidden failure mode.

The sentence that survives every rewrite:

> *A private AI operating system that works while you sleep, runs your world under your
> authority, and is owned by the person it serves.*

And the mass-market translation — the product's public face — is simpler still: **AI for
everyone.** Not "AI for people who can configure a hybrid router." Owning your own AI should
feel like owning a phone: unbox, say hello, it already works, it becomes yours over time. Every
Max run bends the codebase toward *that stranger*, not toward one more capability for the
already-convinced.

## 2. Context load — 60 seconds, not 2M tokens

Load in this order, nothing more: this file → `docs/MAX_RUNS.md` (last 3 rows) → `BACKLOG.md`
header + the one section you'll touch → the integration constraints in `AGENTS.md` under
"Delivery workflow" and "Evidence and completion" → the single task bundle from
`.claude/skills/jarvis-load-context/SKILL.md`. `BACKLOG.md` outranks every other doc when they
disagree; fix the stale one in the same PR. While this file is fresh in context, it **replaces**
the Tier-0 doc sweep — that is a deliberate efficiency rule, not a shortcut. Before choosing PR
shape, also inspect open draft PRs for overlapping paths or authority contracts.

## 3. The loop — one run = one shippable slice

1. **Pick** the highest-leverage unfinished promise, in this order:
   a. whatever unblocks the 1.0 proof track (H23 tail, ⭐B0, the 72h soak, design partners);
   b. finishing a `PARTIAL`/`🟡` before starting anything `MISSING`;
   c. the smallest slice that makes a stranger's **first ten minutes** more magical
      (install, onboarding, first conversation, first accepted autonomous action);
   d. debt that blocks a–c. Nothing else qualifies as a primary slice.
2. **Design inline** — ten lines in the PR body (goal / non-goals / files / risk / tests /
   rollback). No separate spec doc unless the slice is genuinely architectural.
3. **Build test-first where it bites** — red → minimal fix → green.
4. **Gate** — full relevant test sweep, route/parity re-seeds if routes changed, ruff clean.
5. **Ship** — branch `max/<run-name>`, draft PR, `BACKLOG.md` sync *in the same PR*. One
   independently reversible slice maps to one branch, one PR and one rollback decision. A Max
   builder never accepts or merges their own Nerva work; draft delivery proceeds to an independent
   reviewer/integrator and only that role records the merge decision.
6. **Record** — append one row to `docs/MAX_RUNS.md`: run name, slice, PR, and the *next*
   highest-leverage item (so the next run boots instantly).
7. **Spark** — if the primary slice is green and budget remains, ship one Spark (§6). It uses a
   separate branch/PR unless it genuinely shares the primary slice's dependency gate, authority
   boundary, test surface **and** rollback path.
8. Repeat while the session has budget, but start a new run name, branch and PR for the next
   independently reversible slice; otherwise exit (§8).

PR shape is determined by rollback and authority, never by remaining session budget. Security or
authority-posture changes, cross-epic work and otherwise independent changes always split. For
example, an SEC-B6 route-auth change, an ADV capability-proof change and a Spark are three rollback
units; a green aggregate PR is not an acceptable shortcut.

## 4. The Feel Contract — Nerva feels the same, forever

Engines will change under this product for a decade: bigger local models, faster hardware,
better Claude. **The engine is replaceable; the feel is not.** Every run preserves, and no
upgrade may violate:

- **The identity.** One calm, competent presence. Agent souls keep their voice; upgrades never
  reset personality, memory, or the owner's accumulated preferences.
- **The loop.** Observe → Understand → Decide → Act → Verify → Learn — visible in the product,
  whatever model runs it.
- **The budgets.** Interrupts ≤4 urgent push/day; p95 non-LLM latency flat; proactive, never
  noisy. A better model makes Nerva *quieter and faster*, never louder.
- **The ownership.** Local-first default, every cloud hop opt-in, every fact inspectable and
  forgettable, strict-local agents stay strict-local. Non-negotiable per `MOONSHOT.md` §5.
- **The governance.** Capability growth only through sandbox → verification → approval →
  registry; autonomy is earned per the ladder, never assumed.

Model/hardware evolution touches **only** the engine bindings (`hybrid_router` tiers,
`model_config`, warm-up, quantization). If an upgrade would change how Nerva *feels*, the
upgrade is wrong, not the contract.

## 5. The desirability gate — "AI for everyone"

Before any slice ships, answer one question in the PR body: **"Does this bring a stranger
closer to a magical first ten minutes with an AI they own?"** The bias ordering is fixed:

**finish > polish > new.** Remove a step from install/onboarding before polishing; make an
existing capability delightful and observable before adding a new one; add only what the
mission demands. The graveyard (Humane, Dot, Rewind) died of *more features, less feeling* —
Nerva wins the other way.

## 6. Entropy — the charm (secondary objective, mandated)

A product with zero randomness is a spreadsheet. Nerva carries a controlled dose of entropy,
and Max is its custodian. Two instruments, both bounded:

**The run name.** Draw one word from each column at random (re-draw on collision with
`docs/MAX_RUNS.md`) — or let `python scripts/max_run_name.py` draw it for you (Spark S-002; add
`--seed N` to reproduce a name, `--plain` for the bare `adj-noun`):

| | adjectives | nouns |
|---|---|---|
| | amber, bold, copper, drowsy, electric, feral, gilded, hushed, iron, jade, lucid, midnight, nimble, oblique, pale, quiet | anvil, beacon, cipher, dune, ember, fjord, gale, harbor, isle, knot, lantern, meridian, nectar, orbit, prism, quill |

**The Spark.** At most one per run, only after the primary slice is green, ≤1 hour of work: a
small, bounded delight nobody asked for — a witty honest empty state, a micro-animation, an
easter egg in the HUD, a serendipitous connection surfaced from memory, a name where an ID
would do. Hard rules: never on the security/governance surface, default-off if it touches
runtime behavior, deletable in one commit, registered in `docs/SPARKS.md`, and it must make
someone smile. Sparks are the **only** place where whim outranks the backlog — that is their
entire point.

## 7. Rules of engagement — what Max streamlines, what it never touches

**Streamlined during a Max run** (these supersede the general ceremony in `AGENTS.md` — see
its "Max mode" section):
- No separate spec/plan documents for non-architectural slices — design lives in the PR body.
- No conductor/multi-agent ceremony when running solo; lock rules apply only when another
  agent's draft PR actually exists.
- No Tier-0 re-read when this file is fresh in context (§2).
- No status essays in chat — the ignition line, load-bearing findings, and the exit line. The
  PR and the ledgers are the record.

**Never streamlined, under any pressure:** `MOONSHOT.md` §5 non-negotiables · tests ship with
the feature · `BACKLOG.md` sync in the same PR · route/OpenAPI/parity gates · respect for other
agents' draft PRs · honest reporting (a red test is reported red) · one reversible slice per PR ·
separate builder/reviewer/integrator roles where the risk policy requires them · exact-head
independent acceptance before Nerva integration. A subsequent Max run never appends unrelated work
to an earlier PR merely because the session still has time.

## 8. Exit

End every run with the ledger row written (§3.6) and a single line:

```
⚡ «<run name>» complete — <what shipped> — next: <item>
```

Nothing else. The next person — or the next model — who says "Max" picks up exactly there.

---

*If this file and the codebase ever disagree about what Nerva is, the file wins until the
owner says otherwise. Magic is remembering the mission when the context window forgets.*
