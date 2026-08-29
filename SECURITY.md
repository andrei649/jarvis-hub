# Security Policy

Jarvis Hub is a **local-first, self-hosted** personal AI cabinet: it runs on your
own machine, binds to loopback by default, and treats cloud as opt-in per agent.
Most of the threat surface is therefore local — but the project still ships real
defenses (PII/secret scanning, SSRF-safe fetch, a containerized sandbox, an
HMAC-able audit chain, encrypted secrets at rest) and takes vulnerabilities seriously.

See also: [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) — what Jarvis defends against and
the concrete mechanism for each threat — and [`docs/PRIVACY.md`](docs/PRIVACY.md) — the
local-first data-handling and (no-)telemetry stance.

## Supported Versions

From 1.0.0 the window is the current `MAJOR.MINOR` line plus the one prior minor, for
90 days after its successor ships. Older lines are not back-patched — upgrade.

| Version line | Security fixes |
| ------------ | -------------- |
| `1.0.x` (current)  | :white_check_mark: |
| `0.x` (pre-1.0)    | :x: (upgrade)      |

The full versioning, deprecation, and platform contract is in
[`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md). The current version is
single-sourced from `agents.__version__` and shown at `GET /status`.

## Reporting a Vulnerability

**Please do not open a public issue for a security problem.** Instead:

- Use **GitHub's private vulnerability reporting** — the *Security* tab →
  *Report a vulnerability* (GitHub Security Advisories) on
  <https://github.com/andrei649/jarvis-hub>, **or**
- email the maintainer at the address on the GitHub profile.

Please include: affected version (`GET /status` or `agents.__version__`), repro
steps or a proof-of-concept, and the impact you observed.

**What to expect (best-effort, single-maintainer project):**

- Acknowledgement of your report within about **7 days**.
- An initial assessment (accepted / needs-info / declined, with reasoning) after triage.
- For accepted issues: a fix on the supported `1.0.x` line and a published advisory
  crediting you (unless you prefer to remain anonymous).

There is no paid bug-bounty program. Coordinated disclosure is appreciated — please
give a reasonable window to ship a fix before any public write-up.

## Hardening & scope notes

- Default bind is **loopback** (`127.0.0.1`). Binding off-loopback without an auth
  token is refused at boot unless explicitly overridden (`JARVIS_ALLOW_INSECURE_BIND=1`).
  For remote access, put it behind a reverse proxy with TLS.
- Run it as an unprivileged service — see the hardened templates in [`deploy/`](deploy/).
- The full trust docs already ship: [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) and
  [`docs/PRIVACY.md`](docs/PRIVACY.md) in the repo; `NOTICE` + the SBOM are generated
  into every release bundle (`scripts/build_release.sh`, H23.19 ✅).

## API keys & cloud calls (data locality)

The most common question from testers: *"does my API key — and my data — go through your
servers?"* **No.** There is no owner-operated backend or relay:

- **Your keys stay on your machine.** Cloud provider keys live only in your local `.env`
  (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, …). They are
  read at process start and used to call the provider **directly** from your box. They are
  never sent to us, logged to a remote service, or proxied through any third party.
- **Local-first by default.** Out of the box Jarvis routes to your local LM Studio / Ollama;
  cloud is **opt-in, per-agent**. The strict-local agents (`frigga`, `ultron`, `howard`) never
  leave the machine and fail closed rather than fall back to cloud.
- **Verify it yourself.** `grep -rn "api_key\|API_KEY" agents/core/llm/` shows every key read is
  a direct provider call; the network-egress panel (`GET /api/admin/network/calls`, HUD →
  Console → Network) records outbound calls so you can watch a `LOCAL_ONLY` agent make **zero**.
- **What can leave the machine** (only for cloud-routed agents, and only their prompt/response)
  is documented in [`docs/PRIVACY.md`](docs/PRIVACY.md); first-party analytics are cookieless and
  local (Plausible-style), never third-party.
- **Subscriptions ≠ API keys.** A ChatGPT Plus / Claude Pro subscription is **not** an API key
  and cannot be used here — Jarvis needs a provider **API key** (or a local model). See the
  [alpha FAQ](marketing/alpha-testing/FAQ.md) for the plain-language version.
