/* H579 — `@file:path` completion in the composer.

   The hub expands `@file:path` and `@file:path#L10-40` in what the owner sends (the file's
   text is attached under "--- Attached Context ---"). While the last word being typed starts a
   reference (`@`, `@fi`), this offers the reference types `GET /api/context-refs` names; once it
   is an `@file:` reference, the in-scope paths that complete it (a path with a space comes
   quoted). They are listed above the input; Tab (or a click) takes the first / the chosen one.
   A list is only shown for the text it was fetched for. */
import React, { useEffect, useState } from 'react';
import { apiGet } from './api/client';

export const CONTEXT_REFS_PATH = '/api/context-refs';
const PREFIX = '@file:';

export type ContextRef = { ref: string; kind: 'file' | 'dir' | 'type' };

/** The `@file:` reference being typed at the end of `value` (what follows the prefix), or null.
    A quoted path (`@file:"my no`) runs to its closing quote, spaces and all. */
export function typedRef(value: string): string | null {
  const text = String(value || '');
  const at = text.lastIndexOf(PREFIX);
  if (at < 0 || (at > 0 && !/\s/.test(text[at - 1]))) return null;
  const rest = text.slice(at + PREFIX.length);
  if (rest.startsWith('"')) return rest.includes('"', 1) || rest.includes('#') ? null : rest.slice(1);
  return /[\s#]/.test(rest) ? null : rest;
}

/** The reference type being typed at the end of `value` (`@`, `@fi`), or null. */
export function typedType(value: string): string | null {
  const last = String(value || '').split(/\s/).pop() || '';
  return /^@\w*$/.test(last) ? last : null;
}

/** `value` with the reference being typed replaced by `ref`: a type or a directory keeps
    completing (a quoted directory is left open for it), anything else ends with a space. */
export function acceptRef(value: string, ref: string): string {
  const text = String(value || '');
  const word = typedRef(text) === null ? typedType(text) : null;
  const cut = word !== null ? text.length - word.length : text.lastIndexOf(PREFIX);
  if (cut < 0) return value;
  const open = ref.endsWith('/"') ? ref.slice(0, -1) : ref;
  return text.slice(0, cut) + open + (/[/:]$/.test(open) ? '' : ' ');
}

export function useContextRefs(value: string): ContextRef[] {
  const prefix = typedRef(value);
  const word = prefix === null ? typedType(value) : null;
  const key = prefix !== null ? `path:${prefix}` : word !== null ? `type:${word}` : null;
  const [found, setFound] = useState<{ key: string | null; items: ContextRef[] }>({ key: null, items: [] });
  useEffect(() => {
    if (key === null) return;
    let live = true;
    const timer = setTimeout(() => {
      apiGet<{ ok: boolean; types?: string[]; items?: ContextRef[] }>(`${CONTEXT_REFS_PATH}?prefix=${encodeURIComponent(prefix ?? '')}`)
        .then((res) => {
          if (!live) return;
          const ok = !!(res && res.ok);
          const items: ContextRef[] = word !== null
            ? (ok && Array.isArray(res.types) ? res.types : [])
              .map((type) => ({ ref: `@${type}:`, kind: 'type' as const })).filter((item) => item.ref.startsWith(word))
            : ok && Array.isArray(res.items) ? res.items : [];
          setFound({ key, items });
        })
        .catch(() => { if (live) setFound({ key, items: [] }); });
    }, 120);
    return () => { live = false; clearTimeout(timer); };
  }, [key, prefix, word]);
  return key !== null && found.key === key ? found.items : [];
}

export function ContextRefHints({ items, onPick }: { items: ContextRef[]; onPick: (ref: string) => void }) {
  if (!items.length) return null;
  return (
    <div role="listbox" aria-label="file references"
      style={{ position: 'absolute', bottom: '100%', left: 0, marginBottom: 6, zIndex: 25, maxHeight: 180, overflowY: 'auto',
        minWidth: 240, padding: '4px 0', borderRadius: 8, background: 'rgba(10,18,24,.98)', border: '1px solid var(--panel-line)',
        fontFamily: 'var(--font-mono)', fontSize: 11 }}>
      {items.slice(0, 12).map((item, i) => (
        <div key={item.ref} role="option" aria-selected={i === 0} onMouseDown={(e) => { e.preventDefault(); onPick(item.ref); }}
          style={{ padding: '3px 10px', cursor: 'pointer', color: i === 0 ? 'var(--accent-light)' : 'var(--ink-2)' }}>
          {item.ref}{i === 0 ? '  ⇥' : ''}
        </div>
      ))}
    </div>
  );
}
