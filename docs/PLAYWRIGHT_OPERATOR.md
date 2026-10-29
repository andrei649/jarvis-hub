# Playwright Operator (H28.1)

The browser host stays off by default. Operator submits an exact `browser_run`
proposal through authenticated ToolRPC and shows its durable task and Decision
Inbox link. Execution requires owner acceptance, current mediation/registration/
worker evidence and exact per-step Kernel authority. A session ID is only a lookup
key; neither it nor page text grants permission.

## Local runtime prerequisites

Use `requirements-browser.txt` in an isolated hub Python environment. It pins
Playwright and psutil and uses an already installed Chrome/Chromium, without a
Playwright engine download. On this Mac the installed Chrome is under
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`; Linux checks the
normal Chrome/Chromium executable names. Native Windows browser acceptance remains
separate from this Mac fixture and the desktop adapter below.

Readiness requires `JARVIS_PLAYWRIGHT_HOST=1`, `JARVIS_UNIFIED_ACTION_API=1`, the
enabled Action Kernel, mediation in `enforce`, a current governed worker and trusted
browser registration, `JARVIS_PLAYWRIGHT_BROWSER=chromium`, optional libraries and
an installed engine. The server-owned `JARVIS_BROWSER_ALLOWED_DOMAINS` must contain
1–64 declared public domains. Unresolved native or journal cleanup blocks readiness.
These prerequisites are not activated by source installation.

`GET /api/browser/status` is a user-guarded read-only availability check. It does
not launch Chrome or resolve a site. Session/ref listing, task results and owner
close are admin-only: `GET /api/browser/sessions`, `GET /api/browser/tasks/{task_id}`
and `POST /api/browser/sessions/{session_id}/close`. A user-only token cannot read
those projections or stop a session. The owner projection contains bounded
origin/ref/status fields, not profile paths, raw task payloads or page dumps.

## One-shot and session use

The existing one-shot `{steps:[...]}` form starts with navigation and accepts
1–20 bounded `navigate`, `snapshot`, `extract`, `wait`, `click`, `type` and `submit`
steps. Operator **Run with approval** queues it for owner acceptance. Its fresh
temporary profile closes after the result.

Session requests use strict `mode` values:

- `start` supplies a bounded navigation-first `steps` plan and creates one fresh
  session after the exact task is approved.
- `act` supplies its `session_id` and a new separately approved `steps` plan.
  Snapshot returns grounded `@eN` handles. Session click/type/submit/scroll/press
  use those handles, never a selector fallback; navigation, extract, snapshot,
  wait and back use their declared bounded fields. Strict no-argument console and
  get_images reads are session-only and need a separate approved read task.
- `close` supplies only the session ID through the same approved task protocol.
  The authenticated owner close control may also stop its owned fresh session.

Each call rechecks owner, agent, task fingerprint, registration key/UUID epoch,
source/configuration, worker and current Kernel. Mutations, including scroll,
press and back, require exact task-bound step receipts. The preview/check
allowlist does not replace the server policy. Ref use rechecks the exact live
node, visible frame/document/origin, role/name/effective native form target and
focus for keys; stale targets return `stale_browser_ref` before dispatch.
Navigation/back/frame replacement invalidate old references.

Sessions allow one operation at a time, one per owner/agent and four globally,
with 60-second idle and ten-minute absolute limits. Registration/configuration/
control changes, cancellation and expiry begin bounded native close. An unchanged
real registration survives reaper ticks and remains usable by a later approved call.

## Bounded untrusted observations

Operator can queue `console` and `get_images` as separate session read tasks. The
same approved owner, registration, worker, current session, scope and Kernel read
checks apply. They are unavailable to generic one-shot plans. Completed owner task
output is rendered as untrusted text, with React escaping; it is not persistent
preview-pane inspection or execution authority.

Console retains at most 32 records/8,000 encoded bytes and 512 text characters per
record. It exposes allowlisted level/text, bounded source origin and document epoch;
no handles, argument objects, stack paths, headers or storage. Frame attribution
is unknown, so any frame navigation conservatively clears retained records.

Image inventory inspects at most 100 native image nodes in 16 current pinned frames,
returns at most 24 visible rows/8,000 encoded bytes and reports truncation/known
omissions. Bounded alt/dimensions/source metadata and an optional grounded ref come
from one DOM observation; source changes make the ref stale before action. Unpinned
sources are not fetchable and create no new pins or fetches. Owner HTTP projection
is separately bounded to 16,000 bytes. These observations do not provide image vision,
downloads, JavaScript execution, CDP or a dialog handler.

## Network and cleanup

All DNS answers must pass public policy. The same declared authority pins and
logical Host apply to navigation, frames, redirects and subresources; off-list,
private, unpinned and WebSocket destinations are blocked. Service workers and
WebRTC are disabled. LAN routing, owner cookies/logins and saved profiles are not
provided by the private-URL library flag.

A private ownership journal records the fresh profile/controller before launch,
then exact native PID and creation time. Verified close requires native process
exit, profile removal and settled journal/close ownership. Ambiguous restart
records remain quarantined; the server does not adopt an old profile or kill an
unverified process. Retained uncertainty blocks new execution until resolved.

## Local synthetic acceptance and remaining work

The reviewed Task31 `tests/test_browser_chromium_runtime.py` module has 35 cases, run with
isolated optional dependencies and installed local Chrome. It covers actual owner
ToolRPC/approval/worker/Kernel calls, cross-call refs, OOPIF/frame/focus/form semantics,
unchanged and changed registration, public pin/idle/redirect/WebSocket guards,
owner HTTP tiers, cancellation/native cleanup and exact journaled orphan reaping.
Fixtures use generated loopback pages and fresh profiles; their private test seam
cannot be supplied in a production request. Optional dependency skips establish
no native acceptance. These 35 cases are not a claim of 35 distinct launches.
Canonical integration additionally found an idle-journal assertion race; its settled
cleanup regression and subsequent runtime result are recorded separately.

Vision/dialog tools, CDP/browser_exec, other engines, LAN sidecar,
owner-profile consent, recording and snapshot spill remain accepted follow-ups.
The owner-host external-site/headed journey and other platforms retain separate
acceptance. Low-level driver methods do not make those tools callable.

## Windows desktop host (H28.4)

The optional Windows desktop adapter is a separate, accessibility-first host seam for
`GovernedDesktop`. It remains disabled unless the owner opts into **both** host actuation
and an isolated desktop session:

```powershell
python -m pip install pywinauto Pillow
$env:JARVIS_DESKTOP_HOST = "1"
$env:JARVIS_DESKTOP_ISOLATED = "1"
```

Construct and inject it only behind the governed Action Kernel path:

```python
from agents.core.desktop_host import WindowsDesktopDriver

driver = WindowsDesktopDriver.from_env(
    app_launchers={
        "browser": ("C:\\Program Files\\Browser\\browser.exe", "--private"),
    },
)
```

The request may supply only the canonical launcher key (`browser` in the example); it
cannot supply a binary path, arguments, or a shell string. The configured argv is launched
with `shell=False`. `click` and `type` require an accessibility element name and never accept
coordinate-only actuation. `locate` searches the bounded Windows UI Automation snapshot
before considering an explicitly injected, provenance-marked **local** VLM locator. There is
no cloud VLM client in the driver.

Accessibility output, typed text, local grounding output, and screenshot bytes are capped.
Screenshots are byte-checked before base64 encoding. Optional imports and backend startup are
lazy, so standard CI and default Jarvis startup require neither `pywinauto` nor Pillow. Raw
Windows, dependency, path, and window-title exceptions are reduced to bounded reason codes.
