/* H309 — the model points at the HUD.

   The agent posts a `tip` (one target, one caption) or a `tour` (a title and up to eight
   steps) to the canvas with the `canvas_point` tool. This overlay reads the canvas, takes
   the newest tip or tour posted in the last ten minutes that this viewer has not closed,
   finds the element that carries its `data-anchor`, rings it and draws the caption beside
   it with an arrow; a tour pages with Back and Next. A target not on this screen is said
   plainly instead of pointing at nothing. A tip an untrusted turn wrote says so. */
import React, { useCallback, useEffect, useLayoutEffect, useState } from 'react';
import { apiGet } from './api/client';

/** The places a tip may point at; agents/core/canvas.py POINTER_ANCHORS holds the same list. */
export const POINTER_ANCHORS = [
  'mode.cockpit', 'mode.chat', 'mode.projects', 'mode.agents', 'mode.trust', 'mode.memory',
  'mode.autonomy', 'mode.build', 'mode.observe', 'mode.interop', 'mode.finance', 'mode.health',
  'mode.knowledge', 'mode.family', 'mode.comms', 'mode.admin',
  'composer', 'decisions', 'console',
] as const;
export const POINTER_TTL_SECONDS = 600;
export const POLL_MS = 5000;
const CLOSED_KEY = 'hud.pointer.closed';

export type PointerStep = { target: string; caption: string };
export type Pointer = { id: string; kind: 'tip' | 'tour'; title: string; steps: PointerStep[]; untrusted: boolean; agent: string };

const ANCHORS = new Set<string>(POINTER_ANCHORS);

/** A canvas element as a pointer, or null for anything else or anything malformed. */
export function readPointer(el: any): Pointer | null {
  if (!el || typeof el !== 'object' || typeof el.id !== 'string') return null;
  const p = el.payload && typeof el.payload === 'object' ? el.payload : {};
  const step = (s: any): PointerStep | null =>
    s && ANCHORS.has(s.target) && typeof s.caption === 'string' && s.caption ? { target: s.target, caption: s.caption } : null;
  let steps: PointerStep[] = [];
  if (el.type === 'tip') {
    const one = step(p);
    steps = one ? [one] : [];
  } else if (el.type === 'tour' && Array.isArray(p.steps)) {
    steps = p.steps.map(step);
    if (steps.some((s) => s === null)) return null;
  } else {
    return null;
  }
  if (!steps.length) return null;
  return { id: el.id, kind: el.type, title: typeof p.title === 'string' ? p.title : '', steps,
    untrusted: p.untrusted === true, agent: typeof el.agent === 'string' ? el.agent : 'agent' };
}

function readClosed(): string[] {
  try { const v = JSON.parse(sessionStorage.getItem(CLOSED_KEY) || '[]'); return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []; } catch { return []; }
}
function writeClosed(ids: string[]) {
  try { sessionStorage.setItem(CLOSED_KEY, JSON.stringify(ids.slice(-50))); } catch { /* the close lasts this page */ }
}

/** The newest live pointer the viewer has not closed (elements come newest first). */
export function currentPointer(elements: any[], closed: string[], now = Date.now() / 1000): Pointer | null {
  for (const el of Array.isArray(elements) ? elements : []) {
    const created = Number(el && el.created_at);
    if (!isFinite(created) || now - created > POINTER_TTL_SECONDS) continue;
    const ptr = readPointer(el);
    if (ptr && !closed.includes(ptr.id)) return ptr;
  }
  return null;
}

export function anchorRect(target: string, root: ParentNode = document): DOMRect | null {
  if (!ANCHORS.has(target)) return null;
  const el = root.querySelector(`[data-anchor="${target}"]`) as HTMLElement | null;
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width || r.height ? r : null;
}

export function PointerView({ pointer, onClose }: { pointer: Pointer; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const step = pointer.steps[Math.min(index, pointer.steps.length - 1)];
  const measure = useCallback(() => setRect(anchorRect(step.target)), [step.target]);
  useEffect(() => { setIndex(0); }, [pointer.id]);
  useLayoutEffect(() => {
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => { window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true); };
  }, [measure]);
  const last = index >= pointer.steps.length - 1;
  const tour = pointer.kind === 'tour';
  const place: React.CSSProperties = rect
    ? { position: 'fixed', left: Math.max(8, Math.min(rect.left, window.innerWidth - 328)), top: rect.bottom + 12 > window.innerHeight - 120 ? Math.max(8, rect.top - 132) : rect.bottom + 12 }
    : { position: 'fixed', left: '50%', bottom: 72, transform: 'translateX(-50%)' };
  return (
    <>
      {rect && <div data-testid="pointer-ring" aria-hidden="true" style={{ position: 'fixed', left: rect.left - 4, top: rect.top - 4,
        width: rect.width + 8, height: rect.height + 8, border: '2px solid var(--accent-light)', borderRadius: 8,
        boxShadow: '0 0 0 4px rgba(90,200,250,.18)', pointerEvents: 'none', zIndex: 60 }}/>}
      <div role="dialog" aria-label={tour ? `Tour: ${pointer.title || 'guide'}` : 'Tip'} data-pointer={pointer.id}
        style={{ ...place, zIndex: 61, width: 320, padding: '10px 12px', borderRadius: 10, background: 'var(--void-2)',
          border: '1px solid var(--accent-light)', fontSize: 13, boxShadow: '0 8px 24px rgba(0,0,0,.45)' }}>
        {rect && <span aria-hidden="true" style={{ position: 'absolute', left: 18, top: -7, width: 12, height: 12, transform: 'rotate(45deg)',
          background: 'var(--void-2)', borderLeft: '1px solid var(--accent-light)', borderTop: '1px solid var(--accent-light)' }}/>}
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 4 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.12em', color: 'var(--accent-light)' }}>
            {tour ? `${(pointer.title || 'TOUR').toUpperCase()} · ${index + 1}/${pointer.steps.length}` : 'TIP'}
          </span>
          <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>from {pointer.agent}</span>
          {pointer.untrusted && <span role="note" style={{ fontSize: 10, color: 'var(--warn, #e0a030)' }}>from an untrusted turn — check before acting</span>}
          <button type="button" aria-label="Close" onClick={onClose} style={{ marginLeft: 'auto' }}>✕</button>
        </div>
        <div>{step.caption}</div>
        {!rect && <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 4 }}>(not on this screen: {step.target})</div>}
        {tour && (
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
            <button type="button" disabled={index === 0} onClick={() => setIndex((i) => Math.max(0, i - 1))}>Back</button>
            {last
              ? <button type="button" onClick={onClose}>Done</button>
              : <button type="button" onClick={() => setIndex((i) => Math.min(pointer.steps.length - 1, i + 1))}>Next</button>}
          </div>
        )}
      </div>
    </>
  );
}

/** Polls the canvas and shows the newest live tip or tour. Off in demo mode. */
export function PointerOverlay({ enabled = true }: { enabled?: boolean }) {
  const [elements, setElements] = useState<any[]>([]);
  const [closed, setClosed] = useState<string[]>(readClosed);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    const load = () => apiGet<{ elements?: any[] }>('/api/canvas')
      .then((res) => { if (live) setElements(Array.isArray(res && res.elements) ? res.elements : []); })
      .catch(() => { /* the canvas is optional: no overlay */ });
    load();
    const timer = setInterval(load, POLL_MS);
    return () => { live = false; clearInterval(timer); };
  }, [enabled]);
  const pointer = enabled ? currentPointer(elements, closed) : null;
  if (!pointer) return null;
  const close = () => { const next = [...closed, pointer.id]; setClosed(next); writeClosed(next); };
  return <PointerView pointer={pointer} onClose={close} />;
}
