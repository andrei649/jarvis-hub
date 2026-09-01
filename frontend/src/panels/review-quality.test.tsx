// @ts-nocheck
/* REVIEW & QUALITY panel — GET /api/review/stats (open), GET /api/quality/scores and
   POST /api/review/flag (user-tier), plus the read-only /api/quality availability probe.
   fetch is mocked per URL, like src/panels/signals-governance.test.tsx.

   The assertions that matter are the negative ones, because every trap on this lane is a
   200 that looks like data:

     * `{"stats": {}}` from /api/review/stats must render NO rollup numbers — that empty
       dict means the component is absent, and the route never 503s, so a rendered "total 0"
       would be a fabricated measurement.
     * `{"scores": []}` is ambiguous between an idle ring and an absent monitor, and only
       the probe may resolve it — never a guess.
     * ReviewQueue.flag answers {"ok": true} on its idempotent NO-OP path, returning the
       pre-existing item with its original reason. Echoing the operator's typed reason there
       would assert a write that did not happen.
     * A 503 refusal reaches act()'s onErr, never its `then` — drop the onErr argument and
       the button reads as success. Test 5 fails in exactly that case. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ReviewQualityPanel } from './review-quality';

const STATS = '/api/review/stats';
const SCORES = '/api/quality/scores?limit=50';
const TRACES = '/api/traces?limit=25';
const PROBE = '/api/quality';
const FLAG = '/api/review/flag';

/* ReviewQueue.stats() — every key present, exactly as review_queue.py:139 builds it. */
const STATS_OK = {
  stats: {
    total: 12, pending: 5, reviewed: 7, thumbs_up: 4, thumbs_down: 2, in_dataset: 3,
    rubric_criteria: ['accuracy', 'completeness', 'tone', 'safety'],
  },
};
/* The degraded shape: orch.review_queue is None (review.py:29-30). NOT zeros, NOT a 503. */
const STATS_ABSENT = { stats: {} };

/* QualityMonitor.stats() — `n` is what proves the monitor exists. */
const PROBE_OK = { stats: { n: 3, avg_score: 0.71, min: 0.31, max: 0.94, threshold: 0.6 }, alert: { alerting: false } };
const PROBE_ABSENT = { stats: {}, alert: { alerting: false } };

/* QualityMonitor.record entries: persona keys are ABSENT unless the trace carried a
   persona profile (quality.py:197-204). */
const SCORES_OK = {
  scores: [
    { trace_id: 'abc123def456', score: 0.31, ts: 1750000000 },
    { trace_id: 'ffff11112222', score: 0.94, ts: 1749999000, persona_score: 0.82, soul_version: 'v3', agent: 'research' },
  ],
};

/* Tracer._summarize output — note there is no `quality` key, which is why a flagged
   item's score comes back null. */
const TRACE_ROW = {
  id: 'abc123def456', ts: 1750000000, channel: 'web', text_preview: 'why did the deploy fail',
  intent: 'ask', route: 'research', agents: ['research'], model: 'local/qwen',
  tokens_in: 40, tokens_out: 120, cost: 0.0, total_ms: 2100, ok: true, model_info: {},
};
const TRACES_OK = { traces: [TRACE_ROW] };

function mockRoutes(handler) {
  const fn = vi.fn(async (url, init) => {
    const u = String(url);
    const method = String((init && init.method) || 'GET').toUpperCase();
    const r = handler(u, method) || { status: 200, body: {} };
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  });
  global.fetch = fn;
  return fn;
}

/* `over` lets a case swap any single response; `post` is the /api/review/flag answer. */
const mount = (over = {}, post = null) => mockRoutes((u, m) => {
  if (u === FLAG && m === 'POST') return post || { status: 200, body: {} };
  if (u === STATS) return { status: 200, body: over.stats || STATS_OK };
  if (u === SCORES) return { status: 200, body: over.scores || SCORES_OK };
  if (u === TRACES) return { status: 200, body: over.traces || TRACES_OK };
  if (u === PROBE) return { status: 200, body: over.probe || PROBE_OK };
  return null;
});

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  vi.restoreAllMocks();
});

describe('ReviewQualityPanel — the rollup, the score ring and the flag control', () => {
  it('renders the full ReviewQueue.stats() rollup straight off the payload', async () => {
    const fn = mount();
    render(<ReviewQualityPanel />);
    await waitFor(() => expect(screen.getByText('total')).toBeTruthy());

    // every stats key reaches the screen as its own number
    ['total', 'pending', 'reviewed', '👍 thumbs up', '👎 thumbs down', 'in dataset']
      .forEach((l) => expect(screen.getByText(l)).toBeTruthy());
    expect(screen.getByText('12')).toBeTruthy();
    expect(screen.getByText('7')).toBeTruthy();
    expect(screen.getByText('4')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.getByText('5 pending')).toBeTruthy();   // the card sub
    ['accuracy', 'completeness', 'tone', 'safety'].forEach((c) => expect(screen.getByText(c)).toBeTruthy());
    expect(screen.getByText('LIVE')).toBeTruthy();

    // reviewed = up + down is NOT asserted as an identity
    expect(document.body.textContent).toMatch(/need not equal/);

    // user tier only: no admin header on ANY read
    fn.mock.calls.forEach((c) => expect((c[1] && c[1].headers || {})['X-Admin-Token']).toBeUndefined());
    // no vote / promote / threshold control is duplicated here
    expect(document.body.textContent).not.toMatch(/set threshold/);
    const btns = screen.getAllByRole('button').map((b) => b.textContent).join(' ');
    expect(btns).not.toMatch(/👍|👎|⇪/);
  });

  it('renders {"stats": {}} as an ABSENT component and prints no rollup number at all', async () => {
    mount({ stats: STATS_ABSENT });
    render(<ReviewQualityPanel />);
    await waitFor(() => expect(screen.getByText('review queue not available')).toBeTruthy());

    // the forbidden silent zero: not one rollup row may exist
    ['total', 'pending', 'reviewed', '👍 thumbs up', '👎 thumbs down', 'in dataset']
      .forEach((l) => expect(screen.queryByText(l)).toBeNull());
    expect(document.body.textContent).not.toMatch(/\d+ pending/);
    expect(screen.getByText('queue component absent')).toBeTruthy();      // the card sub
    expect(document.body.textContent).toMatch(/this is not a\s+count of zero/);
    expect(document.body.textContent).toMatch(/the route never 503s/);
    expect(screen.getByText('SEED')).toBeTruthy();
    expect(screen.queryByText('LIVE')).toBeNull();
    // no enable/turn-on control is offered for a component with no such route
    expect(screen.getAllByRole('button').map((b) => b.textContent).join(' '))
      .not.toMatch(/enable|turn on|toggle|restart/i);
  });

  it('resolves an empty score list ONLY via the probe: absent monitor vs idle ring', async () => {
    // (a) monitor not wired — /api/quality carries no stats.n
    mount({ scores: { scores: [] }, probe: PROBE_ABSENT });
    const first = render(<ReviewQualityPanel />);
    await waitFor(() => expect(screen.getByText(/quality monitor not wired/)).toBeTruthy());
    expect(document.body.textContent).toMatch(/orch\.quality is None/);
    expect(document.body.textContent).toMatch(/rather than 503/);
    expect(screen.queryByText(/no scored requests in the ring yet/)).toBeNull();
    // with no probe threshold, no cutoff may be asserted
    expect(document.body.textContent).toMatch(/no cutoff is asserted here/);
    first.unmount();

    // (b) monitor wired, ring genuinely empty — n === 0 is a real measurement
    mount({ scores: { scores: [] }, probe: { stats: { n: 0, avg_score: null, threshold: 0.6 }, alert: { alerting: false } } });
    render(<ReviewQualityPanel />);
    await waitFor(() => expect(screen.getByText(/no scored requests in the ring yet/)).toBeTruthy());
    expect(screen.queryByText(/quality monitor not wired/)).toBeNull();
    // and never a ring capacity, which no route exposes
    expect(document.body.textContent).not.toMatch(/window|capacity of|maxlen|of 50/i);
  });

  it('renders the per-request ring with the threshold colour and absent persona keys omitted', async () => {
    mount();
    render(<ReviewQualityPanel />);
    // 0.310 appears twice by design: once in the ring row, once joined onto the picker row
    // for that same trace_id, so the operator flags the turn they can see scored badly.
    await waitFor(() => expect(screen.getAllByText('0.310').length).toBe(2));
    // trace_id is shown truncated to 12 chars, exactly as the ring emitted it
    expect(screen.getByText('abc123def456')).toBeTruthy();
    expect(screen.getByText('0.940')).toBeTruthy();
    // persona axis only on the entry that carried it
    expect(screen.getByText('persona 0.820')).toBeTruthy();
    expect(screen.getByText('soul v3')).toBeTruthy();
    // the entry WITHOUT persona keys invents nothing
    expect(document.body.textContent).not.toMatch(/persona 0\.000|soul unknown|persona unknown/);
    // the cutoff is attributed to its real source
    expect(document.body.textContent).toMatch(/threshold 0\.6, read from \/api\/quality/);
  });

  it('POSTs the fetched trace row VERBATIM plus the typed reason, and shows the returned item', async () => {
    const fn = mount({}, {
      status: 200,
      body: {
        ok: true,
        item: {
          id: 'aa11bb22cc33', trace_id: 'abc123def456', text_preview: 'why did the deploy fail',
          score: null, reason: 'looks wrong', status: 'pending', verdict: null, rubric: {},
          notes: '', in_dataset: false, created_at: 1750000100, reviewed_at: null,
        },
      },
    });
    render(<ReviewQualityPanel />);
    await waitFor(() => expect(screen.getByText('why did the deploy fail')).toBeTruthy());

    // the button cannot fire until a real trace is selected — there is no field to type one into
    const flagBtn = screen.getByText('flag selected trace');
    expect(flagBtn.disabled).toBe(true);
    expect(document.body.textContent).toMatch(/no field to type or paste one into/);

    fireEvent.click(screen.getByText('○'));
    fireEvent.change(screen.getByPlaceholderText(/reason \(optional/), { target: { value: 'looks wrong' } });
    await waitFor(() => expect(screen.getByText('flag selected trace').disabled).toBe(false));
    fireEvent.click(screen.getByText('flag selected trace'));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    const post = fn.mock.calls.find((c) => String(c[0]) === FLAG);
    const body = JSON.parse(post[1].body);
    expect(body.trace).toEqual(TRACE_ROW);          // the fetched row, unaltered
    expect(body.reason).toBe('looks wrong');
    expect(post[1].headers['X-Admin-Token']).toBeUndefined();   // user tier

    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('flagged · item aa11bb22cc33 · status pending');
    expect(alert).toContain('reason: looks wrong');
    expect(alert).toContain('score —');            // null, never 0
    expect(alert).not.toMatch(/score 0\b/);
    expect(alert).toContain('carries no `quality` key');
    expect(alert).not.toMatch(/already queued/);
  });

  it('renders the 503 refusal string VERBATIM — the pin for a dropped onErr', async () => {
    mount({}, { status: 503, body: { error: 'review queue not available' } });
    render(<ReviewQualityPanel />);
    await waitFor(() => expect(screen.getByText('why did the deploy fail')).toBeTruthy());

    fireEvent.click(screen.getByText('○'));
    fireEvent.click(screen.getByText('flag selected trace'));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('refused · HTTP 503 · review queue not available');
    expect(alert).toContain('Nothing was flagged');
    // the success branch must NOT have rendered
    expect(alert).not.toMatch(/flagged · item|already queued|status pending/);
    // and the two distinct causes are never collapsed into one sentence
    expect(alert).not.toMatch(/trace required/);
  });

  it('renders the 400 "trace required" as its own distinct cause', async () => {
    mount({}, { status: 400, body: { error: 'trace required' } });
    render(<ReviewQualityPanel />);
    await waitFor(() => expect(screen.getByText('why did the deploy fail')).toBeTruthy());
    fireEvent.click(screen.getByText('○'));
    fireEvent.click(screen.getByText('flag selected trace'));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('refused · HTTP 400 · trace required');
    expect(alert).not.toMatch(/review queue not available/);
  });

  it('does NOT echo the typed reason when flag() returns a pre-existing item (idempotent no-op)', async () => {
    mount({}, {
      status: 200,
      body: {
        ok: true,
        item: {
          id: 'ee99ff88dd77', trace_id: 'abc123def456', text_preview: 'why did the deploy fail',
          score: 0.31, reason: 'auto: score 0.31 < 0.6', status: 'pending', verdict: null,
          rubric: {}, notes: '', in_dataset: false, created_at: 1749990000, reviewed_at: null,
        },
      },
    });
    render(<ReviewQualityPanel />);
    await waitFor(() => expect(screen.getByText('why did the deploy fail')).toBeTruthy());

    fireEvent.click(screen.getByText('○'));
    fireEvent.change(screen.getByPlaceholderText(/reason \(optional/), { target: { value: 'looks wrong' } });
    fireEvent.click(screen.getByText('flag selected trace'));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('already queued · reason kept: auto: score 0.31 < 0.6');
    expect(alert).toContain('was NOT applied and no new row');
    // the reason the operator typed is never presented as the item's stored reason
    expect(alert).not.toMatch(/reason: looks wrong/);
    expect(alert).not.toMatch(/^flagged ·/m);
  });

  it('renders the tracer degradation string VERBATIM and disables the flag control', async () => {
    mount({ traces: { traces: [], error: 'tracer not available' } });
    render(<ReviewQualityPanel />);
    await waitFor(() => expect(screen.getByText(/tracer not available/)).toBeTruthy());

    expect(screen.getByText('flag selected trace').disabled).toBe(true);
    expect(document.body.textContent).toMatch(/no honest body to POST/);
    // no textarea anywhere: the trace body is agent-produced evidence
    expect(document.querySelector('textarea')).toBeNull();
  });
});
