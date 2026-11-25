import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { logicalPath } from '../base-path';
import { closeHudOverlay, parseHudRoute, useHudRoute } from '../hud-routing';
import { resetPolling } from '../signals/poll';
import {
  DECISIONS_CARD_PARAM, DECISIONS_PATH, DOCKET_ANCHOR_PREFIX, HUD_ROUTE_EVENT, decisionsHref, docketAnchorId, docketHref, docketTaskFromHash,
  openDecisionsCard, openDocketEntry, useDocketSummary, useDocketTitle,
} from './links';
import { DOCKET_FEED_PATH } from './types';

afterEach(() => {
  delete window.__NERVA_BASE_PATH__;
  history.replaceState(null, '', '/v2/');
});

const routeHere = () => parseHudRoute(logicalPath(location.pathname) ?? '', location.search, location.hash);

describe('the docket anchor rule', () => {
  it('names an entry docket-entry-<id> and reads it back from a hash', () => {
    expect(DOCKET_ANCHOR_PREFIX).toBe('docket-entry-');
    expect(docketAnchorId(42)).toBe('docket-entry-42');
    expect(docketTaskFromHash('#docket-entry-42')).toBe(42);
    for (const hash of ['', '#docket-entry-', '#docket-entry-0', '#docket-entry-x', '#entry-4', '#docket-entry-4/5']) {
      expect(docketTaskFromHash(hash), hash).toBeNull();
    }
  });

  it('links to Home with the entry\'s hash, keeping the base path and the query', () => {
    window.__NERVA_BASE_PATH__ = '/one';
    history.replaceState(null, '', '/one/v2/memory?demo=1&frame=ledger#something');
    expect(docketHref(7)).toBe('/one/v2/cockpit?demo=1&frame=ledger#docket-entry-7');
    openDocketEntry(7);
    expect(location.pathname).toBe('/one/v2/cockpit');
    expect(location.search).toBe('?demo=1&frame=ledger');
    expect(location.hash).toBe('#docket-entry-7');
    expect(routeHere()).toMatchObject({ valid: true, mode: 'cockpit', panel: null });
  });

  it('leaves a Decisions card behind when it links to the docket', () => {
    history.replaceState(null, '', '/v2/console/decision-inbox?frame=ledger&card=5');
    expect(docketHref(7)).toBe('/v2/cockpit?frame=ledger#docket-entry-7');
  });
});

describe('the Decisions link', () => {
  it('is a ready href that keeps the base path and the query, sets the card and drops the hash', () => {
    window.__NERVA_BASE_PATH__ = '/one';
    history.replaceState(null, '', '/one/v2/cockpit?demo=1&frame=ledger&card=5#docket-entry-7');
    expect(DECISIONS_PATH).toBe('/v2/console/decision-inbox');
    expect(DECISIONS_CARD_PARAM).toBe('card');
    expect(decisionsHref(12)).toBe('/one/v2/console/decision-inbox?demo=1&frame=ledger&card=12');
    history.replaceState(null, '', '/one/v2/memory');
    expect(decisionsHref(12)).toBe('/one/v2/console/decision-inbox?card=12');
  });

  it('opens the Decisions page on that card: the location parses as the decision-inbox panel with card=<id>', () => {
    window.__NERVA_BASE_PATH__ = '/one';
    history.replaceState(null, '', '/one/v2/cockpit?demo=1&frame=ledger#docket-entry-7');
    openDecisionsCard(12);
    expect(routeHere()).toMatchObject({ valid: true, mode: 'console', panel: 'decision-inbox' });
    expect(new URLSearchParams(location.search).get('card')).toBe('12');
    expect(new URLSearchParams(location.search).get('demo')).toBe('1');
    expect(new URLSearchParams(location.search).get('frame')).toBe('ledger');
    expect(location.hash).toBe('');
  });

  it('reaches the router as the panel, with no "Page not found" fallback', () => {
    history.replaceState(null, '', '/v2/cockpit?frame=ledger');
    function RouteProbe() {
      const { route, notice } = useHudRoute();
      return <output data-testid="route">{`${route.valid}|${route.mode}|${route.panel}|${notice}`}</output>;
    }
    render(<RouteProbe />);
    expect(screen.getByTestId('route').textContent).toBe('true|cockpit|null|');
    act(() => openDecisionsCard(12));
    expect(screen.getByTestId('route').textContent).toBe('true|console|decision-inbox|');
    expect(location.pathname).toBe('/v2/console/decision-inbox');
    expect(location.search).toBe('?frame=ledger&card=12');
  });

  it('pushes one history entry, none when already there, and never carries an overlay\'s return record', () => {
    history.replaceState({ __nervaHudRoute: { path: '/v2/memory', parent: null }, kept: 1 }, '', '/v2/cockpit');
    const before = history.length;
    openDecisionsCard(12);
    expect(history.length).toBe(before + 1);
    expect(history.state).toEqual({ kept: 1 });
    openDecisionsCard(12);
    expect(history.length).toBe(before + 1);
    // The classic Console overlay's Close goes to Today, not to a return path left by another entry.
    closeHudOverlay();
    expect(location.pathname).toBe('/v2/cockpit');
    openDocketEntry(3);
    expect(history.state).not.toHaveProperty('__nervaHudRoute');
  });

  it('is where the feed sends the docket', () => {
    expect(DOCKET_FEED_PATH).toBe('/autonomy/tasks?status=blocked&limit=200');
  });
});

describe('the docket read hooks', () => {
  afterEach(() => { resetPolling(); vi.unstubAllGlobals(); });

  it('answer Unknown ("Checking…") before the feed answers — never a 0, never an all-clear', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    let summary: any;
    let title: any;
    function Probe() { summary = useDocketSummary(); title = useDocketTitle(5); return null; }
    render(<Probe />);
    expect(summary).toMatchObject({ state: 'unknown', value: null, reason: 'checking' });
    expect(title).toMatchObject({ state: 'unknown', value: null });
  });

  it('read the shared decisions feed: counts, and a title only when the docket holds the request', async () => {
    const fetch = vi.fn(async (_url: string) => ({ ok: true, status: 200, json: async () => ({ tasks: [
      { id: 5, title: 'Restart lmstudio', kind: 'restart_service', risk_tier: 3 },
      { id: 6, title: 'Draft a reply', kind: 'draft_email', risk_tier: 1 },
    ] }) }));
    vi.stubGlobal('fetch', fetch);
    let summary: any; let held: any; let gone: any;
    function Probe() { summary = useDocketSummary(); held = useDocketTitle(5); gone = useDocketTitle(99); return null; }
    render(<Probe />);
    await waitFor(() => expect(summary.state).toBe('live'));
    expect(summary.value).toEqual({ entries: 2, requests: 2, friction: { typed: 1, twoStep: 1, click: 0, inDecisions: 0 } });
    expect(held).toMatchObject({ state: 'live', value: 'Restart lmstudio' });
    expect(gone).toMatchObject({ state: 'empty', value: null });
    expect(fetch).toHaveBeenCalledTimes(1);                     // one request, shared
    expect(String(fetch.mock.calls[0][0])).toBe(DOCKET_FEED_PATH);
  });

  it('say refused — no value, no 0 — when the feed needs the owner credential', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) })));
    let summary: any;
    function Probe() { summary = useDocketSummary(); return null; }
    render(<Probe />);
    await waitFor(() => expect(summary.state).toBe('refused'));
    expect(summary.value).toBeNull();
  });

  it('read the demo sample, without a request, under ?demo=1', () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    history.replaceState(null, '', '/v2/cockpit?demo=1');
    let summary: any;
    function Probe() { summary = useDocketSummary(); return null; }
    render(<Probe />);
    expect(summary.state).toBe('demo');
    expect(summary.value.entries).toBe(6);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('follow in-app navigation through hud-routing\'s route-change event (mirrored as HUD_ROUTE_EVENT)', () => {
    const heard = vi.fn();
    window.addEventListener(HUD_ROUTE_EVENT, heard);
    try {
      openDocketEntry(9);
      expect(heard).toHaveBeenCalledTimes(1);
    } finally { window.removeEventListener(HUD_ROUTE_EVENT, heard); }
  });
});
