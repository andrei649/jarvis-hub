import AsyncStorage from '@react-native-async-storage/async-storage';
import { normalizeAppearance, type Appearance } from '../appearance';

/** Credentials remain only in the existing connection settings record. */
export type ServerConfig = { baseUrl: string; token: string; adminToken: string };
export type ServerRecord = { version: 2; config: ServerConfig; appearance: Appearance | null };
const KEY = 'jarvis.server.config.v1';
export const DEFAULT_CONFIG: ServerConfig = { baseUrl: '', token: '', adminToken: '' };
let writes: Promise<void> = Promise.resolve();

export async function loadServerRecord(): Promise<ServerRecord> {
  try {
    await writes.catch(() => {});
    const raw = await AsyncStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    const source = parsed?.version === 2 ? parsed.config : parsed;
    const config = { ...DEFAULT_CONFIG };
    if (source && typeof source === 'object' && !Array.isArray(source)) {
      for (const key of Object.keys(config) as (keyof ServerConfig)[]) {
        if (typeof source[key] === 'string') config[key] = source[key];
      }
    }
    // Only fixed enum fields enter the cache; no server metadata or credentials.
    const appearance = parsed?.version === 2 && parsed.appearance && typeof parsed.appearance === 'object' && !Array.isArray(parsed.appearance)
      ? normalizeAppearance(parsed.appearance) : null;
    return { version: 2, config, appearance };
  } catch {
    return { version: 2, config: { ...DEFAULT_CONFIG }, appearance: null };
  }
}

/** Read the owner's latest record when a serialized write starts. No cross-key atomicity claim. */
export function saveServerRecord(latest: () => ServerRecord): Promise<void> {
  const write = writes.catch(() => {}).then(() => AsyncStorage.setItem(KEY, JSON.stringify(latest())));
  writes = write;
  return write;
}
