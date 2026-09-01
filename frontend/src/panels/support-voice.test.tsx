// @ts-nocheck
/* SUPPORT & VOICE — the honesty properties of two read-only diagnostics, pinned.

   Both routes are GETs, so there is no destructive control to gate here. What CAN rot is
   the truthfulness of the rendering, and every assertion below corresponds to a claim the
   backend does not support:

   1. A section that came back {"error":"unavailable"} must render as the backend's own
      word — never as 0, empty, or a missing row. The six sections fail independently.
   2. A 401/403 from admin_guard must render as the status the client actually saw. apiGet
      throws BEFORE reading the error body, so the guard's `detail` ("admin token
      required" / "admin disabled from network — …") never reaches the client: if it ever
      appears on screen, someone invented it.
   3. audit.chain_ok is set inside contextlib.suppress → ABSENT means "not verified", and
      chain_ok:true over window 0 is a trivially-verified empty chain, not evidence.
   4. Wyoming: `note` renders verbatim, enabled/listening/reachable stay three separate
      truths, and there is NO enable/start/toggle control (no shipped route writes
      voice.wyoming_enabled and nothing in the product starts a Wyoming server).
   5. A copy that could not happen is never reported as a copy that did. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock('../api/client', () => ({
  apiGet: (...a: any[]) => apiGet(...a),
  apiPost: (...a: any[]) => apiPost(...a),
  apiPut: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn(),
  actionFailures: () => [], onActionFailure: () => () => {}, clearActionFailures: vi.fn(),
}));

import { SupportVoicePanel } from './support-voice';

const BUNDLE = '/api/support/bundle';
const WYOMING = '/api/voice/wyoming';

const META = { python: '3.12.3', platform: 'linux', generated_at: '2026-09-01T10:00:00+00:00' };
const POSTURE = {
  hardened: { enabled: false, guardrails_mode_default: 'WARN' },
  product_posture: { name: 'off', raw_name: 'off', valid: true, label: 'Off (default)' },
  system_profile: { active: 'balanced', default: 'balanced' },
};
const bundle = (over: any = {}) => ({
  meta: META, posture: POSTURE,
  capabilities: { error: 'unavailable' },
  egress: { error: 'unavailable' },
  audit: { error: 'unavailable' },
  routes: 412,
  ...over,
});
const wyoming = (over: any = {}) => ({
  protocol: 'wyoming', version: '1.0.0', enabled: false, listening: false, reachable: false,
  note: 'no Wyoming server is listening on this host — the protocol implementation ships but nothing in the product starts it',
  port: 10700, role: 'handle',
  ...over,
});

/** Route the two reads; `b` and `w` may be a value or a rejection. */
function serve(b: any, w: any = wyoming()) {
  apiGet.mockImplementation((path: string) => {
    if (path === BUNDLE) return b instanceof Error ? Promise.reject(b) : Promise.resolve(b);
    if (path === WYOMING) return w instanceof Error ? Promise.reject(w) : Promise.resolve(w);
    return Promise.resolve({});
  });
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
});

describe('SUPPORT BUNDLE · per-section availability', () => {
  it('renders an unavailable section with the backend word, never a zero', async () => {
    serve(bundle());
    render(<SupportVoicePanel />);

    // three failed sections → three rows carrying the backend's own literal
    await waitFor(() => expect(screen.getAllByText('error: unavailable')).toHaveLength(3));
    // …and the strip names each one
    screen.getByText('capabilities · error: unavailable');
    screen.getByText('egress · error: unavailable');
    screen.getByText('audit · error: unavailable');
    // the chip/sub counts only the sections that really arrived
    screen.getByText('3/6 sections');

    // nothing invents a roll-up for a section that failed
    expect(screen.queryByText(/harness_pending/)).toBeNull();
    expect(screen.queryByText(/^external /)).toBeNull();
    expect(screen.queryByText(/^window /)).toBeNull();
    expect(screen.queryByText(/no local-only violations/)).toBeNull();
    expect(screen.queryByText(/chain verified/)).toBeNull();
  });

  it('says "version not reported" rather than inventing one, and marks the posture defaults-only', async () => {
    serve(bundle());
    render(<SupportVoicePanel />);
    await screen.findByText('version not reported');
    await screen.findByText('defaults-only — not this box');
    await screen.findByText('412 routes');
  });

  it('never shows a green clean badge for an empty egress sample', async () => {
    serve(bundle({ egress: { plugins: {}, external_egress_total: 0, model_egress_total: 0, local_only_violations: [], clean: true } }));
    render(<SupportVoicePanel />);
    await screen.findByText('no egress recorded yet — nothing measured');
    expect(screen.queryByText('no local-only violations')).toBeNull();
  });

  it('renders a refusal as the status the client actually saw, and never the guard\'s body', async () => {
    // apiGet throws BEFORE reading the error body: only this message exists client-side
    const err: any = new Error('GET /api/support/bundle -> 403');
    err.status = 403;
    serve(err);
    render(<SupportVoicePanel />);

    await screen.findByText(/GET \/api\/support\/bundle -> 403/);
    // no bundle rows rendered at all
    expect(screen.queryByText('sections')).toBeNull();
    expect(screen.queryByText('attachable artifact')).toBeNull();
    // the admin guard's detail strings were never received, so they must not appear
    expect(screen.queryByText(/admin token required/)).toBeNull();
    expect(screen.queryByText(/admin disabled from network/)).toBeNull();
  });
});

describe('SUPPORT BUNDLE · audit chain honesty', () => {
  it('calls a zero-row chain trivial, not verified', async () => {
    serve(bundle({ audit: { recent_event_counts: {}, window: 0, chain_ok: true } }));
    render(<SupportVoicePanel />);
    await screen.findByText('no events in window — a zero-row chain verifies trivially');
    expect(screen.queryByText(/chain verified over/)).toBeNull();
  });

  it('treats an absent chain_ok as not verified, not as ok', async () => {
    serve(bundle({ audit: { recent_event_counts: { tool_call: 12 }, window: 12 } }));
    render(<SupportVoicePanel />);
    await screen.findByText('chain not verified in this bundle');
    expect(screen.queryByText(/chain verified over/)).toBeNull();
    expect(screen.queryByText(/chain broken/)).toBeNull();
  });

  it('renders a broken chain in the backend\'s own terms', async () => {
    serve(bundle({ audit: { recent_event_counts: { tool_call: 9 }, window: 9, chain_ok: false, chain_broken_at: 7 } }));
    render(<SupportVoicePanel />);
    await screen.findByText(/chain broken @ #7/);
  });
});

describe('SUPPORT BUNDLE · the attachable artifact', () => {
  it('never claims a copy that did not happen', async () => {
    serve(bundle());
    render(<SupportVoicePanel />);
    const btn = await screen.findByLabelText('copy the bundle JSON');

    // jsdom has no navigator.clipboard
    fireEvent.click(btn);
    await screen.findByText(/clipboard unavailable in this browser/);
    expect(screen.queryByText(/^copied ·/)).toBeNull();
  });

  it('reports a rejected writeText as a failure, verbatim', async () => {
    serve(bundle());
    (navigator as any).clipboard = { writeText: () => Promise.reject(new Error('Write permission denied.')) };
    try {
      render(<SupportVoicePanel />);
      fireEvent.click(await screen.findByLabelText('copy the bundle JSON'));
      await screen.findByText('copy failed · Write permission denied.');
      expect(screen.queryByText(/^copied ·/)).toBeNull();
    } finally {
      delete (navigator as any).clipboard;
    }
  });
});

describe('WYOMING VOICE SATELLITE', () => {
  it('renders the backend note verbatim, keeps the three truths apart, and offers no toggle', async () => {
    serve(bundle(), wyoming({ enabled: true }));
    render(<SupportVoicePanel />);

    await screen.findByText('no Wyoming server is listening on this host — the protocol implementation ships but nothing in the product starts it');

    const row = (label: string) => screen.getByText(label).parentElement as HTMLElement;
    expect(row('enabled (setting voice.wyoming_enabled)').textContent).toContain('true');
    expect(row('listening (measured · loopback connect)').textContent).toContain('false');
    expect(row('reachable (enabled AND listening)').textContent).toContain('false');

    // no shipped route writes voice.wyoming_enabled and nothing starts a server
    expect(screen.queryByRole('button', { name: /enable|start|toggle|launch/i })).toBeNull();
  });

  it('renders nothing in place of an empty note when the probe found a listener', async () => {
    serve(bundle(), wyoming({ enabled: true, listening: true, reachable: true, note: '' }));
    render(<SupportVoicePanel />);
    await screen.findByText('port 10700 · v1.0.0');
    expect(screen.queryByText(/no Wyoming server is listening/)).toBeNull();
    // and nothing is invented in the empty note's place
    expect(screen.queryByText(/all good|nothing to report|healthy/i)).toBeNull();
  });
});
