export type ModelCall = { provider: string; model: string };

const ID = /^[A-Za-z0-9][A-Za-z0-9._:/+\-]*$/;

/** One optional, per-turn receipt from the server; invalid receipts stay invisible. */
export function modelCalls(value: unknown): ModelCall[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 8) return [];
  const seen = new Set<string>();
  for (const row of value) {
    if (!row || typeof row !== 'object' || Object.keys(row).length !== 2 ||
        !Object.prototype.hasOwnProperty.call(row, 'provider') ||
        !Object.prototype.hasOwnProperty.call(row, 'model') ||
        typeof row.provider !== 'string' || typeof row.model !== 'string' ||
        row.provider.length > 64 || row.model.length > 120 ||
        !ID.test(row.provider) || !ID.test(row.model) ||
        row.provider.includes('//') || row.model.includes('//')) return [];
    const key = row.provider + '\0' + row.model;
    if (seen.has(key)) return [];
    seen.add(key);
  }
  return value.map(({ provider, model }) => ({ provider, model }));
}
