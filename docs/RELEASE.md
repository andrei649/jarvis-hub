# Releasing Jarvis Hub (H23.13)

Jarvis runs **from source** — it is intentionally *not* a pip-installable package
(see [`pyproject.toml`](../pyproject.toml) / `CONTRIBUTING.md`). A release is therefore a
**source bundle** (`tar.gz` + `zip`) plus a software bill of materials and checksums,
attached to a GitHub Release. There is **no PyPI/wheel** by design.

## Cut a release

1. **Bump the version** — edit `__version__` in [`agents/__init__.py`](../agents/__init__.py)
   (the single source of truth, CDX-4). Update `STATUS.md` if needed. Commit.
2. **Tag and push:**
   ```bash
   git tag v0.12.0        # must equal v$(__version__)
   git push origin v0.12.0
   ```
3. The [`Release`](../.github/workflows/release.yml) workflow fires on the `v*.*.*` tag and:
   - **guards** that the tag equals `v<agents.__version__>` (fails fast on a forgotten bump),
   - builds the artifacts via [`scripts/build_release.sh`](../scripts/build_release.sh),
   - optionally **GPG-signs** them (if the owner configured the secret — see below),
   - creates the GitHub Release with auto-generated notes and uploads every artifact.

### Artifacts produced

| File | What |
| --- | --- |
| `jarvis-<ver>.tar.gz`, `jarvis-<ver>.zip` | Source bundle (git-tracked files only — `.env`, `agents/data/`, `memory_logs/`, `.venv/`, `node_modules/` are excluded automatically). |
| `SBOM.json` | CycloneDX 1.5 SBOM generated from `requirements-beta.txt`. |
| `NOTICE` | Third-party dependency list (run `pip-licenses` in the install venv for full license texts). |
| `SHA256SUMS` | Checksums for all of the above. |
| `*.asc` | Detached GPG signatures (only when signing is configured). |

## Build / test locally

```bash
scripts/build_release.sh dist      # writes dist/jarvis-<ver>.{tar.gz,zip}, SBOM.json, NOTICE, SHA256SUMS
```
`tests/test_release_build.py` exercises this end-to-end (artifacts present, checksums valid,
no secret/data leakage, valid CycloneDX). You can also dry-run the **CI path** without cutting a
tag: Actions → *Release* → *Run workflow* (builds artifacts; creates no Release).

## Verify a downloaded release

```bash
sha256sum -c SHA256SUMS                          # integrity
gpg --verify jarvis-<ver>.tar.gz.asc jarvis-<ver>.tar.gz   # authenticity (if signed)
```

## Optional, owner-gated add-ons

These are off by default and require owner action (they touch keys / external registries):

- **GPG signing** — generate a signing key, then add repo **secrets** `GPG_PRIVATE_KEY`
  (ASCII-armored private key, `gpg --armor --export-secret-keys <KEYID>`) and, if the key has one,
  `GPG_PASSPHRASE`. The workflow then emits `.asc` signatures automatically. Tracked in
  [`docs/OWNER_TASKS.md`](OWNER_TASKS.md).
- **Docker image publishing** — [`docker-compose.yml`](../docker-compose.yml) already builds and runs
  the stack locally (Python 3.12 slim + Qdrant + Neo4j + n8n). Publishing a prebuilt image to a
  registry (e.g. `ghcr.io`) is an opt-in owner decision: it needs registry permissions and a
  `docker/build-push` step. Until then, users build locally with `docker compose up`.

## Reproducibility

`git archive` is deterministic for a given commit, and `SBOM.json`/`NOTICE` derive from the
name-sorted requirements file — so re-running the build at the same commit yields identical bundles.
