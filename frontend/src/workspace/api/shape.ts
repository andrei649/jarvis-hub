/* Response-shape tolerance for the routes whose contract (spec §7) names only the status
   ("→ 201", "→ item"): the object may arrive bare or wrapped in a one-key envelope such as
   `{report: {...}}`. Accepting both keeps a screen working whichever way the router writes
   it, without guessing at fields. */

/** The object under the first present key of *keys*, else the payload itself. */
export function unwrapOne<T>(data: unknown, keys: readonly string[]): T {
  if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>;
    for (const key of keys) {
      const value = record[key];
      if (value && typeof value === 'object' && !Array.isArray(value)) return value as T;
    }
  }
  return data as T;
}

/** The array under the first present key of *keys*; a bare array passes through. */
export function unwrapList<T>(data: unknown, keys: readonly string[]): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>;
    for (const key of keys) {
      if (Array.isArray(record[key])) return record[key] as T[];
    }
  }
  return [];
}
