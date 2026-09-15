# Expo shared-object dependency resolution

Goal: resolve inherited AudioPlayer event types from the locked Expo SDK without changing audio behavior or suppressing TypeScript errors.
Base: d0ce1a3b376f51f96c658ce496c7889ea096aa28. Generated: 2026-09-15.

Baseline: clean lock installation exposes TS2339 for AudioPlayer.addListener and TS7006 for its callback in src/audio/tts.ts. The installed expo-audio declaration imports SharedObject from expo-modules-core. The sole locked core 57.0.16 is nested under expo/node_modules and cannot resolve from sibling expo-audio. That SDK version already belongs to the existing Expo dependency tree.

Plan: declare the same exact locked core version directly in this mobile package, regenerate only its lock layout and inspect all version changes. Install the resulting lock in isolation; compile the actual mobile project and run the existing Jest suite. The two baseline ListEmptyComponent null incompatibilities were explicitly transferred from the native appearance work to this compatibility unit: use undefined for the absent optional component, preserving rendered behavior. Require the complete mobile TypeScript check to pass after both repairs. No casts, API replacements, new SDK versions or unrelated dependencies.

Rollback: revert the package/lock and this explanation as one unit. No product data or authority changes. Native device playback is not claimed by TypeScript/Jest verification.

Lock evidence: npm needed registry metadata after its offline cache miss; it moved the existing core entry from expo/node_modules to the top-level without changing any package version, integrity, or package count. Clean npm ci and 137 Jest tests pass. The initial four compiler errors reduced to exactly the two optional-component errors after dependency resolution alone.

The complete mobile TypeScript check now passes after the two optional-component replacements. Root owns both exact token edits; the parallel appearance feature retains its separate style/provider scope.
