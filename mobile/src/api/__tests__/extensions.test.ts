import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { ApiError } from '../client';
import {
  EXTENSIONS_INSPECTION_PATH,
  fetchExtensionInspection,
  normalizeExtensionInspection,
} from '../extensions';
import type { ServerConfig } from '../../storage/settings';

const config: ServerConfig = {
  baseUrl: '  https://hub.local///  ',
  token: '  user-token  ',
  adminToken: 'admin-token-must-not-be-sent',
};

const activeRow = {
  id: 'boats', version: '1.0.0', reason: 'activated',
  signature_verified: true, approval_verified: false, quarantine_state: 'not_inspected',
  execution_available: true,
  declared_tools: ['boats.summarize'], callable_tools: ['boats.summarize'],
  declared_commands: ['boat_report'], callable_commands: ['boat_report'],
  command_requires_args: ['boat_report'], declared_events: ['session.started'],
  capabilities: ['tools', 'commands', 'events.observe'],
};
const validReport = { mode: 'inspection_only', reason: 'activated', extensions: [activeRow] };

function response(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

describe('mobile read-only extension inspection API', () => {
  it('uses one user-authenticated GET and keeps trust and callability independent', async () => {
    mockFetch.mockResolvedValueOnce(response(validReport));
    const abort = new AbortController();
    const report = await fetchExtensionInspection(config, abort.signal);

    expect(report).toEqual({ mode: 'inspection_only', reason: 'activated', extensions: [{
      id: 'boats', version: '1.0.0', reason: 'activated', signatureVerified: true,
      approvalVerified: false, quarantineState: 'not_inspected', executionAvailable: true,
      declaredTools: ['boats.summarize'], callableTools: ['boats.summarize'],
      declaredCommands: ['boat_report'], callableCommands: ['boat_report'],
      commandRequiresArgs: ['boat_report'], declaredEvents: ['session.started'],
      capabilities: ['tools', 'commands', 'events.observe'],
    }] });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`https://hub.local${EXTENSIONS_INSPECTION_PATH}`);
    expect(init.method).toBe('GET');
    expect(init.body).toBeUndefined();
    expect(init.cache).toBe('no-store');
    expect(init.headers).toEqual({ Accept: 'application/json', 'X-User-Token': 'user-token' });
    expect(init.signal).toBeDefined();
    expect(init.signal).not.toBe(abort.signal);
  });

  it('does not infer callable declarations from signature or approval facts', () => {
    const row = {
      ...activeRow, approval_verified: false,
      declared_tools: ['boats.summarize'], callable_tools: [],
      declared_commands: ['boat_report'], callable_commands: [],
    };
    const result = normalizeExtensionInspection({ ...validReport, extensions: [row] });
    expect(result.extensions[0]).toMatchObject({
      signatureVerified: true, approvalVerified: false,
      declaredTools: ['boats.summarize'], callableTools: [],
      declaredCommands: ['boat_report'], callableCommands: [],
    });
  });

  it('accepts exactly 64 declarations and 128 extensions, rejecting one over either bound', () => {
    const longId = `a${'b'.repeat(63)}`;
    const tools = Array.from({ length: 64 }, (_unused, index) => `${longId}.tool_${index}`);
    const commands = Array.from({ length: 64 }, (_unused, index) => `cmd_${index}`);
    const boundedRow = {
      ...activeRow, id: longId, declared_tools: tools, callable_tools: tools,
      declared_commands: commands, callable_commands: commands,
      command_requires_args: commands,
    };
    expect(normalizeExtensionInspection({ ...validReport, extensions: [boundedRow] }).extensions[0].id)
      .toBe(longId);
    expect(() => normalizeExtensionInspection({ ...validReport, extensions: [{
      ...boundedRow, declared_tools: [...tools, `${longId}.extra`],
    }] })).toThrow('Invalid extension inspection');

    const rows = Array.from({ length: 128 }, (_unused, index) => ({
      id: `ext_${index}`, version: '1.0.0', reason: 'acquired_inactive',
      signature_verified: false, approval_verified: false, quarantine_state: 'not_inspected',
      execution_available: false, declared_tools: [], callable_tools: [],
      declared_commands: [], callable_commands: [], command_requires_args: [],
      declared_events: [], capabilities: [],
    }));
    expect(normalizeExtensionInspection({ ...validReport, extensions: rows }).extensions).toHaveLength(128);
    expect(() => normalizeExtensionInspection({ ...validReport, extensions: [...rows, rows[0]] }))
      .toThrow('Invalid extension inspection');
  });

  it('rejects callables outside declarations and invalid canonical names', () => {
    expect(() => normalizeExtensionInspection({ ...validReport, extensions: [{
      ...activeRow, callable_commands: ['delete_everything'],
    }] })).toThrow('Invalid extension inspection');
    expect(() => normalizeExtensionInspection({ ...validReport, extensions: [{
      ...activeRow, id: 'not-canonical',
    }] })).toThrow('Invalid extension inspection');
  });

  it('does not read or expose an error response body', async () => {
    const json = jest.fn(async () => ({ detail: 'private response body' }));
    mockFetch.mockResolvedValueOnce({ ok: false, status: 403, json } as unknown as Response);
    await expect(fetchExtensionInspection(config, new AbortController().signal)).rejects.toMatchObject({
      name: 'ApiError', status: 403, message: 'Extension inspection unavailable',
    });
    expect(json).not.toHaveBeenCalled();
  });

  it('fences a response after the disclosure aborts its request', async () => {
    let finish!: (value: Response) => void;
    mockFetch.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }) as Promise<Response>);
    const abort = new AbortController();
    const request = fetchExtensionInspection(config, abort.signal);
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    abort.abort();
    finish(response(validReport));
    await expect(request).rejects.toMatchObject({ name: 'ApiError' });
    expect(init.signal?.aborted).toBe(true);
  });

  it('maps malformed responses to a fixed validation error', async () => {
    mockFetch.mockResolvedValueOnce(response({ detail: 'private source path' }));
    await expect(fetchExtensionInspection(config, new AbortController().signal))
      .rejects.toMatchObject({ message: 'Invalid extension inspection' });
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
