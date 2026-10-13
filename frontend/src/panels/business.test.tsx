import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BusinessPanel } from './business';

const catalog = {
  enabled: true,
  templates: [{ id: 'ecommerce', name: 'Comerț online', description: 'Comenzi și stoc', departments: ['Vânzări', 'Operațiuni'] }],
  connectors: [{ id: 'woocommerce', name: 'WooCommerce', description: 'Magazin', category: 'commerce', auth_fields: [{ key: 'consumer_key', label: 'Consumer key', secret: true }, { key: 'consumer_secret', label: 'Consumer secret', secret: true }], base_url_required: true }],
  workflows: [{ id: 'sales_overview', name: 'Sales overview', description: 'Paid sales by currency', requires: 'orders' }],
};
const initial = {
  enabled: true,
  workspace: { name: 'Atelier SRL', industry: 'ecommerce', currency: 'RON', local_only: true },
  connections: [], reports: [], activity: [],
};
const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
const refused = (status: number, detail: string) => ({ ok: false, status, json: async () => ({ detail }) });

function mockApi(workspace = initial, responses: Record<string, unknown> = {}) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url);
    const method = init?.method || 'GET';
    if (method === 'GET' && path.includes('/api/business/catalog')) return ok(catalog);
    if (method === 'GET' && path.includes('/api/business/workspace')) return ok(workspace);
    const key = `${method} ${path.slice(path.indexOf('/api/business/'))}`;
    return responses[key] || refused(500, `Unexpected ${key}`);
  });
  global.fetch = fn as typeof fetch;
  return fn;
}

beforeEach(() => { localStorage.clear(); });

describe('BusinessPanel', () => {
  it('shows the saved workspace and honest empty data state', async () => {
    mockApi();
    render(<BusinessPanel />);
    expect(await screen.findByText('Atelier SRL')).toBeTruthy();
    expect(screen.getByText(/Nu există surse de date/)).toBeTruthy();
    expect(screen.getByText(/Niciun raport rulat/)).toBeTruthy();
  });

  it('keeps the model routing label on the saved policy while the form has unsaved changes', async () => {
    mockApi();
    render(<BusinessPanel />);
    await screen.findByText('Atelier SRL');
    fireEvent.click(screen.getByLabelText('Folosește doar modele AI locale pentru întrebările Business'));
    expect(screen.getByText(/Răspunsuri AI doar locale/)).toBeTruthy();
    expect(screen.queryByText(/Rutare AI conform setărilor Nerva/)).toBeNull();
  });

  it('shows the operator switch when business is disabled without mutation controls', async () => {
    mockApi({ ...initial, enabled: false });
    render(<BusinessPanel />);
    expect(await screen.findByText(/Spațiul Business este dezactivat/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Salvează profilul' })).toBeNull();
  });

  it('sends the edited profile as an admin mutation and renders returned state', async () => {
    const fetcher = mockApi(initial, { 'PUT /api/business/workspace': ok({ ...initial, workspace: { ...initial.workspace, name: 'Magazin Nou', local_only: false } }) });
    localStorage.setItem('hud.admin_token', 'admin-test-token');
    render(<BusinessPanel />);
    await screen.findByText('Atelier SRL');
    fireEvent.change(screen.getByLabelText('Numele companiei'), { target: { value: 'Magazin Nou' } });
    fireEvent.click(screen.getByLabelText('Folosește doar modele AI locale pentru întrebările Business'));
    fireEvent.click(screen.getByRole('button', { name: 'Salvează profilul' }));
    await waitFor(() => expect(screen.getByText('Magazin Nou')).toBeTruthy());
    expect(screen.getByText(/Rutare AI conform setărilor Nerva/)).toBeTruthy();
    const call = fetcher.mock.calls.find(([url, init]) => String(url).includes('/api/business/workspace') && init?.method === 'PUT');
    expect(JSON.parse(call![1]!.body as string)).toMatchObject({ name: 'Magazin Nou', industry: 'ecommerce', currency: 'RON', local_only: false });
    expect((call![1]!.headers as Record<string, string>)['X-Admin-Token']).toBe('admin-test-token');
  });

  it('imports actual CSV text, and does not report success on refusal', async () => {
    const fetcher = mockApi(initial, { 'POST /api/business/import': refused(422, 'Coloana total lipsește') });
    render(<BusinessPanel />);
    await screen.findByText('Atelier SRL');
    fireEvent.change(screen.getByLabelText('Numele sursei CSV'), { target: { value: 'Octombrie' } });
    fireEvent.change(screen.getByLabelText('Conținut CSV'), { target: { value: 'id,status\n1,paid' } });
    fireEvent.click(screen.getByRole('button', { name: 'Importă CSV' }));
    expect(await screen.findByText(/Coloana total lipsește/)).toBeTruthy();
    expect(screen.queryByText(/Import finalizat/)).toBeNull();
    const call = fetcher.mock.calls.find(([url, init]) => String(url).includes('/api/business/import') && init?.method === 'POST');
    expect(JSON.parse(call![1]!.body as string)).toEqual({ name: 'Octombrie', kind: 'orders', csv_text: 'id,status\n1,paid' });
  });

  it('saves encrypted-service credentials as pending, then shows the sync result', async () => {
    const pending = { id: 'c1', provider: 'woocommerce', name: 'Magazin principal', base_url: 'https://shop.example', status: 'pending', last_sync_at: null, error: null, record_count: null };
    const synced = { ...pending, status: 'connected', last_sync_at: '2026-10-13T10:00:00Z', record_count: 4 };
    const fetcher = mockApi(initial, {
      'POST /api/business/connections': ok({ connection: pending }),
      'POST /api/business/connections/c1/sync': ok({ connection: synced }),
    });
    render(<BusinessPanel />);
    await screen.findByText('Atelier SRL');
    fireEvent.change(screen.getByLabelText('Numele conexiunii'), { target: { value: 'Magazin principal' } });
    fireEvent.change(screen.getByLabelText('Adresa HTTPS a serviciului'), { target: { value: 'https://shop.example' } });
    fireEvent.change(screen.getByLabelText('Cheie consumator'), { target: { value: 'key-value' } });
    fireEvent.change(screen.getByLabelText('Secret consumator'), { target: { value: 'secret-value' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salvează conexiunea' }));
    expect(await screen.findByText('Neconfirmat')).toBeTruthy();
    expect(screen.queryByText('Conectat')).toBeNull();
    const create = fetcher.mock.calls.find(([url, init]) => String(url).endsWith('/api/business/connections') && init?.method === 'POST');
    expect(JSON.parse(create![1]!.body as string).credentials).toEqual({ consumer_key: 'key-value', consumer_secret: 'secret-value' });
    fireEvent.click(screen.getByRole('button', { name: 'Sincronizează' }));
    expect(await screen.findByText('Conectat')).toBeTruthy();
    expect(screen.getByText('Înregistrări: 4')).toBeTruthy();
  });

  it('does not remove a connection when the server refuses deletion', async () => {
    const connection = { id: 'c1', provider: 'woocommerce', name: 'Magazin principal', base_url: 'https://shop.example', status: 'error', last_sync_at: null, error: 'Cheie expirată', record_count: null };
    mockApi({ ...initial, connections: [connection] }, { 'DELETE /api/business/connections/c1': refused(403, 'Necesită acces admin') });
    render(<BusinessPanel />);
    await screen.findByText('Magazin principal');
    fireEvent.click(screen.getByRole('button', { name: 'Elimină' }));
    expect(await screen.findByText('Necesită acces admin')).toBeTruthy();
    expect(screen.getByText('Magazin principal')).toBeTruthy();
  });

  it('adds an imported CSV source only when the backend confirms it', async () => {
    const csv = { id: 'csv1', provider: 'csv', name: 'Octombrie', base_url: '', status: 'connected', last_sync_at: '2026-10-13T10:00:00Z', error: null, record_count: 1 };
    mockApi(initial, { 'POST /api/business/import': ok({ connection: csv }) });
    render(<BusinessPanel />);
    await screen.findByText('Atelier SRL');
    fireEvent.change(screen.getByLabelText('Numele sursei CSV'), { target: { value: 'Octombrie' } });
    fireEvent.change(screen.getByLabelText('Conținut CSV'), { target: { value: 'id,status,total,currency,created_at\n1,completed,20.00,RON,2026-10-13' } });
    fireEvent.click(screen.getByRole('button', { name: 'Importă CSV' }));
    expect(await screen.findByText('Import finalizat. Datele din CSV sunt disponibile pentru rapoarte.')).toBeTruthy();
    expect(screen.getByText('Octombrie')).toBeTruthy();
    expect(screen.getByText('Înregistrări: 1')).toBeTruthy();
  });

  it('surfaces the real structured backend refusal message', async () => {
    mockApi(initial, { 'POST /api/business/import': { ok: false, status: 422, json: async () => ({ error: { code: 'bad_csv', message: 'CSV-ul are antet invalid.' } }) } });
    render(<BusinessPanel />);
    await screen.findByText('Atelier SRL');
    fireEvent.change(screen.getByLabelText('Numele sursei CSV'), { target: { value: 'Octombrie' } });
    fireEvent.change(screen.getByLabelText('Conținut CSV'), { target: { value: 'id\n1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Importă CSV' }));
    expect(await screen.findByText('CSV-ul are antet invalid.')).toBeTruthy();
    expect(screen.queryByText(/Import finalizat/)).toBeNull();
  });

  it('shows only a server-produced report and its coverage', async () => {
    const report = { id: 'r1', workflow_id: 'sales_overview', title: 'Vânzări reale', summary: '2 comenzi plătite', metrics: { paid_orders: 2 }, rows: [], coverage: [{ source: 'CSV Octombrie', synced_at: '2026-10-13T09:00:00Z', description: 'import CSV', complete: false }], warnings: ['Date parțiale'], created_at: '2026-10-13T10:00:00Z' };
    mockApi(initial, { 'POST /api/business/reports/sales_overview/run': ok({ report }) });
    render(<BusinessPanel />);
    await screen.findByText('Atelier SRL');
    fireEvent.click(screen.getByRole('button', { name: 'Rulează Vânzări' }));
    expect(await screen.findByText('2 comenzi plătite')).toBeTruthy();
    expect(screen.getByText('Date parțiale')).toBeTruthy();
    expect(screen.getByText('CSV Octombrie').closest('li')?.textContent).toMatch(/parțială.*import CSV/);
  });

  it('keeps an unanswered question distinct from a failed model call', async () => {
    mockApi(initial, { 'POST /api/business/ask': refused(503, 'Modelul local nu este disponibil') });
    render(<BusinessPanel />);
    await screen.findByText('Atelier SRL');
    fireEvent.change(screen.getByLabelText('Întrebare despre date'), { target: { value: 'Cum merg vânzările?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Întreabă Nerva' }));
    expect(await screen.findByText(/Modelul local nu este disponibil/)).toBeTruthy();
    expect(screen.queryByText(/Răspuns Nerva/)).toBeNull();
  });
});
