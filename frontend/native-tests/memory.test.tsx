import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { AppearanceProvider } from '../../mobile/src/context/AppearanceContext';
import { MemoryScreen } from '../../mobile/src/screens/MemoryScreen';
import { records } from './support/storage';

const base = { baseUrl: 'https://one.test', token: 'user-one', adminToken: 'admin-secret' };
const reply = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null }, text: async () => JSON.stringify(body), json: async () => body });
const deferred = () => { let resolve!: (value: any) => void; const promise = new Promise<any>(r => { resolve = r; }); return { promise, resolve }; };
let server: ReturnType<typeof useServer>;
function Harness() { server = useServer(); return <MemoryScreen onGoToSettings={() => {}} />; }
const mount = () => render(<ServerProvider><AppearanceProvider><Harness /></AppearanceProvider></ServerProvider>);
const clickGraph = async () => { fireEvent.click(await screen.findByText('Graph')); await waitFor(() => expect(screen.getByText('Entities')).toBeTruthy()); };
const fixture = (url: string) => {
  if (url.endsWith('/memory')) return reply({ turns: [] });
  if (url.endsWith('/api/notes')) return reply({ content: '' });
  if (url.includes('/api/kg/entities?')) return reply({ entities: [{ name: 'A', type: 'person' }], total: 1 });
  if (url.endsWith('/api/kg/entities/A')) return reply({ entity: { name: 'A', type: 'person' }, relations: [
    { source: 'A', relation: 'knows', target: 'B' }, { source: 'A', relation: 'knows', target: 'B' },
    { source: 'A', relation: 'self', target: 'A' },
  ] });
  if (url.endsWith('/api/kg/entities/B')) return reply({ entity: { name: 'B', type: 'person' }, relations: [] });
  if (url.endsWith('/api/kg/facts/as-of')) return reply({ facts: [] });
  if (url.includes('/api/kg/facts/history')) return reply({ subject: new URL(url).searchParams.get('subject'), history: [] });
  return reply({});
};
beforeEach(() => { records.clear(); records.set('jarvis.server.config.v1', JSON.stringify(base)); global.fetch = vi.fn((url: string) => Promise.resolve(fixture(String(url)))) as any; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('opens a connected entity outside the first entity page once despite duplicate and self relations', async () => {
  mount(); await clickGraph();
  await waitFor(() => expect(screen.getByText('Connected entities')).toBeTruthy());
  expect(screen.getAllByText('B')).toHaveLength(1);
  fireEvent.click(screen.getByText('B'));
  await waitFor(() => expect(screen.getByText('No relations returned for this entity.')).toBeTruthy());
  expect((fetch as any).mock.calls.some(([url]: any[]) => String(url).endsWith('/api/kg/entities/B'))).toBe(true);
});

it('keeps independent detail and history failures visible instead of claiming empty results', async () => {
  global.fetch = vi.fn((url: string) => Promise.resolve(
    String(url).endsWith('/api/kg/entities/A') ? reply({ error: 'graph not available' }, 503)
      : String(url).includes('/api/kg/facts/history') ? reply({ error: 'bi-temporal KG not available' }, 503)
      : fixture(String(url)),
  )) as any;
  mount(); await clickGraph();
  await waitFor(() => expect(screen.getByText(/Connections unavailable/)).toBeTruthy());
  expect(screen.getByText(/History unavailable/)).toBeTruthy();
  expect(screen.queryByText('No relations returned for this entity.')).toBeNull();
  expect(screen.queryByText('No fact history returned for this subject.')).toBeNull();
});

it('still shows valid history when connections fail', async () => {
  global.fetch = vi.fn((url: string) => Promise.resolve(
    String(url).endsWith('/api/kg/entities/A') ? reply({}, 503)
      : String(url).includes('/api/kg/facts/history') ? reply({ subject: 'A', history: [{ subject: 'A', predicate: 'knows', object: 'B' }] })
      : fixture(String(url)),
  )) as any;
  mount(); await clickGraph();
  await waitFor(() => expect(screen.getByText(/Connections unavailable/)).toBeTruthy());
  expect(screen.getByText('A · knows · B')).toBeTruthy();
  expect(screen.queryByText('No fact history returned for this subject.')).toBeNull();
});

it('still shows connections when history fails', async () => {
  global.fetch = vi.fn((url: string) => Promise.resolve(
    String(url).includes('/api/kg/facts/history') ? reply({}, 503) : fixture(String(url)),
  )) as any;
  mount(); await clickGraph();
  await waitFor(() => expect(screen.getByText(/History unavailable/)).toBeTruthy());
  expect(screen.getByText('Connected entities')).toBeTruthy();
  expect(screen.queryByText('No relations returned for this entity.')).toBeNull();
});

it('ignores old detail and history bodies after selecting a connected entity', async () => {
  const oldDetail = deferred(); const oldHistory = deferred();
  let aLoads = 0;
  global.fetch = vi.fn((url: string) => {
    const path = String(url);
    if (path.includes('/api/kg/entities?')) return Promise.resolve(reply({ entities: [{ name: 'A', type: 'person' }, { name: 'B', type: 'person' }], total: 2 }));
    if (path.endsWith('/api/kg/entities/A') && ++aLoads > 1) return oldDetail.promise;
    if (path.includes('history?subject=A') && aLoads > 1) return oldHistory.promise;
    return Promise.resolve(fixture(path));
  }) as any;
  mount(); await clickGraph(); await waitFor(() => expect(screen.getByText('Connected entities')).toBeTruthy());
  fireEvent.click(screen.getAllByText('A')[0]);
  await waitFor(() => expect(aLoads).toBe(2));
  fireEvent.click(screen.getByText('B'));
  await waitFor(() => expect(screen.getByText('No relations returned for this entity.')).toBeTruthy());
  await act(async () => { oldDetail.resolve(reply({ entity: { name: 'A', type: 'person' }, relations: [] })); oldHistory.resolve(reply({ history: [{ subject: 'A', predicate: 'old', object: 'stale' }] })); });
  expect(screen.queryByText('stale')).toBeNull();
  expect(screen.getAllByText('B').length).toBeGreaterThan(0);
});

it('cancels graph reads on search, mode switch, connection change, and unmount', async () => {
  const blocked: AbortSignal[] = [];
  global.fetch = vi.fn((url: string, init: RequestInit) => {
    const path = String(url);
    if (path.includes('/api/kg/entities?')) { blocked.push(init.signal!); return new Promise(() => {}); }
    return Promise.resolve(fixture(path));
  }) as any;
  const view = mount(); await clickGraph(); await waitFor(() => expect(blocked).toHaveLength(1));
  fireEvent.change(screen.getByPlaceholderText('Search graph'), { target: { value: 'next' } });
  fireEvent.click(screen.getByText('Search'));
  await waitFor(() => expect(blocked).toHaveLength(2)); expect(blocked[0].aborted).toBe(true);
  fireEvent.click(screen.getByText('Turns')); expect(blocked[1].aborted).toBe(true);
  fireEvent.click(screen.getByText('Graph')); await waitFor(() => expect(blocked).toHaveLength(3));
  await act(async () => server.updateConfig({ ...base, baseUrl: 'https://two.test', token: 'user-two' }));
  await waitFor(() => expect(blocked).toHaveLength(4)); expect(blocked[2].aborted).toBe(true);
  view.unmount(); expect(blocked[3].aborted).toBe(true);
});

it('ignores a search response delivered after its cancellation', async () => {
  const oldSearch = deferred();
  global.fetch = vi.fn((url: string) => {
    const path = String(url);
    if (path.includes('/api/kg/entities?') && !path.includes('q=next')) return oldSearch.promise;
    if (path.includes('q=next')) return Promise.resolve(reply({ entities: [{ name: 'New', type: 'person' }], total: 1 }));
    if (path.endsWith('/api/kg/entities/New')) return Promise.resolve(reply({ entity: { name: 'New', type: 'person' }, relations: [] }));
    return Promise.resolve(fixture(path));
  }) as any;
  mount(); await clickGraph();
  fireEvent.change(screen.getByPlaceholderText('Search graph'), { target: { value: 'next' } });
  fireEvent.click(screen.getByText('Search'));
  await waitFor(() => expect(screen.getAllByText('New').length).toBeGreaterThan(0));
  await act(async () => oldSearch.resolve(reply({ entities: [{ name: 'Old', type: 'person' }], total: 1 })));
  expect(screen.queryByText('Old')).toBeNull();
  expect(screen.getAllByText('New').length).toBeGreaterThan(0);
});

it('keeps the list and current facts unavailable states separate from empty data', async () => {
  global.fetch = vi.fn((url: string) => Promise.resolve(
    String(url).includes('/api/kg/entities?') ? reply({ entities: [], error: 'graph not available' })
      : String(url).endsWith('/api/kg/facts/as-of') ? reply({ error: 'bi-temporal KG not available' }, 503)
      : fixture(String(url)),
  )) as any;
  mount(); await clickGraph();
  await waitFor(() => expect(screen.getByText('graph not available')).toBeTruthy());
  expect(screen.getByText(/Current facts unavailable/)).toBeTruthy();
  expect(screen.queryByText('No graph entities')).toBeNull();
  expect(screen.queryByText('No current facts returned by the hub.')).toBeNull();
});

it('clears old hub detail immediately and ignores its late body after reconfiguration', async () => {
  const oldDetail = deferred();
  let aLoads = 0;
  global.fetch = vi.fn((url: string) => {
    const path = String(url);
    if (path.startsWith('https://one.test') && path.endsWith('/api/kg/entities/A') && ++aLoads > 1) return oldDetail.promise;
    if (path.startsWith('https://two.test') && path.includes('/api/kg/entities?')) return Promise.resolve(reply({ entities: [{ name: 'New', type: 'person' }], total: 1 }));
    if (path.startsWith('https://two.test') && path.endsWith('/api/kg/entities/New')) return Promise.resolve(reply({ entity: { name: 'New', type: 'person' }, relations: [] }));
    return Promise.resolve(fixture(path));
  }) as any;
  mount(); await clickGraph(); await waitFor(() => expect(screen.getByText('Connected entities')).toBeTruthy());
  fireEvent.click(screen.getAllByText('A')[0]);
  await waitFor(() => expect(aLoads).toBe(2));
  await act(async () => server.updateConfig({ ...base, baseUrl: 'https://two.test', token: 'user-two' }));
  expect(screen.queryByText('Connected entities')).toBeNull();
  await waitFor(() => expect(screen.getAllByText('New').length).toBeGreaterThan(0));
  await act(async () => oldDetail.resolve(reply({ entity: { name: 'A', type: 'person' }, relations: [{ source: 'A', relation: 'old', target: 'Stale' }] })));
  expect(screen.queryByText('Stale')).toBeNull();
  expect(screen.getAllByText('New').length).toBeGreaterThan(0);
});

it('ignores a graph body delivered after leaving Graph mode', async () => {
  const oldList = deferred();
  let listLoads = 0;
  global.fetch = vi.fn((url: string) => {
    const path = String(url);
    if (path.includes('/api/kg/entities?')) {
      listLoads += 1;
      return listLoads === 1 ? oldList.promise : Promise.resolve(reply({ entities: [{ name: 'New', type: 'person' }], total: 1 }));
    }
    if (path.endsWith('/api/kg/entities/New')) return Promise.resolve(reply({ entity: { name: 'New', type: 'person' }, relations: [] }));
    return Promise.resolve(fixture(path));
  }) as any;
  mount(); await clickGraph(); await waitFor(() => expect(listLoads).toBe(1));
  fireEvent.click(screen.getByText('Turns'));
  await act(async () => oldList.resolve(reply({ entities: [{ name: 'Old', type: 'person' }], total: 1 })));
  fireEvent.click(screen.getByText('Graph'));
  await waitFor(() => expect(screen.getAllByText('New').length).toBeGreaterThan(0));
  expect(screen.queryByText('Old')).toBeNull();
});
