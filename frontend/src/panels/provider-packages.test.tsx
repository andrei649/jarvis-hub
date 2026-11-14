// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ProviderPackagesPanel } from './provider-packages';
import { ConsoleOverlay } from '../gap';

const ARTIFACT_ID = 'a'.repeat(32);
const ARTIFACT_ID_2 = 'b'.repeat(32);
const PACKAGE_HASH = '1'.repeat(64);

const samplePreview = {
  artifact_id: ARTIFACT_ID,
  provider_id: 'synthetic-addon',
  package_hash: PACKAGE_HASH,
  source: 'user',
  replacement_target: null,
  hooks: ['build_headers'],
  endpoint_host: 'api.example.org',
  auth_type: 'bearer',
  backend_kind: 'openai-compatible',
  profile_summary: {
    id: 'synthetic-addon',
    endpoint: { scheme: 'https', host: 'api.example.org', port: null },
    backend_kind: 'openai-compatible',
    api_mode: 'chat_completions',
    auth: { type: 'bearer', configured: false },
    capabilities: ['chat', 'cloud'],
    data_policy: { policy: 'unknown' },
    supports_health_check: true,
    supports_model_listing: true,
  },
  sandbox_image: 'jarvis-sandbox:local',
  sandbox: { network: 'none' },
  member_count: 2,
  member_bytes: 512,
};

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('ProviderPackagesPanel owner surface', () => {
  it('renders inert plugin gate and honest 409 selection banner when plugins are disabled', async () => {
    global.fetch = vi.fn(async (url) => {
      const target = String(url);
      if (target.endsWith('/api/llm/provider-packages/status')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ enabled: false, runtime_present: true, selects_model: false }),
        };
      }
      if (target.endsWith('/api/admin/llm/provider-selection')) {
        return {
          ok: false,
          status: 409,
          json: async () => ({ detail: 'provider_install_unavailable' }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(<ProviderPackagesPanel />);
    await screen.findByText('INERT');
    expect(screen.getByText('SEED')).toBeTruthy();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('refused · HTTP 409 · provider_install_unavailable');
  });

  it('drives stage, inspect, propose, permanent-consent decision, promote, and revoke routes', async () => {
    const calls = [];
    global.fetch = vi.fn(async (url, init = {}) => {
      const target = String(url);
      const method = init.method || 'GET';
      calls.push([method, target, init.body ? JSON.parse(init.body) : undefined]);

      if (method === 'GET' && target.endsWith('/api/llm/provider-packages/status')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ enabled: true, runtime_present: true, selects_model: false }),
        };
      }
      if (method === 'GET' && target.endsWith('/api/admin/llm/provider-selection')) {
        return { ok: true, status: 200, json: async () => ({ status: 'unselected' }) };
      }
      if (method === 'POST' && target.endsWith('/api/llm/provider-packages/stage')) {
        return { ok: true, status: 200, json: async () => samplePreview };
      }
      if (method === 'GET' && target.endsWith(`/api/llm/provider-packages/${ARTIFACT_ID_2}`)) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ...samplePreview, artifact_id: ARTIFACT_ID_2, provider_id: 'inspected-addon' }),
        };
      }
      if (method === 'POST' && target.endsWith(`/api/llm/provider-packages/${ARTIFACT_ID}/propose`)) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ...samplePreview, proposal_id: 'prop-101', status: 'pending' }),
        };
      }
      if (method === 'POST' && target.endsWith('/api/llm/provider-packages/proposals/prop-101/decision')) {
        const parsed = JSON.parse(init.body);
        return {
          ok: true,
          status: 200,
          json: async () => ({
            proposal_id: 'prop-101',
            status: parsed.approved ? 'approved' : 'denied',
          }),
        };
      }
      if (method === 'POST' && target.endsWith('/api/llm/provider-packages/proposals/prop-101/promote')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ...samplePreview, status: 'active' }),
        };
      }
      if (method === 'POST' && target.endsWith('/api/llm/provider-packages/synthetic-addon/revoke')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ provider_id: 'synthetic-addon', status: 'revoked' }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(<ProviderPackagesPanel />);
    await screen.findByText('READY');

    // Inspect an existing artifact by ID
    fireEvent.change(screen.getByLabelText('Inspect artifact ID'), { target: { value: ARTIFACT_ID_2 } });
    fireEvent.click(screen.getByText('Inspect artifact'));
    await screen.findByText(/Inspected artifact/);
    expect(calls.some(([m, u]) => m === 'GET' && u.endsWith(`/api/llm/provider-packages/${ARTIFACT_ID_2}`))).toBe(true);

    // Stage a signed candidate
    fireEvent.change(screen.getByLabelText('Stage provider ID'), { target: { value: 'synthetic-addon' } });
    fireEvent.change(screen.getByLabelText('Stage display name'), { target: { value: 'Synthetic Addon' } });
    fireEvent.change(screen.getByLabelText('Stage base URL'), { target: { value: 'https://api.example.org/v1' } });
    fireEvent.change(screen.getByLabelText('Stage declared models'), { target: { value: 'addon-chat' } });
    fireEvent.click(screen.getByText('Stage candidate'));

    await screen.findByText(/model selection unchanged/);
    const stageCall = calls.find(([m, u]) => m === 'POST' && u.endsWith('/api/llm/provider-packages/stage'));
    expect(stageCall[2]).toEqual({
      candidate: 'addon',
      source: 'user',
      profile: {
        id: 'synthetic-addon',
        display_name: 'Synthetic Addon',
        backend_kind: 'openai-compatible',
        api_mode: 'chat_completions',
        default_base_url: 'https://api.example.org/v1',
        auth_type: 'bearer',
        data_policy: 'unknown',
        capabilities: ['chat', 'cloud'],
        fallback_models: ['addon-chat'],
      },
      hooks: ['build_headers'],
      replacement_target: null,
    });

    // Propose the staged artifact
    fireEvent.click(screen.getByText('Propose artifact'));
    await screen.findByText(/Proposal prop-101 created/);

    // Approve and Deny buttons must remain disabled until permanent-consent checkbox is checked
    const approveBtn = screen.getByText('Approve proposal');
    const denyBtn = screen.getByText('Deny proposal');
    expect(approveBtn.disabled).toBe(true);
    expect(denyBtn.disabled).toBe(true);

    const consentCheckbox = screen.getByLabelText(/I permanently authorize this exact artifact and package hash decision/);
    fireEvent.click(consentCheckbox);
    expect(approveBtn.disabled).toBe(false);
    expect(denyBtn.disabled).toBe(false);

    fireEvent.click(approveBtn);
    await screen.findByText(/Proposal prop-101 marked approved/);
    const approveCall = calls.find(([m, u]) => m === 'POST' && u.endsWith('/api/llm/provider-packages/proposals/prop-101/decision'));
    expect(approveCall[2]).toEqual({
      artifact_id: ARTIFACT_ID,
      package_hash: PACKAGE_HASH,
      approved: true,
      permanent: true,
    });

    // Permanent consent resets after submission so another decision cannot fire without fresh consent
    expect(consentCheckbox.checked).toBe(false);
    expect(denyBtn.disabled).toBe(true);

    // Verify deny path also sends approved: false, permanent: true when re-checked
    fireEvent.click(consentCheckbox);
    fireEvent.click(denyBtn);
    await screen.findByText(/Proposal prop-101 marked denied/);
    const decisionCalls = calls.filter(([m, u]) => m === 'POST' && u.endsWith('/api/llm/provider-packages/proposals/prop-101/decision'));
    expect(decisionCalls[1][2]).toEqual({
      artifact_id: ARTIFACT_ID,
      package_hash: PACKAGE_HASH,
      approved: false,
      permanent: true,
    });

    // Promote (activate package)
    fireEvent.click(screen.getByText('Promote (activate package)'));
    await screen.findByText(/Activated package synthetic-addon/);
    expect(calls.some(([m, u]) => m === 'POST' && u.endsWith('/api/llm/provider-packages/proposals/prop-101/promote'))).toBe(true);

    // Revoke (deactivate / remove)
    fireEvent.click(screen.getByText('Revoke (deactivate / remove)'));
    await screen.findByText(/Provider synthetic-addon revoked/);
    expect(calls.some(([m, u]) => m === 'POST' && u.endsWith('/api/llm/provider-packages/synthetic-addon/revoke'))).toBe(true);
  });

  it('checks, rotates, and deletes provider credentials while clearing secrets on both 200 and 409', async () => {
    const calls = [];
    let refusePut = false;
    global.fetch = vi.fn(async (url, init = {}) => {
      const target = String(url);
      const method = init.method || 'GET';
      calls.push([method, target, init.body ? JSON.parse(init.body) : undefined]);

      if (method === 'GET' && target.endsWith('/api/llm/provider-packages/status')) {
        return { ok: true, status: 200, json: async () => ({ enabled: true, runtime_present: true, selects_model: false }) };
      }
      if (method === 'GET' && target.endsWith('/api/admin/llm/provider-selection')) {
        return { ok: true, status: 200, json: async () => ({ status: 'unselected' }) };
      }
      if (method === 'GET' && target.includes('/api/admin/llm/provider-credentials?')) {
        return { ok: true, status: 200, json: async () => ({ configured: false, generation: 2 }) };
      }
      if (method === 'PUT' && target.endsWith('/api/admin/llm/provider-credentials')) {
        if (refusePut) {
          return { ok: false, status: 409, json: async () => ({ error: 'provider_credential_refused' }) };
        }
        return { ok: true, status: 200, json: async () => ({ configured: true, generation: 3 }) };
      }
      if (method === 'DELETE' && target.endsWith('/api/admin/llm/provider-credentials')) {
        return { ok: true, status: 200, json: async () => ({ configured: false, generation: 3 }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    const { container } = render(<ProviderPackagesPanel />);
    await screen.findByText('READY');

    fireEvent.change(screen.getByLabelText('Credential provider ID'), { target: { value: 'synthetic-addon' } });
    fireEvent.change(screen.getByLabelText('Credential package hash'), { target: { value: PACKAGE_HASH } });

    // Check status
    fireEvent.click(screen.getByText('Check credential'));
    await screen.findByText(/Credential for synthetic-addon: absent \(generation 2\)/);

    // Store secret (200) -> input cleared immediately, secret never appears in DOM
    const secretInput = screen.getByLabelText('Provider credential secret');
    expect(secretInput.getAttribute('type')).toBe('password');
    fireEvent.change(secretInput, { target: { value: 'top-secret-token-alpha' } });
    fireEvent.click(screen.getByText('Store or rotate credential'));

    await screen.findByText(/Credential stored for synthetic-addon \(generation 3\)/);
    expect(secretInput.value).toBe('');
    expect(container.textContent).not.toContain('top-secret-token-alpha');
    const putCall = calls.find(([m, u]) => m === 'PUT' && u.endsWith('/api/admin/llm/provider-credentials'));
    expect(putCall[2]).toEqual({
      provider: 'synthetic-addon',
      package_hash: PACKAGE_HASH,
      value: 'top-secret-token-alpha',
    });

    // Refused secret rotation (409) -> input STILL cleared, honest alert shown, secret never echoed
    refusePut = true;
    fireEvent.change(secretInput, { target: { value: 'refused-secret-token-beta' } });
    fireEvent.click(screen.getByText('Store or rotate credential'));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('refused · HTTP 409 · provider_credential_refused');
    expect(secretInput.value).toBe('');
    expect(container.textContent).not.toContain('refused-secret-token-beta');

    // Delete credential with JSON body
    fireEvent.click(screen.getByText('Delete credential'));
    await screen.findByText(/Credential deleted for synthetic-addon \(generation 3\)/);
    const delCall = calls.find(([m, u]) => m === 'DELETE' && u.endsWith('/api/admin/llm/provider-credentials'));
    expect(delCall[2]).toEqual({
      provider: 'synthetic-addon',
      package_hash: PACKAGE_HASH,
    });
  });

  it('selects and clears provider models with CAS revisions and renders honest 409 and 503 refusals', async () => {
    const calls = [];
    let putMode = 'guard_409';
    let currentSelection = { status: 'unselected' };

    global.fetch = vi.fn(async (url, init = {}) => {
      const target = String(url);
      const method = init.method || 'GET';
      calls.push([method, target, init.body ? JSON.parse(init.body) : undefined]);

      if (method === 'GET' && target.endsWith('/api/llm/provider-packages/status')) {
        return { ok: true, status: 200, json: async () => ({ enabled: true, runtime_present: true, selects_model: false }) };
      }
      if (method === 'GET' && target.endsWith('/api/admin/llm/provider-selection')) {
        return { ok: true, status: 200, json: async () => currentSelection };
      }
      if (method === 'PUT' && target.endsWith('/api/admin/llm/provider-selection')) {
        if (putMode === 'guard_409') {
          return {
            ok: false,
            status: 409,
            json: async () => ({ error: 'selection_guard', needs: ['acknowledge_data_policy'] }),
          };
        }
        if (putMode === 'unavailable_503') {
          return {
            ok: false,
            status: 503,
            json: async () => ({ error: 'provider_selection_unavailable' }),
          };
        }
        currentSelection = {
          status: 'selected',
          provider: 'synthetic-addon',
          model: 'addon-chat',
          package_hash: PACKAGE_HASH,
          revision: 4,
          credential_generation: 3,
        };
        return { ok: true, status: 200, json: async () => currentSelection };
      }
      if (method === 'DELETE' && target.endsWith('/api/admin/llm/provider-selection')) {
        currentSelection = { status: 'unselected' };
        return { ok: true, status: 200, json: async () => ({ status: 'cleared', revision: 5 }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    render(<ProviderPackagesPanel />);
    await screen.findByText('READY');

    fireEvent.change(screen.getByLabelText('Selection provider ID'), { target: { value: 'synthetic-addon' } });
    fireEvent.change(screen.getByLabelText('Selection package hash'), { target: { value: PACKAGE_HASH } });
    fireEvent.change(screen.getByLabelText('Selection model'), { target: { value: 'addon-chat' } });

    const selectBtn = screen.getByText('Select provider model');
    expect(selectBtn.disabled).toBe(true);

    // Acknowledge unknown price -> enabled, first attempt hits 409 selection_guard
    fireEvent.click(screen.getByLabelText(/I acknowledge unknown model price/));
    expect(selectBtn.disabled).toBe(false);
    fireEvent.click(selectBtn);

    const alert409 = await screen.findByRole('alert');
    expect(alert409.textContent).toContain('refused · HTTP 409 · selection_guard · needs acknowledge_data_policy');
    expect(screen.queryByRole('status')).toBeNull();

    // Next attempt hits 503 provider_selection_unavailable -> honest 503 alert, never claims success
    putMode = 'unavailable_503';
    fireEvent.click(screen.getByLabelText(/I acknowledge the selected data policy/));
    fireEvent.click(selectBtn);

    const alert503 = await screen.findByRole('alert');
    expect(alert503.textContent).toContain('refused · HTTP 503 · provider_selection_unavailable');
    expect(screen.queryByRole('status')).toBeNull();

    // Succeeds when backend returns 200
    putMode = 'ok';
    fireEvent.click(selectBtn);
    await screen.findByText(/Selected synthetic-addon \(addon-chat\) at revision 4/);

    const okPut = calls.filter(([m, u]) => m === 'PUT' && u.endsWith('/api/admin/llm/provider-selection')).pop();
    expect(okPut[2]).toEqual({
      provider: 'synthetic-addon',
      package_hash: PACKAGE_HASH,
      model: 'addon-chat',
      expected_revision: 0,
      acknowledge_unknown_price: true,
      acknowledge_data_policy: true,
    });

    // Clear selection sends expected_revision: 4 via DELETE body
    fireEvent.click(screen.getByText('Clear selection'));
    await screen.findByText(/Provider selection cleared \(revision 5\)/);
    const delCall = calls.find(([m, u]) => m === 'DELETE' && u.endsWith('/api/admin/llm/provider-selection'));
    expect(delCall[2]).toEqual({ expected_revision: 4 });
  });

  it('mounts inside ConsoleOverlay under Admin route /v2/console/provider-packages with read-only initial load', async () => {
    global.fetch = vi.fn(async (url) => {
      if (String(url).endsWith('/api/llm/provider-packages/status')) {
        return { ok: true, status: 200, json: async () => ({ enabled: true, runtime_present: true, selects_model: false }) };
      }
      return { ok: true, status: 200, json: async () => ({ status: 'unselected' }) };
    });

    render(<ConsoleOverlay panelId="provider-packages" onClose={() => {}} />);
    expect(await screen.findByRole('heading', { name: 'Provider Packages' })).toBeTruthy();
    expect(await screen.findByText('SIGNED PROVIDER PACKAGES')).toBeTruthy();
    for (const [, init] of vi.mocked(global.fetch).mock.calls) {
      expect(init?.method || 'GET').toBe('GET');
    }
  });
});
