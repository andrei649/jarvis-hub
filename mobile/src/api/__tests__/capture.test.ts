import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import {
  clearCapture,
  fetchCaptureExport,
  fetchCaptureRecords,
  fetchCaptureStatus,
  forgetCaptureRecord,
} from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const config = { baseUrl: 'hub.local', token: 'user-token', adminToken: 'admin-token' };

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

describe('mobile capture inbox API', () => {
  it('reads the status with the user token only — never the admin one', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: true,
      surfaces: { clipboard: true, browser: false, files: false },
      records: 3,
    }));

    await expect(fetchCaptureStatus(config)).resolves.toEqual({
      enabled: true,
      surfaces: { clipboard: true, browser: false, files: false },
      records: 3,
    });
    expect(mockFetch).toHaveBeenCalledWith(
      'http://hub.local/api/capture/status',
      expect.objectContaining({ method: 'GET' }),
    );
    // Capture is a user surface; nothing here needs or gets admin authority.
    expect(mockFetch.mock.calls[0][1]?.headers).not.toHaveProperty('X-Admin-Token');
  });

  it('keeps the master switch and the surface opt-ins separate', async () => {
    // The combination that matters: a surface opted in while capture is off.
    // The client must carry both facts through unflattened — collapsing them is
    // how a screen ends up telling someone their clipboard is being recorded.
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: false,
      surfaces: { clipboard: true, browser: true, files: false },
      records: 0,
    }));

    const status = await fetchCaptureStatus(config);
    expect(status.enabled).toBe(false);
    expect(status.surfaces.clipboard).toBe(true);
  });

  it('ignores a surface the hub invented', async () => {
    // The surface map is built from this client's own constant, so a hub that
    // grew a fourth surface cannot make the phone render a control for something
    // it does not understand.
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: true,
      surfaces: { clipboard: true, microphone: true },
      records: 1,
    }));

    const status = await fetchCaptureStatus(config);
    expect(Object.keys(status.surfaces).sort()).toEqual(['browser', 'clipboard', 'files']);
    expect((status.surfaces as Record<string, boolean>).microphone).toBeUndefined();
  });

  it('drops a record with no id rather than showing something unforgettable', async () => {
    // Every record on this screen has a delete button. One with no id could be
    // displayed but never removed — a privacy inbox that shows you something you
    // cannot erase is worse than one that shows you less.
    mockFetch.mockResolvedValueOnce(jsonResponse({
      records: [
        { id: 'a1', surface: 'clipboard', preview: 'hello', redacted: false, triples: 2, created_at: 10 },
        { surface: 'browser', preview: 'orphan' },
      ],
    }));

    const records = await fetchCaptureRecords(config);
    expect(records).toHaveLength(1);
    expect(records[0]).toEqual({
      id: 'a1',
      surface: 'clipboard',
      source: '',
      preview: 'hello',
      redacted: false,
      triples: 2,
      created_at: 10,
    });
  });

  it('passes a surface filter through as a query, url-encoded', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ records: [] }));
    await fetchCaptureRecords(config, 'browser');
    expect(mockFetch.mock.calls[0][0]).toBe('http://hub.local/api/capture?surface=browser');
  });

  it('forgets one record without retrying it', async () => {
    // A DELETE that timed out may well have landed; re-sending it would report
    // "not found" for work that actually succeeded.
    mockFetch.mockResolvedValueOnce(jsonResponse({ forgotten: true }));
    await expect(forgetCaptureRecord(config, 'a1')).resolves.toEqual({ forgotten: true });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch.mock.calls[0][0]).toBe('http://hub.local/api/capture/a1');
    expect(mockFetch.mock.calls[0][1]?.method).toBe('DELETE');
  });

  it('reports a failed forget as false rather than throwing it away', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ forgotten: false }));
    await expect(forgetCaptureRecord(config, 'gone')).resolves.toEqual({ forgotten: false });
  });

  it('clears the inbox, and does not retry that either', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ removed: 7 }));
    await expect(clearCapture(config)).resolves.toEqual({ removed: 7 });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch.mock.calls[0][1]?.method).toBe('POST');
  });

  it('exports the envelope, keeping the scope it was filtered by', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      version: 1,
      exported_at: 1_757_217_600,
      surface: 'clipboard',
      count: 1,
      surfaces: { clipboard: true, browser: false, files: false },
      records: [{ id: 'a1', surface: 'clipboard', preview: '[REDACTED]', redacted: true, created_at: 5 }],
    }));

    const envelope = await fetchCaptureExport(config, 'clipboard');
    expect(mockFetch.mock.calls[0][0]).toBe('http://hub.local/api/capture/export?surface=clipboard');
    expect(envelope.version).toBe(1);
    expect(envelope.surface).toBe('clipboard');
    expect(envelope.count).toBe(1);
    expect(envelope.records[0].redacted).toBe(true);
  });

  it('reports a missing export timestamp as null, never as zero', async () => {
    // `exportStamp` turns null into "unstamped"; a coerced 0 would name the file
    // 19700101-000000Z, which is a lie a file browser will happily sort by.
    mockFetch.mockResolvedValueOnce(jsonResponse({ version: 1, count: 0, records: [] }));
    const envelope = await fetchCaptureExport(config);
    expect(envelope.exported_at).toBeNull();
    expect(envelope.surface).toBeNull();
    expect(envelope.records).toEqual([]);
  });
});
