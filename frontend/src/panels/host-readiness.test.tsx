// @ts-nocheck
/* HOST READINESS panel — `fetch` is mocked (not api/client) so the REAL client path runs.

   Claims pinned:
   · the probe is read from the backend and the platform + refusals render verbatim;
   · every blocking refusal renders the backend's own hint text, unedited;
   · a tri-state permission of `null` renders "unknown" — never "no" and never "yes";
   · `ok:true` with every host rail off reads as capable-but-off, not as enabled;
   · a probe that could not run renders its reason and claims no facts about the host;
   · the S1 benchmark's headline is rendered verbatim — the panel never composes a rate;
   · a result measured against different questions renders as STALE, not as a score;
   · never-run renders as never-run, not as a zero. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { HostReadinessPanel } from './host-readiness';

const PROBE = {
  platform: 'linux-wayland',
  probed: true,
  ok: false,
  deps: { pywinauto: false, uiautomation: false, pyobjc: false, gi_atspi: true, libei: false, playwright: true, mss: false },
  binaries: { xdotool: false, grim: true, gdbus: true, busctl: false },
  flags: {
    JARVIS_DESKTOP_HOST: false,
    JARVIS_DESKTOP_ISOLATED: false,
    JARVIS_PLAYWRIGHT_HOST: false,
    JARVIS_TERMINAL_LOCAL_HOST: false,
  },
  permissions: {
    accessibility_trusted: null,
    screen_capture: true,
    portal_remote_desktop_version: 1,
    xdg_session_type: 'wayland',
    process_elevated: false,
    uinput_writable: null,
    vlm_proven_local: null,
  },
  refusals: ['wayland_input_unavailable'],
  warnings: ['The RemoteDesktop portal reports version 1.'],
  hints: {
    wayland_input_unavailable:
      'Wayland input needs python-libei and an org.freedesktop.portal.RemoteDesktop portal of version 2 or newer; uinput/ydotool are refused by policy (root, bypasses consent).',
  },
  fingerprint: 'ab12cd34ef56ab78cd90ef12ab34cd56ef78ab90cd12ef34ab56cd78ef90ab12',
  vocabulary: ['wayland_input_unavailable'],
  probed_at: 1_760_000_000,
};

const BENCH = {
  ok: true, recorded: true, stale: false,
  hermetic: { attempted: 19, passed: 19, failed: 0, skipped: 0, rate: 1.0 },
  live: { passed: 0, not_run: 19, rate: null },
  governance_clean: true,
  by_surface: {
    desktop: { passed: 4, failed: 0, skipped: 0 },
    vision: { passed: 3, failed: 0, skipped: 0 },
  },
  results: [],
  headline: '19/19 hermetic; nothing confirmed on a real host yet',
};

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve(hit ? hit[1] : ok({}));
  });
  global.fetch = fn;
  return fn;
}

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('HostReadinessPanel — observe-only host truth, rendered without guessing', () => {
  it('GETs the probe and renders the detected platform', async () => {
    const fn = mockFetch({ '/api/host/probe': ok(PROBE) });
    render(<HostReadinessPanel />);
    await waitFor(() => expect(screen.getByText(/Linux · Wayland/)).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/host/probe'))).toBe(true);
  });

  it('renders each blocking refusal with the backend hint text unedited', async () => {
    mockFetch({ '/api/host/probe': ok(PROBE) });
    render(<HostReadinessPanel />);
    await waitFor(() => expect(screen.getByText('wayland_input_unavailable')).toBeTruthy());
    expect(screen.getByText(PROBE.hints.wayland_input_unavailable)).toBeTruthy();
    expect(screen.getByText(/1 blocker/)).toBeTruthy();
  });

  it('renders each permission at its own tri-state, guessing on none of them', async () => {
    mockFetch({ '/api/host/probe': ok(PROBE) });
    render(<HostReadinessPanel />);
    await waitFor(() => expect(screen.getByText('accessibility_trusted')).toBeTruthy());
    // Read the verdict off each key's own row, so the assertion cannot be satisfied by
    // the right word appearing somewhere else on the card.
    const verdict = (key) => screen.getByText(key).parentElement.textContent.replace(key, '');
    // null → unknown, and never the words a reader would act on.
    for (const key of ['accessibility_trusted', 'uinput_writable', 'vlm_proven_local']) {
      expect(verdict(key)).toBe('unknown');
    }
    expect(verdict('screen_capture')).toBe('yes');
    expect(verdict('process_elevated')).toBe('no');
    // A non-boolean fact is printed as itself, not squeezed into the tri-state.
    expect(verdict('portal_remote_desktop_version')).toBe('1');
    expect(verdict('xdg_session_type')).toBe('wayland');
  });

  it('reads a clear probe with every rail off as capable, not as enabled', async () => {
    mockFetch({
      '/api/host/probe': ok({ ...PROBE, ok: true, refusals: [], warnings: [], hints: {} }),
    });
    render(<HostReadinessPanel />);
    await waitFor(() => expect(screen.getByText('nothing blocking')).toBeTruthy());
    expect(screen.getByText('all host rails off')).toBeTruthy();
    expect(screen.getByText(/Readiness is not enablement/)).toBeTruthy();
  });

  it('renders the benchmark headline verbatim rather than composing a rate', async () => {
    mockFetch({ '/api/operator/benchmark': ok(BENCH), '/api/host/probe': ok(PROBE) });
    render(<HostReadinessPanel />);
    await waitFor(() => expect(
      screen.getByText('19/19 hermetic; nothing confirmed on a real host yet')).toBeTruthy());
    expect(screen.getByText('governance clean')).toBeTruthy();
    // the panel must not invent a percentage of its own
    expect(screen.queryByText(/100%/)).toBeNull();
  });

  it('renders a never-run benchmark as never-run, not as a zero score', async () => {
    mockFetch({
      '/api/operator/benchmark': ok({
        ok: true, recorded: false, tasks: 19,
        reason: 'the operator benchmark has not been run on this install',
        how: 'python scripts/operator_bench.py',
      }),
      '/api/host/probe': ok(PROBE),
    });
    render(<HostReadinessPanel />);
    await waitFor(() => expect(screen.getByText('never run')).toBeTruthy());
    expect(screen.getByText(/has not been run on this install/)).toBeTruthy();
    expect(screen.queryByText(/hermetic/)).toBeNull();
  });

  it('marks a result measured against different questions as stale', async () => {
    mockFetch({
      '/api/operator/benchmark': ok({ ...BENCH, stale: true }),
      '/api/host/probe': ok(PROBE),
    });
    render(<HostReadinessPanel />);
    await waitFor(() => expect(screen.getByText('stale')).toBeTruthy());
    expect(screen.getByText(/not a score for the current pack/)).toBeTruthy();
  });

  it('shows a governance breach in red above the rate', async () => {
    mockFetch({
      '/api/operator/benchmark': ok({
        ...BENCH, governance_clean: false,
        headline: '1 action(s) bypassed governance — the pack does not pass at any rate until that is zero',
      }),
      '/api/host/probe': ok(PROBE),
    });
    render(<HostReadinessPanel />);
    await waitFor(() => expect(screen.getByText('governance breach')).toBeTruthy());
    expect(screen.getByText(/does not pass at any rate/)).toBeTruthy();
  });

  it('labels the negative control so its expected failure never reads as a defect', async () => {
    const fn = mockFetch({
      '/api/operator/benchmark/pack': ok({
        ok: true, scored: 19, negative_controls: ['vision-ungoverned-negative-control'],
        tasks: [
          { id: 'a', surface: 'desktop', describe: 'observe a window',
            live_twin: 't', negative_control: false },
          { id: 'vision-ungoverned-negative-control', surface: 'vision',
            describe: 'a correct result reached ungoverned must still fail',
            live_twin: 't', negative_control: true },
        ],
      }),
      '/api/operator/benchmark': ok(BENCH),
      '/api/host/probe': ok(PROBE),
    });
    render(<HostReadinessPanel />);
    await waitFor(() => expect(screen.getByTitle(/show the benchmark questions/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/show the benchmark questions/));
    await waitFor(() => expect(screen.getByText('observe a window')).toBeTruthy());
    expect(screen.getByText('negative control')).toBeTruthy();
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/benchmark/pack'))).toBe(true);
  });

  it('renders a failed probe as its own state and claims no host facts', async () => {
    mockFetch({
      '/api/host/probe': ok({
        ok: false, probed: false, reason: 'probe_failed', vocabulary: [], probed_at: 1,
      }),
    });
    render(<HostReadinessPanel />);
    await waitFor(() => expect(screen.getByText('probe_failed')).toBeTruthy());
    expect(screen.getByText(/no facts were collected at all/)).toBeTruthy();
    expect(screen.queryByText('nothing blocking')).toBeNull();
  });
});
