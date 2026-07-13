import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchAmbientMonitors } from '../client';
import type { ServerConfig } from '../../storage/settings';

const config: ServerConfig = { baseUrl: 'http://hub.local', token: 'user-token', adminToken: '' };
const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
(globalThis as any).fetch = mockFetch;
const jsonResponse = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response;

beforeEach(() => {
  mockFetch.mockReset();
});

describe('mobile Ambient Watch API', () => {
  it('keeps only the bounded redacted projection', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: true, status: 'live', reason: '',
      monitors: [{
        monitor_id: 'monitor.front.private', version: 2, source: 'camera', schema: 'camera.event.v1',
        enabled: true, alert_rung: 'interrupt', recovery_rung: 'monitor', state: 'alert', last_event_at: 1001,
        last_decision: { monitor_id: 'monitor.front.private', transition: 'alert', rung: 'interrupt', attention_mode: 'interrupt', policy_reason: 'policy_selected', decided_at: 1001 },
        subject_id: 'resident.alice.private', predicates: [{ expected: 'private-value' }],
      }],
      sources: [{ source: 'camera', status: 'live', last_event_at: 1001, reason: '', queued: 0, critical_backpressure: 0 }],
      last_decision: { monitor_id: 'monitor.front.private', transition: 'alert', rung: 'interrupt', attention_mode: 'interrupt', policy_reason: 'policy_selected', decided_at: 1001 },
      rung_counts: { interrupt: 1 }, decision_samples: 1,
      attention: { status: 'ready', reason: '', limit: 4, used: 1, remaining: 3, window_id: 'private-window' },
    }));

    const result = await fetchAmbientMonitors(config);

    expect(result.monitors).toHaveLength(1);
    expect(result.monitors[0].last_decision?.rung).toBe('interrupt');
    expect(result.rung_counts).toEqual({ ignore: 0, remember: 0, monitor: 0, act_silently: 0, ask: 0, interrupt: 1 });
    expect(result.attention).toEqual({ status: 'ready', reason: '', limit: 4, used: 1, remaining: 3 });
    expect(JSON.stringify(result)).not.toMatch(/resident\.alice|private-value|predicates|subject_id|window_id/);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://hub.local/api/ambient/monitors',
      expect.objectContaining({ method: 'GET', headers: expect.objectContaining({ 'X-User-Token': 'user-token' }) }),
    );
  });

  it('represents default-off honestly', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ enabled: false, status: 'disabled', reason: 'ambient_disabled' }));
    await expect(fetchAmbientMonitors(config)).resolves.toMatchObject({
      enabled: false, status: 'disabled', reason: 'ambient_disabled', monitors: [], sources: [],
    });
  });
});
