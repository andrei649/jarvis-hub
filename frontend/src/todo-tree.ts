/* H666 — a flat list with parent links, read as an indented tree.

   The twin of agents/core/todo_tree.py (the CLI's), so `nerva todo`, the Decision Inbox and
   the mission canvas draw the same hierarchy. The agent's todo items carry an optional
   `parent` (another item's id) and mission plan steps a nullable `parent` (another step's
   idx). Hermes' rule, taken verbatim: nothing disappears.

   · items come back in depth-first order, children in list order under their parent;
   · depth stops at MAX_DEPTH: a deeper item draws at that depth, under its parent;
   · a parent that is missing, the item itself, or not an id at all draws at depth 0 in
     place (when two items share an id, the first holds it);
   · the members of a cycle, and anything under them, are reached from no root, so they are
     appended at the end, flat, at depth 0, in list order. */

export const MAX_DEPTH = 4;

/** A usable id: text or a whole number (a boolean is not one). Anything else is none. */
export function treeRef(value: unknown): string | number | null {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' && Number.isInteger(value)) return value;
  return null;
}

function read<T>(get: (item: T) => unknown, item: T): unknown {
  try { return get(item); } catch { return null; }
}

export function todoTree<T>(
  items: readonly T[],
  key: (item: T) => unknown,
  parent: (item: T) => unknown,
): Array<[T, number]> {
  const rows = Array.isArray(items) ? items : [];
  // Keyed by the ref itself, so 1 and '1' stay apart, as the backend's dict keeps them.
  const first = new Map<string | number, number>();
  rows.forEach((item, pos) => {
    const own = treeRef(read(key, item));
    if (own !== null && !first.has(own)) first.set(own, pos);
  });
  const children: number[][] = rows.map(() => []);
  const roots: number[] = [];
  rows.forEach((item, pos) => {
    const ref = treeRef(read(parent, item));
    const above = ref === null ? undefined : first.get(ref);
    if (above === undefined || above === pos) roots.push(pos);
    else children[above].push(pos);
  });
  const out: Array<[T, number]> = [];
  const placed = rows.map(() => false);
  for (const root of roots) {
    const stack: Array<[number, number]> = [[root, 0]];
    while (stack.length) {
      const [pos, depth] = stack.pop() as [number, number];
      placed[pos] = true;
      out.push([rows[pos], Math.min(depth, MAX_DEPTH)]);
      for (let k = children[pos].length - 1; k >= 0; k -= 1) stack.push([children[pos][k], depth + 1]);
    }
  }
  rows.forEach((item, pos) => { if (!placed[pos]) out.push([item, 0]); });
  return out;
}
