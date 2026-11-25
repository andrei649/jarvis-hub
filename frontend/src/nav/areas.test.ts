import { describe, expect, it } from 'vitest';
import { CONSOLE_PANELS, CONSOLE_PANEL_MAP } from '../console-routes';
import { HUD_MODES } from '../hud-modes';
import { stringProblems } from '../frame/strings';
import {
  ALL_PAGES, AREAS, AREA_IDS, ATTENTION_STRINGS, PAGES, areaById, areaNote, attentionWords, groupOf,
  pageForMode, pageForPanel, type AreaId,
} from './areas';
import { GROUP_DEFAULT_AREA, UNKNOWN_GROUP_AREA, groupDefaultArea, placePanel } from './placement';
import type { AttentionNote } from '../signals/types';

const panels = PAGES.filter((p) => p.ref.kind === 'panel');
const modes = PAGES.filter((p) => p.ref.kind === 'mode');
const idOf = (p: (typeof PAGES)[number]) => (p.ref as { id: string }).id;
const CEDILLA = /[ŞşŢţ]/;

describe('the nine areas', () => {
  it('are in masthead order with their display names', () => {
    expect(AREAS.map((a) => a.id)).toEqual([...AREA_IDS]);
    expect(AREAS.map((a) => a.label.en)).toEqual(['Home', 'Work', 'Agents', 'Memory', 'Trust', 'Build', 'Connect', 'Observe', 'Settings']);
    expect(AREAS.map((a) => a.label.ro)).toEqual(['Acasă', 'Lucru', 'Agenți', 'Memorie', 'Încredere', 'Construire', 'Conexiuni', 'Observare', 'Setări']);
  });

  it('each open on their landing page (Home stays /v2/cockpit, Connect /v2/interop, Settings /v2/admin)', () => {
    const landing = Object.fromEntries(AREAS.map((a) => [a.id, a.landing.ref]));
    expect(landing).toEqual({
      home: { kind: 'mode', id: 'cockpit' }, work: { kind: 'mode', id: 'work' }, agents: { kind: 'mode', id: 'agents' },
      memory: { kind: 'mode', id: 'memory' }, trust: { kind: 'mode', id: 'trust' }, build: { kind: 'mode', id: 'build' },
      connect: { kind: 'mode', id: 'interop' }, observe: { kind: 'mode', id: 'observe' }, settings: { kind: 'mode', id: 'admin' },
    });
    for (const area of AREAS) {
      expect(area.groups[0].label).toBeNull();
      expect(area.groups[0].pages[0]).toBe(area.landing);
      expect(area.landing.landing && area.landing.primary && area.landing.listed).toBe(true);
      expect(area.pages.filter((p) => p.landing)).toEqual([area.landing]);
    }
  });

  it('name the signals behind their masthead notes (§3.9)', () => {
    expect(Object.fromEntries(AREAS.filter((a) => a.attention.length).map((a) => [a.id, a.attention])))
      .toEqual({ work: ['docket'], trust: ['record', 'payments'], observe: ['services'] });
    expect(pageForPanel('decision-inbox')?.attention).toBe('docket');
    expect(pageForPanel('payments')?.attention).toBe('payments');
    expect(pageForPanel('kill-switch')?.attention).toBe('killSwitch');
    expect(PAGES.filter((p) => p.attention).map((p) => p.key).sort()).toEqual(['panel:decision-inbox', 'panel:kill-switch', 'panel:payments']);
  });
});

describe('the §3.3 placement table', () => {
  it('places every CONSOLE_PANELS id in exactly one area, all of them explicitly', () => {
    for (const panel of CONSOLE_PANELS) {
      const found = panels.filter((p) => idOf(p) === panel.id);
      expect(found.map((p) => p.area), panel.id).toHaveLength(1);
    }
    expect(panels.filter((p) => p.auto).map(idOf)).toEqual([]);
    const count = (area: AreaId) => panels.filter((p) => p.area === area).length;
    expect(Object.fromEntries(AREA_IDS.map((a) => [a, count(a)]))).toEqual({
      home: 7, work: 13, agents: 9, memory: 14, trust: 21, build: 22, connect: 17, observe: 16, settings: 17,
    });
    expect(panels).toHaveLength(CONSOLE_PANELS.length);
  });

  it('has no entry that CONSOLE_PANELS lacks, except Personalisation, which says why it may be missing', () => {
    const missing = panels.filter((p) => !CONSOLE_PANEL_MAP.has(idOf(p)));
    for (const p of missing) expect(p.optional, idOf(p)).toBeTruthy();
    expect(panels.filter((p) => p.optional).map(idOf)).toEqual(['appearance']);
    expect(pageForPanel('appearance')).toMatchObject({ area: 'settings', label: { en: 'Personalisation', ro: 'Personalizare' } });
  });

  it('places every HUD_MODES id exactly once, and nothing else', () => {
    for (const mode of HUD_MODES) expect(modes.filter((p) => idOf(p) === mode), mode).toHaveLength(1);
    expect(modes.map(idOf).sort()).toEqual([...HUD_MODES].sort());
    expect(Object.fromEntries(HUD_MODES.map((m) => [m, pageForMode(m)?.area]))).toEqual({
      cockpit: 'home', chat: 'home', glance: 'home',
      work: 'work', timeline: 'work', projects: 'work', jobs: 'work', autonomy: 'work',
      agents: 'agents', finance: 'agents', health: 'agents', knowledge: 'agents', family: 'agents',
      memory: 'memory', artifacts: 'memory', trust: 'trust', build: 'build',
      interop: 'connect', comms: 'connect', observe: 'observe', world: 'observe', admin: 'settings',
    });
  });

  it('declares the Jobs duplicate: both URLs work, the contents column lists only /v2/jobs', () => {
    expect(pageForPanel('jobs')).toMatchObject({ area: 'work', listed: false, primary: false, duplicateOf: { kind: 'mode', id: 'jobs' } });
    expect(pageForMode('jobs')).toMatchObject({ area: 'work', listed: true });
    expect(PAGES.filter((p) => p.duplicateOf).map((p) => p.key)).toEqual(['panel:jobs']);
  });

  it('keeps Glance out of the contents column and All pages out of every area', () => {
    expect(pageForMode('glance')).toMatchObject({ area: 'home', listed: false, primary: false });
    expect(ALL_PAGES).toMatchObject({ area: null, ref: { kind: 'allPages' } });
    expect(PAGES.some((p) => p.key === ALL_PAGES.key)).toBe(false);
  });

  it('moves Today to Home and puts eight pages behind "More in Home"', () => {
    expect(pageForPanel('today')?.area).toBe('home');
    const home = areaById('home')!;
    expect(home.pages.filter((p) => p.listed && !p.landing)).toHaveLength(8);
  });

  it('gives every key once', () => {
    const keys = PAGES.map((p) => p.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const p of PAGES) expect(groupOf(p)?.pages).toContain(p);
  });
});

describe('labels', () => {
  it('are never blank, in either language, and Romanian takes ș and ț', () => {
    const texts = [
      ...AREAS.map((a) => a.label),
      ...AREAS.flatMap((a) => a.groups.map((g) => g.label).filter(Boolean)),
      ...PAGES.map((p) => p.label),
      ALL_PAGES.label,
    ] as { en: string; ro: string }[];
    for (const t of texts) {
      expect(t.en.trim(), JSON.stringify(t)).not.toBe('');
      expect(t.ro.trim(), JSON.stringify(t)).not.toBe('');
      expect(CEDILLA.test(t.ro), t.ro).toBe(false);
    }
  });

  it('keep the old names as search aliases', () => {
    const findable = (alias: string) => [...PAGES, ALL_PAGES].some((p) => p.aliases.some((a) => a.toLowerCase() === alias.toLowerCase()));
    for (const alias of ['Kg', 'O Auth', 'A2 A Inbox', 'Llm Routing', 'Vlm Describe', 'Console', 'Cockpit', 'Interop', 'Admin', 'Ambient']) {
      expect(findable(alias), alias).toBe(true);
    }
    // every CONSOLE_PANELS label that differs from the display label is an alias
    for (const p of panels) {
      const old = CONSOLE_PANEL_MAP.get(idOf(p))?.label;
      if (old && old.toLowerCase() !== p.label.en.toLowerCase()) expect(p.aliases, idOf(p)).toContain(old);
    }
  });

  it('show at most twelve primary pages per area', () => {
    for (const area of AREAS) {
      const primary = area.pages.filter((p) => p.listed && p.primary);
      expect(primary.length, area.id).toBeGreaterThanOrEqual(1);
      expect(primary.length, area.id).toBeLessThanOrEqual(12);
    }
    expect(PAGES.filter((p) => !p.listed && p.primary)).toEqual([]);
  });
});

describe('placement defaults (nav/placement.ts)', () => {
  it('maps each CONSOLE_PANELS group to its default area', () => {
    expect(GROUP_DEFAULT_AREA).toEqual({
      Start: 'home', Home: 'home', Memory: 'memory', Trust: 'trust', Interop: 'connect', Observe: 'observe',
      Build: 'build', 'Autonomy & Agents': 'work', Admin: 'settings',
    });
    for (const group of new Set(CONSOLE_PANELS.map((p) => p.group))) expect(GROUP_DEFAULT_AREA[group], group).toBeTruthy();
    expect(groupDefaultArea('A group added later')).toBe(UNKNOWN_GROUP_AREA);
  });

  it('prefers the explicit table, else the group default, and knows nothing of unknown ids', () => {
    const explicit = new Map<string, AreaId>(panels.map((p) => [idOf(p), p.area as AreaId]));
    expect(placePanel('model-setup', explicit)).toBe('settings');
    expect(placePanel('model-setup', new Map())).toBe('home');
    expect(placePanel('osint', new Map())).toBe('connect');
    expect(placePanel('no-such-panel', explicit)).toBeNull();
  });
});

describe('attention notes', () => {
  it('have complete strings', () => {
    expect(stringProblems(ATTENTION_STRINGS)).toEqual([]);
  });

  it('read as the spec words, with the accent only for the owner\'s hand', () => {
    expect(attentionWords({ key: 'docket', count: 9 }, 'en')).toEqual({ long: '9 need you', short: '9', mark: null, hand: true });
    expect(attentionWords({ key: 'docket', count: 1 }, 'ro').long).toBe('1 te așteaptă');
    expect(attentionWords({ key: 'payments', count: 1 }, 'en')).toMatchObject({ long: '1 waits', hand: true });
    expect(attentionWords({ key: 'services', count: 4 }, 'en')).toEqual({ long: '4 services down', short: '4', mark: 'problem', hand: false });
    expect(attentionWords({ key: 'services', count: 21 }, 'ro').long).toBe('21 de servicii oprite');
    expect(attentionWords({ key: 'record', brokenAt: 412 }, 'en')).toMatchObject({ long: 'record broken at entry 412', mark: 'problem', hand: false });
    // §3.9 "■ record broken" at every width; the entry number only where there is room
    expect(attentionWords({ key: 'record', brokenAt: 412 }, 'en').short).toBe('record broken');
    expect(attentionWords({ key: 'record', brokenAt: null }, 'ro')).toMatchObject({ long: 'registrul este rupt', short: 'registrul este rupt' });
    expect(attentionWords({ key: 'killSwitch', state: 'unknown' }, 'en')).toMatchObject({ long: 'Unknown', mark: 'unknown' });
  });

  it('draw, at any width, only words of the long note: the short one is its first words (WCAG 2.5.3)', () => {
    // the masthead link is named "<Area> — <long>"; the words it draws below 1680px are the short
    // note, so they must be the long note's first words for the drawn text to be part of the name
    const notes: AttentionNote[] = [
      { key: 'docket', count: 1 }, { key: 'docket', count: 9 }, { key: 'payments', count: 3 },
      { key: 'services', count: 4 }, { key: 'services', count: 21 },
      { key: 'record', brokenAt: 412 }, { key: 'record', brokenAt: null },
      { key: 'killSwitch', state: 'armed' }, { key: 'killSwitch', state: 'halted' }, { key: 'killSwitch', state: 'unknown' },
    ];
    for (const lang of ['en', 'ro'] as const) {
      for (const note of notes) {
        const { long, short } = attentionWords(note, lang);
        const longWords = long.split(/\s+/);
        const shortWords = short.split(/\s+/);
        expect(longWords.slice(0, shortWords.length), `${lang} ${JSON.stringify(note)}: "${short}" is not the start of "${long}"`).toEqual(shortWords);
      }
    }
  });

  it('give an area the first note its keys have, and none when nothing honest is known', () => {
    const trust = areaById('trust')!;
    expect(areaNote(trust, { payments: { key: 'payments', count: 2 }, record: { key: 'record', brokenAt: null } })).toEqual({ key: 'record', brokenAt: null });
    expect(areaNote(trust, { payments: { key: 'payments', count: 2 } })).toEqual({ key: 'payments', count: 2 });
    expect(areaNote(trust, {})).toBeNull();
    expect(areaNote(areaById('memory')!, { docket: { key: 'docket', count: 3 } })).toBeNull();
  });
});
