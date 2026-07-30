# Vendored Claude Code plugins

Plugins committed into this repo (public) so anyone who clones it and opens Claude
Code gets them with no marketplace fetch or network access. Activated via the
repo-local marketplace declared in `.claude/settings.json`
(`extraKnownMarketplaces` → `enabledPlugins`).

## superpowers/ (BACKLOG H22.7)
- **Source:** https://github.com/obra/superpowers
- **Version:** 6.2.0 (vendored 2026-08-06)
- **License:** MIT © Jesse Vincent — see `superpowers/LICENSE` and
  `LICENSES/superpowers-MIT.txt`.
- **What:** the full superpowers methodology + 14 core skills (TDD, debugging,
  brainstorming, writing-plans, subagent-driven-development, code review, …) and
  its SessionStart dispatcher hooks (`superpowers/hooks/hooks.json`), which
  activate automatically once the plugin is enabled.

### Staying current
Drift from upstream is tracked automatically: `.github/third-party-manifest.json`
pins the version, `scripts/check_thirdparty_drift.py` compares it to the latest
GitHub release, and `.github/workflows/thirdparty-drift.yml` runs weekly (opening
a tracking issue when behind). Run it locally with
`python scripts/check_thirdparty_drift.py`.

### Updating
Re-vendor from upstream, then bump the pin in `.github/third-party-manifest.json`:
```bash
git clone --depth 1 https://github.com/obra/superpowers /tmp/sp
rm -rf .claude/plugins/superpowers && cp -r /tmp/sp .claude/plugins/superpowers
rm -rf .claude/plugins/superpowers/.git
cp .claude/plugins/superpowers/LICENSE LICENSES/superpowers-MIT.txt
# then set "pinned_version" in .github/third-party-manifest.json to the new version
python scripts/check_thirdparty_drift.py --consistency   # must pass
```

> The repo-specific **jarvis** dev-skills live separately in `.claude/skills/`
> (`jarvis-load-context`, `jarvis-add-route`, `jarvis-write-test`,
> `jarvis-add-plugin`) — not part of this vendored upstream.
