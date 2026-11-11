/* Remote Members — a room member that lives on another machine (H658).

   The hub decides everything that matters (agents/core/room_peers.py): this panel only
   shows what it is given and says why something was refused.

   On the hub whose tools run (the target):
   - Invite a member into a room with the tools it may use. The invitation is a card in
     the decision inbox; only after you accept it can you take the one-time bundle.
   - Change a member's tools (its grant stops working until it is invited again) or
     revoke it (its next call is refused).

   On the hub where the member lives:
   - Join with a bundle, call a tool through the link (the target's own approvals decide),
     renew the grant, or leave. Grants and keys are never shown. */
import React, { useState } from 'react';
import { apiDelete, apiPost } from '../api/client';
import { Card, Tag, inpS, mono, refusalReason, useApi } from '../panel-kit';

export const ROOM_PEERS_PATH = '/api/room-peers';

type Policy = { tools: string[]; permissions: string[]; max_calls_per_hour: number };
type Invitation = { id: string; room_id: string; member_id: string; policy: Policy; status: string; task_id?: number; bundle_issued?: boolean };
type Member = { id: string; room_id: string; member_id: string; member_hub: string; principal: string; policy: Policy; status: string; key_fingerprint: string; calls?: number };
type Link = { id: string; room_id: string; room_name?: string; member_id: string; target_hub: string; status: string; epoch?: number; target_key_fingerprint: string; last_reason?: string; label?: string };

const why = (err: any) => refusalReason(err, String(err?.status || 'error'));
const tools = (s: string) => s.split(',').map((t) => t.trim()).filter(Boolean);

export function RoomPeersPanel() {
  const st = useApi(ROOM_PEERS_PATH, true, true);
  const d: any = st.d || {};
  const invitations: Invitation[] = Array.isArray(d.invitations) ? d.invitations : [];
  const members: Member[] = Array.isArray(d.members) ? d.members : [];
  const links: Link[] = Array.isArray(d.links) ? d.links : [];
  const [note, setNote] = useState<string | null>(null);
  const [room, setRoom] = useState('');
  const [member, setMember] = useState('');
  const [toolList, setToolList] = useState('');
  const [url, setUrl] = useState('');
  const [bundle, setBundle] = useState('');
  const [shown, setShown] = useState<string | null>(null);
  const [callTool, setCallTool] = useState('');
  const [callArgs, setCallArgs] = useState('{}');
  const [answer, setAnswer] = useState<string | null>(null);

  const invite = () => {
    apiPost('/api/room-peers/invitations', { room_id: room.trim(), member_id: member.trim(), tools: tools(toolList), target_url: url.trim() }, { admin: true })
      .then((r: any) => { setNote(`invitation waits for your decision · card #${r?.task_id} in the decision inbox`); st.reload(); })
      .catch((x: any) => setNote(`not invited · ${why(x)}`));
  };
  const takeBundle = (inv: Invitation) => {
    apiPost(`/api/room-peers/invitations/${encodeURIComponent(inv.id)}/bundle`, {}, { admin: true })
      .then((r: any) => { setShown(r?.bundle || null); setNote(`hand this to the member's hub once · key ${r?.key_fingerprint}`); st.reload(); })
      .catch((x: any) => setNote(`no bundle · ${why(x)}`));
  };
  const narrow = (m: Member) => {
    const next = window.prompt(`tools for ${m.member_id} (comma separated)`, m.policy.tools.join(', '));
    if (next == null) return;
    apiPost(`/api/room-peers/members/${encodeURIComponent(m.id)}/policy`, { tools: tools(next), permissions: m.policy.permissions, max_calls_per_hour: m.policy.max_calls_per_hour }, { admin: true })
      .then(() => { setNote(`${m.member_id}'s policy changed · its grant must be re-issued by a new invitation`); st.reload(); })
      .catch((x: any) => setNote(`not changed · ${why(x)}`));
  };
  const revoke = (m: Member) => {
    apiDelete(`/api/room-peers/members/${encodeURIComponent(m.id)}`, { admin: true })
      .then(() => { setNote(`${m.member_id} revoked · refused from its next call`); st.reload(); })
      .catch((x: any) => setNote(`not revoked · ${why(x)}`));
  };
  const join = () => {
    apiPost('/api/room-peers/links', { bundle: bundle.trim() }, { admin: true })
      .then(() => { setBundle(''); setNote('joined · the target key is pinned'); st.reload(); })
      .catch((x: any) => setNote(`not joined · ${why(x)}`));
  };
  const call = (lk: Link) => {
    let args: unknown = {};
    try { args = JSON.parse(callArgs || '{}'); } catch { setNote('arguments must be JSON'); return; }
    apiPost(`/api/room-peers/links/${encodeURIComponent(lk.id)}/call`, { op: 'dispatch', tool: callTool.trim(), args }, { admin: true })
      .then((r: any) => { setAnswer(JSON.stringify(r, null, 2)); st.reload(); })
      .catch((x: any) => setAnswer(`refused · ${why(x)}`));
  };
  const renew = (lk: Link) => {
    apiPost(`/api/room-peers/links/${encodeURIComponent(lk.id)}/renew`, {}, { admin: true })
      .then((r: any) => { setNote(r?.ok ? 'grant renewed' : `not renewed · ${r?.reason}`); st.reload(); })
      .catch((x: any) => setNote(`not renewed · ${why(x)}`));
  };
  const leave = (lk: Link) => {
    apiDelete(`/api/room-peers/links/${encodeURIComponent(lk.id)}`, { admin: true })
      .then(() => { setNote('left'); st.reload(); })
      .catch((x: any) => setNote(`not left · ${why(x)}`));
  };

  return (
    <Card title="REMOTE MEMBERS" live={st.d ? 'live' : undefined} onReload={st.reload}
      sub={st.d ? `${members.length} members · ${links.length} links` : null}>
      {st.e && <div role="status" style={{ color: 'var(--amber)', fontSize: 11 }}>not loaded · {String(st.e)}</div>}
      {st.d && d.enabled === false && <div role="status" style={{ fontSize: 11 }}>Off on this hub (<span style={mono}>JARVIS_ROOM_PEERS</span>).</div>}
      {d.key_fingerprint && <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginBottom: 6 }}>This hub's key · <span style={mono}>{d.key_fingerprint}</span>. Compare it with the other owner before you accept a bundle.</div>}
      {note && <div role="status" style={{ color: 'var(--ink-2)', fontSize: 11, marginBottom: 4 }}>{note}</div>}

      <div aria-label="invite" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 6 }}>
        <label htmlFor="rp-room" style={{ fontSize: 10.5 }}>Room</label>
        <input id="rp-room" value={room} onChange={(ev) => setRoom(ev.target.value)} style={{ ...inpS, width: 110 }} />
        <label htmlFor="rp-member" style={{ fontSize: 10.5 }}>Member</label>
        <input id="rp-member" value={member} onChange={(ev) => setMember(ev.target.value)} style={{ ...inpS, width: 90 }} />
        <label htmlFor="rp-tools" style={{ fontSize: 10.5 }}>Tools</label>
        <input id="rp-tools" value={toolList} onChange={(ev) => setToolList(ev.target.value)} style={{ ...inpS, width: 160 }} />
        <label htmlFor="rp-url" style={{ fontSize: 10.5 }}>This hub's address</label>
        <input id="rp-url" value={url} onChange={(ev) => setUrl(ev.target.value)} style={{ ...inpS, width: 180 }} />
        <button className="tool-btn" onClick={invite} disabled={!room.trim() || !member.trim() || !toolList.trim() || !url.trim()}>invite…</button>
      </div>

      <ul aria-label="invitations" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {invitations.map((inv) => (
          <li key={inv.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '3px 0', flexWrap: 'wrap' }}>
            <Tag>{inv.status}</Tag>
            <span style={{ ...mono, fontSize: 11 }}>{inv.member_id} → {inv.room_id}</span>
            <span style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>{inv.policy?.tools?.join(', ')}</span>
            {inv.status === 'approved' && <button className="tool-btn" onClick={() => takeBundle(inv)}>bundle</button>}
          </li>
        ))}
      </ul>
      {shown && <pre aria-label="bundle" style={{ ...mono, fontSize: 10, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', background: 'var(--surface)', padding: 6 }}>{shown}</pre>}

      <ul aria-label="members" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {members.map((m) => (
          <li key={m.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '3px 0', borderBottom: '1px solid var(--panel-line)', flexWrap: 'wrap' }}>
            <Tag c={m.status === 'active' ? 'var(--accent-light)' : 'var(--amber)'}>{m.status}</Tag>
            <span style={{ ...mono, fontSize: 11 }}>{m.principal}</span>
            <span style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>{m.policy?.tools?.join(', ')} · key {m.key_fingerprint}</span>
            {m.status === 'active' && <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
              <button className="tool-btn" onClick={() => narrow(m)}>tools…</button>
              <button className="tool-btn" onClick={() => revoke(m)}>revoke</button>
            </span>}
          </li>
        ))}
      </ul>

      <div aria-label="join" style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 8 }}>
        <label htmlFor="rp-bundle" style={{ fontSize: 10.5 }}>Bundle</label>
        <input id="rp-bundle" value={bundle} onChange={(ev) => setBundle(ev.target.value)} style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" onClick={join} disabled={!bundle.trim()}>join</button>
      </div>
      <ul aria-label="links" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {links.map((lk) => (
          <li key={lk.id} style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '3px 0', borderBottom: '1px solid var(--panel-line)', flexWrap: 'wrap' }}>
            <Tag c={lk.status === 'active' ? 'var(--accent-light)' : 'var(--amber)'}>{lk.status}</Tag>
            <span style={{ ...mono, fontSize: 11 }}>{lk.member_id} in {lk.room_name || lk.room_id}</span>
            <span style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>target key {lk.target_key_fingerprint}{lk.last_reason ? ` · ${lk.last_reason}` : ''}</span>
            {lk.status === 'active' && <>
              <label htmlFor={`rp-tool-${lk.id}`} style={{ fontSize: 10.5 }}>tool</label>
              <input id={`rp-tool-${lk.id}`} value={callTool} onChange={(ev) => setCallTool(ev.target.value)} style={{ ...inpS, width: 100 }} />
              <label htmlFor={`rp-args-${lk.id}`} style={{ fontSize: 10.5 }}>args</label>
              <input id={`rp-args-${lk.id}`} value={callArgs} onChange={(ev) => setCallArgs(ev.target.value)} style={{ ...inpS, width: 120 }} />
              <button className="tool-btn" onClick={() => call(lk)} disabled={!callTool.trim()}>call</button>
              <button className="tool-btn" onClick={() => renew(lk)}>renew</button>
            </>}
            <button className="tool-btn" onClick={() => leave(lk)}>leave</button>
          </li>
        ))}
      </ul>
      {answer && <pre aria-label="answer" style={{ ...mono, fontSize: 10, whiteSpace: 'pre-wrap', background: 'var(--surface)', padding: 6 }}>{answer}</pre>}
    </Card>
  );
}
