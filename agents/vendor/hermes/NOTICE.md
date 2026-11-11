Hermes Agent is copyright Nous Research and its contributors, and is MIT licensed.
The full license text is in `LICENSE` beside this file (also `LICENSES/hermes-agent-MIT.txt`).

Source: https://github.com/NousResearch/hermes-agent
Commit: 9c0560f8e6856bc14c11bfe6d666df06be14d2de

The files listed in `MANIFEST.json` are copied from that commit. Each is byte-identical
to upstream except for the import rewrites the manifest records per file (for example
`import httpx` becomes `from agents.vendor.hermes_compat import httpx`), which point the
file at Nerva's compat layer (`agents/vendor/hermes_compat/`). The manifest also holds
each file's upstream and vendored sha256. `scripts/hermes_vendor.py status` checks them;
the procedure is in `docs/hermes/ADOPT_LANE.md`.

The skill catalog under `skills/` and `optional-skills/` (slice 3) is copied byte-identical,
with no rewrite; `SKILLS_CATALOG.json` (written by Nerva) indexes every upstream skill folder.

The MCP server catalog under `optional-mcps/` (slice 5) is copied byte-identical, one
`manifest.yaml` per folder, with no rewrite; its `MANIFEST.json` rows are its index.
