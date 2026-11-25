/* panel-kit — the shared Console panel primitives, extracted verbatim from gap.tsx.

   gap.tsx had grown to 4.6k lines with every panel and every primitive in one file, so
   two panels could never be written in parallel without colliding. The primitives are
   exported so a panel can live in its own module (the pattern `operator-panel.tsx` already
   uses) and still look identical to the ones that stayed behind.

   Their look lives in theme/kit.css (`.n-card`, `.n-tag`, `.n-chip`, `.n-state`, `.n-row`,
   `.n-btn`, `.n-json`), drawn from the theme roles (theme/CONTRACT.md), so every theme
   restyles every panel at once. Markup, text, roles and the HUD v2 class hooks (`.panel`,
   `.panel-head`, `.ttl`, `.st`, `.tool-btn`, `.panel-body`, the `.bk` brackets) are kept:
   tests and Classic rely on them. The style objects callers spread (`mono`, `inpS`, `taS`)
   stay objects, now made of theme tokens, so their call sites follow the theme unedited.

   The HUD parity gate globs every .tsx under frontend/src, so a panel in its own file
   counts as a real caller exactly like an inline one. */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { apiGet, apiPost } from './api/client';

/** One GET, reloadable. An answer is shown unless a newer one already is: a slow
    answer to an earlier read never overwrites a newer one (H153 review: a stale "on"),
    and a poller slower than its interval still sees every answer that is the newest so
    far (H153 fourth review: keeping only the newest request's answer starved it).
    `loading` stays true until the newest request is answered. `status` is the failed
    read's HTTP status (0 when it never reached the hub) and `refusal` its JSON body. */
export function useApi(path, auto = true, admin = false) {
  const [d, setD] = useState(null);
  const [e, setE] = useState(null);
  const [status, setStatus] = useState(0);
  const [refusal, setRefusal] = useState(null);
  const [loading, setLoading] = useState(false);
  const latest = useRef(0);    // the newest request started
  const shown = useRef(0);     // the request whose answer is shown
  const reload = useCallback(() => {
    const mine = ++latest.current;
    setLoading(true);
    const land = (show) => {
      if (mine > shown.current) {
        shown.current = mine;
        show();
      }
      if (mine === latest.current) setLoading(false);
    };
    apiGet(path, admin ? { admin: true } : undefined)
      .then((r) => land(() => { setD(r); setE(null); setStatus(0); setRefusal(null); }))
      .catch((err) => land(() => {
        setE(err?.message || 'offline');
        setStatus(Number(err?.status) || 0);
        setRefusal(err?.body ?? null);
      }));
  }, [path, admin]);
  // Another address or credential: an answer to a request made before it is never shown.
  useEffect(() => { shown.current = latest.current; }, [path, admin]);
  useEffect(() => { if (auto) reload(); }, [auto, reload]);
  return { d, e, status, refusal, loading, reload };
}
// Bolt Optimization: Replace k.map().find() with indexed for loop to eliminate intermediate array and closure allocations
export const arr = (x: any, ...k: any[]): any[] => {
  if (Array.isArray(x)) return x;
  if (x && k.length > 0) {
    for (let i = 0; i < k.length; i++) {
      const val = x[k[i]];
      if (Array.isArray(val)) return val;
    }
  }
  return [];
};
/* Identifiers only (contract §5): hashes, ids, addresses, model and capability names, code,
   logs. The theme's mono at the label step (13px; it was 11px). Words — messages, notes,
   errors, descriptions, hints — take `note` below; a line that mixes both gives the
   identifier its own <code> or IDENT (theme/type.ts) span. Callers that spread this and then
   set their own numeric fontSize keep theirs. */
export const mono = { fontFamily: 'var(--n-font-mono)', fontSize: 'var(--n-fs-label)' };
/* Messages, notes, errors, descriptions and hints: the label step in the interface face. This
   is what most `...mono` spreads that hold words (not identifiers) should have been; the
   contract (theme/CONTRACT.md §5) keeps mono for identifiers only. */
export const note = { fontSize: 'var(--n-fs-label)', lineHeight: 'var(--n-lh-label)' };

/* Per-panel LIVE/SEED honesty chip (TASK-2 tail). Distinct from LiveSourceChip
   (mode-level, block-positioned under a header) — this is inline-sized for the
   panel-head flex row. Same color/wording convention: green LIVE = the panel's
   `enabled`-style flag is on (or the surface has no such flag and simply loaded
   real data), amber SEED = present but not collecting yet. Renders nothing until
   the panel has actually loaded (`live` undefined) so it never guesses. */
export const asLive = (loaded: any, enabled?: any): 'live' | 'seed' | undefined => {
  if (!loaded) return undefined;
  if (enabled === undefined) return 'live';
  return enabled ? 'live' : 'seed';
};

/* LIVE is a filled dot, SEED a ring inside a dashed rule (kit.css `.n-chip`): the state is
   a shape and a word, so it never rests on the green/amber distinction alone. */
export function PanelChip({ live }: { live?: 'live' | 'seed' | null }) {
  if (live !== 'live' && live !== 'seed') return null;
  const isLive = live === 'live';
  return (
    <span
      className={`n-chip n-chip--${live}`}
      title={isLive ? 'Live data from the backend' : 'Seeded/disabled — not live'}
    >
      <span className="n-chip__mark" />
      {isLive ? 'LIVE' : 'SEED'}
    </span>
  );
}

export function Card({ title, sub, live, onReload, children }: { title?: any; sub?: any; live?: any; onReload?: any; children?: any }) {
  return (
    <div className="panel n-card" style={{ marginBottom: 'var(--gap)', breakInside: 'avoid' }}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head n-card__head">
        <span className="ttl n-card__title">{title}</span>
        <PanelChip live={live} />
        {sub != null && <span className="st n-card__sub">{sub}</span>}
        {onReload && <button className="tool-btn n-btn n-btn--quiet n-btn--sm n-card__reload" onClick={onReload} title="reload" aria-label="Reload">↻</button>}
      </div>
      <div className="panel-body tight n-card__body" tabIndex={0}>{children}</div>
    </div>
  );
}
// An error shows even while a newer request is out: a poller slower than its interval is
// always loading, and hid every failed poll behind "loading…" (review-H153e NIT-5).
// Each line carries a mark as well as its words (kit.css `.n-state`): ■ error, ▶ loading, ○ empty.
export const State = ({ e, loading, n }) => (e ? <div className="n-state n-state--error">offline · {e}</div>
  : loading ? <div className="n-state n-state--loading">loading…</div>
  : n === 0 ? <div className="n-state n-state--empty">nothing yet</div> : null);
export const Row = ({ children }) => <div className="n-row">{children}</div>;

/** The kit tone a colour stands for. `<Tag c>` callers pass HUD v2 tokens (`var(--green)`,
    `var(--amber)`, …) or theme roles (`var(--n-ok)`, …); kit.css gives each tone its wash
    and its mark. Only a token that is the tone's own colour counts: a wash, dim or glow
    variant (`--green-dim`, `--accent-faint`, `--n-ok-wash`) would be drawn on the tone's
    wash in its own colour, so it stays neutral. Anything unrecognised is neutral and keeps
    only its text colour.
    The legacy accent (`--accent`, `--accent-light`) is emphasis, not the theme's accent:
    since 2026-11-23 the bridge maps both to `--n-emph` (theme/CONTRACT.md §6), so those
    tags are `emph` (the emphasis ink, no wash). Only the theme's own accent roles
    (`--n-accent`, `--n-accent-text`) are `accent`, which in Ledger is the owner's hand. */
export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'cloud' | 'accent' | 'emph' | 'neutral';
const TONES: ReadonlyArray<readonly [RegExp, Tone]> = [
  [/--(?:green|n-ok)(?![\w-])/, 'ok'],
  [/--(?:amber|n-warn)(?![\w-])/, 'warn'],
  [/--(?:red|n-bad|n-stop)(?![\w-])/, 'bad'],
  [/--(?:violet|n-cloud)(?![\w-])/, 'cloud'],
  [/--(?:n-info|cyan|blue)(?![\w-])/, 'info'],
  [/--n-accent(?:-text)?(?![\w-])/, 'accent'],
  [/--(?:accent(?:-light)?|n-emph)(?![\w-])/, 'emph'],
];
export function toneOf(c: unknown): Tone {
  if (typeof c !== 'string') return 'neutral';
  for (const [pattern, tone] of TONES) if (pattern.test(c)) return tone;
  return 'neutral';
}

/* --n-text-2, the readable secondary ink, as the uncoloured default — never the third ink.
   History: the default was --ink-2 because the HUD v2 --ink-3 is 2.79:1 on --void and
   2.83:1 on --void-2 (the modal), against AA's 4.5:1, while --ink-2 is 7.07:1 and 7.03:1.
   An axe sweep of the ten mode hotkeys found the untinted <Tag> to be the largest single
   source of resolvable contrast failures: 6 of the 8 failing elements, rendering the
   first-run gate's privacy chips ("connected account · cloud model may receive context",
   "stored locally · cloud model may receive context", "external websites", "read-only").
   That is consent copy — the text telling a new user what leaves their machine.
   --n-text-2 is the theme contract's name for that ink: every Nerva theme must clear 4.5:1
   with it on every ground (theme-contrast.test.ts) and Classic derives it from --ink-2.
   This fallback covers uncoloured `<Tag>` uses; explicit `c` values are checked at
   their call sites because several also carried the low-contrast ink-3 text colour.
   The colour stays inline (callers and tests read `style.color`); the shape, type, wash
   and mark come from kit.css `.n-tag` and its tone. */
export const Tag = ({ c, children }: { c?: any; children?: any }) => (
  <span className={`n-tag n-tag--${toneOf(c)}`} style={{ color: c || 'var(--n-text-2)' }}>{children}</span>
);
export const Btn = ({ onClick, children }) => <button className="tool-btn n-btn n-btn--sm" onClick={onClick} style={{ marginLeft: 'auto' }}>{children}</button>;
export const act = (p, body, then?, onErr?) => apiPost(p, body)
  .then(then || (() => {}))
  .catch((err) => { if (onErr) onErr(err); });
// `onErr` is OPTIONAL but matters: without it a failed admin action is invisible. Engaging
// the kill-switch is kernel-mediated and answers 403 "kernel denied" without a capability
// token, so the 2026-07-27 QA run pressed HALT ALL, got no error, no state change and no
// hint it had been refused — the card kept reading "ARMED · operational". Any call site
// that drives a safety or governance control MUST pass onErr and show it.
export const actA = (p, body, then, onErr?) => apiPost(p, body, { admin: true })
  .then(then || (() => {}))
  .catch((err) => { if (onErr) onErr(err); });
/* DRA-52 / DRA-36 / DRA-38 residual, call-site half. `failMutation` now reads the error
   body and attaches it to the thrown error, so the backend's OWN refusal reason is finally
   reachable — but every call site still rendered `refused · 400` or, worse,
   `err.message`, which is the string "POST /api/x -> 400". A status code tells you that
   something was refused; it never tells you WHY, and a caller left guessing writes a
   plausible-looking cause of its own, which is the fabrication this HUD exists to remove.

   The backend speaks THREE refusal dialects and all three are its own words, so all three
   are read: `{"error": …}` is the routers' agreed shape (`error_json`,
   `component_unavailable`); `{"ok": false, "reason": …}` is what the component layer
   returns and the router passes through with a status (sub-agent spawn/steer/stop, media
   actions); `detail` is FastAPI's validation shape, which can be a list of objects —
   stringified rather than dropped, because an unreadable real reason still beats an
   invented readable one. Then the caller's own fallback, then the bare status.

   `err.message` is deliberately NOT in the chain: it is a restatement of the request
   line, and printing it as a reason is how "POST /api/subagents/spawn -> 429" ended up in
   front of operators as the explanation of why their spawn was refused. */
export function refusalReason(err: any, fallback = ''): string {
  const body = err && err.body;
  if (body && typeof body === 'object') {
    for (const key of ['error', 'reason'] as const) {
      const v = (body as any)[key];
      if (typeof v === 'string' && v.trim()) return v.trim();
    }
    const d = (body as any).detail;
    if (typeof d === 'string' && d.trim()) return d.trim();
    if (d != null) { try { return JSON.stringify(d); } catch { /* fall through */ } }
  }
  if (fallback) return fallback;
  return err && err.status ? String(err.status) : 'error';
}
/* Inputs, selects and textareas: the same values as kit.css `.n-field` (`.n-input`,
   `.n-textarea`), as objects because over 300 call sites spread them (`{ ...inpS, width: 70 }`).
   A control is the theme's 36px control on the field fill (--n-field-bg: the raised sheet by
   default, a quiet fill where a theme draws its inputs there), edged by --n-rule-field
   (>= 3:1), in the UI face: what the owner types in words is set like the rest of the
   instrument (contract §5, "everything else"). Code, JSON and identifiers are mono (§5): a
   code or JSON textarea spreads `codeS` (kit.css `.n-field--code`), a one-line id input adds
   `MONO` from theme/type.ts. */
export const inpS = {
  minHeight: 'var(--n-control-h)', padding: 'var(--n-s-1) var(--n-s-2)',
  background: 'var(--n-field-bg)', color: 'var(--n-text)',
  border: '1px solid var(--n-rule-field)', borderRadius: 'var(--n-r-1)',
  fontFamily: 'var(--n-font-ui)', fontSize: 'var(--n-fs-ui)', lineHeight: 'var(--n-lh-ui)',
};
export const taS = {
  width: '100%', minHeight: 64, padding: 'var(--n-s-2)',
  background: 'var(--n-field-bg)', color: 'var(--n-text)',
  border: '1px solid var(--n-rule-field)', borderRadius: 'var(--n-r-1)',
  fontFamily: 'var(--n-font-ui)', fontSize: 'var(--n-fs-ui)', lineHeight: 'var(--n-lh-ui)',
};
/* A textarea that holds code or JSON: taS in the theme's mono at the label step (the size
   `mono` uses), without ligatures, so `=>` and `!=` stay two characters. */
export const codeS = {
  ...taS,
  fontFamily: 'var(--n-font-mono)', fontSize: 'var(--n-fs-label)', lineHeight: 'var(--n-lh-label)',
  fontVariantLigatures: 'none', tabSize: 2,
};
/* Read-only data: mono, wrapped, scrolling past `max` px (kit.css `.n-json`). */
export const Json = ({ v, max = 220 }) => (v == null ? null
  : <pre className="n-json" style={{ maxHeight: max }}>{typeof v === 'string' ? v : JSON.stringify(v, null, 2)}</pre>);
