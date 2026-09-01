/* SECURITY SKILLS · MAP — the three still-uncalled routes of the 0.42 Security Skills pack
   (agents/core/routers/security_skills.py:35, :66, :73 over agents/core/security_skills/pack.py).

   The pack is a pure, offline, in-process constant: no DB, no component, no network, no
   state. That shapes every honesty decision in this file:

   1. NO attack_tactics HERE. GET /api/security-skills/frameworks returns six keys, and its
      `attack_tactics` array is byte-identical to the `tactics` array the ALREADY-SHIPPED
      SecuritySkillsPanel (frontend/src/gap.tsx:706) renders from /api/security-skills/tactics.
      Re-rendering those 14 rows would make this a duplicate-of-shipped surface. The route is
      worth wiring only because `d3fend_tactics` (7) and `csf_functions` (6) are rendered by
      NO client in the repo. So this panel deliberately drops attack_tactics on the floor and
      the `sub` line counts D3FEND/CSF — never ATT&CK.
   2. NO 503, NO availability flag, NO enable/disable control. The pack cannot fail and has
      no enabled/available field anywhere; there is no route to refresh, sync or configure the
      corpus. Rendering a "component unavailable"/SEED state would be as false as hiding one,
      so the panel offers no such control and makes no such claim.
   3. EVERY non-200 IS THE FRAMEWORK'S OWN. These three routes emit no `error`/`reason` key of
      their own — a failure is FastAPI's `detail` (a string for the 401/403 guard, an array of
      {loc,msg,type} for a 422) or the limiter's {"error":"rate limit exceeded"}. apiPost THROWS
      and carries that parsed body on err.body (api/client.ts:98-104), so both POSTs pass onErr
      and `fmtErr` prints the wire text verbatim. Nothing is invented, renamed or collapsed.
   4. `score` IS A COUNT, NOT A CONFIDENCE. map_behavior (pack.py:203) is `kw in text.lower()`
      over the 14 curated techniques' keyword lists; score is len(hits). The pack's own docstring:
      it "surfaces candidates to investigate and never asserts a definitive attribution". The
      matched substrings ride along as `evidence` and are printed verbatim so the operator sees
      WHY a row surfaced. No percentage, no verdict, no attribution.
   5. `count` IS POST-SLICE. map_behavior returns len(scored[:top_k]) — the number of rows
      SHOWN, not the number of techniques that matched. When the list fills top_k exactly the
      panel says the list is truncated instead of implying it is exhaustive.
   6. csf_gaps IS A LIMIT OF THE CURATED MAPPING, NOT A FINDING ABOUT THE OPERATOR. Verified
      against the pack: build_playbook over ALL 14 curated techniques yields csf_coverage
      ['DE','PR','RC'] and csf_gaps ['GV','ID','RS'] — because _D3FEND_TO_CSF (pack.py:161) maps
      GV to nothing, ID only to D3-MODEL and RS only to D3-EVICT, and no curated countermeasure
      uses either. GV/ID/RS are therefore permanently "uncovered". Labelling that a posture gap
      would be a fabricated security claim, so the caption states exactly what it is.
   7. UNKNOWN IDS ARE A 200, NOT AN HTTP ERROR. build_playbook reports an unrecognized id under
      `unknown` (verbatim, un-normalized) inside a 200 body — that is the only domain-level
      refusal these routes have, and it is rendered as one, in amber, JSON.stringify'd so a
      blank or whitespace id is visible rather than printing as nothing.
   8. NOTHING IS POSTED EMPTY. An empty behavior returns 200/0 candidates (reads as a failed
      match rather than an unasked question) and an empty techniques list returns all six CSF
      functions as gaps (reads as "everything uncovered"). Both buttons are disabled instead.
   9. ALL THREE ROUTES ARE user_guard — act(), not actA(); useApi without admin. The footer
      says user tier.

   The corpus is 14 of ATT&CK's 600+ techniques. The payload's own `curated`, `disclaimer` and
   `sources` are shown verbatim rather than paraphrased; this panel asserts nothing about the
   corpus on its own authority. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, inpS, taS } from '../panel-kit';

const FRAMEWORKS_PATH = '/api/security-skills/frameworks';
const MAP_PATH = '/api/security-skills/map';
const PLAYBOOK_PATH = '/api/security-skills/playbook';

const BEHAVIOR_MAX = 2000;   // MapBody.behavior max_length (security_skills.py:27)
const TOP_K_MIN = 1;         // MapBody.top_k ge (security_skills.py:28)
const TOP_K_MAX = 20;        // MapBody.top_k le
const TECHNIQUES_MAX = 50;   // PlaybookBody.techniques max_length (security_skills.py:32)

/* The refusal, straight off the wire. `detail` is a string for the 401/403 guard and an array
   of {loc,msg,type} for a 422; the limiter answers {"error":"rate limit exceeded"}. Whatever
   the body holds is printed as-is — this panel never authors a cause of its own. */
function fmtErr(err: any): string {
  const b = err && err.body;
  const d = b && b.detail;
  let detail: string;
  if (typeof d === 'string') detail = d;
  else if (Array.isArray(d)) {
    detail = d.map((x: any) => (Array.isArray(x && x.loc) ? x.loc.join('.') + ': ' : '') + ((x && x.msg) ?? JSON.stringify(x))).join(' · ');
  } else if (b && typeof b.error === 'string') detail = b.error;
  else if (b != null) detail = JSON.stringify(b);
  else detail = (err && err.message) || 'no response body';
  return 'REFUSED · ' + ((err && err.status) ?? '?') + ' · ' + detail;
}

const Refusal = ({ text }: { text: string }) => (
  <div role="alert" style={{ ...mono, marginTop: 6, padding: 6, color: 'var(--red)', border: '1px solid var(--red)', borderRadius: 4 }}>
    {text}
  </div>
);

const Head = ({ children }) => (
  <div style={{ ...mono, fontSize: 10, letterSpacing: '.06em', color: 'var(--ink-3)', margin: '10px 0 4px' }}>{children}</div>
);
const Note = ({ c, children }: { c?: any; children?: any }) => (
  <div style={{ ...mono, fontSize: 10, lineHeight: 1.5, color: c || 'var(--ink-3)', marginTop: 4 }}>{children}</div>
);

export function SecuritySkillsMapPanel() {
  const { d, e, loading, reload } = useApi(FRAMEWORKS_PATH);
  /* attack_tactics is READ BUT NEVER RENDERED — see note 1 at the top of this file. */
  const d3 = arr(d, 'd3fend_tactics');
  const csf = arr(d, 'csf_functions');
  const sources = (d && typeof (d as any).sources === 'object' && (d as any).sources) || null;

  const [behavior, setBehavior] = useState('');
  const [topK, setTopK] = useState('5');
  const [mapRes, setMapRes] = useState<any>(null);
  const [mapSent, setMapSent] = useState<any>(null);   // the top_k actually POSTed with mapRes
  const [mapErr, setMapErr] = useState<string | null>(null);

  const [checked, setChecked] = useState<string[]>([]);
  const [extra, setExtra] = useState('');
  const [pb, setPb] = useState<any>(null);
  const [pbErr, setPbErr] = useState<string | null>(null);

  const topKNum = Number(topK);
  const topKOk = Number.isInteger(topKNum) && topKNum >= TOP_K_MIN && topKNum <= TOP_K_MAX;
  const behaviorOk = behavior.trim().length > 0;

  const runMap = () => {
    if (!behaviorOk || !topKOk) return;   // never POST an empty behavior (200 + 0 candidates reads as a failed match)
    const k = topKNum;
    setPb(null); setPbErr(null); setChecked([]);
    act(MAP_PATH, { behavior: behavior.trim(), top_k: k },
      (r: any) => { setMapRes(r); setMapSent(k); setMapErr(null); },
      (err: any) => { setMapRes(null); setMapSent(null); setMapErr(fmtErr(err)); });
  };

  const cands = arr(mapRes, 'candidates');
  const toggle = (id: string) => setChecked((p) => (p.indexOf(id) >= 0 ? p.filter((x) => x !== id) : p.concat(id)));

  /* build_playbook does NOT dedupe (['T1566','T1566'] returns two identical rows) and blank
     ids land in `unknown` as '', so the selection is de-duplicated and blank-filtered here. */
  const sel = Array.from(new Set(
    checked.concat(extra.split(',').map((s) => s.trim())).filter(Boolean),
  )).slice(0, TECHNIQUES_MAX);

  const runPb = () => {
    if (sel.length === 0) return;   // never POST an empty list — it returns all six CSF functions as gaps
    act(PLAYBOOK_PATH, { techniques: sel },
      (r: any) => { setPb(r); setPbErr(null); },
      (err: any) => { setPb(null); setPbErr(fmtErr(err)); });
  };

  const pbRows = arr(pb, 'playbook');
  const unknown = arr(pb, 'unknown');
  const coverage = arr(pb, 'csf_coverage');
  const gaps = arr(pb, 'csf_gaps');

  return (
    <Card
      title="SECURITY SKILLS · MAP"
      live={asLive(d)}
      sub={d ? `${d3.length} D3FEND tactics · ${csf.length} CSF functions` : null}
      onReload={reload}
    >
      {/* ── A · DEFENSIVE FRAMEWORKS (GET, user tier) ───────────────────────────── */}
      <State e={e} loading={loading} n={d3.length + csf.length} />

      {d3.length > 0 && <Head>D3FEND DEFENSIVE TACTICS · {d3.length}</Head>}
      {d3.map((t: any, i: number) => (
        <Row key={t.id ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)', minWidth: 92 }}>{t.id}</span>
          <span style={{ ...mono, color: 'var(--ink)' }}>{t.name}</span>
          <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginLeft: 'auto', textAlign: 'right' }}>{t.summary}</span>
        </Row>
      ))}

      {csf.length > 0 && <Head>NIST CSF 2.0 FUNCTIONS · {csf.length}</Head>}
      {csf.map((f: any, i: number) => (
        <Row key={f.id ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)', minWidth: 92 }}>{f.id}</span>
          <span style={{ ...mono, color: 'var(--ink)' }}>{f.name}</span>
          <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginLeft: 'auto', textAlign: 'right' }}>{f.summary}</span>
        </Row>
      ))}

      {d && (
        <div style={{ marginTop: 8 }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <Tag>curated: {String((d as any).curated)}</Tag>
            <Tag>ATT&amp;CK tactics omitted here — already shipped in SECURITY SKILLS</Tag>
          </div>
          {typeof (d as any).disclaimer === 'string' && <Note>{(d as any).disclaimer}</Note>}
          {sources && Object.keys(sources).map((k) => (
            <Note key={k}>{k} · {String(sources[k])}</Note>
          ))}
        </div>
      )}

      {/* ── B · MAP A BEHAVIOR (POST, user tier) ────────────────────────────────── */}
      <Head>MAP A BEHAVIOR → CANDIDATE ATT&amp;CK TECHNIQUES</Head>
      <textarea
        style={taS as any}
        maxLength={BEHAVIOR_MAX}
        value={behavior}
        aria-label="behavior"
        placeholder="what was observed, in plain words (e.g. powershell base64 encoded script ran from a scheduled task and beaconed over dns tunnel)"
        onChange={(ev) => setBehavior(ev.target.value)}
      />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
        <span style={{ ...mono, fontSize: 10, color: behavior.length >= BEHAVIOR_MAX ? 'var(--amber)' : 'var(--ink-3)' }}>
          {behavior.length}/{BEHAVIOR_MAX}
        </span>
        <label style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }} htmlFor="ssm-topk">top_k</label>
        <input
          id="ssm-topk"
          type="number"
          min={TOP_K_MIN}
          max={TOP_K_MAX}
          value={topK}
          aria-label="top_k"
          onChange={(ev) => setTopK(ev.target.value)}
          style={{ ...inpS, width: 64 } as any}
        />
        <button
          className="tool-btn"
          style={{ marginLeft: 'auto' }}
          disabled={!behaviorOk || !topKOk}
          title={!behaviorOk ? 'type a behavior first — an empty body returns 200 with no candidates, which is not a result'
            : !topKOk ? 'top_k must be an integer 1–20' : 'POST ' + MAP_PATH}
          onClick={runMap}
        >map behavior</button>
      </div>
      {!topKOk && <Note c="var(--amber)">top_k must be an integer {TOP_K_MIN}–{TOP_K_MAX} (backend constraint ge={TOP_K_MIN}, le={TOP_K_MAX}) — not sent</Note>}

      {mapErr && <Refusal text={mapErr} />}

      {mapRes && !mapErr && (
        <div style={{ marginTop: 6 }}>
          <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>
            {cands.length} candidate(s) shown · heuristic {String((mapRes as any).heuristic)} · top_k {mapSent} · count (post-slice) {String((mapRes as any).count)}
          </div>
          {cands.length === mapSent && (
            <Note c="var(--amber)">list truncated at top_k — there may be more matches; raise top_k to see them</Note>
          )}
          {cands.length === 0 && (
            <Note>no candidate — none of the 14 curated ATT&amp;CK techniques' keywords appear in this text (heuristic: keyword-match). Not an all-clear.</Note>
          )}
          {cands.map((c: any, i: number) => (
            <div key={c.id ?? i} style={{ padding: '5px 0', borderBottom: '1px solid var(--panel-line)' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <input
                  type="checkbox"
                  checked={checked.indexOf(c.id) >= 0}
                  aria-label={'select ' + c.id}
                  onChange={() => toggle(c.id)}
                />
                <span style={{ ...mono, color: 'var(--ink-2)' }}>{c.id} · {c.name}</span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                  {arr(c.tactics).map((t: any) => <Tag key={String(t)}>{String(t)}</Tag>)}
                  <Tag>score {String(c.score)}</Tag>
                </span>
              </div>
              <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', paddingLeft: 22 }}>
                matched: {arr(c.evidence).join(', ')}
              </div>
            </div>
          ))}
        </div>
      )}
      <Note>keyword substring match — candidates to investigate, not attribution; score = number of matched keywords, not a confidence or a probability.</Note>

      {/* ── C · DEFENSIVE PLAYBOOK (POST, user tier) ────────────────────────────── */}
      <Head>DEFENSIVE PLAYBOOK FOR THE SELECTED TECHNIQUES</Head>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          value={extra}
          aria-label="extra technique ids"
          placeholder="extra ATT&CK ids, comma separated (e.g. T1566, T1486)"
          onChange={(ev) => setExtra(ev.target.value)}
          style={{ ...inpS, flex: 1, minWidth: 180 } as any}
        />
        <button
          className="tool-btn"
          disabled={sel.length === 0}
          title={sel.length === 0 ? 'tick a candidate above or type an ATT&CK id — an empty list returns every CSF function as a gap, which reads as "everything uncovered"' : 'POST ' + PLAYBOOK_PATH}
          onClick={runPb}
        >build playbook · {sel.length}</button>
      </div>

      {pbErr && <Refusal text={pbErr} />}

      {pb && !pbErr && (
        <div style={{ marginTop: 6 }}>
          {pbRows.map((r: any, i: number) => (
            <div key={r.id ?? i} style={{ padding: '5px 0', borderBottom: '1px solid var(--panel-line)' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ ...mono, color: 'var(--ink-2)' }}>{r.id} · {r.name}</span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                  {arr(r.tactics).map((t: any) => <Tag key={String(t)}>{String(t)}</Tag>)}
                  {arr(r.csf_functions).map((f: any) => <Tag key={'csf' + String(f)} c="var(--accent-light)">CSF {String(f)}</Tag>)}
                  {/* the field is real and future-proof; today every curated technique has a
                      countermeasure, so this tag is strictly conditional and never implied. */}
                  {r.gap === true && <Tag c="var(--amber)">NO CURATED COUNTERMEASURE</Tag>}
                </span>
              </div>
              {arr(r.countermeasures).map((cm: any, j: number) => (
                <div key={cm.id ?? j} style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', paddingLeft: 14 }}>
                  {cm.id} · {cm.name} ({cm.d3fend_tactic})
                </div>
              ))}
            </div>
          ))}

          {unknown.length > 0 && (
            <Note c="var(--amber)">
              not in the curated set: {unknown.map((u: any) => JSON.stringify(u)).join(', ')}
            </Note>
          )}

          <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
            CSF reached by this curated mapping: {coverage.join(', ') || 'none'}
          </div>
          <div style={{ ...mono, fontSize: 10, color: 'var(--amber)' }}>
            CSF not reached: {gaps.join(', ') || 'none'}
          </div>
          <Note>
            csf_gaps = functions this curated D3FEND→CSF mapping cannot reach for the selected
            techniques — NOT an assessment of your defenses. GV, ID and RS are never reachable in
            this pack (no curated countermeasure uses D3-MODEL or D3-EVICT), so they appear even
            with all 14 techniques selected.
          </Note>
          {pb.generated === false && <div style={{ marginTop: 4 }}><Tag>generated: false — curated assembly, not AI advice</Tag></div>}
        </div>
      )}

      <Note>
        user tier (user_guard) · offline curated pack, 14 of ATT&amp;CK's 600+ techniques ·
        read-only: nothing on this card changes any control, and the pack has no enable, sync or
        refresh route to offer.
      </Note>
    </Card>
  );
}
