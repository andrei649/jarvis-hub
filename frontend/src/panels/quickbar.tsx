/* QUICKBAR — what one typed line means, before anything happens
   (POST /api/quickbar/resolve, GET /api/quickbar/help; both user-guarded).

   `agents/core/quickbar.py` has shipped a complete command parser since 0.64 with no
   route and no consumer — a parser nobody could reach, which is code that looks alive
   and is not. This panel is the consumer.

   The design problem is that a command bar is the most tempting place in a product to
   put a shortcut past the rules. One keystroke, one line, and something happens. So the
   panel is deliberately a PREVIEW:

   · it renders the plan the backend resolved and DOES NOTHING with it. A navigate plan
     shows where it would go; a summon plan shows which agent would answer. Acting on
     either is the ordinary path, with the affordances that make it reviewable;
   · `unresolved` is rendered as its own state with the backend's reason verbatim, in
     amber. A bar that quietly fell back to "ask the default agent" whenever it did not
     understand you would be a bar that did the wrong thing confidently — which is worse
     than one that says it did not understand;
   · a `query` plan shows its `route_hint` labelled as a GUESS, because the authoritative
     routing happens on submit and a preview that read as a decision would be a lie about
     which agent is going to answer;
   · recall history lives in this browser (localStorage), never on the server. A
     server-side quickbar history is a keystroke log of everything the owner typed into a
     floating bar — the most sensitive store in the product, for the least reason.

   NOTE: never spell a route path in this comment unless the panel calls it —
   tests/test_hud_v2_parity.py:_has_caller matches comment text as a caller. */
import React, { useState } from 'react';
import { apiPost } from '../api/client';
import { useApi, arr, mono, Card, State, Row, Tag, inpS } from '../panel-kit';

const HELP_PATH = '/api/quickbar/help';
const RESOLVE_PATH = '/api/quickbar/resolve';
const COMMANDS_PATH = '/api/commands';
const HISTORY_KEY = 'nerva.quickbar.history';
const MAX_HISTORY = 20;

const EM = '—';

/* Per-viewer, in this browser only. Every read and write is guarded: a private
   window, cleared site data or a browser that blocks storage must leave the bar
   working, not throw on the first keystroke. */
export const readHistory = (): string[] => {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === 'string') : [];
  } catch { return []; }
};

export const pushHistory = (line: string): string[] => {
  const next = [line, ...readHistory().filter((x) => x !== line)].slice(0, MAX_HISTORY);
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  return next;
};

/* Plan kind → how it reads. `unresolved` is amber and never green: a bar that did
   not understand you has not succeeded at anything. */
const KIND_COLOR: Record<string, string> = {
  navigate: 'var(--accent-light)',
  summon: 'var(--accent-light)',
  query: 'var(--ink-2)',
  help: 'var(--ink-2)',
  empty: 'var(--ink-3)',
  unresolved: 'var(--amber)',
};

const Note = ({ c, children }: { c?: any; children?: any }) => (
  <div style={{ fontSize: 10, lineHeight: 1.5, color: c || 'var(--ink-2)', padding: '3px 0 5px' }}>{children}</div>
);

/* What the plan would do, in one sentence, without doing it. */
export const describePlan = (plan: any): string => {
  if (!plan) return EM;
  switch (plan.kind) {
    case 'navigate':
      return `would go to ${plan.tab || plan.mode || EM}`;
    case 'summon':
      return `would ask ${plan.agent}${plan.text ? `: ${plan.text}` : ''}`;
    case 'query':
      return plan.route_hint
        ? `would ask — probably ${plan.route_hint}`
        : 'would ask — no routing guess';
    case 'help':
      return 'the command menu';
    case 'empty':
      return 'nothing typed';
    case 'unresolved':
      return String(plan.reason || 'not understood');
    default:
      return String(plan.kind || EM);
  }
};

export function QuickbarPanel() {
  const help = useApi(HELP_PATH);
  // Include an existing owner credential; visibility is decided by chat's principal.
  const catalog = useApi(COMMANDS_PATH, true, true);
  const [line, setLine] = useState('');
  const [plan, setPlan] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [history, setHistory] = useState<string[]>(readHistory);

  const resolve = (text: string) => {
    setErr(null);
    apiPost(RESOLVE_PATH, { text })
      .then((body: any) => {
        setPlan(body && body.plan);
        const kind = body && body.plan && body.plan.kind;
        // Only actionable lines are recalled — the same rule CommandBar.resolve
        // uses, so up-arrow does not fill with /help and blanks.
        if (['navigate', 'summon', 'query'].includes(kind)) setHistory(pushHistory(text));
      })
      .catch((e: any) => {
        setPlan(null);
        setErr(`refused · ${(e && e.body && e.body.reason) || (e && e.status) || 'error'}`);
      });
  };

  const commands = arr(help.d, 'commands');
  const chatCommands = catalog.e || catalog.loading ? [] : arr(catalog.d, 'commands');

  return (
    <Card
      title="QUICKBAR"
      live={help.d ? 'live' : undefined}
      sub={commands.length ? `${commands.length} command(s)` : null}
      onReload={() => { help.reload(); catalog.reload(); }}
    >
      <State e={help.e} loading={help.loading} n={help.d ? 1 : 0} />

      <Row>
        <input
          style={{ ...inpS, flex: 1 }}
          placeholder="/artifacts · @friday what's up · open memory"
          value={line}
          aria-label="quickbar line"
          onChange={(e: any) => setLine(e.target.value)}
          onKeyDown={(e: any) => { if (e.key === 'Enter') resolve(line); }}
        />
        <button className="tool-btn" title="resolve this line" onClick={() => resolve(line)}>
          resolve
        </button>
      </Row>

      {/* The plan, and nothing done with it. */}
      {plan && (
        <>
          <Row>
            <span style={{ ...mono, fontSize: 11 }}>{plan.input || EM}</span>
            <span style={{ marginLeft: 'auto' }}>
              <Tag c={KIND_COLOR[String(plan.kind)] || 'var(--ink-3)'}>{plan.kind}</Tag>
            </span>
          </Row>
          <Note c={plan.kind === 'unresolved' ? 'var(--amber)' : undefined}>
            {describePlan(plan)}
          </Note>
          {plan.kind === 'query' && plan.route_hint && (
            <Note c="var(--ink-3)">
              The agent is a <b>guess</b> — routing is decided when you actually send it.
            </Note>
          )}
        </>
      )}

      {err && <div role="alert" style={{ ...mono, color: 'var(--red)', marginTop: 6 }}>{err}</div>}

      {history.length > 0 && (
        <>
          <div style={{ ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-2)', marginTop: 10 }}>
            RECENT (this browser only)
          </div>
          {history.slice(0, 5).map((item: string) => (
            <Row key={item}>
              <button
                className="tool-btn"
                title="resolve this line again"
                onClick={() => { setLine(item); resolve(item); }}
              >{item}</button>
            </Row>
          ))}
        </>
      )}

      {commands.length > 0 && (
        <>
          <div style={{ ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-2)', marginTop: 10 }}>
            SHORTCUTS
          </div>
          {commands.slice(0, 8).map((c: any) => (
            <Row key={c.command}>
              <span style={{ ...mono, fontSize: 11 }}>{c.command}</span>
              <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-2)' }}>{c.does}</span>
            </Row>
          ))}
        </>
      )}

      <div style={{ ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-2)', marginTop: 10 }}>
        CHAT COMMANDS
      </div>
      {catalog.loading && <Note>Loading chat commands…</Note>}
      {catalog.e && <Note c="var(--amber)">Chat commands unavailable.</Note>}
      {!catalog.loading && !catalog.e && catalog.d?.ok && chatCommands.length === 0 && (
        <Note>No chat commands available for this session.</Note>
      )}
      {chatCommands.map((command: any) => (
        <div key={command.name} style={{ padding: '5px 0', borderBottom: '1px solid var(--panel-line)' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <span style={{ ...mono, fontSize: 11, overflowWrap: 'anywhere' }}>
              {command.command}{command.usage ? ` ${command.usage}` : ''}
            </span>
            {command.tier === 'admin' && <Tag c="var(--amber)">owner</Tag>}
          </div>
          <Note>{command.description}</Note>
        </div>
      ))}
      {chatCommands.length > 0 && <Note>Send a command in chat to run it.</Note>}

      <Note>
        Preview a line here; use chat to send it. Recent lines stay in this browser.
      </Note>
    </Card>
  );
}

export default QuickbarPanel;
