/* H309 — the model points at the HUD.

   The agent posts a `tip` (one target, one caption) or a `tour` (a title and up to eight
   steps) to the canvas with the `canvas_point` tool. This overlay polls the live tips and
   tours (GET /api/canvas/pointers, aged by the hub's clock), takes the newest one posted in
   the last ten minutes that this viewer has not closed, finds the element that carries its
   `data-anchor`, rings it and draws the caption beside it with an arrow; a tour pages with
   Back and Next. A target not on this screen, or hidden under another layer, is said
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
  if (!r.width && !r.height) return null;
  // Under another layer (the Ambient screen, the Dossier drawer) it is not on this screen;
  // the pointer's own bubble does not count.
  if (typeof document.elementFromPoint === 'function') {
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (hit && !el.contains(hit) && !hit.closest('[data-pointer]')) return null;
  }
  return r;
}

const sameRect = (a: DOMRect | null, b: DOMRect | null) =>
  a === b || (!!a && !!b && a.left === b.left && a.top === b.top && a.width === b.width && a.height === b.height);

const BUBBLE_WIDTH = 320;

export function PointerView({ pointer, onClose }: { pointer: Pointer; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const step = pointer.steps[Math.min(index, pointer.steps.length - 1)];
  const measure = useCallback(() => {
    const next = anchorRect(step.target);
    setRect((prev) => (sameRect(prev, next) ? prev : next));
  }, [step.target]);
  useLayoutEffect(() => {
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    // Bolt Optimization: Frame-throttle DOM mutation measurements via requestAnimationFrame.
    // MutationObserver firing on document.body for every DOM change triggers anchorRect()
    // and elementFromPoint() synchronously, causing forced layout recalculations (layout thrashing).
    let rafId = 0;
    const scheduleMeasure = () => {
      if (!rafId) {
        rafId = requestAnimationFrame(() => {
          rafId = 0;
          measure();
        });
      }
    };
    // A mode switch or an overlay mounts and unmounts anchors without a resize or a scroll.
    const watch = typeof MutationObserver === 'function' ? new MutationObserver(scheduleMeasure) : null;
    watch?.observe(document.body, { childList: true, subtree: true });
    return () => {
      if (rafId) cancelAnimationFrame(rafId);
      window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true); watch?.disconnect();
    };
  }, [measure]);
  const last = index >= pointer.steps.length - 1;
  const tour = pointer.kind === 'tour';
  const left = rect ? Math.max(8, Math.min(rect.left, window.innerWidth - BUBBLE_WIDTH - 8)) : 0;
  // Near the window's bottom the bubble sits above the element, placed by its lower edge;
  // an element too tall to leave room above gets the bubble over its own lower part.
  const low = !!rect && rect.bottom + 12 > window.innerHeight - 120;
  const above = low && rect.top > 160;
  const place: React.CSSProperties = rect
    ? { position: 'fixed', left,
      ...(above ? { bottom: window.innerHeight - rect.top + 12 } : { top: Math.min(rect.bottom + 12, window.innerHeight - 120) }) }
    : { position: 'fixed', left: '50%', bottom: 72, transform: 'translateX(-50%)' };
  const arrow: React.CSSProperties = rect
    ? { left: Math.max(12, Math.min(rect.left + rect.width / 2 - left - 6, BUBBLE_WIDTH - 24)),
      ...(above
        ? { bottom: -7, borderRight: '1px solid var(--accent-light)', borderBottom: '1px solid var(--accent-light)' }
        : { top: -7, borderLeft: '1px solid var(--accent-light)', borderTop: '1px solid var(--accent-light)' }) }
    : {};
  return (
    <>
      {rect && <div data-testid="pointer-ring" aria-hidden="true" style={{ position: 'fixed', left: rect.left - 4, top: rect.top - 4,
        width: rect.width + 8, height: rect.height + 8, border: '2px solid var(--accent-light)', borderRadius: 8,
        boxShadow: '0 0 0 4px rgba(90,200,250,.18)', pointerEvents: 'none', zIndex: 60 }}/>}
      <div role="dialog" aria-label={tour ? `Tour: ${pointer.title || 'guide'}` : 'Tip'} data-pointer={pointer.id}
        style={{ ...place, zIndex: 61, width: BUBBLE_WIDTH, padding: '10px 12px', borderRadius: 10, background: 'var(--void-2)',
          border: '1px solid var(--accent-light)', fontSize: 13, boxShadow: '0 8px 24px rgba(0,0,0,.45)' }}>
        {rect && <span data-testid="pointer-arrow" aria-hidden="true" style={{ position: 'absolute', ...arrow, width: 12, height: 12,
          transform: 'rotate(45deg)', background: 'var(--void-2)' }}/>}
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 4 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.12em', color: 'var(--accent-light)' }}>
            {tour ? `${(pointer.title || 'TOUR').toUpperCase()} · ${index + 1}/${pointer.steps.length}` : 'TIP'}
          </span>
          <span style={{ fontSize: 10, color: 'var(--ink-2)' }}>from {pointer.agent}</span>
          {pointer.untrusted && <span role="note" style={{ fontSize: 10, color: 'var(--warn, #e0a030)' }}>from an untrusted turn — check before acting</span>}
          <button type="button" aria-label="Close" onClick={onClose} style={{ marginLeft: 'auto' }}>✕</button>
        </div>
        <div>{step.caption}</div>
        {!rect && <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>(not on this screen: {step.target})</div>}
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

/** Polls the live tips and tours (not the whole canvas) and shows the newest. Off in demo mode. */
export function PointerOverlay({ enabled = true }: { enabled?: boolean }) {
  const [feed, setFeed] = useState<{ elements: any[]; now?: number }>({ elements: [] });
  const [closed, setClosed] = useState<string[]>(readClosed);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    const load = () => apiGet<{ elements?: any[]; now?: number }>('/api/canvas/pointers')
      .then((res) => {
        const now = Number(res && res.now);
        if (live) setFeed({ elements: Array.isArray(res && res.elements) ? res.elements : [], now: now > 0 ? now : undefined });
      })
      .catch(() => { /* the canvas is optional: no overlay */ });
    load();
    const timer = setInterval(load, POLL_MS);
    return () => { live = false; clearInterval(timer); };
  }, [enabled]);
  // Aged by the hub's clock when it sent one: a device whose clock is off still shows a tip.
  const pointer = enabled ? currentPointer(feed.elements, closed, feed.now) : null;
  if (!pointer) return null;
  const close = () => { const next = [...closed, pointer.id]; setClosed(next); writeClosed(next); };
  // Keyed by the pointer: a new tour mounts at its first step, never a frame of the old one's.
  return <PointerView key={pointer.id} pointer={pointer} onClose={close} />;
}
