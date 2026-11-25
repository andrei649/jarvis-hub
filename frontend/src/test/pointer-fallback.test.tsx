/* Agent tips in the Ledger frame (PHASE_B_PLAN.md §3.8): an exact [data-anchor] still wins;
   without one a tip falls back to the area's masthead link, the contents-column link, the
   docket register, the Find button or the composer's textarea. POINTER_ANCHORS is unchanged. */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { POINTER_ANCHORS, anchorFallbacks, anchorRect } from '../pointer';
import { areaAnchor, areaOfMode } from '../nav/routes';
import { HUD_MODES } from '../hud-modes';

const RECT = { left: 100, top: 50, width: 80, height: 20, right: 180, bottom: 70 };
const NONE = { left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 };
function el(attrs: Record<string, string>, rect = RECT, tag = 'a', parent: HTMLElement = document.body) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  node.getBoundingClientRect = () => ({ ...rect, x: rect.left, y: rect.top, toJSON: () => ({}) }) as DOMRect;
  parent.appendChild(node);
  return node;
}

beforeEach(() => { document.body.innerHTML = ''; (document as any).elementFromPoint = () => null; });
afterEach(() => { document.body.innerHTML = ''; });

describe('anchorFallbacks', () => {
  it('names the masthead link of the mode\'s area, and the contents link', () => {
    expect(anchorFallbacks('mode.trust')).toEqual(['[data-anchor="area.trust"]', '[data-frame="contents"] a[data-page="mode:trust"]']);
    // a mode that is not its area's landing prefers its own contents link
    expect(anchorFallbacks('mode.projects')).toEqual(['[data-frame="contents"] a[data-page="mode:projects"]', '[data-anchor="area.work"]']);
    expect(anchorFallbacks('mode.finance')[1]).toBe('[data-anchor="area.agents"]');
    expect(anchorFallbacks('mode.interop')[0]).toBe('[data-anchor="area.connect"]');
    expect(anchorFallbacks('decisions')).toEqual(['[data-register="docket"]']);
    expect(anchorFallbacks('console')).toEqual(['[data-contents="find-panel"]', '[data-find]']);
    expect(anchorFallbacks('composer')).toEqual(['[data-composer]']);
    expect(anchorFallbacks('something-else')).toEqual([]);
  });

  it('has a masthead anchor for every mode a tip may name', () => {
    for (const anchor of POINTER_ANCHORS.filter((a) => a.startsWith('mode.'))) {
      const id = anchor.slice(5);
      expect(HUD_MODES as readonly string[], anchor).toContain(id);
      expect(areaOfMode(id), anchor).not.toBeNull();
      expect(anchorFallbacks(anchor).some((s) => s.includes(areaAnchor(areaOfMode(id)!))), anchor).toBe(true);
    }
  });
});

describe('anchorRect in the Ledger frame', () => {
  it('points a mode tip at its area\'s masthead link, and at the contents link when that is its page', () => {
    el({ 'data-anchor': 'area.trust' }, { ...RECT, left: 10 });
    expect(anchorRect('mode.trust', document, true)!.left).toBe(10);
    expect(anchorRect('mode.memory', document, true)).toBeNull();   // another area's link is not here
    const contents = el({ 'data-frame': 'contents' }, RECT, 'nav');
    el({ 'data-page': 'mode:projects' }, { ...RECT, left: 30 }, 'a', contents);
    el({ 'data-anchor': 'area.work' }, { ...RECT, left: 20 });
    expect(anchorRect('mode.projects', document, true)!.left).toBe(30);
  });

  it('points "decisions" at the docket register, "console" at the Find button, "composer" at the textarea', () => {
    el({ 'data-register': 'docket' }, { ...RECT, left: 1 }, 'section');
    el({ 'data-contents': 'find-panel' }, { ...RECT, left: 2 }, 'button');
    el({ 'data-composer': '' }, { ...RECT, left: 3 }, 'textarea');
    expect(anchorRect('decisions', document, true)!.left).toBe(1);
    expect(anchorRect('console', document, true)!.left).toBe(2);
    expect(anchorRect('composer', document, true)!.left).toBe(3);
  });

  it('prefers an exact anchor, and falls back from a hidden exact one', () => {
    el({ 'data-anchor': 'area.trust' }, { ...RECT, left: 10 });
    el({ 'data-anchor': 'mode.trust' }, { ...RECT, left: 99 });
    expect(anchorRect('mode.trust', document, true)!.left).toBe(99);
    document.body.innerHTML = '';
    el({ 'data-anchor': 'composer' }, NONE, 'div');
    el({ 'data-composer': '' }, { ...RECT, left: 3 }, 'textarea');
    expect(anchorRect('composer', document, true)!.left).toBe(3);
    expect(anchorRect('composer', document, false)).toBeNull();
  });

  it('skips a fallback that is hidden or under another layer, and tries the next', () => {
    el({ 'data-anchor': 'area.trust' }, NONE);                            // masthead drawer closed
    const contents = el({ 'data-frame': 'contents' }, RECT, 'nav');
    el({ 'data-page': 'mode:trust' }, { ...RECT, left: 40 }, 'a', contents);
    expect(anchorRect('mode.trust', document, true)!.left).toBe(40);
    (document as any).elementFromPoint = () => document.body;            // something sits over it
    expect(anchorRect('mode.trust', document, true)).toBeNull();
  });

  it('never invents a target for a name that is not an anchor', () => {
    el({ 'data-register': 'docket' });
    el({ 'data-anchor': 'approve' });
    expect(anchorRect('approve', document, true)).toBeNull();
    expect(anchorRect('mode.nope', document, true)).toBeNull();
  });

  it('uses the exact anchor alone when its fallbacks are turned off', () => {
    el({ 'data-anchor': 'area.trust' });
    el({ 'data-composer': '' }, RECT, 'textarea');
    el({ 'data-register': 'docket' }, RECT, 'section');
    expect(anchorRect('mode.trust', document, false)).toBeNull();
    expect(anchorRect('composer', document, false)).toBeNull();
    expect(anchorRect('decisions', document, false)).toBeNull();
  });

  it('falls back by default: the Ledger frame is the only one, and it has no rail or context column to carry the old anchors', () => {
    el({ 'data-anchor': 'area.trust' }, { ...RECT, left: 10 });
    el({ 'data-composer': '' }, { ...RECT, left: 3 }, 'textarea');
    el({ 'data-register': 'docket' }, { ...RECT, left: 1 }, 'section');
    expect(anchorRect('mode.trust')!.left).toBe(10);
    expect(anchorRect('composer')!.left).toBe(3);
    expect(anchorRect('decisions')!.left).toBe(1);
    // and still invents nothing for a name that is not an anchor
    expect(anchorRect('approve')).toBeNull();
  });
});
