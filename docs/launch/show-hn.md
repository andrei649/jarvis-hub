# Show HN draft — Jarvis Hub

> Launch copy for Hacker News. Per the GTM research (`docs/research/2026-06-04-privacy-first-gtm.md`):
> plain title, **link the GitHub repo** (not a marketing page), founder works the comments live for
> ~4h, post early in the week. HN over-indexes on open-source + privacy. Fire **r/LocalLLaMA +
> r/selfhosted the same day** to concentrate GitHub star velocity (Trending ranks on velocity).

## Title (plain — no hype, no exclamation, ≤80 chars)
**Primary:** `Show HN: Jarvis Hub – a local-first, governed multi-agent personal AI`
Alternates:
- `Show HN: Jarvis Hub – an always-on personal AI agent that runs on your own GPU`
- `Show HN: The governed alternative to ungoverned local AI agents`

## Body

I built Jarvis Hub because I wanted an always-on personal AI that actually *does* things — triage email, watch my calendar, run nightly jobs — without sending my life to someone else's cloud, and without the "ungoverned agent" risk that's been all over the news this year.

It's 16 specialized agents orchestrated by a planner, running **entirely on your own hardware** (LM Studio or Ollama on your GPU). No cloud by default, ~$0/month. The part I care most about: **every autonomous action passes through an approval queue and lands in a tamper-evident audit log**, with an observability view of what each agent did and why. There's a kill-switch, encrypted secrets, and a family-memory agent that never touches the internet.

The 2026 wave of local agents (you know the one — ~377k stars in six months) proved people want this. But that class of tool ships *ungoverned* autonomy — and we've now seen the consequences (an infostealer lifting a local agent's gateway token; zero-click exfiltration from a major cloud copilot; surveys putting AI-agent incident rates around two-thirds of orgs). Jarvis's bet is that the missing piece isn't more autonomy, it's **governed** autonomy: local, auditable, reversible.

Honest about where it is:
- **Local-first, hybrid by design.** Local models handle the daily 80%; you can opt into a cloud model for the hard 20%. Nothing leaves the box unless you flip that switch.
- **Code-complete, pre-1.0 audit gate.** ~186 backlog items, 1,623 tests passing offline. I'm now doing a code audit + real-hardware testing before tagging 1.0.
- **Pure Python, MIT, self-host.** A hosted "Pro" (managed sync/relay) may come later, but self-host stays first-class — that's the point.

I'd love feedback from people running local models: where does the governance get in your way, and what would make you trust an agent to act unattended?

Repo: <GITHUB_URL>

## First comment (post immediately, founder context)

Some technical notes for the HN crowd:
- **Routing:** a keyword/intent classifier picks a fast vs. deep local slot; the deep slot gets a bigger token budget so reasoning models don't get truncated mid-thought.
- **Memory:** conversation history + a vector store + a knowledge graph, fused with reciprocal-rank fusion; a nightly job consolidates conversations into the graph.
- **Governance:** reversible actions can run autonomously; irreversible/costly ones block on an approval queue (Telegram one-tap or the HUD). Every tool call is hash-chained into an audit log. There's a global kill-switch the agent can't reach.
- **Security posture:** the local agent secures *itself* — no exposed gateway port by default, encrypted secret broker, SSRF/PII/secret scanners. (The recent local-agent infostealer stole a gateway token precisely because the port was reachable; don't do that.)
- **Stack:** Python 3.12 + FastAPI, LM Studio/Ollama, optional Qdrant/Neo4j.

Happy to go deep on any of it.

## Reminders
- [ ] Replace `<GITHUB_URL>`.
- [ ] Post Mon–Wed, morning US time; be free for ~4h.
- [ ] README must have a demo GIF above the fold + a clean install path before posting.
- [ ] In replies: agree with the kernel of truth first, stay humble, lean into OSS/privacy.
