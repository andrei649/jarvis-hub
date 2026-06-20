# Trialing codebase-memory-mcp (BACKLOG H22.8)

> Goal: give coding assistants a structural index of this repo (tree-sitter →
> knowledge graph) so they find symbols without reading file-by-file — automating
> what `docs/AI_CONTEXT.md` does by hand against the ~2M-token codebase.

## What it is
[`DeusData/codebase-memory-mcp`](https://github.com/DeusData/codebase-memory-mcp)
— a single-binary MCP server that indexes a repo into SQLite (tree-sitter entities
as graph nodes + `IMPORTS`/`CALLS` edges, FTS5 BM25, bundled int8 vectors) and
exposes ~14 retrieval tools (`index_repository`, `semantic_query`, `search_code`,
`query_graph`, `trace_path`). Claims large token reductions vs file-by-file.

## Setup (per developer — host action)
1. Install the binary per the upstream README (it ships as a `curl | bash`
   installer; it's SLSA L3 + checksum-signed, but **review the installer first**).
2. Copy the example config and opt in:
   ```
   cp .mcp.json.example .mcp.json
   ```
   `.mcp.json` is gitignored — keep it local; do not commit a live config that
   references a binary other devs may not have installed.
3. **Verify the exact `command`/`args`** in `.mcp.json` against the upstream
   README — the example here is a best-guess invocation, not confirmed.
4. Restart the assistant; run the `index_repository` tool once on this repo.

## Caveats before adopting permanently
- Its bundled int8 embeddings are weaker than jarvis's own embedding stack — treat
  this as a **dev-loop** index, not a product dependency.
- It's a trial: if it doesn't earn its keep over `docs/AI_CONTEXT.md` bundles,
  drop the `.mcp.json` and close H22.8.
