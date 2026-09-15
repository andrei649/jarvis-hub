# Compatible mobile lock security updates

Base 4687c2be800a50fb8b89ede26ce13e80e49f5d28. Preserve every direct package version and manifest range, Expo Metro0.84.5, and SDK architecture. No audit fix/force/major override, telemetry/login/deployment, global metadata.

Target only audited transitive groups: xmldom0.8.15/0.9.12, baseline-browser-mapping2.11+, brace-expansion5.0.9+, browserslist4.28.7+, nested js-yaml3.15.2, shell-quote1.9+, RN CLI Metro0.87.1 family (upstream replaces image-size). Existing parent ranges admit each update. Inventory every changed/new/removed package, reject incidental upgrades. Clean npm ci then full TypeScript/Jest, offline Expo config and native bundle smoke if feasible. Fresh audit must verify remaining findings.

Baseline audit21 (9high/12moderate) /tmp/nerva-mobile-audit.json. Expected remaining UUID/Xcode inheritance is not assumed verified. xcode latest3.0.1 requires uuid^7.0.3, whereas patch starts11.1.1. xcode usesv4, advisory affectsbufferedv3/v5/v6; no demonstrated release-app exposure. Most vulnerable paths are build/dev tooling; declaration as production dependency does not prove mobile release reachability.

Primary references: https://github.com/react/metro/releases/tag/v0.87.1 ; https://github.com/xmldom/xmldom/security/advisories/GHSA-965w-775f-mr7g ; https://github.com/browserslist/browserslist/security/advisories/GHSA-c83g-rgw3-j3cx ; https://github.com/uuidjs/uuid/security/advisories/GHSA-w5hq-g745-h8pq . Full per-group evidence and outcomes to follow.

Implementation complete; exact package deltas, primary evidence, verified audit11 and native-export baseline blocker are recorded in `docs/mobile-lock-security-audit.md`. Next action independent source/lock review.
