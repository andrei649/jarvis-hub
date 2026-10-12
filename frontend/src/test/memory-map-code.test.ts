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
