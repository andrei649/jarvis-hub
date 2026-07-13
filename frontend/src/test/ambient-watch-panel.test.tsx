// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AmbientWatchPanel } from '../gap';

const response = (payload) => Promise.resolve({ ok: true, status: 200, json: async () => payload });

beforeEach(() => {
  global.fetch = vi.fn(() => response({
    enabled: true,
    status: 'live',
    reason: '',
    monitors: [{
      monitor_id: 'monitor.front.private',
      version: 2,
      source: 'camera',
      schema: 'camera.event.v1',
      enabled: true,
      alert_rung: 'interrupt',
      recovery_rung: 'monitor',
      state: 'alert',
      last_event_at: 1001,
      last_decision: {
        monitor_id: 'monitor.front.private', transition: 'alert', rung: 'interrupt',
        attention_mode: 'interrupt', policy_reason: 'policy_selected', decided_at: 1001,
      },
      subject_id: 'resident.alice.private',
      predicates: [{ expected: 'private-person-value' }],
    }],
    sources: [{ source: 'camera', status: 'live', last_event_at: 1001, reason: '', queued: 0, critical_backpressure: 0 }],
    last_decision: {
      monitor_id: 'monitor.front.private', transition: 'alert', rung: 'interrupt',
      attention_mode: 'interrupt', policy_reason: 'policy_selected', decided_at: 1001,
    },
    rung_counts: { ignore: 0, remember: 1, monitor: 2, act_silently: 0, ask: 1, interrupt: 1 },
    attention: { status: 'ready', reason: '', limit: 4, used: 1, remaining: 3 },
    privacy: { events: 'redacted', subjects: 'redacted' },
  }));
});

describe('AmbientWatchPanel (H33.6)', () => {
  it('renders live monitor decisions and global budget without private event material', async () => {
    const { container } = render(<AmbientWatchPanel />);
    await waitFor(() => expect(screen.getByText('monitor.front.private')).toBeTruthy());
    expect(screen.getByText(/3 \/ 4 left/i)).toBeTruthy();
    expect(screen.getByText(/last · alert → interrupt · policy selected/i)).toBeTruthy();
    expect(screen.getByText(/redacted transparency/i)).toBeTruthy();
    expect(container.textContent).not.toContain('resident.alice.private');
    expect(container.textContent).not.toContain('private-person-value');
    expect(global.fetch).toHaveBeenCalledWith('/api/ambient/monitors', expect.any(Object));
  });

  it('shows the honest default-off state', async () => {
    global.fetch = vi.fn(() => response({
      enabled: false, status: 'disabled', reason: 'ambient_disabled', monitors: [], sources: [],
      last_decision: null, rung_counts: {}, attention: { status: 'ready', limit: 4, used: 0, remaining: 4 },
    }));
    render(<AmbientWatchPanel />);
    await waitFor(() => expect(screen.getByText(/ambient intelligence is off/i)).toBeTruthy());
    expect(screen.queryByText(/global attention/i)).toBeNull();
  });
});
