import { describe, expect, it } from 'vitest';
import { MAP_CODE_LIMITS, decodeMapCode, encodeMapCode, type MapContent } from '../api/memory-map-code';

const content: MapContent = {
  nodes: [
    { kind: 'memory', label: 'Andrei', category: 'person', state: 'active', t: 0 },
    { kind: 'memory', label: 'Cluj', category: 'city', state: 'active', t: 2048 },
    { kind: 'skill', label: 'web-search', category: 'research', state: 'disabled', t: null },
  ],
  edges: [{ from: 0, to: 1, label: 'lives_in' }],
};

describe('map code (H206): bounded, versioned, content-only', () => {
  it('round-trips kind, label, category, state, edges and relative time', () => {
    const code = encodeMapCode(content);
    expect(code).toMatch(/^NML1\.[0-9a-f]{8}\.[A-Za-z0-9_-]+$/);
    expect(decodeMapCode(code)).toEqual(content);
  });

  it('carries labels but no property values, absolute timestamps or ids', () => {
    const code = encodeMapCode(content);
    const json = atob(code.split('.')[2].replace(/-/g, '+').replace(/_/g, '/'));
    expect(json).not.toMatch(/properties|secret|created|ingested/i);
    expect(json).not.toMatch(/\b1[5-9]\d{8}\b/);       // no epoch seconds
  });

  it('trims labels to 64 characters', () => {
    const long = { ...content, nodes: [{ ...content.nodes[0], label: 'x'.repeat(80) }] , edges: [] };
    expect(decodeMapCode(encodeMapCode(long)).nodes[0].label).toHaveLength(64);
  });

  it.each([
    ['empty', ''],
    ['not a code', 'hello world'],
    ['wrong prefix', 'XYZ1.00000000.e30'],
    ['future version', 'NML9.00000000.e30'],
    ['bad base64', 'NML1.00000000.@@@@'],
    ['checksum mismatch', encodeMapCode(content).replace(/^NML1\.[0-9a-f]{8}/, 'NML1.deadbeef')],
  ])('rejects %s with a message', (_name, code) => {
    expect(() => decodeMapCode(code)).toThrowError(/map code/i);
  });

  it('rejects an oversize code before decoding it', () => {
    expect(() => decodeMapCode('NML1.00000000.' + 'A'.repeat(MAP_CODE_LIMITS.chars + 1))).toThrowError(/too large/i);
  });

  it('refuses to encode more nodes or edges than the importer accepts', () => {
    const many = { nodes: Array.from({ length: MAP_CODE_LIMITS.nodes + 1 }, (_, i) => ({ ...content.nodes[0], label: 'n' + i })), edges: [] };
    expect(() => encodeMapCode(many)).toThrowError(/too many/i);
  });

  const forge = (payload: unknown) => {
    // Re-sign a hand-edited payload so only the schema check can refuse it.
    const json = JSON.stringify(payload);
    const bytes = new TextEncoder().encode(json);
    let sum = 0x811c9dc5;
    for (const b of bytes) { sum ^= b; sum = Math.imul(sum, 0x01000193) >>> 0; }
    const b64 = btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    return `NML1.${sum.toString(16).padStart(8, '0')}.${b64}`;
  };
  it.each([
    ['control character in a label', { v: 1, n: [[0, 'bad\u0007', 'x', 0, 1]], e: [] }],
    ['bidi override in a label', { v: 1, n: [[0, 'a‮b', 'x', 0, 1]], e: [] }],
    ['label over 64', { v: 1, n: [[0, 'y'.repeat(65), 'x', 0, 1]], e: [] }],
    ['unknown node kind', { v: 1, n: [[7, 'a', 'x', 0, 1]], e: [] }],
    ['unknown state', { v: 1, n: [[0, 'a', 'x', 9, 1]], e: [] }],
    ['time out of range', { v: 1, n: [[0, 'a', 'x', 0, 5000]], e: [] }],
    ['edge to a missing node', { v: 1, n: [[0, 'a', 'x', 0, 1]], e: [[0, 3, 'r']] }],
    ['not an object', [1, 2, 3]],
    ['wrong inner version', { v: 2, n: [], e: [] }],
  ])('rejects %s', (_name, payload) => {
    expect(() => decodeMapCode(forge(payload))).toThrowError(/map code/i);
  });

  it('accepts a well-formed forged payload (control for the cases above)', () => {
    expect(decodeMapCode(forge({ v: 1, n: [[0, 'a', 'x', 0, 1]], e: [] })).nodes[0].label).toBe('a');
  });
});

describe('mutation hardening: the importer and encoder gates', () => {
  const forge = (payload: unknown) => {
    const bytes = new TextEncoder().encode(JSON.stringify(payload));
    let sum = 0x811c9dc5;
    for (const b of bytes) { sum ^= b; sum = Math.imul(sum, 0x01000193) >>> 0; }
    const b64 = btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    return `NML1.${sum.toString(16).padStart(8, '0')}.${b64}`;
  };
  const node = [0, 'a', 'x', 0, 1];

  it('refuses more nodes or edges than the limits, even with a valid checksum', () => {
    expect(() => decodeMapCode(forge({ v: 1, n: Array.from({ length: MAP_CODE_LIMITS.nodes + 1 }, () => node), e: [] }))).toThrowError(/too many nodes/);
    expect(decodeMapCode(forge({ v: 1, n: Array.from({ length: MAP_CODE_LIMITS.nodes }, () => node), e: [] })).nodes).toHaveLength(MAP_CODE_LIMITS.nodes);
    expect(() => decodeMapCode(forge({ v: 1, n: [node], e: Array.from({ length: MAP_CODE_LIMITS.edges + 1 }, () => [0, 0, 'r']) }))).toThrowError(/too many edges/);
  });

  it('refuses an edge whose index is exactly the node count', () => {
    expect(() => decodeMapCode(forge({ v: 1, n: [node, node], e: [[0, 2, 'r']] }))).toThrowError(/missing node/);
    expect(() => decodeMapCode(forge({ v: 1, n: [node, node], e: [[2, 0, 'r']] }))).toThrowError(/missing node/);
    expect(decodeMapCode(forge({ v: 1, n: [node, node], e: [[1, 1, 'r']] })).edges).toHaveLength(1);
  });

  it('refuses a node row of the wrong length', () => {
    expect(() => decodeMapCode(forge({ v: 1, n: [[0, 'a', 'x', 0, 1, 'extra']], e: [] }))).toThrowError(/malformed/);
    expect(() => decodeMapCode(forge({ v: 1, n: [[0, 'a', 'x', 0]], e: [] }))).toThrowError(/malformed/);
  });

  it('refuses a node time above the span and a negative one', () => {
    expect(() => decodeMapCode(forge({ v: 1, n: [[0, 'a', 'x', 0, MAP_CODE_LIMITS.timeSteps + 1]], e: [] }))).toThrowError(/out of range/);
    expect(() => decodeMapCode(forge({ v: 1, n: [[0, 'a', 'x', 0, -1]], e: [] }))).toThrowError(/out of range/);
    expect(decodeMapCode(forge({ v: 1, n: [[0, 'a', 'x', 0, MAP_CODE_LIMITS.timeSteps]], e: [] })).nodes[0].t).toBe(MAP_CODE_LIMITS.timeSteps);
  });

  it('refuses a code with more than three parts and a payload without the inner version', () => {
    expect(() => decodeMapCode(encodeMapCode(content) + '.extra')).toThrowError(/map code/i);
    expect(() => decodeMapCode(forge({ n: [], e: [] }))).toThrowError(/version/);
  });

  it('replaces bidi isolate marks and controls in labels when encoding', () => {
    const dirty = { nodes: [{ ...content.nodes[0], label: 'a⁦b⁩c‮d' }], edges: [] };
    expect(decodeMapCode(encodeMapCode(dirty)).nodes[0].label).toBe('a b c d');
    expect(() => decodeMapCode(forge({ v: 1, n: [[0, 'a⁧b', 'x', 0, 1]], e: [] }))).toThrowError(/invalid/);
  });

  it('refuses to encode a map whose code would exceed the character limit, and accepts the largest that fits', () => {
    const big = {
      nodes: Array.from({ length: MAP_CODE_LIMITS.nodes }, (_, i) => ({ kind: 'memory' as const, label: ('n' + i).padEnd(64, 'x'), category: 'c'.repeat(40), state: 'active' as const, t: 1 })),
      edges: Array.from({ length: MAP_CODE_LIMITS.edges }, (_, i) => ({ from: 0, to: 1, label: ('e' + i).padEnd(64, 'y') })),
    };
    expect(() => encodeMapCode(big)).toThrowError(/Too large/);
    const edges = { ...big, edges: big.edges.slice(0, 1) };
    expect(encodeMapCode(edges).length).toBeLessThanOrEqual(MAP_CODE_LIMITS.chars);
    expect(() => encodeMapCode({ ...content, edges: Array.from({ length: MAP_CODE_LIMITS.edges + 1 }, () => content.edges[0]) })).toThrowError(/Too many edges/);
  });
});
