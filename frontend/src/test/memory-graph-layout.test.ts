import { describe, expect, it } from 'vitest';
import { ZOOM, fit, layout, typeColour, zoomBy, type GEdge, type GNode } from '../panels/memory-graph-layout';

const mem = (id: string, ts: number | null = null): GNode => ({ id, kind: 'memory', label: id, type: 'unknown', ts, rel: null, state: 'active' });
const radius = (p: { x: number; y: number }) => Math.round(Math.hypot(p.x, p.y));

describe('memory graph layout (H206)', () => {
  it('clamps the zoom at both ends', () => {
    const cam = { x: 0, y: 0, k: 1 };
    expect(zoomBy(cam, 1e6).k).toBe(ZOOM.max);
    expect(zoomBy(cam, 1e-6).k).toBe(ZOOM.min);
  });

  it('fills ring 0 with 6 nodes and ring 1 with 12, then starts ring 2', () => {
    const nodes = Array.from({ length: 19 }, (_, i) => mem('n' + String(i).padStart(2, '0'), i));
    const pos = layout(nodes, [], null);
    const rings = nodes.map(n => radius(pos.get(n.id)!));
    expect(rings.filter(r => r === 62)).toHaveLength(6);
    expect(rings.filter(r => r === 112)).toHaveLength(12);
    expect(rings.filter(r => r === 162)).toHaveLength(1);
  });

  it('puts the neighbours of a focus on the first ring whichever way the edge points', () => {
    const nodes = ['a', 'b', 'c', 'd'].map(id => mem(id));
    const edges: GEdge[] = [
      { id: 'e1', from: 'b', to: 'a', label: 'r', fact: false },   // into the focus
      { id: 'e2', from: 'a', to: 'c', label: 'r', fact: false },   // out of the focus
    ];
    const pos = layout(nodes, edges, 'a');
    expect(pos.get('a')).toEqual({ x: 0, y: 0 });
    expect(radius(pos.get('b')!)).toBe(62);
    expect(radius(pos.get('c')!)).toBe(62);
    expect(radius(pos.get('d')!)).toBeGreaterThan(62);
  });

  it('fits an empty set to the origin at scale one, never NaN', () => {
    expect(fit([])).toEqual({ x: 0, y: 0, k: 1 });
  });

  it('gives untyped entities the neutral ink and typed ones a stable hue', () => {
    expect(typeColour('')).toBe('var(--ink-2)');
    expect(typeColour('unknown')).toBe('var(--ink-2)');
    expect(typeColour('person')).toBe(typeColour('Person'));
    expect(typeColour('person')).toMatch(/^hsl\(/);
  });
});
