// @ts-nocheck
/* The seeded ADMIN/OBSERVE corpora survived live hydration (BACKLOG "seeded
 * ADMIN/OBSERVE corpora"). The quality/bench/resilience fixes in
 * observe-no-seed-fallback.test.tsx covered four numbers; these surfaces were
 * still 100% seed fiction in live mode:
 *
 *   OBSERVE.by_agent   — no fetch ever supplied it; seven fabricated latencies
 *                        (athena 3.2s … vision 6.8s) rendered as fact
 *   OBSERVE.arena      — seed rows ("gemma-4-26b · local · DEFAULT") kept when
 *                        /api/arena/leaderboard returned nothing
 *   OBSERVE.traces     — seed rows (tr-8f3a "what does my day look like?")
 *                        kept when /api/traces returned nothing
 *   mark('OBSERVE')    — fired on Signal Layer health alone, stamping LIVE over
 *                        a panel whose every Jarvis source could be pure seed
 *   ADMIN.keys         — "ANTHROPIC_API_KEY sk-ant-••••4f2a valid rotated 14d
 *                        ago" — never fetched, always fiction
 *   ADMIN.backups      — "02:30 today · verified" — no endpoint exists at all
 *   ADMIN.channels     — five "active" channels — no endpoint exists
 *   ADMIN.system       — "jarvis-prime · RTX 4090 · up 18d" — never fetched
 *
 * Rule under test: every number comes from the backend or renders as an
 * honest empty state. Demo mode keeps its labelled fiction corpus untouched.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, cleanup } from '@testing-library/react';
import React from 'react';
import { V2 } from '../data';
import {
  hydrateAdminKeys,
  hydrateByAgent,
  honestAdminSeed,
  honestObserveSeed,
  observeEvidence,
} from '../api/live';

beforeEach(() => { });
afterEach(() => { cleanup(); });

/* ---------- the real payload shapes ---------- */

// GET /api/admin/env → flat map; secrets masked server-side by mask_secret()
// (agents/core/web_helpers.py:79): `abcd…xy` or `****`; everything else clear.
const REAL_ENV = {
  ANTHROPIC_API_KEY: 'sk-a…2f',
  PATH: '/usr/bin:/bin',
  TELEGRAM_BOT_TOKEN: '****',
  DEBUG: '1',
};

// GET /api/admin/agents/stats → {agent_id: {status, model, tier, latency_ms}}
const REAL_AGENTS_STATS = {
  jarvis: { status: 'idle', model: 'gemma-4-26b', tier: 'core', latency_ms: 4123.0 },
  pepper: { status: 'idle', model: 'gemma-4-26b', tier: 'ambient', latency_ms: 0 },
};

describe('hydrateAdminKeys reads the env map, not the seed', () => {
  it('keeps only secret-named entries, with the server mask intact', () => {
    const keys = hydrateAdminKeys(REAL_ENV);
    expect(keys.map((k) => k.name)).toEqual(['ANTHROPIC_API_KEY', 'TELEGRAM_BOT_TOKEN']);
    expect(keys[0].masked).toBe('sk-a…2f');
    expect(keys[1].masked).toBe('****');
  });

  it('never claims rotation or validity it cannot know', () => {
    const keys = hydrateAdminKeys(REAL_ENV);
    for (const k of keys) {
      expect(k.rotated).toBe('');
      expect(k.status).not.toBe('valid');
      expect(k.status).not.toBe('expiring');
    }
  });

  it('returns an empty list, not the seed, when there is nothing to show', () => {
    expect(hydrateAdminKeys(null)).toEqual([]);
    expect(hydrateAdminKeys({})).toEqual([]);
    expect(hydrateAdminKeys({ PATH: '/usr/bin', DEBUG: '1' })).toEqual([]);
    for (const k of hydrateAdminKeys({ DEBUG: '1' })) {
      expect(k.masked).not.toBe('sk-ant-•••••••4f2a');
    }
  });
});

describe('hydrateByAgent reads /api/admin/agents/stats, not the seed', () => {
  it('converts latency_ms to seconds and drops zero-latency agents', () => {
    expect(hydrateByAgent(REAL_AGENTS_STATS)).toEqual([{ id: 'jarvis', v: 4.1 }]);
  });

  it('never returns a seed agent the backend did not report', () => {
    const ids = hydrateByAgent(REAL_AGENTS_STATS).map((a) => a.id);
    expect(ids).not.toContain('athena');
    expect(ids).not.toContain('vision');
  });

  it('returns an empty list on 503 ({error}) or junk', () => {
    expect(hydrateByAgent(null)).toEqual([]);
    expect(hydrateByAgent({ error: 'not initialized' })).toEqual([]);
  });
});

describe('honest seeds strip the fiction but keep the shape', () => {
  it('admin: models/keys/backups/channels empty, system null', () => {
    const A = honestAdminSeed();
    expect(A.models).toEqual([]);
    expect(A.keys).toEqual([]);
    expect(A.backups).toEqual([]);
    expect(A.channels).toEqual([]);
    expect(A.system).toBeNull();
    // plugins keep their place in the shape; the registry hydrates separately
    expect(Array.isArray(A.plugins)).toBe(true);
  });

  it('observe: traces/arena/by_agent empty, scalar panels left to hydrateObserve', () => {
    const O = honestObserveSeed();
    expect(O.traces).toEqual([]);
    expect(O.arena).toEqual([]);
    expect(O.by_agent).toEqual([]);
    expect(O.quality).toBeDefined();
    expect(O.resilience).toBeDefined();
  });
});

describe('the OBSERVE badge requires Jarvis evidence, not neighbour health', () => {
  it('does not fire when every observe source is silent', () => {
    expect(observeEvidence(null, null, null, null, null)).toBe(false);
    expect(observeEvidence(null, null, null, [], [])).toBe(false);
  });

  it('fires on any real observe source', () => {
    expect(observeEvidence({ p50: 1 }, null, null, null, null)).toBe(true);
    expect(observeEvidence(null, { stats: {} }, null, null, null)).toBe(true);
    expect(observeEvidence(null, null, { metrics: {} }, null, null)).toBe(true);
    expect(observeEvidence(null, null, null, [{ model: 'x' }], null)).toBe(true);
    expect(observeEvidence(null, null, null, null, [{ id: 't1' }])).toBe(true);
  });
});

/* ---------- component level: honest corpus renders honest UI ---------- */

vi.mock('../api/actions', () => ({
  getNorthStar: vi.fn(() => Promise.resolve(null)),
  getAutonomyMode: vi.fn(() => Promise.resolve(null)),
  installSkill: vi.fn(),
  setAutonomyMode: vi.fn(),
  queueChannelReply: vi.fn(),
  togglePlugin: vi.fn(() => Promise.resolve({})),
  getEstopStatus: vi.fn(() => Promise.resolve({ engaged: false, state: null })),
  engageEstop: vi.fn(),
  resumeEstop: vi.fn(),
}));
vi.mock('../world-intelligence', () => ({ WorldIntelligencePanel: () => null }));
vi.mock('../gap', () => ({ RoomsPanel: () => null }));

import { ObserveMode } from '../modes2';
import { AdminMode } from '../modes3';

const SEED_FICTION_OBSERVE = ['tr-8f3a', 'gemma-4-26b', 'athena'];
const SEED_FICTION_ADMIN = ['sk-ant', 'jarvis-prime', '02:30 today', 'WhatsApp (bridge)'];

describe('ObserveMode over the honest corpus shows no seed fiction', () => {
  let saved;
  beforeEach(() => {
    saved = V2.OBSERVE;
    V2.OBSERVE = honestObserveSeed();
  });
  afterEach(() => { V2.OBSERVE = saved; });

  it('renders empty states, none of the demo rows', async () => {
    render(<ObserveMode t={{ observe: 'Observe' }} />);
    for (const fiction of SEED_FICTION_OBSERVE) {
      expect(screen.queryByText(new RegExp(fiction))).toBeNull();
    }
    expect(screen.getAllByText(/not connected/i).length).toBeGreaterThanOrEqual(3);
    await act(async () => { await Promise.resolve(); }); // let getNorthStar settle
  });
});

describe('AdminMode over the honest corpus shows no seed fiction', () => {
  let saved;
  beforeEach(() => {
    saved = V2.ADMIN;
    V2.ADMIN = honestAdminSeed();
  });
  afterEach(() => { V2.ADMIN = saved; });

  it('renders empty states for keys/backups/channels/host', () => {
    render(<AdminMode t={{ admin: 'Admin' }} />);
    for (const fiction of SEED_FICTION_ADMIN) {
      expect(screen.queryByText(new RegExp(fiction))).toBeNull();
    }
    expect(screen.getAllByText(/not connected/i).length).toBeGreaterThanOrEqual(4);
  });

  it('hydrated keys render the server mask, never the seed mask', () => {
    V2.ADMIN = { ...honestAdminSeed(), keys: hydrateAdminKeys(REAL_ENV) };
    render(<AdminMode t={{ admin: 'Admin' }} />);
    expect(screen.getByText('ANTHROPIC_API_KEY')).toBeTruthy();
    expect(screen.getByText('sk-a…2f')).toBeTruthy();
    expect(screen.queryByText(/4f2a/)).toBeNull();
  });
});
