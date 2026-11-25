/* The command index behind Ctrl K (PHASE_B_PLAN.md §3.7).

   What the sheet finds: the nine areas, every page (the modes, the views, all Console panels and
   All pages), one "Open" and one "Write to" per agent, and a short list of read-only actions
   plus the appearance rows of the old palette, word for word ("Look · Ledger ✓", "Scheme · Dark",
   "Density · Compact" …).

   What it never holds: a verdict. defineCommands() refuses an *action* whose id or label names an
   approval, a decision, a rejection, a deferral, a signature, the stop or a mode change (the same
   FORBIDDEN_TARGET the keyboard registry uses, plus those words). Navigation entries may be
   called "Decisions" because they only open a page. Nothing here posts anything: an action
   either navigates, opens a surface, re-reads, or sets an appearance preference. */
import { LANGUAGES } from '../data';
import { FORBIDDEN_TARGET, ACTIONS_MAP, chordOf, displayChord, type Overrides } from '../shortcuts';
import { THEMES } from '../theme/registry';
import { defineStrings, fmt, pick, type Lang } from '../frame/strings';
import { selectableChatAgents, type ChatAgent } from '../chat-routing-policy';
import { talkStrings } from '../home/talk/strings';
import type { AttentionKey } from '../signals/types';
import {
  ALL_PAGES, AREAS, PAGES, textOf, type PageEntry, type Text,
} from './areas';
import { landingPath, pathOf } from './routes';
import { fold, type Searchable } from './search';

// ---- the words ---------------------------------------------------------------------------------

export const COMMAND_STRINGS = defineStrings({
  en: {
    groupRecent: 'Recent', groupAreas: 'Areas', groupPages: 'Pages', groupPanels: 'Panels',
    groupAgents: 'Agents', groupActions: 'Actions', groupAppearance: 'Display',
    kindArea: 'Area', kindPage: 'Page', kindPanel: 'Panel', kindAgent: 'Agent', kindAction: 'Action',
    openAgent: 'Open {name}', agentOpenHint: 'Opens the dossier, not the conversation',
    agentWriteHint: 'Changes who you write to',
    glance: 'Glance', cinema: 'Cinema', shortcuts: 'Keyboard shortcuts', verifyRecord: 'Verify the record again',
    refresh: 'Refresh live data', demoOn: 'Turn the demo sample on', demoOff: 'Turn the demo sample off',
    personalisation: 'Personalisation…', actionHint: 'Opens a view or re-reads; changes nothing on your behalf',
    displayHint: 'Appearance',
  },
  ro: {
    groupRecent: 'Recente', groupAreas: 'Zone', groupPages: 'Pagini', groupPanels: 'Panouri',
    groupAgents: 'Agenți', groupActions: 'Acțiuni', groupAppearance: 'Afișare',
    kindArea: 'Zonă', kindPage: 'Pagină', kindPanel: 'Panou', kindAgent: 'Agent', kindAction: 'Acțiune',
    openAgent: 'Deschide {name}', agentOpenHint: 'Deschide dosarul, nu conversația',
    agentWriteHint: 'Schimbă destinatarul mesajelor tale',
    glance: 'Dintr-o privire', cinema: 'Cinema', shortcuts: 'Scurtături de tastatură', verifyRecord: 'Verifică din nou registrul',
    refresh: 'Reîmprospătează datele live', demoOn: 'Activează exemplul demo', demoOff: 'Dezactivează exemplul demo',
    personalisation: 'Personalizare…', actionHint: 'Deschide o vedere sau citește din nou; nu face nimic în numele tău',
    displayHint: 'Aspect',
  },
});

// ---- types --------------------------------------------------------------------------------------

export type CommandKind = 'area' | 'page' | 'agent' | 'action';
/** The section a command is listed under when the query is empty. */
export type CommandGroup = 'areas' | 'pages' | 'panels' | 'agents' | 'actions' | 'appearance';

export interface Command {
  /** Unique and stable: 'area:work', 'page:panel:logs', 'agent:open:frigga', 'action:glance',
   *  'appearance:scheme:dark'. Recents are stored by it. */
  readonly id: string;
  readonly kind: CommandKind;
  readonly group: CommandGroup;
  readonly label: Text;
  readonly aliases: readonly string[];
  /** Id words search matches ("decision-inbox"). */
  readonly ids: readonly string[];
  /** Quiet context in both languages: "Trust › The record". */
  readonly hint: Text | null;
  /** The key that already does this, as written for the owner ("Ctrl+K", "G"), when it has one. */
  readonly chord?: string;
  /** The page this opens, when it opens one: lets the contents and the sheet agree. */
  readonly page?: PageEntry;
  /** The signal that feeds a note beside it in the sheet (none yet; kept for the masthead's twin). */
  readonly attention?: AttentionKey;
  readonly run: () => void;
}

/** What the sheet may do beyond navigating. All of it is read-only or a surface. */
export interface SheetActions {
  onGlance(): void;
  onCinema(): void;
  onShortcuts(): void;
  onVerifyRecord(): void;
  onRefresh(): void;
  demo: boolean;
  setDemo(on: boolean): void;
  onPersonalisation(): void;
}

/** The appearance object App hands the sheet as `ui` (the shape the HUD v2 palette took). */
export interface PaletteUi {
  font?: string; setFont?: (id: string) => void;
  look?: string; setLook?: (id: string) => void;
  scheme?: string; setScheme?: (id: string) => void;
  density?: string; setDensity?: (id: string) => void;
  motion?: string; setMotion?: (id: string) => void;
  scanline?: string; setScanline?: (id: string) => void;
  dotgrid?: string; setDotgrid?: (id: string) => void;
}

/** Everything the commands need from App. */
export interface CommandContext {
  lang: Lang;
  navigate: (path: string) => void;
  agents: readonly ChatAgent[];
  onOpenAgent: (id: string) => void;
  onWriteTo: (id: string) => void;
  actions: SheetActions;
  ui: PaletteUi;
  accent: string;
  setAccent: (v: string) => void;
  setLang: (v: string) => void;
  shortcutOverrides: Overrides;
}

// ---- the rule: no verdict is ever a command --------------------------------------------------------

/** Words an action may never carry, beyond FORBIDDEN_TARGET (approve, decide, reject, deny,
 *  accept, consent): the owner's other hands. */
export const FORBIDDEN_ACTION_WORDS = /(?:^|[^a-z])(?:sign|signs|signed|signing|defer|deferred|stop|stops|halt|halted|resume|kill|arm|disarm|mode|modes)(?:[^a-z]|$)/i;

/** The same words in Romanian, tested on folded text (no diacritics, lower case): approve, reject,
 *  sign, stop, defer, refuse, accept, decide, consent, resume, arm and mode. */
export const FORBIDDEN_RO = /(?:^|[^a-z])(?:aprob\w*|respinge\w*|respins\w*|semn\w*|opr\w*|amana\w*|refuz\w*|accept\w*|decid\w*|decizi\w*|consimt\w*|reia|reluare|armeaz\w*|dezarmeaz\w*|mod|moduri|modul)(?:[^a-z]|$)/;

/** Whether an action's id or label names a verdict, a signature, the stop or a mode change. */
export function isForbiddenAction(texts: readonly string[]): boolean {
  return texts.some((t) => FORBIDDEN_TARGET.test(t) || FORBIDDEN_ACTION_WORDS.test(t) || FORBIDDEN_RO.test(fold(t)));
}

/** Validates a command list and returns it. Throws on a duplicate id, and on an *action* (not a
 *  navigation entry) whose id, label or alias matches FORBIDDEN_TARGET or the words above. */
export function defineCommands(commands: Command[]): Command[] {
  const seen = new Set<string>();
  for (const c of commands) {
    if (seen.has(c.id)) throw new Error(`duplicate command: ${c.id}`);
    seen.add(c.id);
    if (c.kind === 'action' && isForbiddenAction([c.id, c.label.en, c.label.ro, ...c.aliases])) {
      throw new Error(`a command may not be an approval, a decision, a signature, the stop or a mode change: ${c.id}`);
    }
  }
  return commands;
}

// ---- recents -------------------------------------------------------------------------------------

export const RECENT_KEY = 'nerva.sheet.recent';
export const RECENT_MAX = 5;

/** The ids of the five most recent commands, newest first (a per-viewer convenience). */
export function readRecent(storage: Storage | undefined = globalThis.localStorage): string[] {
  try {
    const raw = JSON.parse(storage?.getItem(RECENT_KEY) || '[]');
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string').slice(0, RECENT_MAX) : [];
  } catch { return []; }
}

/** Records a command as the most recent. Never throws. */
export function pushRecent(id: string, storage: Storage | undefined = globalThis.localStorage): string[] {
  const next = [id, ...readRecent(storage).filter((x) => x !== id)].slice(0, RECENT_MAX);
  try { storage?.setItem(RECENT_KEY, JSON.stringify(next)); } catch { /* storage off: it lasts this page */ }
  return next;
}

// ---- building the index --------------------------------------------------------------------------------

const SEP = ' › ';
const both = (en: string, ro: string = en): Text => ({ en, ro });

function pageHint(entry: PageEntry): Text | null {
  if (!entry.area) return null;
  const area = AREAS.find((a) => a.id === entry.area);
  if (!area) return null;
  const group = area.groups.find((g) => g.pages.includes(entry));
  const label = group?.label;
  return {
    en: label ? `${area.label.en}${SEP}${label.en}` : area.label.en,
    ro: label ? `${area.label.ro}${SEP}${label.ro}` : area.label.ro,
  };
}

/** A page's Searchable-like fields: the entry's own aliases, plus its old name. */
function pageCommand(entry: PageEntry, ctx: CommandContext): Command {
  const panel = entry.ref.kind === 'panel';
  const ids = entry.ref.kind === 'allPages' ? ['console', 'all-pages'] : [entry.ref.id];
  const chord = entry.ref.kind === 'mode' && entry.landing ? chordFor(`mode.${entry.ref.id}`, ctx) : undefined;
  return {
    id: `page:${entry.key}`,
    kind: 'page',
    group: panel ? 'panels' : 'pages',
    label: entry.label,
    aliases: entry.aliases,
    ids,
    hint: pageHint(entry),
    ...(chord ? { chord } : {}),
    page: entry,
    run: () => ctx.navigate(pathOf(entry.ref)),
  };
}

function chordFor(actionId: string, ctx: CommandContext): string | undefined {
  if (!ACTIONS_MAP.has(actionId)) return undefined;
  const chord = displayChord(chordOf(ctx.shortcutOverrides, actionId));
  return chord || undefined;
}

const FONTS: ReadonlyArray<readonly [string, string]> = [
  ['theme', 'Theme Default'], ['system-sans', 'System Sans'], ['system-serif', 'System Serif'],
  ['system-mono', 'System Mono'], ['jetbrains-mono', 'JetBrains Mono'],
];
const ACCENTS: ReadonlyArray<readonly [string, string]> = [['cyan', 'Cyan'], ['amber', 'Amber'], ['green', 'Green'], ['violet', 'Violet']];
const SCHEMES: ReadonlyArray<readonly [string, string]> = [['dark', 'Dark'], ['light', 'Light'], ['system', 'System']];

/** The appearance rows of the old palette, word for word (a ✓ marks the active choice). */
function appearanceCommands(ctx: CommandContext): Command[] {
  const u = ctx.ui;
  const look = u.look || 'ledger';
  const scheme = u.scheme || 'dark';
  const hint = both(pick(COMMAND_STRINGS, 'en').displayHint, pick(COMMAND_STRINGS, 'ro').displayHint);
  const row = (id: string, name: string, run: () => void): Command => ({
    id: `appearance:${id}`, kind: 'action', group: 'appearance', label: both(name), aliases: [], ids: [], hint, run,
  });
  const out: Command[] = [];
  for (const [id, name] of ACCENTS) out.push(row(`accent-${id}`, `Accent · ${name}`, () => ctx.setAccent(id)));
  for (const l of LANGUAGES) out.push(row(`language-${l.code}`, `Language · ${l.label}${ctx.lang === l.code ? ' ✓' : ''}`, () => ctx.setLang(l.code)));
  for (const [id, name] of FONTS) out.push(row(`font-${id}`, `Font · ${name}${u.font === id ? ' ✓' : ''}`, () => u.setFont?.(id)));
  for (const theme of THEMES.filter((t) => t.family === 'nerva')) {
    out.push(row(`look-${theme.id}`, `Look · ${theme.name.en}${look === theme.id ? ' ✓' : ''}`, () => u.setLook?.(theme.id)));
  }
  out.push(row('look-obsidian', `Look · ${look === 'obsidian' ? 'Obsidian ✓' : 'Obsidian'}`, () => u.setLook?.('obsidian')));
  out.push(row('look-graphite', `Look · ${look === 'graphite' ? 'Graphite ✓' : 'Graphite'}`, () => u.setLook?.('graphite')));
  for (const [id, name] of SCHEMES) out.push(row(`scheme-${id}`, `Scheme · ${name}${scheme === id ? ' ✓' : ''}`, () => u.setScheme?.(id)));
  const density = u.density || 'normal';
  for (const [id, name] of [['compact', 'Compact'], ['normal', 'Normal'], ['comfy', 'Comfy']] as const) {
    out.push(row(`density-${id}`, `Density · ${density === id ? `${name} ✓` : name}`, () => u.setDensity?.(id)));
  }
  const motion = u.motion || 'lively';
  for (const [id, name] of [['system', 'System'], ['lively', 'Lively'], ['calm', 'Calm']] as const) {
    out.push(row(`motion-${id}`, `Motion · ${motion === id ? `${name} ✓` : name}`, () => u.setMotion?.(id)));
  }
  out.push(row('scanline', `Scanline · ${u.scanline === 'off' ? 'On' : 'Off'}`, () => u.setScanline?.(u.scanline === 'off' ? 'on' : 'off')));
  out.push(row('dotgrid', `Dot grid · ${u.dotgrid === 'on' ? 'Off' : 'On'}`, () => u.setDotgrid?.(u.dotgrid === 'on' ? 'off' : 'on')));
  return out;
}

/** Every command the sheet can find, in the order an empty query lists them: areas, pages,
 *  panels, agents, actions, appearance. Throws (defineCommands) if an action names a verdict. */
export function buildCommands(ctx: CommandContext): Command[] {
  const en = pick(COMMAND_STRINGS, 'en');
  const ro = pick(COMMAND_STRINGS, 'ro');
  const list: Command[] = [];

  for (const area of AREAS) {
    const landing = area.landing;
    const chord = landing.ref.kind === 'mode' ? chordFor(`mode.${landing.ref.id}`, ctx) : undefined;
    list.push({
      id: `area:${area.id}`, kind: 'area', group: 'areas', label: area.label, aliases: area.aliases, ids: [area.id],
      hint: null, ...(chord ? { chord } : {}), page: landing, run: () => ctx.navigate(landingPath(area.id)),
    });
  }
  for (const entry of [...PAGES, ALL_PAGES]) list.push(pageCommand(entry, ctx));

  // Write-to is offered only for a recipient App will accept (selectChatAgent's own rule: a live
  // roster row that is not retired or disabled; in the demo App accepts any). Bad rows from the hub
  // (no id, a repeated id, a name that is not text) are skipped, never thrown on.
  const accepted = new Set(selectableChatAgents(ctx.agents.filter((x) => !!x && typeof x === "object"), false).map((x) => x.id));
  const seenAgents = new Set<string>();
  for (const agent of ctx.agents) {
    if (!agent || typeof agent.id !== 'string' || !agent.id || seenAgents.has(agent.id)) continue;
    seenAgents.add(agent.id);
    const id = agent.id;
    const raw = typeof agent.name === 'string' ? agent.name.trim() : '';
    const name = raw || id;
    list.push({
      id: `agent:open:${id}`, kind: 'agent', group: 'agents',
      label: { en: fmt(en.openAgent, { name }), ro: fmt(ro.openAgent, { name }) },
      aliases: [name], ids: [id], hint: both(en.agentOpenHint, ro.agentOpenHint), run: () => ctx.onOpenAgent(id),
    });
    if (agent.enabled !== false && (ctx.actions.demo || accepted.has(id))) {
      list.push({
        id: `agent:write:${id}`, kind: 'agent', group: 'agents',
        // the conversation's own words ("Write to Frigga", "Scrie-i lui Frigga"), as the composer's
        // question and the Dossier say them: one phrase for one act
        label: { en: fmt(talkStrings('en').writeTo, { agent: name }), ro: fmt(talkStrings('ro').writeTo, { agent: name }) },
        aliases: [name, 'message', 'chat', 'mesaj'], ids: [id], hint: both(en.agentWriteHint, ro.agentWriteHint), run: () => ctx.onWriteTo(id),
      });
    }
  }

  const a = ctx.actions;
  const hint = both(en.actionHint, ro.actionHint);
  const action = (id: string, label: Text, run: () => void, more: Partial<Command> = {}): Command =>
    ({ id: `action:${id}`, kind: 'action', group: 'actions', label, aliases: [], ids: [], hint, run, ...more });
  const glanceChord = chordFor('view.ambient', ctx);
  const cinemaChord = chordFor('view.cinema', ctx);
  const shortcutsChord = chordFor('session.shortcuts', ctx);
  list.push(
    action('glance', both(en.glance, ro.glance), a.onGlance, { aliases: ['Ambient', 'Ambiental'], ...(glanceChord ? { chord: glanceChord } : {}) }),
    action('cinema', both(en.cinema, ro.cinema), a.onCinema, { ...(cinemaChord ? { chord: cinemaChord } : {}) }),
    action('shortcuts', both(en.shortcuts, ro.shortcuts), a.onShortcuts, { aliases: ['Hotkeys', 'Keys', 'Taste'], ...(shortcutsChord ? { chord: shortcutsChord } : {}) }),
    action('verify-record', both(en.verifyRecord, ro.verifyRecord), a.onVerifyRecord, { aliases: ['Audit chain', 'Registru'] }),
    action('refresh', both(en.refresh, ro.refresh), a.onRefresh, { aliases: ['Reload', 'Reîncarcă'] }),
    action('demo', a.demo ? both(en.demoOff, ro.demoOff) : both(en.demoOn, ro.demoOn), () => a.setDemo(!a.demo), { aliases: ['Demo sample', 'Exemplu demo'] }),
    action('personalisation', both(en.personalisation, ro.personalisation), a.onPersonalisation, { aliases: ['Personalisation', 'Personalizare', 'Appearance', 'Theme'] }),
  );
  list.push(...appearanceCommands(ctx));
  return defineCommands(list);
}

// ---- what search reads --------------------------------------------------------------------------------------

/** A command's searchable fields: the label in both languages, aliases, ids, hint. */
export function searchableOf(command: Command, lang: Lang): Searchable {
  const other: Lang = lang === 'ro' ? 'en' : 'ro';
  return {
    label: command.label[lang],
    otherLabels: [command.label[other]],
    aliases: command.aliases,
    ids: command.ids.flatMap((id) => [id, id.replace(/[-_]/g, ' ')]),
    ...(command.hint ? { hint: `${command.hint.en} ${command.hint.ro}` } : {}),
  };
}

/** The words that tell a row's kind apart in a result list. */
export function kindWord(command: Command, lang: Lang): string {
  const s = pick(COMMAND_STRINGS, lang);
  if (command.kind === 'area') return s.kindArea;
  if (command.kind === 'agent') return s.kindAgent;
  if (command.kind === 'action') return s.kindAction;
  return command.group === 'panels' ? s.kindPanel : s.kindPage;
}

export const GROUP_ORDER: readonly CommandGroup[] = ['areas', 'pages', 'panels', 'agents', 'actions', 'appearance'];

/** A group's heading. */
export function groupWord(group: CommandGroup, lang: Lang): string {
  const s = pick(COMMAND_STRINGS, lang);
  switch (group) {
    case 'areas': return s.groupAreas;
    case 'pages': return s.groupPages;
    case 'panels': return s.groupPanels;
    case 'agents': return s.groupAgents;
    case 'actions': return s.groupActions;
    default: return s.groupAppearance;
  }
}

/** A command's hint in a language ("" when it has none). */
export function hintOf(command: Command, lang: Lang): string {
  return command.hint ? textOf(command.hint, lang) : '';
}
