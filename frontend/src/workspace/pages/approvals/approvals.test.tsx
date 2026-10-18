import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Approval } from '../../api/types';
import { renderApp } from '../../test/render';
import { apiError, json, makeUser, mockFetch, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';

const NOW = Date.now() / 1000;

function approval(over: Partial<Approval> = {}): Approval {
  return {
    id: 5, kind: 'email.send', department_id: 1, summary: 'Email către ion@client.ro: Termene de plată',
    payload: {
      to: ['ion@client.ro', 'ana@client.ro'], subject: 'Termene de plată',
      body_markdown: '## Pe scurt\n\nPlata se face în **30 de zile**.', source: { type: 'report_run', id: 40 },
    },
    status: 'pending', requester: { id: 2, name: 'Ion Ionescu' }, decider: null, decided_at: null, decision_note: null,
    result: null, error_code: null, created_at: NOW - 600, expires_at: NOW + 6 * 86_400, can_decide: true, can_cancel: false,
    eligible_deciders: [{ id: 1, name: 'Ana Pop' }], ...over,
  };
}

function boot(path: string, routes: Record<string, RouteHandler> = {}, role: 'admin' | 'approver' | 'member' = 'approver') {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser({ role })),
    ...shellRoutes(),
    'GET /api/workspace/approvals': (call) => {
      const box = new URLSearchParams(call.search).get('box');
      return { items: box === 'inbox' ? [approval()] : [approval({ id: 8, requester: { id: 1, name: 'Ana Pop' }, can_decide: false, can_cancel: true })], pending_inbox_count: 1 };
    },
    'GET /api/workspace/approvals/5': approval(),
    ...routes,
  });
  renderApp(path);
  return mock;
}

describe('Approvals → deciding', () => {
  it('previews an email request and approves it with a note; the result and the badge refresh', async () => {
    const mock = boot('/workspace/approvals', {
      'POST /api/workspace/approvals/5/decide': approval({
        status: 'approved', can_decide: false, decider: { id: 1, name: 'Ana Pop' }, decided_at: NOW, decision_note: 'Trimite.',
        result: { sent_to: ['ion@client.ro', 'ana@client.ro'] },
      }),
    });
    const table = await screen.findByRole('table', { name: /De aprobat/ });
    await waitFor(() => expect(mock.find('GET', '/api/workspace/approvals')[0]).toBeTruthy());
    expect(mock.find('GET', '/api/workspace/approvals').some((c) => c.search === '?box=inbox&status=pending')).toBe(true);
    fireEvent.click(await within(table).findByRole('button', { name: 'Email către ion@client.ro: Termene de plată' }));
    await waitFor(() => expect(window.location.pathname).toBe('/workspace/approvals/5'));

    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    // The recipients read as one plain value of the grid, like the subject under them (UX-20).
    expect(await within(drawer).findByText('ion@client.ro, ana@client.ro')).toBeTruthy();
    expect(within(drawer).getByRole('heading', { name: 'Ce se întâmplă la aprobare' })).toBeTruthy();
    expect(within(drawer).getByText('Termene de plată')).toBeTruthy();
    expect(within(drawer).getByRole('heading', { name: 'Pe scurt' })).toBeTruthy();
    expect(within(drawer).getByText('30 de zile')).toBeTruthy();
    expect(within(drawer).getByRole('link', { name: 'Deschide raportul' }).getAttribute('href')).toBe('/workspace/report-runs/40');
    expect(within(drawer).getByText('Ana Pop')).toBeTruthy();

    const badgeReads = mock.find('GET', '/api/workspace/approvals').length;
    fireEvent.click(within(drawer).getByRole('button', { name: 'Aprobă' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Aprobi cererea?' });
    fireEvent.change(within(confirm).getByLabelText(/^Notă pentru solicitant/), { target: { value: 'Trimite.' } });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Aprobă' }));

    expect(await screen.findByText('Cererea a fost aprobată și executată.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/approvals/5/decide')[0].body).toEqual({ decision: 'approve', note: 'Trimite.' });
    expect(await within(drawer).findByText('Aprobată și executată')).toBeTruthy();
    expect(within(drawer).getByText('Trimis către: ion@client.ro, ana@client.ro')).toBeTruthy();
    expect(within(drawer).getByRole('heading', { name: 'Acțiunea cerută' })).toBeTruthy();
    expect(within(drawer).queryByRole('heading', { name: 'Ce se întâmplă la aprobare' })).toBeNull();
    expect(within(drawer).queryByRole('button', { name: 'Aprobă' })).toBeNull();
    await waitFor(() => expect(mock.find('GET', '/api/workspace/approvals').length).toBeGreaterThan(badgeReads + 1));
  });

  it('rejects a request without a note, and shows when execution failed after approval', async () => {
    const mock = boot('/workspace/approvals/5', {
      'POST /api/workspace/approvals/5/decide': (call) => ((call.body as { decision: string }).decision === 'reject'
        ? approval({ status: 'rejected', can_decide: false, decider: { id: 1, name: 'Ana Pop' }, decided_at: NOW })
        : approval()),
    });
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    fireEvent.click(await within(drawer).findByRole('button', { name: 'Respinge' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Respingi cererea?' });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Respinge' }));
    expect(await within(drawer).findByText('Cererea a fost respinsă.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/approvals/5/decide')[0].body).toEqual({ decision: 'reject' });
    // A rejected request no longer says what approving *will* do (UX-20).
    expect(within(drawer).getByRole('heading', { name: 'Ce s-ar fi întâmplat la aprobare' })).toBeTruthy();
    expect(within(drawer).queryByRole('heading', { name: 'Ce se întâmplă la aprobare' })).toBeNull();
  });

  it('reports an approval that failed to execute, with the reason', async () => {
    boot('/workspace/approvals/5', {
      'GET /api/workspace/approvals/5': approval({ status: 'failed', can_decide: false, error_code: 'smtp_failed', decider: { id: 1, name: 'Ana Pop' }, decided_at: NOW }),
    });
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    expect(await within(drawer).findByText('Aprobată, dar execuția nu a reușit')).toBeTruthy();
    expect(within(drawer).getByText('Serverul de email a refuzat mesajul sau nu a putut fi contactat.')).toBeTruthy();
    expect(within(drawer).getByRole('heading', { name: 'Acțiunea cerută' })).toBeTruthy();
  });

  it('heads the preview of an expired or cancelled request with what approving would have done (UX-20)', async () => {
    for (const status of ['expired', 'cancelled'] as const) {
      boot('/workspace/approvals/5', { 'GET /api/workspace/approvals/5': approval({ status, can_decide: false }) });
      const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
      expect(await within(drawer).findByRole('heading', { name: 'Ce s-ar fi întâmplat la aprobare' }), status).toBeTruthy();
      cleanup();
    }
  });

  it('says so when someone else decided first', async () => {
    boot('/workspace/approvals/5', { 'POST /api/workspace/approvals/5/decide': apiError(409, 'already_decided') });
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    fireEvent.click(await within(drawer).findByRole('button', { name: 'Aprobă' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Aprobi cererea?' });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Aprobă' }));
    expect(await within(confirm).findByText('Cererea a fost deja decisă.')).toBeTruthy();
  });

  it('previews what publishing a document and delivering a report will do', async () => {
    boot('/workspace/approvals/5', {
      'GET /api/workspace/approvals/5': approval({ kind: 'document.company_publish', summary: 'Publicare: Regulament', payload: { document_id: 9 } }),
    }, 'admin');
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    expect(await within(drawer).findByText(/va deveni vizibil în toate departamentele/)).toBeTruthy();
    expect(within(drawer).getByRole('link', { name: 'Deschide documentul' }).getAttribute('href')).toBe('/workspace/documents/9');
  });
});

describe('Approvals → my requests', () => {
  it('lists my requests and cancels a pending one after confirmation', async () => {
    const mock = boot('/workspace/approvals', {
      'GET /api/workspace/approvals/8': approval({ id: 8, requester: { id: 1, name: 'Ana Pop' }, can_decide: false, can_cancel: true }),
      'POST /api/workspace/approvals/8/cancel': approval({ id: 8, status: 'cancelled', requester: { id: 1, name: 'Ana Pop' }, can_decide: false, can_cancel: false }),
    }, 'member');
    // A member decides nothing: the page opens on their own requests, with no inbox to switch to.
    await waitFor(() => expect(mock.find('GET', '/api/workspace/approvals').some((c) => c.search === '?box=mine')).toBe(true));
    expect(screen.queryByRole('tab', { name: /De aprobat/ })).toBeNull();
    expect(screen.getByText('Cererile trimise de tine (emailuri, partajări, publicări) și decizia primită pentru fiecare.')).toBeTruthy();
    const table = await screen.findByRole('table', { name: 'Cererile mele' });
    fireEvent.click(await within(table).findByRole('button', { name: 'Email către ion@client.ro: Termene de plată' }));
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #8' });
    expect(await within(drawer).findByText('Este cererea ta, așa că o decide altcineva.')).toBeTruthy();
    expect(within(drawer).queryByRole('button', { name: 'Aprobă' })).toBeNull();

    fireEvent.click(within(drawer).getByRole('button', { name: 'Anulează cererea' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Anulezi cererea?' });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Anulează cererea' }));
    expect(await screen.findByText('Cererea a fost anulată.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/approvals/8/cancel')).toHaveLength(1);
    expect(await within(drawer).findByText('Solicitantul a anulat cererea.')).toBeTruthy();
  });

  it('filters by status on the server', async () => {
    const mock = boot('/workspace/approvals');
    await screen.findByRole('table', { name: /De aprobat/ });
    fireEvent.change(screen.getByLabelText('Stare'), { target: { value: 'approved' } });
    await waitFor(() => expect(mock.find('GET', '/api/workspace/approvals').slice(-1)[0]?.search).toBe('?box=inbox&status=approved'));
  });

  it('teaches an empty inbox', async () => {
    boot('/workspace/approvals', { 'GET /api/workspace/approvals': json(200, { items: [], pending_inbox_count: 0 }) });
    expect(await screen.findByText('Nicio cerere de aprobat')).toBeTruthy();
  });

  it('names the department as the server does, also one outside the viewer\'s list', async () => {
    boot('/workspace/approvals/5', {
      'GET /api/workspace/approvals': { items: [approval({ department_id: 9, department_name: 'Achiziții' })], pending_inbox_count: 1 },
      'GET /api/workspace/approvals/5': approval({ department_id: 9, department_name: 'Achiziții' }),
    }, 'admin');
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    expect(await within(drawer).findByText('Achiziții')).toBeTruthy();
    expect(within(drawer).queryByText('#9')).toBeNull();
  });

  it('shows who will receive an approved report delivery', async () => {
    boot('/workspace/approvals/5', {
      'GET /api/workspace/approvals/5': approval({
        kind: 'report.delivery', payload: { report_id: 3, emails: ['sef@acme.ro'] }, status: 'approved', can_decide: false,
        decider: { id: 1, name: 'Ana Pop' }, decided_at: NOW, result: { report_id: 3, approved_recipients: ['sef@acme.ro'] },
      }),
    });
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    expect(await within(drawer).findByText('Fiecare rulare reușită a raportului va fi trimisă către: sef@acme.ro')).toBeTruthy();
  });

  it('explains why an approved request failed, in plain words', async () => {
    boot('/workspace/approvals/5', {
      'GET /api/workspace/approvals/5': approval({ status: 'failed', can_decide: false, error_code: 'stale_request', decider: { id: 1, name: 'Ana Pop' }, decided_at: NOW }),
    });
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    expect(await within(drawer).findByText(/Cererea nu mai corespunde situației actuale/)).toBeTruthy();
  });

  it('says in the reader\'s language that an admin\'s own request ran at once', async () => {
    boot('/workspace/approvals/5', {
      'GET /api/workspace/approvals/5': approval({
        kind: 'report.share_company', payload: { run_id: 40 }, status: 'approved', can_decide: false,
        requester: { id: 1, name: 'Ana Pop' }, decider: { id: 1, name: 'Ana Pop' }, decided_at: NOW, decision_note: 'admin action',
        result: { run_id: 40, shared_company: true },
      }),
    }, 'admin');
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    expect(await within(drawer).findByText('Aplicată imediat: solicitantul este administrator, iar acțiunea nu avea nevoie de altă aprobare.')).toBeTruthy();
    expect(within(drawer).queryByText('admin action')).toBeNull();
  });
});
