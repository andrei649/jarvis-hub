// @ts-nocheck
/* PRESENCE & INBOX — the four ways this panel could have lied, each pinned here:

     1. `away:false` painted as "the owner is present". _compute_away fails calm — it is
        false for a stale signal and for state 'unknown' — so false means "not known to be
        away" and nothing else.
     2. `idle_seconds:null` painted as 0. null means the daemon attached no hint; a 0 would
        be a measurement nobody took.
     3. The inbox's unbound branch painted as a real count. Its threads/messages zeros are
        literals in integrations.py:132-133 and max_messages is absent from that branch, so
        a bare 0 and a fabricated 500 would both be fabrications.
     4. The presence 503 painted as a received reason. apiGet (client.ts:106) throws before
        reading the body, so the only string the panel HOLDS is
        'GET /api/presence/owner -> 503'; the handler's own words may be cited from source
        and must appear nowhere else.

   Plus the standing product claim of this lane: the presence signal is daemon-written
   (admin-guarded POST), so the panel must expose no control that lets a human set it. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { PresenceInboxPanel } from './presence-inbox';

const NOW = Math.floor(Date.now() / 1000);

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });

/* Route the two GETs independently so a refusal on one never masks the other. */
function mockFetch(presence, inbox) {
  const fn = vi.fn(async (url) => {
    const u = String(url);
    if (u.includes('/api/channels/inbox/status')) return typeof inbox === 'function' ? inbox() : inbox;
    if (u.includes('/api/presence/owner')) return typeof presence === 'function' ? presence() : presence;
    throw new Error('unexpected fetch ' + u);
  });
  global.fetch = fn;
  return fn;
}

/* The row whose label is `key`, as text — so an assertion reads "this row carries this
   value" rather than "both strings exist somewhere on the panel". */
const rowText = (key) => {
  // Match the row's LABEL span (its first child), not any value that happens to read the
  // same — with state 'away' the string "away" is both a label and a payload value.
  const rows = Array.from(document.querySelectorAll('div')).filter((el) => {
    const first = el.firstElementChild;
    return first && first.tagName === 'SPAN' && first.textContent === key;
  });
  if (rows.length !== 1) throw new Error(`expected one row labelled "${key}", found ${rows.length}`);
  return rows[0].textContent;
};

/* A live presence report: state 'away', a named daemon, an idle hint, fresh. */
const PRESENCE_AWAY = {
  state: 'away',
  source: 'win-idle-watcher',
  since: NOW - 900,
  updated_at: NOW - 30,
  idle_seconds: 612.0,
  ttl_seconds: 900.0,
  stale: false,
  away: true,
  ever_reported: true,
};

/* The never-reported snapshot every fresh boot serves: constructor defaults, stale by
   definition (_is_stale returns True immediately when ever_reported is false). */
const PRESENCE_NEVER = {
  state: 'unknown',
  source: '',
  since: NOW - 120,
  updated_at: NOW - 120,
  idle_seconds: null,
  ttl_seconds: 900.0,
  stale: true,
  away: false,
  ever_reported: false,
};

/* Branch (B) of channels_inbox_status — orch.channel_inbox bound, stats() measured. */
const INBOX_BOUND = {
  enabled: true,
  stats: { enabled: true, channels: ['email', 'telegram', 'web'], threads: 3, messages: 41, max_messages: 500 },
};

/* Branch (A) — store unbound. Note what the handler does NOT send: max_messages. */
const INBOX_UNBOUND = {
  enabled: false,
  stats: { enabled: false, channels: ['email', 'telegram', 'web'], threads: 0, messages: 0 },
};

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('PresenceInboxPanel — owner desk presence + the inbox flag COMMS cannot see', () => {
  it('reads both routes and renders a live away report without inventing a verdict', async () => {
    const fn = mockFetch(ok(PRESENCE_AWAY), ok(INBOX_BOUND));
    render(<PresenceInboxPanel />);

    await waitFor(() => expect(screen.getByText('state')).toBeTruthy());
    await waitFor(() => expect(screen.getByText('threads')).toBeTruthy());

    // both literal routes were actually called
    const urls = fn.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes('/api/presence/owner'))).toBe(true);
    expect(urls.some((u) => u.includes('/api/channels/inbox/status'))).toBe(true);

    // presence, verbatim
    expect(rowText('state')).toContain('away');
    expect(rowText('away')).toContain('AWAY');
    expect(rowText('daemon')).toContain('win-idle-watcher');
    expect(rowText('idle_seconds')).toContain('612');
    expect(rowText('freshness')).toContain('fresh');
    expect(rowText('freshness')).toContain('900');

    // the operator consequence of away, quoted from AwayNotifier
    expect(screen.getByText(/no extra interrupt slot/)).toBeTruthy();

    // inbox, measured
    expect(rowText('threads')).toContain('3');
    expect(rowText('messages')).toContain('41');
    expect(rowText('cap')).toContain('500');
    expect(screen.getByText('BOUND')).toBeTruthy();
    expect(screen.queryByText('NOT BOUND')).toBeNull();
    // nothing is tagged a placeholder when the store is really bound
    expect(rowText('threads')).not.toContain('placeholder');

    // channels render verbatim — email included — but are never called replyable
    ['email', 'telegram', 'web'].forEach((c) => expect(screen.getByText(c)).toBeTruthy());
    expect(screen.getByText(/not automatically replyable/)).toBeTruthy();

    // the lane's hard rule: no control can set presence from here. Only Card's reload.
    const buttons = Array.from(document.querySelectorAll('button')).map((b) => b.textContent.trim());
    expect(buttons).toEqual(['↻']);
    expect(document.querySelectorAll('input, textarea, select').length).toBe(0);
  });

  it('never-reported presence reads as unknown/stale, not as 0 and not as "present"', async () => {
    mockFetch(ok(PRESENCE_NEVER), ok(INBOX_BOUND));
    render(<PresenceInboxPanel />);

    await waitFor(() => expect(screen.getByText('daemon')).toBeTruthy());

    expect(screen.getByText('NEVER REPORTED')).toBeTruthy();
    expect(screen.getByText('STALE')).toBeTruthy();

    // away:false must never be spoken as presence
    const away = rowText('away');
    expect(away).toContain('not known to be away');
    expect(away).not.toContain('present');
    expect(away).not.toContain('at the desk');

    // idle_seconds:null is "not reported" — never 0, never "idle for 0s"
    const idle = rowText('idle_seconds');
    expect(idle).toContain('not reported');
    expect(idle).not.toContain('0');

    // source '' must not become a made-up daemon name
    expect(rowText('daemon')).not.toContain('win-idle-watcher');

    // the timestamps are labelled as construction, not as a signal that never arrived
    expect(screen.getByText('tracker created')).toBeTruthy();
    expect(screen.queryByText('last signal')).toBeNull();
  });

  it('unbound inbox is an amber 200-state with placeholder figures, not zeros or an error', async () => {
    mockFetch(ok(PRESENCE_AWAY), ok(INBOX_UNBOUND));
    render(<PresenceInboxPanel />);

    await waitFor(() => expect(screen.getByText('NOT BOUND')).toBeTruthy());

    // the zeros are named for what they are
    expect(rowText('threads')).toContain('(placeholder)');
    expect(rowText('messages')).toContain('(placeholder)');
    expect(screen.getByText(/hardcoded placeholders/)).toBeTruthy();

    // max_messages is absent from this branch: an em dash, never 0 and never a guessed 500
    const cap = rowText('cap');
    expect(cap).toContain('—');
    expect(cap).not.toContain('0');
    expect(cap).not.toContain('500');

    // a 200 with enabled:false is not an outage — it must not surface as an offline error
    expect(screen.queryByText(/offline ·/)).toBeNull();
  });

  it('a presence 503 renders verbatim, cites the handler for its meaning, and paints no state', async () => {
    mockFetch(
      { ok: false, status: 503, json: async () => ({ error: 'presence not available' }) },
      ok(INBOX_BOUND),
    );
    render(<PresenceInboxPanel />);

    // the thrown message — all apiGet actually gives the panel
    await waitFor(() => expect(screen.getByText(/GET \/api\/presence\/owner -> 503/)).toBeTruthy());

    // no presence value is invented behind the refusal
    expect(screen.queryByText('state')).toBeNull();
    expect(screen.queryByText('away')).toBeNull();
    expect(screen.queryByText('idle_seconds')).toBeNull();
    expect(screen.queryByText('AWAY · cards also escalate')).toBeNull();
    expect(screen.queryByText('not known to be away')).toBeNull();

    /* The handler's own words appear exactly once, in the innermost element that carries
       them, and that element also says where they were read from — so they can never be
       mistaken for a reason this panel received. */
    const leaves = Array.from(document.querySelectorAll('div')).filter((el) =>
      el.textContent.includes('presence not available')
      && !Array.from(el.children).some((c) => c.textContent.includes('presence not available')));
    expect(leaves.length).toBe(1);
    expect(leaves[0].textContent).toContain('presence.py:37');
    expect(leaves[0].textContent).toContain('not received from this response');

    // the other read is untouched by the refusal
    expect(screen.getByText('BOUND')).toBeTruthy();
    expect(rowText('messages')).toContain('41');
  });
});
