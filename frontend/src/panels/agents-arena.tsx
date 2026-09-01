/* AGENTS & ARENA — two shipped user-tier reads that no client made reachable:

   1. GET /api/agents/history  (agents/core/routers/agents_api.py:110)
      The FLEET rollup: one row per agent with runs / ok-rate / avg latency / last run,
      computed by RunHistory.agents() (run_history.py:85). Distinct from the per-agent run
      list GET /api/agents/{id}/history that modes.tsx already calls, and from
      /api/admin/agents/stats (live in-process status, not history).

   2. GET /api/arena/match/{match_id}  (agents/core/routers/arena.py:69)
      The detail behind the already-shipped MODEL ARENA leaderboard (gap.tsx ArenaPanel):
      the blind entries of one match, and — only after a vote — the label→model mapping.

   THE THREE THINGS THIS PANEL IS NOT ALLOWED TO SAY, each checked against the handler:

   A. "0 runs" / "no activity" for an empty rollup. agents_api.py:112-114 is
        if not orch or not getattr(orch, "run_history", None):
            return nocache_json({"agents": []})
      so a missing orchestrator, a run-history component that failed to initialize, and a
      genuinely idle system all answer 200 with a BYTE-IDENTICAL empty list. There is no
      503 and no availability flag in the payload. The panel therefore cross-reads
      GET /api/health/components (status.py:51) — registry key "run_history"
      (orchestrator.py:301) — and names which of the three the health read confirms, or
      says plainly that it confirms none of them.

   B. A spend figure from `total_cost`. It is STRUCTURALLY always 0.0: the single
      production writer is orchestrator.py:2629 `self.run_history.record(agent_id=…,
      input_text=…, output_text=…, latency_ms=…, ok=…, route=…)` — it never passes `cost`,
      which defaults to 0.0 (run_history.py:47). "$0.00" would be a fabricated fact, so a
      zero renders as "cost —" with the reason, and a non-zero (a future writer) renders
      the number.

   C. "all-time" / "lifetime" for runs, ok-rate or avg latency. Each agent's deque is
      capped at RUN_HISTORY_MAX_PER_AGENT = 100 (config.py:22), so every number here is
      "over the last ≤100 retained runs".

   AND THE TWO FOR THE MATCH READ:

   D. A 503 is not an empty match and a 404 is not an outage. require_component("arena",
      "arena not available") answers 503 when there is no orchestrator or orch.arena is
      None; arena.py:74 answers 404 {"error": "not found"} for an unknown/purged id. They
      are rendered as two visibly different blocks, neither of which shows 0 entries.
      apiGet (client.ts:107-111) throws `GET <path> -> <status>` and does NOT attach the
      response body — unlike apiPost/failMutation, which does — so the panel branches on
      err.status, prints err.message verbatim, and never quotes a JSON reason string it
      could not read.

   E. Which model wrote an entry, before `voted` is true. Arena.get_match() strips
      "_mapping" and re-adds it only after a vote (arena.py:82-94) — the blindness IS the
      product, pinned by tests/test_h10_19_model_arena.py::test_create_match_is_blind.

   Why POST /api/arena/run and /api/arena/vote are here even though the legacy /tools HUD
   already calls them (agents/web/static/tools.js:102,106): NO ROUTE ENUMERATES MATCHES.
   arena.py has exactly four routes and the leaderboard returns per-MODEL rows with no
   match ids. A run's response is the only place in the whole system an id comes from, so
   without it the detail read would need a hardcoded id — i.e. a fake.

   The run control sends the {query, agents:[…]} body ONLY. The other accepted body,
   {candidates: {model: response}}, is pre-generated MODEL OUTPUT; a pair of textareas
   asking the owner to hand-paste two model answers would be a human typing what only an
   agent can legitimately produce, so that shape is deliberately not offered.

   apiPost THROWS on 4xx, so every write passes onErr and renders err.body.error VERBATIM
   in a role="alert" row. In particular the backend's single "invalid vote" is printed as
   "invalid vote": it covers BOTH "match already voted" and "unknown label" (arena.py:60,
   arena.py:102-106) and expanding it to one of them would be a guess.

   Arena.clear() / RunHistory.clear() have no HTTP route, so this panel offers no
   clear/reset/disable control for either store. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, inpS, Json } from '../panel-kit';
import { apiGet } from '../api/client';

const HISTORY_PATH = '/api/agents/history';
const HEALTH_PATH = '/api/health/components';
const MATCH_STEM = '/api/arena/match/';       // + encodeURIComponent(id chosen by the operator
const RUN_PATH = '/api/arena/run';            //   or returned by a run) — never a literal id.
const VOTE_PATH = '/api/arena/vote';
const RING = 100;                             // RUN_HISTORY_MAX_PER_AGENT (config.py:22)

const COST_WHY =
  "the orchestrator's run_history.record() call never passes cost (orchestrator.py:2629), "
  + 'so 0.0 means NOT RECORDED, not free';

const ink3 = 'var(--ink-3)';
const ink2 = 'var(--ink-2)';

function ago(ts: any): string {
  if (typeof ts !== 'number' || !isFinite(ts)) return '—';
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function stamp(ts: any): string {
  if (typeof ts !== 'number' || !isFinite(ts)) return '—';
  try { return new Date(ts * 1000).toLocaleString(); } catch { return String(ts); }
}

/* The load-bearing honesty branch. Same zero rows, four different sentences — the health
   read decides which one is true, and "cannot tell" is one of the four. */
function EmptyRollup({ health }: { health: any }) {
  const d = health.d;
  const hc = (d && d.components) || {};
  if (d && d.summary === 'registry unavailable') {
    return (
      <div style={{ ...mono, color: 'var(--amber)', marginTop: 4 }}>
        orchestrator / component registry unavailable — {HISTORY_PATH} answers 200
        {' '}{'{agents: []}'} with no orchestrator, so this is NOT "zero runs".
      </div>
    );
  }
  if (hc.run_history === 'failed') {
    return (
      <div style={{ ...mono, color: 'var(--amber)', marginTop: 4 }}>
        run-history component failed to initialize (component registry: run_history =
        failed) — the rollup route degrades to 200 {'{agents: []}'}; this is not zero runs.
      </div>
    );
  }
  if (hc.run_history === 'ok') {
    return (
      <div style={{ ...mono, color: ink3, marginTop: 4 }}>
        no runs recorded yet — the run-history component reports ok, so the ring is
        genuinely empty.
      </div>
    );
  }
  return (
    <div style={{ ...mono, color: 'var(--amber)', marginTop: 4 }}>
      empty rollup, and {HEALTH_PATH} did not confirm run_history
      {health.e ? ` (health read offline · ${health.e})` : ' (key absent from the registry)'}
      {' '}— cannot tell "no runs yet" from "component missing".
    </div>
  );
}

/* 503 vs 404 vs guard vs network: four causes, four blocks, no quoted body. */
function MatchRefusal({ err, arenaHealth, id }: { err: any; arenaHealth: any; id: string }) {
  const st = err && err.status;
  const msg = (err && err.message) || 'offline';
  const box = (color: string, head: string, body: any) => (
    <div role="alert" style={{ marginTop: 8, padding: 6, border: `1px solid ${color}`, borderRadius: 4 }}>
      <div style={{ ...mono, color }}>{head}</div>
      <div style={{ ...mono, color: ink2, marginTop: 4 }}>{msg}</div>
      {body}
      <div style={{ ...mono, color: ink3, marginTop: 4 }}>
        GETs surface the status only — apiGet does not attach the response body
        (client.ts:107), so no reason string is quoted here.
      </div>
    </div>
  );
  if (st === 503) {
    return box('var(--red)', 'arena component not available (503)', (
      <>
        <div style={{ ...mono, color: ink2, marginTop: 4 }}>
          require_component("arena") refused: there is no orchestrator, or orch.arena is
          None. This is a component outage — NOT an empty match, and not a missing id:
          match "{id}" may well exist.
        </div>
        {arenaHealth === 'failed' && (
          <div style={{ ...mono, color: 'var(--amber)', marginTop: 4 }}>
            component registry: arena = failed
          </div>
        )}
      </>
    ));
  }
  if (st === 404) {
    return box(ink3, 'no match with that id (404)', (
      <div style={{ ...mono, color: ink2, marginTop: 4 }}>
        arena.get_match("{id}") returned None — unknown or purged id. The arena itself
        answered, so this is not an outage.
      </div>
    ));
  }
  if (st === 401 || st === 403) {
    return box('var(--amber)', `refused by the user guard (${st})`, (
      <div style={{ ...mono, color: ink2, marginTop: 4 }}>
        this instance is network-exposed and the X-User-Token was missing or rejected.
      </div>
    ));
  }
  return box('var(--amber)', `match read failed${st ? ` (${st})` : ''}`, null);
}

export function AgentsArenaPanel() {
  const health = useApi(HEALTH_PATH);                 // open route, availability cross-check
  const hist = useApi(HISTORY_PATH);                  // user tier
  const rows = arr(hist.d, 'agents');
  const hc = (health.d && health.d.components) || {};

  const [sel, setSel] = useState<string[]>([]);
  const [extra, setExtra] = useState('');
  const [q, setQ] = useState('');
  const [paste, setPaste] = useState('');
  const [ids, setIds] = useState<string[]>([]);
  const [mid, setMid] = useState('');
  const [m, setM] = useState<any>(null);
  const [mErr, setMErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [voteErr, setVoteErr] = useState<string | null>(null);

  const toggle = (id: string) =>
    setSel((prev) => (prev.indexOf(id) >= 0 ? prev.filter((x) => x !== id) : prev.concat(id)));

  const extraIds = extra.split(',').map((s) => s.trim()).filter(Boolean);
  const agentIds = sel.concat(extraIds.filter((x) => sel.indexOf(x) < 0));

  /* The lane route. The id is always something the operator picked or the panel produced —
     a run response, a session chip, or an id pasted from the legacy /tools HUD or curl. */
  const load = (id: string) => {
    const clean = String(id || '').trim();
    if (!clean) return;
    setMErr(null);
    setMid(clean);
    apiGet(MATCH_STEM + encodeURIComponent(clean))
      .then((r) => { setM(r); })
      .catch((err) => { setM(null); setMErr({ status: err && err.status, message: err && err.message }); });
  };

  const runReady = q.trim() !== '' && agentIds.length >= 2 && !busy;
  const run = () => {
    if (!runReady) return;
    setRunErr(null);
    setVoteErr(null);
    setBusy(true);
    act(
      RUN_PATH,
      { query: q.trim(), agents: agentIds },
      (r) => {
        setBusy(false);
        const id = r && r.match && r.match.id;
        if (!id) {
          setRunErr('the run answered 200 but carried no match.id — nothing to load');
          return;
        }
        setIds((prev) => [id].concat(prev.filter((x) => x !== id)));
        load(id);
      },
      (err) => {
        setBusy(false);
        setRunErr((err && err.body && err.body.error) || (err && err.message) || 'run failed');
      },
    );
  };

  const vote = (label: string) => {
    if (!mid) return;
    setVoteErr(null);
    act(
      VOTE_PATH,
      { match_id: mid, winner: label },
      () => { load(mid); },
      (err) => setVoteErr((err && err.body && err.body.error) || (err && err.message) || 'vote failed'),
    );
  };

  const entries = Array.isArray(m && m.entries) ? m.entries.slice().sort(
    (a: any, b: any) => String(a && a.label).localeCompare(String(b && b.label))) : [];
  const mapping = (m && m.mapping) || null;

  return (
    <>
      <Card
        title="AGENT RUN HISTORY"
        /* SEED, not LIVE, when the rollup is empty and the health read has not
           confirmed the component is ok — an empty list is not evidence of an idle fleet. */
        live={asLive(hist.d, rows.length > 0 || hc.run_history === 'ok')}
        sub={rows.length > 0 ? `${rows.length} agents` : (hist.d ? 'empty rollup' : null)}
        onReload={() => { hist.reload(); health.reload(); }}
      >
        <div style={{ ...mono, color: ink3, marginBottom: 6 }}>
          Fleet rollup from the per-agent run-history ring — one row per agent that has at
          least one retained run. Agents with an empty ring are omitted by the backend, so
          an absent agent is not a non-existent agent.
        </div>

        <State e={hist.e} loading={hist.loading} n={null} />

        {rows.map((r: any, i: number) => {
          const ok = typeof r.ok_rate === 'number' ? r.ok_rate : null;
          const okColor = ok == null ? ink3 : ok < 0.5 ? 'var(--red)' : ok < 0.95 ? 'var(--amber)' : 'var(--green)';
          const cost = typeof r.total_cost === 'number' ? r.total_cost : 0;
          const picked = sel.indexOf(String(r.agent_id)) >= 0;
          return (
            <Row key={r.agent_id ?? i}>
              <button
                className="tool-btn"
                onClick={() => toggle(String(r.agent_id))}
                title="add/remove this agent from the arena run below"
                style={{ ...mono, color: picked ? 'var(--accent-light)' : ink2 }}
              >
                {picked ? '● ' : '○ '}{String(r.agent_id)}
              </button>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                <Tag>{r.runs} runs</Tag>
                <Tag c={okColor}>{ok == null ? 'ok-rate —' : `${Math.round(ok * 100)}% ok`}</Tag>
                <Tag>{r.avg_latency_ms} ms avg</Tag>
                {cost > 0
                  ? <Tag c="var(--amber)">{cost} cost</Tag>
                  : <span title={COST_WHY}><Tag>cost —</Tag></span>}
                <span style={{ ...mono, color: ink3 }} title={stamp(r.last_ts)}>{ago(r.last_ts)}</span>
              </span>
            </Row>
          );
        })}

        {rows.length > 0 && (
          <div style={{ ...mono, color: ink3, marginTop: 6 }}>
            runs · ok-rate · avg latency are computed over the last ≤{RING} retained runs
            per agent (RUN_HISTORY_MAX_PER_AGENT), never all-time. "cost —" means the
            recorder does not write a cost field, not that the runs were free.
          </div>
        )}

        {!hist.loading && !hist.e && rows.length === 0 && <EmptyRollup health={health} />}

        <div style={{ ...mono, color: ink3, marginTop: 8 }}>
          user-tier read · GET {HISTORY_PATH} · availability cross-checked against GET
          {' '}{HEALTH_PATH}
          {health.d && health.d.summary ? ` ("${String(health.d.summary)}")` : ''}.
        </div>
      </Card>

      <Card
        title="ARENA MATCH"
        live={asLive(m)}
        sub={m ? (m.voted ? 'voted' : 'blind') : null}
        onReload={() => { if (mid) load(mid); }}
      >
        <div style={{ ...mono, color: ink3, marginBottom: 6 }}>
          One blind match in full: the entries as the arena stores them, and the label→model
          mapping only once a vote has revealed it. No route lists match ids — the
          leaderboard ranks models, not matches — so an id comes from a run below, from a
          chip this panel produced, or from one you paste.
        </div>

        {/* ── run: the only honest source of a match id ─────────────────────────── */}
        <Row>
          <span style={{ ...mono, color: ink3 }}>query</span>
          <input
            style={{ ...inpS, flex: 1 }}
            value={q}
            placeholder="the prompt to compare, e.g. summarize this changelog"
            onChange={(ev) => setQ(ev.target.value)}
          />
        </Row>
        <Row>
          <span style={{ ...mono, color: ink3 }}>agents</span>
          <input
            style={{ ...inpS, flex: 1 }}
            value={extra}
            placeholder="extra agent ids, comma-separated (for agents with no recorded runs)"
            onChange={(ev) => setExtra(ev.target.value)}
          />
          <button className="tool-btn" disabled={!runReady} onClick={run}>RUN MATCH</button>
        </Row>
        <div style={{ ...mono, color: ink3, marginTop: 4 }}>
          selected: {agentIds.length ? agentIds.join(', ') : '(none — click agent ids above)'}
        </div>
        {!runReady && !busy && (
          <div style={{ ...mono, color: 'var(--amber)', marginTop: 4 }}>
            {q.trim() === ''
              ? "disabled: the backend refuses an empty query with 400 \"query required\""
              : `disabled: ${agentIds.length} of the 2 agents required are selected — the backend refuses with 400 "provide candidates or >=2 agents"`}
          </div>
        )}
        {busy && (
          <div style={{ ...mono, color: 'var(--amber)', marginTop: 4 }}>
            running the query live against {agentIds.length} agents — one real inference per
            agent, through orch.handle_input(channel="arena").
          </div>
        )}
        {runErr != null && (
          <div role="alert" style={{ ...mono, color: 'var(--red)', marginTop: 6, padding: 6, border: '1px solid var(--red)', borderRadius: 4 }}>
            run refused · POST {RUN_PATH} · {runErr}
          </div>
        )}
        <div style={{ ...mono, color: ink3, marginTop: 4 }}>
          only the {'{query, agents:[…]}'} body is offered. The route also accepts
          {' '}{'{candidates:{model:response}}'} — pre-generated model output — and a textarea
          asking you to paste two model answers by hand would be a form over something only
          an agent can produce.
        </div>

        {/* ── pick an id ────────────────────────────────────────────────────────── */}
        <Row>
          <span style={{ ...mono, color: ink3 }}>match id</span>
          <input
            style={{ ...inpS, flex: 1 }}
            value={paste}
            placeholder="paste a match id (from /tools or curl)"
            onChange={(ev) => setPaste(ev.target.value)}
          />
          <button className="tool-btn" disabled={paste.trim() === ''} onClick={() => load(paste.trim())}>LOAD</button>
        </Row>
        {ids.length > 0 && (
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 6, alignItems: 'center' }}>
            <span style={{ ...mono, color: ink3 }}>this session:</span>
            {ids.map((id) => (
              <button key={id} className="tool-btn" style={{ ...mono, color: id === mid ? 'var(--accent-light)' : ink2 }} onClick={() => load(id)}>
                {id}
              </button>
            ))}
          </div>
        )}

        {mErr != null && <MatchRefusal err={mErr} arenaHealth={hc.arena} id={mid} />}

        {m != null && mErr == null && (
          <div style={{ marginTop: 8 }}>
            <Row>
              <span style={{ ...mono, color: ink2 }}>{String(m.id)}</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                <Tag c={m.voted ? 'var(--green)' : 'var(--amber)'}>{m.voted ? 'VOTED' : 'BLIND'}</Tag>
                <span style={{ ...mono, color: ink3 }}>{stamp(m.created_at)}</span>
              </span>
            </Row>
            <div style={{ ...mono, color: ink2, marginTop: 6 }}>query: {String(m.query)}</div>

            {!m.voted && (
              <div style={{ ...mono, color: ink3, marginTop: 4 }}>
                model identities are hidden until a vote — the server strips the label→model
                mapping from this response, so this panel cannot say which model is which.
              </div>
            )}

            {entries.map((en: any, i: number) => {
              const resp = String(en && en.response);
              const failed = resp.startsWith('[error:');
              return (
                <div key={en.label ?? i} style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--panel-line)' }}>
                  <Row>
                    <span style={{ ...mono, fontWeight: 700, color: failed ? 'var(--red)' : ink2 }}>
                      {String(en.label)}
                    </span>
                    {failed && <Tag c="var(--red)">RUN FAILED</Tag>}
                    {mapping && mapping[en.label] && <Tag c="var(--accent-light)">{String(mapping[en.label])}</Tag>}
                    {m.voted && m.winner_label === en.label && <Tag c="var(--green)">WINNER</Tag>}
                    {!m.voted && (
                      <button
                        className="tool-btn"
                        style={{ marginLeft: 'auto' }}
                        disabled={failed}
                        title={failed
                          ? 'this candidate is a stored exception, not an answer — voting for it would move ELO on a failure'
                          : 'irreversible: reveals the mapping and moves ELO for every model in this match'}
                        onClick={() => vote(String(en.label))}
                      >
                        VOTE {String(en.label)}
                      </button>
                    )}
                  </Row>
                  {failed && (
                    <div style={{ ...mono, color: 'var(--red)', marginTop: 4 }}>
                      the agent raised during this run and the backend stored the exception
                      text as this candidate's answer (arena.py:39-40). It is not a model
                      response, and voting on it would pollute the ELO leaderboard.
                    </div>
                  )}
                  <Json v={resp} />
                </div>
              );
            })}

            {voteErr != null && (
              <div role="alert" style={{ ...mono, color: 'var(--red)', marginTop: 6, padding: 6, border: '1px solid var(--red)', borderRadius: 4 }}>
                vote refused · POST {VOTE_PATH} · {voteErr}
              </div>
            )}

            {!m.voted && (
              <div style={{ ...mono, color: 'var(--amber)', marginTop: 6 }}>
                a vote is irreversible: it reveals the mapping and moves ELO for every model
                in this match, and the MODEL ARENA leaderboard is the downstream surface.
              </div>
            )}

            {m.voted && (
              <div style={{ ...mono, color: ink2, marginTop: 6 }}>
                revealed by the backend · winner:{' '}
                {m.winner_model != null
                  ? String(m.winner_model)
                  : `${String(m.winner_label)} (the response carried no winner_model)`}
              </div>
            )}
          </div>
        )}

        {m == null && mErr == null && (
          <div style={{ ...mono, color: ink3, marginTop: 8 }}>
            no match loaded — run one above, or paste an id.
          </div>
        )}

        <div style={{ ...mono, color: ink3, marginTop: 8 }}>
          user-tier reads and writes · GET {MATCH_STEM}{'{match_id}'} · the run and vote
          controls drive POST {RUN_PATH} and POST {VOTE_PATH}, which the legacy /tools HUD
          already calls (agents/web/static/tools.js:102,106); they exist here because no
          route lists match ids, so a run is the only place one can come from.
        </div>
        <div style={{ ...mono, color: ink3, marginTop: 2 }}>
          no clear/reset control: Arena.clear() and RunHistory.clear() have no HTTP route.
        </div>
      </Card>
    </>
  );
}
