export const records = new Map<string, string>();
export const storage = {
  getItem: async (key: string) => records.get(key) ?? null,
  setItem: async (key: string, value: string) => { records.set(key, value); },
  removeItem: async (key: string) => { records.delete(key); },
};
export default storage;
