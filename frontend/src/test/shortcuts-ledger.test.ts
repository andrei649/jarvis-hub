/* The HUD's keys (PHASE_B_PLAN.md §3.6), the one registry since the classic frame and its switch
   were deleted (stage 5); shortcuts.test.tsx pins its default table. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ACTIONS, FORBIDDEN_TARGET, defineActions, readOverrides } from '../shortcuts';
import { AREAS, pageForMode } from '../nav/areas';

const chords = (list: typeof ACTIONS) => Object.fromEntries(list.map((a) => [a.id, a.chord]));

describe('the registry', () => {
  it('puts the nine areas on 1–9 in masthead order and the conversation on 0', () => {
    const c = chords(ACTIONS);
    expect(['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'].map((k) => ACTIONS.find((a) => a.chord === k)!.id)).toEqual([
      'mode.cockpit', 'mode.work', 'mode.agents', 'mode.memory', 'mode.trust', 'mode.build', 'mode.interop', 'mode.observe', 'mode.admin', 'mode.chat',
    ]);
    // the area behind each of keys 1–9 is the masthead order
    const area = (id: string) => pageForMode(id.slice(5))!.area;
    expect(['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((k) => area(ACTIONS.find((a) => a.chord === k)!.id))).toEqual(AREAS.map((a) => a.id));
    expect(c['mode.autonomy']).toBeUndefined();
    expect(c['mode.comms']).toBeUndefined();
    expect(c['view.world']).toBeUndefined();
    expect(c).toMatchObject({ 'view.console': '`', 'view.ambient': 'a', 'view.cinema': 'm', 'composer.focus': '/', 'session.palette': 'mod+k', 'session.shortcuts': 'mod+/' });
  });

  it('words the labels for the new places', () => {
    const label = (id: string) => ACTIONS.find((a) => a.id === id)!.label;
    expect(label('mode.interop')).toBe('Go to Connect');
    expect(label('mode.admin')).toBe('Go to Settings');
    expect(label('mode.work')).toBe('Go to Work');
    expect(label('mode.cockpit')).toBe('Go to Home');
    expect(label('mode.chat')).toBe('Go to Conversation');
    expect(label('view.console')).toBe('Find a panel');
    expect(label('view.ambient')).toBe('Glance');
  });

  it('holds no chord for an approval or a decision, no docket verb and no duplicate chord in a scope', () => {
    for (const a of ACTIONS) {
      expect(FORBIDDEN_TARGET.test(`${a.id} ${a.category} ${a.label}`), a.id).toBe(false);
      expect(/sign|docket|stop/i.test(a.id), a.id).toBe(false);
    }
    const seen = new Set<string>();
    for (const a of ACTIONS) { const k = `${a.scope}:${a.chord}`; expect(seen.has(k), k).toBe(false); seen.add(k); }
    expect(() => defineActions(ACTIONS)).not.toThrow();
  });
});

describe('the registry a page loads', () => {
  afterEach(() => { history.replaceState(null, '', '/'); localStorage.clear(); vi.resetModules(); });

  it('is the same whatever the URL or the browser says, and drops a stored override for an id it no longer has', async () => {
    for (const path of ['/v2/cockpit', '/v2/cockpit?frame=classic']) {
      history.replaceState(null, '', path);
      localStorage.setItem('hud.frame', 'classic');   // the deleted switch's word, from an old browser
      vi.resetModules();
      const mod = await import('../shortcuts');
      expect(mod.ACTIONS.map((a) => a.id), path).toEqual(ACTIONS.map((a) => a.id));
      expect(mod.ACTIONS_MAP.has('mode.work')).toBe(true);
      expect(mod.ACTIONS_MAP.has('mode.comms')).toBe(false);
      expect(mod.readOverrides({ 'mode.comms': 'x', 'mode.autonomy': 'y', 'mode.work': 'x' })).toEqual({ 'mode.work': 'x' });
    }
    // the registry this file loaded with drops the HUD v2 rail's ids too
    expect(readOverrides({ 'mode.comms': 'x', 'mode.work': 'x' })).toEqual({ 'mode.work': 'x' });
  });
});
