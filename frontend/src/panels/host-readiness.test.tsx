// @ts-nocheck
/* HOST READINESS panel — `fetch` is mocked (not api/client) so the REAL client path runs.

   Claims pinned:
   · the probe is read from the backend and the platform + refusals render verbatim;
   · every blocking refusal renders the backend's own hint text, unedited;
   · a tri-state permission of `null` renders "unknown" — never "no" and never "yes";
   · `ok:true` with every host rail off reads as capable-but-off, not as enabled;
   · a probe that could not run renders its reason and claims no facts about the host. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
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
