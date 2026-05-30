# Quick-start for opencode

Paste this prompt into opencode (after navigating to your `cabinet/` directory):

```
Read design_handoff_jarvis_hub/README.md end-to-end first.
Then implement the design described there, targeting:

  cabinet/agents/web/templates/index.html
  cabinet/agents/web/static/style.css
  cabinet/agents/web/static/data.js
  cabinet/agents/web/static/app.js
  cabinet/agents/web/static/components.js
  cabinet/agents/web/static/network.js
  cabinet/agents/web/static/enhancements.js

Use the prototype in design_handoff_jarvis_hub/design/ as the
visual + behavioral source of truth. Match it pixel-perfect.

Mode A (recommended): keep React via CDN, port .jsx → .js by
replacing JSX with React.createElement calls. Drop Babel.

Use existing aiohttp endpoints (/status, /chat/stream, /dashboard,
etc.). Add GET /tasks endpoint (stub with [] if needed).
Skip WebSocket for now — use 30s polling. Note in code where WS
events would replace polling.

After each file, show me a 10-line summary of what you did
before moving to the next. Work in the order from §13 of the README.
```

That's it. opencode will read the full README + design files on its own.
