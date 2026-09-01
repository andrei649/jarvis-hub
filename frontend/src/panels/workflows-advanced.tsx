/* WORKFLOW TRACES — lane "workflows-advanced". Two shipped, user-reachable routes that
   no client in this repo has ever called:

     GET  /api/workflows/traces        agents/core/routers/workflows.py:104
     POST /api/workflows/hierarchical  agents/core/routers/workflows.py:201

   Both are Depends(user_guard) — USER tier, not admin. The traces route is deliberately
   user-guarded (WFL-132) because step traces echo 160-char rendered prompt/output
   previews, which is personal content. So: useApi(path) and act(), never the admin
   variants, and the footer says so.

   ── WHY THIS IS NOT A DUPLICATE OF A SHIPPED PANEL ────────────────────────────────
   The only shipped consumer of WorkflowEngine.recent() is build_swarm_summary
   (agents/core/routers/swarm.py:288-290). It pushes every run through _payload_free_run
   (swarm.py:172-188), which STRIPS input_preview and output_preview, caps the list at 5,
   and SwarmPanel (gap.tsx:1271) renders the whole thing as one scalar: "{n} workflow runs".
   Per-step kind/agent/timing/ok, `terminated_by`, the previews, and anything past the five
   most recent are unreachable in the HUD today. WorkflowsPanel (gap.tsx:1834) can start a
   pipeline but prints only "ran <id> · ok"; WorkflowBuilderPanel (gap.tsx:1878) is
   authoring-only. Nothing anywhere posts to /api/workflows/hierarchical.

   ── THE ONE HONESTY FACT THAT DOMINATES SECTION A ─────────────────────────────────
   /api/workflows/traces has NO refusal branch and NO error body. Its only guard is:

       engine = getattr(orch, "workflow_engine", None) if orch else None
       if engine is None:
           return nocache_json({"runs": []})            # workflows.py:107-110

   A missing orchestrator and a missing workflow engine are both returned as HTTP 200 with
   an EMPTY LIST — byte-identical to "the engine is up and nothing has run yet". There is no
   available/enabled/initialized flag anywhere in this payload, and no other already-called
   route disambiguates it (/api/swarm/summary computes wf_runs through _safe(..., []), so it
   degrades to [] the same way). POST /api/workflows/run is the only surface that says
   "workflow engine not initialized" — and calling it would EXECUTE a pipeline, so this panel
   does not probe. The zero-state is therefore an explicit amber "cannot distinguish" line,
   never "no workflow runs yet" and never a green idle/healthy claim.

   Other things this panel must not do, checked against the handlers:
     · `ok: true` and `terminated_by: "<step>"` can BOTH be set (H10.12 early stop). An
       early-terminated run is not a failed run, so the terminated tag is ADDITIVE amber
       beside the status tag, never instead of it.
     · `elapsed` is SECONDS (engine.py:139), `steps[].elapsed_ms` is MILLISECONDS
       (engine.py:209). They are labelled in their own units and never mixed.
     · A `subflow` step recurses into WorkflowEngine.run and therefore reaches _stash_run
       too, so a nested sub-pipeline appears as its OWN additional row. Stated in the footer;
       the list is not one row per operator action.
     · The ring is deque(maxlen=50) and persistence is opt-in via the JARVIS_WORKFLOW_PERSIST
       env var. There is NO route to change either, so both are printed as facts and this
       panel draws no toggle for them.

   ── SECTION B, THE DEGENERATE-FORM TEST ───────────────────────────────────────────
   POST /api/workflows/hierarchical takes a goal the owner types plus a crew of agents the
   owner picks with prompt templates. That is human-authored config of exactly the class the
   shipped WorkflowBuilderPanel already accepts — not an agent-produced card, trace, plan or
   evidence blob. Verdict: real human input, built.

   Its traps, all load-bearing:
     · apiPost THROWS on 4xx/503, so every refusal reaches onErr and NEVER the then branch.
       The four backend strings arrive on err.body.error ("not initialized", "goal and crew
       required", "max_retries must be an integer", "max_retries must be between 0 and 10");
       guard/transport refusals arrive on err.body.detail. Both are printed VERBATIM — none
       of those sentences is typed into this file, and no status is mapped to prose.
     · 200 + ok:false is a FAILED run, not a success. `final` is still populated (the manager
       synthesizes over failed member outputs), so showing only `final` would present a
       failure as an answer. The header goes red and the synthesis carries a red note.
     · Orchestrator._handle_input does `if agent_override and agent_override in self.agents:`
       and otherwise falls through to NORMAL ROUTING, while members[].agent echoes the name
       that was sent. A typo'd agent therefore runs somewhere else and the response still
       looks correct. So agent/fallback/manager are SELECTS over the live roster
       (GET /api/agents, already a shipped caller at src/api/loaders.ts:66) — never free text.
     · `.get("manager", "jarvis")` only defaults on a MISSING key, so manager:"" would give
       manager_agent="" and an unrouted synthesis call. The key is OMITTED when unset. Same
       for a blank crew id / agent / fallback / prompt: omitted, never sent empty.
     · A crew entry that is not an object reaches member.get(...) → AttributeError → an
       unhandled 500, so crew is always serialized as objects.
     · The call is long-running and synchronous — crew_size × (1..max_retries+1) agent turns
       plus one synthesis turn, all inside the open POST, with no per-step timeout on this
       path (unlike WorkflowEngine's 120s). The button locks and says why.
     · HierarchicalManager never calls _stash_run, so a hierarchical run does NOT appear in
       section A. Stated between the sections, and section A is deliberately NOT reloaded
       after a POST. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, inpS, taS, Json } from '../panel-kit';

const TRACES_PATH = '/api/workflows/traces';
const HIER_PATH = '/api/workflows/hierarchical';
const AGENTS_PATH = '/api/agents';

/* limit is Query(20, ge=1, le=50): anything outside 1..50 is a FastAPI 422 raised before
   the handler runs, so the selector only offers values the backend accepts. */
const LIMITS = [10, 20, 50];

/* The fixed, sanitized string HierarchicalManager._run returns for ANY agent exception
   (hierarchical.py:44-47). tests/test_h10_11_hierarchical.py::
   test_agent_exception_detail_is_not_returned_to_client asserts the real cause is
   deliberately withheld — so it is printed as-is and no cause is supplied here. */
const AGENT_ERR = '[error:agent execution failed]';

const str = (v: any) => (typeof v === 'string' && v !== '' ? v : null);
const num = (v: any) => (Number.isFinite(Number(v)) ? Number(v) : null);

function rel(tsSec: any): string | null {
  const n = Number(tsSec);
  if (!Number.isFinite(n) || n <= 0) return null;
  const s = Math.round(Date.now() / 1000 - n);
  if (s < 0) return 'just now';
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.round(s / 60) + 'm ago';
  if (s < 86400) return Math.round(s / 3600) + 'h ago';
  return Math.round(s / 86400) + 'd ago';
}

function abs(tsSec: any): string | null {
  const n = Number(tsSec);
  if (!Number.isFinite(n) || n <= 0) return null;
  try { return new Date(n * 1000).toLocaleString(); } catch { return null; }
}

const dim = { ...mono, fontSize: 10, color: 'var(--ink-3)' };
const amber = { ...mono, fontSize: 10.5, color: 'var(--amber)', lineHeight: 1.5 };
const red = { ...mono, fontSize: 10.5, color: 'var(--red)', lineHeight: 1.5 };

/* Rendered whenever the runs list is empty and the read did NOT fail. Wording is the point:
   it reports the ambiguity instead of resolving it in either direction. */
const AMBIGUITY =
  'GET /api/workflows/traces answers {"runs": []} both when nothing has run AND when the '
  + 'orchestrator or its workflow engine is absent (agents/core/routers/workflows.py:107-110). '
  + 'The payload carries no available/enabled/initialized flag, and no other read reports engine '
  + 'state — POST /api/workflows/run is the only surface that says "workflow engine not '
  + 'initialized", and calling it would execute a pipeline. This panel does not probe, so an '
  + 'empty list here does NOT mean the workflow engine is up.';

/* ── one preview field, printed exactly as the backend truncated it ─────────────── */
function Preview({ label, v }: { label: string; v: any }) {
  const s = typeof v === 'string' ? v : null;
  return (
    <div style={{ marginTop: 4 }}>
      <div style={dim}>{label}</div>
      {s === null
        ? <div style={{ ...dim, color: 'var(--amber)' }}>(field absent from the payload)</div>
        : s === ''
          ? <div style={{ ...dim, color: 'var(--amber)' }}>(the backend sent an empty string)</div>
          : <Json v={s} max={120} />}
    </div>
  );
}

function StepRow({ s }: { s: any }) {
  const ok = s && s.ok === true;
  const bad = s && s.ok === false;
  const ms = num(s && s.elapsed_ms);
  return (
    <div style={{ padding: '5px 0 6px', borderBottom: '1px solid var(--panel-line)' }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ ...mono, fontSize: 11 }}>{str(s && s.step) || '(step id absent)'}</span>
        {str(s && s.kind) && <Tag>kind {s.kind}</Tag>}
        {str(s && s.agent) && <Tag>agent {s.agent}</Tag>}
        {ms != null && <Tag>{ms} ms</Tag>}
        {ok && <Tag c="var(--green)">ok</Tag>}
        {bad && <Tag c="var(--red)">step failed</Tag>}
        {!ok && !bad && <Tag c="var(--amber)">ok flag absent</Tag>}
      </div>
      <Preview label="input_preview (first 160 chars, truncated by the backend)" v={s && s.input_preview} />
      <Preview label="output_preview (first 160 chars, truncated by the backend)" v={s && s.output_preview} />
    </div>
  );
}

export function WorkflowTracesPanel() {
  /* ── section A · GET /api/workflows/traces (user tier) ───────────────────────── */
  const [limit, setLimit] = useState(20);
  const { d, e, loading, reload } = useApi(TRACES_PATH + '?limit=' + limit);
  const runs = arr(d, 'runs');
  const [open, setOpen] = useState<number | null>(null);
  const loaded = !!d && !e;

  /* ── section B · POST /api/workflows/hierarchical (user tier) ────────────────── */
  const ros = useApi(AGENTS_PATH);
  const roster: string[] = arr(ros.d, 'agents')
    .map((a: any) => (typeof a === 'string' ? a : str(a && a.id)))
    .filter(Boolean);
  const rosterLoaded = !!ros.d && !ros.e;
  const rosterUsable = rosterLoaded && roster.length > 0;

  const [goal, setGoal] = useState('');
  const [manager, setManager] = useState('');          // '' → key omitted from the body
  const [maxRetries, setMaxRetries] = useState('1');   // sent as typed; int() lives on the server
  const [crew, setCrew] = useState<any[]>([{ id: '', agent: '', fallback: '', prompt: '{_goal}' }]);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  const setMember = (i: number, k: string, v: string) =>
    setCrew((c) => c.map((m, j) => (j === i ? { ...m, [k]: v } : m)));

  const crewComplete = crew.length > 0 && crew.every((m) => !!str(m.agent));
  const canRun = !busy && !!goal.trim() && crewComplete && rosterUsable;

  /* Every empty field is DROPPED rather than sent blank: the backend defaults only on a
     MISSING key, so "" would silently become an unrouted agent / an unreferenceable id. */
  const buildBody = () => {
    const body: any = {
      goal,
      crew: crew.map((m) => {
        const o: any = { agent: m.agent };
        if (str(m.id && m.id.trim())) o.id = m.id.trim();
        if (str(m.fallback)) o.fallback = m.fallback;
        if (str(m.prompt)) o.prompt = m.prompt;
        return o;
      }),
      max_retries: maxRetries,
    };
    if (str(manager)) body.manager = manager;
    return body;
  };

  const run = () => {
    if (!canRun) return;
    setRes(null);
    setErr(null);
    setBusy(true);
    act(
      HIER_PATH,
      buildBody(),
      (r) => { setBusy(false); setRes(r); },
      /* apiPost throws on every 4xx/503, so this is the ONLY branch a refusal reaches.
         The string is whatever the backend sent — error, else detail, else the transport
         message. Nothing is substituted, mapped or reworded. */
      (x: any) => { setBusy(false); setErr(x?.body?.error ?? x?.body?.detail ?? x?.message ?? String(x)); },
    );
  };

  const members = res && Array.isArray(res.members) ? res.members : [];
  const redistributed = res && Array.isArray(res.redistributed) ? res.redistributed : [];
  const runOk = res ? res.ok === true : null;
  const runBad = res ? res.ok === false : null;

  return (
    <>
      {/* ══ WORKFLOW TRACES ═══════════════════════════════════════════════════ */}
      <Card
        title="WORKFLOW TRACES"
        sub={loaded ? runs.length + ' runs · limit ' + limit : null}
        live={asLive(d)}
        onReload={reload}
      >
        {/* n={null}: State's own n===0 branch prints "nothing yet", which is exactly the
            claim this payload cannot support. The zero-state is rendered below instead. */}
        <State e={e} loading={loading} n={null} />

        <Row>
          <span style={dim}>limit</span>
          <select
            aria-label="trace limit"
            value={limit}
            onChange={(ev) => { setOpen(null); setLimit(Number(ev.target.value)); }}
            style={inpS as any}
          >
            {LIMITS.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <span style={dim}>backend accepts 1..50 (Query(20, ge=1, le=50)); anything else is a 422</span>
        </Row>

        {loaded && runs.length === 0 && (
          <div style={{ ...amber, marginTop: 8 }}>
            <Tag c="var(--amber)">0 runs · CANNOT DISTINGUISH</Tag>
            <div style={{ marginTop: 5 }}>{AMBIGUITY}</div>
          </div>
        )}

        {loaded && runs.map((r: any, i: number) => {
          const elapsed = num(r && r.elapsed);
          const steps = Array.isArray(r && r.steps) ? r.steps : [];
          const term = str(r && r.terminated_by);
          const ok = r && r.ok === true;
          const bad = r && r.ok === false;
          const when = rel(r && r.ts);
          return (
            <div key={i}>
              <Row>
                <button
                  className="tool-btn"
                  onClick={() => setOpen(open === i ? null : i)}
                  title={open === i ? 'collapse steps' : 'expand steps'}
                >
                  {open === i ? '▾' : '▸'}
                </button>
                <span style={{ ...mono, fontSize: 11 }}>
                  {str(r && r.pipeline_name) || str(r && r.pipeline_id) || '(pipeline id absent)'}
                </span>
                {elapsed != null && <Tag>{elapsed} s total</Tag>}
                <Tag>{steps.length} steps</Tag>
                {ok && <Tag c="var(--green)">ok</Tag>}
                {bad && <Tag c="var(--red)">failed</Tag>}
                {!ok && !bad && <Tag c="var(--amber)">ok flag absent</Tag>}
                {/* additive, never instead of the status: an early stop is not a failure */}
                {term && <Tag c="var(--amber)">terminated by {term}</Tag>}
                <span style={{ ...dim, marginLeft: 'auto' }} title={abs(r && r.ts) || ''}>
                  {when || '(no ts)'}
                </span>
              </Row>
              {open === i && (
                <div style={{ padding: '2px 0 8px 18px' }}>
                  {str(r && r.pipeline_id) && (
                    <div style={dim}>pipeline_id {r.pipeline_id}</div>
                  )}
                  {term && (
                    <div style={{ ...amber, marginTop: 3 }}>
                      terminated_by = {term} — that step's terminate_when guard fired (H10.12) and the
                      run stopped early. It is reported beside the ok flag, not in place of it.
                    </div>
                  )}
                  {steps.length === 0
                    ? <div style={{ ...amber, marginTop: 4 }}>this run carries no steps array</div>
                    : steps.map((s: any, j: number) => <StepRow key={j} s={s} />)}
                </div>
              )}
            </div>
          );
        })}

        <div style={{ ...dim, marginTop: 8, lineHeight: 1.55 }}>
          <div>
            WorkflowEngine keeps the last 50 runs in memory (deque(maxlen=50)); history survives a
            restart only when JARVIS_WORKFLOW_PERSIST is set, which mirrors the ring to
            data/workflows/runs.json. Neither the ring size nor the persistence flag has a route,
            so no control for them is drawn here — these are facts, not settings.
          </div>
          <div style={{ marginTop: 3 }}>
            A subflow step recurses into WorkflowEngine.run, so a nested sub-pipeline is stashed as
            its own ADDITIONAL row: this list is not one row per operator action.
          </div>
          <div style={{ marginTop: 3 }}>
            elapsed is in seconds; each step's elapsed_ms is in milliseconds. Both are labelled above.
          </div>
          <div style={{ marginTop: 3 }}>
            user-tier read — GET {TRACES_PATH} is Depends(user_guard) (WFL-132: the previews are
            personal content), so no admin token is attached.
          </div>
        </div>
      </Card>

      {/* ══ HIERARCHICAL RUN ══════════════════════════════════════════════════ */}
      <Card
        title="HIERARCHICAL RUN"
        sub={rosterUsable ? roster.length + ' agents' : 'roster unavailable'}
        live={asLive(ros.d, rosterUsable)}
        onReload={ros.reload}
      >
        <div style={{ ...dim, lineHeight: 1.55, marginBottom: 6 }}>
          POST {HIER_PATH} — a manager agent runs each crew member toward the goal, retries a
          failed member (optionally onto its fallback agent), then synthesizes one final answer.
        </div>
        <div style={{ ...amber, marginBottom: 8 }}>
          A hierarchical run does NOT appear in the trace list above: HierarchicalManager bypasses
          WorkflowEngine entirely and nothing stashes it in the trace ring. This panel therefore
          does not reload that list after a run.
        </div>

        {ros.e && (
          <div style={{ ...amber, marginBottom: 6 }}>
            agent roster unavailable · {ros.e} — the run control is disabled rather than falling
            back to free-typed agent names, because the backend silently routes an unknown agent
            normally while echoing the name you sent, which would make a misrouted run look correct.
          </div>
        )}
        {rosterLoaded && roster.length === 0 && (
          <div style={{ ...amber, marginBottom: 6 }}>
            the roster read returned 0 agents — GET {AGENTS_PATH} answers with an empty list both
            when no agent is registered and when the orchestrator is absent, so this panel cannot
            offer a validated agent to run. The run control is disabled.
          </div>
        )}

        <div style={{ ...dim, marginTop: 2 }}>goal (required)</div>
        <textarea
          aria-label="goal"
          value={goal}
          onChange={(ev) => setGoal(ev.target.value)}
          placeholder="what the crew should achieve"
          style={taS as any}
        />

        <Row>
          <span style={dim}>manager</span>
          <select
            aria-label="manager"
            value={manager}
            onChange={(ev) => setManager(ev.target.value)}
            style={inpS as any}
          >
            <option value="">(key omitted — backend default "jarvis")</option>
            {roster.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <span style={dim}>the key is dropped when unset; manager:"" would run an unrouted synthesis</span>
        </Row>
        {rosterUsable && !manager && roster.indexOf('jarvis') === -1 && (
          <div style={amber}>
            the backend's default manager is "jarvis" and the live roster does not list it — an
            unknown manager falls through to normal routing while the response still echoes it.
            Pick a manager from the roster.
          </div>
        )}

        <Row>
          <span style={dim}>max_retries</span>
          <input
            aria-label="max_retries"
            type="number"
            min={0}
            max={10}
            value={maxRetries}
            onChange={(ev) => setMaxRetries(ev.target.value)}
            style={{ ...(inpS as any), width: 72 }}
          />
          <span style={dim}>
            sent as typed; the backend coerces it with int() and enforces its own cap
            (MAX_RETRIES_CAP), refusing out-of-range itself — its message is shown verbatim below
          </span>
        </Row>

        <div style={{ ...dim, marginTop: 8 }}>
          crew — each member is sent as an OBJECT (a bare string entry is an unhandled 500).
          Blank fields are omitted so the backend applies its own defaults.
        </div>
        <div style={{ ...dim, marginTop: 2 }}>
          prompt template placeholders: {'{_goal}'} and the id of any EARLIER crew member. An
          unknown placeholder renders as the empty string, silently.
        </div>
        {crew.map((m, i) => (
          <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid var(--panel-line)' }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={dim}>#{i + 1}</span>
              <input
                aria-label={'crew ' + (i + 1) + ' id'}
                value={m.id}
                onChange={(ev) => setMember(i, 'id', ev.target.value)}
                placeholder="id (blank → agent name)"
                style={{ ...(inpS as any), width: 150 }}
              />
              <select
                aria-label={'crew ' + (i + 1) + ' agent'}
                value={m.agent}
                onChange={(ev) => setMember(i, 'agent', ev.target.value)}
                style={inpS as any}
              >
                <option value="">agent…</option>
                {roster.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
              <select
                aria-label={'crew ' + (i + 1) + ' fallback'}
                value={m.fallback}
                onChange={(ev) => setMember(i, 'fallback', ev.target.value)}
                style={inpS as any}
              >
                <option value="">fallback: none</option>
                {roster.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
              <button
                className="tool-btn"
                onClick={() => setCrew((c) => c.filter((_, j) => j !== i))}
                title="remove crew member"
                style={{ marginLeft: 'auto' }}
              >
                ✕
              </button>
            </div>
            <input
              aria-label={'crew ' + (i + 1) + ' prompt'}
              value={m.prompt}
              onChange={(ev) => setMember(i, 'prompt', ev.target.value)}
              placeholder="prompt template (blank → {_goal})"
              style={{ ...(inpS as any), width: '100%', marginTop: 4 }}
            />
          </div>
        ))}

        <Row>
          <button
            className="tool-btn"
            onClick={() => setCrew((c) => c.concat([{ id: '', agent: '', fallback: '', prompt: '{_goal}' }]))}
          >
            + add crew member
          </button>
          <button className="tool-btn" onClick={run} disabled={!canRun} style={{ marginLeft: 'auto' }}>
            {busy ? 'running… (the request stays open for the whole run)' : 'run hierarchical'}
          </button>
        </Row>
        {!crewComplete && crew.length > 0 && (
          <div style={dim}>every crew member needs an agent from the roster before this can run</div>
        )}
        <div style={{ ...dim, marginTop: 3 }}>
          one agent turn per crew member, ×(max_retries+1) worst case, plus one synthesis turn —
          all inside the open POST, with no per-step timeout on this path.
        </div>

        {err && (
          <div style={{ ...red, marginTop: 8 }}>
            <Tag c="var(--red)">REFUSED</Tag>
            <div style={{ marginTop: 4 }}>refused · {err}</div>
            <div style={{ ...dim, marginTop: 3 }}>
              printed exactly as the backend sent it (err.body.error, else err.body.detail, else the
              transport message); no status is translated into a sentence here.
            </div>
          </div>
        )}

        {res && (
          <div style={{ marginTop: 8 }}>
            <Row>
              {runOk && <Tag c="var(--green)">ok</Tag>}
              {runBad && <Tag c="var(--red)">run failed</Tag>}
              {!runOk && !runBad && <Tag c="var(--amber)">ok flag absent</Tag>}
              {str(res.manager) && <Tag>manager {res.manager}</Tag>}
              <Tag>{members.length} members</Tag>
              {redistributed.length > 0 && (
                <Tag c="var(--amber)">redistributed: {redistributed.join(', ')}</Tag>
              )}
            </Row>
            {runBad && (
              <div style={red}>
                HTTP 200 with ok:false — at least one crew member failed validation. This is a failed
                run, not an answer.
              </div>
            )}

            {members.map((m: any, i: number) => {
              const mok = m && m.ok === true;
              const att = num(m && m.attempts);
              const out = typeof (m && m.output) === 'string' ? m.output : null;
              return (
                <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid var(--panel-line)' }}>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                    <span style={{ ...mono, fontSize: 11 }}>{str(m && m.id) || '(id absent)'}</span>
                    <Tag>agent that produced the final attempt: {str(m && m.agent) || '(absent)'}</Tag>
                    {att != null && <Tag>{att} attempts</Tag>}
                    {m && m.redistributed === true && (
                      <Tag c="var(--amber)">redistributed → {str(m.agent) || '(absent)'}</Tag>
                    )}
                    {mok
                      ? <Tag c="var(--green)">ok</Tag>
                      : <Tag c="var(--red)">member failed</Tag>}
                  </div>
                  {out === null
                    ? <div style={amber}>(no output string in this member record)</div>
                    : <Json v={out} max={160} />}
                  {out === AGENT_ERR && (
                    <div style={dim}>
                      the backend returns this fixed string for any agent exception and deliberately
                      withholds the underlying cause, so none is shown here.
                    </div>
                  )}
                </div>
              );
            })}

            <div style={{ ...dim, marginTop: 6 }}>manager synthesis (final)</div>
            {typeof res.final === 'string' && res.final !== ''
              ? <Json v={res.final} max={200} />
              : <div style={amber}>(final was empty — the crew produced no results to synthesize)</div>}
            {runBad && (
              <div style={red}>
                this synthesis was produced over FAILED member outputs; it is not a validated answer.
              </div>
            )}
          </div>
        )}

        <div style={{ ...dim, marginTop: 8, lineHeight: 1.55 }}>
          user-tier write — POST {HIER_PATH} is Depends(user_guard), so act() is used and no admin
          token is attached. Agent, fallback and manager come from the live roster because the
          backend does not validate agent names: an unknown one falls through to normal routing while
          the response echoes the name that was sent.
        </div>
      </Card>
    </>
  );
}
