# Mobile transitive security lock update — 2026-09-15

Base: `4687c2be800a50fb8b89ede26ce13e80e49f5d28`. No manifest, direct dependency version/integrity, SDK or application source changes. All direct production AND dev package records were compared and are identical. Expo's Metro0.84.5 package record and dependency family remain unchanged. No overrides or audit-fix commands.

Targeted `npm update --package-lock-only --ignore-scripts --no-audit --no-fund @xmldom/xmldom baseline-browser-mapping brace-expansion browserslist js-yaml shell-quote metro` resolves compatible audited groups. Restored the unrelated test-exclude brace-expansion2.1.4 record from the base after npm attempted an incidental2.1.7 refresh. Clean npmci validates the resulting lock. No other incidental updates retained.

## Complete package delta

26 changed package records, two additions, two removals. Fifteen changed packages are the coordinated RN CLI Metro0.87.1 family. Every changed version has a changed registry SHA512 integrity; no same-version integrity rewrite. Full digests are in the lock diff and `/tmp/nerva-mobile-security-lock-delta.json`; abbreviated digests below identify each old/new record.

| Package path (under node_modules) | Version | Integrity old → new (prefix) | Reason |
|---|---|---|---|
| `@istanbuljs/load-nyc-config/node_modules/js-yaml` | 3.14.2 → 3.15.2 | `sha512-PMSmkqxr106Xa15` → `sha512-6EuL879VkRA+1Cz` | Audited vulnerable transitive package, updated within existing parent range. |
| `@react-native/community-cli-plugin/node_modules/metro` | 0.87.0 → 0.87.1 | `sha512-fRqFhSzQhLNQSCv` → `sha512-1oyLU9elM7hPAsK` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-babel-transformer` | 0.87.0 → 0.87.1 | `sha512-IEn1K1FyY4J1sA5` → `sha512-orvRIGpb0yK1yMb` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-cache` | 0.87.0 → 0.87.1 | `sha512-146vS1BMSKcp99j` → `sha512-juNPaj0Xi5tkLp8` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-cache-key` | 0.87.0 → 0.87.1 | `sha512-Q+MPt6jl0zQogr4` → `sha512-scqVVPMA2c+RVO1` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-config` | 0.87.0 → 0.87.1 | `sha512-yZ9QAIzWH9Mxwrz` → `sha512-NmkDlc/qZAdo5gT` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-core` | 0.87.0 → 0.87.1 | `sha512-yW57+pCOHRC/CJZ` → `sha512-xizzky/4+c/Mkzn` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-file-map` | 0.87.0 → 0.87.1 | `sha512-Dc57t8jsINwA90b` → `sha512-9sPuNCojC3pS4vj` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-minify-terser` | 0.87.0 → 0.87.1 | `sha512-tPa0O983PDutFu3` → `sha512-YK4k1oO1wV48hfE` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-resolver` | 0.87.0 → 0.87.1 | `sha512-Xl3M9R3KToaHJvX` → `sha512-FXH/brY69wT6sPx` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-runtime` | 0.87.0 → 0.87.1 | `sha512-XsXZkgEwI0ZMYSB` → `sha512-kjeuSvInsM6OzBj` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-source-map` | 0.87.0 → 0.87.1 | `sha512-31BrYqu1c2co93r` → `sha512-Bqpm0PBGdy53pig` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-symbolicate` | 0.87.0 → 0.87.1 | `sha512-uOpTxAXu74N+RSu` → `sha512-rcGvwabrg0lbXGR` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-transform-plugins` | 0.87.0 → 0.87.1 | `sha512-i8keUe9+BaSwMuQ` → `sha512-qMiJ/x+VfqumFJJ` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/metro-transform-worker` | 0.87.0 → 0.87.1 | `sha512-YftLzNJxCTYxEN5` → `sha512-VOzs3OV405FuOLY` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@react-native/community-cli-plugin/node_modules/ob1` | 0.87.0 → 0.87.1 | `sha512-8Q8sKCiUwsxgSmj` → `sha512-i8iA8uij0g1YQzS` | Coordinated Metro 0.87.1 dependency family (including ob1). |
| `@xmldom/xmldom` | 0.8.13 → 0.8.15 | `sha512-KRYzxepc14G/CEp` → `sha512-/5NV/vDALVFDXgL` | Audited vulnerable transitive package, updated within existing parent range. |
| `baseline-browser-mapping` | 2.10.34 → 2.11.23 | `sha512-IMDedajPifLnHNY` → `sha512-le521dGVfxM7yRX` | Audited vulnerable transitive package, updated within existing parent range. |
| `brace-expansion` | 5.0.6 → 5.0.12 | `sha512-kLpxurY4Z4r9sgM` → `sha512-YovQ3rzhaLMIrDj` | Audited vulnerable transitive package, updated within existing parent range. |
| `browserslist` | 4.28.2 → 4.29.0 | `sha512-48xSriZYYg+8qXn` → `sha512-3GSvyjvDI4Dur1M` | Audited vulnerable transitive package, updated within existing parent range. |
| `caniuse-lite` | 1.0.30001793 → 1.0.30001810 | `sha512-iwSsYWaCOoh26cV` → `sha512-TITQPUkaz+aVk5G` | New minimum dependency range required by Browserslist 4.29.0. |
| `electron-to-chromium` | 1.5.368 → 1.5.428 | `sha512-7RckJJK4uESJF9P` → `sha512-1JxbaFJj1bRKurj` | New minimum dependency range required by Browserslist 4.29.0. |
| `flow-estree` | absent → 0.331.0 | `—` → `sha512-FVLYkSL/ITb/QXB` | Required by the new flow-parser. |
| `flow-parser` | absent → 0.331.0 | `—` → `sha512-vEZcHIlnKeN8JSV` | Required by Metro 0.87.1 instead of its previous parser dependency. |
| `image-size` | 1.2.1 → removed | `sha512-rH+46sQJ2dlwfjf` → `—` | Removed by Metro upstream security fix. |
| `node-releases` | 2.0.47 → 2.0.55 | `sha512-Uzmd6LXpouKo8EU` → `sha512-mIrE/Cw9y+9Au6d` | New minimum dependency range required by Browserslist 4.29.0. |
| `plist/node_modules/@xmldom/xmldom` | 0.9.10 → 0.9.12 | `sha512-A9gOqLdi6cV4iba` → `sha512-5AXjrcMClTryPe9` | Audited vulnerable transitive package, updated within existing parent range. |
| `queue` | 6.0.2 → removed | `sha512-iHZWu+q3IdFZFX3` → `—` | Only required by the removed image-size. |
| `shell-quote` | 1.8.4 → 1.10.0 | `sha512-VsC6n6vz1ihYYyZ` → `sha512-w1aiOKwKuRgtwAR` | Audited vulnerable transitive package, updated within existing parent range. |
| `update-browserslist-db` | 1.2.3 → 1.3.3 | `sha512-Js0m9cx+qOgDxo0` → `sha512-pJ2sYawQS0R/WI9` | New minimum dependency range required by Browserslist 4.29.0. |

## Verified outcomes

- Clean `npm ci --no-audit --no-fund`: exit0,1247 installed packages; `/tmp/nerva-mobile-security-ci.log`. Existing install-script policy reports two unapproved hooks; no approval/config change made.
- `tsc --noEmit`: exit0, `/tmp/nerva-mobile-security-tsc.log`.
- Full `jest --runInBand`:32 suites/137 tests passed, `/tmp/nerva-mobile-security-jest.log`.
- Offline/telemetry-disabled Expo public config:exit0, `/tmp/nerva-mobile-security-expo-config.json` and `.log`.
- Fresh `npm audit --json`:**11 moderate, zero high/critical**, down from21 (12moderate/9high). Audit exits1 because the documented moderate findings remain. `/tmp/nerva-mobile-security-audit.json`.
- Native export attempted with `CI=1 EXPO_OFFLINE=1 EXPO_NO_TELEMETRY=1 expo export --platform ios --platform android --max-workers 1`, output only in `/tmp`. Android fails on missing `react-native/rn-get-polyfills` from ExpoMetroConfig. Isolated archived-base export reproduces the same missing module using unchanged baseline dependencies (`/tmp/nerva-mobile-security-baseline-export.log` vs `/tmp/nerva-mobile-security-export.log`). This is a pre-existing SDK compatibility blocker; this change does not claim native bundle/device success. iOS completion was not reached. No source shim or SDK change added to hide it.

## Remaining advisory and exposure limits

All11 remaining moderate reports derive from `xcode3.0.1 → uuid^7.0.3` and propagate through Expo config/CLI/splash-screen packages. Latest xcode still declares that range; uuid's patched line begins11.1.1. npm's proposed Expo46 or splash-screen55 downgrade is incompatible with the preserved SDK57 architecture and is not applied. Inspected xcode code usesv4(); the UUID advisory concerns bufferedv3/v5/v6, so an exploitable call was not demonstrated. Keep the finding recorded, not suppressed.

The other findings followed build/config/asset-processing and test tooling: xmldom through plist/Expo plist, Browserslist/browser mappings through Babel/Metro, brace expansion through minimatch, js-yaml3 through Istanbul's load-nyc-config, shell-quote through React DevTools. RN's DevTools initialization is gated by __DEV__. A production dependency flag does not prove inclusion/reachability in the installed mobile release. Release-bundle reachability remains unproven; no live models/network service exploit tests were run. The following compatibility repair restores export, but bundle generation alone does not establish advisory reachability.

Primary evidence: [Metro0.87.1 removes image-size](https://github.com/react/metro/releases/tag/v0.87.1), [xmldom0.8.15/0.9.12 patch](https://github.com/xmldom/xmldom/security/advisories/GHSA-965w-775f-mr7g), [Browserslist patch](https://github.com/browserslist/browserslist/security/advisories/GHSA-c83g-rgw3-j3cx), [UUID maintainer advisory](https://github.com/uuidjs/uuid/security/advisories/GHSA-w5hq-g745-h8pq), [shell-quote1.9 patch](https://github.com/advisories/GHSA-395f-4hp3-45gv), [js-yaml3.15.2](https://github.com/advisories/GHSA-2883-xcg3-v3hh). Registry manifests verified every selected version against parent ranges. Original audit and dependency paths: `/tmp/nerva-mobile-audit.json`, `/tmp/nerva-mobile-audit-paths.json`.

## Subsequent native export repair

The [bounded native compatibility adapter](superpowers/plans/2026-09-15-native-export.md) adds the official RN-aligned polyfill package and preserves Expo serializer defaults for other platforms. After integrating native appearance, root verification passes140 Jest tests, native TypeScript and offline Android/iOS Hermes export. The earlier failed export above records the security-only increment, not the final combined build. Existing private-featureflag fallback warnings and absence of device/native-compilation proof remain explicit.
