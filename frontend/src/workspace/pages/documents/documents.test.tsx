import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { WorkspaceDocument } from '../../api/types';
import { renderApp } from '../../test/render';
import { apiError, json, makeUser, mockFetch, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';
import { installFakeXhr } from '../../test/streams';

const NOW = Date.now() / 1000;

function doc(over: Partial<WorkspaceDocument> = {}): WorkspaceDocument {
  return {
    id: 5, title: 'Contract cadru', filename: 'contract-cadru.pdf', mime: 'application/pdf', size_bytes: 248_000,
    department_id: 1, visibility: 'department', status: 'ready', error: null, page_count: 12, chunk_count: 40,
    uploader: { id: 1, name: 'Ana Pop' }, created_at: NOW - 3600, can_delete: true, can_reindex: true, can_publish: true, ...over,
  };
}

function boot(path: string, routes: Record<string, RouteHandler> = {}, role: 'admin' | 'member' = 'admin') {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser({ role })),
    ...shellRoutes(),
    'GET /api/workspace/documents': { documents: [doc()] },
    ...routes,
  });
  renderApp(path);
  return mock;
}

function fileInput(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error('no file input');
  return input;
}

describe('Documents → upload', () => {
  it('uploads with real progress, then lists the document; a refused type fails without a request', async () => {
    const Xhr = installFakeXhr();
    let listed: WorkspaceDocument[] = [];
    const mock = boot('/workspace/documents', { 'GET /api/workspace/documents': () => ({ documents: listed }) });
    expect(await screen.findByText('Niciun document încă')).toBeTruthy();
    const pdf = new File(['%PDF-1.7 test'], 'Politica concedii.pdf', { type: 'application/pdf' });
    const exe = new File(['MZ'], 'setup.exe', { type: 'application/octet-stream' });
    fireEvent.change(fileInput(), { target: { files: [pdf, exe] } });

    expect(await screen.findByText('Tipul de fișier nu este acceptat.')).toBeTruthy();
    expect(Xhr.instances).toHaveLength(1);
    const xhr = Xhr.instances[0];
    expect(xhr.method).toBe('POST');
    expect(xhr.url).toBe('/api/workspace/documents?department_id=1&filename=Politica+concedii.pdf');
    expect(xhr.headers['X-CSRF-Token']).toBe('csrf-1');
    expect(xhr.headers['Content-Type']).toBe('application/pdf');
    expect(xhr.body).toBe(pdf);

    await act(async () => { xhr.progress(512, 1024); });
    expect(await screen.findByText(/Se încarcă… 50/)).toBeTruthy();
    const bar = screen.getByRole('progressbar', { name: 'Încărcarea fișierului Politica concedii.pdf' }) as HTMLProgressElement;
    expect(bar.value).toBe(50);

    listed = [doc({ id: 9, title: 'Politica concedii', filename: 'Politica concedii.pdf', chunk_count: 4 })];
    await act(async () => { xhr.respond(201, listed[0]); });
    expect(await screen.findByText('Gata · 4 fragmente indexate')).toBeTruthy();
    const table = screen.getByRole('table', { name: 'Documente' });
    expect(await within(table).findByRole('button', { name: 'Politica concedii' })).toBeTruthy();
    expect(mock.find('GET', '/api/workspace/documents').length).toBeGreaterThan(1);
    expect(screen.getByText('Politica concedii.pdf a fost încărcat și indexat.')).toBeTruthy();
  });

  it('explains a failed extraction and a server refusal, one file after the other', async () => {
    const Xhr = installFakeXhr();
    boot('/workspace/documents');
    await screen.findByRole('table', { name: 'Documente' });
    const locked = new File(['%PDF'], 'secret.pdf', { type: 'application/pdf' });
    const huge = new File(['x'], 'arhiva.csv', { type: 'text/csv' });
    fireEvent.change(fileInput(), { target: { files: [locked, huge] } });

    await waitFor(() => expect(Xhr.instances).toHaveLength(1));
    expect(screen.getByText('În așteptare')).toBeTruthy();
    await act(async () => { Xhr.instances[0].respond(201, doc({ id: 10, title: 'secret', filename: 'secret.pdf', status: 'failed', error: 'encrypted_pdf', chunk_count: 0 })); });
    expect(await screen.findByText('PDF-ul este protejat cu parolă. Salvează-l fără parolă și încarcă-l din nou.')).toBeTruthy();

    await waitFor(() => expect(Xhr.instances).toHaveLength(2));
    expect(Xhr.instances[1].url).toBe('/api/workspace/documents?department_id=1&filename=arhiva.csv');
    await act(async () => { Xhr.instances[1].respond(413, { error: 'file_too_large', message: 'too big' }); });
    expect(await screen.findByText('Fișierul depășește dimensiunea maximă permisă.')).toBeTruthy();
  });

  it('refreshes a rotated CSRF token and re-sends the file once', async () => {
    const Xhr = installFakeXhr();
    const mock = boot('/workspace/documents');
    await screen.findByRole('table', { name: 'Documente' });
    const sessionReads = mock.find('GET', '/api/workspace/session').length;
    fireEvent.change(fileInput(), { target: { files: [new File(['a'], 'note.txt', { type: 'text/plain' })] } });
    await waitFor(() => expect(Xhr.instances).toHaveLength(1));
    await act(async () => { Xhr.instances[0].respond(403, { error: 'csrf_failed', message: 'csrf' }); });
    await waitFor(() => expect(Xhr.instances).toHaveLength(2));
    expect(mock.find('GET', '/api/workspace/session').length).toBeGreaterThan(sessionReads);
    await act(async () => { Xhr.instances[1].respond(201, doc({ id: 11, title: 'note', filename: 'note.txt', chunk_count: 1 })); });
    expect(await screen.findByText('Gata · 1 fragment indexat')).toBeTruthy();
  });

  it('shows the company collection from the server and uploads to it as an admin', async () => {
    const Xhr = installFakeXhr();
    const mock = boot('/workspace/documents', { 'GET /api/workspace/documents': { documents: [doc({ id: 3, visibility: 'company', department_id: null, title: 'Regulament intern' })] } });
    fireEvent.change(await screen.findByLabelText('Documentele din'), { target: { value: 'company' } });
    await waitFor(() => expect(mock.find('GET', '/api/workspace/documents').slice(-1)[0]?.search).toBe('?department_id=company'));
    expect(await screen.findByText('Se adaugă în: Toată compania')).toBeTruthy();
    fireEvent.change(fileInput(), { target: { files: [new File(['a'], 'cod.md', { type: 'text/markdown' })] } });
    await waitFor(() => expect(Xhr.instances[0]?.url).toBe('/api/workspace/documents?department_id=company&filename=cod.md'));
  });

  it('tells a member that company-wide documents are added by administrators', async () => {
    boot('/workspace/documents', {}, 'member');
    fireEvent.change(await screen.findByLabelText('Documentele din'), { target: { value: 'company' } });
    expect(await screen.findByText(/Documentele pentru toată compania sunt adăugate de administratori/)).toBeTruthy();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });
});

describe('Documents → list and actions', () => {
  it('filters on the server by text and status', async () => {
    const mock = boot('/workspace/documents');
    await screen.findByRole('button', { name: 'Contract cadru' });
    fireEvent.change(screen.getByLabelText('Stare'), { target: { value: 'failed' } });
    await waitFor(() => expect(mock.find('GET', '/api/workspace/documents').slice(-1)[0]?.search).toBe('?department_id=1&status=failed'));
    fireEvent.change(screen.getByLabelText('Caută'), { target: { value: 'contract' } });
    await waitFor(() => expect(mock.find('GET', '/api/workspace/documents').slice(-1)[0]?.search).toBe('?department_id=1&q=contract&status=failed'));
  });

  it('deletes a document only after confirmation', async () => {
    const mock = boot('/workspace/documents', { 'DELETE /api/workspace/documents/5': json(204) });
    fireEvent.click(await screen.findByRole('button', { name: 'Acțiuni pentru „Contract cadru”' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Șterge' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Ștergi documentul?' });
    expect(within(confirm).getByText(/va fi șters definitiv/)).toBeTruthy();
    expect(mock.find('DELETE', '/api/workspace/documents/5')).toHaveLength(0);
    fireEvent.click(within(confirm).getByRole('button', { name: 'Șterge' }));
    expect(await screen.findByText('Documentul a fost șters.')).toBeTruthy();
    expect(mock.find('DELETE', '/api/workspace/documents/5')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Contract cadru' })).toBeNull();
  });

  it('keeps the document when deletion is refused, and says why', async () => {
    boot('/workspace/documents', { 'DELETE /api/workspace/documents/5': apiError(404, 'not_found') });
    fireEvent.click(await screen.findByRole('button', { name: 'Acțiuni pentru „Contract cadru”' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Șterge' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Ștergi documentul?' });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Șterge' }));
    expect(await within(confirm).findByText('Elementul nu mai există sau nu îți este disponibil.')).toBeTruthy();
  });

  it('opens the preview drawer from a link with metadata, text and the download', async () => {
    boot('/workspace/documents/5', { 'GET /api/workspace/documents/5': { ...doc(), preview: 'Art. 1 — Obiectul contractului.' } });
    const drawer = await screen.findByRole('dialog', { name: 'Contract cadru' });
    expect(await within(drawer).findByText('Art. 1 — Obiectul contractului.')).toBeTruthy();
    expect(within(drawer).getByText('contract-cadru.pdf')).toBeTruthy();
    expect(within(drawer).getByText('40 de fragmente indexate')).toBeTruthy();
    expect(within(drawer).getByRole('link', { name: 'Descarcă' }).getAttribute('href')).toBe('/api/workspace/documents/5/file');
    fireEvent.click(within(drawer).getByRole('button', { name: 'Închide' }));
    await waitFor(() => expect(window.location.pathname).toBe('/workspace/documents'));
  });

  it('re-indexes a document and reports the outcome', async () => {
    const mock = boot('/workspace/documents', { 'POST /api/workspace/documents/5/reindex': doc({ chunk_count: 41 }) });
    fireEvent.click(await screen.findByRole('button', { name: 'Acțiuni pentru „Contract cadru”' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Reindexează' }));
    expect(await screen.findByText('Documentul a fost reindexat.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/documents/5/reindex')).toHaveLength(1);
  });

  it('publishes company-wide at once for an admin and shows the result', async () => {
    const mock = boot('/workspace/documents', {
      'POST /api/workspace/approvals': json(201, { id: 40, kind: 'document.company_publish', status: 'approved', error_code: null }),
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Acțiuni pentru „Contract cadru”' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Publică în toată compania' }));
    const dialog = await screen.findByRole('dialog', { name: 'Publici documentul în toată compania?' });
    expect(within(dialog).getByText(/publicarea se aplică imediat/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Publică acum' }));
    expect(await screen.findByText('„Contract cadru” este acum disponibil în toată compania.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/approvals')[0].body).toEqual({ kind: 'document.company_publish', payload: { document_id: 5 } });
    expect(mock.find('GET', '/api/workspace/approvals/eligible')).toHaveLength(0);
  });

  it('lets a member ask for publishing only when an administrator can approve it', async () => {
    const mock = boot('/workspace/documents', { 'GET /api/workspace/approvals/eligible': { count: 0 } }, 'member');
    fireEvent.click(await screen.findByRole('button', { name: 'Acțiuni pentru „Contract cadru”' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Publică în toată compania' }));
    const dialog = await screen.findByRole('dialog', { name: 'Publici documentul în toată compania?' });
    expect(await within(dialog).findByText('Nimeni nu poate aproba acum')).toBeTruthy();
    expect(mock.find('GET', '/api/workspace/approvals/eligible')[0].search).toBe('?kind=document.company_publish&department_id=1');
    expect((within(dialog).getByRole('button', { name: 'Trimite cererea' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
