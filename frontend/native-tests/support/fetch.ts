export const fetch = (...args: Parameters<typeof globalThis.fetch>) => globalThis.fetch(...args);
