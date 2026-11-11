# The Hermes skill catalog

Nerva ships the skills of Hermes Agent (MIT, `NousResearch/hermes-agent`) as an **inert
catalog**: they sit on disk, pinned to one upstream commit, and do nothing until you install
one. This is the page Hermes keeps for its `optional-skills` (`hermes skills browse --source
official`, `hermes skills install official/<category>/<skill>`), for Nerva.

How it is built and refreshed (the vendor script, the manifest, why a skill with code is not
installable) is in [`docs/hermes/ADOPT_LANE.md`](hermes/ADOPT_LANE.md) → "Skills (slice 3)".

## What is in it (pin `9c0560f8`)

185 skills: 44 from Hermes's `skills/`, 141 from its `optional-skills/`.

| Kind | Count | What you can do |
|---|---|---|
| installable (`instruction`) | 125 | install, repair. Instructions and plain data (`.md`, `.txt`, `.yaml`, `.yml`, `.json`, `LICENSE`) only |
| carries code (`upstream_only`) | 55 | browse only: the list shows which code files it carries. The catalog refuses it (422) |
| excluded | 5 | browse only, with the reason (HTML templates, or a reference over 256 KB) |

By category:

| Category | Skills | Installable | Carry code | Excluded |
|---|---:|---:|---:|---:|
| `creative` | 40 | 24 | 13 | 3 |
| `mlops` | 23 | 21 | 0 | 2 |
| `productivity` | 19 | 11 | 8 | 0 |
| `software-development` | 18 | 16 | 2 | 0 |
| `research` | 16 | 7 | 9 | 0 |
| `autonomous-ai-agents` | 11 | 10 | 1 | 0 |
| `finance` | 9 | 5 | 4 | 0 |
| `devops` | 8 | 6 | 2 | 0 |
| `security` | 6 | 2 | 4 | 0 |
| `web-development` | 5 | 2 | 3 | 0 |
| `apple` | 4 | 4 | 0 | 0 |
| `blockchain` | 3 | 0 | 3 | 0 |
| `email` | 3 | 3 | 0 | 0 |
| `mcp` | 3 | 1 | 2 | 0 |
| `media` | 3 | 2 | 1 | 0 |
| `gaming` | 2 | 2 | 0 | 0 |
| `health` | 2 | 1 | 1 | 0 |
| `payments` | 2 | 2 | 0 | 0 |
| `social-media` | 2 | 1 | 1 | 0 |
| `communication`, `data-science`, `dogfood`, `note-taking`, `smart-home` | 1 each | 1 each | 0 | 0 |
| `web` | 1 | 0 | 1 | 0 |

The live numbers are the catalog's own: `nerva skills catalog` prints them on its first line,
and `GET /skills/imported` carries them as `hermes_catalog.counts`.

## Browse

```bash
nerva skills catalog                          # at most 100 rows, like `hermes skills browse`
nerva skills catalog --search mail            # slug, name, category, description or tags
nerva skills catalog --category mlops
nerva skills catalog --kind upstream_only     # the skills that carry code, with their files
nerva skills catalog --limit 20 --json
```

A browse shows at most 100 rows (Hermes caps a browse at 100 results a source; `--limit` takes
1–100) and says `showing N of M` when it cut the list. Each row says `install`, `installed`,
`code` or `excluded`, the keys the skill declares (`needs AGENTMAIL_API_KEY`) and whether its
text was flagged as instruction-like. In the HUD, the **Skills Import** panel lists the same
rows with a filter.

## Install

```bash
nerva skills catalog install email/agentmail      # or: agentmail, official/email/agentmail
```

Installing is an **owner action**: the admin token (`JARVIS_ADMIN_TOKEN`), through
`POST /api/skills/catalog/install`, or the panel's **install** button. It does **not** need
`DEV_MODE`, unlike every other skill import, because these bytes are pinned to one upstream
commit, checked file by file against `agents/vendor/hermes/MANIFEST.json` before every write
(a difference writes nothing and answers 503), and carry instructions only. A user token
cannot install; `POST /skills/import` (any source, the catalog's included) keeps its
`DEV_MODE` gate.

The skill is copied into your skills folder through the importer's usual checks: the SKILL.md
validator, a folder of that name that you or another source wrote is left alone (409
`exists`), a name another skill holds is refused (409 `name_taken`). The install is recorded in
the intent log as `skill.install`. An installed catalog skill has no more trust than any
import: its text is read as data until you vouch for it, and a key it declares is offered to
the code tool only after that.

## Repair

```bash
nerva skills catalog repair agentmail             # put back deleted files
nerva skills catalog repair agentmail --force     # also replace files you edited
```

Hermes's `repair-official --restore`. The install recorded the sha256 of every file it wrote;
a repair compares the folder with that record and:

- restores every **deleted** file from the vendored bytes;
- **refuses** (409 `local_edits`, with the list of files) when a file was **edited**, unless
  you pass `--force` (HUD: **replace my edits**), which first keeps a copy of each edited file
  in `<data root>/skills/catalog-repair-backups/<skill>/<time>/`;
- answers `intact` and writes nothing when every file matches;
- brings the skill up to the catalog's commit when the catalog moved since you installed it.

Files you added to the folder are not the catalog's and are never touched. A skill the catalog
did not install (your own, another source's import, the older network import of Hermes) is
never repaired (409 `not_from_catalog`); one that is not installed answers 404
`not_installed`. Installing a skill that is already installed is a repair without `--force`,
so it never overwrites your edits. Each repair that writes is recorded as `skill.repair`.

## What it does not do

- **Skills that carry code** (55) are not installable from the catalog. Nerva's imports copy a
  SKILL.md and plain data only; code reaches Nerva only as a marketplace package (an admin
  install whose code is scanned and is not run in-process without a keyed signature or your
  approval). A scanned, approved package path for these 55 is still open (Hermes ledger H336).
- There is no uninstall verb here: remove the folder, or use the skill batch delete.

## Two official pins, on purpose

Nerva reaches Hermes's skills at two upstream commits, and the HUD says which one each row uses:

| Source | Pin | Why this pin |
|---|---|---|
| `hermes-catalog` (this catalog, offline) | `9c0560f8` (main, 2026-11-10) | The Adopt lane vendors one main-branch commit for every slice (providers, skills, MCP manifests); `agents/vendor/hermes/NOTICE.md`. |
| `hermes` (the network import, `POST /skills/import`) | `v2026.8.31` = `29112bef` | `hermes_pin_v2.json` must name a **release**: its loader refuses any other tag, and each page in `docs/skills/hermes/` cites it. |

They are not aligned because the catalog commit is not a release, and moving the import pin to a
main-branch commit would drop that guarantee; moving the catalog back would drop two months of
upstream fixes. `GET /api/skills/taps` measures the gap on the two records
(`pin_alignment`): of the 190 skills the import pin lists, 87 have byte-identical SKILL.md in the
catalog, 68 changed and 35 are not in it (renamed or removed upstream). When Hermes cuts a release
at or after the catalog commit, both can move to it together.

## Skill sources (taps) and setup values

**Taps** (`GET /api/skills/taps`, HUD → Skills Import → Skill sources) list every source the owner
trusts: the two official ones above (built in, cannot be removed) and GitHub repositories the
owner added.

- **Adding a tap** (`POST /api/skills/taps`, admin) takes `repo`, an exact 40-hex `commit`, a
  `path` (default `skills`) and a trust level (`trusted` or `community`; `official` is the
  built-ins' alone). It only queues an approval card at the irreversible tier, with the source
  URL on the card. Nothing is fetched or searchable until a person accepts the card. A branch or a
  tag is refused: a tap moves to another commit only by remove + add.
- **Refresh** (`POST /api/skills/taps/<id>/refresh`) reads the repository's tree and each
  `<path>/<skill>/SKILL.md` (and `references/`) at that commit, through the governed egress client
  (the kernel's `plugin.egress` for every request, only `api.github.com` and
  `raw.githubusercontent.com`, no redirects, 8 MB a refresh, 100 skills a tap). Entries that fail
  (an unsafe name or path, an invalid SKILL.md, a `name` that is not its folder) are listed as
  refused and are never installable.
- **Search** (`GET /api/skills/taps/search?q=`) covers every active source, ranked official >
  trusted > community.
- **Install** (`POST /api/skills/taps/install`, admin) hands the tap's pin (commit, path,
  sha256 of the SKILL.md and of each reference) to `POST /skills/import`'s own import: the bytes
  are fetched again at that commit and checked, `skill.install` is crossed before and after, and
  the skill lands quarantined pending your review. Code in a tapped skill's folder is not copied.

**Setup values** (`GET /api/skills/setup/<skill>`, HUD → Skill setup). A skill may declare the
environment variables it needs (`required_environment_variables`, `setup.collect_secrets`). The
panel lists which are set (stored for this skill, or in the hub's environment) and which are
missing; a value set there is stored encrypted, never shown again, never placed in the hub's
environment, and handed only to that skill's own commands, for the install you set it for. It never
reaches the code interpreter (`execute_code` runs code the model writes; it keeps reading only the
hub's `.env`), and a skill's error text is scrubbed of it (as is, URL-encoded, base64). Another
skill that later takes the same name does not get it, and removing the skill clears it. A runnable
skill with a required value missing refuses to run and says which. Managed provider keys and
control names (`PATH`, `JARVIS_*` …) cannot be set for a skill; the panel says only that they are
reserved, not whether the hub has them.
