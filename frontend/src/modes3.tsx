// @ts-nocheck
import React, { useState as uS3 } from 'react';
import { V2, Conversation, InputBar } from './ui';
import { Icon as Ic3, ICONS as IK3, Glyph as Gl3, statusClass as sc3 } from './ui';
/* HUD v2 · MODES III — Chat (focus), Comms, Admin */

function SubH3({ children, style }){ return <div className="sub-h" style={style}>{children}</div>; }

/* ============ CHAT · distraction-free ============ */
function ChatMode({ messages, thinking, onSubmit, onProv, mic, setMic, t }){
  const Conversation = Conversation, InputBar = InputBar;
  return (
    <div className="chat-wrap">
      <div className="chat-col">
        <div className="chat-head">
          <span className="chat-glyph"><Gl3 id="jarvis" size={20}/></span>
          <div><div className="chat-title">{t.directLine} · JARVIS</div><div className="chat-sub">{t.focusHintChat}</div></div>
          <span className="chat-live"><span className="sdot active"></span>local</span>
        </div>
        <Conversation messages={messages} thinking={thinking} onProv={onProv} t={t}/>
        <InputBar onSubmit={onSubmit} mic={mic} setMic={setMic} t={t}/>
      </div>
    </div>
  );
}

/* ============ COMMS · unified inbox ============ */
function CommsMode({ t }){
  const C = V2.COMMS;
  const [filter,setFilter]=uS3('all');
  const [sel,setSel]=uS3(C.threads[0].id);
  const chIcon = ch => ch==='telegram'?'send':ch==='email'?'comms':ch==='whatsapp'?'chat':'mic';
  const list = C.threads.filter(th=>filter==='all'||th.channel===filter);
  const active = C.threads.find(th=>th.id===sel) || list[0];
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
          {active && (<>
            <div className="cr-head"><span className="cr-ch"><Ic3 d={IK3[chIcon(active.channel)]} size={14}/>{active.channel}</span>
              <span className="cr-handled"><Gl3 id={active.agent} size={13}/>handled by {active.agent}</span></div>
            <div className="cr-subj">{active.subj}</div>
            <div className="cr-from">{active.from} · {active.ts}</div>
            <div className="cr-body">{active.preview}</div>
            <div className="cr-actions">
              <button className="cr-btn primary">Reply via {active.channel}</button>
              <button className="cr-btn">Hand to agent</button>
              <button className="cr-btn">Archive</button>
            </div>
          </>)}
        </div>
      </div>
    </div>
  );
}

/* ============ ADMIN ============ */
function AdminMode({ t }){
  const A = V2.ADMIN;
  const [plugins,setPlugins]=uS3(A.plugins);
  const togglePlugin = i => setPlugins(ps=>ps.map((p,j)=>j===i?{...p,on:!p.on}:p));
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
                <button className={'twk-mini '+(p.on?'on':'')} onClick={()=>togglePlugin(i)}><i></i></button>
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
