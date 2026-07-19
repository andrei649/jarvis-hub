import React, { useState as uS3, useEffect as uE3 } from 'react';
import { V2, Conversation, InputBar } from './ui';
import { Icon as Ic3, ICONS as IK3, Glyph as Gl3, statusClass as sc3 } from './ui';
import { queueChannelReply, togglePlugin } from './api/actions';
import { RoomsPanel } from './gap';
/* HUD v2 · MODES III — Chat (focus), Comms, Admin */

function SubH3({ children, style }: { children?: any; style?: any }){ return <div className="sub-h" style={style}>{children}</div>; }

/* ============ CHAT · distraction-free ============ */
function ChatMode({ messages, thinking, onStop, onSubmit, onProv, mic, setMic, lang, t }: any){
  return (
    <div className="chat-wrap">
      <div className="chat-col">
        <div className="chat-head">
          <span className="chat-glyph"><Gl3 id="jarvis" size={20}/></span>
          <div><div className="chat-title">{t.directLine} · NERVA</div><div className="chat-sub">{t.focusHintChat}</div></div>
          <span className="chat-live"><span className="sdot active"></span>local</span>
        </div>
        <Conversation messages={messages} thinking={thinking} onStop={onStop} onProv={onProv} lang={lang} t={t}/>
        <InputBar onSubmit={onSubmit} mic={mic} setMic={setMic} t={t}/>
      </div>
    </div>
  );
}

/* ============ COMMS · unified inbox ============ */
function CommsMode({ t }){
  const C = V2.COMMS;
  const [filter,setFilter]=uS3('all');
  const [sel,setSel]=uS3(C.threads[0]?.id || '');
  const chIcon = ch => ch==='telegram'?'send':ch==='email'?'comms':ch==='whatsapp'?'chat':ch==='discord'?'chat':'mic';
  const list = C.threads.filter(th=>filter==='all'||th.channel===filter);
  const active = C.threads.find(th=>th.id===sel) || list[0];
  const [reply,setReply]=uS3('');
  const [replyState,setReplyState]=uS3('');
  const activeAny = active as any;
  const activeThread = activeAny?.thread_id || activeAny?.id || '';
  const canReply = !!activeAny?.replyable && !!activeThread && ['telegram','web'].includes(activeAny.channel);
  uE3(()=>{ setReply(''); setReplyState(''); }, [activeThread]);
  const queueReply = () => {
    const text = reply.trim();
    if (!canReply || !text) return;
    setReplyState('queueing…');
    queueChannelReply(activeThread, text, active.agent || 'veronica')
      .then((r: any) => {
        setReply('');
        setReplyState(r?.queued ? 'queued for approval' : 'reply drafted');
      })
      .catch(() => setReplyState('queue failed'));
  };
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Ic3 d={IK3.comms} size={14}/><span className="ttl">{t.inbox}</span><span className="st">{C.threads.filter(x=>x.unread).length} unread</span></div>
      <div className="comms-body">
        <div className="comms-list">
          <div className="comms-filters">
            <button className={'cf'+(filter==='all'?' on':'')} onClick={()=>setFilter('all')}>{t.allChannels}</button>
            {C.channels.map(ch=>(
              <button key={ch.id} className={'cf'+(filter===ch.id?' on':'')} onClick={()=>setFilter(ch.id)}>{ch.label} · {ch.count}</button>
            ))}
          </div>
          {list.map(th=>(
            <div className={'comms-row'+(sel===th.id?' sel':'')+(th.unread?' unread':'')} key={th.id} onClick={()=>setSel(th.id)}>
              <span className="cm-ch"><Ic3 d={IK3[chIcon(th.channel)]} size={13}/></span>
              <div className="cm-mid">
                <div className="cm-top"><span className="cm-from">{th.from}</span><span className="cm-ts">{th.ts}</span></div>
                <div className="cm-subj">{th.subj}</div>
                <div className="cm-handled"><Gl3 id={th.agent} size={10}/>{th.agent}{th.local&&<span className="cm-local">on-device</span>}{th.dir==='out'&&<span className="cm-out">outbound</span>}</div>
              </div>
              {th.unread && <span className="cm-dot"></span>}
            </div>
          ))}
        </div>
        <div className="comms-read">
          {active ? (<>
            <div className="cr-head"><span className="cr-ch"><Ic3 d={IK3[chIcon(active.channel)]} size={14}/>{active.channel}</span>
              <span className="cr-handled"><Gl3 id={active.agent} size={13}/>handled by {active.agent}</span></div>
            <div className="cr-subj">{active.subj}</div>
            <div className="cr-from">{active.from} · {active.ts}</div>
            <div className="cr-body">{active.preview}</div>
            {canReply ? (
              <div className="cr-actions" style={{alignItems:'stretch', flexDirection:'column'}}>
                <textarea
                  value={reply}
                  onChange={e=>setReply(e.target.value)}
                  placeholder="Write a governed reply"
                  rows={3}
                  style={{width:'100%', resize:'vertical', background:'var(--surface)', color:'var(--ink)', border:'1px solid var(--panel-line)', borderRadius:4, padding:8, fontFamily:'var(--font-ui)', fontSize:12}}
                />
                <div style={{display:'flex', gap:8, alignItems:'center'}}>
                  <button className="cr-btn primary" disabled={!reply.trim()} onClick={queueReply}>Queue reply</button>
                  {replyState && <span className="cr-from">{replyState}</span>}
                </div>
              </div>
            ) : (
              <div className="cr-actions">
                <button className="cr-btn primary" disabled title="not connected — no live channel thread id" style={{opacity:.5,cursor:'not-allowed'}}>Reply via {active.channel}</button>
              </div>
            )}
            <div className="cr-actions">
              <button className="cr-btn" disabled title="not connected — channel inbox is a preview" style={{opacity:.5,cursor:'not-allowed'}}>Hand to agent</button>
              <button className="cr-btn" disabled title="not connected — channel inbox is a preview" style={{opacity:.5,cursor:'not-allowed'}}>Archive</button>
            </div>
            <div style={{marginTop:'var(--gap)'}}>
              <div className="sub-h" style={{marginBottom:8}}>LIVE ROOMS · multi-agent messaging (real backend)</div>
              <RoomsPanel />
            </div>
          </>) : <div className="empty-note" style={{padding:16}}>No live comms threads yet</div>}
        </div>
      </div>
    </div>
  );
}

/* ============ ADMIN ============ */
function AdminMode({ t }){
  const A = V2.ADMIN;
  const [plugins,setPlugins]=uS3<Array<{ name: string; scope: string; net: string; on: boolean; id?: string }>>(A.plugins);
  // Keep local plugin list in sync if live.ts swaps in the real registry after mount.
  uE3(() => { setPlugins(A.plugins); }, [A.plugins]);
  // REAL toggle: PUT /plugins/{id}/toggle flips enabled on the backend. The seeded
  // DEMO plugins carry no `id`, so those flip locally only (preview); real plugins
  // (id present) post and reconcile to the server's returned `enabled` (revert on fail).
  const onToggle = i => {
    const p = plugins[i];
    const next = !p.on;
    setPlugins(ps=>ps.map((x,j)=>j===i?{...x,on:next}:x)); // optimistic
    if (!p.id) return; // demo/seed row — no backend id, preview only
    togglePlugin(p.id)
      .then((r: any) => { if (r && typeof r.enabled === 'boolean') setPlugins(ps=>ps.map((x,j)=>j===i?{...x,on:r.enabled}:x)); })
      .catch(() => setPlugins(ps=>ps.map((x,j)=>j===i?{...x,on:!next}:x))); // revert on failure
  };
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Ic3 d={IK3.admin} size={14}/><span className="ttl">{t.admin} · Settings</span><span className="st">{A.system.host} · up {A.system.uptime}</span></div>
      <div className="panel-body">
        <div className="admin-grid">
          <div>
            <SubH3>MODELS &amp; BACKENDS</SubH3>
            {A.models.map((m,i)=>(
              <div className="mdl-row" key={i}>
                <div><div className="mdl-name">{m.name}<span className={'mdl-type '+m.type}>{m.type}</span></div><div className="mdl-meta">{m.backend} · ctx {m.ctx} · {m.use}</div></div>
                <span className={'mdl-status '+(m.status==='loaded'?'on':'')}>{m.status}</span>
              </div>
            ))}
            <SubH3 style={{marginTop:16}}>API KEYS &amp; SECRETS</SubH3>
            {A.keys.map((k,i)=>(
              <div className="key-row" key={i}>
                <div><div className="key-name">{k.name}</div><div className="key-mask">{k.masked}</div></div>
                <div className="key-right"><span className={'key-status '+(k.status==='valid'?'ok':'warn')}>{k.status}</span><span className="key-rot">{k.rotated}</span></div>
              </div>
            ))}
            <SubH3 style={{marginTop:16}}>BACKUPS</SubH3>
            {A.backups.map((b,i)=>(
              <div className="cap-row" key={i}><div><div className="cn" style={{fontFamily:'var(--font-ui)'}}>{b.ts}</div><div className="cd">{b.size} · {b.target}</div></div><span className="cap-tag allow">✓ {b.status}</span></div>
            ))}
          </div>
          <div>
            <SubH3>PLUGIN REGISTRY · {plugins.filter(p=>p.on).length}/{plugins.length} enabled</SubH3>
            {plugins.map((p,i)=>(
              <div className="plg-row" key={i}>
                <div><div className="plg-name">{p.name}</div><div className="plg-scope">{p.scope}<span className={'plg-net '+p.net}>{p.net}</span></div></div>
                <button className={'twk-mini '+(p.on?'on':'')} onClick={()=>onToggle(i)} title={p.id?(p.on?'disable plugin':'enable plugin'):'demo plugin — preview only'}><i></i></button>
              </div>
            ))}
            <SubH3 style={{marginTop:16}}>CHANNELS</SubH3>
            {A.channels.map((c,i)=>(
              <div className="cap-row" key={i}><div className="cn" style={{fontFamily:'var(--font-ui)'}}>{c.name}</div><span className="cap-tag allow">{c.status}</span></div>
            ))}
            <SubH3 style={{marginTop:16}}>HOST</SubH3>
            <div className="host-grid">
              {[['CPU',A.system.cpu],['RAM',A.system.ram],['GPU',A.system.gpu],['UPTIME',A.system.uptime]].map(([k,v])=>(
                <div className="host-cell" key={k}><div className="hk">{k}</div><div className="hv">{v}</div></div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export { ChatMode, CommsMode, AdminMode };
