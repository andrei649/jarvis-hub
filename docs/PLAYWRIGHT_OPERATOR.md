# Playwright Operator (H28.1)

The browser host stays off by default. The current owner Operator panel can submit
one governed `browser_run` plan through authenticated `/api/toolrpc/call`, then
show its durable task id and Decision Inbox link. Execution requires the owner's
accepted task, current mediation/registration/worker evidence and exact per-step
Kernel authority. Calling the driver directly is not an execution permission.

## Local runtime prerequisites

Install `requirements-browser.txt` into the isolated Python environment used by the
hub. It pins Playwright and psutil; an already installed Google Chrome supplies the
engine, so this path does not require a Playwright browser download. The current
Mac path is `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`; Linux
also checks the usual Chrome/Chromium executable names on PATH. Native Windows
browser acceptance remains unverified; the separate desktop seam below is unchanged.

The server needs all of the following before readiness can become true:

- `JARVIS_PLAYWRIGHT_HOST=1` and `JARVIS_UNIFIED_ACTION_API=1`.
- The Action Kernel enabled and task mediation in `enforce` mode
  (`JARVIS_TASK_MEDIATION=enforce`), with the current governed worker registered.
- `JARVIS_PLAYWRIGHT_BROWSER=chromium` (the default).
- A nonempty server-owned `JARVIS_BROWSER_ALLOWED_DOMAINS` list, at most64 entries.
- The optional Python libraries, installed engine and no unresolved browser cleanup.

These are prerequisites for a later owner-controlled activation, not settings this
implementation enables automatically. `GET /api/browser/status` is a user-guarded,
read-only availability check; it neither launches Chrome nor resolves a site. A
missing prerequisite or uncertain cleanup returns `available:false`.

## Governed use

In Operator, create a plan starting with navigation and choose **Run with approval**.
The HUD rechecks server readiness, submits only the steps, and displays the task id
and Decision Inbox link. Approve that exact task as the owner. The server rechecks
its durable plan, configuration, registration and worker identity before execution.
The editable allowlist used by **Check** and **Preview** is not execution authority;
the server's domain list and pinned resolver govern real requests.

The registered schema accepts1–20 steps: `navigate`, `snapshot`, `extract`, `wait`,
`click`, `type` and `submit`. It caps the plan and its strings and rejects extra
fields. Click/type/submit use exact task-bound `browser.step` receipts; reads and
navigation recheck live Kernel policy after awaits. The runtime owns one fresh
temporary profile, without the owner's saved cookies or logins.

All DNS answers must pass the public policy. The same allowlist and IP pins apply
to navigation, redirects and subresources; unpinned destinations and WebSockets are
blocked. The governed path does not enable LAN browsing through the library's
private-URL flag. It blocks service workers and WebRTC and verifies actual owned
Chrome process exit before deleting its profile. Interrupted or uncertain cleanup
retains its owner and blocks new execution until resolved.

Stable element references, scroll/back/press, image/vision/console/dialog tools,
CDP/browser_exec, other engines, real profiles, recording and durable sessions remain
accepted follow-ups. Low-level driver methods do not make those tools available.

## Local synthetic acceptance

`tests/test_browser_chromium_runtime.py` exercises the authenticated owner ToolRPC
proposal and approval path against a private ephemeral loopback fixture. Its9 cases
include four test functions with five actual installed-Chrome launches and five
prelaunch/status checks. They verify pins, one mutation, denial, timeout/cancellation,
readiness and native-process/profile cleanup. The test-only loopback policy cannot
be supplied in a production request.

The recorded local run used an isolated `.venv-browser` Playwright installation
with canonical test dependencies. Running the canonical environment without the
optional package may skip those cases; a skip is not native acceptance. This Mac
fixture is separate from the owner-host external-site/headed proof in the manual,
other platforms, saved-profile consent and advanced browser acceptance.

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
