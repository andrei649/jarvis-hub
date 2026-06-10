'use strict';
/* HUD v2 · MODES IV — Finance, Health, Knowledge, Family (agent homes) */
const { Icon:Ic4, ICONS:IK4, Glyph:Gl4 } = window;

function MP({ icon, title, status, children }){
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Ic4 d={IK4[icon]} size={14}/><span className="ttl">{title}</span>{status&&<span className="st">{status}</span>}</div>
      <div className="panel-body">{children}</div>
    </div>
  );
}
function SubH4({ children, style }){ return <div className="sub-h" style={style}>{children}</div>; }

/* ============ FINANCE ============ */
function FinanceMode({ t }){
  const F = window.V2.FINANCE;
  return (
    <MP icon="finance" title={t.finance} status="Gecko">
      <div className="fin-hero">
        <div><div className="fin-nw">{F.net_worth}</div><div className="fin-nwl">net worth · <span style={{color:'var(--green)'}}>{F.mom} MoM</span></div></div>
      </div>
      <div className="admin-grid">
        <div>
          <SubH4>ACCOUNTS</SubH4>
          {F.accounts.map((a,i)=>(
            <div className="acct-row" key={i}>
              <div><div className="acct-n">{a.name}</div><div className="acct-d">{a.delta}</div></div>
              <span className={'acct-b '+a.kind}>{a.bal}</span>
            </div>
          ))}
          <SubH4 style={{marginTop:16}}>WATCHES</SubH4>
          {F.watches.map((w,i)=>(
            <div className="cap-row" key={i}><div><div className="cn">{w.pair}</div><div className="cd">band {w.band}</div></div>
              <span className={'cap-tag '+(w.state==='warn'?'gated':'allow')}>{w.val}</span></div>
          ))}
        </div>
        <div>
          <SubH4>BUDGETS · this month</SubH4>
          {F.budgets.map((b,i)=>{ const pct=Math.round(b.spent/b.cap*100); return (
            <div className="meter" key={i}>
              <div className="ml"><span>{b.cat}</span><span>€{b.spent.toLocaleString()} / €{b.cap.toLocaleString()}</span></div>
              <div className="mt"><div className="mf" style={{width:pct+'%', background: pct>85?'var(--amber)':undefined}}></div></div>
            </div>
          );})}
          <SubH4 style={{marginTop:16}}>PENDING</SubH4>
          {F.pending.map((p,i)=>(
            <div className="pay-row" key={i}><span className="pcap">{p.who}</span><span style={{color:'var(--ink-2)'}}>{p.desc}</span>
              <span style={{textAlign:'right',color:p.state==='approve'?'var(--amber)':'var(--ink-3)'}}>{p.amt}</span></div>
          ))}
          <div className="pay-pending"><span style={{color:'var(--amber)',fontFamily:'var(--font-mono)',fontSize:11}}>⏳ 1 sweep awaiting approval — €4,200</span></div>
        </div>
      </div>
    </MP>
  );
}

/* ============ HEALTH ============ */
function Ring({ val, idx }){
  const r=46-idx*13, c=2*Math.PI*r, off=c*(1-val/100);
  const col=['var(--green)','var(--accent)','var(--violet)'][idx];
  return <circle cx="60" cy="60" r={r} fill="none" stroke={col} strokeWidth="9" strokeLinecap="round"
    strokeDasharray={c} strokeDashoffset={off} transform="rotate(-90 60 60)" opacity=".9"/>;
}
function HealthMode({ t }){
  const H = window.V2.HEALTH;
  const maxW=Math.max(...H.week.map(d=>d.v));
  return (
    <MP icon="health" title={t.health} status="Hercules">
      <div className="health-top">
        <div className="rings-card">
          <svg width="120" height="120" viewBox="0 0 120 120">
            {[46,33,20].map((r,i)=><circle key={i} cx="60" cy="60" r={r} fill="none" stroke="var(--void)" strokeWidth="9"/>)}
            {H.rings.map((rg,i)=><Ring key={i} val={rg.val} idx={i}/>)}
          </svg>
          <div className="rings-legend">
            {H.rings.map((rg,i)=>(
              <div className="rl-row" key={i}><span className="rl-sw" style={{background:['var(--green)','var(--accent)','var(--violet)'][i]}}></span>{rg.label}<b>{rg.val}{rg.unit}</b></div>
            ))}
          </div>
        </div>
        <div className="mem-grid" style={{flex:1}}>
          {H.metrics.map((m,i)=>(
            <div className="stat-card" key={i}><div className="sv" style={{fontSize:20}}>{m.v}</div><div className="sl">{m.k}</div><div style={{fontSize:10,color:'var(--ink-3)',marginTop:4}}>{m.sub}</div></div>
          ))}
        </div>
      </div>
      <div className="admin-grid" style={{marginTop:'var(--gap)'}}>
        <div>
          <SubH4>ACTIVITY · this week</SubH4>
          <div className="week-bars">
            {H.week.map((d,i)=>(
              <div className="wb" key={i}><div className="wb-track"><div className="wb-fill" style={{height:(d.v/maxW*100||2)+'%'}}></div></div><span className="wb-d">{d.d}</span></div>
            ))}
          </div>
        </div>
        <div>
          <SubH4>PLAN</SubH4>
          {H.plan.map((p,i)=>(
            <div className={'cal-row '+(p.done?'past':'')} key={i} style={{gridTemplateColumns:'70px 1fr'}}>
              <span className="tm">{p.time}</span><div><div className="ti">{p.done?'✓ ':''}{p.title}</div><div className="vw">{p.detail}</div></div>
            </div>
          ))}
          <div className="verified-row" style={{marginTop:10}}><Ic4 d={IK4.shield} size={12}/>{H.sync}</div>
        </div>
      </div>
    </MP>
  );
}

/* ============ KNOWLEDGE ============ */
function KnowledgeMode({ t }){
  const K = window.V2.KNOWLEDGE;
  return (
    <MP icon="knowledge" title={t.knowledge} status="Vision · OSINT">
      <div className="admin-grid">
        <div>
          <SubH4>RESEARCH QUEUE</SubH4>
          {K.queue.map((q,i)=>(
            <div className="kq-row" key={i}>
              <div><div className="kq-t">{q.title}</div><div className="kq-m"><Gl4 id={q.agent} size={10}/>{q.agent} · {q.sources} sources</div></div>
              <span className={'kq-s '+q.status}>{q.status}</span>
            </div>
          ))}
          <SubH4 style={{marginTop:16}}>DAILY DIGEST</SubH4>
          {K.digest.map((d,i)=>(
            <div className="dig-row" key={i}><div className="dig-t">{d.t}</div><div className="dig-m">{d.src} · {d.when}</div></div>
          ))}
        </div>
        <div>
          <SubH4>SAVED · cited</SubH4>
          {K.saved.map((s,i)=>(
            <div className="saved-row" key={i}>
              <div><div className="sv-t">{s.title}</div><div className="sv-m">{s.src}</div>
                <div style={{marginTop:6}}><span className="topic-pill">{s.tag}</span><span className="topic-pill">{s.cites} citations</span></div></div>
            </div>
          ))}
        </div>
      </div>
    </MP>
  );
}

/* ============ FAMILY · local-only ============ */
function FamilyMode({ t }){
  const F = window.V2.FAMILY;
  return (
    <MP icon="family" title={t.family} status="Frigga">
      <div className="fam-banner"><Ic4 d={IK4.shield} size={14}/> Local-only space · all family data stays on-device, never leaves the machine.</div>
      <div className="admin-grid">
        <div>
          <SubH4>FAMILY</SubH4>
          {F.members.map((m,i)=>(
            <div className="fam-row" key={i}>
              <span className="fam-av">{m.name[0]}</span>
              <div><div className="fam-n">{m.name}<span className="fam-rel">{m.rel}</span></div><div className="fam-note">{m.note}</div></div>
            </div>
          ))}
          <SubH4 style={{marginTop:16}}>REMINDERS</SubH4>
          {F.reminders.map((r,i)=>(
            <div className="cap-row" key={i}><div className="cn" style={{fontFamily:'var(--font-ui)'}}>{r.t}</div><span className="cap-tag scoped">{r.due}</span></div>
          ))}
        </div>
        <div>
          <SubH4>UPCOMING</SubH4>
          {F.events.map((e,i)=>(
            <div className="cal-row" key={i} style={{gridTemplateColumns:'48px 1fr'}}>
              <span className="tm">{e.date}</span><div><div className="ti">{e.title}</div><div className="vw">{e.time} · {e.who}</div></div>
            </div>
          ))}
        </div>
      </div>
    </MP>
  );
}

Object.assign(window, { FinanceMode, HealthMode, KnowledgeMode, FamilyMode });
