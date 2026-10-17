/* One namespace of UI copy, in both languages at once.

   Both dictionaries share one key type K, inferred from both objects, so a key present in only
   one language is a compile error (the Romanian dictionary lacks it, or the English one does).
   The i18n completeness test re-checks the same at runtime, plus placeholder parity. */
export type Dictionary<K extends string> = Record<K, string>;

export interface Namespace<K extends string> {
  ro: Dictionary<K>;
  en: Dictionary<K>;
}

export function defineMessages<K extends string>(messages: { ro: Record<K, string>; en: Record<K, string> }): Namespace<K> {
  return messages;
}
