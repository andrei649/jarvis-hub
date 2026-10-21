/* H206 — the shareable "map code" of the memory graph explorer.

   Serialises the MAP CONTENT the canvas draws and nothing else: per node its kind
   (memory | skill), a label (<= 64 chars), a category (the entity type / skill
   category), a state and a position on the time axis RELATIVE to the map's own span
   (0..4095), plus the edges between nodes. No property values, ids or absolute
   timestamps travel in it. A code is versioned (`NML1`), checksummed and bounded, and
   the importer validates it strictly. It is data only: importing a code draws a
   read-only map and never fetches, writes or executes anything.

   Format: `NML1.<fnv1a-32 of the JSON, 8 hex>.<base64url of the UTF-8 JSON>` where the
   JSON is `{v:1, n:[[kind, label, category, state, t]], e:[[from, to, label]]}`. */

export type MapNodeKind = 'memory' | 'skill';
export type MapNodeState = 'active' | 'disabled';
export type MapContentNode = { kind: MapNodeKind; label: string; category: string; state: MapNodeState; t: number | null };
export type MapContentEdge = { from: number; to: number; label: string };
export type MapContent = { nodes: MapContentNode[]; edges: MapContentEdge[] };

export const MAP_CODE_LIMITS = { nodes: 500, edges: 1500, chars: 96_000, label: 64, category: 40, timeSteps: 4095 } as const;
const PREFIX = 'NML1';
const KINDS: MapNodeKind[] = ['memory', 'skill'];
const STATES: MapNodeState[] = ['active', 'disabled'];
// C0/C1 controls, DEL, line/paragraph separators and the bidi override/isolate marks.
const UNSAFE_RANGES: [number, number][] = [[0, 31], [127, 159], [0x2028, 0x2029], [0x202a, 0x202e], [0x2066, 0x2069]];
const unsafeChar = (ch: string) => { const c = ch.codePointAt(0) as number; return UNSAFE_RANGES.some(([a, b]) => c >= a && c <= b); };
const hasUnsafe = (value: string) => Array.from(value).some(unsafeChar);

const bad = (why: string): never => { throw new Error('Not a valid map code: ' + why + '.'); };

function fnv1a(bytes: Uint8Array): string {
  let sum = 0x811c9dc5;
  for (const b of bytes) { sum ^= b; sum = Math.imul(sum, 0x01000193) >>> 0; }
  return sum.toString(16).padStart(8, '0');
}
function toBase64Url(bytes: Uint8Array): string {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function fromBase64Url(text: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]*$/.test(text)) bad('the payload is not base64url');
  const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
  try { return Uint8Array.from(atob(padded), c => c.charCodeAt(0)); } catch { return bad('the payload is not base64url'); }
}
const clean = (value: string, max: number) => Array.from(Array.from(value).map(ch => (unsafeChar(ch) ? ' ' : ch)).join('').trim()).slice(0, max).join('');

export function encodeMapCode(content: MapContent): string {
  if (content.nodes.length > MAP_CODE_LIMITS.nodes) throw new Error('Too many nodes for a map code (max ' + MAP_CODE_LIMITS.nodes + ').');
  if (content.edges.length > MAP_CODE_LIMITS.edges) throw new Error('Too many edges for a map code (max ' + MAP_CODE_LIMITS.edges + ').');
  const payload = {
    v: 1,
    n: content.nodes.map(n => [KINDS.indexOf(n.kind), clean(n.label, MAP_CODE_LIMITS.label), clean(n.category, MAP_CODE_LIMITS.category),
      STATES.indexOf(n.state), n.t === null ? null : Math.max(0, Math.min(MAP_CODE_LIMITS.timeSteps, Math.round(n.t)))]),
    e: content.edges.map(e => [e.from, e.to, clean(e.label, MAP_CODE_LIMITS.label)]),
  };
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  const code = `${PREFIX}.${fnv1a(bytes)}.${toBase64Url(bytes)}`;
  if (code.length > MAP_CODE_LIMITS.chars) throw new Error('Too large for a map code.');
  return code;
}

const label = (value: unknown, max: number, what: string, allowEmpty = false): string => {
  if (typeof value !== 'string' || (!allowEmpty && !value.trim()) || Array.from(value).length > max || hasUnsafe(value)) bad(what + ' is invalid');
  return value as string;
};

export function decodeMapCode(code: string): MapContent {
  const text = typeof code === 'string' ? code.trim() : '';
  if (!text) bad('it is empty');
  if (text.length > MAP_CODE_LIMITS.chars + 32) throw new Error('Not a valid map code: too large.');
  const parts = text.split('.');
  if (parts.length !== 3 || parts[0] !== PREFIX || !/^[0-9a-f]{8}$/.test(parts[1])) bad('it is not an ' + PREFIX + ' map code');
  if (parts[2].length > MAP_CODE_LIMITS.chars) throw new Error('Not a valid map code: too large.');
  const bytes = fromBase64Url(parts[2]);
  if (fnv1a(bytes) !== parts[1]) bad('the checksum does not match');
  let raw: any;
  try { raw = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); } catch { return bad('the payload is not JSON'); }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || raw.v !== 1) bad('unsupported version');
  if (!Array.isArray(raw.n) || !Array.isArray(raw.e)) bad('nodes and edges are missing');
  if (raw.n.length > MAP_CODE_LIMITS.nodes) bad('too many nodes');
  if (raw.e.length > MAP_CODE_LIMITS.edges) bad('too many edges');
  const nodes = raw.n.map((row: unknown): MapContentNode => {
    if (!Array.isArray(row) || row.length !== 5) bad('a node row is malformed');
    const [kind, name, category, state, t] = row as unknown[];
    if (!Number.isInteger(kind) || !KINDS[kind as number]) bad('a node kind is unknown');
    if (!Number.isInteger(state) || !STATES[state as number]) bad('a node state is unknown');
    if (t !== null && !(Number.isInteger(t) && (t as number) >= 0 && (t as number) <= MAP_CODE_LIMITS.timeSteps)) bad('a node time is out of range');
    return { kind: KINDS[kind as number], label: label(name, MAP_CODE_LIMITS.label, 'a node label'),
      category: label(category, MAP_CODE_LIMITS.category, 'a node category', true), state: STATES[state as number], t: t as number | null };
  });
  const edges = raw.e.map((row: unknown): MapContentEdge => {
    if (!Array.isArray(row) || row.length !== 3) bad('an edge row is malformed');
    const [from, to, name] = row as unknown[];
    if (!Number.isInteger(from) || !Number.isInteger(to) || (from as number) < 0 || (to as number) < 0
      || (from as number) >= nodes.length || (to as number) >= nodes.length) bad('an edge points at a missing node');
    return { from: from as number, to: to as number, label: label(name, MAP_CODE_LIMITS.label, 'an edge label', true) };
  });
  return { nodes, edges };
}
