/* COACH — the client half of the 0.43 Learning Coach pack (spaced repetition +
   curriculum planning).

   The pack is documented as stateless: "the caller holds the card state; this module
   computes the schedule" (agents/core/coach/pack.py:1-17). There is no GET route, no
   coach store and no server-side id namespace — grepping /api/coach across the repo hits
   only the generated frontend/src/api/schema.gen.ts. So the missing half of this
   capability is precisely a client that OWNS a deck, which is what this panel is. The
   deck lives in this browser and nowhere else, and the panel says so on screen rather
   than implying Nerva remembers the owner's cards. It is deliberately NOT a "paste your
   cards JSON" box: the request bodies are composed from real panel state the operator
   built card by card, and the two human inputs — what to learn, and how well he just
   recalled a card — are irreducibly human. Nothing in this repo produces either.

   Three POSTs, all user-tier (Depends(user_guard)), all via act(...) with an onErr:
     /api/coach/session     — pick today's due + new cards out of the deck
     /api/coach/review      — grade one card; SM-2 → next interval / ease / due_day
     /api/coach/curriculum  — order topics by prereqs, split into sessions

   Honesty notes that shaped this file:
     * apiPost THROWS on 401/403/422/429/500, so every call passes onErr and a refusal
       CLEARS that section's previous result — a stale success can never sit under a
       refusal and read as though the write landed. The refusal text is the backend's
       own body, quoted verbatim; the five distinct causes are never collapsed into one
       fixed sentence.
     * The router lazily imports a pure, offline, dependency-free module. It has no
       component guard and cannot answer 503, so this panel never renders an
       "unavailable" state for it — and there is no enable/disable route to expose.
     * plan_curriculum silently drops a topic with a falsy id (`[t for t in topics if
       t.get("id")]`) and collapses duplicate ids (last wins), with NO field in the
       response reporting either. The panel refuses both locally, in its own words,
       prefixed "not sent" so a local guard is never mistaken for something the server
       said.
     * counts.deferred, unknown_prereqs and cycles are the pack's own honesty outputs.
       They are rendered whenever non-empty; burying them would turn a truncated backlog
       or an unschedulable prereq loop into a clean-looking plan.
     * The LIVE chip only appears once a POST has actually returned a payload that is
       still on screen. Locally computed deck state is not backend data. */
import React, { useState, useEffect } from 'react';
import { arr, mono, asLive, Card, Row, Tag, act, inpS, Json } from '../panel-kit';

type CoachCard = {
  id: string;
  label?: string;
  repetitions?: number;
  interval?: number;
  ease?: number;
  due_day?: number;
  last_quality?: number;
  lapsed?: boolean;
  [k: string]: any;
};

type TopicRow = { id: string; title: string; prereqs: string };

const DECK_KEY = 'hud.coach.deck';
const DAY_MS = 86400000;
/* The pack's `now_day` is an integer day index on the CALLER's clock (pack.py:32-42) —
   the server has no clock of its own here, so the panel supplies one and shows it, or
   the due_day numbers coming back would be uninterpretable. */
const dayIndex = () => Math.floor(Date.now() / DAY_MS);

const slug = (s: string) => s.toLowerCase().trim()
  .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);

const loadDeck = (): CoachCard[] => {
  try {
    const raw = localStorage.getItem(DECK_KEY);
    const v = raw ? JSON.parse(raw) : null;
    return Array.isArray(v) ? v.filter((c) => c && typeof c.id === 'string' && c.id) : [];
  } catch { return []; }
};
const saveDeck = (d: CoachCard[]) => {
  try { localStorage.setItem(DECK_KEY, JSON.stringify(d)); } catch { /* private mode / quota */ }
};

/* The backend's own words, never ours. apiPost's failMutation (api/client.ts) attaches
   the parsed refusal body as `err.body`, so this renders exactly "user token required",
   exactly "user routes disabled from network — set JARVIS_USER_TOKEN to enable remote
   access", exactly "rate limit exceeded", and the raw pydantic 422 detail array as JSON.
   Nothing is guessed: with no body at all it says so. */
const why = (err: any): string => {
  const b: any = err?.body;
  const d = b?.detail ?? b?.error ?? b?.message;
  const txt = typeof d === 'string' ? d
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
const num = (v: any) => (typeof v === 'number' ? String(v) : v == null ? '—' : String(v));

/* SM-2 recall grades. These labels describe what the OPERATOR means by the grade he is
   about to give — they are the algorithm's own 0–5 scale, not text the backend emits.
   The only backend-defined fact stated on screen is the pack's: "a grade < 3 is a lapse:
   the repetition count resets and the card is seen again tomorrow" (pack.py:35-36), and
   whether a given review actually lapsed is read off the response's `lapsed` field. */
const GRADES: { q: number; hint: string }[] = [
  { q: 0, hint: 'grade 0 — total blackout' },
  { q: 1, hint: 'grade 1 — wrong; recognised the answer when shown' },
  { q: 2, hint: 'grade 2 — wrong; the answer felt familiar' },
  { q: 3, hint: 'grade 3 — correct, with serious difficulty' },
  { q: 4, hint: 'grade 4 — correct, after hesitation' },
  { q: 5, hint: 'grade 5 — perfect recall' },
];

export function CoachPanel() {
  const [deck, setDeck] = useState<CoachCard[]>(() => loadDeck());
  useEffect(() => { saveDeck(deck); }, [deck]);

  const [busy, setBusy] = useState<string>('');

  // ── 1 · deck editor (browser-local) ──────────────────────────────
  const [newLabel, setNewLabel] = useState('');
  const [newId, setNewId] = useState('');
  const [idTouched, setIdTouched] = useState(false);
  const [deckMsg, setDeckMsg] = useState<string>('');

  // ── 2 · today's session ──────────────────────────────────────────
  const [newLimit, setNewLimit] = useState('20');
  const [maxReviews, setMaxReviews] = useState('200');
  const [sessionRes, setSessionRes] = useState<any>(null);
  const [sessionErr, setSessionErr] = useState<string>('');

  // ── 3 · grade a card ─────────────────────────────────────────────
  const [selId, setSelId] = useState('');
  const [reviewRes, setReviewRes] = useState<any>(null);
  const [reviewErr, setReviewErr] = useState<string>('');

  // ── 4 · curriculum ───────────────────────────────────────────────
  const [topics, setTopics] = useState<TopicRow[]>([]);
  const [perSession, setPerSession] = useState('3');
  const [planRes, setPlanRes] = useState<any>(null);
  const [planErr, setPlanErr] = useState<string>('');

  const [showRaw, setShowRaw] = useState(false);

  const today = dayIndex();
  const draftId = (idTouched ? newId : slug(newLabel)).trim();

  /* Grade candidates: the cards the LAST session response actually selected, falling
     back to the whole deck before a session has been built. Every option id came from
     something the operator typed — no id is ever hardcoded to make a POST look wired. */
  const sessionIds: string[] = sessionRes
    ? [...arr(sessionRes, 'due'), ...arr(sessionRes, 'new')].map((c: any) => c && c.id).filter(Boolean)
    : [];
  const gradable = Array.from(new Set(sessionRes ? sessionIds : deck.map((c) => c.id)))
    .filter((id) => deck.some((c) => c.id === id));
  const selected = deck.find((c) => c.id === selId) || null;

  useEffect(() => {
    if (!sessionRes) return;
    // Clear the selection when the session yields NOTHING, do not just skip. The old guard
    // was `sessionIds.length && !sessionIds.includes(selId)`, so an empty session (due: [],
    // new: []) left `selId` on whatever was picked before it was built. `gradable` is then
    // [] and the select shows only the placeholder — but `selected` still resolves that
    // stale id out of the deck, so the grade buttons stayed ENABLED and posted a review for
    // a card the session does not contain and the operator cannot see selected.
    if (!sessionIds.includes(selId)) setSelId(sessionIds[0] || '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionRes]);

  // ── deck writes ──────────────────────────────────────────────────
  const addCard = () => {
    const label = newLabel.trim();
    const id = draftId;
    if (!label && !id) { setDeckMsg('not added · a card needs a label'); return; }
    if (!id) {
      setDeckMsg('not added · blank id — the pack keys a card by `id` and the review '
        + 'response echoes `id: null` for a card that has none, so it could never be '
        + 'written back into this deck');
      return;
    }
    if (deck.some((c) => c.id === id)) {
      setDeckMsg(`not added · duplicate id "${id}" — a review result is written back to `
        + 'the deck by id, and two cards sharing one id could not be told apart');
      return;
    }
    if (deck.length >= 5000) {
      setDeckMsg('not added · the deck is at the route cap (SessionBody.cards, '
        + 'max_length=5000) — remove a card first');
      return;
    }
    setDeck([...deck, { id, label: label || id }]);
    setNewLabel(''); setNewId(''); setIdTouched(false);
    setDeckMsg(`added · ${id}`);
  };

  const dropCard = (id: string) => {
    setDeck(deck.filter((c) => c.id !== id));
    setDeckMsg(`removed · ${id}`);
  };

  // ── 2 · POST /api/coach/session ──────────────────────────────────
  const buildSession = () => {
    if (!deck.length) return;
    const nl = Number(newLimit);
    const mr = Number(maxReviews);
    if (!Number.isFinite(nl) || !Number.isFinite(mr)) {
      setSessionRes(null);
      setSessionErr('not sent · new_limit and max_reviews must be numbers');
      return;
    }
    setBusy('session');
    act('/api/coach/session',
      { cards: deck, now_day: today, new_limit: Math.trunc(nl), max_reviews: Math.trunc(mr) },
      (r: any) => { setSessionRes(r); setSessionErr(''); setBusy(''); },
      (err: any) => { setSessionRes(null); setSessionErr(why(err)); setBusy(''); });
  };

  // ── 3 · POST /api/coach/review ───────────────────────────────────
  const grade = (q: number) => {
    if (!selected) return;
    const id = selected.id;
    setBusy('review');
    act('/api/coach/review',
      { card: selected, quality: q, now_day: today },
      (r: any) => {
        setReviewRes(r); setReviewErr(''); setBusy('');
        /* The returned card IS the new state — the server persists nothing, so if this
           deck does not take it, the review is lost. It is only written back when the
           response carries the id we sent; an `id: null` echo is reported, not patched. */
        if (r && r.id === id) setDeck((d) => d.map((c) => (c.id === id ? { ...r } : c)));
      },
      (err: any) => { setReviewRes(null); setReviewErr(why(err)); setBusy(''); });
  };

  // ── 4 · POST /api/coach/curriculum ───────────────────────────────
  const addTopic = () => setTopics([...topics, { id: '', title: '', prereqs: '' }]);
  const setTopic = (i: number, k: keyof TopicRow, v: string) =>
    setTopics(topics.map((t, j) => (j === i ? { ...t, [k]: v } : t)));
  const dropTopic = (i: number) => setTopics(topics.filter((_, j) => j !== i));
  const topicsFromDeck = () => {
    setTopics(deck.map((c) => ({ id: c.id, title: String(c.label || c.id), prereqs: '' })));
    setPlanErr(''); setPlanRes(null);
  };

  const planCurriculum = () => {
    const rows = topics.map((t) => ({
      id: t.id.trim(),
      title: t.title.trim(),
      prereqs: t.prereqs.split(',').map((s) => s.trim()).filter(Boolean),
    }));
    const refuseLocal = (m: string) => { setPlanRes(null); setPlanErr(m); };
    if (!rows.length) { refuseLocal('not sent · no topics — add one'); return; }
    if (rows.some((r) => !r.id)) {
      refuseLocal('not sent · a topic with a blank id is dropped by plan_curriculum '
        + '(`[t for t in topics if t.get("id")]`) and nothing in the response says so — '
        + 'give every topic an id');
      return;
    }
    const dup = rows.map((r) => r.id).find((id, i, a) => a.indexOf(id) !== i);
    if (dup) {
      refuseLocal(`not sent · duplicate topic id "${dup}" — plan_curriculum keys topics `
        + 'by id (last wins), so the earlier one would vanish from `order` with no '
        + 'server-side signal');
      return;
    }
    if (rows.length > 2000) {
      refuseLocal('not sent · topics cap is max_length=2000 (CurriculumBody)');
      return;
    }
    const ps = Number(perSession);
    if (!Number.isFinite(ps)) { refuseLocal('not sent · per_session must be a number'); return; }
    setBusy('plan');
    act('/api/coach/curriculum',
      {
        topics: rows.map((r) => (r.title ? { id: r.id, title: r.title, prereqs: r.prereqs }
          : { id: r.id, prereqs: r.prereqs })),
        per_session: Math.trunc(ps),
      },
      (r: any) => { setPlanRes(r); setPlanErr(''); setBusy(''); },
      (err: any) => { setPlanRes(null); setPlanErr(why(err)); setBusy(''); });
  };

  const counts = sessionRes && sessionRes.counts ? sessionRes.counts : null;
  const deferred = counts && typeof counts.deferred === 'number' ? counts.deferred : 0;
  const unknownPrereqs = arr(planRes, 'unknown_prereqs');
  const cycles = arr(planRes, 'cycles');
  const label = (c: any) => (c && (c.label || c.title || c.id)) || '(no label)';

  return (
    <Card
      title="COACH"
      live={asLive(sessionRes || reviewRes || planRes)}
      sub={`${deck.length} card${deck.length === 1 ? '' : 's'} · browser-local`}
    >
      <Note>
        SM-2 spaced repetition + prerequisite curriculum planning. The coach API is
        stateless and stores nothing — no GET route, no server-side deck, no id namespace —
        so <b>this deck lives in this browser only</b> and a returned card is the new state
        only because this panel keeps it. The pack schedules and orders; it never generates
        lesson content.
      </Note>

      {/* ── 1 · DECK ─────────────────────────────────────────────── */}
      <Head>DECK · local</Head>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '5px 0' }}>
        <input
          style={{ ...inpS, flex: '1 1 150px', minWidth: 120 }}
          placeholder="card label"
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
        />
        <input
          style={{ ...inpS, flex: '0 1 120px' }}
          placeholder="id (slug)"
          value={idTouched ? newId : slug(newLabel)}
          onChange={(e) => { setIdTouched(true); setNewId(e.target.value); }}
        />
        <button className="tool-btn" onClick={addCard}>add card</button>
      </div>
      {deckMsg && (
        deckMsg.startsWith('not added')
          ? <Amber>{deckMsg}</Amber>
          : <Note>{deckMsg}</Note>
      )}
      {!deck.length && <Note>deck is empty — add a card above.</Note>}
      {deck.map((c) => (
        <Row key={c.id}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{c.label || c.id}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
            {typeof c.repetitions === 'number' ? <Tag>reps {c.repetitions}</Tag> : null}
            {typeof c.interval === 'number' ? <Tag>interval {c.interval}d</Tag> : null}
            {typeof c.ease === 'number' ? <Tag>ease {c.ease}</Tag> : null}
            {typeof c.due_day === 'number' ? <Tag>due_day {c.due_day}</Tag> : null}
            {c.due_day == null && !c.repetitions ? <Tag>never reviewed</Tag> : null}
            <button className="tool-btn" title={`remove ${c.id}`} onClick={() => dropCard(c.id)}>✕</button>
          </span>
        </Row>
      ))}

      {/* ── 2 · SESSION ──────────────────────────────────────────── */}
      <Head>TODAY&apos;S SESSION · POST /api/coach/session</Head>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '5px 0' }}>
        <label style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>new_limit</label>
        <input type="number" min={0} max={1000} style={{ ...inpS, width: 66 }}
          value={newLimit} onChange={(e) => setNewLimit(e.target.value)} />
        <label style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>max_reviews</label>
        <input type="number" min={1} max={5000} style={{ ...inpS, width: 72 }}
          value={maxReviews} onChange={(e) => setMaxReviews(e.target.value)} />
        <button className="tool-btn" onClick={buildSession} disabled={!deck.length || busy === 'session'}>
          build session
        </button>
        <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>now_day {today}</span>
      </div>
      {!deck.length && <Note>deck is empty — add a card. (An empty deck would answer a
        true 0/0/0, which is not the same statement as &ldquo;nothing due today&rdquo;.)</Note>}
      {sessionErr && <Amber>{sessionErr}</Amber>}
      {counts && (
        <>
          <Row>
            <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>counts</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              <Tag>due_total {num(counts.due_total)}</Tag>
              <Tag>due_selected {num(counts.due_selected)}</Tag>
              <Tag>new_total {num(counts.new_total)}</Tag>
              <Tag>new_selected {num(counts.new_selected)}</Tag>
              <Tag c={deferred > 0 ? 'var(--amber)' : undefined}>deferred {num(counts.deferred)}</Tag>
            </span>
          </Row>
          {deferred > 0 && (
            <Amber>{deferred} deferred by the caps — backlog, not lost (counts.deferred,
              the backend&apos;s own number)</Amber>
          )}
          {arr(sessionRes, 'due').map((c: any, i: number) => (
            <Row key={`due-${c?.id ?? i}`}>
              <Tag>due</Tag>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>{label(c)}</span>
              {typeof c?.due_day === 'number' && (
                <span style={{ marginLeft: 'auto' }}><Tag>due_day {c.due_day}</Tag></span>
              )}
            </Row>
          ))}
          {arr(sessionRes, 'new').map((c: any, i: number) => (
            <Row key={`new-${c?.id ?? i}`}>
              <Tag>new</Tag>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>{label(c)}</span>
            </Row>
          ))}
          {showRaw && <Json v={sessionRes} max={180} />}
        </>
      )}

      {/* ── 3 · REVIEW ───────────────────────────────────────────── */}
      <Head>GRADE A CARD · POST /api/coach/review</Head>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '5px 0' }}>
        <select
          aria-label="card to grade"
          style={{ ...inpS, flex: '1 1 160px', minWidth: 130 }}
          value={selId}
          onChange={(e) => setSelId(e.target.value)}
        >
          <option value="">— pick a card —</option>
          {gradable.map((id) => {
            const c = deck.find((x) => x.id === id);
            return <option key={id} value={id}>{c ? (c.label || c.id) : id}</option>;
          })}
        </select>
        {GRADES.map((g) => (
          <button
            key={g.q}
            className="tool-btn"
            title={g.hint}
            disabled={!selected || busy === 'review'}
            onClick={() => grade(g.q)}
          >{g.q}</button>
        ))}
      </div>
      <Note>
        your recall grade, 0–5 (SM-2). The pack: &ldquo;a grade &lt; 3 is a lapse: the
        repetition count resets and the card is seen again tomorrow&rdquo;. The graded card
        is sent whole and the response replaces it in this deck — nothing is stored server-side.
        {sessionRes ? '' : ' Options are the whole deck until a session is built.'}
      </Note>
      {reviewErr && <Amber>{reviewErr}</Amber>}
      {reviewRes && (
        <>
          <Row>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>{label(reviewRes)}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              <Tag>last_quality {num(reviewRes.last_quality)}</Tag>
              <Tag>repetitions {num(reviewRes.repetitions)}</Tag>
              <Tag>interval {num(reviewRes.interval)}d</Tag>
              <Tag>ease {num(reviewRes.ease)}</Tag>
              <Tag>due_day {num(reviewRes.due_day)}</Tag>
            </span>
          </Row>
          {reviewRes.lapsed === true && (
            <Amber>lapsed: true — repetitions back to {num(reviewRes.repetitions)},
              interval {num(reviewRes.interval)}d, due_day {num(reviewRes.due_day)}</Amber>
          )}
          {reviewRes.id == null && (
            <Amber>the response echoed id: null — this card was NOT written back into the
              deck, so this schedule is not held anywhere</Amber>
          )}
          {showRaw && <Json v={reviewRes} max={180} />}
        </>
      )}

      {/* ── 4 · CURRICULUM ───────────────────────────────────────── */}
      <Head>CURRICULUM · POST /api/coach/curriculum</Head>
      {topics.map((t, i) => (
        <div key={i} style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap', padding: '3px 0' }}>
          <input style={{ ...inpS, flex: '0 1 110px' }} placeholder="topic id"
            value={t.id} onChange={(e) => setTopic(i, 'id', e.target.value)} />
          <input style={{ ...inpS, flex: '1 1 130px', minWidth: 100 }} placeholder="title"
            value={t.title} onChange={(e) => setTopic(i, 'title', e.target.value)} />
          <input style={{ ...inpS, flex: '1 1 130px', minWidth: 100 }} placeholder="prereqs (ids, comma-separated)"
            value={t.prereqs} onChange={(e) => setTopic(i, 'prereqs', e.target.value)} />
          <button className="tool-btn" title={`remove topic ${i + 1}`} onClick={() => dropTopic(i)}>✕</button>
        </div>
      ))}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '5px 0' }}>
        <button className="tool-btn" onClick={addTopic}>add topic</button>
        <button className="tool-btn" onClick={topicsFromDeck} disabled={!deck.length}>use deck as topics</button>
        <label style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>per_session</label>
        <input type="number" min={1} max={100} style={{ ...inpS, width: 60 }}
          value={perSession} onChange={(e) => setPerSession(e.target.value)} />
        <button className="tool-btn" onClick={planCurriculum} disabled={!topics.length || busy === 'plan'}>
          plan curriculum
        </button>
      </div>
      {planErr && <Amber>{planErr}</Amber>}
      {planRes && (
        <>
          <Row>
            <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>order</span>
            <span style={{ marginLeft: 'auto' }}><Tag>session_count {num(planRes.session_count)}</Tag></span>
          </Row>
          {arr(planRes, 'order').map((t: any, i: number) => (
            <Row key={`ord-${t?.id ?? i}`}>
              <Tag>{i + 1}</Tag>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>{label(t)}</span>
            </Row>
          ))}
          {arr(planRes, 'sessions').map((s: any, i: number) => (
            <Row key={`sess-${i}`}>
              <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>session {i + 1}</span>
              <span style={{ ...mono, color: 'var(--ink-2)', marginLeft: 'auto', textAlign: 'right' }}>
                {(Array.isArray(s) ? s : []).map(label).join(' · ')}
              </span>
            </Row>
          ))}
          {unknownPrereqs.map((u: any, i: number) => (
            <Amber key={`unk-${i}`}>
              topic {String(u?.topic)} → missing prereq {String(u?.missing_prereq)} (edge
              ignored, not invented)
            </Amber>
          ))}
          {cycles.length > 0 && (
            <Amber>prereq cycle: {cycles.map(String).join(', ')} — planned last, not dropped</Amber>
          )}
          {showRaw && <Json v={planRes} max={200} />}
        </>
      )}

      {/* ── footer ───────────────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', paddingTop: 6 }}>
        <label style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} />
          raw response
        </label>
      </div>
      <Note>
        user-tier POSTs (act) · /api/coach/session, /api/coach/review, /api/coach/curriculum ·
        the pack is offline, deterministic and stateless — no GET, no server-side deck,
        nothing persisted; there is no enable/disable route for it. Refusals are shown with
        the backend&apos;s own status and body text; a line starting &ldquo;not sent&rdquo;
        is this panel&apos;s own local guard, not something the server said.
      </Note>
    </Card>
  );
}
