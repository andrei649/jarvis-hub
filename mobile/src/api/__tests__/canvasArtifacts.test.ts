import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import {
  CANVAS_MARKDOWN_LIMIT,
  deleteCanvasArtifact,
  fetchCanvasArtifacts,
  pinCanvasArtifact,
  saveCanvasArtifact,
} from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

const config = { baseUrl: '192.168.1.20:8080/', token: 'user-token', adminToken: '' };

describe('mobile canvas artifacts API (H18.20)', () => {
  it('fetches the governed canvas with user auth and normalizes elements', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        elements: [
          {
            id: 'e1',
            agent: 'jarvis',
            type: 'markdown',
            payload: { title: 'Saved response', body: 'hello' },
            pinned: true,
            created_at: 1770000000,
          },
        ],
      }),
    );

    const out = await fetchCanvasArtifacts(config);

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/api/canvas',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ 'X-User-Token': 'user-token' }),
      }),
    );
    expect(out.elements).toHaveLength(1);
    expect(out.elements[0]).toMatchObject({ id: 'e1', agent: 'jarvis', type: 'markdown', pinned: true });
  });

  it('normalizes a sparse canvas payload to an empty list', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ elements: 'bad' }));
    await expect(fetchCanvasArtifacts(config)).resolves.toEqual({ elements: [] });
  });

  it('saves a reply with the exact governed markdown contract', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ id: 'new1', agent: 'vision', type: 'markdown' }));

    const out = await saveCanvasArtifact(config, { agent: 'vision', body: 'the completed answer' });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/api/canvas/post',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          agent: 'vision',
          type: 'markdown',
          payload: { title: 'Saved response', body: 'the completed answer' },
          pinned: false,
        }),
      }),
    );
    expect(out.truncated).toBe(false);
    expect(out.element).toMatchObject({ id: 'new1' });
  });

  it('truncates long replies at the canvas bound on a code-point boundary', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ id: 'new2' }));
    // an emoji straddling the limit: a naive .slice() would send a lone surrogate
    const long = 'x'.repeat(CANVAS_MARKDOWN_LIMIT - 1) + '😀' + 'y'.repeat(40);

    const out = await saveCanvasArtifact(config, { agent: 'jarvis', body: long });

    expect(out.truncated).toBe(true);
    const sent = JSON.parse(String((mockFetch.mock.calls[0][1] as RequestInit).body));
    const cps = Array.from(sent.payload.body as string);
    expect(CANVAS_MARKDOWN_LIMIT).toBe(4000);
    expect(cps).toHaveLength(CANVAS_MARKDOWN_LIMIT);
    expect(cps[cps.length - 1]).toBe('😀');
  });

  it('pins and unpins through the existing endpoint', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ id: 'e 1', pinned: true }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ id: 'e 1', pinned: false }));

    await pinCanvasArtifact(config, 'e 1', true);
    await pinCanvasArtifact(config, 'e 1', false);

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      'http://192.168.1.20:8080/api/canvas/e%201/pin?pinned=true',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      'http://192.168.1.20:8080/api/canvas/e%201/pin?pinned=false',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('deletes through the existing endpoint', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ removed: true }));

    const out = await deleteCanvasArtifact(config, 'e1');

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/api/canvas/e1',
      expect.objectContaining({ method: 'DELETE' }),
    );
    expect(out.removed).toBe(true);
  });
});
