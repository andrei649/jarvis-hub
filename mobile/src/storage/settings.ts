import AsyncStorage from '@react-native-async-storage/async-storage';

/** Persisted connection settings for reaching a Jarvis hub. */
export type ServerConfig = {
  /** Base URL of the hub, e.g. http://192.168.1.20:8000 */
  baseUrl: string;
  /** Optional JARVIS_USER_TOKEN sent as the X-User-Token header. */
  token: string;
};

const KEY = 'jarvis.server.config.v1';

export const DEFAULT_CONFIG: ServerConfig = { baseUrl: '', token: '' };

export async function loadConfig(): Promise<ServerConfig> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (raw) return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
  } catch {
    // Corrupt/unavailable storage — fall back to defaults.
  }
  return DEFAULT_CONFIG;
}

export async function saveConfig(config: ServerConfig): Promise<void> {
  await AsyncStorage.setItem(KEY, JSON.stringify(config));
}
