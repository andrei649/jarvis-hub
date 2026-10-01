// @ts-nocheck
/* HUD-v3 C6 — the Console Governance scorecard + Security posture panels read the real
   security endpoints (/api/security/governance open · /api/security/posture admin) and
   render the suite scores + packaged posture. fetch is mocked, like
   kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { GovernancePanel, PosturePanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('GovernancePanel — the trust scorecard is live', () => {
  it('GETs /api/security/governance and shows the gate + per-suite scores', async () => {
    const fn = mockFetch({
      injection: { n: 6, passed: 6, score: 1.0 },
      harm: { n: 6, passed: 5, score: 0.83 },
      owasp: { n: 10, passed: 10, score: 1.0 },
      overall_score: 0.94, threshold: 0.9, pass: true,
    });
    render(<GovernancePanel />);
    await waitFor(() => expect(screen.getByText('gate: pass')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/security/governance'))).toBe(true);
    expect(screen.getByText('injection')).toBeTruthy();
    expect(screen.getByText('5/6')).toBeTruthy();   // the harm suite's partial pass
  });

  it('surfaces a FAILED gate honestly', async () => {
    mockFetch({
      injection: { n: 6, passed: 4, score: 0.66 }, harm: { n: 6, passed: 6, score: 1.0 },
      owasp: { n: 10, passed: 9, score: 0.9 }, overall_score: 0.85, threshold: 0.9, pass: false,
    });
    render(<GovernancePanel />);
    await waitFor(() => expect(screen.getByText('gate: FAIL')).toBeTruthy());
  });
});

describe('PosturePanel — packaged security posture is live', () => {
  it('GETs /api/security/posture and shows secrets/signing/sandbox state', async () => {
    const fn = mockFetch({
      secrets: { encrypted_at_rest: true, backend: 'fernet' },
      skills: { require_signed: true, total: 10, trusted: 9, untrusted: 1, untrusted_names: ['x'] },
      sandbox: { isolated: true, docker_available: true },
      guardrails: { mode: 'BLOCK' },
    });
    render(<PosturePanel />);
    await waitFor(() => expect(screen.getByText('guardrails: BLOCK')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/security/posture'))).toBe(true);
    expect(screen.getByText('encrypted')).toBeTruthy();
    expect(screen.getByText('fernet')).toBeTruthy();
    expect(screen.getByText('9/10 trusted')).toBeTruthy();
    expect(screen.getByText('isolated')).toBeTruthy();
  });
});

describe('PosturePanel — an unreadable secret store is not reported as encrypted', () => {
  it('shows "unknown" in amber, not "encrypted", when the backend is unavailable', async () => {
    // The endpoint used to return a hardcoded `encrypted_at_rest: true`, so this
    // tag was green whether or not the store could be opened — on the one screen
    // whose entire purpose is to report security posture honestly.
    mockFetch({
      secrets: { encrypted_at_rest: null, backend: 'unavailable',
                 note: 'secret store could not be opened — at-rest state unknown' },
      skills: { require_signed: true, total: 0, trusted: 0, untrusted: 0, untrusted_names: [] },
      sandbox: { isolated: null, docker_available: false },
      guardrails: { mode: 'BLOCK' },
    });
    render(<PosturePanel />);
    await waitFor(() => expect(screen.getByText('unknown')).toBeTruthy());
    expect(screen.queryByText('encrypted')).toBeNull();
    // "plain" would be its own false claim — we did not observe plaintext, we
    // failed to look.
    expect(screen.queryByText('plain')).toBeNull();
  });

  it('still says "plain" when the store genuinely reports no encryption', async () => {
    mockFetch({
      secrets: { encrypted_at_rest: false, backend: 'none' },
      skills: { require_signed: false, total: 0, trusted: 0, untrusted: 0, untrusted_names: [] },
      sandbox: { isolated: false, docker_available: false },
      guardrails: { mode: 'OFF' },
    });
    render(<PosturePanel />);
    await waitFor(() => expect(screen.getByText('plain')).toBeTruthy());
  });
});

describe('PosturePanel — provider data handling', () => {
  const scope = 'a'.repeat(64);
  const row = { provider: 'compatible', policy: 'unknown', note: 'Account terms are unverified',
    warning: 'This provider may use prompts for training.', acknowledged: false, last_used: null, scope };

  it('acknowledges and revokes the current configuration without hiding its warning', async () => {
    let acknowledged = false;
    const fn = vi.fn(async (url, options) => {
      if (options?.method === 'POST') {
        acknowledged = JSON.parse(options.body).acknowledged;
        return { ok: true, status: 200, json: async () => ({ ok: true, acknowledged }) };
      }
      return { ok: true, status: 200, json: async () => ({
        data_handling: { settings_readable: true, providers: [{ ...row, acknowledged }] },
      }) };
    });
    global.fetch = fn;
    render(<PosturePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Allow unattended use for compatible' }));
    await screen.findByRole('button', { name: 'Revoke unattended use for compatible' });
    expect(screen.getByText(row.warning)).toBeTruthy();
    expect(screen.getByText(row.note)).toBeTruthy();
    const calls = () => fn.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(String(calls()[0][0])).toContain('/api/security/data-handling/ack');
    expect(JSON.parse(calls()[0][1].body)).toEqual({ provider: 'compatible', acknowledged: true, scope });
    fireEvent.click(screen.getByRole('button', { name: 'Revoke unattended use for compatible' }));
    await screen.findByRole('button', { name: 'Allow unattended use for compatible' });
    expect(JSON.parse(calls()[1][1].body)).toEqual({ provider: 'compatible', acknowledged: false, scope });
    expect(screen.getByText(row.warning)).toBeTruthy();
  });

  it('keeps the warning and unacknowledged state when consent is refused', async () => {
    global.fetch = vi.fn(async (_, options) => options?.method === 'POST'
      ? { ok: false, status: 409, json: async () => ({ error: 'Configuration changed; reload.' }) }
      : { ok: true, status: 200, json: async () => ({ data_handling: {
        settings_readable: true, providers: [row],
      } }) });
    render(<PosturePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Allow unattended use for compatible' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/Configuration changed/));
    expect(screen.queryByRole('button', { name: 'Revoke unattended use for compatible' })).toBeNull();
    expect(screen.getByText(row.warning)).toBeTruthy();
  });

  it('cannot grant consent when the policy store is unreadable', async () => {
    mockFetch({ data_handling: { settings_readable: false, providers: [row] } });
    render(<PosturePanel />);
    const button = await screen.findByRole('button', { name: 'Allow unattended use for compatible' });
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/Consent settings unavailable/)).toBeTruthy();
  });

  it('explains why an ambiguous provider cannot be acknowledged', async () => {
    mockFetch({ data_handling: { settings_readable: true, providers: [{ ...row,
      can_acknowledge: false, acknowledgment_unavailable: 'Multiple configured accounts; select a unique provider configuration.',
    }] } });
    render(<PosturePanel />);
    const button = await screen.findByRole('button', { name: 'Allow unattended use for compatible' });
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/Multiple configured accounts/)).toBeTruthy();
  });
});

describe('PosturePanel — separate approval judge consent', () => {
  const scope = 'b'.repeat(64);
  const provider = { provider: 'compatible', policy: 'unknown', warning: 'Provider warning', scope: 'a'.repeat(64), acknowledged: false };
  const target = { target_id: 'role:approval_judge', label: 'Approval judge', provider: 'compatible', model: 'judge-model',
    mode: 'dedicated', policy: 'unknown', warning: 'Judge warning', scope, acknowledged: false, can_acknowledge: true };

  it('uses a distinct role identity and sends target only for role controls', async () => {
    const fn = vi.fn(async (_, options) => options?.method === 'POST'
      ? { ok: true, status: 200, json: async () => ({ ok: true }) }
      : { ok: true, status: 200, json: async () => ({ data_handling: {
        settings_readable: true, role_settings_readable: true, providers: [provider], targets: [target],
      } }) });
    global.fetch = fn;
    render(<PosturePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Allow unattended use for Approval judge' }));
    await waitFor(() => expect(fn.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Allow unattended use for compatible' }).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Allow unattended use for compatible' }));
    await waitFor(() => expect(fn.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(2));
    const calls = fn.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(JSON.parse(calls[0][1].body)).toEqual({ target: 'role:approval_judge', provider: 'compatible', scope, acknowledged: true });
    expect(JSON.parse(calls[1][1].body)).toEqual({ provider: 'compatible', scope: provider.scope, acknowledged: true });
    expect(screen.getByText(/judge-model/)).toBeTruthy();
    expect(screen.getByText('Judge warning')).toBeTruthy();
  });

  it('disables unreadable role settings independently of provider controls', async () => {
    mockFetch({ data_handling: { settings_readable: true, role_settings_readable: false, providers: [provider], targets: [target] } });
    render(<PosturePanel />);
    expect((await screen.findByRole('button', { name: 'Allow unattended use for Approval judge' })).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Allow unattended use for compatible' }).disabled).toBe(false);
    expect(screen.getByText(/Role consent settings unavailable/)).toBeTruthy();
  });
});


describe('PosturePanel — Telegram media role consent', () => {
  const judge = { target_id: 'role:approval_judge', provider: 'compatible', model: 'judge-model', mode: 'dedicated',
    policy: 'unknown', warning: 'Judge warning', scope: 'b'.repeat(64), acknowledged: false };
  const media = { target_id: 'role:telegram_media_reader', provider: 'compatible', model: 'vision-model', mode: 'dedicated',
    policy: 'unknown', warning: 'Media warning', scope: 'c'.repeat(64), acknowledged: false };

  it('grants and revokes same-provider roles independently with exact target and scope', async () => {
    const states = { [judge.target_id]: false, [media.target_id]: false };
    const fn = vi.fn(async (_, options) => {
      if (options?.method === 'POST') {
        const body = JSON.parse(options.body);
        states[body.target] = body.acknowledged;
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
      }
      return { ok: true, status: 200, json: async () => ({ data_handling: {
        settings_readable: true, role_settings_readable: true, providers: [],
        targets: [judge, media].map(row => ({ ...row, acknowledged: states[row.target_id] })),
      } }) };
    });
    global.fetch = fn;
    render(<PosturePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Allow unattended use for Telegram image descriptions' }));
    await screen.findByRole('button', { name: 'Revoke unattended use for Telegram image descriptions' });
    expect(screen.getByRole('button', { name: 'Allow unattended use for Approval judge' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Allow unattended use for Approval judge' }));
    await screen.findByRole('button', { name: 'Revoke unattended use for Approval judge' });
    fireEvent.click(screen.getByRole('button', { name: 'Revoke unattended use for Telegram image descriptions' }));
    await screen.findByRole('button', { name: 'Allow unattended use for Telegram image descriptions' });
    expect(screen.getByRole('button', { name: 'Revoke unattended use for Approval judge' })).toBeTruthy();
    const bodies = fn.mock.calls.filter(([, options]) => options?.method === 'POST').map(([, options]) => JSON.parse(options.body));
    expect(bodies).toEqual([
      { target: media.target_id, provider: 'compatible', scope: media.scope, acknowledged: true },
      { target: judge.target_id, provider: 'compatible', scope: judge.scope, acknowledged: true },
      { target: media.target_id, provider: 'compatible', scope: media.scope, acknowledged: false },
    ]);
    expect(screen.getByText(/compatible · dedicated · vision-model/)).toBeTruthy();
    expect(screen.getByText(/Unknown or training policies require their own acknowledgment/)).toBeTruthy();
    expect(screen.getByText(/does not enable remote image descriptions/)).toBeTruthy();
    expect(screen.getByText('Media warning')).toBeTruthy();
  });

  it('keeps a refused media save unacknowledged and preserves its warning', async () => {
    global.fetch = vi.fn(async (_, options) => options?.method === 'POST'
      ? { ok: true, status: 200, json: async () => ({ ok: false }) }
      : { ok: true, status: 200, json: async () => ({ data_handling: {
        role_settings_readable: true, targets: [media],
      } }) });
    render(<PosturePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Allow unattended use for Telegram image descriptions' }));
    await screen.findByText('Consent was not saved.');
    expect(screen.queryByRole('button', { name: 'Revoke unattended use for Telegram image descriptions' })).toBeNull();
    expect(screen.getByText('Media warning')).toBeTruthy();
  });

  it('disables both roles when their shared store is unreadable', async () => {
    mockFetch({ data_handling: { role_settings_readable: false, targets: [judge, media] } });
    render(<PosturePanel />);
    expect((await screen.findByRole('button', { name: 'Allow unattended use for Telegram image descriptions' })).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Allow unattended use for Approval judge' }).disabled).toBe(true);
    expect(screen.getByText(/Role consent settings unavailable/)).toBeTruthy();
  });

  it('never offers controls for unknown target IDs or trusts their labels', async () => {
    mockFetch({ data_handling: { role_settings_readable: true, targets: [{ ...media,
      target_id: 'role:unregistered', label: 'Injected control label',
    }] } });
    render(<PosturePanel />);
    await screen.findByText('provider data handling');
    expect(screen.queryByText('Injected control label')).toBeNull();
    expect(screen.queryByRole('button', { name: /unattended use/ })).toBeNull();
  });
});


describe('PosturePanel — separate camera model-data consent', () => {
  const camera = { target_id: 'role:camera_descriptions', provider: 'compatible', model: 'camera-model', mode: 'dedicated',
    policy: 'unknown', warning: 'Camera model policy is unknown.', scope: 'd'.repeat(64), acknowledged: false };
  const judge = { ...camera, target_id: 'role:approval_judge', model: 'judge-model', scope: 'b'.repeat(64), acknowledged: true };
  const media = { ...camera, target_id: 'role:telegram_media_reader', model: 'media-model', scope: 'c'.repeat(64), acknowledged: true };

  it('changes only camera consent for three roles using the same provider', async () => {
    let acknowledged = false;
    const fn = vi.fn(async (_, options) => {
      if (options?.method === 'POST') {
        acknowledged = JSON.parse(options.body).acknowledged;
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
      }
      return { ok: true, status: 200, json: async () => ({ data_handling: {
        role_settings_readable: true, targets: [judge, media, { ...camera, acknowledged }],
      } }) };
    });
    global.fetch = fn;
    render(<PosturePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Allow unattended use for Camera descriptions' }));
    await screen.findByRole('button', { name: 'Revoke unattended use for Camera descriptions' });
    expect(screen.getByRole('button', { name: 'Revoke unattended use for Approval judge' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Revoke unattended use for Telegram image descriptions' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Revoke unattended use for Camera descriptions' }));
    await screen.findByRole('button', { name: 'Allow unattended use for Camera descriptions' });
    expect(screen.getByRole('button', { name: 'Revoke unattended use for Approval judge' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Revoke unattended use for Telegram image descriptions' })).toBeTruthy();
    const bodies = fn.mock.calls.filter(([, options]) => options?.method === 'POST').map(([, options]) => JSON.parse(options.body));
    expect(bodies).toEqual([true, false].map(acknowledged => ({
      target: camera.target_id, provider: camera.provider, scope: camera.scope, acknowledged,
    })));
    expect(screen.getByText(/compatible · dedicated · camera-model/)).toBeTruthy();
    expect(screen.getByText(/Camera descriptions require a local VLM on the Nerva server/)).toBeTruthy();
    expect(screen.getByText(/Unknown or training policies require separate model-data acknowledgment/)).toBeTruthy();
    expect(screen.getByText(/does not enable camera capture, event description or remote destinations/)).toBeTruthy();
    expect(screen.getByText(/does not replace household consent/)).toBeTruthy();
  });

  it('disables camera controls when shared role settings are unavailable', async () => {
    mockFetch({ data_handling: { role_settings_readable: false, targets: [camera] } });
    render(<PosturePanel />);
    expect((await screen.findByRole('button', { name: 'Allow unattended use for Camera descriptions' })).disabled).toBe(true);
    expect(screen.getByText(/Role consent settings unavailable/)).toBeTruthy();
  });

  it('preserves judge and Telegram controls when the camera target is absent', async () => {
    mockFetch({ data_handling: { role_settings_readable: true, targets: [judge, media] } });
    render(<PosturePanel />);
    await screen.findByRole('button', { name: 'Revoke unattended use for Approval judge' });
    expect(screen.getByRole('button', { name: 'Revoke unattended use for Telegram image descriptions' })).toBeTruthy();
    expect(screen.queryByText('Camera descriptions')).toBeNull();
    expect(screen.queryByRole('button', { name: /for Camera descriptions/ })).toBeNull();
  });
});

describe('PosturePanel — separate video analysis consent', () => {
  it('sends the video role target and explains the separate approval', async () => {
    const target = { target_id: 'role:video_analysis', provider: 'openai-compatible', model: 'video-model',
      mode: 'dedicated', policy: 'unknown', warning: 'Unknown video policy',
      scope: 'e'.repeat(64), acknowledged: false, can_acknowledge: true };
    const fn = mockFetch({ data_handling: { role_settings_readable: true, targets: [target] } });
    render(<PosturePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Allow unattended use for Video analysis' }));
    await waitFor(() => expect(fn.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(true));
    const post = fn.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(JSON.parse(post[1].body)).toEqual({ target: 'role:video_analysis', provider: 'openai-compatible',
      scope: target.scope, acknowledged: true });
    expect(screen.getByText(/separate owner-approved tool call/)).toBeTruthy();
  });
});
