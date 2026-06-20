# Jarvis Hub — Year-One Review & Learnings

> **Audience:** the owner. **Register:** candid. This is not the launch post or the
> brand deck — those live in `marketing/` and `MOONSHOT.md`. This is the document you
> read alone, at night, to decide what the next year is actually about.
>
> **Date:** 2026-06-20 · **At version:** v9.9.9 (pre-1.0 audit gate) · **Companion
> docs:** [`MOONSHOT.md`](../MOONSHOT.md) (the bet), [`BACKLOG.md`](../BACKLOG.md) (the
> work), [`STATUS.md`](../STATUS.md) (the snapshot), [`docs/HISTORY.md`](HISTORY.md)
> (the chronicle). This review *reads* those; it does not rewrite them.

---

## 1. The verdict

You built a genuinely impressive machine. Seventeen agents, a governed autonomy
cortex, fused vector-graph memory, a tamper-evident audit chain, ~2,300 backend
tests, a hardened hot path — and a decoupled 4D-OSINT product on the side. The bet
is **proven in code**: every non-negotiable principle in `MOONSHOT.md` is enforced by
a test or an architectural constraint, not by a paragraph. That is rare, and it is
real.

It is also the easy half.

The machine has been used in anger by exactly **one person: you.** The headline
feature — *governed proactive autonomy* — has never been validated on the real
hardware it was designed for. There is no second user, no design partner, no install
that isn't yours, no evidence that an "accepted autonomous action" feels valuable to
anyone whose name isn't on the repo. **Code-complete is not desirable.** A product
people want is a different artifact than a system that passes its own tests, and the
gap between them is the entire next chapter.

The one-line truth: *you have proven the thesis to the compiler and proven nothing to
the market.* The next milestone is not H18. It is a stranger who keeps the system
running for a month because it earned it.

---

## 2. Where we are — status at a glance

| Dimension | State |
|---|---|
| Version / gate | **v9.9.9**, pre-1.0 audit gate |
| Backlog (H1–H17) | **194 / 196 items code-complete (~99% SP)** |
| Open backlog items | 2 — both GPU-host-gated (H12.14 fine-tune, H13.3 speculative decoding) |
| Tests | ~2,300 backend (pytest, offline-first) + 184 frontend (Jest, ~67% line) |
| Agents | 17 active (incl. Howard emerging, Argus WorldView bridge) + 17 bench |
| Surface | ~299 HTTP routes · 22 plugins · 13 skills · 6 channels |
| Codebase | ~40K LOC `agents/` + ~30K LOC tests + ~5K LOC frontend + WorldView (separate stack) |
| Cost to run | **$0/month** (local inference + free tiers) |
| **Real users** | **1 (you)** |

**Human gates still open** (these, not code, block v1.0):

- [ ] Manual testing on real hardware — `docs/MANUAL_TESTING.md`, incl. the ⭐ governed-autonomy demo
- [ ] HUD V2 runtime verification — every panel, live backend (deep write-controls lag ~37 surfaces: `docs/design/HUD_V2_REMAINING.md`)
- [ ] Two GPU-host features (H12.14, H13.3) + Howard's training data export
- [ ] Owner sign-offs: license (MIT → Apache-2.0), GitHub repo metadata/topics, Dependabot moderates

The software is done. What's left is the part that needs a human, a GPU, and a user.

---

## 3. The arc — what this year actually was

The narrative spans Phase 0 Foundation → H5 Next Wave → H6 Autonomy → H7
performance/hardening → H8 Personal Memory → H9 Observability → H10–H11
competitive/parity → H12–H17 frontiers → WorldView (O19, merged). That's the
documented twelve-month arc, and `docs/HISTORY.md` chronicles it horizon by horizon.

**The honest footnote — and it's a finding, not an aside:** the *delivery* of that arc
was compressed into a few intense, largely agent-driven weeks of multi-agent parallel
work (one day alone landed 35 commits across worktrees). This is a strength: you
proved that a single owner orchestrating a wave of agents can produce what looks like
a year of a small team's output. It is also a risk worth naming plainly — **velocity
this high, this concentrated, by this few hands, means the system has never been
stress-tested by time.** No long-running deployment, no slow-burning state corruption,
no "left it running for three weeks and the audit DB grew to 2GB" lesson. The clock
has barely started on this code. Treat its maturity as *broad* (everything exists and
is tested) but not yet *deep* (little of it has survived contact with the real world
over real time).

---

## 4. What we actually built — inventory by maturity

No inflation. Three honest buckets.

### Production-ready (shipping, tested, load-bearing)
- **Orchestration core** — full request lifecycle, parallel agent calls, graceful
  LLM-down fallback, per-agent timeouts (`agents/core/orchestrator.py`).
- **Hybrid LLM routing** — `LOCAL_ONLY_AGENTS` hard-coded; complexity-based
  local↔cloud escalation; live LM Studio model control with a kill-switch.
- **Memory + recall** — conversation + vector + graph, **RRF fusion**, 3-layer
  embedding cache (LRU → disk → backend) with hash fallback.
- **Autonomy cortex (H6)** — SQLite task queue + state machine, 4-tier risk policy,
  approval inbox, watchers, nightly reflection, remediation. *Built and tested. Not
  yet exercised on real hardware against a real life — see §7.*
- **Security & audit** — guardrails (PII/secret/SSRF), **Merkle-chained audit log**,
  route-auth matrix test (`SEC-2`) that fails CI on any new unguarded mutator.
- **Persistence** — SQLite WAL hot path (**36× commit speedup**), off-event-loop I/O,
  checkpoint debounce. The single highest-ROI engineering work of the year.
- **Plugins (22), skills (13), channels (6)** — all with manifests/gates/tests.
- **WorldView (4D OSINT)** — standalone Next.js/Fastify product, contract-bridged
  read-only via Argus. Complete and decoupled.

### Partial / scaffolded (works in the lab, unproven in the field)
- **Server-side voice + real-mic** — browser loop ships; wake-word/satellite-mic is
  scaffolded, optional-dep, never hardware-validated.
- **Howard (digital twin)** — ingestion pipeline complete; the agent is *activated but
  untrained*. The headline "it sounds like you" promise is unfulfilled.
- **HUD V2 deep write-controls** — the backend sprinted ~37 endpoints ahead of the
  cockpit. The API works; the buttons don't exist yet.
- **Route-auth on a few open mutators** — functionally correct; a handful still lean
  on "localhost is safe," which stops being true the moment it's on a LAN/Pi/tunnel.

### Stub / blocked (real, but gated on hardware)
- **H12.14** fine-tuned agentic model · **H13.3** speculative decoding — both need the
  RTX 5090 box. Runbook ready (`docs/GPU_RUNBOOK.md`); work not started.

---

## 5. The twelve learnings (the real payload)

Each as *what we believed → what happened → the durable lesson.*

1. **The bottleneck was I/O, not the model.**
   *Believed:* an agent system is gated by inference. *Happened:* profiling found the
   non-LLM per-turn cost was synchronous SQLite writes on the event loop; WAL +
   `synchronous=NORMAL` cut commits ~36×. *Lesson:* for agent systems, **I/O
   scheduling beats inference scheduling.** Profile the boring path first.

2. **Governance must be code-enforced, not documented.**
   *Believed:* the principles in `MOONSHOT.md` described the system. *Happened:* docs
   said LOCAL_ONLY while Frigga and Howard could still reach cloud on a fallback path
   (BUG-14/15). *Lesson:* **a principle that isn't a failing test is a wish.** The fix
   was the route-auth matrix, not a stronger paragraph.

3. **Mock-fallback design hides real bugs.**
   *Believed:* green tests meant working code. *Happened:* an MCP `asyncio` NameError
   was swallowed by a broad `except` and silently returned `{}` for *months*; HUD
   wiring mismatches hid behind mocks. *Lesson:* **mocks prove the test, not the
   system.** Anything labelled "live" needs runtime validation on real hardware before
   it's called done.

4. **Deterministic beats LLM on the hot path.**
   *Believed:* route and extract with a model. *Happened:* keyword-scored bilingual
   routing and regex profile extraction were faster and far less noisy than LLM
   classification. *Lesson:* **reserve the model for what only a model can do;**
   determinism owns the latency-sensitive, high-volume path.

5. **Graceful degradation beats feature completeness.**
   *Happened:* async embedding calls were fragile, so recall falls back to a
   deterministic hash embedding under failure. *Lesson:* **a RAG that sometimes
   degrades beats one that sometimes crashes.** Design the fallback first.

6. **"Done" has three meanings, and they drift.**
   Code-complete ≠ audit-complete ≠ human-complete. The BACKLOG once listed bugs as
   "open" that had been fixed-with-tests weeks earlier. *Lesson:* **only automated
   checks keep tallies honest** at this scale; hand-maintained status rots.

7. **The rival's failure validated the bet — don't misread it as safety.**
   OpenClaw's implosion (plaintext secrets, ungoverned autonomy, #1 infostealer
   target) and the device graveyard (Humane, Dot, Rewind, Pi) confirmed *local-first +
   governed* as **durability, not constraint**. *Lesson:* but a validated thesis with
   no users is still a hypothesis. The market showed appetite — it did not show up *for
   you*.

8. **Multi-agent velocity has a merge tax.**
   *Happened:* parallel waves compounded output, but coordination cost climbed fast
   past ~3 agents on one repo. *Lesson:* **explicit sequencing and rebase-first
   discipline are the price of parallelism**, and that price is real.

9. **The linter finds real bugs — if you triage it.**
   CodeQL surfaced ~13 genuine issues (a calendar signature TypeError whose *tests
   mirrored the wrong signature*, a ReDoS regex, log injection) alongside false
   positives. *Lesson:* **cyclic tests can canonize a bug;** an outside checker plus
   triage discipline catches what your own suite agrees to ignore.

10. **Personal memory is regex-and-rules, not magic.**
    LLM-extracted facts were too noisy; hand-tuned patterns (CNP, IBAN, email) were
    reliable. *Lesson:* the "it learns you" magic is **mostly unglamorous deterministic
    plumbing** — and that's fine, but it bounds how far the twin can generalize.

11. **Security is a posture, not a milestone.**
    The SEC-1…SEC-5b wave, the FastAPI 0.137 route-collapse regression, the egress
    manifests — security work never closed; it became a *standing CI gate*. *Lesson:*
    **the win condition is "no new unguarded mutator can merge," not "audit passed."**

12. **A backlog can become a comfort zone.**
    H1→H17→H21 is a beautifully ordered ladder, and climbing it *feels* like progress.
    *Lesson — the most important one:* **shipping the next horizon is the most
    legible way to avoid the illegible, scary work** of finding a user. The backlog is
    real; it is also a place to hide.

---

## 6. Strategic position — the bet, stress-tested

**The wedge** is genuinely defensible on paper: no shipping consumer product combines
**local-first + proactive autonomy + living memory + observability + governance** in
one system. Rivals hold one or two axes (Bee: autonomy+memory, cloud; Omi:
local+passive, no learning; OpenClaw: local+proactive, no governance, broken). The
five-axis intersection is hard to execute well, and you executed it.

**The moat** is the local-first dual advantage — privacy *and* $0 COGS — plus
compounding proactivity and trust-through-inspectability. The **north-star metric** is
the right one: *weekly autonomous actions **accepted** per active user*, guarded by
interrupt-rate, reject-rate, and %-local counter-metrics.

**Now the provocation.** Every sentence above is currently **unfalsified, not
proven.** "Proactivity compounds" — over whose weeks? "Trust is earned by
inspectability" — earned from whom? "Switching cost no reactive tool can match" —
nobody has anything to switch *from* yet, because nobody is on it. With **n = 1**, the
moat is a hypothesis you happen to believe. The metric reads zero through no fault of
the architecture: **there is no active user to measure.** The strategy is sound enough
that the only honest way to test it is to expose it to someone who can walk away.

---

## 7. Gaps to a *desirable* product

Two categories. Be ruthless about which one matters more.

### Engineering gaps — known, tracked, mostly small
- HUD V2 deep write-controls (~37 surfaces) — `docs/design/HUD_V2_REMAINING.md`.
- A handful of open route mutators still relying on localhost trust.
- Howard untrained; server voice/real-mic unvalidated.
- `CLN-2`/`CLN-3` god-object split (`orchestrator.py`, `web.py`) — deliberately
  deferred post-1.0 to avoid pre-audit regression. Correct call.
- BUG-7 (httpx pool close), FastAPI version pin. Minor.

These are a few focused weeks. **None of them is why the product isn't desirable.**

### Product gaps — the actual frontier (and the backlog barely touches them)
- **No user but you.** Everything else is downstream of this. The system has never
  had to be legible, trustworthy, or valuable to a person who didn't build it.
- **The headline loop is unproven.** Governed proactive autonomy — the entire pitch —
  has never run on the real hardware against a real life for a real stretch of time.
  Until the ⭐B0 demo runs and *keeps* running, the central claim is untested.
- **The first ten minutes are config-heavy.** A privacy-conscious power user is still
  a stranger who will bounce off a `.env`, an LM Studio model pull, and a Docker
  compose. Onboarding is the product for anyone who isn't you.
- **No proof that "accepted action" = felt value.** The metric can be high and the
  product still hollow if the accepted actions are trivial. *Useful* autonomy, not
  just *safe* autonomy, is the unsolved problem.
- **No distribution motion.** No design partners, no landing page that explains
  rather than chats, no demo video, no launch. (`docs/gap-analysis-1.0.md` already
  flags landing page / video / Product Hunt as open.)
- **Single-maintainer reality.** ~70K LOC, 17 agents, ~299 routes, a second
  Node/OSINT stack — maintained by one person. Bus factor 1 is the quiet risk under
  every other line.
- **"Jarvis" naming/trademark** — fine for OSS, a wall at Phase 2.

**Say it plainly: shipping H18–H21 will not close a single product gap.** They are a
different *kind* of work — outward, social, unglamorous, and the only kind that turns
this from an extraordinary personal artifact into a product someone wants.

---

## 8. Potential directions — and a recommendation

Three honest forks:

- **A. Finish the fortress.** Tag v1.0, clear HUD depth, train Howard, harden the last
  routes. *Pro:* satisfying, fully in your control, plays to strengths. *Con:* it's
  the comfort zone (learning #12). Ends with a more perfect system still at n=1.
- **B. Recruit 3 design partners now.** Stop adding capability; get the current build
  into 3 real hands and instrument the north-star. *Pro:* the only path that tests the
  thesis. *Con:* exposes the rough onboarding and the unproven loop — which is exactly
  the point, and exactly what's uncomfortable.
- **C. Narrow to one killer proactive loop and prove it.** Pick the single most
  valuable autonomous behavior (e.g. morning brief + one class of reversible
  remediation), make *that* undeniable end-to-end on real hardware, and lead with it.
  *Pro:* converts breadth into one sharp, demonstrable claim. *Con:* requires killing
  your darlings — most of the 17 agents sit out the spotlight.

**Recommendation: a sequenced C → B.** Spend the next stretch making **one** proactive
loop genuinely, provably valuable on the real box (this also discharges the v1.0
manual-testing gate, so it's not a detour). Then put *that* — not the whole cabinet —
in front of **1–3 design partners** and measure accepted-actions/week. Let real usage,
not the backlog, rank what comes after. This is the Phase-2 gate in `MOONSHOT.md`
(3–5 design partners) pulled forward and made concrete. Bias the year toward **proving
value to a user over adding capability for yourself.**

---

## 9. Actionable — the next 90 days

Prioritized, owner-executable. Each item: *what · why · done-when.*

1. **Run the ⭐B0 governed-autonomy demo on the RTX 5090 box.**
   *Why:* it's both the v1.0 manual-testing gate and the proof the central claim
   works. *Done-when:* `docs/MANUAL_TESTING.md` signed; the loop has run unattended
   for ≥72h without a trust violation.
2. **Pick and polish ONE killer proactive loop** (Direction C).
   *Why:* breadth is proven; depth/value isn't. *Done-when:* you'd show it to a
   skeptical stranger without caveats.
3. **Tag v1.0.0.** *Why:* closes the human gate, frees attention for users. *Done-when:*
   manual testing + audit pass, license flipped, version cut.
4. **Cut a 60-second demo video + a landing page that explains, not chats.**
   *Why:* the first artifact a non-you human will ever see. *Done-when:* both live and
   linked from the repo.
5. **Recruit 1–3 design partners and instrument the north-star.**
   *Why:* the only way to falsify the moat. *Done-when:* ≥1 non-owner install running a
   week, accepted-actions/week being recorded.
6. **Owner-only unblocks:** license MIT→Apache-2.0, GitHub repo metadata/topics,
   Dependabot moderates, GPU runbook kickoff (H12.14/H13.3).
   *Why:* small, you-only, currently blocking. *Done-when:* checklist in
   `docs/OWNER_TASKS.md` cleared.
7. **Write down the maintenance reality.** *Why:* bus-factor-1 on 70K LOC is the
   silent risk. *Done-when:* a one-page "if I disappear for a month" runbook exists.

Everything not on this list — including most of H18–H21 — waits until a real user tells
you it matters.

---

## 10. Risks that could kill it

- **Bus factor 1.** One person, 70K LOC, two stacks. Illness, burnout, or boredom ends
  the project regardless of how good the code is. The highest-severity risk, and the
  least discussed.
- **Scope-gravity.** The backlog is a comfortable, legible place to spend a year while
  never finding a user. Climbing horizons *feels* like progress and can substitute for
  it indefinitely. (Learning #12, restated because it's the one that bites.)
- **Safe but not useful.** Autonomy can be perfectly governed and still not worth the
  setup cost. If accepted-actions are trivial, the metric lies and the product is
  hollow.
- **A funded team copies the wedge.** OpenClaw proved the appetite; the governance
  intersection is hard but not secret. Your edge is being *first and correct* — which
  only counts if you reach users before someone better-resourced does.
- **The thesis survives the compiler but not the user.** The real, unhedged risk:
  local-first + governed + proactive is exactly right *for you* and merely *fine* for
  everyone else. You won't know until §9.5 runs. That uncertainty is the whole game.

---

### Closing

You set out to prove you could own your AI instead of renting it, and against a
graveyard of better-funded teams who couldn't, **you built the thing.** That is the
hard part of engineering and you are past it.

The hard part of *product* is still entirely ahead, and it is a different hardness —
social, outward, unglamorous, measured by strangers. The machine is ready for that
test. The only open question left is whether you'll point it at a user, or at the next
horizon.

Point it at a user.
