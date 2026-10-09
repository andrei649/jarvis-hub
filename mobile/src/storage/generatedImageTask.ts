import AsyncStorage from '@react-native-async-storage/async-storage';

export type GeneratedImageRecord =
  | { kind: 'task'; taskId: number; prompt: string }
  | { kind: 'unknown'; prompt: string };

const PREFIX = 'jarvis.generated-image.';
let writes: Promise<void> = Promise.resolve();

function key(scope: string): string {
  if (!/^[a-z0-9-]{1,128}$/.test(scope)) throw new Error('Invalid image scope');
  return PREFIX + scope;
}

function validPrompt(prompt: unknown): prompt is string {
  return typeof prompt === 'string' && prompt.length <= 4000 && !!prompt.trim();
}

function validRecord(value: unknown): value is GeneratedImageRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  if (!validPrompt(row.prompt)) return false;
  if (row.kind === 'unknown') return Object.keys(row).sort().join(',') === 'kind,prompt';
  return row.kind === 'task' && Number.isSafeInteger(row.taskId) && (row.taskId as number) >= 1 &&
    Object.keys(row).sort().join(',') === 'kind,prompt,taskId';
}

export async function loadGeneratedImageTask(scope: string): Promise<GeneratedImageRecord | null> {
  try {
    const storageKey = key(scope);
    await writes.catch(() => {});
    const raw = await AsyncStorage.getItem(storageKey);
    // A 4,000-character prompt can expand to 24,000 JSON characters via escapes.
    if (!raw || raw.length > 25_000) return null;
    const parsed: unknown = JSON.parse(raw);
    return validRecord(parsed) ? parsed : null;
  } catch { return null; }
}

export function saveGeneratedImageTask(scope: string, value: GeneratedImageRecord | null): Promise<void> {
  const storageKey = key(scope);
  if (value !== null && !validRecord(value)) return Promise.reject(new Error('Invalid image task metadata'));
  const write = writes.catch(() => {}).then(() => value === null
    ? AsyncStorage.removeItem(storageKey)
    : AsyncStorage.setItem(storageKey, JSON.stringify(value)));
  writes = write;
  return write;
}
