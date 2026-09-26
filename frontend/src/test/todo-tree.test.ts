/* H666 — the HUD's tree builder. The shared cases in todo-tree-cases.json pin it to the
   Python twin (agents/core/todo_tree.py); tests/test_h666_subtasks.py reads the same file. */
import { describe, it, expect } from 'vitest';
import { MAX_DEPTH, todoTree } from '../todo-tree';
import shared from './todo-tree-cases.json';

type Row = { id: unknown; parent?: unknown };
const rows = (...pairs: Array<[unknown, unknown]>): Row[] => pairs.map(([id, parent]) => ({ id, parent }));
const shape = (list: Row[]) => todoTree(list, (r) => r.id, (r) => r.parent).map(([r, d]) => [r.id, d]);

describe('todoTree (H666)', () => {
  it('puts children under their parent, depth first, in list order', () => {
    expect(shape(rows(['a', null], ['b', null], ['a1', 'a'], ['b1', 'b'], ['a2', 'a'], ['a1x', 'a1'])))
      .toEqual([['a', 0], ['a1', 1], ['a1x', 2], ['a2', 1], ['b', 0], ['b1', 1]]);
    expect(shape(rows(['c', 'p'], ['p', null]))).toEqual([['p', 0], ['c', 1]]);
  });

  it('stops depth at four and keeps the deeper items under their parent', () => {
    const chain = rows(...Array.from({ length: 7 }, (_, i): [unknown, unknown] => [`n${i}`, i ? `n${i - 1}` : null]), ['tail', null]);
    expect(MAX_DEPTH).toBe(4);
    expect(shape(chain)).toEqual([['n0', 0], ['n1', 1], ['n2', 2], ['n3', 3], ['n4', 4], ['n5', 4], ['n6', 4], ['tail', 0]]);
  });

  it('draws a dangling or self parent at depth 0 in place, and a self parent keeps its children', () => {
    expect(shape(rows(['a', null], ['orphan', 'gone'], ['b', null]))).toEqual([['a', 0], ['orphan', 0], ['b', 0]]);
    expect(shape(rows(['me', 'me'], ['kid', 'me']))).toEqual([['me', 0], ['kid', 1]]);
  });

  it('appends cycle members flat after the tree', () => {
    expect(shape(rows(['x', 'y'], ['root', null], ['y', 'x'], ['under', 'x'], ['r1', 'root'])))
      .toEqual([['root', 0], ['r1', 1], ['x', 0], ['y', 0], ['under', 0]]);
  });

  it('never drops or repeats an item, whatever the parents are', () => {
    const list = rows(['a', 'b'], ['b', 'c'], ['c', 'a'], ['d', 'd'], ['e', 'zz'], ['f', null], ['g', 'f'],
      ['a', 'f'], ['h', ['x']], ['i', true], ['j', { id: 'f' }], ['k', 1.5]);
    const got = todoTree(list, (r) => r.id, (r) => r.parent).map(([r]) => r);
    expect(got.length).toBe(list.length);
    expect(new Set(got).size).toBe(list.length);
  });

  it('reads only text or whole numbers as ids: a boolean, a float or a string index is no parent', () => {
    // The boolean sits on step 2: read as 1 it would nest under step 1, so the case tells.
    const steps = [{ idx: 0, parent: null }, { idx: 1, parent: null }, { idx: 2, parent: true },
      { idx: 3, parent: 0.5 }, { idx: 4, parent: '0' }, { idx: 5, parent: 0 }];
    expect(todoTree(steps, (s) => s.idx, (s) => s.parent).map(([s, d]) => [s.idx, d]))
      .toEqual([[0, 0], [5, 1], [1, 0], [2, 0], [3, 0], [4, 0]]);
    // a float is no id as a key either
    const floats = [{ idx: 0.5, parent: null }, { idx: 1, parent: 0.5 }];
    expect(todoTree(floats, (s) => s.idx, (s) => s.parent).map(([, d]) => d)).toEqual([0, 0]);
  });

  it('lets the first of two items sharing an id hold it, and survives a getter that throws', () => {
    expect(shape(rows(['a', null], ['a', null], ['k', 'a']))).toEqual([['a', 0], ['k', 1], ['a', 0]]);
    const boom = () => { throw new Error('no'); };
    expect(todoTree([{ id: 'a' }, { id: 'b' }], (r) => r.id, boom).map(([, d]) => d)).toEqual([0, 0]);
    expect(todoTree(null as unknown as Row[], (r) => r.id, (r) => r.parent)).toEqual([]);
  });

  it('walks a long chain without recursion', () => {
    const chain = rows(...Array.from({ length: 5000 }, (_, i): [unknown, unknown] => [`n${i}`, i ? `n${i - 1}` : null]));
    const got = shape(chain);
    expect(got.length).toBe(5000);
    expect(got[4999]).toEqual(['n4999', MAX_DEPTH]);
  });

  it('draws every shared case exactly as the Python twin does', () => {
    const cases = (shared as { cases: Array<{ name: string; items: Row[]; expected: number[][] }> }).cases;
    expect(cases.length).toBeGreaterThanOrEqual(40);
    for (const c of cases) {
      const got = todoTree(c.items, (r) => r.id, (r) => r.parent).map(([r, d]) => [c.items.indexOf(r), d]);
      expect(got, c.name).toEqual(c.expected);
    }
  });
});
