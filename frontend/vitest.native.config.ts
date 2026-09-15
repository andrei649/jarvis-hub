import { defineConfig } from 'vitest/config';
import { transformWithOxc } from 'vite';
import { fileURLToPath } from 'node:url';
const local = (path: string) => fileURLToPath(new URL(path, import.meta.url));
export default defineConfig({
  // Test transpilation is independent of Expo/Metro. Native tsc runs separately.
  oxc: { exclude: /\/mobile\// },
  plugins: [{ name: 'native-react-tests', enforce: 'pre', transform(code, id) {
    if (id.includes('/mobile/') && /\.[jt]sx?$/.test(id)) return transformWithOxc(code, id, { tsconfig: false });
  } }],
  resolve: { alias: {
    react: local('./node_modules/react'),
    'react-native': local('./native-tests/support/native.tsx'),
    '@react-native-async-storage/async-storage': local('./native-tests/support/storage.ts'),
    'expo-status-bar': local('./native-tests/support/expo.tsx'),
    'expo-file-system/legacy': local('./native-tests/support/files.ts'),
    'expo-audio': local('./native-tests/support/audio.ts'),
  } },
  test: { name: 'native-appearance', environment: 'jsdom', globals: true, include: ['native-tests/*.test.tsx'], maxWorkers: 1 },
});
