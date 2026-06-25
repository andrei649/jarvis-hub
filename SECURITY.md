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

This is a pre-1.0 (`0.x`) project; only the **latest minor release line** receives
security fixes. Older lines are not back-patched — upgrade to the latest `0.MINOR.x`.

| Version line | Security fixes |
| ------------ | -------------- |
| `0.11.x` (current) | :white_check_mark: |
| `< 0.11`           | :x: (upgrade)      |

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
- For accepted issues: a fix on the supported `0.11.x` line and a published advisory
  crediting you (unless you prefer to remain anonymous).

There is no paid bug-bounty program. Coordinated disclosure is appreciated — please
give a reasonable window to ship a fix before any public write-up.

## Hardening & scope notes

- Default bind is **loopback** (`127.0.0.1`). Binding off-loopback without an auth
  token is refused at boot unless explicitly overridden (`JARVIS_ALLOW_INSECURE_BIND=1`).
  For remote access, put it behind a reverse proxy with TLS.
- Run it as an unprivileged service — see the hardened templates in [`deploy/`](deploy/).
- A deeper `THREAT_MODEL.md` + NOTICE/SBOM + telemetry/privacy disclosures are
  tracked under H23.19 and ship before 1.0.
