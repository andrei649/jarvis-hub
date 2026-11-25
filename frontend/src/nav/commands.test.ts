import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CONSOLE_PANELS } from '../console-routes';
import { fmt, stringProblems } from '../frame/strings';
import { talkStrings } from '../home/talk/strings';
import { FORBIDDEN_TARGET } from '../shortcuts';
import { ALL_PAGES, AREAS, PAGES } from './areas';
import {
  COMMAND_STRINGS, FORBIDDEN_ACTION_WORDS, RECENT_KEY, RECENT_MAX, buildCommands, defineCommands, hintOf, kindWord,
  pushRecent, readRecent, searchableOf, type Command, type CommandContext,
} from './commands';
import { CONTENTS_STRINGS } from './contents-model';
import { SHEET_STRINGS, sheetSections } from './CommandSheet';
import { fold, rankBy } from './search';
import { pathOf } from './routes';

function ctx(over: Partial<CommandContext> = {}): CommandContext {
  return {
    lang: 'en',
    navigate: vi.fn(),
    agents: [{ id: 'frigga', name: 'Frigga', enabled: true, rosterSource: 'api' }, { id: 'athena', name: 'Athena' }, { id: 'old', name: 'Old', enabled: false }],
    onOpenAgent: vi.fn(),
    onWriteTo: vi.fn(),
    actions: { onGlance: vi.fn(), onCinema: vi.fn(), onShortcuts: vi.fn(), onVerifyRecord: vi.fn(), onRefresh: vi.fn(), demo: false, setDemo: vi.fn(), onPersonalisation: vi.fn() },
    ui: { font: 'theme', look: 'ledger', scheme: 'dark', density: 'normal', motion: 'lively', scanline: 'off', dotgrid: 'off', setFont: vi.fn(), setLook: vi.fn(), setScheme: vi.fn(), setDensity: vi.fn(), setMotion: vi.fn(), setScanline: vi.fn(), setDotgrid: vi.fn() },
    accent: 'cyan', setAccent: vi.fn(), setLang: vi.fn(), shortcutOverrides: {},
    ...over,
  };
}
const find = (commands: Command[], query: string, lang: 'en' | 'ro' = 'en') => rankBy(commands, query, (c) => searchableOf(c, lang));
const ids = (list: Command[]) => list.map((c) => c.id);

beforeEach(() => localStorage.clear());

describe('the strings', () => {
  it('are complete in English and Romanian', () => {
    expect(stringProblems(COMMAND_STRINGS)).toEqual([]);
    expect(stringProblems(SHEET_STRINGS)).toEqual([]);
    expect(stringProblems(CONTENTS_STRINGS)).toEqual([]);
  });
});

describe('the index', () => {
  const commands = buildCommands(ctx());

  it('holds every area, every page (modes, views, All pages) and every Console panel once', () => {
    expect(commands.filter((c) => c.kind === 'area')).toHaveLength(AREAS.length);
    for (const area of AREAS) expect(commands.find((c) => c.id === `area:${area.id}`)).toBeTruthy();
    for (const page of [...PAGES, ALL_PAGES]) expect(commands.find((c) => c.id === `page:${page.key}`), page.key).toBeTruthy();
    const panels = commands.filter((c) => c.group === 'panels');
    expect(panels.length).toBeGreaterThanOrEqual(CONSOLE_PANELS.length);
    expect(new Set(ids(commands)).size).toBe(commands.length);
  });

  it('finds every page by its label in both languages, with or without diacritics, by id and by alias', () => {
    for (const page of [...PAGES, ALL_PAGES]) {
      const id = `page:${page.key}`;
      expect(ids(find(commands, page.label.en)), `${page.key} en`).toContain(id);
      expect(ids(find(commands, page.label.ro, 'ro')), `${page.key} ro`).toContain(id);
      expect(ids(find(commands, fold(page.label.ro), 'ro')), `${page.key} ro folded`).toContain(id);
      expect(ids(find(commands, page.label.ro.toUpperCase(), 'en')), `${page.key} RO upper`).toContain(id);
      if (page.ref.kind !== 'allPages') expect(ids(find(commands, page.ref.id)), `${page.key} id`).toContain(id);
      for (const alias of page.aliases) expect(ids(find(commands, alias)), `${page.key} alias ${alias}`).toContain(id);
    }
  });

  it('finds every area by its name and puts it first for an exact word', () => {
    for (const area of AREAS) {
      expect(ids(find(commands, area.label.en))[0], area.id).toBe(`area:${area.id}`);
      expect(ids(find(commands, fold(area.label.ro), 'ro')), area.id).toContain(`area:${area.id}`);
    }
    expect(ids(find(commands, 'increder', 'ro'))[0]).toBe('area:trust');
  });

  it('finds the old Console and panel names as aliases', () => {
    expect(ids(find(commands, 'Kg'))).toContain('page:panel:kg');
    expect(ids(find(commands, 'Console'))).toContain('page:allPages');
    expect(find(commands, 'logs')[0].id).toBe('page:panel:logs');
  });

  it('puts a page hint of Area › Group beside a panel', () => {
    const logs = commands.find((c) => c.id === 'page:panel:logs') as Command;
    expect(hintOf(logs, 'en')).toBe('Observe › Health');
    expect(hintOf(logs, 'ro')).toContain('Observare');
    expect(kindWord(logs, 'en')).toBe('Panel');
    expect(kindWord(commands.find((c) => c.id === 'area:work') as Command, 'ro')).toBe('Zonă');
  });

  it('opens each page at its path', () => {
    const c = ctx();
    const built = buildCommands(c);
    built.find((x) => x.id === 'page:panel:logs')!.run();
    built.find((x) => x.id === 'page:mode:work')!.run();
    built.find((x) => x.id === 'area:connect')!.run();
    built.find((x) => x.id === 'page:allPages')!.run();
    expect(vi.mocked(c.navigate).mock.calls.map((x) => x[0])).toEqual(['/v2/console/logs', '/v2/work', '/v2/interop', '/v2/console']);
    for (const page of PAGES) expect(pathOf(page.ref)).toMatch(/^\/v2\//);
  });
});

describe('Write to follows what the composer will accept', () => {
  const writeIds = (agents: CommandContext['agents'], demo = false) => {
    const base = ctx();
    return buildCommands(ctx({ agents, actions: { ...base.actions, demo } })).filter((c) => c.id.startsWith('agent:write:')).map((c) => c.id);
  };
  it('offers it only for live roster rows that are not retired or disabled', () => {
    expect(writeIds([
      { id: 'a', name: 'A', rosterSource: 'api' },
      { id: 'b', name: 'B' },
      { id: 'c', name: 'C', rosterSource: 'api', status: 'disabled' },
      { id: 'd', name: 'D', rosterSource: 'api', status: 'retired' },
      { id: 'e', name: 'E', rosterSource: 'api', enabled: false },
    ] as CommandContext['agents'])).toEqual(['agent:write:a']);
  });
  it('accepts any enabled agent in the demo, as selectChatAgent does', () => {
    expect(writeIds([{ id: 'b', name: 'B' }, { id: 'e', name: 'E', enabled: false }] as CommandContext['agents'], true)).toEqual(['agent:write:b']);
  });
  it('skips a bad roster row instead of throwing', () => {
    const built = buildCommands(ctx({ agents: [
      { id: 'a', name: 'A', rosterSource: 'api' }, { id: 'a', name: 'Again', rosterSource: 'api' },
      { id: 'n', name: 42 }, { id: '' }, null,
    ] as unknown as CommandContext['agents'] }));
    expect(built.filter((c) => c.id === 'agent:open:a')).toHaveLength(1);
    expect(built.find((c) => c.id === 'agent:open:n')!.label.en).toBe('Open n');
    expect(built.filter((c) => c.kind === 'agent').map((c) => c.id)).toEqual(['agent:open:a', 'agent:write:a', 'agent:open:n']);
  });
});

describe('a verdict named in Romanian is no command either', () => {
  const action = (label: string, id = 'action:x'): Command => ({ id, kind: 'action', group: 'actions', label: { en: 'Open it', ro: label }, aliases: [], ids: [], hint: null, run: () => {} });
  it.each(['Aprobă', 'Respinge', 'Semnează', 'Oprește', 'Amână cererea', 'Acceptă', 'Schimbă modul'])('refuses %s', (word) => {
    expect(() => defineCommands([action(word)])).toThrow();
  });
  it('lets the ordinary Romanian actions through', () => {
    expect(() => defineCommands([action('Reîmprospătează datele live', 'action:a'), action('Dintr-o privire', 'action:b')])).not.toThrow();
  });
});

describe('agents', () => {
  it('has Open (the dossier, not the recipient) and Write to (the recipient) for each agent', () => {
    const c = ctx();
    const built = buildCommands(c);
    expect(ids(built.filter((x) => x.kind === 'agent'))).toEqual([
      'agent:open:frigga', 'agent:write:frigga', 'agent:open:athena', 'agent:open:old',
    ]);   // athena has no live roster row, old is disabled: neither can be written to
    expect(built.find((x) => x.id === 'agent:open:frigga')!.label.en).toBe('Open Frigga');
    built.find((x) => x.id === 'agent:open:frigga')!.run();
    built.find((x) => x.id === 'agent:write:frigga')!.run();
    expect(c.onOpenAgent).toHaveBeenCalledWith('frigga');
    expect(c.onWriteTo).toHaveBeenCalledWith('frigga');
    expect(c.onOpenAgent).toHaveBeenCalledTimes(1);
    expect(ids(find(built, 'frigga'))).toEqual(expect.arrayContaining(['agent:open:frigga', 'agent:write:frigga']));
  });
  it('words Write to as the conversation does: the composer\'s question and the Dossier say the same', () => {
    const write = buildCommands(ctx()).find((x) => x.id === 'agent:write:frigga')!;
    expect(write.label).toEqual({ en: 'Write to Frigga', ro: 'Scrie-i lui Frigga' });
    // one phrase for one act, in both languages: the sheet takes the talk register's own words
    expect(write.label.en).toBe(fmt(talkStrings('en').writeTo, { agent: 'Frigga' }));
    expect(write.label.ro).toBe(fmt(talkStrings('ro').writeTo, { agent: 'Frigga' }));
    // and it is still found by the Romanian words the owner types
    expect(ids(find(buildCommands(ctx()), 'scrie-i lui frigga', 'ro'))).toContain('agent:write:frigga');
  });
});

describe('actions and the appearance rows', () => {
  it('holds the read-only actions, each running its handler', () => {
    const c = ctx();
    const built = buildCommands(c);
    for (const [id, fn] of [['glance', c.actions.onGlance], ['cinema', c.actions.onCinema], ['shortcuts', c.actions.onShortcuts],
      ['verify-record', c.actions.onVerifyRecord], ['refresh', c.actions.onRefresh], ['personalisation', c.actions.onPersonalisation]] as const) {
      built.find((x) => x.id === `action:${id}`)!.run();
      expect(fn, id).toHaveBeenCalledTimes(1);
    }
    expect(built.find((x) => x.id === 'action:demo')!.label.en).toBe('Turn the demo sample on');
    built.find((x) => x.id === 'action:demo')!.run();
    expect(c.actions.setDemo).toHaveBeenCalledWith(true);
    const on = buildCommands(ctx({ actions: { ...c.actions, demo: true } }));
    expect(on.find((x) => x.id === 'action:demo')!.label.en).toBe('Turn the demo sample off');
  });

  it('keeps the old palette rows word for word, the active choice ticked', () => {
    const labels = buildCommands(ctx()).filter((x) => x.group === 'appearance').map((x) => x.label.en);
    for (const row of [
      'Accent · Cyan', 'Accent · Amber', 'Accent · Green', 'Accent · Violet', 'Language · English ✓', 'Language · Română',
      'Font · Theme Default ✓', 'Font · System Sans', 'Font · JetBrains Mono', 'Look · Ledger ✓', 'Look · Obsidian', 'Look · Graphite',
      'Scheme · Dark ✓', 'Scheme · Light', 'Scheme · System', 'Density · Compact', 'Density · Normal ✓', 'Density · Comfy',
      'Motion · System', 'Motion · Lively ✓', 'Motion · Calm', 'Scanline · On', 'Dot grid · On',
    ]) expect(labels, row).toContain(row);
    const classic = buildCommands(ctx({ ui: { look: 'obsidian', scheme: 'light', scanline: 'off', dotgrid: 'on' } })).filter((x) => x.group === 'appearance').map((x) => x.label.en);
    expect(classic).toEqual(expect.arrayContaining(['Look · Obsidian ✓', 'Look · Graphite', 'Scheme · Light ✓', 'Dot grid · Off']));
  });

  it('sets the preference when a row runs', () => {
    const c = ctx();
    const built = buildCommands(c);
    built.find((x) => x.id === 'appearance:scheme-light')!.run();
    built.find((x) => x.id === 'appearance:look-obsidian')!.run();
    built.find((x) => x.id === 'appearance:density-compact')!.run();
    built.find((x) => x.id === 'appearance:scanline')!.run();
    built.find((x) => x.id === 'appearance:accent-amber')!.run();
    built.find((x) => x.id === 'appearance:language-ro')!.run();
    expect(c.ui.setScheme).toHaveBeenCalledWith('light');
    expect(c.ui.setLook).toHaveBeenCalledWith('obsidian');
    expect(c.ui.setDensity).toHaveBeenCalledWith('compact');
    expect(c.ui.setScanline).toHaveBeenCalledWith('on');
    expect(c.setAccent).toHaveBeenCalledWith('amber');
    expect(c.setLang).toHaveBeenCalledWith('ro');
  });
});

describe('no verdict is ever a command', () => {
  const act = (id: string, en: string, ro = en, aliases: string[] = []): Command =>
    ({ id, kind: 'action', group: 'actions', label: { en, ro }, aliases, ids: [], hint: null, run: () => {} });

  it('refuses an action whose id, label or alias names a verdict, a signature, the stop or a mode change', () => {
    for (const bad of [
      act('action:approve-all', 'Tidy up'), act('action:x', 'Approve the card'), act('action:x', 'Reject it'), act('action:x', 'Defer the entry'),
      act('action:x', 'Sign the entry'), act('action:x', 'Stop everything'), act('action:x', 'Resume'), act('action:x', 'Give consent'),
      act('action:x', 'Switch the approval mode'), act('action:x', 'Decide now'), act('action:x', 'Deny'), act('action:x', 'Accept the offer'),
      act('action:x', 'Fine', 'Ok', ['Reject']), act('action:kill', 'Kill switch'),
    ]) {
      expect(() => defineCommands([bad]), `${bad.id} ${bad.label.en}`).toThrow(/may not be/);
    }
    expect(() => defineCommands([act('action:a', 'One'), act('action:a', 'Two')])).toThrow(/duplicate/);
  });

  it('lets navigation mention decisions, and allows ordinary words that merely contain the letters', () => {
    const nav: Command = { ...act('page:panel:decision-inbox', 'Decisions'), kind: 'page', group: 'panels' };
    expect(() => defineCommands([nav])).not.toThrow();
    expect(FORBIDDEN_ACTION_WORDS.test('Design review')).toBe(false);
    expect(FORBIDDEN_ACTION_WORDS.test('Signal governance')).toBe(false);
    expect(FORBIDDEN_ACTION_WORDS.test('Motion · System')).toBe(false);
    expect(FORBIDDEN_ACTION_WORDS.test('Sign it')).toBe(true);
  });

  it('holds no action that matches FORBIDDEN_TARGET or the stop and mode words', () => {
    for (const c of buildCommands(ctx()).filter((x) => x.kind === 'action')) {
      for (const text of [c.id, c.label.en, c.label.ro, ...c.aliases]) {
        expect(FORBIDDEN_TARGET.test(text), `${c.id}: ${text}`).toBe(false);
        expect(FORBIDDEN_ACTION_WORDS.test(text), `${c.id}: ${text}`).toBe(false);
      }
    }
  });

  it('never answers a verdict word with an action', () => {
    const built = buildCommands(ctx());
    for (const word of ['approve', 'sign', 'reject', 'defer', 'consent', 'decide', 'stop', 'resume', 'deny', 'accept']) {
      const hits = find(built, word).filter((c) => c.kind === 'action' || c.kind === 'agent');
      expect(hits.map((c) => c.id), word).toEqual([]);
    }
  });
});

describe('recents', () => {
  it('keeps the five newest ids, newest first, without repeats', () => {
    for (const id of ['a', 'b', 'c', 'd', 'e', 'f', 'c']) pushRecent(id);
    expect(readRecent()).toEqual(['c', 'f', 'e', 'd', 'b']);
    expect(readRecent()).toHaveLength(RECENT_MAX);
    expect(JSON.parse(localStorage.getItem(RECENT_KEY) as string)).toEqual(['c', 'f', 'e', 'd', 'b']);
  });

  it('survives unreadable storage', () => {
    localStorage.setItem(RECENT_KEY, '{nope');
    expect(readRecent()).toEqual([]);
    localStorage.setItem(RECENT_KEY, JSON.stringify([1, 'ok', null]));
    expect(readRecent()).toEqual(['ok']);
    const throwing = { getItem: () => { throw new Error('off'); }, setItem: () => { throw new Error('off'); } } as unknown as Storage;
    expect(readRecent(throwing)).toEqual([]);
    expect(pushRecent('x', throwing)).toEqual(['x']);
  });
});

describe('sheetSections', () => {
  const commands = buildCommands(ctx());
  it('lists recents, areas and actions for an empty query, and only panels under the filter', () => {
    const sections = sheetSections(commands, '', null, ['page:panel:logs'], 'en');
    expect(sections.map((s) => s.key)).toEqual(['recent', 'areas', 'actions']);
    expect(sections[0].items.map((c) => c.id)).toEqual(['page:panel:logs']);
    const panels = sheetSections(commands, '', 'panels', [], 'en');
    expect(panels).toHaveLength(1);
    expect(panels[0].items.every((c) => c.group === 'panels')).toBe(true);
    expect(panels[0].items.length).toBeGreaterThanOrEqual(CONSOLE_PANELS.length);
  });
  it('ranks a query across everything, filters to panels, and says nothing when nothing matches', () => {
    expect(sheetSections(commands, 'kill', 'panels', [], 'en')[0].items[0].id).toBe('page:panel:kill-switch');
    expect(sheetSections(commands, 'zzzzqq', null, [], 'en')).toEqual([]);
    expect(sheetSections(commands, 'logs', 'panels', [], 'en')[0].items.every((c) => c.group === 'panels')).toBe(true);
  });
});
