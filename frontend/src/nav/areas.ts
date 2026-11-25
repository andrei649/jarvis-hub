/* The navigation registry (PHASE_B_PLAN.md §3.1–3.3, §3.9).

   Nine areas in masthead order. Each has a landing page and groups of pages: modes
   (`/v2/<mode>`) and Console panels (`/v2/console/<id>`). Every HUD_MODES id appears exactly
   once and every CONSOLE_PANELS id resolves to exactly one area (nav/areas.test.ts); a panel
   added later with no entry here lands in its group's default area under "Other pages"
   (nav/placement.ts).

   Labels are display labels in English and Romanian. CONSOLE_PANELS ids and labels stay as
   they are (tests and bookmarks use them): a panel's old label becomes a search alias here
   automatically, and old mode names are written as aliases ("Cockpit", "Interop", "Admin" …).
   `primary: false` puts a page behind the contents column's "N more pages"; at most 12 pages of
   an area are primary. Every string a page or area shows lives in this file, in both languages. */
import { CONSOLE_PANELS, CONSOLE_PANEL_MAP } from '../console-routes';
import { HUD_MODES, type HudMode } from '../hud-modes';
import { defineStrings, fmt, langOf, plural, pick, type Lang } from '../frame/strings';
import type { MarkKind } from '../frame/kit/marks';
import type { AttentionKey, AttentionNote } from '../signals/types';
import { groupDefaultArea } from './placement';

// ---- types -----------------------------------------------------------------------------------

/** The nine areas, in masthead order (also the order of hotkeys 1–9). */
export const AREA_IDS = ['home', 'work', 'agents', 'memory', 'trust', 'build', 'connect', 'observe', 'settings'] as const;
export type AreaId = typeof AREA_IDS[number];

/** A label in both languages. */
export interface Text { readonly en: string; readonly ro: string }

/** What a page opens: a mode (`/v2/<id>`), a Console panel (`/v2/console/<id>`) or the
 *  All pages site map (`/v2/console`). nav/routes.ts `pathOf()` turns it into a path. */
export type PageRef =
  | { readonly kind: 'mode'; readonly id: HudMode }
  | { readonly kind: 'panel'; readonly id: string }
  | { readonly kind: 'allPages' };

/** One page of the registry. */
export interface PageEntry {
  /** Unique: 'mode:<id>', 'panel:<id>' or 'allPages'. */
  readonly key: string;
  readonly ref: PageRef;
  /** The owning area; null only for ALL_PAGES, which belongs to none. */
  readonly area: AreaId | null;
  /** The group id within the area; null for the area's lead pages (its landing and the pages
   *  listed right after it, before the first named group). */
  readonly group: string | null;
  readonly label: Text;
  /** Search aliases: old labels and names (both languages). Search also matches `ref.id`. */
  readonly aliases: readonly string[];
  /** Shown before the contents column's "N more pages". */
  readonly primary: boolean;
  /** The area's landing page (what the masthead link opens). */
  readonly landing: boolean;
  /** Shown in the contents column and on All pages. False for Glance (it has its own button
   *  and key) and for a duplicate (the panel `jobs` duplicates the mode `jobs`). Search finds
   *  every entry. */
  readonly listed: boolean;
  /** A note beside the page in the contents column, fed by signals (§3.9). */
  readonly attention?: AttentionKey;
  /** The same content as another page: both URLs work, the contents column lists the other. */
  readonly duplicateOf?: PageRef;
  /** Why an explicit panel entry may be missing from CONSOLE_PANELS (it then has no page). */
  readonly optional?: string;
  /** Placed by its CONSOLE_PANELS group default, not by the §3.3 table (a newer panel). */
  readonly auto?: boolean;
}

/** A named group of an area's pages; the lead group has no label. */
export interface Group {
  readonly id: string;
  readonly area: AreaId;
  readonly label: Text | null;
  readonly pages: readonly PageEntry[];
}

export interface Area {
  readonly id: AreaId;
  readonly label: Text;
  readonly aliases: readonly string[];
  readonly landing: PageEntry;
  /** In contents order. groups[0] is the lead group (label null): the landing, then the pages
   *  listed right after it. */
  readonly groups: readonly Group[];
  /** Every page of the area in contents order (landing first), listed or not. */
  readonly pages: readonly PageEntry[];
  /** The keys that feed the masthead note, in priority order (Trust: a broken record first,
   *  else payments waiting). */
  readonly attention: readonly AttentionKey[];
}

// ---- the §3.3 table --------------------------------------------------------------------------

type PageSpec = {
  ref: PageRef; en: string; ro: string; aliases?: string[]; primary?: boolean; listed?: boolean;
  attention?: AttentionKey; duplicateOf?: PageRef; optional?: string;
};
type GroupSpec = { id: string; en: string; ro: string; pages: PageSpec[] };
type AreaSpec = { id: AreaId; en: string; ro: string; aliases?: string[]; attention?: AttentionKey[]; landing: PageSpec; lead: PageSpec[]; groups: GroupSpec[] };

const mode = (id: HudMode, en: string, ro: string, more: Partial<PageSpec> = {}): PageSpec => ({ ref: { kind: 'mode', id }, en, ro, ...more });
const panel = (id: string, en: string, ro: string, more: Partial<PageSpec> = {}): PageSpec => ({ ref: { kind: 'panel', id }, en, ro, ...more });
/** Rarely used technical pages: behind "N more pages". */
const MORE = { primary: false };
const OVERVIEW = ['Overview', 'Prezentare generală'] as const;

const SPEC: readonly AreaSpec[] = [
  {
    id: 'home', en: 'Home', ro: 'Acasă', aliases: ['Cockpit', 'Cabină'],
    landing: mode('cockpit', 'Today', 'Azi', { aliases: ['Cockpit', 'Cabină', 'Home', 'Acasă'] }),
    lead: [
      mode('chat', 'Conversation', 'Conversație', { aliases: ['Chat', 'Direct line', 'Linie directă'] }),
      mode('glance', 'Glance', 'Dintr-o privire', { listed: false, aliases: ['Ambient', 'Ambiental'] }),
    ],
    groups: [
      { id: 'day', en: 'Your day', ro: 'Ziua ta', pages: [
        panel('today', 'What Nerva did today', 'Ce a făcut Nerva azi'),
        panel('today-receipt', 'Today’s receipt', 'Chitanța zilei'),
        panel('usage', 'Usage and cost', 'Utilizare și cost'),
        panel('presence-inbox', 'Presence inbox', 'Mesaje de prezență'),
      ] },
      { id: 'around', en: 'Around you', ro: 'În jurul tău', pages: [
        panel('ambient-watch', 'Ambient watch', 'Supraveghere ambientală'),
        panel('house', 'House', 'Casa'),
        panel('camera', 'Camera', 'Cameră'),
      ] },
      { id: 'start', en: 'Start here', ro: 'Începe aici', pages: [
        panel('command-center', 'Command center', 'Centru de comandă', MORE),
        panel('docs', 'Documentation', 'Documentație', MORE),
      ] },
    ],
  },
  {
    id: 'work', en: 'Work', ro: 'Lucru', attention: ['docket'],
    landing: mode('work', OVERVIEW[0], OVERVIEW[1], { aliases: ['Work', 'Lucru', 'Needs you', 'Running now'] }),
    lead: [
      mode('timeline', 'Timeline', 'Cronologie', { aliases: ['Day lanes', 'Culoarele zilei'] }),
      panel('decision-inbox', 'Decisions', 'Decizii', { attention: 'docket', aliases: ['Approvals', 'Aprobări', 'Docket'] }),
    ],
    groups: [
      { id: 'projects', en: 'Projects', ro: 'Proiecte', pages: [
        mode('projects', 'Projects', 'Proiecte'),
        panel('missions', 'Missions', 'Misiuni'),
        panel('mission-canvas', 'Mission canvas', 'Planșa misiunilor', MORE),
        panel('sessions', 'Sessions', 'Sesiuni'),
        panel('transcript', 'Transcript', 'Transcriere', MORE),
      ] },
      { id: 'scheduled', en: 'Scheduled', ro: 'Programate', pages: [
        mode('jobs', 'Scheduled jobs', 'Sarcini programate', { aliases: ['Automations', 'Automatizări', 'Jobs'] }),
        panel('jobs', 'Scheduled jobs', 'Sarcini programate', { listed: false, primary: false, duplicateOf: { kind: 'mode', id: 'jobs' } }),
        panel('schedule', 'Schedule', 'Program'),
        panel('heartbeat', 'Heartbeats', 'Verificări periodice', MORE),
      ] },
      { id: 'autonomy', en: 'Autonomy', ro: 'Autonomie', pages: [
        mode('autonomy', 'Autonomy', 'Autonomie'),
        panel('autonomy-control', 'Autonomy control', 'Controlul autonomiei'),
        panel('escalation', 'Escalation', 'Escaladare', MORE),
        panel('learning', 'Learning', 'Învățare', MORE),
        panel('quickbar', 'Quickbar', 'Bară rapidă', MORE),
        panel('context-meter', 'Context meter', 'Contor de context', MORE),
      ] },
    ],
  },
  {
    id: 'agents', en: 'Agents', ro: 'Agenți',
    landing: mode('agents', 'Roster', 'Echipa', { aliases: ['Agents', 'Agenți'] }),
    lead: [],
    groups: [
      { id: 'homes', en: 'Agent homes', ro: 'Paginile agenților', pages: [
        mode('finance', 'Gecko · Finance', 'Gecko · Finanțe', { aliases: ['Finance', 'Finanțe', 'Gecko'] }),
        mode('health', 'Hercules · Health', 'Hercules · Sănătate', { aliases: ['Health', 'Sănătate', 'Hercules'] }),
        mode('knowledge', 'Vision · Knowledge', 'Vision · Cunoaștere', { aliases: ['Knowledge', 'Cunoaștere', 'Vision'] }),
        mode('family', 'Frigga · Family', 'Frigga · Familie', { aliases: ['Family', 'Familie', 'Frigga'] }),
      ] },
      { id: 'how', en: 'How they work', ro: 'Cum lucrează', pages: [
        panel('agent-autonomy', 'Agent autonomy', 'Autonomia agenților'),
        panel('company-room', 'Company room', 'Sala companiei', MORE),
        panel('sub-agents', 'Sub-agents', 'Subagenți'),
        panel('swarm', 'Swarm', 'Roi', MORE),
        panel('moa-presets', 'Committees', 'Comitete', MORE),
      ] },
      { id: 'shape', en: 'Shape them', ro: 'Modelează-i', pages: [
        panel('prompts', 'Prompts', 'Instrucțiuni'),
        panel('templates', 'Templates', 'Șabloane'),
        panel('agents-arena', 'Agents arena', 'Arena agenților', MORE),
        panel('pets', 'Companions', 'Companioni', MORE),
      ] },
    ],
  },
  {
    id: 'memory', en: 'Memory', ro: 'Memorie',
    landing: mode('memory', OVERVIEW[0], OVERVIEW[1], { aliases: ['Memory', 'Memorie', 'Memory & Knowledge'] }),
    lead: [
      mode('artifacts', 'Saved replies', 'Răspunsuri salvate', { aliases: ['Artifacts', 'Artefacte'] }),
    ],
    groups: [
      { id: 'knows', en: 'What it knows', ro: 'Ce știe', pages: [
        panel('kg', 'Knowledge graph', 'Graful cunoștințelor'),
        panel('long-term-memory', 'Long-term memory', 'Memorie pe termen lung'),
        panel('notes', 'Notes', 'Notițe'),
        panel('note-docs', 'Note documents', 'Documente de notițe', MORE),
        panel('local-docs', 'Local documents', 'Documente locale'),
        panel('vault', 'Vault', 'Seif'),
        panel('data-spaces', 'Data spaces', 'Spații de date', MORE),
      ] },
      { id: 'learns', en: 'How it learns', ro: 'Cum învață', pages: [
        panel('memory-write', 'Write to memory', 'Scrie în memorie'),
        panel('capture', 'Capture', 'Captură'),
        panel('reflection', 'Reflection', 'Reflecție', MORE),
        panel('memory-consolidate', 'Consolidate', 'Consolidare', MORE),
        panel('memory-hygiene', 'Hygiene', 'Igienă', MORE),
      ] },
      { id: 'checks', en: 'Checks', ro: 'Verificări', pages: [
        panel('memory-eval', 'Memory evaluation', 'Evaluarea memoriei', MORE),
        panel('provenance', 'Provenance', 'Proveniență'),
      ] },
    ],
  },
  {
    id: 'trust', en: 'Trust', ro: 'Încredere', attention: ['record', 'payments'],
    landing: mode('trust', OVERVIEW[0], OVERVIEW[1], { aliases: ['Trust', 'Încredere', 'Trust & Governance'] }),
    lead: [],
    groups: [
      { id: 'record', en: 'The record', ro: 'Registrul', pages: [
        panel('audit-anchors', 'Audit anchors', 'Ancore de audit'),
        panel('governance', 'Governance', 'Guvernanță'),
        panel('kernel-metrics', 'Kernel metrics', 'Metricile nucleului', MORE),
      ] },
      { id: 'authority', en: 'Your authority', ro: 'Autoritatea ta', pages: [
        panel('kill-switch', 'Emergency stop', 'Oprire de urgență', { attention: 'killSwitch', aliases: ['Stop all agents', 'Oprește toți agenții', 'Halt'] }),
        panel('payments', 'Payments', 'Plăți', { attention: 'payments' }),
        panel('permissions', 'Permissions', 'Permisiuni'),
        panel('capabilities', 'Capabilities', 'Capabilități'),
        panel('skill-switches', 'Skill switches', 'Comutatoare de abilități', MORE),
      ] },
      { id: 'secrets', en: 'Secrets and access', ro: 'Secrete și acces', pages: [
        panel('secrets', 'Secrets', 'Secrete'),
        panel('pairing', 'Pairing', 'Asociere', MORE),
        panel('trust-ops', 'Trust operations', 'Operațiuni de încredere', MORE),
      ] },
      { id: 'boundary', en: 'Boundary', ro: 'Granița', pages: [
        panel('posture', 'Posture', 'Postură'),
        panel('signal-governance', 'Signal governance', 'Guvernanța semnalelor', MORE),
        panel('network-monitor', 'Network monitor', 'Monitor de rețea'),
        panel('comms-rate', 'Outbound rate', 'Rata de trimitere', MORE),
        panel('safe-comms-draft', 'Safe drafts', 'Ciorne sigure', MORE),
        panel('injection-scan', 'Injection scan', 'Scanare de injecții', MORE),
      ] },
      { id: 'defences', en: 'Defences', ro: 'Apărări', pages: [
        panel('security-skills', 'Security skills', 'Abilități de securitate', MORE),
        panel('security-skills-map', 'Security skills map', 'Harta abilităților de securitate', MORE),
        panel('loop-breaker', 'Loop breaker', 'Întrerupător de bucle', MORE),
        panel('readiness', 'Readiness', 'Pregătire', MORE),
      ] },
    ],
  },
  {
    id: 'build', en: 'Build', ro: 'Construire',
    landing: mode('build', OVERVIEW[0], OVERVIEW[1], { aliases: ['Build', 'Construire', 'Builds'] }),
    lead: [],
    groups: [
      { id: 'create', en: 'Create', ro: 'Creează', pages: [
        panel('images', 'Images', 'Imagini'),
        panel('creative', 'Creative', 'Creație'),
        panel('media-director', 'Media director', 'Regizor media', MORE),
        panel('media-gallery', 'Media gallery', 'Galerie media'),
        panel('publish-readiness', 'Publish readiness', 'Pregătire pentru publicare', MORE),
      ] },
      { id: 'automate', en: 'Automate', ro: 'Automatizează', pages: [
        panel('workflows', 'Workflows', 'Fluxuri de lucru'),
        panel('workflow-builder', 'Workflow builder', 'Constructor de fluxuri'),
        panel('workflow-traces', 'Workflow traces', 'Urmele fluxurilor', MORE),
        panel('operator', 'Operator', 'Operator'),
        panel('browser-broker', 'Browser broker', 'Intermediar de browser', MORE),
        panel('screen-reflex', 'Screen reflex', 'Reflex de ecran', MORE),
        panel('sandbox', 'Sandbox', 'Mediu izolat', MORE),
      ] },
      { id: 'skills', en: 'Skills', ro: 'Abilități', pages: [
        panel('skills-import', 'Import skills', 'Importă abilități'),
        panel('marketplace', 'Marketplace', 'Piață'),
        panel('marketplace-admin', 'Marketplace admin', 'Administrarea pieței', MORE),
        panel('skill-history', 'Skill history', 'Istoricul abilităților', MORE),
        panel('packs', 'Packs', 'Pachete', MORE),
        panel('pending-skills', 'Pending skills', 'Abilități în așteptare'),
      ] },
      { id: 'machine', en: 'This machine', ro: 'Acest calculator', pages: [
        panel('host-readiness', 'Host readiness', 'Pregătirea gazdei', MORE),
        panel('desktop-allowlist', 'Desktop allowlist', 'Lista permisă pe desktop', MORE),
        panel('extensions', 'Extensions', 'Extensii', MORE),
        panel('acquisition', 'Acquisition', 'Achiziție', MORE),
      ] },
    ],
  },
  {
    id: 'connect', en: 'Connect', ro: 'Conexiuni', aliases: ['Interop'],
    landing: mode('interop', OVERVIEW[0], OVERVIEW[1], { aliases: ['Interop', 'Connect', 'Conexiuni'] }),
    lead: [
      mode('comms', 'Inbox', 'Mesaje primite', { aliases: ['Comms', 'Comunicări', 'Unified inbox'] }),
    ],
    groups: [
      { id: 'channels', en: 'Channels', ro: 'Canale', pages: [
        panel('channels-config', 'Channels', 'Canale'),
        panel('rooms', 'Rooms', 'Camere'),
        panel('remote-members', 'Remote members', 'Membri la distanță', MORE),
        panel('integrations', 'Integrations', 'Integrări'),
        panel('o-auth', 'OAuth sign-ins', 'Autentificări OAuth', MORE),
      ] },
      { id: 'elsewhere', en: 'Agents elsewhere', ro: 'Agenți în altă parte', pages: [
        panel('a2-a-inbox', 'A2A inbox', 'Mesaje A2A'),
        panel('mesh-peers', 'Mesh peers', 'Noduri mesh', MORE),
        panel('satellites', 'Satellites', 'Sateliți', MORE),
        panel('device-sync', 'Device sync', 'Sincronizare dispozitive'),
      ] },
      { id: 'tools', en: 'Tools and feeds', ro: 'Unelte și fluxuri', pages: [
        panel('mcp', 'MCP servers', 'Servere MCP'),
        panel('webhooks', 'Webhooks', 'Webhook-uri'),
        panel('hooks', 'Hooks', 'Hook-uri', MORE),
        panel('oracle', 'Oracle', 'Oracol', MORE),
        panel('osint', 'OSINT', 'OSINT', MORE),
        panel('watchlist', 'Watchlist', 'Listă de urmărire', MORE),
        panel('signal-routing', 'Signal routing', 'Rutarea semnalelor', MORE),
        panel('writeback-digest', 'Writeback digest', 'Rezumatul scrierilor externe', MORE),
      ] },
    ],
  },
  {
    id: 'observe', en: 'Observe', ro: 'Observare', attention: ['services'],
    landing: mode('observe', OVERVIEW[0], OVERVIEW[1], { aliases: ['Observe', 'Observă', 'Observability'] }),
    lead: [
      mode('world', 'World signals', 'Semnale din lume', { aliases: ['World', 'World Intelligence', 'Lume'] }),
    ],
    groups: [
      { id: 'health', en: 'Health', ro: 'Stare', pages: [
        panel('system-map', 'System map', 'Harta sistemului'),
        panel('logs', 'Logs', 'Jurnale'),
        panel('apm', 'Performance', 'Performanță'),
        panel('model-info', 'Model info', 'Informații despre model'),
        panel('design-manifest', 'Design manifest', 'Manifestul de design', MORE),
      ] },
      { id: 'quality', en: 'Quality', ro: 'Calitate', pages: [
        panel('eval', 'Evaluation', 'Evaluare'),
        panel('review', 'Review', 'Revizuire', MORE),
        panel('review-quality', 'Review quality', 'Calitatea revizuirilor', MORE),
        panel('arena', 'Arena', 'Arenă', MORE),
        panel('quality', 'Quality', 'Calitate'),
        panel('coach', 'Coach', 'Antrenor', MORE),
        panel('feedback', 'Feedback', 'Feedback', MORE),
      ] },
      { id: 'learning', en: 'Learning', ro: 'Învățare', pages: [
        panel('cognition', 'Cognition', 'Cogniție'),
        panel('self-improvement', 'Self-improvement', 'Autoperfecționare'),
        panel('code-intel', 'Code intelligence', 'Analiza codului', MORE),
        panel('onboarding', 'Onboarding', 'Inițiere', MORE),
      ] },
    ],
  },
  {
    id: 'settings', en: 'Settings', ro: 'Setări', aliases: ['Admin'],
    landing: mode('admin', OVERVIEW[0], OVERVIEW[1], { aliases: ['Admin', 'Settings', 'Setări'] }),
    lead: [
      panel('appearance', 'Personalisation', 'Personalizare', {
        aliases: ['Appearance', 'Aspect', 'Theme', 'Temă'],
        optional: 'Phase A adds this panel (theme contract §8); without it in CONSOLE_PANELS the entry has no page to open.',
      }),
    ],
    groups: [
      { id: 'models', en: 'Models', ro: 'Modele', pages: [
        panel('model-setup', 'Model setup', 'Configurarea modelului'),
        panel('lm-studio', 'LM Studio', 'LM Studio'),
        panel('llm-routing', 'Model routing', 'Rutarea modelelor'),
        panel('custom-endpoints', 'Custom endpoints', 'Puncte de acces personalizate', MORE),
        panel('provider-packages', 'Provider packages', 'Pachete de furnizori', MORE),
        panel('provider-check', 'Provider check', 'Verificarea furnizorilor', MORE),
        panel('provider-quota', 'Provider quota', 'Cota furnizorilor', MORE),
        panel('vlm-describe', 'Image description model', 'Modelul de descriere a imaginilor', MORE),
        panel('auth-profiles', 'Auth profiles', 'Profiluri de autentificare', MORE),
      ] },
      { id: 'system', en: 'System', ro: 'Sistem', pages: [
        panel('settings', 'All settings', 'Toate setările'),
        panel('system-profile', 'System profile', 'Profilul sistemului'),
        panel('restart-update', 'Restart and update', 'Repornire și actualizare'),
        panel('backup', 'Backup', 'Copie de rezervă'),
        panel('files', 'Files', 'Fișiere'),
        panel('inspector', 'Inspector', 'Inspector', MORE),
        panel('support-voice', 'Voice support', 'Asistență vocală', MORE),
      ] },
    ],
  },
];

/** The group a later panel lands in when the table has no entry for it. */
export const OTHER_GROUP_ID = 'other';
const OTHER_GROUP: Text = { en: 'Other pages', ro: 'Alte pagini' };

// ---- building the registry --------------------------------------------------------------------

/** The unique key of a page ref. */
export function pageKey(ref: PageRef): string {
  return ref.kind === 'allPages' ? 'allPages' : `${ref.kind}:${ref.id}`;
}

const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

function entryOf(spec: PageSpec, area: AreaId, group: string | null, landing: boolean, auto = false): PageEntry {
  const aliases = [...(spec.aliases || [])];
  // A panel's CONSOLE_PANELS label is its old name: keep it findable.
  const old = spec.ref.kind === 'panel' ? CONSOLE_PANEL_MAP.get(spec.ref.id)?.label : undefined;
  if (old && !same(old, spec.en) && !aliases.some((a) => same(a, old))) aliases.unshift(old);
  return {
    key: pageKey(spec.ref),
    ref: spec.ref,
    area,
    group,
    label: { en: spec.en, ro: spec.ro },
    aliases,
    primary: landing ? true : spec.primary !== false && spec.listed !== false,
    landing,
    listed: spec.listed !== false,
    ...(spec.attention ? { attention: spec.attention } : {}),
    ...(spec.duplicateOf ? { duplicateOf: spec.duplicateOf } : {}),
    ...(spec.optional ? { optional: spec.optional } : {}),
    ...(auto ? { auto: true } : {}),
  };
}

function build(): { areas: Area[]; pages: PageEntry[] } {
  const explicitPanels = new Set<string>();
  SPEC.forEach((a) => [a.landing, ...a.lead, ...a.groups.flatMap((g) => g.pages)].forEach((p) => {
    if (p.ref.kind === 'panel') explicitPanels.add(p.ref.id);
  }));
  // A panel the table does not place lands in its group's default area, behind "More pages".
  const later = new Map<AreaId, PageEntry[]>();
  CONSOLE_PANELS.forEach((p) => {
    if (explicitPanels.has(p.id)) return;
    const area = groupDefaultArea(p.group);
    const entry = entryOf(panel(p.id, p.label, p.label, MORE), area, OTHER_GROUP_ID, false, true);
    later.set(area, [...(later.get(area) || []), entry]);
  });
  const pages: PageEntry[] = [];
  const areas = SPEC.map((spec): Area => {
    const landing = entryOf(spec.landing, spec.id, null, true);
    const lead: Group = { id: 'lead', area: spec.id, label: null, pages: [landing, ...spec.lead.map((p) => entryOf(p, spec.id, null, false))] };
    const groups: Group[] = [lead, ...spec.groups.map((g): Group => ({
      id: g.id, area: spec.id, label: { en: g.en, ro: g.ro }, pages: g.pages.map((p) => entryOf(p, spec.id, g.id, false)),
    }))];
    const extra = later.get(spec.id);
    if (extra?.length) groups.push({ id: OTHER_GROUP_ID, area: spec.id, label: OTHER_GROUP, pages: extra });
    const areaPages = groups.flatMap((g) => g.pages);
    pages.push(...areaPages);
    return {
      id: spec.id, label: { en: spec.en, ro: spec.ro }, aliases: spec.aliases || [], landing,
      groups, pages: areaPages, attention: spec.attention || [],
    };
  });
  return { areas, pages };
}

const BUILT = build();

/** The nine areas, in masthead order. */
export const AREAS: readonly Area[] = BUILT.areas;
/** Every page of every area (modes and panels, listed or not), in area and contents order. */
export const PAGES: readonly PageEntry[] = BUILT.pages;

/** The `/v2/console` site map: it belongs to no area. */
export const ALL_PAGES: PageEntry = {
  key: 'allPages',
  ref: { kind: 'allPages' },
  area: null,
  group: null,
  label: { en: 'All pages', ro: 'Toate paginile' },
  aliases: ['Console', 'Consolă', 'Site map', 'Harta site-ului'],
  primary: false,
  landing: false,
  listed: false,
};

const AREA_MAP = new Map<AreaId, Area>(AREAS.map((a) => [a.id, a]));
const PAGE_MAP = new Map<string, PageEntry>();
PAGES.forEach((p) => { if (!PAGE_MAP.has(p.key)) PAGE_MAP.set(p.key, p); });
PAGE_MAP.set(ALL_PAGES.key, ALL_PAGES);

export function areaById(id: AreaId | string | null | undefined): Area | null {
  return (id && AREA_MAP.get(id as AreaId)) || null;
}
/** The registry entry for a ref (null for a mode or panel id it does not know). */
export function pageByRef(ref: PageRef): PageEntry | null {
  return PAGE_MAP.get(pageKey(ref)) || null;
}
export function pageForMode(id: string): PageEntry | null {
  return PAGE_MAP.get(`mode:${id}`) || null;
}
export function pageForPanel(id: string): PageEntry | null {
  return PAGE_MAP.get(`panel:${id}`) || null;
}
/** The group an entry sits in (null for ALL_PAGES). */
export function groupOf(entry: PageEntry): Group | null {
  const area = areaById(entry.area);
  return area?.groups.find((g) => g.pages.includes(entry)) || null;
}
/** A label in a language. */
export function textOf(text: Text, lang: Lang | string): string {
  return text[langOf(lang)];
}
/** Every mode id the registry places (a test pins it to HUD_MODES). */
export const PLACED_MODES: readonly string[] = PAGES.filter((p) => p.ref.kind === 'mode').map((p) => (p.ref as { id: string }).id);
/** HUD_MODES, re-exported for the registry's readers. */
export { HUD_MODES };

// ---- attention notes (§3.9): the words, shared by the masthead and the contents column --------

export const ATTENTION_STRINGS = defineStrings({
  en: {
    needYou: { one: '{n} needs you', few: '{n} need you', other: '{n} need you' },
    waits: { one: '{n} waits', few: '{n} wait', other: '{n} wait' },
    servicesDown: { one: '{n} service down', few: '{n} services down', other: '{n} services down' },
    recordBroken: 'record broken',
    recordBrokenAt: 'record broken at entry {n}',
    armed: 'Armed',
    halted: 'Halted',
    unknown: 'Unknown',
  },
  ro: {
    needYou: { one: '{n} te așteaptă', few: '{n} te așteaptă', other: '{n} te așteaptă' },
    waits: { one: '{n} așteaptă', few: '{n} așteaptă', other: '{n} așteaptă' },
    servicesDown: { one: '{n} serviciu oprit', few: '{n} servicii oprite', other: '{n} de servicii oprite' },
    recordBroken: 'registrul este rupt',
    recordBrokenAt: 'registrul este rupt la intrarea {n}',
    armed: 'Armat',
    halted: 'Oprit',
    unknown: 'Necunoscut',
  },
});

/** How a note reads. `long` at ≥ 1680px, `short` below; `mark` is drawn before it (problem
 *  notes); `hand` notes are the owner's hand and take the accent (docket, payments). `short` is
 *  always the first words of `long` ("9" of "9 need you", "record broken" of "record broken at
 *  entry 412", §3.9's "■ record broken"): the masthead link is named with the long note, and the
 *  words it draws at any width must be part of that name (WCAG 2.5.3). */
export interface AttentionWords { readonly long: string; readonly short: string; readonly mark: MarkKind | null; readonly hand: boolean }

export function attentionWords(note: AttentionNote, lang: Lang | string): AttentionWords {
  const s = pick(ATTENTION_STRINGS, lang);
  switch (note.key) {
    case 'docket': return { long: plural(lang, s.needYou, note.count), short: String(note.count), mark: null, hand: true };
    case 'payments': return { long: plural(lang, s.waits, note.count), short: plural(lang, s.waits, note.count), mark: null, hand: true };
    case 'services': return { long: plural(lang, s.servicesDown, note.count), short: String(note.count), mark: 'problem', hand: false };
    case 'record': return {
      long: note.brokenAt === null ? s.recordBroken : fmt(s.recordBrokenAt, { n: note.brokenAt }),
      short: s.recordBroken, mark: 'problem', hand: false,
    };
    case 'killSwitch':
    default: {
      const word = note.state === 'armed' ? s.armed : note.state === 'halted' ? s.halted : s.unknown;
      return { long: word, short: word, mark: note.state === 'halted' ? 'held' : note.state === 'unknown' ? 'unknown' : null, hand: false };
    }
  }
}

/** The note an area shows: the first of its keys that has one (Trust: a broken record, else
 *  payments waiting); null when none has anything honest to say. */
export function areaNote(area: Area, attention: { readonly [K in AttentionKey]?: AttentionNote }): AttentionNote | null {
  for (const key of area.attention) {
    const note = attention[key];
    if (note) return note;
  }
  return null;
}
