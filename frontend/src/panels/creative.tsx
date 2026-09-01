/* CREATIVE — the client half of two shipped-but-uncalled surfaces that both answer with
   *specs*, never with anything produced: the P4 creative pipeline planner
   (POST /api/creative/plan, POST /api/creative/export-packs) and the P3 daily market
   brief (POST /api/market/brief). All three are user-tier (Depends(user_guard)).

   What the backends actually are, and what that forces on this file:

   1. NOTHING IS GENERATED. plan_pipeline (agents/core/creative/pipeline.py:53-89) sets
      `generated: False` on every stage and every export pack and returns
      provenance.note "plan only — render/publish are owner-gated". There is no render
      route and no publish route in this lane, so this panel has no render/publish button
      and never words a control as "produce" or "export the video". The amber
      "not generated" tag on each row is read off the response field, not assumed.

   2. SILENT PLATFORM SUBSTITUTION. plan_pipeline keeps only youtube|instagram|readme
      (`[p for p in platforms if p in EXPORT_TARGETS]`) and, if nothing survives,
      substitutes ["readme"]; an empty `platforms` list falls back to
      ["youtube","readme"]. Nothing in the response says a platform was discarded. So the
      panel diffs what was SENT against `exports[].target` and names both directions —
      otherwise an operator who asked for tiktok would read a plan for readme as a plan
      for tiktok.

   3. /api/creative/export-packs IS THE SAME FUNCTION as the `exports` field of a plan:
      plan_pipeline calls build_export_packs(goal or format, platforms). With the same
      title and targets the two payloads are byte-identical, so this panel does not
      pretend it is an unrelated capability. It is here for the two behaviours a plan
      cannot give you: a filename slug you choose (a goal sentence makes a terrible
      filename) and NO readme substitution — this route honestly answers {"packs": []}
      for an unmodelled target where /plan quietly invents readme. The footer says so.

   4. MARKET: the brief never refuses. market_brief has no error_json, no HTTPException
      and no 503 — an outage arrives INSIDE the body, as the `quotes` provenance block
      (routers/market.py:60-127). So the panel reads the body, not the status: live vs
      provided, the feed's own `source`/`as_of`, and `degraded.reason` printed VERBATIM.
      The five reasons the rail can emit ("stock-quotes plugin unavailable or disabled",
      "live quotes feed unavailable", "live quotes feed degraded", plus the plugin's own
      "no quotes returned for the requested symbols" / "no ticker symbols supplied") are
      never collapsed into one sentence of ours.

   5. SILENT DROPS on the market side too: portfolio_snapshot (market/analyze.py:99-112)
      discards any position without a numeric qty AND price, and reports nothing. The
      panel counts what it sent, compares it with `snapshot.count`, and names the gap.
      `alerts[].price` is null with status "no_quote" — that renders "no quote", never 0.
      `snapshot.net_worth` is 0.0 when count===0 — that renders "no positions priced",
      never "net worth 0". The DISCLAIMER is a backend non-negotiable and is printed
      verbatim, never paraphrased or truncated.

   6. NO ACTION CONTROLS. There is no route that acts on a signal: a trade or transfer is
      a separate Action-Kernel action classified IRREVERSIBLE_OR_MONEY → QUEUE. And the
      saved watchlist is READ here only, to seed the symbols — the shipped
      WatchlistPanel owns that CRUD (gap.tsx:4173).

   apiPost THROWS on 4xx, so every POST passes onErr, a refusal CLEARS that section's
   previous result, and the refusal text is the backend's own body quoted verbatim. A
   line starting "not sent" is this panel's own local guard, never something the server
   said. */
import React, { useState, useEffect, useRef } from 'react';
import { useApi, arr, mono, asLive, Card, Row, Tag, act, inpS, taS, Json } from '../panel-kit';

/* The backend's export table keys (pipeline.py:26-35), in table order for the chips and
   alphabetical in the "supported:" sentence. Matching is EXACT and lowercase. */
const TARGETS = ['youtube', 'instagram', 'readme'];
const SUPPORTED = 'instagram, readme, youtube';

/* The backend's own words, never ours. apiPost's failMutation (api/client.ts) attaches the
   parsed refusal body as `err.body`, so a 403 renders exactly "user routes disabled from
   network — set JARVIS_USER_TOKEN to enable remote access" and a 422 renders the pydantic
   detail with its `msg` intact. With no body at all it says so rather than inventing one. */
const why = (err: any): string => {
  const b: any = err?.body;
  const d = b?.detail ?? b?.error ?? b?.message;
  const txt = Array.isArray(d)
    ? d.map((x: any) => `${(x?.loc || []).slice(1).join('.')}: ${x?.msg}`).join(' · ')
    : typeof d === 'string' ? d
    : d != null ? JSON.stringify(d)
    : (err?.message || 'no response body');
  return `refused · ${err?.status ?? 'error'} · ${txt}`;
};

const Amber = ({ children }: { children?: any }) => (
  <div style={{ ...mono, fontSize: 11, color: 'var(--amber)', padding: '3px 0', lineHeight: 1.5 }}>{children}</div>
);
const Note = ({ children }: { children?: any }) => (
  <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', padding: '3px 0', lineHeight: 1.5 }}>{children}</div>
);
const Head = ({ children }: { children?: any }) => (
  <div style={{
    ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-2)',
    marginTop: 12, paddingTop: 7, borderTop: '1px solid var(--panel-line)',
  }}>{children}</div>
);

const trimmed = (v: any) => String(v ?? '').trim();
const isBadNum = (v: any) => trimmed(v) !== '' && !Number.isFinite(Number(trimmed(v)));
const orNull = (v: any) => (trimmed(v) === '' ? null : Number(trimmed(v)));

/* A pack is a delivery SPEC. `generated` is read, never assumed; readme's max_seconds 0
   means "not a timed medium" (pipeline.py:33-34), so it is never printed as "max 0s". */
const PackRow = ({ p }: { p: any }) => (
  <Row>
    <Tag c="var(--accent-light)">{String(p?.target ?? '—')}</Tag>
    <span style={{ ...mono, color: 'var(--ink-2)' }}>{String(p?.filename ?? '—')}</span>
    <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
      <Tag>{p?.width}×{p?.height} · {p?.aspect} · {p?.format}</Tag>
      <Tag>{String(p?.caption_kind ?? '—')}</Tag>
      {typeof p?.max_seconds === 'number'
        ? (p.max_seconds > 0 ? <Tag>max {p.max_seconds}s</Tag> : <Tag>still image · not timed</Tag>)
        : null}
      {p?.generated === false
        ? <Tag c="var(--amber)">not generated</Tag>
        : p?.generated === true
          ? <Tag c="var(--green)">generated</Tag>
          : <Tag c="var(--amber)">generated flag absent</Tag>}
    </span>
  </Row>
);

type WatchRow = { symbol: string; low: string; high: string; quote: string; note: string };
type PosRow = { symbol: string; qty: string; price: string; kind: string };

export function CreativePanel() {
  // ── 1 · creative plan ────────────────────────────────────────────
  const [goal, setGoal] = useState('');
  const [format, setFormat] = useState('short-video');
  const [picked, setPicked] = useState<string[]>(['youtube', 'readme']);
  const [extra, setExtra] = useState('');
  const [inputsText, setInputsText] = useState('');
  const [plan, setPlan] = useState<any>(null);
  const [planSent, setPlanSent] = useState<any>(null);
  const [planErr, setPlanErr] = useState('');

  // ── 2 · export specs (its own title + its own targets, see header note 3) ──
  const [packTitle, setPackTitle] = useState('');
  const [packTargets, setPackTargets] = useState<string[]>(['readme']);
  const [packExtra, setPackExtra] = useState('');
  const [packs, setPacks] = useState<any[]>([]);
  const [packsSent, setPacksSent] = useState<string[]>([]);
  const [packsRan, setPacksRan] = useState(false);
  const [packsErr, setPacksErr] = useState('');

  // ── 3 · market brief ─────────────────────────────────────────────
  const saved = useApi('/api/market/watchlist/saved');
  const seeded = useRef(false);
  const [rows, setRows] = useState<WatchRow[]>([]);
  const [positions, setPositions] = useState<PosRow[]>([]);
  const [live, setLive] = useState(false);
  const [brief, setBrief] = useState<any>(null);
  const [briefSent, setBriefSent] = useState<any>(null);
  const [briefErr, setBriefErr] = useState('');
  const [showRaw, setShowRaw] = useState(false);

  /* Seed the watch rows ONCE from the owner's curated list. If that GET fails the panel
     says so — an empty editor would read as "you watch nothing". */
  useEffect(() => {
    if (seeded.current || !saved.d) return;
    seeded.current = true;
    const w = arr(saved.d, 'watches').map((x: any) => ({
      symbol: String(x?.symbol ?? ''),
      low: x?.low == null ? '' : String(x.low),
      high: x?.high == null ? '' : String(x.high),
      quote: '',
      note: String(x?.note ?? ''),
    }));
    if (w.length) setRows(w);
  }, [saved.d]);

  // ── plan ─────────────────────────────────────────────────────────
  const togglePlatform = (t: string) =>
    setPicked((p) => (p.includes(t) ? p.filter((x) => x !== t) : [...p, t]));
  const addPlatform = () => {
    const t = extra.trim();
    if (!t) return;
    if (!picked.includes(t)) setPicked([...picked, t]);
    setExtra('');
  };

  const runPlan = () => {
    const inputs = inputsText.split('\n').map((s) => s.trim()).filter(Boolean);
    if (inputs.length > 200) {
      setPlan(null);
      setPlanErr('not sent · inputs cap is max_length=200 (BriefBody, creative.py:26)');
      return;
    }
    if (picked.length > 20) {
      setPlan(null);
      setPlanErr('not sent · platforms cap is max_length=20 (BriefBody, creative.py:25)');
      return;
    }
    setPlanSent({ platforms: [...picked], format: format.trim() });
    act('/api/creative/plan',
      { goal: goal.trim(), format: format.trim(), platforms: picked, inputs },
      (r: any) => { setPlan(r); setPlanErr(''); },
      (err: any) => { setPlan(null); setPlanErr(why(err)); });
  };

  const planExports = arr(plan, 'exports');
  const gotTargets = planExports.map((p: any) => String(p?.target ?? ''));
  const sentPlatforms: string[] = planSent ? planSent.platforms : [];
  const dropped = sentPlatforms.filter((p) => !gotTargets.includes(p));
  const added = gotTargets.filter((t: string) => !sentPlatforms.includes(t));
  /* `str(b.get("format") or "short-video")` — a blank format is replaced without comment
     too, so the same picked-vs-returned rule applies to it. */
  const formatSwapped = !!(plan && planSent && String(plan.format ?? '') !== String(planSent.format ?? ''));

  // ── export specs ─────────────────────────────────────────────────
  const toggleTarget = (t: string) =>
    setPackTargets((p) => (p.includes(t) ? p.filter((x) => x !== t) : [...p, t]));
  const addTarget = () => {
    const t = packExtra.trim();
    if (!t) return;
    if (!packTargets.includes(t)) setPackTargets([...packTargets, t]);
    setPackExtra('');
  };

  const runPacks = () => {
    if (packTargets.length > 20) {
      setPacks([]); setPacksRan(false);
      setPacksErr('not sent · targets cap is max_length=20 (ExportBody, creative.py:32)');
      return;
    }
    setPacksSent([...packTargets]);
    act('/api/creative/export-packs',
      { title: packTitle.trim(), targets: packTargets },
      (r: any) => { setPacks(arr(r, 'packs')); setPacksRan(true); setPacksErr(''); },
      (err: any) => { setPacks([]); setPacksRan(false); setPacksErr(why(err)); });
  };

  // ── market ───────────────────────────────────────────────────────
  const setRow = (i: number, k: keyof WatchRow, v: string) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const setPos = (i: number, k: keyof PosRow, v: string) =>
    setPositions(positions.map((p, j) => (j === i ? { ...p, [k]: v } : p)));

  const runBrief = () => {
    const wRows = rows.filter((r) => trimmed(r.symbol));
    const pRows = positions.filter((p) => trimmed(p.symbol));
    const stop = (m: string) => { setBrief(null); setBriefErr(m); };
    for (const r of wRows) {
      if (isBadNum(r.low) || isBadNum(r.high)) {
        stop(`not sent · watch ${trimmed(r.symbol)}: low and high must be numbers or blank`); return;
      }
      if (isBadNum(r.quote)) {
        stop(`not sent · watch ${trimmed(r.symbol)}: the quote must be a number or blank`); return;
      }
    }
    for (const p of pRows) {
      if (isBadNum(p.qty) || isBadNum(p.price)) {
        stop(`not sent · position ${trimmed(p.symbol)}: qty and price must be numbers or blank `
          + '(a blank is sent as null and portfolio_snapshot drops the position — nothing is guessed)');
        return;
      }
    }
    const quotes: Record<string, number> = {};
    wRows.forEach((r) => { if (trimmed(r.quote) !== '') quotes[trimmed(r.symbol)] = Number(trimmed(r.quote)); });
    const body = {
      watches: wRows.map((r) => ({
        symbol: trimmed(r.symbol), low: orNull(r.low), high: orNull(r.high),
        note: String(r.note || '').slice(0, 200),
      })),
      quotes,
      live,
      positions: pRows.map((p) => ({
        symbol: trimmed(p.symbol), qty: orNull(p.qty), price: orNull(p.price),
        kind: trimmed(p.kind) || 'other',
      })),
    };
    setBriefSent({ live, positions: pRows.length, watches: wRows.length });
    act('/api/market/brief', body,
      (r: any) => { setBrief(r); setBriefErr(''); },
      (err: any) => { setBrief(null); setBriefErr(why(err)); });
  };

  const q = brief && brief.quotes && typeof brief.quotes === 'object' ? brief.quotes : null;
  const snap = brief && brief.snapshot && typeof brief.snapshot === 'object' ? brief.snapshot : null;
  const snapCount = snap && typeof snap.count === 'number' ? snap.count : 0;
  const alerts = arr(brief, 'alerts');
  const missing = arr(q, 'missing');
  const degraded = q && q.degraded && typeof q.degraded === 'object' ? q.degraded : null;
  const droppedPositions = briefSent && snap ? Math.max(0, briefSent.positions - snapCount) : 0;
  const byKind = snap && snap.by_kind && typeof snap.by_kind === 'object' ? snap.by_kind : {};

  return (
    <>
      {/* ══ CREATIVE PIPELINE ═════════════════════════════════════ */}
      <Card
        title="CREATIVE"
        live={asLive(plan || (packsRan ? packs : null))}
        sub={plan ? `${String(plan.slug ?? '')} · ${String(plan.format ?? '')}` : 'planner'}
      >
        <Note>
          A pipeline PLANNER and a delivery-spec table. It never generates media and never
          publishes: every stage and every pack comes back with <b>generated: false</b>, and
          the render / publish wiring is owner-gated (docs/OWNER_TASKS.md). There is no render
          route and no publish route behind this card, so there is no button for either.
        </Note>

        <Head>BRIEF · POST /api/creative/plan</Head>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '5px 0' }}>
          <input
            style={{ ...inpS, flex: '1 1 180px', minWidth: 140 }}
            placeholder="goal (what this campaign is for)"
            maxLength={500}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
          <input
            style={{ ...inpS, flex: '0 1 130px' }}
            placeholder="format"
            maxLength={40}
            value={format}
            onChange={(e) => setFormat(e.target.value)}
          />
        </div>
        <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap', padding: '3px 0' }}>
          <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>platforms</span>
          {TARGETS.map((t) => (
            <button
              key={t}
              className="tool-btn"
              aria-label={`platform ${t}`}
              onClick={() => togglePlatform(t)}
              style={picked.includes(t)
                ? { borderColor: 'var(--accent-light)', color: 'var(--accent-light)' }
                : { opacity: 0.55 }}
            >{t}</button>
          ))}
          <input
            style={{ ...inpS, flex: '0 1 150px' }}
            placeholder="other platform (sent verbatim)"
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
          />
          <button className="tool-btn" onClick={addPlatform}>+ platform</button>
        </div>
        {picked.filter((p) => !TARGETS.includes(p)).length > 0 && (
          <Note>
            {picked.filter((p) => !TARGETS.includes(p)).join(', ')} will be sent as typed. The
            backend keeps only an exact lowercase match against its table — anything else is
            discarded silently, and the diff below is what tells you.
          </Note>
        )}
        <textarea
          style={{ ...taS, minHeight: 52, fontSize: 11 }}
          placeholder="source inputs — one per line (optional; free text, this is what stage 1 is told it may use)"
          value={inputsText}
          onChange={(e) => setInputsText(e.target.value)}
        />
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '5px 0' }}>
          <button className="tool-btn" onClick={runPlan}>plan</button>
          <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>
            {picked.length ? `${picked.length} platform(s) picked` : 'no platform picked — the backend substitutes youtube + readme'}
          </span>
        </div>
        {planErr && <Amber>{planErr}</Amber>}

        {plan && (
          <>
            <Amber>plan only · nothing generated · render and publish are owner-gated</Amber>
            {plan.provenance && plan.provenance.note != null && (
              <Note>provenance.note · {String(plan.provenance.note)}</Note>
            )}
            {dropped.length > 0 && (
              <Amber>
                dropped · {dropped.join(', ')} — not modelled by the backend (it matches
                lowercase {SUPPORTED} exactly); no spec was planned for {dropped.length === 1 ? 'it' : 'them'}
              </Amber>
            )}
            {added.length > 0 && (
              <Amber>
                backend substituted · {added.join(', ')} — not requested; plan_pipeline never
                returns an empty export set
              </Amber>
            )}
            {formatSwapped && (
              <Amber>
                format · the backend planned &ldquo;{String(plan.format ?? '')}&rdquo;, not
                &ldquo;{String(planSent.format ?? '')}&rdquo; — a blank format falls back to
                short-video
              </Amber>
            )}
            {arr(plan, 'stages').map((s: any, i: number) => (
              <Row key={`stage-${s?.id ?? i}`}>
                <span style={{ ...mono, color: 'var(--accent-light)' }}>{String(s?.id ?? '—')}</span>
                <span style={{ ...mono, color: 'var(--ink-2)' }}>{String(s?.title ?? '')}</span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                  <Tag>{String(s?.kind ?? '')}</Tag>
                  <Tag>{String(s?.generator ?? '')}</Tag>
                  {s?.generated === false
                    ? <Tag c="var(--amber)">not generated</Tag>
                    : s?.generated === true
                      ? <Tag c="var(--green)">generated</Tag>
                      : <Tag c="var(--amber)">generated flag absent</Tag>}
                </span>
              </Row>
            ))}
            {arr(plan, 'stages').length > 0 && (
              <Note>
                {arr(plan, 'stages').map((s: any, i: number) => (
                  <div key={`in-${s?.id ?? i}`}>
                    {String(s?.id ?? '—')} · {arr(s, 'inputs').length
                      ? `inputs · ${arr(s, 'inputs').join(', ')}`
                      : 'no source inputs'}
                  </div>
                ))}
              </Note>
            )}
            {planExports.length > 0 && <Head>PLANNED EXPORT SPECS · plan.exports</Head>}
            {planExports.map((p: any, i: number) => <PackRow key={`px-${p?.target ?? i}`} p={p} />)}
            {showRaw && <Json v={plan} max={200} />}
          </>
        )}

        {/* ── export specs — own title, own targets, no substitution ── */}
        <Head>EXPORT SPECS · POST /api/creative/export-packs</Head>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '5px 0' }}>
          <input
            style={{ ...inpS, flex: '1 1 160px', minWidth: 130 }}
            placeholder="asset filename title"
            maxLength={200}
            value={packTitle}
            onChange={(e) => setPackTitle(e.target.value)}
          />
          {TARGETS.map((t) => (
            <button
              key={t}
              className="tool-btn"
              aria-label={`target ${t}`}
              onClick={() => toggleTarget(t)}
              style={packTargets.includes(t)
                ? { borderColor: 'var(--accent-light)', color: 'var(--accent-light)' }
                : { opacity: 0.55 }}
            >{t}</button>
          ))}
          <input
            style={{ ...inpS, flex: '0 1 140px' }}
            placeholder="other target (sent verbatim)"
            value={packExtra}
            onChange={(e) => setPackExtra(e.target.value)}
          />
          <button className="tool-btn" onClick={addTarget}>+ target</button>
          <button className="tool-btn" onClick={runPacks}>specs</button>
        </div>
        {packsErr && <Amber>{packsErr}</Amber>}
        {packs.map((p: any, i: number) => <PackRow key={`sp-${p?.target ?? i}`} p={p} />)}
        {packsRan && !packsErr && packs.length === 0 && (
          <Note>
            no export spec for {packsSent.join(', ') || '(no target picked)'} — supported: {SUPPORTED}.
            That is a real 200 with an empty list, not a failure.
          </Note>
        )}
        <Note>
          same spec table as the plan&apos;s exports (both are build_export_packs), keyed off this
          filename title instead of the goal slug — and with no readme substitution: an
          unmodelled target answers an empty list here, where /plan quietly plans readme instead.
        </Note>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', paddingTop: 6 }}>
          <label style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', display: 'flex', gap: 4, alignItems: 'center' }}>
            <input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} />
            raw response
          </label>
        </div>
        <Note>
          user-tier POSTs (act) · /api/creative/plan, /api/creative/export-packs · planner only:
          no media is generated and nothing is published here. Neither route has a component
          guard or a 503, so this card never shows an &ldquo;unavailable&rdquo; state — the only
          failures possible are auth and validation, shown verbatim.
        </Note>
      </Card>

      {/* ══ MARKET BRIEF ══════════════════════════════════════════ */}
      <Card
        title="MARKET BRIEF"
        live={asLive(brief)}
        sub={brief ? String(brief.headline ?? '') : 'analysis only'}
      >
        {saved.e
          ? <Note>saved watchlist unavailable · {saved.e} — enter symbols manually below</Note>
          : <Note>
              symbols seeded from your saved watchlist (read-only here — MARKET WATCHLIST owns
              adding and removing). Quotes are yours unless you ask for live.
            </Note>}

        <Head>WATCHES · symbol · band · your quote</Head>
        {rows.map((r, i) => (
          <div key={`w-${i}`} style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap', padding: '3px 0' }}>
            <input style={{ ...inpS, flex: '0 0 76px' }} placeholder="symbol" maxLength={24}
              value={r.symbol} onChange={(e) => setRow(i, 'symbol', e.target.value)} />
            <input style={{ ...inpS, width: 58 }} placeholder="low"
              value={r.low} onChange={(e) => setRow(i, 'low', e.target.value)} />
            <input style={{ ...inpS, width: 58 }} placeholder="high"
              value={r.high} onChange={(e) => setRow(i, 'high', e.target.value)} />
            <input style={{ ...inpS, width: 74 }} placeholder="your quote"
              value={r.quote} onChange={(e) => setRow(i, 'quote', e.target.value)} />
            <button className="tool-btn" title={`remove watch ${i + 1}`}
              onClick={() => setRows(rows.filter((_, j) => j !== i))}>✕</button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '5px 0' }}>
          <button className="tool-btn"
            onClick={() => setRows([...rows, { symbol: '', low: '', high: '', quote: '', note: '' }])}>+ watch</button>
          <label style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', display: 'flex', gap: 4, alignItems: 'center' }}>
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
            fill missing quotes from the keyless stock-quotes feed (delayed Stooq closes)
          </label>
        </div>
        <Note>
          the feed is only asked for WATCH symbols you did not price yourself. It never prices a
          position — qty and price in the portfolio below are always your own numbers.
        </Note>

        <Head>POSITIONS · qty × price (both must be numbers or the row is dropped)</Head>
        {positions.map((p, i) => (
          <div key={`p-${i}`} style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap', padding: '3px 0' }}>
            <input style={{ ...inpS, flex: '0 0 76px' }} placeholder="position symbol" maxLength={24}
              value={p.symbol} onChange={(e) => setPos(i, 'symbol', e.target.value)} />
            <input style={{ ...inpS, width: 62 }} placeholder="qty"
              value={p.qty} onChange={(e) => setPos(i, 'qty', e.target.value)} />
            <input style={{ ...inpS, width: 68 }} placeholder="price"
              value={p.price} onChange={(e) => setPos(i, 'price', e.target.value)} />
            <input style={{ ...inpS, width: 74 }} placeholder="kind" maxLength={24}
              value={p.kind} onChange={(e) => setPos(i, 'kind', e.target.value)} />
            <button className="tool-btn" title={`remove position ${i + 1}`}
              onClick={() => setPositions(positions.filter((_, j) => j !== i))}>✕</button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '5px 0' }}>
          <button className="tool-btn"
            onClick={() => setPositions([...positions, { symbol: '', qty: '', price: '', kind: 'other' }])}>+ position</button>
          <button className="tool-btn" onClick={runBrief}>brief</button>
          <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>kind is free text — the backend does not enum it</span>
        </div>
        {briefErr && <Amber>{briefErr}</Amber>}

        {brief && (
          <>
            <Row>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>{String(brief.headline ?? '')}</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                {q ? <Tag c={q.live ? 'var(--green)' : 'var(--amber)'}>quotes · {q.live ? 'live' : 'provided'}</Tag> : null}
                {q && q.source ? <Tag>source {String(q.source)}</Tag> : null}
                {q && q.as_of ? <Tag>as of {String(q.as_of)}</Tag> : null}
              </span>
            </Row>
            {!q && <Note>the response carried no quotes provenance block</Note>}
            {q && briefSent && briefSent.live && q.live !== true && (
              <Amber>live requested · served from provided quotes</Amber>
            )}
            {degraded && (
              <Amber>
                degraded · {String(degraded.reason ?? '(no reason field)')}
                {arr(degraded, 'needs').length ? ` · needs · ${arr(degraded, 'needs').join(', ')}` : ''}
              </Amber>
            )}
            {q && briefSent && briefSent.live && q.live !== true && !degraded && (
              <Note>
                nothing to fetch — every watched symbol already carried a quote you supplied, so
                the feed was not called (the backend returns early in that case)
              </Note>
            )}
            {missing.length > 0 && <Note>no price for · {missing.join(', ')}</Note>}

            {alerts.map((a: any, i: number) => (
              <Row key={`a-${a?.symbol ?? i}`}>
                <span style={{ ...mono, color: 'var(--accent-light)' }}>{String(a?.symbol ?? '—')}</span>
                <span style={{ ...mono, color: a?.price == null ? 'var(--ink-3)' : 'var(--ink-2)' }}>
                  {a?.price == null ? 'no quote' : String(a.price)}
                </span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                  <Tag>{a?.low == null ? '−∞' : String(a.low)}–{a?.high == null ? '+∞' : String(a.high)}</Tag>
                  <Tag c={a?.breached ? 'var(--amber)' : a?.status === 'no_quote' ? 'var(--ink-3)' : 'var(--ink-2)'}>
                    {String(a?.status ?? '')}
                  </Tag>
                </span>
              </Row>
            ))}
            {alerts.map((a: any, i: number) => (
              <Note key={`am-${a?.symbol ?? i}`}>
                {String(a?.message ?? '')}{a?.note ? ` · ${String(a.note)}` : ''}
              </Note>
            ))}

            <Head>PORTFOLIO</Head>
            {!snap && <Note>the response carried no snapshot block</Note>}
            {snap && snapCount === 0 && <Note>no positions priced</Note>}
            {snap && snapCount > 0 && (
              <>
                <Row>
                  <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>net worth</span>
                  <span style={{ ...mono, color: 'var(--ink-2)' }}>{String(snap.net_worth)}</span>
                  <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                    {Object.keys(byKind).map((k) => <Tag key={k}>{k} {String(byKind[k])}</Tag>)}
                  </span>
                </Row>
                {arr(snap, 'positions').map((p: any, i: number) => (
                  <Row key={`sp-${p?.symbol ?? i}`}>
                    <span style={{ ...mono, color: 'var(--accent-light)' }}>{String(p?.symbol ?? '—')}</span>
                    <Tag>{String(p?.kind ?? 'other')}</Tag>
                    <span style={{ ...mono, color: 'var(--ink-3)' }}>{String(p?.qty)} × {String(p?.price)}</span>
                    <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                      <Tag>{String(p?.value)}</Tag>
                      <Tag>{typeof p?.weight === 'number' ? `${(p.weight * 100).toFixed(1)}%` : 'no weight'}</Tag>
                    </span>
                  </Row>
                ))}
              </>
            )}
            {droppedPositions > 0 && (
              <Amber>
                {droppedPositions} position(s) dropped — qty and price must both be numbers;
                nothing is guessed
              </Amber>
            )}
            {brief.disclaimer
              ? <div style={{ ...mono, fontSize: 10, color: 'var(--ink-2)', padding: '7px 0 0', lineHeight: 1.5 }}>
                  {String(brief.disclaimer)}
                </div>
              : <Amber>the response carried no disclaimer field</Amber>}
            {showRaw && <Json v={brief} max={220} />}
          </>
        )}

        <Note>
          user-tier · GET /api/market/watchlist/saved (read, to seed) + POST /api/market/brief ·
          analysis only. No trade or transfer is proposed here: acting on a signal is a separate
          approval-held kernel action (IRREVERSIBLE_OR_MONEY → QUEUE). Watchlist CRUD lives in
          MARKET WATCHLIST. The brief route never answers 4xx of its own — an outage arrives as
          the quotes.degraded block above, printed in the backend&apos;s own words.
        </Note>
      </Card>
    </>
  );
}
