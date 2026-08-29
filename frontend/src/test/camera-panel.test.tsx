// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CameraPanel } from '../gap';

function response(payload) {
  return Promise.resolve({ ok: true, status: 200, json: async () => payload });
}

const status = {
  enabled: true,
  status: 'healthy',
  reason: null,
  source: { status: 'online', camera_count: 1, last_success_at: 100, last_error: null },
  storage: { status: 'ready', items: 1, bytes: 200, last_sweep_at: 100 },
};

const event = {
  event_id: 'event-1',
  camera_id: 'front-door',
  label: 'person',
  occurred_at: 100,
  confidence: 0.91,
  anonymous: true,
  zone: 'porch',
  room_id: 'entry',
  description: 'An anonymous person left a package.',
  description_provenance: 'local_vlm_on_demand',
};

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  global.fetch = vi.fn((url) => {
    if (String(url).includes('/api/cameras/status')) return response(status);
    if (String(url).includes('/api/cameras/events')) {
      return response({ enabled: true, status: 'ok', reason: null, interpretation: {}, events: [event] });
    }
    return response({ enabled: true, status: 'empty', reason: 'no_matches', interpretation: {}, events: [] });
  });
});

describe('CameraPanel (H31.5)', () => {
  it('renders bounded metadata and never creates an image, video, or frame surface', async () => {
    const { container } = render(<CameraPanel />);
    await waitFor(() => expect(screen.getByText('front-door')).toBeTruthy());
    expect(screen.getByText('person')).toBeTruthy();
    expect(screen.getByText('porch')).toBeTruthy();
    expect(screen.getByText('91%')).toBeTruthy();
    expect(screen.getByText('An anonymous person left a package.')).toBeTruthy();
    expect(screen.getByText(/local vlm on demand/i)).toBeTruthy();
    expect(container.querySelector('img,video,iframe')).toBeNull();
    expect(container.innerHTML.toLowerCase()).not.toContain('background-image');
  });

  it('posts a bounded private search body and renders an honest empty state', async () => {
    render(<CameraPanel />);
    await waitFor(() => expect(screen.getByText('front-door')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('camera search'), { target: { value: 'courier yesterday' } });
    fireEvent.click(screen.getByRole('button', { name: /search camera events/i }));
    await waitFor(() => expect(screen.getByText(/no matching camera events/i)).toBeTruthy());
    const call = vi.mocked(global.fetch).mock.calls.find(([url]) => String(url).includes('/api/cameras/search'));
    expect(call).toBeTruthy();
    expect(JSON.parse(call[1].body)).toEqual({ query: 'courier yesterday', limit: 100 });
    expect(String(call[0])).not.toContain('courier');
  });

  it('shows default-off state without pretending the camera source is live', async () => {
    global.fetch = vi.fn((url) => String(url).includes('/api/cameras/status')
      ? response({ enabled: false, status: 'disabled', reason: 'camera_disabled', source: null, storage: null })
      : response({ enabled: false, status: 'disabled', reason: 'camera_disabled', interpretation: {}, events: [] }));
    render(<CameraPanel />);
    await waitFor(() => expect(screen.getByText(/camera intelligence is off/i)).toBeTruthy());
    expect(screen.queryByRole('button', { name: /search camera events/i })).toBeNull();
  });

  it('keeps ONVIF discovery behind the admin token and renders metadata only', async () => {
    localStorage.setItem('hud.admin_token', 'owner-token');
    global.fetch = vi.fn((url) => {
      if (String(url).includes('/api/cameras/status')) return response(status);
      if (String(url).includes('/api/cameras/events')) {
        return response({ enabled: true, status: 'ok', reason: null, interpretation: {}, events: [] });
      }
      if (String(url).includes('/api/cameras/onvif/discover')) {
        return response({
          enabled: true,
          status: 'online',
          reason: null,
          devices: [{ device_id: 'a'.repeat(24), name: 'Front Door', host: '192.168.1.40', port: 80, secure: false, mapped: true, frigate_camera_id: 'front-door' }],
        });
      }
      return response({});
    });
    render(<CameraPanel />);
    await waitFor(() => expect(screen.getByRole('button', { name: /discover ONVIF cameras/i })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /discover ONVIF cameras/i }));
    await waitFor(() => expect(screen.getByText(/192.168.1.40:80/)).toBeTruthy());
    const call = vi.mocked(global.fetch).mock.calls.find(([url]) => String(url).includes('/api/cameras/onvif/discover'));
    expect(call[1].headers['X-Admin-Token']).toBe('owner-token');
  });

  function mockDiscovery(payload) {
    localStorage.setItem('hud.admin_token', 'owner-token');
    global.fetch = vi.fn((url) => {
      if (String(url).includes('/api/cameras/status')) return response(status);
      if (String(url).includes('/api/cameras/events')) {
        return response({ enabled: true, status: 'ok', reason: null, interpretation: {}, events: [] });
      }
      if (String(url).includes('/api/cameras/onvif/discover')) return response(payload);
      return response({});
    });
  }

  it('surfaces a 200-body dependency refusal instead of a dead button', async () => {
    mockDiscovery({
      enabled: true,
      status: 'unavailable',
      reason: 'onvif_dependency_missing',
      detail: "ONVIF discovery needs the optional 'wsdiscovery' package on this host; run 'pip install wsdiscovery' and retry",
      devices: [],
    });
    render(<CameraPanel />);
    await waitFor(() => expect(screen.getByRole('button', { name: /discover ONVIF cameras/i })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /discover ONVIF cameras/i }));
    await waitFor(() => expect(screen.getByText(/onvif_dependency_missing/)).toBeTruthy());
    expect(screen.getByText(/pip install wsdiscovery/)).toBeTruthy();
  });

  it('renders a degraded discovery outcome with its reason', async () => {
    mockDiscovery({ enabled: true, status: 'degraded', reason: 'discovery_timeout', devices: [] });
    render(<CameraPanel />);
    await waitFor(() => expect(screen.getByRole('button', { name: /discover ONVIF cameras/i })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /discover ONVIF cameras/i }));
    await waitFor(() => expect(screen.getByText(/degraded · discovery_timeout/)).toBeTruthy());
  });

  it('says so when a healthy discovery simply finds nothing', async () => {
    mockDiscovery({ enabled: true, status: 'online', reason: null, devices: [] });
    render(<CameraPanel />);
    await waitFor(() => expect(screen.getByRole('button', { name: /discover ONVIF cameras/i })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /discover ONVIF cameras/i }));
    await waitFor(() => expect(screen.getByText(/no ONVIF devices found/i)).toBeTruthy());
  });
});
