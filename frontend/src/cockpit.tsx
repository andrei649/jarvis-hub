import {ComposerImages,useComposerImages} from './composer-images';
import { useVaultNotes, VaultNoteReview } from './composer-vault';
import { ComposerSkills, skillDraftWarning } from './composer-skills';
import { OfficeAttached, OfficeButton, OfficeReview, useOfficeDocument } from './composer-office';
import { BoardResultReview, useBoardResult, type BoardResultRef } from './composer-board-result';
import { BoardSources } from './board-sources';
import type { WorkshopRef } from './workshop-projects';
import { ContextRefHints, acceptRef, useContextRefs } from './context-refs';
/* HUD v2 · COCKPIT — conversation + cognition trace + input */
import React, { useState, useEffect, useLayoutEffect, useRef, useMemo, useId } from 'react';
import { createPortal } from 'react-dom';
import { Icon, ICONS, Glyph } from './primitives';
import { V2 } from './data';
import { playTts } from './api/actions';
import { SaveArtifactButton } from './artifacts';
import { VoiceOrb } from './orb';
import { Markdown } from './markdown';
import { godotDownload } from './godot-download';
import { BlenderModel, blenderCodeExport, blenderMeshRequest, blenderSourceFromReply } from './blender-export';
import './blender-export.css';
import { OfficeExportButton } from './office-export';
import { PhotoshopLayoutButton } from './photoshop-layout';
import { TurnApprovals, TurnTools } from './turn-tools';
import { MicLeases } from './mic-leases';
import { StatusStrip, TurnToolActivity, type TurnOutcome } from './turn-outcome';
import type { PowerState } from './power-chip';
import { RememberMessageDialog } from './remember-message';
import { ChatTaskDialog } from './chat-task-dialog';
import { CompareAgentsDialog } from './compare-agents';
import { ChatHistorySearch, historyOwnerKey, historySourceLabel, type HistoryReference } from './chat-history-search';
import { selectableChatAgents, type ChatAgent } from './chat-routing-policy';
import { TeachProcedureDialog } from './teach-procedure-dialog';
import { ObsidianChatNote, noteCredential, type NoteReceipt, type NoteSubmission, type Target } from './obsidian-chat-note';
import { onOwnerSession } from './api/owner-session';
import { obsidianOpenUri } from '../../apps/jarvis-os/public/js/obsidian-source.js';

/* Per-message TTS replay (🔊) — POST /tts {text,lang} → audio. Honest states: while
   speaking shows ◼ (stop is best-effort via re-click), errors fall back silently to
   the icon. voice.ts owns the live mic loop; this is just on-demand playback of a
   single past reply, which the prototype was missing. */
function TtsButton({ text, lang }) {
  const [state, setState] = useState('idle'); // idle | playing | err
  const play = () => {
    if (state === 'playing' || !text) return;
    setState('playing');
    playTts(text, lang || 'en').then(() => setState('idle')).catch(() => setState('err'));
  };
  return (
    <button className="mic" onClick={play} title={state==='err'?'TTS unavailable':'replay aloud'}
      style={{ width: 22, height: 22, opacity: state==='playing'?1:.6, fontSize: 12, lineHeight: 1, color: state==='err'?'var(--amber)':undefined }}>
      {state==='playing' ? '◼' : '🔊'}
    </button>
  );
}

function Conversation({ messages, thinking, onStop, onProv, onArtifactSaved, exportAllowed = false, messageActionsAllowed = false, messageScope, lang, t }: any) {
  const endRef = useRef(null);
  const [action, setAction] = useState<{ kind: 'remember' | 'task' | 'teach' | 'obsidian'; message: any; scope: string; opener: HTMLElement; credential?: string } | null>(null);
  const [meshReview, setMeshReview] = useState<{ source: string; message: any; scope: string; opener: HTMLElement } | null>(null);
  const meshClose = useRef<HTMLButtonElement>(null);
  const visibleMeshReview = meshReview && exportAllowed && meshReview.scope === messageScope && messages.includes(meshReview.message) ? meshReview : null;
  useEffect(() => { if (meshReview && !visibleMeshReview) setMeshReview(null); }, [meshReview, visibleMeshReview]);
  useEffect(() => { if (visibleMeshReview) meshClose.current?.focus(); }, [visibleMeshReview]);
  const [noteReceipts, setNoteReceipts] = useState<{ message: any; scope: string; receipt: NoteReceipt; target: Target; credential: string }[]>([]);
  const [pendingNotes, setPendingNotes] = useState<{ message: any; scope: string; submission: NoteSubmission; credential: string }[]>([]);
  const selected = action && messageActionsAllowed && action.scope === messageScope && messages.includes(action.message)
    && (action.kind !== 'remember' || action.credential === noteCredential()) ? action : null;
  useEffect(() => {
    if (action && !selected) setAction(null);
  }, [action, selected]);
  useEffect(() => {
    const valid = (entry: { message: any; scope: string; credential: string }) =>
      messageActionsAllowed && entry.scope === messageScope && entry.credential === noteCredential() && messages.includes(entry.message);
    setNoteReceipts(previous => previous.every(valid) ? previous : previous.filter(valid));
    setPendingNotes(previous => previous.every(valid) ? previous : previous.filter(valid));
  }, [messageScope, messageActionsAllowed, messages]);
  useEffect(() => onOwnerSession(() => {
    setAction(previous => previous?.kind === 'remember' && previous.credential !== noteCredential() ? null : previous);
    setNoteReceipts(previous => previous.filter(entry => entry.credential === noteCredential()));
    setPendingNotes(previous => previous.filter(entry => entry.credential === noteCredential()));
  }), []);
  useEffect(()=>{ if(endRef.current) endRef.current.scrollTop = endRef.current.scrollHeight; }, [messages, thinking]);
  // Explicit save-to-artifacts (never auto): only completed, non-system, non-empty
  // assistant replies get the control — while a turn streams, its (last) message is
  // still in flight — and only on surfaces that opt in by passing onArtifactSaved
  // (the cockpit does; ChatMode doesn't).
  const canSave = (m, i) => !!onArtifactSaved && !!m.text && m.who !== 'system'
    && !(thinking && i === messages.length - 1);
  const completedReply = (m, i) => m.role === 'agent' && typeof m.text === 'string' && !!m.text.trim() && m.who !== 'system'
    && (!m._turnId || m._complete) && !(thinking && !m._turnId && i === messages.length - 1);
  const canExport = (m, i) => exportAllowed && completedReply(m, i);
  const latestMesh = messages.reduce((last, m, i) => {
    const source = canExport(m, i) && blenderSourceFromReply(m.text);
    return source ? { message: m, source } : last;
  }, null as { message: any; source: string } | null);
  const taskButton = (message) => <button type="button" className="tool-btn"
    onClick={e => setAction({ kind: 'task', message, scope: messageScope, opener: e.currentTarget })}>
    {lang === 'ro' ? 'Creează sarcină' : 'Create task'}</button>;
  /* The transcript is `overflow-y:auto` (styles.css `.convo`), so it is a scrollable
     region — and a scrollable region a keyboard user cannot enter is a WCAG 2.1.1
     failure. It has no focusable children of its own: the ⧉/🔊 controls live on AGENT
     bubbles only, so a run of user turns with no reply (an unreachable model, an
     aborted turn) leaves the region overflowing with nothing to tab to. axe reports
     `serious · scrollable-region-focusable` in exactly that state.

     Two facts that are easy to conflate, so stated apart. (1) Chromium makes overflow
     scrollers focusable on its own, so an unfixed `.convo` IS tab-reachable there —
     measured, reached at the 39th Tab with `tabIndex === -1`, and at the 28th with the
     fix. That is why a tab-walk assertion proves nothing and e2e/a11y.spec.ts asserts
     the axe rule and `tabIndex` instead. (2) It does NOT mask the axe rule: Chromium's
     axe reports the violation on an overflowing unfixed transcript just as webkit does.
     Chromium was 0/3 in the nightly for the other reason — the existing scans run
     against an EMPTY transcript, where the rule cannot apply at all.

     `role="log"` is the ARIA APG role for a chat transcript and is what gives the
     focused region an accessible name (`aria-label` alone would sit on a `generic`
     element, which prohibits naming). It also makes the region `aria-live="polite"` by
     default. Known trade, only half of it measured: the `.thinking` block below is
     inside the region and its label churns several times per turn, so it carries an
     explicit `aria-live="off"`. Not addressed, and not measured with a real screen
     reader: the `GET /memory` rehydration (app.tsx) injects a whole restored transcript
     into an already-mounted live region, which an AT may announce in bulk. Scoping the
     live region to a messages-only wrapper is the fix if that turns out to matter — it
     is a DOM restructure inside a flex column, so it belongs in its own change. */
  return <>
    <div className="convo" ref={endRef} tabIndex={0} role="log"
         aria-label={(t && t.convoRegion) || 'Conversation transcript'}>
      {messages.map((m,i)=> m.role==='user'
        ? (
          <div className="msg user" key={i}>
            <div className="bubble">{m.text}{m.imageNames&&<div style={{fontSize:11,opacity:.7}}>Images: {m.imageNames.join(', ')}</div>}
              {(m.attachmentNames || m.vaultNames) && <ul aria-label={lang === 'ro' ? 'Surse atașate' : 'Attached sources'}>
                {(m.attachmentNames || m.vaultNames).map(name => <li key={name}>{name}</li>)}</ul>}
              {messageActionsAllowed && Array.isArray(m.boardSources) && !!m.boardSources.length &&
                <BoardSources key={messageScope} sources={m.boardSources} lang={lang}/>}</div>
            {messageActionsAllowed && typeof m.text === 'string' && m.text.trim() &&
              <div className="message-actions">
                <button type="button" className="tool-btn"
                  onClick={e => setAction({ kind: 'remember', message: m, scope: messageScope, opener: e.currentTarget, credential: noteCredential() })}>Remember message</button>
                {taskButton(m)}
              </div>}
          </div>
        ) : m.role==='vision' ? (
          <div className="msg agent" key={i}>
            <div className="mtag"><span className="who">VISION ANALYSIS</span><span className="ts">{m.ts}</span></div>
            <div className="bubble"><Bubble text={m.text} /></div>
            <div style={{fontSize:11,color:'var(--ink-2)'}}>{m.model} · {m.backend} · {m.destination} · {m.local?'loopback':'remote'}</div>
            {m.warning&&<div style={{fontSize:11,color:'var(--amber)'}}>{m.warning}</div>}
          </div>
        ) : (
          <div className="msg agent" key={i}>
            <div className="mtag">
              <span className="who">{(m.who||'jarvis').toUpperCase()}</span>
              <span className="role">{m.role_label||''}</span>
              <span className="ts">{m.ts||''}</span>
              {m.text && m.who!=='system' && (
                <span style={{marginLeft:'auto',display:'inline-flex',alignItems:'center',gap:5}}>
                  {canSave(m, i) && <SaveArtifactButton message={m} onSaved={onArtifactSaved} lang={lang} />}
                  {canExport(m, i) && <OfficeExportButton data={{ format: 'docx', text: m.text }} lang={lang} />}
                  {canExport(m, i) && blenderSourceFromReply(m.text) && <button type="button" className="tool-btn"
                    onClick={event => setMeshReview({ source: blenderSourceFromReply(m.text)!, message: m, scope: messageScope, opener: event.currentTarget })}>
                    {lang === 'ro' ? 'Revizuiește modelul Blender' : 'Review Blender model'}</button>}
                  <TtsButton text={m.text} lang={lang} />
                </span>
              )}
            </div>
            <TurnTools tools={m.tools} />
            <div className="bubble"><Bubble text={m.text} tableExport={canExport(m, i)} codeExport={canExport(m, i)} lang={lang} /></div>
            {m.who !== 'system' && <TurnToolActivity activity={m.toolActivity} lang={lang} />}
            {messageActionsAllowed && completedReply(m, i) && <div className="message-actions">
              {canExport(m, i) && <PhotoshopLayoutButton key={`${messageScope}/${m._turnId ?? m.text}`}
                text={m.text} lang={lang === 'ro' ? 'ro' : 'en'} />}
              {!m._unattributed && <button type="button" className="tool-btn" onClick={e => setAction({ kind: 'obsidian', message: m, scope: messageScope, opener: e.currentTarget })}>
                {lang === 'ro' ? 'Salvează în Obsidian' : 'Save to Obsidian'}</button>}
              {taskButton(m)}
              {!m._unattributed && <button type="button" className="tool-btn"
                onClick={e => setAction({ kind: 'teach', message: m, scope: messageScope, opener: e.currentTarget })}>{lang === 'ro' ? 'Învață abilitate' : 'Teach skill'}</button>
              }
            </div>}
            {messageActionsAllowed && (() => {
              const receipt = noteReceipts.find(entry => entry.message === m && entry.scope === messageScope && entry.credential === noteCredential())?.receipt;
              return receipt && <div role="status">{lang === 'ro' ? 'Salvat în Obsidian: ' : 'Saved to Obsidian: '}{receipt.relPath}
                {receipt.source && <> · <a href={obsidianOpenUri(receipt.source) || undefined}>
                  {lang === 'ro' ? 'Deschide în Obsidian' : 'Open in Obsidian'}</a></>}</div>;
            })()}
            <TurnApprovals ids={m.approvals} />
            {Array.isArray(m.prov?.models) && m.prov.models.length > 0 && (
              <button type="button" className="prov-chip" style={{background:'transparent',textAlign:'left',maxWidth:'100%',overflowWrap:'anywhere'}} onClick={()=>onProv(m.prov)}>
                <Icon d={ICONS.shield} size={12}/>
                <span>Models called: {m.prov.models.map(({provider,model})=>`${provider} / ${model}`).join(' · ')}</span>
              </button>
            )}
          </div>
        )
      )}
      {thinking && (
        /* aria-live="off" overrides the `role="log"` region above: the label cycles
           classify -> route -> gather -> synthesize within a single turn, and a polite
           live region would announce every step. The finished reply is the thing worth
           announcing, and it arrives as a `.msg.agent` addition. */
        <div className="thinking" aria-live="off">
          <div className="tl"><span className="ar">▸</span> {thinking.label}
            {thinking.route && <span className="route-pill">→ {thinking.route.join(' · ')}</span>}
            <span className="dots"><span></span><span></span><span></span></span>
            {onStop && (
              <button className="route-pill stop-gen" style={{ marginLeft: 'auto', cursor: 'pointer' }}
                      onClick={onStop} title="Stop generating" aria-label="Stop generating">■ stop</button>
            )}
          </div>
        </div>
      )}
    </div>
    {latestMesh && <div className="blender-review-launch"><button type="button" className="tool-btn"
      onClick={event => setMeshReview({ ...latestMesh, scope: messageScope, opener: event.currentTarget })}>
      {lang === 'ro' ? 'Revizuiește ultimul model Blender' : 'Review latest Blender model'}</button></div>}
    {selected?.kind === 'remember' && <RememberMessageDialog text={selected.message.text} opener={selected.opener} onClose={() => setAction(null)} />}
    {visibleMeshReview && createPortal(<div className="blender-review-overlay"><section className="blender-review-dialog" role="dialog" aria-modal="true"
      aria-label={lang === 'ro' ? 'Revizuiește modelul Blender' : 'Review Blender model'}
      onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); setMeshReview(null); visibleMeshReview.opener.focus(); }
        if (event.key === 'Tab') {
          const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
          if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons[buttons.length - 1]?.focus(); }
          else if (!event.shiftKey && document.activeElement === buttons[buttons.length - 1]) { event.preventDefault(); buttons[0]?.focus(); }
        }
      }}>
      <div className="blender-review-head"><strong>{lang === 'ro' ? 'Model Blender editabil' : 'Editable Blender model'}</strong>
        <button ref={meshClose} type="button" className="tool-btn" aria-label={lang === 'ro' ? 'Închide revizuirea modelului' : 'Close model review'}
          onClick={() => { setMeshReview(null); visibleMeshReview.opener.focus(); }}>×</button></div>
      <BlenderModel source={visibleMeshReview.source} lang={lang}/>
    </section></div>, document.body)}
    {selected?.kind === 'task' && <ChatTaskDialog text={selected.message.text} opener={selected.opener} lang={lang} onClose={() => setAction(null)} />}
    {selected?.kind === 'teach' && <TeachProcedureDialog message={selected.message} agent={selected.message.who || 'jarvis'} lang={lang} opener={selected.opener} onClose={() => setAction(null)} />}
    {selected?.kind === 'obsidian' && <ObsidianChatNote text={selected.message.text} lang={lang} opener={selected.opener}
      onClose={() => setAction(null)} onTarget={(target: Target | null) => {
        const matches = (value: Target) => !!target && value.id === target.id && value.vault === target.vault && value.inbox === target.inbox;
        setNoteReceipts(previous => previous.filter(entry => matches(entry.target)));
        if (target) setPendingNotes(previous => previous.filter(entry => matches(entry.submission.target)));
      }}
      initialSubmission={pendingNotes.find(entry => entry.message === selected.message && entry.scope === selected.scope &&
        entry.credential === noteCredential())?.submission || null}
      onSubmitted={(submission: NoteSubmission | null) => setPendingNotes(previous => [
        ...previous.filter(entry => entry.message !== selected.message),
        ...(submission ? [{ message: selected.message, scope: selected.scope, submission, credential: noteCredential() }] : []),
      ])}
      onSaved={(receipt: NoteReceipt, target: Target) => setNoteReceipts(previous => [
        ...previous.filter(entry => entry.message !== selected.message),
        { message: selected.message, scope: selected.scope, receipt, target, credential: noteCredential() },
      ])} />}
  </>;
}
/* H168 — agent text is Markdown, rendered by the one shared, React-only renderer
   (markdown.tsx): lists, fences, tables and http(s)/same-origin links render; raw HTML
   and any other link stay text; a single newline is a line break. Memoised on the
   text, so a streamed token re-parses only the bubble it lands in. The owner's own
   turns are shown as typed. */
const Bubble = React.memo(function Bubble({ text, tableExport = false, codeExport = false, lang }: { text: string; tableExport?: boolean; codeExport?: boolean; lang?: string }) {
  return <Markdown text={text} className="md md-inline" breaks
    tableExport={tableExport ? rows => <OfficeExportButton data={{ format: 'xlsx', rows }} lang={lang} /> : undefined}
    codeExport={codeExport ? (language, source, index) => blenderCodeExport(language, source, lang) || godotDownload(language, source, index, lang) : undefined} />;
});

/* ---- Cognition trace ---- */
function CognitionStream({ trace, t }) {
  if (!trace) {
    return (
      <div className="cog">
        <div className="cog-empty">
          <Icon d={ICONS.brain} size={34}/>
          <div className="big">{t.cogempty}</div>
          <div style={{fontFamily:'var(--font-mono)',fontSize:11,color:'var(--accent-light)'}}>{t.cogempty2}</div>
        </div>
      </div>
    );
  }
  const stages = trace.stages;
  return (
    <div className="cog">
      {stages.map((s,i)=>(
        <div key={i} className={'cog-stage '+(s.state||'')}>
          <div className="cog-rail">
            <div className="cog-node">{i+1}</div>
            {i<stages.length-1 && <div className="cog-line"></div>}
          </div>
          <div className="cog-content">
            <div className="cog-stage-name">{s.name}<span className="dur">{s.dur}</span></div>
            <div className="cog-stage-body">
              {s.body}
              {s.kind==='score' && (
                <div className="score-table">
                  {s.scores.map((sc,j)=>(
                    <div key={j} className={'score-row'+(sc.win?' win':'')}>
                      <span className="ag"><Glyph id={sc.id} size={12}/>{sc.id}</span>
                      <span className="score-bar"><i style={{width:`${sc.v*100}%`}}></i></span>
                      <span className="sc">{sc.v.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              )}
              {s.kind==='keywords' && (
                <div style={{marginTop:6}}>
                  {s.keywords.map((k,j)=><span key={j} className={'kwchip'+(k.anti?' anti':'')}>{k.w} · {k.s.toFixed(2)}</span>)}
                </div>
              )}
              {s.esc && <div className="esc-marker">⚠ {s.esc}</div>}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* build a trace from input text using COGNITION_SCORING */
function buildTrace(text){
  const SC = V2.COGNITION_SCORING;
  const low = text.toLowerCase();
  const hits = SC.filter(s => low.includes(s.keyword));
  const agentScore: Record<string, number> = {};
  hits.forEach(h => h.agents.forEach(a => { agentScore[a]=Math.max(agentScore[a]||0, h.weight); }));
  let scored = Object.entries(agentScore).map(([id,v])=>({id,v} as {id:string; v:number; win?:boolean})).sort((a,b)=>b.v-a.v);
  if (scored.length===0) scored=[{id:'jarvis',v:0.55}];
  scored = scored.slice(0,5);
  scored[0].win = true;
  const selected = scored.filter(s=>s.v>=0.6).map(s=>s.id);
  const sel = selected.length?selected:[scored[0].id];
  const kws = hits.length?hits.slice(0,6).map(h=>({w:h.keyword,s:h.weight})):[{w:'(general)',s:0.55}];
  const conf = scored[0].v;
  return {
    selected: sel, conf,
    stages:[
      { name:'CLASSIFY', dur:'12ms', kind:'keywords', keywords:kws, body:`Matched ${hits.length} routing keyword${hits.length===1?'':'s'} via keyword_match classifier.` },
      { name:'ROUTE', dur:'8ms', kind:'score', scores:scored, body:`Scored candidate agents. Routing to ${sel.map(s=>s.toUpperCase()).join(' + ')} (≥0.60 threshold).`, esc: conf<0.6?'Low confidence — escalating to Jarvis for direct handling.':null },
      { name:'GATHER', dur:'145ms', body:`Pulling context — plugin reads (calendar/gmail), KG recall, ${sel.length} agent contexts. 2 PII spans redacted by Ultron.` },
      { name:'SYNTHESIZE', dur:'890ms', body:`Nerva composed the reply locally · 234 tokens · 100% on-device, no cloud egress.` },
    ],
  };
}

/* segmented toggle for the voice settings popover */
function Seg({ cur, opts, on }) {
  return (
    <span style={{display:'inline-flex',gap:3}}>
      {opts.map(o=>(
        <button key={o.v} onClick={()=>on(o.v)}
          style={{padding:'3px 8px',borderRadius:6,border:'1px solid '+(cur===o.v?'var(--accent)':'var(--panel-line)'),background:cur===o.v?'var(--accent)':'transparent',color:cur===o.v?'#021a1f':'var(--ink-2)',fontFamily:'var(--font-mono)',fontSize:10,letterSpacing:'.04em',cursor:'pointer'}}>{o.l}</button>
      ))}
    </span>
  );
}

/* input bar — text + voice (mic toggles the useVoice loop; ⚙ opens voice settings) */
function InputBar({ onSubmit, mic, setMic, voice, cfg, onCfg, micMuted, motion, t, lang='en', demo=false, agent='jarvis', agents=[], recipientStatus='ready', sessionId='', selectedTurn=false, outcome, power, projectForChat, onProjectReviewed, boardResultForChat, onBoardResultReviewed, inspectBlend, turnActive=false, canContinue }: { onSubmit?: any; mic?: any; setMic?: any; voice?: any; cfg?: any; onCfg?: any; micMuted?: any; motion?: any; t?: any; lang?: string; demo?: boolean; agent?: string; agents?: ChatAgent[]; recipientStatus?: 'ready' | 'checking' | 'choose'; sessionId?: string; selectedTurn?: boolean; outcome?: TurnOutcome | null; power?: PowerState; projectForChat?: WorkshopRef | null; onProjectReviewed?: () => void; boardResultForChat?: BoardResultRef | null; onBoardResultReviewed?: () => void; inspectBlend?: React.RefObject<((file: File) => boolean) | null>; turnActive?: boolean; canContinue?: () => boolean }) {
  const [val,setVal]=useState('');
  const [blenderMode, setBlenderMode] = useState(false);
  const blenderRequest = blenderMode && val.trim() ? blenderMeshRequest(val) : '';
  const blenderTooLong = blenderRequest.length > 4096;
  const pickedSkill = useRef<{ command: string; agent: string; sessionId: string } | null>(null);
  const picked = pickedSkill.current;
  const typed = val.trimStart();
  const skillArgs = picked && (typed === picked.command || (typed.startsWith(picked.command) && /\s/.test(typed.charAt(picked.command.length))))
    ? typed.slice(picked.command.length) : null;
  const skillWarning = picked && skillArgs !== null ? skillDraftWarning(picked.command, skillArgs, lang) : '';
  useLayoutEffect(() => {
    if (!picked) return;
    if (skillArgs === null) { pickedSkill.current = null; return; }
    if (picked.agent !== agent || picked.sessionId !== sessionId || !selectedTurn) {
      pickedSkill.current = null;
      setVal(val.slice(0, val.length - typed.length) + skillArgs.replace(/^\s/, ''));
    }
  }, [picked, skillArgs, val, agent, sessionId, selectedTurn, typed]);
  const [sentCount,setSentCount]=useState(0);
  const [cfgOpen,setCfgOpen]=useState(false);
  const [directReplyScope,setDirectReplyScope]=useState('');
  const directReplyHelpId = useId();
  const recipientHintId = useId();
  const recipientHint = recipientStatus === 'checking'
    ? lang === 'ro' ? 'Verific agentul selectat…' : 'Checking the selected agent…'
    : lang === 'ro' ? 'Alege un agent disponibil înainte de a trimite.' : 'Choose an available agent before sending.';
  const draft=useComposerImages(val.trim(),agent,sessionId,selectedTurn);
  const vault = useVaultNotes(val.trim(), agent, sessionId, selectedTurn && !draft.enabled);
  const command = val.trim().startsWith('/');
  const office = useOfficeDocument(agent, sessionId, demo, draft.enabled || vault.open || command, lang);
  const [officeSending, setOfficeSending] = useState(false);
  const officeActive = !!office.file || !!office.status || office.attachments.length > 0;
  const officeReady = office.attachments.length > 0 && !office.busy && (!office.expanded || !!office.attachment);
  const [historyReference, setHistoryReference] = useState<{ reference: HistoryReference; role: 'user' | 'assistant'; scope: string } | null>(null);
  const historyScope = JSON.stringify([agent, sessionId, historyOwnerKey()]);
  const currentHistory = historyReference?.scope === historyScope ? historyReference : null;
  const [historySending, setHistorySending] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const canStartAttachment = selectedTurn && !demo && !command && !draft.enabled && !vault.open && !officeActive && !currentHistory;
  const boardResult = useBoardResult(agent, sessionId, canStartAttachment, lang);
  const boardInUse = boardResult.active || boardResult.reviewing || boardResult.busy;
  const boardCloudCapable = !['frigga', 'ultron', 'howard'].includes(agent.toLowerCase());
  const [boardCloudConsent, setBoardCloudConsent] = useState(false);
  const boardConsentNow = useRef(false);
  boardConsentNow.current = boardCloudConsent;
  useLayoutEffect(() => setBoardCloudConsent(false), [agent, sessionId, boardResult.staged]);
  useEffect(() => onOwnerSession(() => setBoardCloudConsent(false)), []);
  const choices = selectableChatAgents(agents, demo);
  const canCompare = canStartAttachment && !boardInUse && !vault.selected.length && choices.length >= 2;
  const [comparison, setComparison] = useState<{ question: string; opener: HTMLElement; agent: string; sessionId: string } | null>(null);
  const [historyOpener, setHistoryOpener] = useState<{ node: HTMLElement; scope: string } | null>(null);
  const historyUseCurrent = useRef({ scope: historyScope, allowed: false });
  historyUseCurrent.current = { scope: historyScope, allowed: recipientStatus === 'ready' && !turnActive && !historySending
    && !draft.enabled && !vault.selected.length && !officeActive && !boardInUse && !currentHistory };
  useLayoutEffect(() => { setHistoryReference(null); setHistoryOpener(null); setHistorySending(false); setHistoryError(''); }, [historyScope]);
  useEffect(() => onOwnerSession(() => { setHistoryReference(null); setHistoryOpener(null); setHistorySending(false); setHistoryError(''); }), []);
  const showComparison = comparison && canCompare && comparison.agent === agent && comparison.sessionId === sessionId;
  useLayoutEffect(() => { if (comparison && !showComparison) setComparison(null); }, [comparison, showComparison]);
  useLayoutEffect(() => {
    if (!inspectBlend) return;
    inspectBlend.current = file => {
      if (!canStartAttachment || boardInUse) return false;
      office.choose(file);
      return true;
    };
    return () => { inspectBlend.current = null; };
  }, [inspectBlend, canStartAttachment, boardInUse, office.choose]);
  const directReply = selectedTurn && !draft.enabled && !val.trim().startsWith('/') && directReplyScope === `${agent}\u0000${sessionId}`;
  const latestDraft = useRef({ val, directReply, onSubmit, scope: historyScope });
  latestDraft.current = { val, directReply, onSubmit, scope: historyScope };
  useLayoutEffect(() => { setDirectReplyScope(''); }, [agent, sessionId, selectedTurn, draft.enabled, val.trim().startsWith('/')]);
  const composerInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!projectForChat || !selectedTurn || draft.enabled || command || boardInUse || currentHistory || officeActive) return;
    vault.reviewProject(projectForChat.path);
    composerInput.current?.focus();
    onProjectReviewed?.();
  }, [projectForChat, selectedTurn, draft.enabled, command, boardInUse, officeActive, currentHistory]);
  useEffect(() => {
    if (!boardResultForChat || !canStartAttachment) return;
    boardResult.open(boardResultForChat);
    onBoardResultReviewed?.();
  }, [boardResultForChat, canStartAttachment]);
  const fileInput=useRef<HTMLInputElement>(null);
  const refs=useContextRefs(val);   // H579: @file: completion
  const submit=()=>{
    if (recipientStatus !== 'ready') return;
    if (officeSending || vault.busy || boardResult.busy || boardResult.reviewing || skillWarning) return;
    if (blenderMode) {
      if (!canStartAttachment || boardInUse || !val.trim() || blenderTooLong) return;
      if ((directReply ? onSubmit(blenderRequest, undefined, undefined, true) : onSubmit(blenderRequest)) === false) return;
      setBlenderMode(false); setDirectReplyScope(''); setVal(''); setSentCount(n => n + 1); return;
    }
    if (currentHistory) {
      if (currentHistory.scope !== JSON.stringify([agent, sessionId, historyOwnerKey()])) {
        setHistoryReference(null); setHistoryError(lang === 'ro' ? 'Accesul s-a schimbat. Caută și revizuiește sursa din nou.' : 'Owner access changed. Search and review the source again.');
        return;
      }
      if (!val.trim() || historySending || turnActive) return;
      const submitted = val.trim();
      const selected = currentHistory;
      setHistorySending(true); setHistoryError('');
      const accepted = onSubmit(submitted, undefined, undefined, directReply, {
        reference: selected.reference, role: selected.role,
        onResult: (ok: boolean, reason?: string) => {
          if (selected.scope !== historyUseCurrent.current.scope || selected.scope !== JSON.stringify([agent, sessionId, historyOwnerKey()])) return;
          setHistorySending(false);
          if (ok) { setHistoryReference(null); setVal(current => current === val ? '' : current); setDirectReplyScope(''); setSentCount(n => n + 1); }
          else setHistoryError(reason || (lang === 'ro' ? 'Sursa nu a fost acceptată. Revizuiește pasajul și încearcă din nou.' : 'The source was not accepted. Review the passage and try again.'));
        },
      });
      if (accepted === false) { setHistorySending(false); setHistoryError(lang === 'ro' ? 'Mesajul nu a fost acceptat. Ciorna și pasajul sunt păstrate.' : 'The message was not accepted. Your draft and passage are still here.'); }
      return;
    }
    if (boardResult.active) {
      if (boardCloudCapable && !boardCloudConsent) return;
      void boardResult.send(async references => {
        const latest = latestDraft.current;
        if (latest.val !== val || latest.directReply !== directReply || !latest.onSubmit ||
            (boardCloudCapable && !boardConsentNow.current)) return false;
        const message = val.trim() || (references.length === 1
          ? (lang === 'ro' ? 'Rezumă rezultatul sarcinii.' : 'Summarize this task result.')
          : (lang === 'ro' ? 'Compară rezultatele și indică sursa fiecărei concluzii.' : 'Compare the task results and identify the source of each conclusion.'));
        const accepted = await latest.onSubmit(message, undefined, undefined, directReply,
          { boardReferences: references, allowBoardCloud: boardCloudCapable && boardConsentNow.current });
        if (accepted === false) return false;
        if (latestDraft.current.scope === latest.scope && latestDraft.current.val === val && latestDraft.current.directReply === directReply) {
          setDirectReplyScope(''); setBoardCloudConsent(false); setVal(''); setSentCount(n => n + 1);
        }
        return true;
      });
      return;
    }
    if (officeActive) {
      if (!officeReady || draft.enabled || vault.open || command || !office.readyToSend()) return;
      const passages = office.attachments;
      const message = val.trim() || (passages.length > 1
        ? (lang === 'ro' ? 'Compară pasajele și indică documentul pentru fiecare constatare.' : 'Compare the passages and identify the document for each finding.')
        : (lang === 'ro' ? 'Analizează acest pasaj.' : 'Review this passage.'));
      const finish = (accepted?: boolean) => {
        setOfficeSending(false);
        if (accepted === false || latestDraft.current.scope !== historyScope) return;
        office.clear(); setDirectReplyScope(''); setVal(current => current === val ? '' : current);
        setSentCount(n => n + 1);
      };
      if (office.kind === 'docx' || office.kind === 'xlsx') {
        setOfficeSending(true);
        const accepted = onSubmit(message, undefined, passages, directReply, { awaitAdmission: true });
        if (accepted?.then) void accepted.then(finish, () => finish(false));
        else finish(accepted);
      } else {
        finish(directReply ? onSubmit(message, undefined, passages, true) : onSubmit(message, undefined, passages));
      }
      return;
    }
    if (vault.selected.length) {
      void vault.lookup((notes, message) => {
        if ((directReply ? onSubmit(message, undefined, notes, true) : onSubmit(message, undefined, notes)) === false) return false;
        setDirectReplyScope('');
        setVal(''); setSentCount(n=>n+1);
        return true;
      });
      return;
    }
    if(draft.enabled){const vision=draft.submission();if(!vision)return;
      if(onSubmit(val.trim()||'Describe these images.',vision)===false)return;
      draft.clear();setVal('');setSentCount(n=>n+1);return;}
    if(!val.trim())return;if((directReply ? onSubmit(val.trim(), undefined, undefined, true) : onSubmit(val.trim()))===false)return;vault.clear();setDirectReplyScope('');setVal('');setSentCount(n=>n+1);
  };
  const showPill = voice && (voice.active || voice.error);
  const label = voice && voice.error ? voice.error
    : voice && voice.status==='listening' ? 'listening…'
    : voice && voice.status==='transcribing' ? 'transcribing…'
    : voice && voice.status==='speaking' ? 'speaking…' : 'voice on';
  const row = (lbl,node) => (
    <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:12,padding:'4px 0'}}>
      <span style={{color:'var(--ink-2)',fontFamily:'var(--font-mono)',fontSize:10,letterSpacing:'.1em'}}>{lbl}</span>{node}
    </div>
  );
  return (
    <div style={{position:'relative',display:'flex',flexDirection:'column',minHeight:0,flexShrink:1}} onPaste={boardInUse || currentHistory || officeActive ? undefined : draft.onPaste} onDrop={boardInUse || currentHistory || officeActive ? event => event.preventDefault() : draft.onDrop} onDragOver={event=>{if(Array.from(event.dataTransfer.types).includes('Files'))event.preventDefault();}}>
      <ComposerImages draft={draft} disabled={!!currentHistory}/>
      {officeSending
        ? <p role="status">{lang === 'ro' ? 'Se trimit pasajele selectate…' : 'Sending selected passages…'}</p>
        : <><OfficeReview draft={office}/><OfficeAttached draft={office}/></>}
      <BoardResultReview draft={boardResult}/>
      {boardResult.active && boardCloudCapable && <label className="board-cloud-consent">
        <input type="checkbox" checked={boardCloudConsent} disabled={boardResult.busy} onChange={event => setBoardCloudConsent(event.target.checked)}/>
        {lang === 'ro' ? 'Permit trimiterea pasajelor revizuite către furnizorul cloud al acestui agent.' : 'Allow these reviewed passages to reach this agent’s cloud provider.'}
      </label>}
      {boardResult.active && val.includes('@file:') && <p role="status">{lang === 'ro'
        ? 'Fișierele @file și rezultatele împart limita de 128.000 de octeți. Dacă nu încap toate, selectează pasaje mai scurte înainte de trimitere.'
        : 'Files referenced with @file and task results share 128,000 bytes. If they do not fit together, select shorter passages before sending.'}</p>}
      {showComparison && <CompareAgentsDialog question={comparison.question} agent={agent} agents={choices}
        lang={lang} opener={comparison.opener} onClose={() => setComparison(null)}/>}
      {historyOpener?.scope === historyScope && <ChatHistorySearch lang={lang} opener={historyOpener.node} onClose={() => setHistoryOpener(null)}
        hasDraft={!!val.trim()} hasAttachment={draft.enabled || !!vault.selected.length || officeActive || boardInUse || !!currentHistory}
        turnActive={turnActive} canContinue={canContinue} recipient={agent}
        canUse={() => historyOpener.scope === historyUseCurrent.current.scope && historyUseCurrent.current.allowed}
        onUse={(reference, role) => {
          if (historyOpener.scope !== historyUseCurrent.current.scope || !historyUseCurrent.current.allowed) return false;
          setHistoryReference({ reference, role, scope: historyScope }); setHistoryError(''); return true;
        }}/>}
      {currentHistory && <div className="chat-history-selected" role="status"><strong>{historySourceLabel({ ...currentHistory.reference, role: currentHistory.role })}</strong>
        <pre>{currentHistory.reference.excerpt}</pre><button type="button" className="tool-btn" disabled={historySending}
          onClick={() => { setHistoryReference(null); setHistoryError(''); }}>{lang === 'ro' ? 'Elimină pasajul' : 'Remove passage'}</button></div>}
      {historyError && <p role="alert">{historyError} <button type="button" className="tool-btn"
        onClick={event => { setHistoryReference(null); setHistoryOpener({ node: event.currentTarget, scope: historyScope }); setHistoryError(''); }}>
        {lang === 'ro' ? 'Revizuiește din nou' : 'Review again'}</button></p>}
      {boardResultForChat && !canStartAttachment && <p role="status">
        {lang === 'ro' ? 'Încheie ciorna curentă pentru a deschide rezultatul sarcinii.' : 'Finish or clear this draft to review the task result.'}
        <button type="button" className="tool-btn" onClick={onBoardResultReviewed}>{lang === 'ro' ? 'Închide' : 'Dismiss'}</button></p>}
      {projectForChat && (draft.enabled || command || boardInUse || currentHistory) &&
        <p role="status">Finish or clear this draft to review the saved project in a text message.
          <button type="button" className="tool-btn" onClick={onProjectReviewed}>Dismiss</button></p>}
      <VaultNoteReview draft={vault}/>
      {skillWarning && <p role="status">{skillWarning}</p>}
      {recipientStatus !== 'ready' && <p id={recipientHintId} role="status" style={{color:'var(--amber)',fontSize:11}}>{recipientHint}</p>}
      {showPill && (
        <div style={{display:'flex',alignItems:'center',gap:8,padding:'5px 10px',marginBottom:6,borderRadius:8,fontFamily:'var(--font-mono)',fontSize:11,letterSpacing:'.04em',background:'rgba(0,0,0,.18)',border:'1px solid var(--panel-line)',color:voice.error?'var(--amber)':'var(--accent-light)'}}>
          {!voice.error && <VoiceOrb status={voice.status} level={voice.level||0} motion={motion} density="compact" showLabel={false} className="vorb-inline" />}
          <span style={{flex:'none'}}>{voice.error ? '⚠ ' : ''}{label}</span>
          {/* H247: another surface on this machine holds the microphone — the owner may take it. */}
          {voice.error && voice.micHolder && typeof voice.takeOver === 'function' && (
            <button className="tool-btn" style={{padding:'0 6px',fontSize:10}} onClick={() => voice.takeOver()}
              aria-label={`take the microphone from ${voice.micHolder}`}>take over</button>
          )}
          {!voice.error && voice.status==='listening' && (
            <span style={{flex:1,height:4,borderRadius:4,background:'var(--panel-line)',overflow:'hidden'}}>
              <span style={{display:'block',height:'100%',width:Math.min(100,Math.round((voice.level||0)*400))+'%',background:'var(--green)',transition:'width .08s'}}/>
            </span>
          )}
          {!voice.error && voice.transcript && <span style={{color:'var(--ink-2)',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis',maxWidth:220}}>“{voice.transcript}”</span>}
        </div>
      )}
      {cfgOpen && cfg && onCfg && (
        <div style={{position:'absolute',bottom:'100%',right:0,marginBottom:8,zIndex:30,minWidth:262,padding:'10px 12px',borderRadius:10,background:'rgba(10,18,24,.98)',border:'1px solid var(--panel-line)',boxShadow:'0 10px 30px rgba(0,0,0,.45)'}}>
          <div style={{color:'var(--accent-light)',fontFamily:'var(--font-mono)',fontSize:10,letterSpacing:'.14em',marginBottom:6}}>VOICE</div>
          {row('MODE', <Seg cur={cfg.mode} opts={[{v:'hands-free',l:'HANDS-FREE'},{v:'ptt',l:'PUSH-TO-TALK'}]} on={(v)=>onCfg({mode:v})} />)}
          {row('SPEAK', <Seg cur={cfg.tts} opts={[{v:'server',l:'SERVER'},{v:'browser',l:'LOCAL'},{v:'off',l:'OFF'}]} on={(v)=>onCfg({tts:v})} />)}
          {row('LANG', <Seg cur={cfg.lang} opts={[{v:'auto',l:'AUTO'},{v:'ro',l:'RO'},{v:'en',l:'EN'}]} on={(v)=>onCfg({lang:v})} />)}
          {row('BARGE-IN', <Seg cur={cfg.barge||'off'} opts={[{v:'off',l:'OFF'},{v:'on',l:'ON'}]} on={(v)=>onCfg({barge:v})} />)}
          {cfg.barge==='on' && <div style={{marginTop:4,color:'var(--ink-2)',fontSize:9,fontFamily:'var(--font-mono)'}}>experimental — talk over the reply to interrupt; needs echo cancellation</div>}
          {voice && voice.caps && voice.caps.stt===false && <div style={{marginTop:6,color:'var(--amber)',fontSize:10,fontFamily:'var(--font-mono)'}}>local STT not installed — pip install faster-whisper</div>}
          <MicLeases />
        </div>
      )}
      <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple aria-label="Attach images" style={{display:'none'}} onChange={event=>{if(!currentHistory)draft.addFiles(Array.from(event.target.files||[]));event.target.value='';}}/>
      {selectedTurn && <div className="direct-reply-option">
        {!demo && <button type="button" aria-haspopup="dialog" onClick={event => setHistoryOpener({ node: event.currentTarget, scope: historyScope })}>
          {lang === 'ro' ? 'Caută în conversații' : 'Search chat history'}
        </button>}
        <button type="button" aria-pressed={directReply} disabled={draft.enabled || val.trim().startsWith('/')} aria-describedby={directReplyHelpId}
          onClick={()=>setDirectReplyScope(directReply ? '' : `${agent}\u0000${sessionId}`)}>{t?.directReply || 'Direct reply'}</button>
        <span id={directReplyHelpId}>{t?.directReplyHelp || 'Ask supported models to skip extended thinking for this message'}</span>
        {canCompare && <button type="button" aria-haspopup="dialog" disabled={!val.trim()}
          onClick={event => setComparison({ question: val.trim(), opener: event.currentTarget, agent, sessionId })}>
          {lang === 'ro' ? 'Compară agenții' : 'Compare agents'}
        </button>}
      </div>}
      {selectedTurn && !demo && <div className="blender-composer-option">
        <button type="button" className="tool-btn" aria-pressed={blenderMode}
          disabled={!blenderMode && (!canStartAttachment || boardInUse || !!vault.selected.length)}
          onClick={() => setBlenderMode(value => !value)}>{lang === 'ro' ? 'Creează model Blender editabil' : 'Make editable Blender model'}</button>
        <span>{lang === 'ro' ? 'Folosește descrierea ta pentru geometrie editabilă. Răspunsul trebuie să conțină cod OBJ; vei revizui modelul înainte de descărcare.'
          : 'Use your description for editable geometry. The reply needs OBJ code; you will review the model before download.'}</span>
        {blenderMode && <details><summary>{lang === 'ro' ? 'Revizuiește instrucțiunea trimisă' : 'Review instruction to send'}</summary>
          <pre>{blenderRequest || (lang === 'ro' ? 'Scrie o descriere în câmpul de mesaj.' : 'Write a description in the message field.')}</pre></details>}
        {blenderMode && blenderTooLong && <p role="alert">{lang === 'ro' ? 'Instrucțiunea depășește 4.096 de caractere. Scurtează descrierea sau dezactivează modul Blender.'
          : 'The instruction exceeds 4,096 characters. Shorten your description or turn off Blender mode.'}</p>}
      </div>}
      <div className="inputbar">
        <button className="mic" aria-label="Choose images" title="Attach images" disabled={boardInUse || officeActive || !!currentHistory} onClick={()=>fileInput.current?.click()}>▧</button>
        <OfficeButton draft={office} disabled={officeSending || demo || draft.enabled || vault.open || command || boardInUse || !!currentHistory}/>
        {selectedTurn && !draft.enabled && <button className="vault-trigger" type="button"
          aria-label="Find vault notes" title="Find Obsidian notes for this message" aria-expanded={vault.open}
          disabled={!val.trim() || command || officeActive || boardInUse || !!currentHistory} onClick={() => vault.open ? vault.clear() : void vault.lookup()}>
          <Icon d={ICONS.memory} size={16}/> Vault
        </button>}
        {selectedTurn && !demo && !draft.enabled && <button ref={boardResult.trigger} type="button" className="vault-trigger"
          aria-label={lang === 'ro' ? 'Atașează rezultatul unei sarcini' : 'Attach board result'}
          disabled={!canStartAttachment || boardResult.busy} onClick={() => boardResult.open()}>
          {lang === 'ro' ? 'Rezultat sarcină' : 'Board result'}
        </button>}
        {selectedTurn && !draft.enabled && !boardInUse && <ComposerSkills key={`${agent}:${sessionId}:${sentCount}`} agent={agent} draft={val} lang={lang}
          onInsert={(command, isSkill) => {
            pickedSkill.current = isSkill ? { command, agent, sessionId } : null;
            setVal(command + ' ' + val); composerInput.current?.focus();
          }}/>}
        <span className="pre">▸</span>
        <span className="chan">{t.channel}</span>
        <div className="field" style={{position:'relative'}}>
          <ContextRefHints items={refs} onPick={ref=>setVal(acceptRef(val,ref))}/>
          <input ref={composerInput} data-composer="1" data-anchor="composer" value={val} onChange={e=>setVal(e.target.value)} placeholder={voice && voice.active ? (cfg && cfg.mode==='ptt' ? 'listening — speak now' : 'listening — just speak (or type)') : t.placeholder}
            onKeyDown={e=>{ if(e.key==='Tab'&&refs.length){e.preventDefault();setVal(acceptRef(val,refs[0].ref));return;} if(e.key==='Enter') submit(); }}/>
          <button className={'mic'+(mic?' on':'')} onClick={()=>setMic && setMic()}
            title={micMuted ? 'mic muted — unmute NERVA' : (voice && voice.supported===false ? 'voice not supported in this browser' : (cfg && cfg.mode==='ptt' ? 'push-to-talk' : 'hands-free voice'))}
            style={micMuted?{opacity:.4}:undefined}><Icon d={ICONS.mic} size={15}/></button>
          {cfg && onCfg && <button className="mic" onClick={()=>setCfgOpen(o=>!o)} title="voice settings" style={{color:cfgOpen?'var(--accent-light)':'var(--ink-2)',fontSize:13,lineHeight:1}}>⚙</button>}
        </div>
        <button className="transmit" aria-describedby={recipientStatus === 'ready' ? undefined : recipientHintId} disabled={recipientStatus !== 'ready' || !!skillWarning || officeSending || vault.busy || boardResult.busy || boardResult.reviewing || historySending || (boardResult.active && boardCloudCapable && !boardCloudConsent) || (blenderMode && (!val.trim() || blenderTooLong || !canStartAttachment || boardInUse || !!vault.selected.length)) || (!!currentHistory && !val.trim()) || (draft.enabled&&!draft.ready) || (officeActive && !officeReady)} onClick={submit}><Icon d={ICONS.send} size={13}/>{t.transmit}</button>
      </div>
      <StatusStrip outcome={outcome} power={power} />
    </div>
  );
}

/* P2 — map the real /api/cognition snapshot onto the 4-stage trace visual */
function gatherBody(cog){
  const tr = Array.isArray(cog && cog.trace) ? cog.trace : [];
  const steps = tr.map(s => s.step || s.name || s.stage).filter(Boolean);
  return steps.length ? `Context gathered \u00b7 ${steps.join(' \u2192 ')}.` : 'Context gathered \u2014 plugin reads + memory recall.';
}
function traceFromCognition(cog, text){
  if (!cog || (!cog.scoring && !cog.decision)) return buildTrace(text);
  const scoring = Array.isArray(cog.scoring) ? cog.scoring : [];
  const dec = cog.decision || {};
  const sel = Array.isArray(dec.agents_selected) && dec.agents_selected.length ? dec.agents_selected : ['jarvis'];
  const timing = dec.timing || {};
  const alts = Array.isArray(dec.alternatives) ? dec.alternatives : [];
  let scores = alts.map(a => ({ id: a.id || a.agent || a.name || String(a), v: +(a.score != null ? a.score : a.confidence != null ? a.confidence : a.weight != null ? a.weight : 0) }));
  if (!scores.length) scores = sel.map((id, i) => ({ id, v: i === 0 ? +(dec.confidence != null ? dec.confidence : 0.7) : 0.4 }));
  scores.forEach(s => { if (sel.indexOf(s.id) >= 0) s.win = true; });
  if (!scores.some(s => s.win) && scores[0]) scores[0].win = true;
  scores = scores.slice(0, 6);
  const kws = scoring.length ? scoring.slice(0, 6).map(s => ({ w: s.keyword, s: +(s.weight != null ? s.weight : 0.5) })) : [{ w: '(general)', s: 0.55 }];
  const conf = +(dec.confidence != null ? dec.confidence : (scores[0] ? scores[0].v : 0.6));
  return {
    selected: sel, conf,
    stages: [
      { name: 'CLASSIFY', dur: (timing.classify != null ? timing.classify : 0) + 'ms', kind: 'keywords', keywords: kws, body: `Matched ${scoring.length} routing keyword${scoring.length === 1 ? '' : 's'} via ${dec.source || 'router'}.` },
      { name: 'ROUTE', dur: (timing.route != null ? timing.route : 0) + 'ms', kind: 'score', scores, body: `Routing to ${sel.map(s => String(s).toUpperCase()).join(' + ')} \u00b7 source ${dec.source || '\u2014'}.`, esc: conf < 0.6 ? 'Low confidence \u2014 Nerva handling directly.' : null },
      { name: 'GATHER', dur: '\u2014', body: gatherBody(cog) },
      { name: 'SYNTHESIZE', dur: (timing.total != null ? timing.total : 0) + 'ms', body: 'Reply composed on-device \u00b7 streamed token-by-token.' },
    ],
  };
}

export { Conversation, CognitionStream, buildTrace, traceFromCognition, InputBar, Bubble };
