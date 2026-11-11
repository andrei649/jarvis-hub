// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { RoomPeersPanel } from './room-peers';
import { CONSOLE_PANELS } from '../console-routes';

const STATUS = {
  available: true, enabled: true, hub: 'a'.repeat(32), key_fingerprint: 'abcd:ef01:2345:6789', epochs: { room1: 3 },
  invitations: [{ id: 'inv1', room_id: 'room1', member_id: 'ana', status: 'approved', policy: { tools: ['room_read'], permissions: ['dispatch'], max_calls_per_hour: 60 } }],
  members: [{ id: 'm1', room_id: 'room1', member_id: 'ana', member_hub: 'b'.repeat(32), principal: 'roommember:room1:ana@bbbb', status: 'active', key_fingerprint: '1111:2222:3333:4444', policy: { tools: ['room_read'], permissions: ['dispatch'], max_calls_per_hour: 60 } }],
  links: [{ id: 'l1', room_id: 'room9', room_name: 'Garage', member_id: 'me', target_hub: 'c'.repeat(32), status: 'active', target_key_fingerprint: '9999:8888:7777:6666' }],
};

function hub(routes) {
  const calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET';
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
    calls.push({ url: String(url), method, body });
    const answer = routes(String(url), method, body);
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
  });
  return calls;
}

const standard = (url, method) => {
  if (url.endsWith('/api/room-peers') && method === 'GET') return { status: 200, body: STATUS };
  if (url.endsWith('/api/room-peers/invitations')) return { status: 200, body: { ok: true, task_id: 12 } };
  if (url.includes('/bundle')) return { status: 200, body: { ok: true, bundle: 'nrb1.xyz', key_fingerprint: 'abcd:ef01:2345:6789' } };
  if (url.includes('/api/room-peers/members/m1') && method === 'DELETE') return { status: 200, body: { ok: true } };
  if (url.includes('/api/room-peers/links/l1/call')) return { status: 202, body: { ok: false, reason: 'approval_required', task_id: 4 } };
  return { status: 404, body: {} };
};

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('Remote Members panel', () => {
  it('is registered as an admin console panel', () => {
    expect(CONSOLE_PANELS).toContainEqual({ id: 'remote-members', label: 'Remote Members', group: 'Admin', component: 'RoomPeersPanel' });
  });

  it('shows members, links and key fingerprints, never a grant', async () => {
    hub(standard);
    render(<RoomPeersPanel />);
    await screen.findByText('roommember:room1:ana@bbbb');
    expect(screen.getByText(/abcd:ef01:2345:6789/)).toBeTruthy();
    expect(screen.getByText(/9999:8888:7777:6666/)).toBeTruthy();
  });

  it('invites through an approval card, takes the bundle, revokes and calls through a link', async () => {
    const calls = hub(standard);
    render(<RoomPeersPanel />);
    await screen.findByText('roommember:room1:ana@bbbb');
    fireEvent.change(screen.getByLabelText('Room'), { target: { value: 'room1' } });
    fireEvent.change(screen.getByLabelText('Member'), { target: { value: 'bob' } });
    fireEvent.change(screen.getByLabelText('Tools'), { target: { value: 'room_read, room_write' } });
    fireEvent.change(screen.getByLabelText("This hub's address"), { target: { value: 'http://192.168.1.5:8000' } });
    fireEvent.click(screen.getByText('invite…'));
    await screen.findByText(/card #12/);
    const invite = calls.find((c) => c.url.endsWith('/api/room-peers/invitations'));
    expect(invite.body).toEqual({ room_id: 'room1', member_id: 'bob', tools: ['room_read', 'room_write'], target_url: 'http://192.168.1.5:8000' });
    fireEvent.click(screen.getByText('bundle'));
    await screen.findByText('nrb1.xyz');
    fireEvent.click(screen.getByText('revoke'));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/api/room-peers/members/m1'))).toBe(true));
    fireEvent.change(screen.getByLabelText('tool'), { target: { value: 'room_write' } });
    fireEvent.click(screen.getByText('call'));
    await screen.findByText(/approval_required/);
  });
});
