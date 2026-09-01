// @ts-nocheck
/* DESKTOP ALLOWLIST — the pack's inspectable vocabulary, and the three ways this panel
   could have lied about it:

     * a guard refusal (401/403/429) painted as an empty allowlist — "this install allows
       nothing" when the truth is "the read was refused";
     * a hardcoded ["screenshot"] read-only set instead of the backend's own `read_only`
       list, which would keep saying "read-only" after the backend changed its mind;
     * a key missing from the payload rendered as zero rows instead of "not in payload".

   Plus the standing product claim: nothing here is runnable. `/api/desktop/run` refuses
   every step this vocabulary plans (tests/test_desktop_control.py:194), so the panel must
   never offer a launch/mute/record control. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { DesktopAllowlistPanel } from './desktop-allowlist';

/* The exact payload of allowlist() (agents/core/desktop_control.py:130-138), pinned
   byte-for-byte by tests/test_desktop_control.py::test_allowlist_route_exposes_the_whole_inspectable_surface. */
const REAL = {
  apps: ['browser', 'calendar', 'editor', 'files', 'mail', 'music', 'notes', 'settings', 'terminal'],
  os_actions: ['brightness_set', 'lock_screen', 'media_next', 'media_playpause', 'media_prev',
    'screenshot', 'sleep_display', 'volume_mute', 'volume_set'],
  read_only: ['screenshot'],
  recording: ['start', 'stop'],
};

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });

function mockFetch(res) {
  const fn = vi.fn(async (url) => {
    if (!String(url).includes('/api/desktop/allowlist')) throw new Error('unexpected fetch ' + url);
    return typeof res === 'function' ? res() : res;
  });
  global.fetch = fn;
  return fn;
}

/* The row for `key` and the tag text sitting on it, so the assertion is "this key carries
   this tag" rather than "both strings exist somewhere in the panel". */
const tagOn = (key) => {
  const row = screen.getByText(key).closest('div');
  return row ? row.textContent : '';
};

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('DesktopAllowlistPanel — the desktop pack vocabulary, inspectable and honest', () => {
  it('GETs /api/desktop/allowlist and renders every key verbatim, unrelabelled', async () => {
    const fn = mockFetch(ok(REAL));
    render(<DesktopAllowlistPanel />);

    await waitFor(() => expect(screen.getByText('browser')).toBeTruthy());
    REAL.apps.forEach((a) => expect(screen.getByText(a)).toBeTruthy());
    REAL.os_actions.forEach((a) => expect(screen.getByText(a)).toBeTruthy());
    expect(screen.getByText('start')).toBeTruthy();
    expect(screen.getByText('stop')).toBeTruthy();
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/desktop/allowlist'))).toBe(true);

    // the backend owns the label map ("browser" -> "Web browser"); it is not in this payload
    expect(screen.queryByText('Web browser')).toBeNull();
    expect(screen.queryByText('Code editor')).toBeNull();

    // counts come from the payload, not from a constant
    expect(screen.getByText('9 apps · 9 OS actions · 2 recording ops')).toBeTruthy();

    // nothing here actuates: no run/launch/record controls, only Card's reload
    const buttons = Array.from(document.querySelectorAll('button')).map((b) => b.textContent.trim());
    expect(buttons).toEqual(['↻']);
    expect(screen.queryByText(/^launch$/i)).toBeNull();
  });

  it('tags os_actions from the payload read_only list — screenshot read-only, volume_set approval-gated', async () => {
    mockFetch(ok(REAL));
    render(<DesktopAllowlistPanel />);

    await waitFor(() => expect(screen.getByText('screenshot')).toBeTruthy());
    expect(tagOn('screenshot')).toContain('read-only');
    expect(tagOn('volume_set')).toContain('mutating · requires approval');
    expect(tagOn('lock_screen')).toContain('mutating · requires approval');
    expect(tagOn('volume_set')).not.toContain('read-only');
  });

  it('reads read_only rather than guessing it: a payload where volume_set is read-only flips both tags', async () => {
    mockFetch(ok({ ...REAL, read_only: ['volume_set'] }));
    render(<DesktopAllowlistPanel />);

    await waitFor(() => expect(screen.getByText('volume_set')).toBeTruthy());
    expect(tagOn('volume_set')).toContain('read-only');
    expect(tagOn('screenshot')).toContain('mutating · requires approval');
  });

  it('renders a guard refusal AS a refusal — never as an empty or zero allowlist', async () => {
    // 403 "user routes disabled from network"; apiGet throws without a body, so the panel
    // can only ever see (and must only ever print) the status line.
    mockFetch({ ok: false, status: 403, json: async () => ({ detail: 'user routes disabled from network' }) });
    render(<DesktopAllowlistPanel />);

    await waitFor(() => expect(screen.getByText(/GET \/api\/desktop\/allowlist -> 403/)).toBeTruthy());

    // not one row of vocabulary is painted under a refused read
    expect(screen.queryByText('browser')).toBeNull();
    expect(screen.queryByText('screenshot')).toBeNull();
    expect(screen.queryByText('start')).toBeNull();
    // and no fabricated emptiness or invented cause
    expect(screen.queryByText(/0 apps/)).toBeNull();
    expect(screen.queryByText('nothing yet')).toBeNull();
    expect(screen.queryByText(/user routes disabled/)).toBeNull();
    expect(screen.queryByText(/unavailable/i)).toBeNull();
  });

  it('says "not in payload" for a key that never arrived, instead of a silent zero', async () => {
    mockFetch(ok({ apps: REAL.apps, os_actions: REAL.os_actions, read_only: [] }));
    render(<DesktopAllowlistPanel />);

    await waitFor(() => expect(screen.getByText('recording not in payload')).toBeTruthy());
    expect(screen.getByText('browser')).toBeTruthy();
    // read_only arrived as an empty array — that is a real answer, so every action is mutating
    expect(screen.queryByText('read_only not in payload')).toBeNull();
    expect(tagOn('screenshot')).toContain('mutating · requires approval');
    expect(screen.getByText('9 apps · 9 OS actions · 0 recording ops')).toBeTruthy();
  });

  it('drops the read-only/mutating tags entirely when read_only itself is missing', async () => {
    mockFetch(ok({ apps: REAL.apps, os_actions: REAL.os_actions, recording: REAL.recording }));
    render(<DesktopAllowlistPanel />);

    await waitFor(() => expect(screen.getByText('read_only not in payload')).toBeTruthy());
    expect(tagOn('screenshot')).not.toContain('read-only');
    expect(tagOn('volume_set')).not.toContain('mutating · requires approval');
  });
});
