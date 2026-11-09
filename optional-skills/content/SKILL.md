# Content

> Veronica's content drafting — save & list platform drafts (LinkedIn, blog) locally

**Version:** 0.1.0
**Author:** claude
**Agents:** veronica

## Usage
Saves drafts as local JSON under `memory_logs/content_drafts/<platform>.json`.
Pure-local, no external network. Generation of the text itself is done by the
LLM; this skill persists and retrieves the drafts.

## Commands
- `draft <input>` — save a draft: `<platform>|<title>|<body>`
- `list_drafts <input>` — list saved drafts for `<platform>`

## Example Output
```
Draft salvat pentru linkedin (id a1b2c3d4): „AI în banking”.
Drafturi linkedin (2):
- [a1b2c3d4] AI în banking
```
