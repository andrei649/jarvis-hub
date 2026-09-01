// @ts-nocheck
/* CREATIVE panel — the P4 planner + the P3 market brief. fetch is mocked (same idiom as
   coach.test.tsx) so the REAL api/client path runs: that is what proves the refusal branch
   is live, because apiPost's failMutation is what attaches `err.body` to the throw that the
   panel's onErr renders verbatim.

   The three claims these tests defend, in order of how badly they would mislead an operator:
     · a platform the backend DISCARDED is never shown as planned (the picked-vs-returned diff)
     · a 4xx renders as a refusal with the backend's own words, never as an empty result
     · a missing market number is "no quote" / "no positions priced", never 0             */
import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CreativePanel } from './creative';

const DISCLAIMER = 'Informational only — not financial advice. Figures derive from the data '
  + 'you provided; verify independently. Any trade or transfer requires your explicit approval.';

/** Route mock: {'<path fragment>': {body, status?}}. An unmocked path answers 404 loudly. */
const routes = (map) => {
  const fn = vi.fn().mockImplementation((url) => {
    const key = Object.keys(map).find((k) => String(url).includes(k));
    if (!key) {
      return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: `no mock for ${url}` }) });
    }
    const v = map[key];
    const status = v.status || 200;
    return Promise.resolve({ ok: status < 400, status, json: async () => v.body });
  });
  global.fetch = fn;
  return fn;
};
const bodyOf = (fn, path) => JSON.parse(fn.mock.calls.find((c) => String(c[0]).includes(path))[1].body);

const SAVED = (watches) => ({ body: { watches, stats: { total: watches.length, with_low: 0, with_high: 0 } } });

const STAGES = [
  { id: 'script', title: 'Script & beats', kind: 'creative.draft', generator: 'llm', inputs: [], generated: false },
  { id: 'image_prompts', title: 'Image prompts', kind: 'creative.draft', generator: 'llm', inputs: ['<script>'], generated: false },
  { id: 'render', title: 'Render frames/clips', kind: 'creative.plan', generator: 'media_gen', inputs: ['<image_prompts>'], generated: false },
  { id: 'assemble', title: 'Assemble cut', kind: 'creative.draft', generator: 'editor', inputs: ['<render>'], generated: false },
  { id: 'export', title: 'Export packs', kind: 'creative.draft', generator: 'exporter', inputs: ['<assemble>'], generated: false },
];
const README_PACK = {
  target: 'readme', filename: 'nerva-launch-readme.png', aspect: '16:9', width: 1200,
  height: 630, format: 'png', caption_kind: 'markdown-embed', max_seconds: 0, generated: false,
};

describe('CreativePanel — the planner never claims to have generated anything', () => {
  it('names the platforms the backend DROPPED and the one it SUBSTITUTED', async () => {
    const fn = routes({
      '/api/market/watchlist/saved': SAVED([]),
      '/api/creative/plan': {
        body: {
          goal: 'nerva launch', format: 'short-video', slug: 'nerva-launch',
          stages: STAGES, exports: [README_PACK],
          provenance: { source_inputs: [], generated: false, note: 'plan only — render/publish are owner-gated' },
        },
      },
    });
    render(<CreativePanel />);

    // the operator asks for youtube + tiktok: readme off, tiktok typed in verbatim
    fireEvent.click(screen.getByLabelText('platform readme'));
    fireEvent.change(screen.getByPlaceholderText('other platform (sent verbatim)'), { target: { value: 'tiktok' } });
    fireEvent.click(screen.getByText('+ platform'));
    fireEvent.change(screen.getByPlaceholderText('goal (what this campaign is for)'), { target: { value: 'nerva launch' } });
    fireEvent.click(screen.getByText('plan'));

    await waitFor(() => expect(screen.getByText(/dropped · youtube, tiktok/)).toBeTruthy());
    expect(screen.getByText(/backend substituted · readme/)).toBeTruthy();

    // what was actually sent — no hardcoded platform list
    expect(bodyOf(fn, '/api/creative/plan').platforms).toEqual(['youtube', 'tiktok']);

    // the standing "nothing was produced" statement + the backend's own provenance note
    expect(screen.getByText('plan only · nothing generated · render and publish are owner-gated')).toBeTruthy();
    expect(screen.getByText(/plan only — render\/publish are owner-gated/)).toBeTruthy();
    // 5 stages + 1 export pack, each carrying generated:false read off the response
    expect(screen.getAllByText('not generated').length).toBe(6);
    // stage[0] had no inputs — that is stated, not left blank
    expect(screen.getByText(/script · no source inputs/)).toBeTruthy();
    // readme's max_seconds 0 is "not a timed medium", never "max 0s"
    expect(screen.getByText(/still image · not timed/)).toBeTruthy();
    expect(screen.queryByText(/max 0s/)).toBeNull();
  });

  it('renders a 422 from /api/creative/plan as a refusal with the pydantic msg intact', async () => {
    routes({
      '/api/market/watchlist/saved': SAVED([]),
      '/api/creative/plan': {
        status: 422,
        body: { detail: [{ type: 'string_too_long', loc: ['body', 'goal'], msg: 'String should have at most 500 characters' }] },
      },
    });
    render(<CreativePanel />);
    fireEvent.click(screen.getByText('plan'));

    await waitFor(() => expect(screen.getByText(
      'refused · 422 · goal: String should have at most 500 characters',
    )).toBeTruthy());
    // the success branch is NOT taken: no stage, no substitution diff
    expect(screen.queryByText('not generated')).toBeNull();
    expect(screen.queryByText(/backend substituted/)).toBeNull();
  });

  it('renders an empty export-packs answer as a real 200 with no spec, not as an error', async () => {
    routes({
      '/api/market/watchlist/saved': SAVED([]),
      '/api/creative/export-packs': { body: { packs: [] } },
    });
    const { container } = render(<CreativePanel />);

    fireEvent.click(screen.getByLabelText('target readme'));
    fireEvent.change(screen.getByPlaceholderText('other target (sent verbatim)'), { target: { value: 'tiktok' } });
    fireEvent.click(screen.getByText('+ target'));
    fireEvent.click(screen.getByText('specs'));

    await waitFor(() => expect(screen.getByText(
      /no export spec for tiktok — supported: instagram, readme, youtube/,
    )).toBeTruthy());
    expect(container.textContent).not.toContain('refused');
  });
});

describe('CreativePanel — the market brief reads the body, not the status', () => {
  const briefBody = (over) => ({
    headline: 'no market data', alerts: [], breached: 0, disclaimer: DISCLAIMER,
    snapshot: { net_worth: 0, positions: [], by_kind: {}, count: 0, disclaimer: DISCLAIMER },
    quotes: { live: false, source: 'provided' },
    ...over,
  });

  it('seeds watches from the saved list and renders a null price as "no quote", never 0', async () => {
    const fn = routes({
      '/api/market/watchlist/saved': SAVED([{ symbol: 'AAPL', low: 240, high: null, note: '' }]),
      '/api/market/brief': {
        body: briefBody({
          headline: '1 watch(es) · 0 breached · net worth 0',
          alerts: [{
            symbol: 'AAPL', price: null, low: 240, high: null, status: 'no_quote',
            breached: false, message: 'AAPL: no quote supplied', note: '', disclaimer: DISCLAIMER,
          }],
        }),
      },
    });
    render(<CreativePanel />);
    await waitFor(() => expect(screen.getByDisplayValue('AAPL')).toBeTruthy());

    fireEvent.click(screen.getByText('brief'));
    await waitFor(() => expect(screen.getByText('no quote')).toBeTruthy());

    expect(bodyOf(fn, '/api/market/brief').watches).toEqual([{ symbol: 'AAPL', low: 240, high: null, note: '' }]);
    expect(screen.getByText('AAPL: no quote supplied')).toBeTruthy();
    // never a zero standing in for a number nobody measured
    expect(screen.queryByText('0')).toBeNull();
    expect(screen.getByText('no positions priced')).toBeTruthy();
    // the disclaimer is a backend non-negotiable — verbatim, untruncated
    expect(screen.getByText(DISCLAIMER)).toBeTruthy();
  });

  it('prints quotes.degraded.reason VERBATIM when live was requested and the feed was not there', async () => {
    routes({
      '/api/market/watchlist/saved': SAVED([{ symbol: 'AAPL', low: 240, high: null, note: '' }]),
      '/api/market/brief': {
        body: briefBody({
          quotes: {
            live: false, source: 'provided', missing: ['AAPL'],
            degraded: { reason: 'stock-quotes plugin unavailable or disabled', needs: [] },
          },
        }),
      },
    });
    render(<CreativePanel />);
    await waitFor(() => expect(screen.getByDisplayValue('AAPL')).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/fill missing quotes/));
    fireEvent.click(screen.getByText('brief'));

    await waitFor(() => expect(screen.getByText(
      /degraded · stock-quotes plugin unavailable or disabled/,
    )).toBeTruthy());
    expect(screen.getByText('live requested · served from provided quotes')).toBeTruthy();
    expect(screen.getByText(/no price for · AAPL/)).toBeTruthy();
    expect(screen.getByText('quotes · provided')).toBeTruthy();
    expect(screen.queryByText('quotes · live')).toBeNull();
  });

  it('counts the positions the snapshot silently dropped', async () => {
    routes({
      '/api/market/watchlist/saved': SAVED([]),
      '/api/market/brief': { body: briefBody({}) },
    });
    render(<CreativePanel />);

    fireEvent.click(screen.getByText('+ position'));
    fireEvent.click(screen.getByText('+ position'));
    const syms = screen.getAllByPlaceholderText('position symbol');
    fireEvent.change(syms[0], { target: { value: 'BTC' } });
    fireEvent.change(syms[1], { target: { value: 'VWCE' } });   // both left unpriced
    fireEvent.click(screen.getByText('brief'));

    await waitFor(() => expect(screen.getByText(
      /2 position\(s\) dropped — qty and price must both be numbers; nothing is guessed/,
    )).toBeTruthy());
    expect(screen.getByText('no positions priced')).toBeTruthy();
    // the headline verbatim — it appears in the card sub AND in the result row
    expect(screen.getAllByText('no market data').length).toBeGreaterThan(0);
  });

  it('renders a 403 on the brief as a refusal and clears the previous success', async () => {
    routes({
      '/api/market/watchlist/saved': SAVED([]),
      '/api/market/brief': {
        body: briefBody({
          headline: '0 watch(es) · 0 breached · net worth 120',
          snapshot: {
            net_worth: 120, count: 1, by_kind: { crypto: 120 }, disclaimer: DISCLAIMER,
            positions: [{ symbol: 'BTC', kind: 'crypto', qty: 2, price: 60, value: 120, weight: 1 }],
          },
        }),
      },
    });
    render(<CreativePanel />);
    fireEvent.click(screen.getByText('+ position'));
    fireEvent.change(screen.getByPlaceholderText('position symbol'), { target: { value: 'BTC' } });
    fireEvent.change(screen.getByPlaceholderText('qty'), { target: { value: '2' } });
    fireEvent.change(screen.getByPlaceholderText('price'), { target: { value: '60' } });
    fireEvent.click(screen.getByText('brief'));
    // 120 shows twice — the net-worth cell and the position's value
    await waitFor(() => expect(screen.getAllByText('120').length).toBe(2));

    routes({
      '/api/market/watchlist/saved': SAVED([]),
      '/api/market/brief': {
        status: 403,
        body: { detail: 'user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access' },
      },
    });
    fireEvent.click(screen.getByText('brief'));

    await waitFor(() => expect(screen.getByText(
      'refused · 403 · user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access',
    )).toBeTruthy());
    expect(screen.queryAllByText('120').length).toBe(0);
  });

  it('says the saved watchlist is unavailable instead of showing an empty editor', async () => {
    routes({ '/api/market/watchlist/saved': { status: 500, body: { error: 'store unreadable' } } });
    render(<CreativePanel />);
    await waitFor(() => expect(screen.getByText(/saved watchlist unavailable/)).toBeTruthy());
  });
});
