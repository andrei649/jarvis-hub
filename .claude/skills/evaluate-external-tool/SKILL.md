---
name: evaluate-external-tool
description: Use when anyone proposes adopting an external AI tool, MCP server, agent pack or skill bundle into this repo — a shared link or list ("are these useful for us?", "integrate this", "add this MCP"), a GitHub/product URL, or a "N agents / N skills" pack. Also use before installing anything that writes to .claude/ or .mcp.json.
---

# Before adopting anything external

**Check the record first — this repo re-proposes tools it already rejected.**
`docs/decisions/` and `docs/research/` hold prior verdicts. OpenMontage was
evaluated and filed "no value" in June 2026 and re-proposed in September.

Then, in order:

1. **Resolve the URL yourself.** Shared lists carry dead and wrong links.
   `graft.nanodevs.ai` was NXDOMAIN; three items on one list shared a single
   GitHub *profile* URL. Never describe a tool you could not fetch.
   `curl -s -H 'accept: application/dns-json' "https://dns.google/resolve?name=<host>&type=A"`
   — `Status: 3` means the domain does not exist.

2. **Ask what Nerva already has.** `docs/ARCHITECTURE.md` (module index),
   `docs/AI_CONTEXT.md` (tiered loading), `jarvis-load-context`,
   `scripts/backlog.py|ledger.py` (query-don't-load). Most "context for agents"
   tools duplicate these, untuned to this repo. "We already do this" is the
   expected answer.

3. **Check the install shape against governance.** Anything writing
   `.claude/settings.json`, `.claude/hooks/**` or `.mcp.json` runs code inside
   the loop that authorises unattended merges. That is an **owner decision**,
   never an adopt — see `selfdev-policy.json` and `AGENTS.md`.

4. **Local-first is a constraint, not a preference.** A tool whose value comes
   from shipping source to a vendor model contradicts the stated posture.

Record the verdict in `docs/decisions/` so it is not re-litigated.
