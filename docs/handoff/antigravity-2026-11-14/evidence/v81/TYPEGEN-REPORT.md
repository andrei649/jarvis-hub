# Actual type generation on root's V81 combined source

Source: `/workspace/scratch/nerva-v81-combined/source`. Executed 2026-11-13 UTC using the same existing integrity-verified `openapi-typescript@7.13.0` package/dependency cache and existing Python runtime as the V80 check. No installations, downloads, server/lifespan activation, registry substitution, or input source writes.

**PASS:** Fresh actual `agents.web.app.openapi()` contains 785 paths, 876 operations and 262 schemas. It is semantically identical to V80's actual export. The pinned generator ran against that complete fresh JSON with exit 0 and reproduced the delivered `frontend/src/api/schema.gen.ts` byte-for-byte. SHA-256: `c879e6e3c198d36d41dc2946b5082122ac8f073154a0414c8f1f56d4d1b96060`.

`production-hash-proof-initial.json` compares all 7,066 frozen V80 source files against the root's integrated source, including executable modes. Existing changes are generated status documents and the intended Chromium fixture. Every production file under `agents/`, `frontend/`, `mobile/`, `services/`, and `scripts/` is unchanged. The prior full frontend `tsc --noEmit` result continues to apply because all frontend sources/configuration and the generated schema are byte-identical; no additional frontend TypeScript run is claimed here.

The exporter reads the actual registered application without changing routes or registry. Its audit hook blocks socket bind/connect and all writes outside this owned final evidence area. Python bytecode caching is off, and runtime/TMPDIR are redirected into the evidence area. An initial export attempt used the parent's TMPDIR outside the narrower final audit scope; the audit hook blocked that write. The rerun with final/TMPDIR succeeded.

Evidence: `export_openapi.py`, `export.log`, `export.exit`, `openapi.json`, `generator.log`, `generator.exit`, `schema.gen.ts`, `production-hash-proof-initial.json`. Final root manifest/tree confirmation follows the coordinator's source freeze; generation is valid while these production/schema bytes remain unchanged.

## Frozen final source receipt

Confirmed local commit `68366dd776291facd4da5692fce9e01adf74bc69`, exact tree `9deba0f24220f9f0f89fee585f2a923e549cecc1`, 7,068 source files. Manifest SHA-256: `faa2b4c2bac41aee833227f0d4146e454f4bdc8016ad6a9f36a080ebff4f0f67`.

On this frozen source, the reviewer repeated the actual application export and pinned generator again. Export and generator exit codes are 0. The generated schema again matches the committed file byte-for-byte, SHA-256 `c879e6e3c198d36d41dc2946b5082122ac8f073154a0414c8f1f56d4d1b96060`.

Before and after this final execution, every manifest path matched SHA-256, byte length, Git blob hash and executable mode. Independently reconstructing the Git tree from those exact files yields `9deba0f24220f9f0f89fee585f2a923e549cecc1`. The before/after verification receipts are identical; there are zero missing files or content/mode mismatches. The sole nonmanifest path is the pre-existing `.git` pointer. Read-only Git inspection confirms the requested commit/tree and clean status.

Comparing final and V80 frozen manifests shows exactly five generated status documents plus the existing Chromium fixture changed, and exactly two test files added. No files were removed. All production/schema/frontend bytes and modes remain identical to V80. The earlier successful full frontend tsc check therefore still applies, without claiming another TypeScript run.

The final frozen helper SHA-256 is `bf4df65715e1cb66f97bc078176104c7a072fd48fa51c543d09247527143c646`, matching the independently approved helper and diagnostic probe. This receipt establishes actual combined generation and unchanged source bytes for the exact final tree; it does not claim a GitHub CI run or platform/provider acceptance.

Final evidence: `frozen-before-verification.json`, `frozen-after-verification.json`, `frozen-production-proof.json`, `frozen-export.log`, `frozen-export.exit`, `frozen-generator.log`, `frozen-generator.exit`, `source-status.txt`.
