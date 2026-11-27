/* The Ctrl K sheet (PHASE_B_PLAN.md §3.7): search and command in one dialog.

   A dialog holding a combobox and a listbox. Arrow keys move, Enter runs, Esc closes and gives the
   focus back to what opened it (Tab stays inside). Matching ignores case and Romanian diacritics.
   With the "Panels:" filter on (the backtick key, or the contents column's "Find a panel") only
   Console panels are listed; Backspace on an empty field, or its close control, lifts the filter.
   With nothing typed it lists the five most recent items, the nine areas and the actions.

   It finds navigation, agents and read-only actions. It can never sign, approve, reject, defer,
   consent, stop or change a mode: see defineCommands() in commands.ts. Running a command records
   it as recent (localStorage['nerva.sheet.recent'], five ids). */
import React, { useEffect, useId, useRef, useState } from 'react';
import type { ChatAgent } from '../chat-routing-policy';
import { defineStrings, plural, fmt, pick, type Lang } from '../frame/strings';
import { chordOf, displayChord, type Overrides } from '../shortcuts';
import {
  GROUP_ORDER, RECENT_MAX, buildCommands, groupWord, hintOf, kindWord, pushRecent, readRecent, searchableOf,
  COMMAND_STRINGS, type Command, type CommandGroup, type PaletteUi, type SheetActions,
} from './commands';
import { fold, rankBy } from './search';
import './sheet.css';

export const SHEET_STRINGS = defineStrings({
  en: {
    title: 'Search or run a command',
    field: 'Search pages, panels, agents and actions',
    placeholder: 'Search or run a command',
    results: 'Results',
    count: { one: '{n} result', few: '{n} results', other: '{n} results' },
    none: 'Nothing matches “{query}”.',
    nonePanels: 'No panel matches “{query}”.',
    scope: 'Panels:',
    scopeOff: 'Remove the Panels filter',
    keyMove: 'move',
    keyRun: 'run',
    keyClose: 'close',
    close: 'Close',
  },
  ro: {
    title: 'Caută sau rulează o comandă',
    field: 'Caută pagini, panouri, agenți și acțiuni',
    placeholder: 'Caută sau rulează o comandă',
    results: 'Rezultate',
    count: { one: '{n} rezultat', few: '{n} rezultate', other: '{n} de rezultate' },
    none: 'Nimic nu se potrivește cu „{query}”.',
    nonePanels: 'Niciun panou nu se potrivește cu „{query}”.',
    scope: 'Panouri:',
    scopeOff: 'Scoate filtrul Panouri',
    keyMove: 'mută',
    keyRun: 'rulează',
    keyClose: 'închide',
    close: 'Închide',
  },
});

export interface CommandSheetProps {
  open: boolean;
  /** 'panels' opens it with the Panels filter on (the backtick key). */
  filter: 'panels' | null;
  /** Esc, a click on the scrim and the close control call it; focus returns to the opener. */
  onClose: () => void;
  lang: Lang;
  navigate: (path: string) => void;
  agents: readonly ChatAgent[];
  /** The Dossier, without changing who the owner writes to. */
  onOpenAgent: (id: string) => void;
  /** App's writeTo: hands the change to the composer's To, which makes it at once, or asks first
   *  while a reply is being written (it would stop it); then focuses [data-composer]. */
  onWriteTo: (id: string) => void;
  actions: SheetActions;
  ui: PaletteUi;
  accent: string;
  setAccent: (v: string) => void;
  setLang: (v: string) => void;
  shortcutOverrides: Overrides;
}

interface Section { readonly key: string; readonly heading: string | null; readonly items: readonly Command[] }

const LIMIT = 60;

/** What the sheet lists: sections of commands, in the order the keyboard walks them. */
export function sheetSections(commands: readonly Command[], query: string, scope: 'panels' | null, recent: readonly string[], lang: Lang): Section[] {
  const pool = scope === 'panels' ? commands.filter((c) => c.group === 'panels') : commands;
  if (query.trim()) {
    const rank = new Map(recent.map((id, i) => [id, RECENT_MAX - i]));
    const found = rankBy(pool, query, (c) => searchableOf(c, lang), { recency: (c) => rank.get(c.id) ?? 0, limit: scope === 'panels' ? undefined : LIMIT });
    // Two entries with one label (Glance the page and Glance the action; a duplicated panel) read
    // as a duplicate: keep the better-ranked one.
    const labels = new Set<string>();
    const items = found.filter((c) => { const k = fold(c.label[lang]); if (labels.has(k)) return false; labels.add(k); return true; });
    return items.length ? [{ key: 'found', heading: null, items }] : [];
  }
  if (scope === 'panels') return [{ key: 'panels', heading: groupWord('panels', lang), items: pool }];
  const byId = new Map(commands.map((c) => [c.id, c]));
  const recents = recent.map((id) => byId.get(id)).filter((c): c is Command => !!c);
  const sections: Section[] = [];
  if (recents.length) sections.push({ key: 'recent', heading: pick(COMMAND_STRINGS, lang).groupRecent, items: recents });
  const showGroups: readonly CommandGroup[] = GROUP_ORDER.filter((g) => g === 'areas' || g === 'actions');
  for (const g of showGroups) {
    const items = commands.filter((c) => c.group === g);
    if (items.length) sections.push({ key: g, heading: groupWord(g, lang), items });
  }
  return sections;
}

function Sheet(props: CommandSheetProps & {
  pendingRestore: React.RefObject<ReturnType<typeof setTimeout> | null>;
  ownerMounted: React.RefObject<boolean>;
}) {
  const { lang, onClose, shortcutOverrides, pendingRestore, ownerMounted } = props;
  const s = pick(SHEET_STRINGS, lang);
  const uid = useId();
  const listId = `${uid}-list`;
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<'panels' | null>(props.filter);
  const [active, setActive] = useState(0);
  const [recent] = useState(() => readRecent());
  const inputRef = useRef<HTMLInputElement>(null);
  const scopeRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const ran = useRef(false);
  if (opener.current === null && typeof document !== 'undefined') opener.current = document.activeElement as HTMLElement | null;

  // Give the focus back to what opened the sheet. After Esc or the scrim, at once; after a command,
  // only if the command did not place the focus itself (Write to does: it focuses the composer;
  // appearance rows, Refresh and the demo toggle do not, and would leave it on <body>).
  useEffect(() => {
    const doc = dialogRef.current?.ownerDocument;
    if (pendingRestore.current !== null) clearTimeout(pendingRestore.current);
    pendingRestore.current = null;
    const back = () => {
      const o = opener.current;
      if (o && o.isConnected && o.ownerDocument === doc && typeof o.focus === 'function') o.focus();
    };
    return () => {
      if (!ownerMounted.current || !doc) return;
      if (!ran.current) { back(); return; }
      pendingRestore.current = setTimeout(() => {
        pendingRestore.current = null;
        if (!ownerMounted.current || typeof document === 'undefined' || document !== doc) return;
        const at = doc.activeElement;
        if (!at || at === doc.body || at === doc.documentElement) back();
      }, 60);
    };
  }, []);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const commands = buildCommands({
    lang, navigate: props.navigate, agents: props.agents, onOpenAgent: props.onOpenAgent, onWriteTo: props.onWriteTo,
    actions: props.actions, ui: props.ui, accent: props.accent, setAccent: props.setAccent, setLang: props.setLang,
    shortcutOverrides,
  });
  const sections = sheetSections(commands, query, scope, recent, lang);
  const flat = sections.flatMap((sec) => sec.items);
  const current = flat.length ? Math.min(active, flat.length - 1) : -1;
  const optionId = (i: number) => `${uid}-opt-${i}`;

  useEffect(() => { setActive(0); }, [query, scope]);
  useEffect(() => {
    const el = current >= 0 ? document.getElementById(optionId(current)) : null;
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  const dismiss = () => onClose();
  const run = (command: Command) => {
    pushRecent(command.id);
    ran.current = true;
    onClose();
    command.run();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    // The sheet is modal: no key reaches the page's own hotkeys behind it.
    e.stopPropagation();
    if ((e.nativeEvent as KeyboardEvent).isComposing) return;   // IME: Esc and Enter belong to the composition
    if (e.key === 'Escape') { e.preventDefault(); dismiss(); return; }
    if (e.key === 'Tab') {
      const stops: HTMLElement[] = [scopeRef.current, inputRef.current, closeRef.current].filter((x): x is HTMLButtonElement | HTMLInputElement => !!x);
      const at = stops.indexOf(document.activeElement as HTMLElement);
      e.preventDefault();
      const next = e.shiftKey ? (at <= 0 ? stops.length - 1 : at - 1) : (at + 1) % stops.length;
      stops[next]?.focus();
      return;
    }
    if (e.target !== inputRef.current) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); if (flat.length) setActive((current + 1) % flat.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); if (flat.length) setActive((current - 1 + flat.length) % flat.length); }
    else if (e.key === 'PageDown') { e.preventDefault(); if (flat.length) setActive(Math.min(flat.length - 1, current + 8)); }
    else if (e.key === 'PageUp') { e.preventDefault(); if (flat.length) setActive(Math.max(0, current - 8)); }
    else if (e.key === 'Enter') { e.preventDefault(); if (current >= 0) run(flat[current]); }
    else if (e.key === 'Backspace' && !query && scope) { e.preventDefault(); setScope(null); }
  };

  let index = -1;
  const find = displayChord(chordOf(shortcutOverrides, 'session.palette'));
  return (
    <div className="n-cmd" data-cmd="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) dismiss(); }}>
      <div
        ref={dialogRef} role="dialog" aria-modal="true" aria-label={s.title} tabIndex={-1} className="n-cmd-sheet" data-cmd="sheet" onKeyDown={onKeyDown}
        onMouseDown={(e) => {
          // A click on a part that cannot take focus (the foot, a heading) must not drop it to <body>.
          const t = e.target as HTMLElement;
          if (!t.closest('button, input, a')) { e.preventDefault(); inputRef.current?.focus(); }
        }}
      >
        <div className="n-cmd-bar">
          {scope === 'panels' && (
            <button ref={scopeRef} type="button" className="n-tag n-cmd-scope" data-cmd="scope" aria-label={s.scopeOff} title={s.scopeOff}
              onClick={() => { setScope(null); inputRef.current?.focus(); }}>
              {s.scope}<span aria-hidden="true"> ✕</span>
            </button>
          )}
          <input
            ref={inputRef} type="text" role="combobox" className="n-field n-cmd-input" data-cmd="input"
            aria-label={s.field} aria-autocomplete="list" aria-expanded={flat.length > 0} aria-controls={listId}
            aria-activedescendant={current >= 0 ? optionId(current) : undefined}
            placeholder={s.placeholder} value={query} autoComplete="off" spellCheck={false}
            onChange={(e) => setQuery(e.target.value)}
          />
          {find && <kbd className="n-kbd n-cmd-chord" aria-hidden="true">{find}</kbd>}
          <button ref={closeRef} type="button" className="n-btn n-btn--sm n-cmd-close" data-cmd="close" aria-label={s.close} title={s.close} onClick={dismiss}>
            <span aria-hidden="true">✕</span>
          </button>
        </div>
        <div id={listId} ref={listRef} role="listbox" aria-label={s.results} className="n-cmd-list" data-cmd="list" hidden={flat.length === 0}>
          {sections.map((sec) => {
            const rows = sec.items.map((c) => {
              index += 1;
              const i = index;
              const chosen = i === current;
              const hint = hintOf(c, lang);
              return (
                <div
                  key={c.id} id={optionId(i)} role="option" aria-selected={chosen} data-command={c.id} data-kind={c.kind}
                  className="n-cmd-item" data-active={chosen ? 'true' : undefined}
                  onMouseMove={() => { if (!chosen) setActive(i); }} onClick={() => run(c)}
                >
                  <span className="n-cmd-label">{c.label[lang]}</span>
                  {hint && <span className="n-cmd-hint">{hint}</span>}
                  <span className="n-cmd-kind">{kindWord(c, lang)}</span>
                  {c.chord && <kbd className="n-kbd n-cmd-chord" aria-hidden="true">{c.chord}</kbd>}
                </div>
              );
            });
            if (!sec.heading) return <React.Fragment key={sec.key}>{rows}</React.Fragment>;
            const headId = `${uid}-h-${sec.key}`;
            return (
              <div key={sec.key} role="group" aria-labelledby={headId} className="n-cmd-group">
                <div id={headId} className="n-cmd-group-head">{sec.heading}</div>
                {rows}
              </div>
            );
          })}
        </div>
        {flat.length === 0 && (
          <p className="n-cmd-none" data-cmd="none">
            {fmt(scope === 'panels' ? s.nonePanels : s.none, { query: query.trim() })}
          </p>
        )}
        <div className="n-cmd-foot">
          <span role="status" aria-live="polite" className="n-cmd-count">{query.trim() || scope ? plural(lang, s.count, flat.length) : ''}</span>
          <span className="n-cmd-keys" aria-hidden="true">
            <span><kbd className="n-kbd">↑↓</kbd> {s.keyMove}</span>
            <span><kbd className="n-kbd">↵</kbd> {s.keyRun}</span>
            <span><kbd className="n-kbd">Esc</kbd> {s.keyClose}</span>
          </span>
        </div>
      </div>
    </div>
  );
}

/** The sheet. Mounted only while open, so every opening starts clean (empty field, the filter it
 *  was opened with, fresh recents). */
export function CommandSheet(props: CommandSheetProps): React.JSX.Element | null {
  const pendingRestore = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ownerMounted = useRef(true);
  useEffect(() => {
    ownerMounted.current = true;
    return () => {
      ownerMounted.current = false;
      if (pendingRestore.current !== null) clearTimeout(pendingRestore.current);
    };
  }, []);
  if (!props.open) return null;
  return <Sheet {...props} pendingRestore={pendingRestore} ownerMounted={ownerMounted} key={props.filter ?? 'all'} />;
}
