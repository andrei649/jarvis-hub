/* LLM ROUTING — the H13.4 MoE thinking/non-thinking routing preview
   (POST /api/llm/moe/route, agents/core/routers/models_llm.py:85 → route_moe,
   agents/core/llm/moe_routing.py:38). Admin tier (admin_guard).

   What this panel is NOT allowed to imply, checked against the handlers:

   1. IT ROUTES NOTHING. `route_moe` has no production consumer: the only callers in the
      repo are this endpoint and tests/test_moe_routing_h13_4.py. hybrid_router.py /
      router.py contain no '/think' or '/no_think' path, and LLMRouter.backend_type is
      `auto | lm-studio | ollama` (router.py:33). So the truthful sentence — and the one
      in the footer — is that the request COMPUTES a decision and changes nothing on the
      running router. The panel never says "switched", "applied" or "now routing".
   2. NO FORCE / OVERRIDE TOGGLE. `route_moe(prompt, model, force)` has a force override in
      Python (moe_routing.py:39) but MoERouteBody (models_llm.py:80-82) declares only
      `prompt` and `model`; pydantic ignores extras. A toggle here would send a key the
      backend drops and then report an override that never happened.
   3. `collapses_tiers` IS A PROPERTY OF THE MODEL, NOT OF THE PROMPT
      (moe_routing.py:48 returns `supports`). thinking:false therefore has TWO different
      causes and they are rendered as two different lines:
        · collapses_tiers:false → the model is outside the MoE registry, so the answer is
          forced to /no_think whatever the prompt says;
        · collapses_tiers:true + thinking:false → the model does support thinking mode and
          the backend judged THIS prompt simple.
      Collapsing those into one sentence would tell the operator the prompt was simple when
      in fact the model was never eligible.
   4. NO CLIENT-SIDE HEURISTIC. decide_thinking_mode (moe_routing.py:26) is deliberately not
      reimplemented in TypeScript: every verdict on screen comes from the response body.
   5. NO "SUPPORTED MODELS" LIST. No route exposes MOE_MODELS, so a dropdown sourced from it
      would be frontend-invented backend state. The model field is free text defaulting to
      the backend's own pydantic default, and each answer's `collapses_tiers` reports the
      truth for the model that was actually used.
   6. NO INVENTED REFUSAL STRING. This route emits no `reason`/`error` key of its own. The
      only truthful refusal strings are pydantic's `detail` ARRAY (422) and the admin
      guard's `detail` STRING (401/403) — two shapes, rendered as two shapes, verbatim.
      A refused request has no decision, so nothing renders 0 / "off" / "/no_think" for it.
   7. The prompt/model inputs carry no maxLength: the 8000/80 caps belong to the backend and
      its verbatim 422 is what the operator should see, not a silent client truncation. An
      empty prompt is a real 200 ('/no_think'), so the button is simply disabled rather than
      showing a refusal the backend would never emit.

   apiPost THROWS on 4xx and carries the parsed body, so the call passes onErr and the
   refusal is rendered from that body — otherwise every refusal would be dead code. */
import React, { useState } from 'react';
import { mono, asLive, Card, State, Row, Tag, actA, inpS, taS, Json } from '../panel-kit';

const MOE_PATH = '/api/llm/moe/route';
const PROMPT_CAP = 8000;          // MoERouteBody.prompt  max_length (models_llm.py:81)
const MODEL_CAP = 80;             // MoERouteBody.model   max_length (models_llm.py:82)
const DEFAULT_MODEL = 'gpt-oss-20b';  // the backend's own Field() default

/* The refusal, straight from the wire. `detail` is a STRING for the admin guard
   (401 "admin token required" / 403 "admin disabled from network — …") and an ARRAY of
   {loc,msg,…} for a pydantic 422. Nothing is mapped, renamed or merged, and when the body
   holds neither shape the panel says only what it knows: the status. */
function Refusal({ err }: { err: any }) {
  const body = (err && err.body) || null;
  const detail = body ? body.detail : null;
  const asString = typeof detail === 'string' ? detail : null;
  const asList = Array.isArray(detail) ? detail : null;
  return (
    <div role="alert" style={{ marginTop: 8, padding: 6, border: '1px solid var(--red)', borderRadius: 4 }}>
      <div style={{ ...mono, color: 'var(--red)' }}>
        refused · HTTP {(err && err.status) || 'error'} · POST {MOE_PATH}
      </div>
      {asString != null && (
        <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>{asString}</div>
      )}
      {asList != null && asList.map((d, i) => (
        <div key={i} style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>
          {(Array.isArray(d && d.loc) ? d.loc : []).join('.')}: {d && d.msg}
        </div>
      ))}
      {asString == null && asList == null && (
        <>
          <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>
            no decision was computed — the response carried no readable refusal detail.
          </div>
          {body != null && <Json v={body} />}
        </>
      )}
    </div>
  );
}

/* The one state worth reading carefully. Three distinct facts, three distinct lines. */
function Verdict({ out }: { out: any }) {
  if (out.collapses_tiers === false) {
    return (
      <div style={{ ...mono, color: 'var(--amber)', marginTop: 6 }}>
        collapses_tiers: false — the backend's MoE registry has no thinking mode for
        {' '}"{String(out.model)}"; the decision is forced to /no_think whatever the prompt says.
      </div>
    );
  }
  if (out.thinking === true) {
    return (
      <div style={{ ...mono, color: 'var(--green)', marginTop: 6 }}>
        collapses_tiers: true — thinking mode on for this prompt.
      </div>
    );
  }
  return (
    <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 6 }}>
      collapses_tiers: true — this model supports thinking mode; the backend judged THIS
      prompt simple enough for /no_think.
    </div>
  );
}

export function LlmRoutingPanel() {
  const [prompt, setPrompt] = useState('');
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [out, setOut] = useState<any>(null);
  const [err, setErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const ready = prompt.trim() !== '' && !busy;

  const preview = () => {
    if (!ready) return;
    setBusy(true);
    setErr(null);
    setOut(null);
    actA(
      MOE_PATH,
      { prompt, model: model.trim() || DEFAULT_MODEL },
      (r) => { setOut(r); setBusy(false); },
      (e) => { setErr(e); setBusy(false); },
    );
  };

  return (
    <Card
      title="LLM ROUTING · MoE PREVIEW"
      live={asLive(out)}
      sub={out ? `${String(out.model)} · ${String(out.directive)}` : null}
    >
      <div style={{ ...mono, color: 'var(--ink-3)', marginBottom: 6 }}>
        Computes the H13.4 thinking / non-thinking decision for one prompt: which directive,
        how big a token budget, and whether the model can collapse the fast/deep tier split.
      </div>

      <textarea
        style={taS}
        value={prompt}
        placeholder="prompt to route (e.g. explain why the router picked this backend)"
        onChange={(e) => setPrompt(e.target.value)}
      />
      <div style={{ ...mono, color: 'var(--ink-3)', margin: '3px 0 6px' }}>
        {prompt.length} chars · backend cap {PROMPT_CAP}
      </div>

      <Row>
        <span style={{ ...mono, color: 'var(--ink-3)' }}>model</span>
        <input
          style={{ ...inpS, flex: 1 }}
          value={model}
          placeholder={DEFAULT_MODEL}
          onChange={(e) => setModel(e.target.value)}
        />
        <span style={{ ...mono, color: 'var(--ink-3)' }}>cap {MODEL_CAP}</span>
        <button className="tool-btn" disabled={!ready} onClick={preview}>PREVIEW ROUTE</button>
      </Row>
      <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 4 }}>
        free text — no route lists the backend's MoE registry, so this panel does not invent
        one; "{DEFAULT_MODEL}" is the backend's own default and each answer's collapses_tiers
        reports whether the model it used is in that registry.
      </div>
      {prompt.trim() === '' && !busy && (
        <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 4 }}>type a prompt to preview</div>
      )}

      <State e={null} loading={busy} n={null} />

      {err != null && <Refusal err={err} />}

      {out != null && (
        <div style={{ marginTop: 6 }}>
          <Row>
            <Tag c={out.directive === '/think' ? 'var(--green)' : 'var(--ink-3)'}>{String(out.directive)}</Tag>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>thinking: {String(out.thinking)}</span>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>max_tokens: {String(out.max_tokens)}</span>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>model: {String(out.model)}</span>
          </Row>
          <Verdict out={out} />
          <Json v={out} />
        </div>
      )}

      <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 8 }}>
        POST {MOE_PATH} · admin tier (X-Admin-Token).
      </div>
      <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 2 }}>
        Preview only: this request computes the decision and changes nothing on the running
        router — the live router selects its backend elsewhere.
      </div>
    </Card>
  );
}
