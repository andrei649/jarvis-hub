// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CustomEndpointsPanel } from './custom-endpoints';

const catalog = { endpoints: [{ key: 'office', identity: 'custom:office', name: 'Office',
  host: 'example.org', model: 'm', auth_type: 'bearer', data_policy: 'unknown',
  destination_class: 'public', revision: 2, active: false, credential_configured: false,
  credential_generation: 0 }], choice_epoch: 7, active: null,
  legacy_recovery_candidate: null, unavailable: false };

function mockResponses() {
  const calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    calls.push([String(url), init]);
    return { ok: true, status: 200, json: async () =>
      init.method === 'GET' || !init.method ? catalog : { ok: true } };
  });
  return calls;
}

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('named custom endpoint owner panel', () => {
  it('uses revisioned activation and an explicit price acknowledgement', async () => {
    const calls = mockResponses();
    render(<CustomEndpointsPanel />);
    await screen.findByText(/Office · custom:office/);
    const activate = screen.getByText('Activate');
    expect(activate.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/I acknowledge unknown model price/));
    fireEvent.click(screen.getByLabelText(/Grant this exact LAN or public destination for activation/));
    fireEvent.click(activate);
    await waitFor(() => expect(calls.some(([url]) => url.includes('/office/activate'))).toBe(true));
    const [, init] = calls.find(([url]) => url.includes('/office/activate'));
    expect(JSON.parse(init.body)).toEqual({ expected_revision: 2,
      expected_choice_epoch: 7, acknowledge_unknown_price: true,
      acknowledge_data_policy: false, grant_destination: true });
  });

  it('keeps the secret input empty after a credential mutation', async () => {
    const calls = mockResponses();
    render(<CustomEndpointsPanel />);
    await screen.findByText(/Office · custom:office/);
    fireEvent.click(screen.getByText('Credential'));
    const field = screen.getByLabelText('secret for office');
    fireEvent.change(field, { target: { value: 'synthetic-private-key' } });
    fireEvent.click(screen.getByText('Set or rotate'));
    await waitFor(() => expect(field.value).toBe(''));
    expect(screen.queryByText('synthetic-private-key')).toBeNull();
    const [, init] = calls.find(([url, options]) =>
      url.includes('/office/credential') && options.method === 'PUT');
    expect(JSON.parse(init.body)).toEqual({ secret: 'synthetic-private-key' });
  });

  it('clears a refused secret and shows only the bounded refusal', async () => {
    global.fetch = vi.fn(async (url, init = {}) => {
      if (String(url).includes('/credential') && init.method === 'PUT') {
        return { ok: false, status: 409, json: async () => ({ error: 'custom_endpoint_refused' }) };
      }
      return { ok: true, status: 200, json: async () => catalog };
    });
    render(<CustomEndpointsPanel />);
    await screen.findByText(/Office · custom:office/);
    fireEvent.click(screen.getByText('Credential'));
    const field = screen.getByLabelText('secret for office');
    fireEvent.change(field, { target: { value: 'synthetic-refused-secret' } });
    fireEvent.click(screen.getByText('Set or rotate'));
    await waitFor(() => expect(field.value).toBe(''));
    expect(screen.queryByText('synthetic-refused-secret')).toBeNull();
    expect(screen.getByText(/refused · HTTP 409/)).toBeTruthy();
  });
});
