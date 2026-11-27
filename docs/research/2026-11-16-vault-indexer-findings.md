# Vault indexer findings: the ANDREI OS interface on a vault with a different layout

**Date:** 2026-11-16
**Scope:** `apps/jarvis-os/server.py`, `apps/jarvis-os/vault_fs.py` and `agents/core/routers/jarvis_os.py` as introduced by PR #1370. First checked at head `93ddc93`, re-checked at `8a513d5`; line numbers refer to `8a513d5`.
**Status:** the observations below describe the original indexer. The current hub
maintains a local SQLite FTS5 index and watches the configured vault for changes.

## Using the local integration

Configure the vault root, allowed and excluded relative paths, native index
paths and schemas, and an existing inbox in the private `.env`. The generic
keys are in `.env.example`. Start the hub normally. In the OS vault settings
or the HUD Vault console, check the note count, skipped hard links, last index
time and Memory Copilot connection. **Reindex vault** reconciles changes immediately.

The local index contains eligible Markdown text and Canvas metadata. A native
map can describe a much larger inventory, including excluded zones. The default
reader and the model-facing search omit restricted bodies. A direct loopback
owner can request a restricted Markdown note in an allowed zone with
`local_only=true`. Searches and graph navigation preserve the same folder policy.

In the owner's local web chat, ask “Ce proiecte sunt de terminat acum?” to
read the native priority queue directly. For a deeper search, choose a
local-only agent such as Frigga with its memory tools enabled. A loopback model
can search the scoped vault, the configured AI knowledge base and the fixed
Memory Copilot search tool. Raw memory results stay out of saved transcripts
and training trajectories.

Optional external builders operate on a temporary copy of permitted inputs.
Their derived SQLite file is published in the hub's private runtime directory
after the builder reports zero unmasked names and SQLite passes an integrity
check. The source vault and external archive databases retain their existing
files. The hub's own FTS index works independently of this option.

## Why this exists

The interface builds its knowledge graph from an Obsidian vault and was written against one
vault layout. The owner's current working vault has the same owner but different top-level
folders, more notes, a duplicated subtree and some private areas, and it sits in a folder
that a sync client uploads. Running the indexer against it showed the behaviours below. They
matter before that vault is connected for real, because retrieved notes are attached to
model calls.

## How it was checked

- Read `build_real_brain_graph`, `_classify_vault_hub`, `_parse_markdown_content`,
  `_allow_hardlinks`, `retrieve_vault_context`, `capture_inbox_note` and the hub router.
- Loaded `server.py` as a module (the way the router does) and called
  `build_real_brain_graph` and `retrieve_vault_context` against the working vault, in mode
  `andrei_os`. No server was started, nothing was written, no model was called.
- Only aggregate numbers are reported here. No note content, titles or names.

Result at `8a513d5`: with the defaults, 2 vault notes are indexed (see F10). With hard links
allowed, 958 nodes (946 from the vault) and 3,957 edges. The same graph was measured at
`93ddc93`, before hard links were filtered.

## Summary

| # | Finding | Impact | Size of fix |
|---|---|---|---|
| F1 | No privacy boundary: any note in the vault can be attached to a model call | high | medium |
| F2 | Hub classification is hard-coded to one vault layout | medium | small |
| F3 | Duplicate note names resolve silently; the first file visited wins | medium | medium |
| F4 | `canonical_keywords` matches substrings, so "ing" links unrelated notes | low | small |
| F5 | Short tokens and substring matching dominate retrieval | low | small |
| F6 | Frontmatter is read with two regular expressions | low | small |
| F7 | Non-note files become graph nodes | low | small |
| F8 | Defaults and labels assume one machine and one vault | low | small |
| F9 | Capture creates `08 Inbox` at the vault root | low | small |
| F10 | Hard-linked files are skipped by default; the documented config key has no effect | medium on a synced vault | small |

Suggested order: F1 before any vault with private areas is connected; F10 because it decides
whether a synced vault shows anything at all; then F5 and F4, which are small and improve
retrieval at once; then F2 and F3; then the rest.

## F1. No privacy boundary

**What happens.** `build_real_brain_graph` walks the whole vault. It skips directories whose
name starts with a dot, three manifest file names and, since `8a513d5`, links that leave the
vault. Nothing else: there is no folder exclusion and frontmatter such as `privacy:` is not
read. `retrieve_vault_context` scores every node, and the hub router returns the best
matches as attachments for `/chat` (`_ATTACHMENT_COUNT = 4`, `_ATTACHMENT_CHARS = 1500`).
`GET /api/os/brain/note` serves the body of any indexed note.

**Observed.** A folder of private personal notes, which the owner does not intend for any
model, was indexed in full. A generic question about what the agents could do next returned
notes from that folder as three of the four attachments. Behind a cloud provider this sends
private content off the machine without the owner having chosen to.

**Suggested change.**
- A configurable exclusion list of vault-relative folders (for example
  `JARVIS_OS_VAULT_EXCLUDE`), applied in the walk, so excluded notes never become nodes.
- A second tier for notes that may appear in the galaxy but must not be sent to a model:
  honour a frontmatter property (the vault already uses `privacy:` with values such as
  `private`, `personal-private` and, in newer notes, `restricted`) and leave those notes out
  of `retrieve_vault_context` and of the `/api/os/brain/retrieve` attachments.
- Apply the same rule to `/api/os/brain/note`.

**Suggested test.** A fixture vault with one excluded folder and one `privacy: restricted`
note: neither may appear in the attachments for a query that matches their text; the
excluded folder contributes no nodes.

## F2. Hub classification is hard-coded

**What happens.** `_classify_vault_hub` (lines 415-442) compares the first path segment with
a fixed list of folder names and returns the "00 Acasa" hub for anything else, including
files in the vault root.

**Observed.** 808 of the 946 vault notes (85%) landed in the fallback hub. The hub meant for
projects received 10 notes and the infrastructure hub 8. The galaxy collapses into one
cluster, and the category and path bonus in retrieval stops meaning anything.

**Suggested change.** Move the mapping to configuration (folder name or prefix to hub), with
a neutral fallback hub instead of the home hub, and report in `/api/os/status` how many notes
fell through to the fallback.

## F3. Duplicate note names resolve silently

**What happens.** `register_lookup` stores the lower-cased stem and title with `setdefault`
(line 641), so the first file the walk reaches owns the name. Wikilinks are reduced to a stem
before lookup (`_parse_markdown_content`), which discards the folder part of a path-style
link such as `[[folder/note|alias]]`.

**Observed.** The vault contains a second copy of a large subtree. 341 lookup keys had more
than one candidate. Links resolve to whichever copy is visited first, both copies are nodes,
and the same note came back twice among four retrieved notes.

**Suggested change.** Resolve path-style links by path first and fall back to the stem only
for bare links; treat byte-identical files as one node (hash on read); list ambiguous keys in
the status response so the owner can see them.

## F4. `canonical_keywords` matches substrings

**What happens.** `canonical_keywords` (line 797) is applied with `if kw in t_low`
(line 825), which adds an edge from any note whose title contains the keyword to a fixed
target note. One keyword is `"ing"` (line 805).

**Observed.** Every title containing "ing" (briefing, tuning, branding, routing and so on)
gets an edge to the note about a job interview at a bank of that name. The other short keys
have the same problem to a smaller degree.

**Suggested change.** Match on word boundaries, require a minimum keyword length, and move
the table to configuration next to the hub mapping.

## F5. Short tokens and substring matching dominate retrieval

**What happens.** `retrieve_vault_context` tokenises the query with `[\wăâîșț]{2,}`
(line 1023) and removes a short stop list. Tokens are then tested with `in` against the
title, category, path and body (from line 1048), which is substring matching. Synonym
expansion is triggered the same way (`if phrase in q_norm`, line 1031).

**Observed.** Common Romanian particles are not in the stop list and match almost every
note. Substring matching also produces false hits. In the F1 example the verb "face" matched
"Facebook" in the titles and bodies of the private notes, and that match alone put them
ahead of every project note (checked token by token on the four retrieved notes). The
synonym key `"pc"` fires for any query that contains those two letters inside a longer word
and pulls in hardware terms.

**Suggested change.** Whole-word matching for tokens and for synonym keys, a minimum token
length of three with a small allowlist for meaningful short tokens, and a fuller Romanian
stop list. `call_llm` already uses a three-character minimum for a related check.

## F6. Frontmatter is read with two regular expressions

**What happens.** `_parse_markdown_content` recognises `title:` and an inline
`tags: [a, b]` list (line 460). A YAML block list of tags yields none. No other property
reaches the node.

**Observed.** Part of the vault writes tags as block lists, so those notes have no tags in
the graph. Status, type and privacy are unavailable to the interface and to retrieval.

**Suggested change.** Parse a small YAML subset (scalars, inline and block lists) and expose
a short allowlist of properties on each node. F1 needs `privacy` in any case.

## F7. Non-note files become nodes

**What happens.** `_VAULT_EXTENSIONS` (line 496) lists `.md`, `.canvas`, `.html`, `.csv`,
`.json` and `.txt`. Everything except Markdown gets a placeholder body.

**Observed.** About 60 data and attachment files became nodes, and a `.txt` sidecar ranked
among the four retrieved notes for a one-word query on its title. A data file placed next to
the notes registers its name and can take an attachment slot although it has no content.

**Suggested change.** Index `.md` and `.canvas` by default; make other extensions an
explicit option or a separate, non-retrievable layer.

## F8. Defaults and labels assume one machine and one vault

**What happens.** The vault is searched for under one folder name in three places
(`_detect_default_vault_path`). When it is not found the interface falls back to
`demo_550`. `discoveredSources` reports literal counts (line 886) whatever was indexed.

**Observed.** On a machine where the vault folder has another name the interface shows the
demo galaxy until `JARVIS_OS_VAULT_PATH` is set, and the source panel describes a vault that
is not the one loaded.

**Suggested change.** Show the resolved path and the real node and link counts, drop the
literals, and state in the page when the demo is shown because no vault was found.

## F9. Capture creates `08 Inbox` at the vault root

**What happens.** `capture_inbox_note` creates `<vault>/08 Inbox` (`INBOX_FOLDER`, line 917)
if it is missing and links the new note to `[[Acasa]]` by default.

**Observed.** In a vault with another layout this adds a new top-level folder, which that
vault's own rules for assistants forbid, and the default link is ambiguous when two notes
share that name (see F3).

**Suggested change.** Make the inbox folder and the default link configurable, and answer
409 instead of creating a top-level folder that does not exist.

## F10. Hard-linked files are skipped by default

**What happens.** Since `8a513d5` the vault is read through `vault_fs.VaultFs`, which leaves
out files that have more than one hard link unless `_allow_hardlinks(cfg)` is true
(lines 511-520): the environment variable `JARVIS_OS_ALLOW_HARDLINKS` (or
`NERVA_OS_ALLOW_HARDLINKS`), or `cfg["allowHardLinks"]`. The README says
`"allowHardLinks": true` in `config.json` works as well, but `load_config` copies only the
names listed in `CONFIG_KEYS`, and `allowHardLinks` is not among them, so the standalone app
drops the setting. The hub route reads the environment flag and is not affected.

**Observed.** In the working vault 953 of 955 files have a second hard link, created by the
sync client that uploads the folder. With the defaults the graph has 2 vault notes out of
946. Nothing on the page says that files were skipped or why.

**Suggested change.** Add `allowHardLinks` to `CONFIG_KEYS` and to `config.example.json`;
report the number of files skipped for this reason in `/api/os/status` and show it on the
page, so an almost empty galaxy explains itself.

## Related idea

The working vault is getting a machine-readable index of its project notes (id, registry
status, stage, next step, links between projects; schema `andrei-proiecte-index/v1`, stored
next to the notes). When such a file is present the hub could read project state from it
instead of inferring it from note bodies.

## What is not claimed

- Nothing in the app was changed or run as a server; numbers come from one vault.
- The front end (`public/js`), the standalone provider router and the `/chat` path beyond the
  attachment limits named above were not reviewed.
- The branch is moving; a finding may already be addressed after `8a513d5`.
