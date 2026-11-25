/* Settings → Personalisation — theme contract v1, §8 (src/theme/CONTRACT.md).

   One page for every appearance choice, in the contract's order: the theme (a card per
   registry entry, each holding a live miniature of the Ledger home drawn in that theme), the
   colour scheme, density, motion, typeface, language and, only while a Classic theme is in
   use, the accent. Every control applies at once through setPreference and shows the sync
   state, exactly like a palette edit.

   Appearance is read and written only through useAppearanceContext(): App owns the one
   useAppearance() instance. Outside the provider this page renders a read-only notice and
   never starts a second writer, because two writers would race on one synced document.

   A preview is a `.n-theme-scope` carrying data-look and data-scheme. Theme files declare
   their roles on that selector as well as on :root, so inside it the same --n-* names
   resolve to the previewed theme whatever the page theme is. A Classic preview also carries
   data-accent, the owner's Classic accent, so it shows the accent chosen on this page whatever
   theme is in use (bridge.css restates that accent on the scope; contract §6). All styling
   lives in appearance.css and comes from --n-* roles only: this file holds no colour and no
   inline style. */
import React, { useId, useState, useSyncExternalStore, type ReactNode } from 'react';
import { LANGUAGES } from '../data';
import { useAppearanceContext, type AppearanceApi } from '../theme/appearance-context';
import { readPrefersDark, subscribePrefersDark } from '../theme/apply';
import {
  DEFAULT_SCHEME_PREFERENCE, SCHEME_PREFERENCES, THEMES, resolveScheme, themeById,
  type Scheme, type SchemePreference, type ThemeId, type ThemeInfo,
} from '../theme/registry';
import './appearance.css';

type Lang = 'en' | 'ro';
type SyncState = 'loading' | 'local' | 'synced' | 'saving' | 'unsynced';

/* The values each field accepts (appearance.ts and the server's OPTIONS), in display order. */
const DENSITIES = ['normal', 'compact', 'comfy'] as const;
const MOTIONS = ['system', 'calm', 'lively'] as const;
const FONTS = ['theme', 'system-sans', 'system-serif', 'system-mono', 'jetbrains-mono'] as const;
const ACCENTS = ['cyan', 'amber', 'green', 'violet'] as const;
/** appearance.ts's default: the accent Classic shows when none is stored. */
const DEFAULT_ACCENT: Accent = 'cyan';
const SYNC_STATES: readonly SyncState[] = ['loading', 'local', 'synced', 'saving', 'unsynced'];

type Density = typeof DENSITIES[number];
type Motion = typeof MOTIONS[number];
type Font = typeof FONTS[number];
type Accent = typeof ACCENTS[number];

interface Copy {
  intro: string;
  outside: string;
  title: { theme: string; scheme: string; density: string; motion: string; font: string; lang: string; accent: string };
  hint: { theme: string; density: string; motion: string; font: string; lang: string; accent: string };
  inUse: string;
  /** The schemes a theme designs, as its card says them. */
  schemes: { dark: string; light: string; darkLight: string; lightDark: string };
  scheme: Record<SchemePreference, string>;
  /** A scheme inside a sentence. */
  schemeWord: Record<Scheme, string>;
  classicDarkOnly: string;
  oneScheme: (theme: string) => string;
  /** Added to the reason while the stored scheme is one the theme in use cannot show. */
  schemeKept: (scheme: string) => string;
  systemNow: (scheme: string) => string;
  systemUnread: (scheme: string) => string;
  density: Record<Density, string>;
  motion: Record<Motion, string>;
  motionNow: { calm: string; lively: string };
  font: Record<Font, string>;
  accent: Record<Accent, string>;
  status: Record<SyncState, string> & { retry: string };
  mark: Record<Exclude<SyncState, 'loading'>, string>;
  /** appearance.ts reports sync failures in English; their translation, keyed by the exact text. */
  errors: Record<string, string>;
  /** Words inside the theme previews (decorative: the previews are hidden from assistive tech). */
  mini: {
    home: string; work: string; agents: string; awaiting: string; entry1: string; entry2: string;
    sign: string; open: string; reply: string; live: string;
  };
}

const COPY: Record<Lang, Copy> = {
  en: {
    intro: 'Choose how Nerva looks. Each change applies at once and syncs to your hub.',
    outside: 'Appearance is available inside the HUD.',
    title: {
      theme: 'Theme', scheme: 'Colour scheme', density: 'Density', motion: 'Motion',
      font: 'Typeface', lang: 'Language', accent: 'Accent',
    },
    hint: {
      theme: 'Every screen takes the theme’s colours, typefaces and shapes. Layout, words and behaviour stay the same.',
      density: 'How much room rows and controls get.',
      motion: 'Calm keeps movement to a minimum.',
      font: 'Theme default keeps the faces each theme was designed with.',
      lang: 'The language of the HUD’s own words.',
      accent: 'The one colour of the Classic themes.',
    },
    inUse: 'In use',
    schemes: { dark: 'Dark only', light: 'Light only', darkLight: 'Dark and light', lightDark: 'Light and dark' },
    scheme: { dark: 'Dark', light: 'Light', system: 'Same as system' },
    schemeWord: { dark: 'dark', light: 'light' },
    classicDarkOnly: 'Classic themes are dark only, so they always show dark.',
    oneScheme: (theme) => `${theme} is designed in one scheme only.`,
    schemeKept: (scheme) => `The ${scheme} scheme stays your choice for the themes that have it.`,
    systemNow: (scheme) => `Now ${scheme}, as your system asks.`,
    systemUnread: (scheme) => `Your system’s choice cannot be read here, so this theme shows ${scheme}.`,
    density: { normal: 'Normal', compact: 'Compact', comfy: 'Comfortable' },
    motion: { system: 'Same as system', calm: 'Calm', lively: 'Lively' },
    motionNow: {
      calm: 'Calm now: your system asks for reduced motion.',
      lively: 'Lively now: your system does not ask for reduced motion.',
    },
    font: {
      theme: 'Theme default', 'system-sans': 'System sans', 'system-serif': 'System serif',
      'system-mono': 'System mono', 'jetbrains-mono': 'JetBrains Mono',
    },
    accent: { cyan: 'Cyan', amber: 'Amber', green: 'Green', violet: 'Violet' },
    status: {
      loading: 'Reading your saved choices…',
      local: 'Using this browser’s choices. Nothing is saved on your hub yet.',
      synced: 'Saved and synced to your hub.',
      saving: 'Saving…',
      unsynced: 'Not synced yet. Your changes are kept on this browser.',
      retry: 'Sync again',
    },
    mark: { local: 'Kept on this browser', synced: 'Saved', saving: 'Saving…', unsynced: 'Not synced' },
    errors: {},
    mini: {
      home: 'Home', work: 'Work', agents: 'Agents', awaiting: 'await your signature',
      entry1: 'Sweep €4,200 to savings', entry2: 'Draft a reply with the agenda',
      sign: 'Sign', open: 'Open', reply: 'Good morning. Three projects are due this week.',
      live: 'Live · checked 10:50',
    },
  },
  ro: {
    intro: 'Alege cum arată Nerva. Fiecare schimbare se aplică imediat și se sincronizează cu hubul.',
    outside: 'Aspectul se poate schimba din HUD.',
    title: {
      theme: 'Temă', scheme: 'Schemă de culori', density: 'Densitate', motion: 'Mișcare',
      font: 'Font', lang: 'Limbă', accent: 'Accent',
    },
    hint: {
      theme: 'Fiecare ecran preia culorile, fonturile și formele temei. Așezarea, textele și comportamentul rămân la fel.',
      density: 'Cât spațiu primesc rândurile și controalele.',
      motion: 'Mișcarea calmă reduce animațiile la minimum.',
      font: 'Fontul temei păstrează fonturile cu care a fost desenată fiecare temă.',
      lang: 'Limba în care îți vorbește HUD-ul.',
      accent: 'Singura culoare a temelor clasice.',
    },
    inUse: 'Activă',
    schemes: {
      dark: 'Doar întunecată', light: 'Doar luminoasă',
      darkLight: 'Întunecată și luminoasă', lightDark: 'Luminoasă și întunecată',
    },
    scheme: { dark: 'Întunecată', light: 'Luminoasă', system: 'La fel ca sistemul' },
    schemeWord: { dark: 'întunecată', light: 'luminoasă' },
    classicDarkOnly: 'Temele clasice sunt doar întunecate, așa că apar mereu întunecate.',
    oneScheme: (theme) => `${theme} are o singură schemă de culori.`,
    schemeKept: (scheme) => `Schema ${scheme} rămâne alegerea ta pentru temele care o au.`,
    systemNow: (scheme) => `Acum ${scheme}, cum cere sistemul.`,
    systemUnread: (scheme) => `Alegerea sistemului nu poate fi citită aici, așa că tema apare ${scheme}.`,
    density: { normal: 'Normală', compact: 'Compactă', comfy: 'Confortabilă' },
    motion: { system: 'La fel ca sistemul', calm: 'Calmă', lively: 'Vie' },
    motionNow: {
      calm: 'Calmă acum: sistemul cere mișcare redusă.',
      lively: 'Vie acum: sistemul nu cere mișcare redusă.',
    },
    font: {
      theme: 'Fontul temei', 'system-sans': 'Sans de sistem', 'system-serif': 'Serif de sistem',
      'system-mono': 'Mono de sistem', 'jetbrains-mono': 'JetBrains Mono',
    },
    accent: { cyan: 'Cyan', amber: 'Chihlimbar', green: 'Verde', violet: 'Violet' },
    status: {
      loading: 'Se citesc alegerile salvate…',
      local: 'Se folosesc alegerile din acest browser. Pe hub nu e salvat încă nimic.',
      synced: 'Salvat și sincronizat cu hubul.',
      saving: 'Se salvează…',
      unsynced: 'Încă nesincronizat. Schimbările rămân în acest browser.',
      retry: 'Sincronizează din nou',
    },
    mark: { local: 'Păstrat în acest browser', synced: 'Salvat', saving: 'Se salvează…', unsynced: 'Nesincronizat' },
    errors: {
      'Appearance saved on this browser only. Sync failed.':
        'Aspectul e salvat doar în acest browser. Sincronizarea a eșuat.',
      'Appearance is using this browser’s saved choices. Server unavailable.':
        'Aspectul folosește alegerile salvate în acest browser. Serverul nu răspunde.',
    },
    mini: {
      home: 'Acasă', work: 'Lucru', agents: 'Agenți', awaiting: 'așteaptă semnătura ta',
      entry1: 'Mută 4.200 € în economii', entry2: 'Ciornă de răspuns cu agenda',
      sign: 'Semnează', open: 'Deschide', reply: 'Bună dimineața. Trei proiecte au termen săptămâna aceasta.',
      live: 'În direct · verificat la 10:50',
    },
  },
};

const asLang = (value: unknown): Lang => (value === 'ro' ? 'ro' : 'en');
const asSchemePreference = (value: unknown): SchemePreference =>
  (SCHEME_PREFERENCES as readonly unknown[]).includes(value) ? (value as SchemePreference) : DEFAULT_SCHEME_PREFERENCE;
const asSyncState = (value: unknown): SyncState | null =>
  (SYNC_STATES as readonly unknown[]).includes(value) ? (value as SyncState) : null;
const asAccent = (value: unknown): Accent =>
  (ACCENTS as readonly unknown[]).includes(value) ? (value as Accent) : DEFAULT_ACCENT;

/** Nerva themes first, then Classic, each in registry order. */
const ORDERED_THEMES: readonly ThemeInfo[] = [
  ...THEMES.filter((theme) => theme.family === 'nerva'),
  ...THEMES.filter((theme) => theme.family === 'classic'),
];

function schemesLabel(theme: ThemeInfo, t: Copy): string {
  const [first, second] = theme.schemes;
  if (!second) return t.schemes[first];
  return first === 'light' ? t.schemes.lightDark : t.schemes.darkLight;
}

const followPrefersDark = (changed: () => void) => subscribePrefersDark(() => changed());

/** The OS colour scheme, followed live and read exactly as theme/apply.ts reads it for the page
    (true dark, false light, null when it cannot be read, and resolveScheme() then falls back to
    each theme's own default), so a preview never resolves `system` differently from the page. */
function usePrefersDark(): boolean | null {
  return useSyncExternalStore(followPrefersDark, readPrefersDark, () => null);
}

function Check() {
  return (
    <svg className="ap-check" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2.5 6.5 5 9l4.5-6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Ledger's risk glyph: three bars, as many filled as the tier. */
function Risk({ level }: { level: number }) {
  return (
    <span className="ap-mini-risk">
      {[0, 1, 2].map((bar) => <span key={bar} className={bar < level ? 'is-on' : undefined} />)}
    </span>
  );
}

/** A miniature of the Ledger home: the masthead with the current area and the stop, a register
    opened by its rule with two docket rows (one awaiting the owner's signature), a reply in the
    reading face and the running foot. Drawn only from --n-* roles, so the enclosing
    .n-theme-scope paints it in the previewed theme: the current area in the emphasis ink, the
    stop as a solid stop fill, the signature on the accent (in Ledger, the seal). It draws no
    other primary action; one added later takes --n-primary / --n-on-primary. */
function Miniature({ t }: { t: Copy['mini'] }) {
  return (
    <>
      <span className="ap-mini-mast">
        <span className="ap-mini-ring" />
        <span className="ap-mini-brand">Nerva</span>
        <span className="ap-mini-nav is-on">{t.home}</span>
        <span className="ap-mini-nav">{t.work}</span>
        <span className="ap-mini-nav">{t.agents}</span>
        <span className="ap-mini-stop" />
      </span>
      <span className="ap-mini-body">
        <span className="ap-mini-reg">
          <span className="ap-mini-reg-head"><span className="ap-mini-fig">2</span>{t.awaiting}</span>
          <span className="ap-mini-row">
            <Risk level={3} />
            <span className="ap-mini-entry">{t.entry1}</span>
            <span className="ap-mini-sign"><span className="ap-mini-seal" />{t.sign}</span>
          </span>
          <span className="ap-mini-row">
            <Risk level={1} />
            <span className="ap-mini-entry">{t.entry2}</span>
            <span className="ap-mini-open">{t.open}</span>
          </span>
        </span>
        <span className="ap-mini-reply"><span className="ap-mini-who">Jarvis</span>{t.reply}</span>
      </span>
      <span className="ap-mini-foot"><span className="ap-mini-dot" />{t.live}</span>
    </>
  );
}

/** One theme: a toggle button named by the theme, described by its tagline and schemes. The
    whole card is the button; the preview inside it is decorative and hidden from assistive tech.
    A Classic preview carries the owner's accent, so it shows the Classic they would get.
    The tagline, the schemes and "In use" are drawn inside the button but read through its
    description and aria-pressed, not as its name: they are hidden from assistive tech, so the
    name the button takes from its content is the theme's name alone, which is also the card's
    title, the words a speech user would say (WCAG 2.5.3). No aria-labelledby: an explicit name
    makes axe compare it with EVERY word drawn in the card, the preview's and the tagline's
    included, and it never matched (label-content-name-mismatch in the e2e lane).
    aria-describedby still reads the hidden tagline and schemes. */
function ThemeCard({ theme, lang, t, active, scheme, accent, onChoose }: {
  theme: ThemeInfo; lang: Lang; t: Copy; active: boolean; scheme: Scheme; accent: Accent;
  onChoose: (id: ThemeId) => void;
}) {
  const id = useId();
  const taglineId = `${id}-tagline`;
  const schemesId = `${id}-schemes`;
  return (
    <button
      type="button"
      className="ap-card"
      aria-pressed={active}
      aria-describedby={`${taglineId} ${schemesId}`}
      onClick={() => onChoose(theme.id)}
    >
      <span className="ap-frame">
        <span
          className="n-theme-scope ap-mini"
          data-look={theme.id}
          data-scheme={scheme}
          data-accent={theme.family === 'classic' ? accent : undefined}
          aria-hidden="true"
        >
          <Miniature t={t.mini} />
        </span>
      </span>
      <span className="ap-card-text">
        <span className="ap-card-head">
          <span className="ap-card-name">{theme.name[lang]}</span>
          {active ? <span className="ap-card-inuse" aria-hidden="true"><Check />{t.inUse}</span> : null}
        </span>
        <span id={taglineId} className="ap-card-tagline" aria-hidden="true">{theme.tagline[lang]}</span>
        <span id={schemesId} className="ap-card-meta" aria-hidden="true">{schemesLabel(theme, t)}</span>
      </span>
    </button>
  );
}

interface ChoiceOption { value: string; label: string; unavailable?: boolean; lang?: string }

/** A titled radio group: native radios (arrow keys move and choose), drawn as a row of words
    where the chosen one is inked and underlined. `hint` explains the setting, `note` says what
    it resolves to now, `reason` says why an option is unavailable.

    An unavailable option is a disabled radio, except while it is the stored choice: a radio is
    never both checked and disabled. A browser that tabs only to a group's checked radio (or to
    any when none is checked) drops such a group from the Tab order; one that falls back to an
    unchecked neighbour (Chromium 149 does) hides the stored choice from the keyboard. So the
    stored-but-unavailable option stays checked and focusable, says it is unavailable with
    aria-disabled and ignores changes. */
function Choice({ title, value, options, onChange, hint, note, reason, mark }: {
  title: string; value: string; options: readonly ChoiceOption[]; onChange: (value: string) => void;
  hint?: string | null; note?: string | null; reason?: string | null; mark?: ReactNode;
}) {
  const id = useId();
  const titleId = `${id}-title`;
  const hintId = `${id}-hint`;
  const noteId = `${id}-note`;
  const reasonId = `${id}-reason`;
  const described = [hint && hintId, note && noteId, reason && reasonId].filter(Boolean).join(' ') || undefined;
  return (
    <div className="ap-section">
      <div className="ap-section-head">
        <h3 id={titleId} className="ap-section-title">{title}</h3>
        {mark}
      </div>
      {hint ? <p id={hintId} className="ap-hint">{hint}</p> : null}
      <div role="radiogroup" aria-labelledby={titleId} aria-describedby={described} className="ap-seg">
        {options.map((option) => {
          const checked = option.value === value;
          const unavailable = !!option.unavailable;
          return (
            <label key={option.value} className="ap-opt">
              <input
                type="radio"
                name={`${id}-value`}
                value={option.value}
                checked={checked}
                disabled={unavailable && !checked}
                aria-disabled={unavailable && checked ? true : undefined}
                aria-describedby={unavailable && reason ? reasonId : undefined}
                onChange={() => { if (!unavailable) onChange(option.value); }}
              />
              <span className="ap-opt-text" lang={option.lang}>{option.label}</span>
            </label>
          );
        })}
      </div>
      {note ? <p id={noteId} className="ap-hint">{note}</p> : null}
      {reason ? <p id={reasonId} className="ap-hint ap-reason">{reason}</p> : null}
    </div>
  );
}

/** Beside the setting changed last: the sync state as a mark and a word (the page's status
    line below the intro is the announced one, so this copy is hidden from assistive tech). */
function SyncMark({ state, t }: { state: SyncState | null; t: Copy }) {
  if (!state || state === 'loading') return null;
  return <span className="ap-mark" data-state={state} aria-hidden="true"><span className="ap-dot" />{t.mark[state]}</span>;
}

/** The page's sync line: what happened to the last change, the failure in words, and a retry. */
function SyncStatus({ api, t }: { api: AppearanceApi; t: Copy }) {
  const state = asSyncState(api.status);
  if (!state) return null;
  const text = state === 'unsynced'
    ? (api.error ? t.errors[api.error] ?? api.error : t.status.unsynced)
    : t.status[state];
  return (
    <div className="ap-status" data-state={state}>
      <span className="ap-dot" aria-hidden="true" />
      <span role="status" className="ap-status-text">{text}</span>
      {state === 'unsynced'
        ? <button type="button" className="ap-btn" onClick={() => api.retry()}>{t.status.retry}</button>
        : null}
    </div>
  );
}

function Personalisation({ api }: { api: AppearanceApi }) {
  const uid = useId();
  const prefersDark = usePrefersDark();
  const [lastKey, setLastKey] = useState<string | null>(null);
  const preferences = api.preferences || {};
  const lang = asLang(preferences.lang);
  const t = COPY[lang];
  const active = themeById(preferences.look);
  const classic = active.family === 'classic';
  const schemePreference = asSchemePreference(preferences.scheme);
  const accent = asAccent(preferences.accent);
  const state = asSyncState(api.status);

  const choose = (key: string, value: string) => {
    if (preferences[key] === value) return;
    setLastKey(key);
    api.setPreference(key, value);
  };
  const mark = (key: string) => (lastKey === key ? <SyncMark state={state} t={t} /> : null);

  const unsupported = (['dark', 'light'] as const).filter((scheme) => !active.schemes.includes(scheme));
  /* the stored scheme when the theme in use cannot show it: it stays checked and saved */
  const keptScheme = unsupported.find((scheme) => scheme === schemePreference);
  const schemeReason = unsupported.length
    ? [classic ? t.classicDarkOnly : t.oneScheme(active.name[lang]), keptScheme ? t.schemeKept(t.schemeWord[keptScheme]) : '']
      .filter(Boolean).join(' ')
    : null;
  const systemScheme = resolveScheme(active, 'system', prefersDark);
  const schemeNote = !schemeReason && schemePreference === 'system'
    ? (prefersDark === null ? t.systemUnread : t.systemNow)(t.schemeWord[systemScheme])
    : null;
  const motionNote = preferences.motion === 'system'
    ? (api.motion === 'calm' ? t.motionNow.calm : t.motionNow.lively)
    : null;

  const themeTitleId = `${uid}-theme`;
  const themeHintId = `${uid}-theme-hint`;
  return (
    <div className="ap-panel">
      <p className="ap-intro">{t.intro}</p>
      <SyncStatus api={api} t={t} />

      <div className="ap-section">
        <div className="ap-section-head">
          <h3 id={themeTitleId} className="ap-section-title">{t.title.theme}</h3>
          {mark('look')}
        </div>
        <p id={themeHintId} className="ap-hint">{t.hint.theme}</p>
        <ul role="list" className="ap-themes" aria-labelledby={themeTitleId} aria-describedby={themeHintId}>
          {ORDERED_THEMES.map((theme) => (
            <li key={theme.id}>
              <ThemeCard
                theme={theme}
                lang={lang}
                t={t}
                active={theme.id === active.id}
                scheme={resolveScheme(theme, schemePreference, prefersDark)}
                accent={accent}
                onChoose={(id) => choose('look', id)}
              />
            </li>
          ))}
        </ul>
      </div>

      <Choice
        title={t.title.scheme}
        value={schemePreference}
        options={SCHEME_PREFERENCES.map((value) => ({
          value, label: t.scheme[value], unavailable: value !== 'system' && !active.schemes.includes(value),
        }))}
        note={schemeNote}
        reason={schemeReason}
        mark={mark('scheme')}
        onChange={(value) => choose('scheme', value)}
      />
      <Choice
        title={t.title.density}
        hint={t.hint.density}
        value={preferences.density ?? ''}
        options={DENSITIES.map((value) => ({ value, label: t.density[value] }))}
        mark={mark('density')}
        onChange={(value) => choose('density', value)}
      />
      <Choice
        title={t.title.motion}
        hint={t.hint.motion}
        value={preferences.motion ?? ''}
        options={MOTIONS.map((value) => ({ value, label: t.motion[value] }))}
        note={motionNote}
        mark={mark('motion')}
        onChange={(value) => choose('motion', value)}
      />
      <Choice
        title={t.title.font}
        hint={t.hint.font}
        value={preferences.font ?? ''}
        options={FONTS.map((value) => ({ value, label: t.font[value] }))}
        mark={mark('font')}
        onChange={(value) => choose('font', value)}
      />
      <Choice
        title={t.title.lang}
        hint={t.hint.lang}
        value={preferences.lang ?? ''}
        options={LANGUAGES.map((language) => ({ value: language.code, label: language.label, lang: language.code }))}
        mark={mark('lang')}
        onChange={(value) => choose('lang', value)}
      />
      {classic ? (
        <Choice
          title={t.title.accent}
          hint={t.hint.accent}
          value={accent}
          options={ACCENTS.map((value) => ({ value, label: t.accent[value] }))}
          mark={mark('accent')}
          onChange={(value) => choose('accent', value)}
        />
      ) : null}
    </div>
  );
}

/** Outside the HUD's AppearanceProvider there is no owner instance to write through. */
function OutsideNotice() {
  const docLang = typeof document !== 'undefined' ? String(document.documentElement.lang || '') : '';
  const t = COPY[asLang(docLang.slice(0, 2).toLowerCase())];
  return (
    <div className="ap-panel">
      <p className="ap-hint">{t.outside}</p>
    </div>
  );
}

/** Console panel `appearance` — Personalisation / Personalizare. */
export function AppearancePanel() {
  const api = useAppearanceContext();
  return api ? <Personalisation api={api} /> : <OutsideNotice />;
}
