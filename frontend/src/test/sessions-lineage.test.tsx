// @ts-nocheck
/* H440 — a conversation is one row. The hub leaves continuations out of the list and each
   row says which lineage member a resume opens (resume_id) and how many continuations it
   has; the panel resumes that member. The owner can rename a chat: a human title is never
   replaced by the automatic ones. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { SessionsPanel, resumeTarget, titlePath } from '../panels/sessions';

let calls;
let renameReply;

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

beforeEach(() => {
  cleanup();
  calls = [];
  renameReply = (body) => reply(200, { ok: true, session: 'root-1', title: body.title, title_source: 'human' });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: u.replace(/^.*?(\/sessions)/, '$1'), method: init.method || 'GET', body });
    if (u.endsWith('/sessions/resume')) return reply(200, { ok: true, session: body.session_id, turns: [], recap: null });
    if (u.endsWith('/title')) return renameReply(body);
    if (u.endsWith('/sessions')) {
      return reply(200, { sessions: [
        { id: 'root-1', title: 'Trip plan', title_source: 'model', resume_id: 'cont-3', continuations: 2 },
        { id: 'solo-1', title: 'Other', title_source: 'human', resume_id: 'solo-1', continuations: 0 },
      ] });
    }
    return reply(404, {});
  });
});

const sent = (method) => calls.filter((c) => c.method === method);

describe('SessionsPanel — H440 lineage and rename', () => {
  it('names what a resume opens and builds the rename path', () => {
    expect(resumeTarget({ id: 'a', resume_id: 'b' })).toBe('b');
    expect(resumeTarget({ id: 'a' })).toBe('a');
    expect(resumeTarget({ session_id: 'a', resume_id: '' })).toBe('a');
    expect(resumeTarget('plain')).toBe('plain');
    expect(titlePath('a b')).toBe('/sessions/a%20b/title');
  });

  it('shows how many continuations a conversation has, only where it has some', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Trip plan');
    const badges = screen.getAllByTestId('lineage-badge');
    expect(badges).toHaveLength(1);
    expect(badges[0].textContent).toBe('+2');
    expect(badges[0].getAttribute('title')).toContain('2 continuations');
  });

  it('resumes the newest member of the lineage, not the root', async () => {
    render(<SessionsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'resume root-1' }));
    await waitFor(() => expect(sent('POST')).toHaveLength(1));
    expect(sent('POST')[0]).toMatchObject({ url: '/sessions/resume', body: { session_id: 'cont-3' } });
    expect((await screen.findByRole('status')).textContent).toContain('resumed cont-3');
  });

  it('resumes a conversation without continuations by its own id', async () => {
    render(<SessionsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'resume solo-1' }));
    await waitFor(() => expect(sent('POST')).toHaveLength(1));
    expect(sent('POST')[0].body).toEqual({ session_id: 'solo-1' });
  });

  it('renames a chat with the title the owner typed, and reloads the list', async () => {
    render(<SessionsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'rename root-1' }));
    const input = screen.getByRole('textbox', { name: 'title for root-1' });
    expect(input.value).toBe('Trip plan');
    fireEvent.change(input, { target: { value: '  Summer in Brasov ' } });
    fireEvent.click(screen.getByRole('button', { name: 'save title for root-1' }));
    await waitFor(() => expect(sent('PATCH')).toHaveLength(1));
    expect(sent('PATCH')[0]).toMatchObject({ url: '/sessions/root-1/title', body: { title: 'Summer in Brasov' } });
    expect((await screen.findByRole('status')).textContent).toContain('renamed root-1');
    expect(screen.queryByRole('textbox', { name: 'title for root-1' })).toBeNull();
    await waitFor(() => expect(calls.filter((c) => c.url === '/sessions' && c.method === 'GET').length).toBeGreaterThan(1));
  });

  it('sends nothing for a blank title and can be cancelled', async () => {
    render(<SessionsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'rename solo-1' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'title for solo-1' }), { target: { value: '   ' } });
    expect(screen.getByRole('button', { name: 'save title for solo-1' }).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'cancel rename' }));
    expect(screen.queryByRole('textbox', { name: 'title for solo-1' })).toBeNull();
    expect(sent('PATCH')).toHaveLength(0);
  });

  it('says so when the hub refuses the rename, and keeps the editor open', async () => {
    renameReply = () => reply(400, { error: 'a title is one line of 1 to 100 characters', reason: 'invalid_title' });
    render(<SessionsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'rename root-1' }));
    fireEvent.click(screen.getByRole('button', { name: 'save title for root-1' }));
    expect((await screen.findByRole('alert')).textContent).toContain('not renamed');
    expect(screen.getByRole('textbox', { name: 'title for root-1' })).toBeTruthy();
  });
});
