/* H579 — `@file:path` completion in the composer.

   The hub expands `@file:path` and `@file:path#L10-40` in what the owner sends (the file's
   text is attached under "--- Attached Context ---"). While the last word being typed is an
   `@file:` reference, this asks `GET /api/context-refs` for the in-scope paths that complete
   it and lists them above the input; Tab (or a click) takes the first / the chosen one. */
import React, { useEffect, useState } from 'react';
import { apiGet } from './api/client';

export const CONTEXT_REFS_PATH = '/api/context-refs';
const PREFIX = '@file:';

export type ContextRef = { ref: string; kind: 'file' | 'dir' };

/** The `@file:` reference being typed at the end of `value` (what follows the prefix), or null. */
export function typedRef(value: string): string | null {
  const last = String(value || '').split(/\s/).pop() || '';
  if (!last.startsWith(PREFIX) || last.includes('#')) return null;
  return last.slice(PREFIX.length);
}

/** `value` with its trailing reference replaced by `ref` (a directory keeps completing). */
export function acceptRef(value: string, ref: string): string {
  const cut = String(value || '').lastIndexOf(PREFIX);
  if (cut < 0) return value;
  return value.slice(0, cut) + ref + (ref.endsWith('/') ? '' : ' ');
}

export function useContextRefs(value: string): ContextRef[] {
  const prefix = typedRef(value);
  const [items, setItems] = useState<ContextRef[]>([]);
  useEffect(() => {
    if (prefix === null) { setItems([]); return; }
    let live = true;
    const timer = setTimeout(() => {
      apiGet<{ ok: boolean; items?: ContextRef[] }>(`${CONTEXT_REFS_PATH}?prefix=${encodeURIComponent(prefix)}`)
        .then((res) => { if (live) setItems(res && res.ok && Array.isArray(res.items) ? res.items : []); })
        .catch(() => { if (live) setItems([]); });
    }, 120);
    return () => { live = false; clearTimeout(timer); };
  }, [prefix]);
  return prefix === null ? [] : items;
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
