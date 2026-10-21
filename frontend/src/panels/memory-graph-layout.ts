/* H206 — pure geometry for the memory graph explorer (no React, no DOM).
   A deterministic radial layout: the same nodes always land on the same points. */

export const VIEW = { w: 640, h: 380 } as const;
export const ZOOM = { min: 0.2, max: 5 } as const;

export type NodeKind = 'memory' | 'skill';
export type GNode = {
  id: string; kind: NodeKind; label: string; type: string;
  ts: number | null;          // seconds since epoch the store first saw it (live maps)
  rel: number | null;         // 0..4095 position on an imported map's own time span
  state: 'active' | 'disabled'; essential?: boolean;
};
export type GEdge = { id: string; from: string; to: string; label: string; fact: boolean };
export type Camera = { x: number; y: number; k: number };
export type Point = { x: number; y: number };

const RING_FIRST = 62;
const RING_STEP = 50;
const ringCapacity = (ring: number) => 6 + 6 * ring;

/** Rings from the core outwards: oldest first (nodes with no known time last), skills
 *  in their own outer rings grouped by category. With a focus, that node sits in the
 *  centre and its neighbours take the first ring. */
export function layout(nodes: GNode[], edges: GEdge[], focusId: string | null): Map<string, Point> {
  const out = new Map<string, Point>();
  const byLabel = (a: GNode, b: GNode) => a.label.localeCompare(b.label) || a.id.localeCompare(b.id);
  const age = (a: GNode, b: GNode) => (a.ts === null && a.rel === null ? 1 : 0) - (b.ts === null && b.rel === null ? 1 : 0)
    || (a.ts ?? a.rel ?? 0) - (b.ts ?? b.rel ?? 0) || byLabel(a, b);
  const memory = nodes.filter(n => n.kind === 'memory').sort(age);
  const skills = nodes.filter(n => n.kind === 'skill').sort((a, b) => a.type.localeCompare(b.type) || byLabel(a, b));
  let ring = 0;
  const place = (group: GNode[]) => {
    let i = 0;
    while (i < group.length) {
      const count = Math.min(ringCapacity(ring), group.length - i);
      const radius = RING_FIRST + RING_STEP * ring;
      const turn = ring * 0.6 - Math.PI / 2;
      for (let j = 0; j < count; j++) {
        const angle = turn + (2 * Math.PI * j) / count;
        out.set(group[i + j].id, { x: Math.round(radius * Math.cos(angle) * 10) / 10, y: Math.round(radius * Math.sin(angle) * 10) / 10 });
      }
      i += count; ring += 1;
    }
  };
  const focus = focusId ? memory.find(n => n.id === focusId) || skills.find(n => n.id === focusId) : undefined;
  let rest = memory;
  if (focus) {
    out.set(focus.id, { x: 0, y: 0 });
    const near = new Set<string>();
    for (const e of edges) { if (e.from === focus.id) near.add(e.to); else if (e.to === focus.id) near.add(e.from); }
    const ring1 = memory.filter(n => n.id !== focus.id && near.has(n.id));
    place(ring1);
    rest = memory.filter(n => n.id !== focus.id && !near.has(n.id));
  }
  place(rest);
  place(skills.filter(n => !out.has(n.id)));
  return out;
}

export function neighbourhood(edges: GEdge[], id: string): Set<string> {
  const near = new Set<string>([id]);
  for (const e of edges) { if (e.from === id) near.add(e.to); else if (e.to === id) near.add(e.from); }
  return near;
}

const clampK = (k: number) => Math.min(ZOOM.max, Math.max(ZOOM.min, k));
export const zoomBy = (cam: Camera, factor: number): Camera => ({ ...cam, k: clampK(cam.k * factor) });

/** The camera that shows every point, with a margin. */
export function fit(points: Iterable<Point>, margin = 48): Camera {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of points) { minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y); }
  if (!Number.isFinite(minX)) return { x: 0, y: 0, k: 1 };
  const k = clampK(Math.min(VIEW.w / (maxX - minX + 2 * margin), VIEW.h / (maxY - minY + 2 * margin)));
  return { x: (minX + maxX) / 2, y: (minY + maxY) / 2, k: Math.round(k * 1000) / 1000 };
}

export function viewBox(cam: Camera): string {
  const w = VIEW.w / cam.k, h = VIEW.h / cam.k;
  const r = (n: number) => Math.round(n * 100) / 100;
  return `${r(cam.x - w / 2)} ${r(cam.y - h / 2)} ${r(w)} ${r(h)}`;
}

/** Stable colour per entity type; unknown / untyped nodes get the neutral ink. */
export function typeColour(type: string): string {
  if (!type || type === 'unknown') return 'var(--ink-2)';
  let h = 0;
  for (const ch of type.toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `hsl(${h % 360} 62% 62%)`;
}
