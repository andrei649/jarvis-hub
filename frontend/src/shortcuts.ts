/* H209 — one registry for the HUD's keyboard shortcuts.

   Every shortcut the HUD answers is an action here (id, category, label, default chord,
   scope); app.tsx and the cinema overlay dispatch through `matchAction` instead of their
   own literal key maps, and the Keyboard Shortcuts panel (mod+/) lists, searches and
   rebinds them. An owner's rebinding is a per-viewer convenience kept in localStorage.

   Governance: no chord may reach an approval or a decision. An action whose id, category
   or label names one is refused when the registry is built, so a key can never approve,
   reject or decide anything — those stay a deliberate click on the card. */

export type Scope = 'global' | 'cinema';
export type Category = 'Navigation' | 'View' | 'Composer' | 'Session';
export type ShortcutAction = {
  id: string;
  category: Category;
  label: string;
  chord: string;          // the default, e.g. "mod+k", "1", "`"
  scope: Scope;
  /** Works while typing in an input (only chords with a modifier may). */
  inInputs?: boolean;
};

export const CATEGORIES: Category[] = ['Navigation', 'View', 'Composer', 'Session'];
export const STORAGE_KEY = 'hud.shortcuts';
/** An approval or decision is never a keyboard target. */
export const FORBIDDEN_TARGET = /(approv|decision|decide|reject|deny|accept|consent)/i;

const MODES: [string, string, string][] = [
  ['1', 'cockpit', 'Cockpit'], ['2', 'agents', 'Agents'], ['3', 'trust', 'Trust'],
  ['4', 'memory', 'Memory'], ['5', 'autonomy', 'Autonomy'], ['6', 'build', 'Build'],
  ['7', 'observe', 'Observe'], ['8', 'interop', 'Interop'], ['9', 'chat', 'Chat'], ['0', 'comms', 'Comms'],
];

export function defineActions(actions: ShortcutAction[]): ShortcutAction[] {
  const seen = new Set<string>();
  for (const action of actions) {
    if (seen.has(action.id)) throw new Error(`duplicate shortcut action: ${action.id}`);
    seen.add(action.id);
    if (FORBIDDEN_TARGET.test(action.id) || FORBIDDEN_TARGET.test(action.category) || FORBIDDEN_TARGET.test(action.label)) {
      throw new Error(`a shortcut may not target an approval or decision: ${action.id}`);
    }
    if (!CATEGORIES.includes(action.category)) throw new Error(`unknown shortcut category: ${action.category}`);
    if (normalizeChord(action.chord) !== action.chord) throw new Error(`default chord not normal: ${action.chord}`);
  }
  return actions;
}

export const ACTIONS: ShortcutAction[] = defineActions([
  ...MODES.map(([key, mode, label]) => ({
    id: `mode.${mode}`, category: 'Navigation' as Category, label: `Go to ${label}`, chord: key, scope: 'global' as Scope,
  })),
  { id: 'view.world', category: 'Navigation', label: 'Open World Intelligence', chord: 'w', scope: 'global' },
  { id: 'view.console', category: 'Navigation', label: 'Open or close the Console', chord: '`', scope: 'global' },
  { id: 'view.ambient', category: 'View', label: 'Ambient mode', chord: 'a', scope: 'global' },
  { id: 'view.cinema', category: 'View', label: 'Cinema mode', chord: 'm', scope: 'global' },
  { id: 'cinema.orb', category: 'View', label: 'Cinema: the voice orb', chord: 'o', scope: 'cinema' },
  { id: 'cinema.mesh', category: 'View', label: 'Cinema: the neural mesh', chord: 'n', scope: 'cinema' },
  { id: 'cinema.brain', category: 'View', label: 'Cinema: the briefing wall', chord: 'b', scope: 'cinema' },
  { id: 'composer.focus', category: 'Composer', label: 'Focus the message box', chord: '/', scope: 'global' },
  { id: 'session.palette', category: 'Session', label: 'Command palette', chord: 'mod+k', scope: 'global', inInputs: true },
  { id: 'session.shortcuts', category: 'Session', label: 'Keyboard shortcuts', chord: 'mod+/', scope: 'global', inInputs: true },
]);

const MODIFIER_KEYS = new Set(['control', 'meta', 'alt', 'shift', 'os', 'altgraph', 'capslock', 'fn']);

/** A chord in its one spelling: modifiers in the order mod, alt, shift, then the key. */
export function normalizeChord(raw: string): string {
  const parts = String(raw || '').toLowerCase().split('+').map((p) => p.trim());
  let key = parts.pop() || '';
  if (key === '' && parts.length && parts[parts.length - 1] === '') { parts.pop(); key = '+'; }
  const mods = new Set(parts.map((p) => (p === 'ctrl' || p === 'cmd' || p === 'meta' ? 'mod' : p)));
  const out = ['mod', 'alt', 'shift'].filter((m) => mods.has(m));
  if (key === 'space') key = ' ';
  return [...out, key].join('+');
}

/** The chord a key event spells, or null for a lone modifier. */
export function chordFromEvent(e: { key?: string; metaKey?: boolean; ctrlKey?: boolean; altKey?: boolean; shiftKey?: boolean }): string | null {
  const key = String(e.key || '').toLowerCase();
  if (!key || MODIFIER_KEYS.has(key) || key === 'dead' || key === 'unidentified') return null;
  const mods: string[] = [];
  if (e.metaKey || e.ctrlKey) mods.push('mod');
  if (e.altKey) mods.push('alt');
  // A shifted symbol ("?", "~") already carries its shift; a letter or a named key does not.
  if (e.shiftKey && (key.length > 1 || /[a-z]/.test(key))) mods.push('shift');
  return [...mods, key].join('+');
}

export function displayChord(chord: string, mac = typeof navigator !== 'undefined' && /mac/i.test(navigator.platform || '')): string {
  return chord.split('+').map((p) => (p === 'mod' ? (mac ? '⌘' : 'Ctrl') : p === 'alt' ? (mac ? '⌥' : 'Alt')
    : p === 'shift' ? (mac ? '⇧' : 'Shift') : p === ' ' ? 'Space' : p.length === 1 ? p.toUpperCase() : p)).join(mac ? '' : '+');
}

export type Overrides = Record<string, string>;

/** The owner's rebindings: known ids to normal chords; anything else is dropped. */
export function readOverrides(raw: unknown): Overrides {
  const out: Overrides = {};
  if (!raw || typeof raw !== 'object') return out;   // an array's indices are no action ids
  const known = new Set(ACTIONS.map((a) => a.id));
  for (const [id, chord] of Object.entries(raw as Record<string, unknown>)) {
    if (!known.has(id) || typeof chord !== 'string' || !chord || chord.length > 40) continue;
    out[id] = normalizeChord(chord);
  }
  return out;
}

export function loadOverrides(storage: Storage | undefined = globalThis.localStorage): Overrides {
  try { return readOverrides(JSON.parse(storage?.getItem(STORAGE_KEY) || '{}')); } catch { return {}; }
}

export function saveOverrides(overrides: Overrides, storage: Storage | undefined = globalThis.localStorage): void {
  try {
    const clean = readOverrides(overrides);
    if (Object.keys(clean).length) storage?.setItem(STORAGE_KEY, JSON.stringify(clean));
    else storage?.removeItem(STORAGE_KEY);
  } catch { /* storage off: the change lasts this page */ }
}

export type Binding = ShortcutAction & { current: string; custom: boolean };

export function bindings(overrides: Overrides = {}): Binding[] {
  return ACTIONS.map((a) => {
    const current = overrides[a.id] ?? a.chord;
    return { ...a, current, custom: current !== a.chord };
  });
}

/** The other actions that answer *chord* (what the panel names as "Also bound to"). */
export function conflictsFor(id: string, chord: string, list: Binding[]): Binding[] {
  return list.filter((b) => b.id !== id && b.current === chord);
}

/** The action a key event triggers in *scope*: the first one bound to its chord. */
export function matchAction(e: Parameters<typeof chordFromEvent>[0], list: Binding[], scope: Scope): Binding | null {
  const chord = chordFromEvent(e);
  if (!chord) return null;
  return list.find((b) => b.scope === scope && b.current === chord) || null;
}

export function rebind(overrides: Overrides, id: string, chord: string): Overrides {
  const action = ACTIONS.find((a) => a.id === id);
  if (!action) return overrides;
  const next = { ...overrides };
  const normal = normalizeChord(chord);
  if (normal === action.chord) delete next[id];
  else next[id] = normal;
  return next;
}

export function resetBinding(overrides: Overrides, id: string): Overrides {
  const next = { ...overrides };
  delete next[id];
  return next;
}

export function searchBindings(list: Binding[], query: string): Binding[] {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return list;
  return list.filter((b) => b.label.toLowerCase().includes(q) || b.category.toLowerCase().includes(q)
    || b.id.includes(q) || b.current === q || displayChord(b.current, false).toLowerCase().includes(q));
}
