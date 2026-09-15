# Native export compatibility

## Plan recorded before implementation

Base: `10be2d1e`. Installed Expo 57.0.20 requires `react-native/rn-get-polyfills` in its Metro serializer, but RN 0.87.1 removed that entry. The [official RN 0.87 release notes](https://reactnative.dev/blog/2026/08/11/react-native-0.87) direct consumers to `@react-native/js-polyfills`. Installed Expo's `bundledNativeModules.json` targets RN 0.86.3; this repair does not establish full support for the existing mixed stack.

Add exact `@react-native/js-polyfills` 0.87.1 as a mobile build dependency. Start the project Metro config with Expo's default config, replacing only `serializer.getPolyfills` for Android and iOS. Preserve empty-platform behavior and delegate web to Expo. Do not patch dependencies, copy private shims, remove native error handling, or migrate SDK versions. Report any deeper incompatibility before expanding scope.

Write failing adapter regressions first. Then verify the lock delta, clean install, full mobile TypeScript and Jest checks, offline Expo config, and Android/iOS exports into temporary directories. Do not modify global configuration, security policy, or delivery status.

## Implementation and dependency accounting

`mobile/metro.config.js` uses the official replacement for both native platforms. All other Expo config fields retain their original values. Three regressions exercise Android, iOS, and preservation of resolver/transformer/serializer defaults plus web and empty-platform handling.

The manifest adds one exact dev dependency. The lock adds its root declaration and one package entry, with no dependencies of its own. Every previously locked package version and integrity remains unchanged, including Expo Metro 0.84.5 and the RN CLI's separate Metro 0.87.1 tree. No SDK versions, overrides, or install-script permissions changed.

## Verification and limits

The immutable baseline failure is recorded in `/tmp/nerva-mobile-security-baseline-export.log`. The adapter regressions initially failed three times because the project config did not exist (`/tmp/nerva-native-export-red.log`). Final results are recorded below after verification.

The export emits existing warnings that Expo imports RN's private `ReactNativeFeatureFlags` path outside its declared exports; Metro falls back to file resolution. This narrow compatibility adapter does not resolve that upstream API mismatch. Successful exports prove offline Hermes bundle generation, not simulator/device execution, native compilation, or complete Expo/RN compatibility. No telemetry, login, deployment, or live provider calls are needed.

Final verification (2026-09-15):

- `npm ci --no-audit --no-fund`: 1,248 packages installed; existing two install-script permission warnings retained (`/tmp/nerva-native-export-final-ci.log`).
- `node node_modules/typescript/bin/tsc --noEmit`: passed (`/tmp/nerva-native-export-final-tsc.log`).
- `node node_modules/jest/bin/jest.js --runInBand`: 33 suites, 140 tests passed, three new tests (`/tmp/nerva-native-export-final-jest.log`).
- `CI=1 EXPO_OFFLINE=1 EXPO_NO_TELEMETRY=1 node node_modules/expo/bin/cli config --type public`: passed (`/tmp/nerva-native-export-final-config.log`).
- Same environment, `expo export --platform ios --platform android --max-workers 1 --output-dir /tmp/nerva-native-export-final`: passed, one 1.8 MB Hermes bundle per platform (`/tmp/nerva-native-export-final-export.log`).
- Actual installed config returns existing `console.js` and `error-guard.js` paths for both native platforms. Exact lock comparison confirms one added package and no changed existing non-root package records.
- Fresh `npm audit --json`: 11 moderate, zero high/critical, unchanged from the security baseline (`/tmp/nerva-native-export-final-audit.json`; audit exits 1 for the documented UUID-chain remainder).
- `git diff --check`: passed.
