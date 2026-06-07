import AsyncStorage from '@react-native-async-storage/async-storage';

/** Small user preferences, separate from connection config. */
export type Prefs = {
  /** Selected agent id for new messages (default "jarvis"). */
  agent: string;
};

const KEY = 'jarvis.prefs.v1';

export const DEFAULT_PREFS: Prefs = { agent: 'jarvis' };

export async function loadPrefs(): Promise<Prefs> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (raw) return { ...DEFAULT_PREFS, ...JSON.parse(raw) };
  } catch {
    // ignore
  }
  return DEFAULT_PREFS;
}

export async function savePrefs(prefs: Prefs): Promise<void> {
  try {
    await AsyncStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // ignore
  }
}
