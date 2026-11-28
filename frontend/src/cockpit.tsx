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
import { playTts } from './api/actions';
import { SaveArtifactButton } from './artifacts';
import { VoiceOrb } from './orb';
import { Markdown } from './markdown';
import { godotDownload } from './godot-download';
import { BlenderModel, blenderCodeExport, blenderMeshRequest, blenderSourceFromReply } from './blender-export';
import './blender-export.css';
import { OfficeExportButton } from './office-export';
import { PhotoshopLayoutButton } from './photoshop-layout';
import { TurnApprovals } from './turn-tools';
import { MicLeases } from './mic-leases';
import { StatusStrip, type TurnOutcome } from './turn-outcome';
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
import { LABEL } from './theme/type';
import { isLocalOnlyAgent } from './signals/agents-policy';
import { apiPost } from './api/client';
import { cloudHistoryPreview, type CloudHistoryPreview } from './cloud-history';
import type { TabTurn } from './signals/types';
import { fmt, plural } from './frame/strings';
import { TalkMenu } from './home/talk/TalkMenu';
import { RecipientPicker, agentDisplayName, recipientRefusalText } from './home/talk/RecipientPicker';
import { ComposerMode, type ApprovalModeInput } from './home/talk/ComposerMode';
import { talkStrings } from './home/talk/strings';
import type { RecipientHold, RecipientRefusal, RecipientSwitch, RecipientSwitchDropped, TalkMessage, TalkVariant } from './home/talk/types';
import { WorkingReply, PendingReply } from './home/talk/WorkingReply';
import { ReplyFootnote } from './home/talk/ReplyFootnote';
import { ReplyActions, OwnerActions } from './home/talk/ReplyActions';
import { RecalledFactSourceDialog, mayFindSavedSource } from './home/talk/RecalledFactSourceDialog';
import { Mark } from './frame/kit';
import './home/talk/talk.css';

/** The hub refuses a chat message longer than this (agents/web.py ChatRequest.message). */
const MAX_MESSAGE = 4096;
/** …and an image question longer than this (agents/core/routers/composer_vision.py, every route's `prompt`). */
const MAX_IMAGE_PROMPT = 4000;
/** The composer shows its count from here on. */
const COUNT_FROM = 3500;

/* Per-message TTS replay (🔊) — POST /tts {text,lang} → audio. Honest states: while
   speaking shows ◼ (stop is best-effort via re-click), errors fall back silently to
   the icon. voice.ts owns the live mic loop; this is just on-demand playback of a
   single past reply, which the prototype was missing. */
function TtsButton({ text, lang, words }: { text: string; lang?: string; words: { idle: string; playing: string; failed: string } }) {
  const [state, setState] = useState('idle'); // idle | playing | err
  const play = () => {
    if (state === 'playing' || !text) return;
    setState('playing');
    playTts(text, lang || 'en').then(() => setState('idle')).catch(() => setState('err'));
  };
  // The reply actions name the control in words ("Read aloud").
  return (
    <button type="button" className="n-acts__btn" onClick={play} data-state={state}>
      {state === 'playing' ? words.playing : state === 'err' ? words.failed : words.idle}
    </button>
  );
}

/* The transcript. Today's props, logic and dialogs, plus what the Ledger's conversation register
   passes (all optional; ConversationProps in home/talk/types.ts is unchanged):
     variant          set by TalkRegister ('home' | 'chat' | 'floating'; 'home' when left out): the
                      floating window's approval slips say to sign in the main window. The classic
                      `.convo` bubbles were deleted with ChatMode at the stage 5 cleanup
                      (PHASE_B_PLAN.md §9.3, §8.3): every transcript is the Ledger's.
     turns            this tab's in-flight turns: a reply whose _turnId is here is drawn as a
                      working reply; one that left it (stopped) is drawn as written so far
     agents           names for the agents who reply
     outcome, power   App's outcome of its newest turn: that turn's footnote and "Turn details"
                      (the old status strip under the composer), drawn only on that turn's reply
     outcomeTurnId    the turn `outcome` belongs to, when App says so (null: none drawn)
     awaitingAnswer   a mid-turn question waits for the owner ("Waiting for your answer"): the
                      turn id that asked, or true (drawn only when one turn is in flight) */
function Conversation({ messages, thinking, onStop, onProv, onArtifactSaved, exportAllowed = false, messageActionsAllowed = false, messageScope, sessionId, agent, lang, t,
  variant = 'home', turns = [], agents = [], outcome = null, outcomeTurnId, power, awaitingAnswer = false }: any) {
  const endRef = useRef(null);
  const [action, setAction] = useState<{ kind: 'remember' | 'task' | 'teach' | 'obsidian' | 'saved-source'; message: any; scope: string; opener: HTMLElement; credential?: string } | null>(null);
  const [sourceAllowed, setSourceAllowed] = useState(mayFindSavedSource);
  const [meshReview, setMeshReview] = useState<{ source: string; message: any; scope: string; opener: HTMLElement } | null>(null);
  const meshClose = useRef<HTMLButtonElement>(null);
  const visibleMeshReview = meshReview && exportAllowed && meshReview.scope === messageScope && messages.includes(meshReview.message) ? meshReview : null;
  useEffect(() => { if (meshReview && !visibleMeshReview) setMeshReview(null); }, [meshReview, visibleMeshReview]);
  useEffect(() => { if (visibleMeshReview) meshClose.current?.focus(); }, [visibleMeshReview]);
  const [noteReceipts, setNoteReceipts] = useState<{ message: any; scope: string; receipt: NoteReceipt; target: Target; credential: string }[]>([]);
  const [pendingNotes, setPendingNotes] = useState<{ message: any; scope: string; submission: NoteSubmission; credential: string }[]>([]);
  const selected = action && messageActionsAllowed && action.scope === messageScope && messages.includes(action.message)
    && (action.kind !== 'remember' || action.credential === noteCredential())
    && (action.kind !== 'saved-source' || (action.credential === historyOwnerKey() && sourceAllowed && mayFindSavedSource())) ? action : null;
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
    setSourceAllowed(mayFindSavedSource());
    setAction(previous => previous?.kind === 'saved-source' ? null : previous);
    setAction(previous => previous?.kind === 'remember' && previous.credential !== noteCredential() ? null : previous);
    setNoteReceipts(previous => previous.filter(entry => entry.credential === noteCredential()));
    setPendingNotes(previous => previous.filter(entry => entry.credential === noteCredential()));
  }), []);
  useEffect(() => {
    const changed = (event: StorageEvent) => {
      if (event.key === 'hud.admin_token' || event.key === 'hud.user_token') {
        setSourceAllowed(mayFindSavedSource());
        setAction(previous => previous?.kind === 'saved-source' ? null : previous);
      }
    };
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, []);
  useEffect(()=>{ if(endRef.current) endRef.current.scrollTop = endRef.current.scrollHeight; }, [messages, thinking]);
  // Explicit save-to-artifacts (never auto): only completed, non-system, non-empty
  // assistant replies get the control — while a turn streams, its (last) message is
  // still in flight — and only on surfaces that opt in by passing onArtifactSaved
  // (App's conversation register does; its demo does not).
  const canSave = (m, i) => !!onArtifactSaved && !!m.text && m.who !== 'system'
    && !(thinking && i === messages.length - 1);
  const completedReply = (m, i) => m.role === 'agent' && typeof m.text === 'string' && !!m.text.trim() && m.who !== 'system'
    && (!m._turnId || m._complete) && !(thinking && !m._turnId && i === messages.length - 1);
  const canExport = (m, i) => exportAllowed && completedReply(m, i);
  /* The transcript scrolls (talk.css `.n-transcript`), so it is a scrollable region — and a
     scrollable region a keyboard user cannot enter is a WCAG 2.1.1 failure. A run of owner turns
     whose replies never came (an unreachable model, an aborted turn) has no focusable child of its
     own, and axe reports `serious · scrollable-region-focusable` in exactly that state; so the
     region itself takes `tabIndex={0}`. Chromium makes overflow scrollers focusable on its own,
     so a tab walk proves nothing there: e2e/a11y.spec.ts asserts the axe rule and `tabIndex`, and
     test/convo-keyboard-access.test.tsx pins the attributes.

     `role="log"` is the ARIA APG role for a chat transcript and is what gives the focused region
     an accessible name (`aria-label` alone would sit on a `generic` element, which prohibits
     naming); it also makes the region `aria-live="polite"`. The working reply's steps change
     several times per turn, so WorkingReply marks them `aria-live="off"`. Not measured with a real
     screen reader: the `GET /memory` rehydration (app.tsx) injects a whole restored transcript into
     an already-mounted live region, which an AT may announce in bulk. */
  const s = talkStrings(lang);
  const flying: TabTurn[] = Array.isArray(turns) ? turns : [];
  const flyingIds = new Set(flying.map(turn => turn.turnId));
  const inFlight = (m: TalkMessage) => m.role === 'agent' && typeof m._turnId === 'number' && flyingIds.has(m._turnId);
  const workingIndexes = messages.flatMap((m, i) => inFlight(m) ? [i] : []);
  const lastWorking = workingIndexes.length ? workingIndexes[workingIndexes.length - 1] : -1;
  /* Whose outcome. App's `outcome` always belongs to App's newest turn: runTurn clears it when a
     turn starts, the turn's outcome_progress frames set it while it is in flight, its end frame
     sets it last. So it is drawn on that turn's reply only, once the reply is written — never on
     an earlier reply (a reply in flight shows only the model it reported). The newest turn is the
     highest turn id this transcript has seen: a reply bubble's, a turn in flight, or one drawn
     before and since removed (App drops a turn's bubble when the hub did not use its board or
     chat source, and that turn's outcome stays). When App names the turn, that is used instead. */
  const seenTurn = useRef(-Infinity);
  const latestTurnId = Math.max(seenTurn.current,
    messages.reduce((latest, m) => typeof m._turnId === 'number' && m._turnId > latest ? m._turnId : latest, -Infinity),
    flying.reduce((latest, turn) => turn.turnId > latest ? turn.turnId : latest, -Infinity));
  useLayoutEffect(() => { seenTurn.current = latestTurnId; }, [latestTurnId]);
  const outcomeTurn: number | null = typeof outcomeTurnId === 'number' || outcomeTurnId === null ? outcomeTurnId : latestTurnId;
  const outcomeOf = (m: TalkMessage) => outcome && outcomeTurn !== null && m._turnId === outcomeTurn && !inFlight(m) ? outcome : null;
  // A question waits on the turn that asked it; with only "a question is open", on the one turn in flight.
  const askingTurn = typeof awaitingAnswer === 'number' ? awaitingAnswer
    : awaitingAnswer === true && flying.length === 1 ? flying[0].turnId : null;
  const newestReply = messages.reduce((last, m, i) => m.role === 'agent' && m.who !== 'system' && !inFlight(m)
    && ((typeof m.text === 'string' && m.text.trim()) || outcomeOf(m)) ? i : last, -1);
  const turnTime = (m: TalkMessage) => m.ts ? <time className="n-turn__time">{m.ts}</time> : <span className="n-turn__time" aria-hidden="true" />;
  /* The Ledger transcript (PHASE_B_PLAN.md §5.3): one log region, a grid per turn (time · who ·
     words), the owner's words as typed, a reply in the reading face with its footnote, slip and
     action budget. The test hooks are data-turn="owner|reply|system|vision" and data-turn-body
     on the words. */
  const transcript = (
    <div className="n-transcript" ref={endRef} tabIndex={0} role="log" data-transcript=""
         aria-label={(t && t.convoRegion) || 'Conversation transcript'}>
      {messages.map((m: TalkMessage, i: number) => {
        if (m.role === 'user') {
          const text = typeof m.text === 'string' ? m.text : '';
          const sources = m.attachmentNames || m.vaultNames;
          return (
            <div className="n-turn n-turn--owner" data-turn="owner" key={i}>
              {turnTime(m)}
              <span className="n-turn__who">{s.you}</span>
              <div className="n-turn__body">
                <p className="n-turn__said" data-turn-body="">{text}</p>
                {Array.isArray(m.imageNames) && m.imageNames.length > 0 && <p className="n-turn__attach">{fmt(s.imagesSent, { names: m.imageNames.join(', ') })}</p>}
                {Array.isArray(sources) && sources.length > 0 && <ul className="n-turn__sources" aria-label={lang === 'ro' ? 'Surse atașate' : 'Attached sources'}>
                  {sources.map(name => <li key={name}>{name}</li>)}</ul>}
                {messageActionsAllowed && Array.isArray(m.boardSources) && !!m.boardSources.length &&
                  <BoardSources key={messageScope} sources={m.boardSources} lang={lang}/>}
                {messageActionsAllowed && text.trim() && <OwnerActions lang={lang}
                  onRemember={opener => setAction({ kind: 'remember', message: m, scope: messageScope, opener, credential: noteCredential() })}
                  onTask={opener => setAction({ kind: 'task', message: m, scope: messageScope, opener })}/>}
              </div>
            </div>
          );
        }
        if (m.role === 'vision') {
          const ran = [m.model, m.backend, m.destination].filter((part): part is string => typeof part === 'string' && part !== '');
          return (
            <div className="n-turn n-turn--vision" data-turn="vision" key={i}>
              {turnTime(m)}
              <span className="n-turn__who" title={s.vision}>{s.visionWho}</span>
              <div className="n-turn__body">
                <div className="n-turn__said" data-turn-body=""><Bubble text={m.text as string} /></div>
                <p className="n-turn__ran">{ran.map((part, n) => <React.Fragment key={n}><code>{part}</code>{' · '}</React.Fragment>)}{m.local ? s.loopback : s.remote}</p>
                {typeof m.warning === 'string' && m.warning && <p className="n-turn__warn"><Mark kind="attn" size="sm" lang={lang}/><span>{m.warning}</span></p>}
              </div>
            </div>
          );
        }
        if (m.who === 'system') {
          return (
            <div className="n-turn n-turn--system" data-turn="system" key={i}>
              {turnTime(m)}
              <span className="n-turn__who">{s.system}</span>
              <div className="n-turn__body"><div className="n-turn__said" data-turn-body=""><Bubble text={m.text as string} lang={lang} /></div></div>
            </div>
          );
        }
        const working = inFlight(m);
        const hasText = typeof m.text === 'string' && m.text.trim() !== '';
        const tools = Array.isArray(m.tools) ? m.tools : [];
        // a reserved bubble that was stopped before a word or a tool arrived carries nothing to read
        if (!working && !hasText && !tools.length && !m._complete && typeof m._turnId === 'number') return null;
        const name = agentDisplayName(String(m.who || 'jarvis'), agents);
        const receipt = messageActionsAllowed ? noteReceipts.find(entry => entry.message === m && entry.scope === messageScope && entry.credential === noteCredential())?.receipt : undefined;
        const mesh = canExport(m, i) ? blenderSourceFromReply(m.text) : null;
        const actionable = messageActionsAllowed && completedReply(m, i);
        const canFindSource = actionable && hasText && sourceAllowed && mayFindSavedSource();
        const own = outcomeOf(m);
        return (
          <div className="n-turn n-turn--reply" data-turn="reply" key={i} data-working={working ? '' : undefined} data-newest={i === newestReply ? '' : undefined}>
            {turnTime(m)}
            <span className="n-turn__who" title={m.role_label ? `${name} — ${m.role_label}` : name}>{name}</span>
            <div className="n-turn__body">
              {working ? (
                <WorkingReply message={m} turn={flying.find(turn => turn.turnId === m._turnId) || null} agentName={name}
                  inFlight={flying.length} showStop={i === lastWorking} onStop={onStop} outcome={outcome}
                  latest={outcomeTurn !== null && m._turnId === outcomeTurn} awaitingAnswer={askingTurn !== null && m._turnId === askingTurn} lang={lang}>
                  {hasText && <div className="n-turn__said" data-turn-body=""><Bubble text={m.text as string} lang={lang} /></div>}
                </WorkingReply>
              ) : (
                <div className="n-turn__said" data-turn-body=""><Bubble text={m.text as string} tableExport={canExport(m, i)} codeExport={canExport(m, i)} lang={lang} /></div>
              )}
              <TurnApprovals ids={m.approvals as number[] | undefined} slip floating={variant === 'floating'} lang={lang} />
              {receipt && <div role="status" className="n-turn__receipt">{lang === 'ro' ? 'Salvat în Obsidian: ' : 'Saved to Obsidian: '}{receipt.relPath}
                {receipt.source && <> · <a href={obsidianOpenUri(receipt.source) || undefined}>
                  {lang === 'ro' ? 'Deschide în Obsidian' : 'Open in Obsidian'}</a></>}</div>}
              {!working && <div className="n-turn__foot">
                <ReplyFootnote message={m} onProv={onProv} outcome={own} lang={lang} />
                {/* a reply written empty still carries its turn's details (a completion warning lives there) */}
                {(hasText || own) && <ReplyActions lang={lang} text={hasText ? m.text as string : ''} newest={i === newestReply}
                  save={hasText && canSave(m, i) ? <SaveArtifactButton message={m} onSaved={onArtifactSaved} lang={lang} /> : undefined}
                  readAloud={hasText ? <TtsButton text={m.text as string} lang={lang} words={{ idle: s.readAloud, playing: s.reading, failed: s.readFailed }} /> : undefined}
                  onTask={actionable ? opener => setAction({ kind: 'task', message: m, scope: messageScope, opener }) : undefined}
                  more={[
                    ...(canFindSource ? [{ key: 'saved-source', label: s.findSavedSource,
                      onPick: (opener: HTMLElement) => setAction({ kind: 'saved-source', message: m, scope: messageScope, opener, credential: historyOwnerKey() }) }] : []),
                    ...(canExport(m, i) ? [{ key: 'word', node: <OfficeExportButton data={{ format: 'docx', text: m.text as string }} lang={lang} /> }] : []),
                    ...(actionable && canExport(m, i) ? [{ key: 'photoshop', node: <PhotoshopLayoutButton key={`${messageScope}/${m._turnId ?? m.text}`}
                      text={m.text as string} lang={lang === 'ro' ? 'ro' : 'en'} /> }] : []),
                    ...(actionable && !m._unattributed ? [{ key: 'obsidian', label: s.saveObsidian,
                      onPick: (opener: HTMLElement) => setAction({ kind: 'obsidian', message: m, scope: messageScope, opener }) }] : []),
                    ...(actionable && !m._unattributed ? [{ key: 'teach', label: s.teach,
                      onPick: (opener: HTMLElement) => setAction({ kind: 'teach', message: m, scope: messageScope, opener }) }] : []),
                    ...(mesh ? [{ key: 'blender', label: s.reviewBlender,
                      onPick: (opener: HTMLElement) => setMeshReview({ source: mesh, message: m, scope: messageScope, opener }) }] : []),
                  ]}
                  details={own ? <StatusStrip outcome={own} power={power} /> : undefined} />}
              </div>}
            </div>
          </div>
        );
      })}
      {thinking && !workingIndexes.length && <PendingReply lang={lang} onStop={onStop} inFlight={Math.max(1, flying.length)}
        {...(thinking.label === 'Vision analysis' ? { who: s.visionWho, whoTitle: s.vision }
          : { who: Array.isArray(thinking.route) && thinking.route[0] ? agentDisplayName(String(thinking.route[0]).toLowerCase(), agents) : '' })} />}
    </div>
  );
  return <>
    {transcript}
    {selected?.kind === 'remember' && <RememberMessageDialog text={selected.message.text}
      source={{ sessionId, text: selected.message.text, role: 'user', agentId: agent }}
      opener={selected.opener} onClose={() => setAction(null)} />}
    {selected?.kind === 'saved-source' && <RecalledFactSourceDialog reply={selected.message.text} lang={lang}
      opener={selected.opener} onClose={() => setAction(null)} />}
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

/* segmented toggle for the voice settings popover */
function Seg({ cur, opts, on }) {
  return (
    <span style={{display:'inline-flex',gap:3}}>
      {opts.map(o=>(
        <button key={o.v} onClick={()=>on(o.v)}
          style={{...LABEL, padding:'3px 8px',borderRadius:6,border:'1px solid '+(cur===o.v?'var(--accent)':'var(--panel-line)'),background:cur===o.v?'var(--accent)':'transparent',color:cur===o.v?'var(--n-on-accent)':'var(--ink-2)',fontSize:'var(--n-fs-meta)',cursor:'pointer'}}>{o.l}</button>
      ))}
    </span>
  );
}

/* The composer (PHASE_B_PLAN.md §5.3), re-laid in place: a head (To, Mode) above a multi-line
   field and a bar with exactly Attach ▾ · Voice · Options ▾ · the `/` and `@` hints · Send. The
   classic layout without that head (and with the turn's outcome lines under the bar) was deleted
   with ChatMode at the stage 5 cleanup: the outcome lines are the newest reply's "Turn details".
   Every control the input bar had is kept with its logic; those outside the fixed set moved into
   the Attach and Options menus, which stay mounted while closed. Enter sends, Shift+Enter adds a
   line, nothing sends while an IME is composing, and Tab still accepts an @file: completion. The
   hub takes at most 4,096 characters (code points); longer text stays in the field, counted,
   and Send says why it is off. When Send is disabled, a line under the bar says why (or Send
   points at the message above that already does).

   Additive props, all optional (InputBarProps in home/talk/types.ts is unchanged):
     onSelectAgent  the "To" picker (App's selectChatAgent); without it the recipient is shown
     approvalMode   the reading the "Mode" shows (home/talk/recipient-mode.ts: the recipient's
                    own mode); without it: "Mode unknown — not read on this page"
     variant        the register that holds it ('home' | 'chat' | 'floating'; 'home' when left
                    out): the floating window's field starts at one line
     openHistory    filled with an opener for the chat-history search, so the register head's
                    "Search earlier conversations" opens the same dialog the Options item does
     recipientSwitch, onRecipientSwitch
                    the change of recipient waiting for the owner's answer, when App keeps it (so
                    the To's question outlives the composer); without it the To keeps its own
     recipientRefusal
                    why App holds no recipient (home/talk/types.ts RecipientRefusal): the line
                    above the composer says it, and that nothing is sent until a new choice
     recipientHold  the selected agent App keeps but cannot confirm (a poll completed without the
                    hub serving the roster): the line says so in the hub's terms, the To names the
                    agent "not confirmed" and offers Jarvis
     recipientSwitchDropped, onRecipientSwitchDropped
                    a change of recipient App dropped because a served roster no longer offers the
                    agent: one line in the head says so until the next send, a new recipient or
                    Dismiss; without them the composer says it of the To's own question
   `outcome` and `power` stay in the props (InputBarProps) and are not drawn here: the turn's
   outcome lines are its reply's "Turn details" (Conversation). */
function InputBar({ onSubmit, mic, setMic, voice, cfg, onCfg, micMuted, motion, t, lang='en', demo=false, agent='jarvis', agents=[], recipientStatus='ready', sessionId='', selectedTurn=false, projectForChat, onProjectReviewed, boardResultForChat, onBoardResultReviewed, inspectBlend, turnActive=false, canContinue, onSteer, onSelectAgent, approvalMode, variant='home', openHistory, recipientSwitch, onRecipientSwitch, recipientRefusal = null, recipientHold = null, recipientSwitchDropped, onRecipientSwitchDropped }: { onSubmit?: any; mic?: any; setMic?: any; voice?: any; cfg?: any; onCfg?: any; micMuted?: any; motion?: any; t?: any; lang?: string; demo?: boolean; agent?: string; agents?: ChatAgent[]; recipientStatus?: 'ready' | 'checking' | 'choose'; sessionId?: string; selectedTurn?: boolean; outcome?: TurnOutcome | null; power?: PowerState; projectForChat?: WorkshopRef | null; onProjectReviewed?: () => void; boardResultForChat?: BoardResultRef | null; onBoardResultReviewed?: () => void; inspectBlend?: React.RefObject<((file: File) => boolean) | null>; turnActive?: boolean; canContinue?: () => boolean; onSteer?: (text: string) => Promise<boolean>; onSelectAgent?: (id: string) => void; approvalMode?: ApprovalModeInput | null; variant?: TalkVariant; openHistory?: React.MutableRefObject<((opener: HTMLElement) => boolean) | null>; recipientSwitch?: RecipientSwitch | null; onRecipientSwitch?: (id: string | null) => void; recipientRefusal?: RecipientRefusal | null; recipientHold?: RecipientHold | null; recipientSwitchDropped?: RecipientSwitchDropped | null; onRecipientSwitchDropped?: () => void }) {
  const [val,setVal]=useState('');
  const [blenderMode, setBlenderMode] = useState(false);
  const blenderRequest = blenderMode && val.trim() ? blenderMeshRequest(val) : '';
  // the hub counts characters as code points (ChatRequest.message), as composer-skills does
  const blenderTooLong = Array.from(blenderRequest).length > MAX_MESSAGE;
  // The Blender option is offered only on a live, selected turn; leaving one turns the mode off,
  // so Send is never held by a mode whose switch is not on screen.
  useLayoutEffect(() => { if (!selectedTurn || demo) setBlenderMode(false); }, [selectedTurn, demo]);
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
  // Checking while the selected agent is verified (the register head says the same sentence); once
  // a poll has completed without the hub serving the roster, that it cannot be confirmed and why;
  // once App has dropped a recipient, why, and that nothing goes to a substitute (the generic line
  // only when App gave no reason)
  const recipientWords = talkStrings(lang);
  const hold = recipientStatus === 'checking' && !demo ? recipientHold : null;
  const holdName = hold ? agentDisplayName(hold.agent, agents, hold.name) : '';
  const recipientHint = hold ? fmt(recipientWords.recipientNotServed, { agent: holdName, fallback: agentDisplayName('jarvis', agents) })
    : recipientStatus === 'checking' ? recipientWords.recipientChecking
      : recipientRefusalText(recipientRefusal, agents, lang) ?? recipientWords.recipientChoose;
  // A change of recipient waiting on the To's question: Send holds meanwhile, so a message written
  // now does not go to the recipient being replaced. App keeps the question when it passes one
  // (`recipientSwitch`, null when none is open); a composer drawn without App learns of the To's
  // own question from the To.
  const [ownSwitch, setOwnSwitch] = useState(false);
  const switchKept = recipientSwitch !== undefined;
  const switchPending = switchKept ? !!recipientSwitch : ownSwitch;
  const onSwitchChange = (id: string | null) => { if (switchKept) onRecipientSwitch?.(id); else setOwnSwitch(id !== null); };
  const switchWhyId = useId();
  // …and one dropped because a roster the hub served no longer offers the agent: said on one line
  // until the next send, a change of recipient or Dismiss. App keeps it with the question; drawn
  // without App, the composer keeps what the To tells it of its own.
  const [ownDropped, setOwnDropped] = useState<RecipientSwitchDropped | null>(null);
  useLayoutEffect(() => { setOwnDropped(null); }, [sentCount, agent, demo]);
  const dropped = switchKept ? recipientSwitchDropped ?? null : ownDropped;
  const dismissDropped = () => { if (switchKept) onRecipientSwitchDropped?.(); else setOwnDropped(null); };
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
  // A strictly local agent (signals/agents-policy.ts, the hub's LOCAL_ONLY_AGENTS) never sends
  // board passages to a cloud provider, so it needs no cloud consent.
  const boardCloudCapable = !isLocalOnlyAgent(agent);
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
  const composerInput = useRef<HTMLTextAreaElement>(null);
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
  /* What the hub would receive, counted as it counts (code points): a chat message takes 4,096, an
     image question 4,000 (the routes images go to). Text over the limit stays in the field — a
     paste is never cut — and is not sent. The Blender instruction has its own check
     (blenderTooLong), since it wraps the description in a longer request. */
  const typedLength = Array.from(val.trim()).length;
  const limit = draft.enabled ? MAX_IMAGE_PROMPT : MAX_MESSAGE;
  const tooLong = !blenderMode && typedLength > limit;
  // This review belongs to one draft, recipient and retained session. A changed scope cannot
  // inherit its preview, even if a response to an older preview arrives later.
  const cloudScope = JSON.stringify([agent, sessionId, val.trim(), demo, selectedTurn]);
  const cloudScopeNow = useRef(cloudScope);
  cloudScopeNow.current = cloudScope;
  const [cloudReview, setCloudReview] = useState<{ scope: string; message: string; preview: CloudHistoryPreview } | null>(null);
  const [cloudReviewBusy, setCloudReviewBusy] = useState(false);
  const [cloudReviewError, setCloudReviewError] = useState('');
  const [cloudSending, setCloudSending] = useState(false);
  const cloudReviewButton = useRef<HTMLButtonElement>(null);
  const cloudCancelButton = useRef<HTMLButtonElement>(null);
  useEffect(() => onOwnerSession(() => { cloudScopeNow.current = ''; setCloudReview(null); }), []);
  const cloudEligible = !demo && selectedTurn && !isLocalOnlyAgent(agent) && !!sessionId && !command &&
    !draft.enabled && !vault.selected.length && !officeActive && !boardInUse && !currentHistory && !blenderMode;
  const visibleCloudReview = cloudEligible && cloudReview?.scope === cloudScope ? cloudReview : null;
  useLayoutEffect(() => {
    if (!visibleCloudReview) return;
    cloudCancelButton.current?.focus();
    return () => {
      const trigger = cloudReviewButton.current;
      if (trigger?.isConnected) trigger.focus();
      else composerInput.current?.focus();
    };
  }, [visibleCloudReview]);
  useLayoutEffect(() => {
    if (cloudReview && !visibleCloudReview) setCloudReview(null);
    setCloudReviewError('');
  }, [cloudScope, cloudEligible]);
  const reviewCloudHistory = async () => {
    if (!cloudEligible || !val.trim() || cloudReviewBusy || cloudSending || turnActive || tooLong || recipientStatus !== 'ready' || switchPending) return;
    const scope = cloudScope, message = val.trim();
    setCloudReviewBusy(true); setCloudReviewError('');
    try {
      const result = cloudHistoryPreview(await apiPost('/api/chat/cloud-history/preview',
        { session_id: sessionId, agent, message }, { admin: true }), sessionId, agent);
      if (cloudScopeNow.current !== scope) return;
      if (!result) throw new Error('invalid preview');
      setCloudReview({ scope, message, preview: result });
    } catch {
      if (cloudScopeNow.current === scope) setCloudReviewError(lang === 'ro'
        ? 'Istoricul nu poate fi revizuit acum. Ciorna este păstrată.'
        : 'Earlier turns cannot be reviewed now. Your draft is kept.');
    } finally { setCloudReviewBusy(false); }
  };
  const sendCloudHistory = async () => {
    const review = visibleCloudReview;
    if (!review || cloudSending || turnActive || review.message !== val.trim() || tooLong || recipientStatus !== 'ready' || switchPending) return;
    setCloudReview(null); setCloudSending(true);
    try {
      const accepted = await onSubmit(review.message, undefined, undefined, directReply,
        { cloudHistory: review.preview, reviewedMessage: review.message, awaitAdmission: true });
      if (accepted !== false && cloudScopeNow.current === review.scope) {
        vault.clear(); setDirectReplyScope(''); setVal(''); setSentCount(n => n + 1);
      } else if (cloudScopeNow.current === review.scope) {
        setCloudReviewError(lang === 'ro' ? 'Trimiterea a fost refuzată. Ciorna este păstrată.' : 'Send was refused. Your draft is kept.');
      }
    } catch {
      if (cloudScopeNow.current === review.scope) setCloudReviewError(lang === 'ro' ? 'Trimiterea a fost refuzată. Ciorna este păstrată.' : 'Send was refused. Your draft is kept.');
    } finally { setCloudSending(false); }
  };
  const submit=()=>{
    if (visibleCloudReview || cloudSending) return;
    if (recipientStatus !== 'ready' || switchPending) return;
    if (officeSending || vault.busy || boardResult.busy || boardResult.reviewing || skillWarning) return;
    if (tooLong) return;
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
  const showPill = voice && (voice.active || voice.error || voice.status === 'interrupted');
  const label = voice && voice.error ? voice.error
    : voice && voice.status==='interrupted' ? 'interrupted — listening…'
    : voice && voice.status==='listening' ? (voice.bargeInterrupted ? 'barge-in interrupted · listening…' : 'listening…')
    : voice && voice.status==='transcribing' ? 'transcribing…'
    : voice && voice.status==='speaking' ? 'speaking…' : 'voice on';
  const row = (lbl,node) => (
    <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:12,padding:'4px 0'}}>
      <span style={{...LABEL, color:'var(--ink-2)',fontSize:'var(--n-fs-meta)'}}>{lbl}</span>{node}
    </div>
  );

  /* ---- the re-laid composer (§5.3) ---- */
  const s = talkStrings(lang);
  const [attachOpen, setAttachOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const attachButton = useRef<HTMLButtonElement | null>(null);
  const optionsButton = useRef<HTMLButtonElement | null>(null);
  const whyId = useId(), skillWarningId = useId(), officeSendingId = useId(), blenderAlertId = useId(), countId = useId(), inputId = useId();
  // A document or task-result review returns focus to its trigger inside the Attach menu, so the
  // menu opens with the review (behind its dialog) and is there when the review closes.
  useEffect(() => { if (office.expanded || boardResult.reviewing) setAttachOpen(true); }, [office.expanded, boardResult.reviewing]);
  // The register head's "Search earlier conversations" opens the same dialog as the Options item.
  useLayoutEffect(() => {
    if (!openHistory) return undefined;
    openHistory.current = node => {
      if (!selectedTurn || demo) return false;
      setHistoryOpener({ node, scope: historyScope });
      return true;
    };
    return () => { openHistory.current = null; };
  }, [openHistory, selectedTurn, demo, historyScope]);
  // The field grows with what is written (one to six lines, set in talk.css), then scrolls.
  useLayoutEffect(() => {
    const field = composerInput.current;
    if (!field) return;
    field.style.height = '';
    if (field.scrollHeight > 0) field.style.height = `${field.scrollHeight}px`;
  }, [val, variant]);
  // the recipient the field is written for: App's, or the one it keeps without confirming it
  const recipientName = hold ? holdName : agentDisplayName(agent, agents);
  const template = typeof t?.placeholder === 'string' && t.placeholder ? t.placeholder : s.placeholder;
  // the change of recipient dropped (see above), named as the hub's roster named it
  const droppedNotice = dropped ? (() => {
    const name = agentDisplayName(dropped.id, agents, dropped.name);
    const now = agentDisplayName(agent, agents);
    return fmt(now ? s.switchDropped : s.switchDroppedNone, { agent: name, current: now });
  })() : null;
  const placeholder = voice && voice.active ? (cfg && cfg.mode==='ptt' ? 'listening — speak now' : 'listening — just speak (or type)')
    : recipientName ? fmt(template, { agent: recipientName }) : s.toChoose;
  const sendLabel = typeof t?.transmit === 'string' && t.transmit ? t.transmit : s.send;
  const locale = lang === 'ro' ? 'ro-RO' : 'en-US';
  /* Send's existing twelve conditions, in their order, with the To's open question after the
     recipient's, then the length limit. The first that holds says why Send is off: either a
     message above already says it (the recipient hint, the To's question, the skill warning, the
     passages being sent, the Blender length alert) and Send points at it, or the line under the
     bar does. */
  const blenderBlocked = blenderMode && (!val.trim() || blenderTooLong || !canStartAttachment || boardInUse || !!vault.selected.length);
  // the Blender length alert above says it when it is drawn (Blender mode shows only on a selected live turn)
  const blenderAlertShown = selectedTurn && !demo && blenderMode && blenderTooLong;
  // Blender mode is held by a / command, or by something attached (images, a passage, notes, a task result)
  const blenderWhy = !val.trim() ? s.whyBlenderEmpty : blenderAlertShown ? null : blenderTooLong ? s.whyBlenderLong
    : command ? s.whyBlenderCommand : s.whyBlenderBlocked;
  const blockers: Array<[boolean, string | null, string | null]> = [
    [recipientStatus !== 'ready', null, recipientHintId],
    [switchPending, null, switchWhyId],
    [!!skillWarning, null, skillWarningId],
    [officeSending, null, officeSendingId],
    [vault.busy, s.whyVaultBusy, null],
    [boardResult.busy, s.whyBoardBusy, null],
    [boardResult.reviewing, s.whyBoardReview, null],
    [historySending, s.whyHistorySending, null],
    [boardResult.active && boardCloudCapable && !boardCloudConsent, s.whyBoardConsent, null],
    [blenderBlocked, blenderWhy, val.trim() && blenderAlertShown ? blenderAlertId : null],
    [!!currentHistory && !val.trim(), s.whyHistoryText, null],
    [draft.enabled && !draft.ready, s.whyImages, null],
    [officeActive && !officeReady, s.whyOffice, null],
    [tooLong, plural(lang, s.whyTooLong, typedLength - limit,
      { n: (typedLength - limit).toLocaleString(locale), max: limit.toLocaleString(locale) }), null],
  ];
  const blocker = blockers.find(([on]) => on) || null;
  const sendDisabled = !!blocker;
  const why = blocker ? blocker[1] : null;
  const describedBy = blocker ? (blocker[2] || (why ? whyId : undefined)) : undefined;
  const ready = !sendDisabled && (!!val.trim() || draft.enabled || officeActive || boardResult.active || !!vault.selected.length);
  // the staged images and their review show only while there is something to show
  const showImages = draft.enabled || !!draft.note || draft.activeState !== 'idle' || draft.xaiUnsupported;
  const keyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Tab' && refs.length) { e.preventDefault(); setVal(acceptRef(val, refs[0].ref)); return; }
    if (e.key !== 'Enter' || e.shiftKey) return;   // Shift+Enter adds a line
    // An IME uses Enter to pick its candidate: nothing is sent while it composes.
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    submit();
  };
  const [steeringBusy, setSteeringBusy] = useState(false);
  const canSteer = !!onSteer && turnActive && !demo && recipientStatus === 'ready' && !switchPending
    && !!val.trim() && !command && !tooLong && !blenderMode && !draft.enabled && !officeActive
    && !boardInUse && !vault.selected.length && !currentHistory && !visibleCloudReview;
  const steerActiveTurn = async () => {
    if (!canSteer || steeringBusy || !onSteer) return;
    const text = val.trim();
    setSteeringBusy(true);
    try {
      const ok = await onSteer(text);
      if (ok) {
        setVal('');
        setSentCount(n => n + 1);
      }
    } finally {
      setSteeringBusy(false);
    }
  };
  const closeOptions = () => { setOptionsOpen(false); optionsButton.current?.focus(); };
  const closeAttach = () => { setAttachOpen(false); attachButton.current?.focus(); };
  const chevron = <svg className="n-composer__chev-sm" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M3.5 6l4.5 4.5L12.5 6" /></svg>;
  return (
    <div className={`n-composer-wrap n-composer-wrap--${variant}`} data-composer-root="" data-composer-variant={variant}
      style={{position:'relative',display:'flex',flexDirection:'column',minHeight:0,flexShrink:1}} onPaste={boardInUse || currentHistory || officeActive ? undefined : draft.onPaste} onDrop={boardInUse || currentHistory || officeActive ? event => event.preventDefault() : draft.onDrop} onDragOver={event=>{if(Array.from(event.dataTransfer.types).includes('Files'))event.preventDefault();}}>
      {cloudEligible && <div style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', marginBottom: 6 }}>
        {lang === 'ro' ? 'Se trimite doar mesajul curent. Verifică destinația înainte de a include istoricul.'
          : 'Current message only. Check the destination before including history.'}{' '}
        <button ref={cloudReviewButton} type="button" className="tool-btn" disabled={!val.trim() || cloudReviewBusy || cloudSending || turnActive || tooLong}
          onClick={() => { void reviewCloudHistory(); }}>{lang === 'ro' ? 'Revizuiește mesajele anterioare' : 'Review earlier turns'}</button>
        {cloudReviewBusy && <span role="status">{lang === 'ro' ? 'Se verifică destinația…' : 'Checking destination…'}</span>}
        {cloudReviewError && <span role="alert">{cloudReviewError}</span>}
      </div>}
      {visibleCloudReview && <div className="pal-scrim" onClick={() => setCloudReview(null)} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setCloudReview(null); } }}>
        <div className="pal" role="dialog" aria-modal="true" aria-label={lang === 'ro' ? 'Trimite mesajele anterioare' : 'Send earlier turns'}
          onClick={event => event.stopPropagation()} style={{ width: 'min(440px,92vw)' }}>
          <div style={{ padding: 18 }}>
            <p>{lang === 'ro' ? 'Mesajele anterioare din această conversație vor fi trimise la' : 'Earlier turns from this chat will be sent to'} <b>{visibleCloudReview.preview.provider} / {visibleCloudReview.preview.model}</b>.</p>
            <p>{lang === 'ro' ? 'Această alegere se aplică doar mesajului curent.' : 'This choice applies only to this message.'}</p>
            <button ref={cloudCancelButton} type="button" className="tool-btn" onClick={() => setCloudReview(null)}>{lang === 'ro' ? 'Anulează' : 'Cancel'}</button>{' '}
            <button type="button" className="tool-btn" onClick={() => { void sendCloudHistory(); }}>{lang === 'ro' ? 'Include și trimite' : 'Include and send'}</button>
          </div>
        </div>
      </div>}
      {showImages && <ComposerImages draft={draft} disabled={!!currentHistory}/>}
      {officeSending
        ? <p role="status" id={officeSendingId}>{lang === 'ro' ? 'Se trimit pasajele selectate…' : 'Sending selected passages…'}</p>
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
        <pre style={{fontFamily:'inherit'}}>{currentHistory.reference.excerpt}</pre><button type="button" className="tool-btn" disabled={historySending}
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
      {skillWarning && <p role="status" id={skillWarningId}>{skillWarning}</p>}
      {recipientStatus !== 'ready' && <p id={recipientHintId} role="status" className="n-composer__recipient"
        data-recipient-state={hold ? 'unconfirmed' : recipientStatus} data-recipient-reason={recipientStatus === 'choose' && recipientRefusal ? recipientRefusal.reason : undefined}>{recipientHint}</p>}
      {selectedTurn && !demo && blenderMode && <div className="n-composer__staged" data-staged="blender">
        <p>{s.blenderOn}</p>
        <details><summary>{lang === 'ro' ? 'Revizuiește instrucțiunea trimisă' : 'Review instruction to send'}</summary>
          <pre style={{fontFamily:'inherit'}}>{blenderRequest || (lang === 'ro' ? 'Scrie o descriere în câmpul de mesaj.' : 'Write a description in the message field.')}</pre></details>
        {blenderTooLong && <p role="alert" id={blenderAlertId}>{lang === 'ro' ? 'Instrucțiunea depășește 4.096 de caractere. Scurtează descrierea sau dezactivează modul Blender.'
          : 'The instruction exceeds 4,096 characters. Shorten your description or turn off Blender mode.'}</p>}
      </div>}
      {showPill && (
        <div style={{display:'flex',alignItems:'center',gap:8,padding:'5px 10px',marginBottom:6,borderRadius:8,fontSize:'var(--n-fs-meta)',background:'var(--void-2)',border:'1px solid var(--panel-line)',color:voice.error?'var(--amber)':'var(--accent-light)'}}>
          {!voice.error && <VoiceOrb status={voice.status} level={voice.level||0} motion={motion} density="compact" showLabel={false} className="vorb-inline" />}
          <span style={{flex:'none'}}>{voice.error ? '⚠ ' : ''}{label}</span>
          {/* H247: another surface on this machine holds the microphone — the owner may take it. */}
          {voice.error && voice.micHolder && typeof voice.takeOver === 'function' && (
            <button className="tool-btn" style={{padding:'0 6px',fontSize:'var(--n-fs-meta)'}} onClick={() => voice.takeOver()}
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
      <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple aria-label="Attach images" style={{display:'none'}} onChange={event=>{if(!currentHistory)draft.addFiles(Array.from(event.target.files||[]));event.target.value='';}}/>
      <div className="n-composer" data-composer-frame="" aria-label={recipientName ? fmt(s.composerLabel, { agent: recipientName }) : undefined} role="group">
        <div className="n-composer__head">
          <RecipientPicker agent={agent} agents={agents} demo={demo} recipientStatus={recipientStatus}
            onSelectAgent={onSelectAgent} inFlight={turnActive} lang={lang}
            pending={switchKept ? (recipientSwitch ? recipientSwitch.id : null) : undefined}
            pendingName={switchKept && recipientSwitch ? recipientSwitch.name : undefined} unconfirmed={hold}
            onDropped={(id) => setOwnDropped({ id, from: agent, demo })}
            onPendingChange={onSwitchChange} whyId={switchWhyId} onChosen={() => composerInput.current?.focus()}/>
          <ComposerMode reading={approvalMode} agentName={recipientName} lang={lang}/>
          {/* on its own line under the head, where the question was: Send is free (nothing waits on it) */}
          {droppedNotice && <p className="n-composer__dropped" role="status" data-recipient-dropped={dropped!.id}>
            <span>{droppedNotice}</span>{' '}
            <button type="button" className="n-btn n-btn--sm n-btn--bare" onClick={dismissDropped}>{s.dismiss}</button>
          </p>}
        </div>
        <div className="n-composer__field" style={{position:'relative'}}>
          <ContextRefHints items={refs} onPick={ref=>setVal(acceptRef(val,ref))}/>
          <label className="n-composer__label" htmlFor={inputId} data-visually-hidden="">{recipientName ? fmt(s.composerLabel, { agent: recipientName }) : s.toChoose}</label>
          <textarea id={inputId} ref={composerInput} data-composer="1" data-anchor="composer" className="n-composer__input" rows={1}
            value={val} onChange={e=>setVal(e.target.value)} placeholder={placeholder} onKeyDown={keyDown}
            aria-describedby={typedLength > COUNT_FROM ? countId : undefined}/>
          {typedLength > COUNT_FROM && <span className="n-composer__count" id={countId} data-over={typedLength > limit ? '' : undefined}>
            {fmt(s.count, { n: typedLength.toLocaleString(locale), max: limit.toLocaleString(locale) })}</span>}
        </div>
        <div className="n-composer__bar" data-composer-bar="">
          <TalkMenu hook="attach" menuLabel={s.attach} open={attachOpen} onOpenChange={setAttachOpen} buttonRef={attachButton}
            hold={office.expanded || boardResult.reviewing} buttonClassName="n-btn n-btn--bare n-composer__tool"
            label={<><svg className="n-composer__ico" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M8 3v10M3 8h10" /></svg>{s.attach}{chevron}</>}>
            <button type="button" className="n-tmenu__item" aria-label="Choose images" title="Attach images" disabled={boardInUse || officeActive || !!currentHistory}
              onClick={() => { closeAttach(); fileInput.current?.click(); }}>{s.images}</button>
            <div className="n-tmenu__item n-tmenu__item--embed" data-embed="office">
              <OfficeButton draft={office} disabled={officeSending || demo || draft.enabled || vault.open || command || boardInUse || !!currentHistory}/>
            </div>
            {selectedTurn && !draft.enabled && <button className="n-tmenu__item" type="button"
              aria-label="Find vault notes" title="Find Obsidian notes for this message" aria-expanded={vault.open}
              disabled={!val.trim() || command || officeActive || boardInUse || !!currentHistory}
              onClick={() => { closeAttach(); if (vault.open) vault.clear(); else void vault.lookup(); }}>
              {s.vaultNotes}{!val.trim() && <small className="n-tmenu__hint"> · {s.vaultNeedsText}</small>}
            </button>}
            {selectedTurn && !demo && !draft.enabled && <button ref={boardResult.trigger} type="button" className="n-tmenu__item"
              aria-label={lang === 'ro' ? 'Atașează rezultatul unei sarcini' : 'Attach board result'}
              disabled={!canStartAttachment || boardResult.busy} onClick={() => boardResult.open()}>
              {lang === 'ro' ? 'Rezultat sarcină' : 'Board result'}
            </button>}
          </TalkMenu>
          {/* Voice: its title keeps the legacy hints (e2e and §8.2 row 32 find it by "push-to-talk" /
              "hands-free voice"); a muted or unsupported microphone is said in words, so it is in
              the button's name and never shown by fading alone. */}
          <button type="button" className={'n-btn n-btn--bare n-composer__tool n-composer__voice' + (mic ? ' is-on' : '')} aria-pressed={!!mic}
            data-muted={micMuted ? '' : undefined} onClick={()=>setMic && setMic()}
            title={micMuted ? 'mic muted — unmute NERVA' : (voice && voice.supported===false ? 'voice not supported in this browser' : (cfg && cfg.mode==='ptt' ? 'push-to-talk' : 'hands-free voice'))}>
            <svg className="n-composer__ico" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><rect x="6" y="1.8" width="4" height="7.6" rx="2" /><path d="M3.4 7.6a4.6 4.6 0 0 0 9.2 0M8 12.2v2.2" /></svg>
            {s.voice}
            {/* the separating space sits outside the <small>, so the button's name keeps it */}
            {micMuted ? <>{' '}<small className="n-composer__vstate">· {s.voiceMuted}</small></>
              : voice && voice.supported === false ? <>{' '}<small className="n-composer__vstate">· {s.voiceUnsupported}</small></>
              : voice && voice.caps && voice.caps.stt === true && <>{' '}<small className="n-composer__stt">· {s.voiceLocalStt}</small></>}
          </button>
          <TalkMenu hook="options" menuLabel={s.options} open={optionsOpen} onOpenChange={setOptionsOpen} buttonRef={optionsButton}
            buttonClassName="n-btn n-btn--bare n-composer__tool" label={<>{s.options}{chevron}</>}>
            {selectedTurn && <div className="n-tmenu__choice">
              <button type="button" className="n-tmenu__item" aria-pressed={directReply} disabled={draft.enabled || val.trim().startsWith('/')} aria-describedby={directReplyHelpId}
                onClick={()=>setDirectReplyScope(directReply ? '' : `${agent}\u0000${sessionId}`)}>{t?.directReply || 'Direct reply'}</button>
              <span className="n-tmenu__help" id={directReplyHelpId}>{t?.directReplyHelp || 'Ask supported models to skip extended thinking for this message'}</span>
            </div>}
            {selectedTurn && !demo && <button type="button" className="n-tmenu__item" aria-haspopup="dialog"
              onClick={event => { const opener = optionsButton.current || event.currentTarget; setOptionsOpen(false); setHistoryOpener({ node: opener, scope: historyScope }); }}>
              {lang === 'ro' ? 'Caută în conversații' : 'Search chat history'}
            </button>}
            {canCompare && <button type="button" className="n-tmenu__item" aria-haspopup="dialog" disabled={!val.trim()}
              onClick={event => { const opener = optionsButton.current || event.currentTarget; setOptionsOpen(false); setComparison({ question: val.trim(), opener, agent, sessionId }); }}>
              {lang === 'ro' ? 'Compară agenții' : 'Compare agents'}
            </button>}
            {selectedTurn && !demo && <div className="n-tmenu__choice">
              <button type="button" className="n-tmenu__item" aria-pressed={blenderMode}
                disabled={!blenderMode && (!canStartAttachment || boardInUse || !!vault.selected.length)}
                onClick={() => setBlenderMode(value => !value)}>{lang === 'ro' ? 'Creează model Blender editabil' : 'Make editable Blender model'}</button>
              <span className="n-tmenu__help">{lang === 'ro' ? 'Folosește descrierea ta pentru geometrie editabilă. Răspunsul trebuie să conțină cod OBJ; vei revizui modelul înainte de descărcare.'
                : 'Use your description for editable geometry. The reply needs OBJ code; you will review the model before download.'}</span>
            </div>}
            {selectedTurn && !draft.enabled && !boardInUse && <div className="n-tmenu__item n-tmenu__item--embed" data-embed="skills">
              <ComposerSkills key={`${agent}:${sessionId}:${sentCount}`} agent={agent} draft={val} lang={lang}
                onInsert={(command, isSkill) => {
                  pickedSkill.current = isSkill ? { command, agent, sessionId } : null;
                  setVal(command + ' ' + val); setOptionsOpen(false); composerInput.current?.focus();
                }}/>
            </div>}
            {cfg && onCfg && <div className="n-tmenu__choice">
              <button type="button" className="n-tmenu__item" aria-expanded={cfgOpen} title="voice settings" onClick={()=>setCfgOpen(o=>!o)}>{s.voiceSettings}</button>
              {cfgOpen && <div className="n-composer__voiceset">
                <div style={{...LABEL, color:'var(--accent-light)',fontSize:'var(--n-fs-meta)',marginBottom:6}}>VOICE</div>
                {row('MODE', <Seg cur={cfg.mode} opts={[{v:'hands-free',l:'HANDS-FREE'},{v:'ptt',l:'PUSH-TO-TALK'}]} on={(v)=>onCfg({mode:v})} />)}
                {row('SPEAK', <Seg cur={cfg.tts} opts={[{v:'server',l:'SERVER'},{v:'browser',l:'LOCAL'},{v:'off',l:'OFF'}]} on={(v)=>onCfg({tts:v})} />)}
                {row('LANG', <Seg cur={cfg.lang} opts={[{v:'auto',l:'AUTO'},{v:'ro',l:'RO'},{v:'en',l:'EN'}]} on={(v)=>onCfg({lang:v})} />)}
                {row('BARGE-IN', <Seg cur={cfg.barge||'off'} opts={[{v:'off',l:'OFF'},{v:'on',l:'ON'}]} on={(v)=>onCfg({barge:v})} />)}
                {cfg.barge==='on' && <div style={{marginTop:4,color:'var(--ink-2)',fontSize:'var(--n-fs-meta)'}}>experimental — talk over the reply to interrupt; needs echo cancellation</div>}
                {row('WAKE WORD', <Seg cur={cfg.wake||'off'} opts={[{v:'off',l:'OFF'},{v:'on',l:'ON'}]} on={(v)=>onCfg({wake:v})} />)}
                {cfg.wake==='on' && (voice && voice.wakeSupported===false
                  ? <div style={{marginTop:4,color:'var(--amber)',fontSize:'var(--n-fs-meta)'}}>browser SpeechRecognition not available in this browser</div>
                  : <div style={{marginTop:4,color:'var(--ink-2)',fontSize:'var(--n-fs-meta)'}}>opt-in standby for "hey jarvis" / "hey nerva" via browser SpeechRecognition</div>)}
                {voice && voice.caps && voice.caps.stt===false && <div style={{marginTop:6,color:'var(--amber)',fontSize:'var(--n-fs-meta)'}}>local STT not installed — pip install faster-whisper</div>}
                <MicLeases />
              </div>}
            </div>}
            <button type="button" className="n-tmenu__item" disabled={!!currentHistory}
              onClick={() => { closeOptions(); void draft.loadActiveImages(); }}>{s.usePreviousImage}</button>
          </TalkMenu>
          <span className="n-composer__keys" title={s.keysTitle}>
            <span><code>/</code> {s.keysCommands}</span><span><code>@</code> {s.keysFiles}</span>
          </span>
          {canSteer && (
            <button type="button" className="n-btn n-composer__steer" data-composer-steer=""
              disabled={steeringBusy}
              title={lang === 'ro' ? 'Trimite îndrumare turei active fără a o opri' : 'Deliver mid-turn guidance to the running turn without stopping it'}
              onClick={() => { void steerActiveTurn(); }}>
              {lang === 'ro' ? 'Ghidează' : 'Steer'}
            </button>
          )}
          <button type="button" className={'n-btn n-composer__send' + (ready ? ' n-btn--primary' : '')} data-composer-send=""
            aria-describedby={describedBy} disabled={sendDisabled} onClick={submit}>{sendLabel}</button>
        </div>
        {why && <p className="n-composer__why" id={whyId}>{why}</p>}
      </div>
    </div>
  );
}

/* Phase B retired the cockpit's cognition trace (CognitionStream, buildTrace, traceFromCognition):
   the stages, timings and routing it drew were not what the chat stream reports. PHASE_B_PLAN.md
   \u00a72.4; the working reply in home/talk/ shows what the stream says. */

export { Conversation, InputBar, Bubble };
