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
 *   ADMIN.plugins      — eight fabricated rows (Gmail API … Cloud LLM Fallback)
 *                        rendered as the real registry, under a fabricated
 *                        "8/8 enabled" header with no empty state
 *   OBSERVE quality/bench/resilience — the scalar panels were left at the seed,
 *                        so a 503 from /bench/stats kept the 4.2s p50 while
 *                        /api/quality (200) stamped the LIVE badge
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
  hydrateObserve,
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
  it('admin: models/plugins/keys/backups/channels empty, system null', () => {
    const A = honestAdminSeed();
    expect(A.models).toEqual([]);
    expect(A.keys).toEqual([]);
    expect(A.backups).toEqual([]);
    expect(A.channels).toEqual([]);
    expect(A.system).toBeNull();
    // GET /plugins answers {"plugins": [], "total": 0} with no orchestrator, so
    // the registry never overwrites the seed — it has to start empty.
    expect(A.plugins).toEqual([]);
  });

  it('observe: traces/arena/by_agent empty, scalar panels null', () => {
    const O = honestObserveSeed();
    expect(O.traces).toEqual([]);
    expect(O.arena).toEqual([]);
    expect(O.by_agent).toEqual([]);
    // toEqual on the whole object also pins that the objects stay objects —
    // ObserveMode reads O.quality.success_rate / O.bench.p50 unguarded.
    expect(O.bench).toEqual({ p50: null, p95: null, p99: null });
    expect(O.quality).toEqual({ success_rate: null, interactions: null, escalations: null });
    expect(O.resilience).toEqual({ uptime: null, ssrf_blocked: null, errors_24h: null, redactions: null });
  });
});

describe('a silent observe endpoint nulls its own block, even over the demo seed', () => {
  it('a 503 on /bench/stats nulls the block instead of keeping the seed 4.2', () => {
    // The reachable case: no orchestrator → /bench/stats 503s (null here) while
    // /api/quality answers 200, which is enough to stamp the panel LIVE.
    const O = hydrateObserve(null, { stats: {}, alert: { alerting: false } }, null, V2.OBSERVE);
    expect(O.bench).toEqual({ p50: null, p95: null, p99: null });
    expect(O.bench.p50).not.toBe(4.2);
    expect(O.resilience.uptime).toBeNull();
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
const SEED_FICTION_ADMIN = ['sk-ant', 'jarvis-prime', '02:30 today', 'WhatsApp (bridge)',
  'Gmail API', 'Google Calendar', 'Telegram Bot', 'Spotify', 'WhatsApp Bridge',
  'Apple Health', 'Homebridge', 'Cloud LLM Fallback'];

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
    // The literal outputs of _pct(0.91) / _obs(847) / _obs(4.2,'s') / _obs('99.97%') —
    // exact strings, not regexes, because `.` would match any character.
    expect(screen.queryByText('4.2s')).toBeNull();
    expect(screen.queryByText('91%')).toBeNull();
    expect(screen.queryByText('847')).toBeNull();
    expect(screen.queryByText('99.97%')).toBeNull();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(4);
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

  it('renders an honest empty plugin registry, not a fabricated 8/8 count', () => {
    render(<AdminMode t={{ admin: 'Admin' }} />);
    expect(screen.getByText('PLUGIN REGISTRY')).toBeTruthy();   // exact: no count suffix
    expect(screen.queryByText(/\d+\/\d+ enabled/)).toBeNull();
    expect(screen.getByText(/not connected · no plugin registry/i)).toBeTruthy();
  });

  it('hydrated keys render the server mask, never the seed mask', () => {
    V2.ADMIN = { ...honestAdminSeed(), keys: hydrateAdminKeys(REAL_ENV) };
    render(<AdminMode t={{ admin: 'Admin' }} />);
    expect(screen.getByText('ANTHROPIC_API_KEY')).toBeTruthy();
    expect(screen.getByText('sk-a…2f')).toBeTruthy();
    expect(screen.queryByText(/4f2a/)).toBeNull();
  });
});
