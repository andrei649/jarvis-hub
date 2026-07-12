# Playwright Operator (H28.1)

Jarvis keeps browser actuation off by default. `GovernedBrowser` still uses
`NullBrowserDriver` unless a caller explicitly injects `PlaywrightBrowserDriver`.

## Host setup

Install the optional Python runtime and one browser binary in the Jarvis environment:

```powershell
python -m pip install playwright
python -m playwright install chromium
$env:JARVIS_PLAYWRIGHT_HOST = "1"
```

Optional settings:

- `JARVIS_PLAYWRIGHT_BROWSER=chromium|firefox|webkit` (default `chromium`)
- `JARVIS_PLAYWRIGHT_HEADLESS=1|0` (default `1`)
- `JARVIS_PLAYWRIGHT_DOWNLOAD_DIR=<absolute path>` (required only for downloads)

## Governed use

```python
from agents.core.browser_agent import BrowserPolicy, GovernedBrowser
from agents.core.browser_playwright import PlaywrightBrowserDriver

policy = BrowserPolicy(["example.com"])
driver = PlaywrightBrowserDriver.from_env()
driver.set_url_guard(policy.domain_allowed)
browser = GovernedBrowser(
    driver=driver,
    policy=policy,
    approvals=approval_queue,
)
try:
    result = await browser.run([
        {"action": "navigate", "url": "https://example.com"},
        {"action": "extract", "selector": "main"},
    ])
finally:
    await driver.close()
```

The driver refuses to start until a per-request URL guard is explicitly bound. Passing
the same `BrowserPolicy.domain_allowed` guard used by `GovernedBrowser` means off-list
navigation, redirects, and subresources are checked before each request. Click/type/submit/download/
execute-js/upload still require the existing approval queue. Each driver instance
creates a fresh browser context with no ambient cookies or cache. Screenshots are
returned in memory; service workers are blocked so they cannot bypass request routing;
downloads require an explicit directory and are saved with sanitized filenames.

## Live smoke

The normal suite uses a faithful async fake and needs no Playwright installation. To run
the owner-gated Chromium smoke after host setup:

```powershell
$env:JARVIS_PLAYWRIGHT_LIVE = "1"
python -m pytest tests/test_h28_playwright_driver.py -q
```
