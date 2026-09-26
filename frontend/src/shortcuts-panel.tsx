/* H209 — the Keyboard Shortcuts panel (mod+/): every HUD shortcut by category, searchable,
   rebindable by clicking its chord and pressing the new one, with per-binding and
   reset-all, and an "Also bound to" note when two actions share a chord. */
import React, { useEffect, useMemo, useState } from 'react';
import {
  CATEGORIES, type Overrides, bindings, chordFromEvent, conflictsFor, displayChord, rebind, resetBinding, searchBindings,
} from './shortcuts';

export function ShortcutsPanel({ overrides, onChange, onClose }: {
  overrides: Overrides; onChange: (next: Overrides) => void; onClose: () => void;
}) {
  const [query, setQuery] = useState('');
  const [recording, setRecording] = useState<string | null>(null);
  const list = useMemo(() => bindings(overrides), [overrides]);
  const shown = useMemo(() => searchBindings(list, query), [list, query]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (recording) {
        e.preventDefault();
        e.stopPropagation();
        if (e.key === 'Escape') { setRecording(null); return; }
        const chord = chordFromEvent(e);
        if (!chord) return;                       // a lone modifier: keep listening
        onChange(rebind(overrides, recording, chord));
        setRecording(null);
        return;
      }
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', h, true);
    return () => window.removeEventListener('keydown', h, true);
  }, [recording, overrides, onChange, onClose]);

  const custom = list.some((b) => b.custom);
  return (
    <div className="pal-scrim" onClick={onClose} style={{ alignItems: 'flex-start', paddingTop: '8vh' }}>
      <div role="dialog" aria-label="Keyboard shortcuts" onClick={(e) => e.stopPropagation()}
        style={{ width: 'min(640px,94vw)', maxHeight: '80vh', overflow: 'auto', background: 'var(--void-2)',
          border: '1px solid var(--panel-line)', borderRadius: 'var(--radius)', padding: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <span style={{ fontFamily: 'var(--font-mono)', letterSpacing: '.14em', color: 'var(--accent-light)' }}>SHORTCUTS</span>
          <input aria-label="Search shortcuts" placeholder="search" value={query} onChange={(e) => setQuery(e.target.value)}
            style={{ flex: 1, background: 'transparent', border: '1px solid var(--panel-line)', borderRadius: 6, padding: '4px 8px', color: 'var(--ink-1)' }}/>
          <button type="button" disabled={!custom} onClick={() => onChange({})}>Reset all</button>
          <button type="button" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        {CATEGORIES.map((category) => {
          const rows = shown.filter((b) => b.category === category);
          if (!rows.length) return null;
          return (
            <section key={category} aria-label={category} style={{ marginBottom: 12 }}>
              <h3 style={{ fontSize: 11, letterSpacing: '.12em', color: 'var(--ink-3)', margin: '6px 0' }}>{category.toUpperCase()}</h3>
              {rows.map((b) => {
                const also = conflictsFor(b.id, b.current, list);
                return (
                  <div key={b.id} data-action={b.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3px 0' }}>
                    <span style={{ flex: 1 }}>{b.label}
                      {also.length > 0 && <span role="note" style={{ marginLeft: 8, fontSize: 11, color: 'var(--warn, #e0a030)' }}>
                        Also bound to {also.map((a) => a.label).join(', ')}</span>}
                    </span>
                    <button type="button" aria-label={`Rebind ${b.label}`} onClick={() => setRecording(b.id)}
                      style={{ fontFamily: 'var(--font-mono)', minWidth: 90 }}>
                      {recording === b.id ? 'Press a key…' : displayChord(b.current)}
                    </button>
                    <button type="button" aria-label={`Reset ${b.label}`} disabled={!b.custom}
                      onClick={() => onChange(resetBinding(overrides, b.id))}>↺</button>
                  </div>
                );
              })}
            </section>
          );
        })}
        {!shown.length && <div style={{ color: 'var(--ink-3)' }}>No shortcut matches “{query}”.</div>}
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 8 }}>
          Approvals and decisions have no shortcut: they are always a click on the card.
        </div>
      </div>
    </div>
  );
}
