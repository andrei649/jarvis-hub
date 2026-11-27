import { SAFE_MODE_OFF } from './safe-mode-banner';
import { usePower } from './power-chip';
import { usePressure } from './pressure-banner';
import {describeImages,restoreVisionTurn} from './vision-turn';
import type {VisionDraft} from './composer-images';
import type { components } from './api/schema.gen';
import { useAppearance, type AppearanceKey } from './appearance';
import { AppearanceProvider, type AppearanceApi } from './theme/appearance-context';
import { applyAppearanceToDocument, readPrefersDark, subscribePrefersDark } from './theme/apply';
import { resolveScheme, themeById, type SchemePreference } from './theme/registry';
/* HUD v2 · APP ROOT — the Ledger frame (docs/design/hud-next/PHASE_B_PLAN.md §2.1). Every route is a
   page inside the Frame (masthead, running head, notices, the page, running foot); Glance is drawn
   full screen; the floating desktop window is the conversation page's floating variant. App owns
   the conversation, the loader and the hub snapshot, and hands them to the pages. */
import React, { useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo, lazy } from 'react';
import { V2, restoreDemoCorpora } from './data';
import { localityFigure } from './locality';
import { useClock, fmtTimeShort, Icon, ICONS } from './primitives';
import { CinemaMesh } from './shell';
import { approvalIds, mergeToolEvent } from './turn-tools';
import { bindings as shortcutBindings, firesInInputs, matchAction, useShortcutOverrides } from './shortcuts';
import { ShortcutsPanel } from './shortcuts-panel';
import { PointerOverlay } from './pointer';
import { PetCompanionOverlay, type AgentPetState } from './panels/pets';
import { historySourceLabel, type HistoryReference } from './chat-history-search';
import { useVoice } from './voice';
import { noticeMessages } from './turn-notices';
import { toolActivity, turnOutcome, type TurnOutcome } from './turn-outcome';
import { createLatestRefreshRunner, loadJarvisData } from './api/loaders';
import { PREVIEW_MODE_LIVE_KEYS, useLiveModes } from './api/live';
import { postStream, apiGet, apiPost, apiFetchOnce, getToken, getAdminToken } from './api/client';
import { csrfToken, isNetworkedOrigin, loadOwnerSession, onOwnerSession, ownerSession } from './api/owner-session';
import { pendingQuestion, PendingQuestion, type Question, type QuestionAnswer } from './pending-question';
import type { WorkshopRef } from './workshop-projects';
import type { BoardReference, BoardResultRef } from './composer-board-result';
import { boardSources } from './board-sources';
import { initAnalytics, trackPageview } from './analytics';
import { useDemoMode } from './demo-mode';
import { notifyDesktopConversation, useDesktopConversation, useDesktopDecisionNotifications, useQuickEntryFocus } from './desktop';
import { useListeningIndicator } from './listening';
import { SessionRecovery } from './session-recovery';
import { modelCalls } from './model-call-provenance';
import { selectableChatAgents } from './chat-routing-policy';

import { shouldShowFirstRun, FIRST_RUN_DISMISS_KEY } from './onboarding-state';
import { useHudRoute, navigateHud, navigatePage, closeHudOverlay, type HudRoute } from './hud-routing';
import type { HudMode } from './hud-modes';
import { RouteBoundary } from './route-boundary';
import { Frame } from './frame/Frame';
import { AreaPage, SlotNote } from './frame/AreaPage';
import { ModePage } from './frame/ModePage';
import { PanelPage } from './frame/PanelPage';
import { Notices } from './frame/Notices';
import { useFrameAttention } from './frame/attention';
import { hubReading, hubSnapshotFrom, hubWithLocality, initialHubSnapshot, type FirstRunNotice, type FrameNavigation, type HubLoaderData } from './frame/types';
import { langOf, type Lang } from './frame/strings';
import { Home } from './home/Home';
import { ChatPage } from './home/ChatPage';
import type { RecipientHold, RecipientRefusal, RecipientSwitch, RecipientSwitchDropped, TalkInput } from './home/talk/types';
import { recipientChoosable, rosterServed, switchStanding } from './home/talk/RecipientPicker';
import { DOCKET_FEED_PATH } from './docket/types';
import { AllPages } from './nav/AllPages';
import { CommandSheet } from './nav/CommandSheet';
import type { SheetActions } from './nav/commands';
import { pageForRoute, type RoutePage } from './nav/routes';
import { refreshPolled } from './signals/poll';
import type { HubSnapshot, TabTurn } from './signals/types';

type ChatAttachment = components['schemas']['ChatAttachment'];
type HistorySend = { reference: HistoryReference; role: 'user' | 'assistant'; onResult: (ok: boolean, reason?: string) => void };
type BoardSend = { boardReferences: BoardReference[]; allowBoardCloud: boolean };

const AgentsMode = lazy(() => import('./modes').then(m => ({ default: m.AgentsMode })));
const Dossier = lazy(() => import('./modes').then(m => ({ default: m.Dossier })));
const MemoryMode = lazy(() => import('./modes').then(m => ({ default: m.MemoryMode })));
const JobsWorkspace = lazy(() => import('./panels/jobs').then(m => ({ default: m.JobsWorkspace })));
const AutonomyMode = lazy(() => import('./modes2').then(m => ({ default: m.AutonomyMode })));
const BuildMode = lazy(() => import('./modes2').then(m => ({ default: m.BuildMode })));
const ObserveMode = lazy(() => import('./modes2').then(m => ({ default: m.ObserveMode })));
const InteropMode = lazy(() => import('./modes2').then(m => ({ default: m.InteropMode })));
const CommsMode = lazy(() => import('./modes3').then(m => ({ default: m.CommsMode })));
const AdminMode = lazy(() => import('./modes3').then(m => ({ default: m.AdminMode })));
const FinanceMode = lazy(() => import('./modes4').then(m => ({ default: m.FinanceMode })));
const HealthMode = lazy(() => import('./modes4').then(m => ({ default: m.HealthMode })));
const KnowledgeMode = lazy(() => import('./modes4').then(m => ({ default: m.KnowledgeMode })));
const FamilyMode = lazy(() => import('./modes4').then(m => ({ default: m.FamilyMode })));
const FirstRunGate = lazy(() => import('./gap').then(m => ({ default: m.FirstRunGate })));
const ProjectsMode = lazy(() => import('./gap').then(m => ({ default: m.ProjectsMode })));
// The Ledger frame's own pages (PHASE_B_PLAN.md §6), loaded when their route is first visited.
const WorkOverview = lazy(() => import('./pages/WorkOverview').then(m => ({ default: m.WorkOverview })));
const Timeline = lazy(() => import('./pages/Timeline').then(m => ({ default: m.Timeline })));
const TrustOverview = lazy(() => import('./pages/TrustOverview').then(m => ({ default: m.TrustOverview })));
const ArtifactsPage = lazy(() => import('./pages/ArtifactsPage').then(m => ({ default: m.ArtifactsPage })));
const Glance = lazy(() => import('./pages/Glance').then(m => ({ default: m.Glance })));
/** The Ledger frame moves between pages with hud-routing's own functions. */
const FRAME_NAVIGATION: FrameNavigation = { navigate: navigateHud, closeOverlay: closeHudOverlay };
const HOME_PATH = '/v2/cockpit';
/** Settings › Personalisation (the Console panel `appearance`). */
const PERSONALISATION_PATH = '/v2/console/appearance';
/** The audit chain's verdict as signals/hooks.ts useAuditVerify reads it ("Verify the record again"). */
const AUDIT_VERIFY_PATH = '/api/security/audit/verify';

const CHAT_SESSION_KEY = 'nerva.chat.session_id';
const CHAT_RECIPIENT_KEY = 'nerva.chat.recipient';
const recipientPrincipal = () => JSON.stringify([getToken(), getAdminToken(), ownerSession()?.signed_in ? csrfToken() : '']);
/** The owner's choice of recipient, kept for this tab; `name` is the display name the hub's roster
 *  gave the agent when it was chosen (a choice refused after a reload names the agent as the owner
 *  knew it, not by its id). */
type SavedRecipient = { agent: string; name?: string; session: string | null; credential: string };
function savedRecipient(): SavedRecipient | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(CHAT_RECIPIENT_KEY) || 'null');
    return value && typeof value.agent === 'string' && typeof value.credential === 'string'
      && (value.session === null || typeof value.session === 'string')
      && (value.name === undefined || typeof value.name === 'string') ? value : null;
  } catch { return null; }
}
async function recipientCredential(): Promise<string> {
  if (isNetworkedOrigin() && !getToken() && !ownerSession()) await loadOwnerSession();
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(recipientPrincipal()));
  return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
}
/** Notes the display name the hub's roster gives each agent it served (rows from GET /api/agents). */
function noteRosterNames(names: Map<string, string>, agents: readonly any[] | undefined): void {
  for (const agent of agents || []) {
    if (agent && agent.rosterSource === 'api' && typeof agent.id === 'string' && typeof agent.name === 'string' && agent.name.trim()) {
      names.set(agent.id, agent.name.trim());
    }
  }
}
function savedChatSession(): string | null {
  try { return sessionStorage.getItem(CHAT_SESSION_KEY); } catch { return null; }
}
export function visibleTurns(turns: any[]): any[] {
  return turns.map((tn: any) => {
    const ts = fmtTimeShort(new Date(tn.timestamp || Date.now()));
    const calls = tn.role === 'assistant' ? modelCalls(tn.model_calls) : [];
    const activity = tn.role === 'assistant' && !('foreign_origin' in tn) && !('tainted' in tn)
      && typeof tn.agent_id === 'string' && tn.agent_id.trim()
      ? toolActivity(tn.tool_activity) : null;
    const ownerTurn = tn.role === 'user' && !('foreign_origin' in tn) && !('tainted' in tn);
    const source = ownerTurn ? historySourceLabel(tn.history_source) : null;
    return tn.role === 'user'
      ? { role: 'user', text: tn.content, ts, ...(source ? { attachmentNames: [source] } : {}),
        ...(ownerTurn ? { boardSources: boardSources(tn.board_sources) } : {}) }
      : restoreVisionTurn(tn,ts) || { role: 'agent', who: tn.agent_id || 'jarvis', role_label: '', text: tn.content, ts,
        _unattributed: tn.role !== 'assistant' || typeof tn.agent_id !== 'string' || !tn.agent_id.trim(),
        ...(calls.length ? { prov: { models: calls } } : {}),
        ...(activity ? { toolActivity: activity } : {}) };
  });
}

function App({ floating = false }: {
  /** The 420 × 620 desktop window (main.tsx, `?desktop=floating` with the native bridge). */
  floating?: boolean;
} = {}) {
  const appearance = useAppearance();
  const { look, density, scanline, dotgrid, accent } = appearance.preferences;
  const schemePreference = appearance.preferences.scheme as SchemePreference;
  const motion = appearance.motion;
  // Theme contract v1 §7: `scheme: system` follows the OS colour scheme live; the resolved scheme
  // (never `system`) goes on .hud-root and, with the other axes, on <html> where the themes select.
  // The OS reading is followed whatever the scheme, so the first frame after choosing System is
  // already right even when the OS changed while Dark or Light was chosen.
  const [prefersDark, setPrefersDark] = useState(readPrefersDark);
  useEffect(() => {
    setPrefersDark(readPrefersDark());
    return subscribePrefersDark(setPrefersDark);
  }, []);
  const scheme = resolveScheme(themeById(look), schemePreference, prefersDark);
  useLayoutEffect(() => {
    applyAppearanceToDocument({ ...appearance.preferences, motion }, prefersDark);
  }, [appearance.preferences, motion, prefersDark]);
  // One owner instance (§7): every component reads and changes appearance through this provider.
  // The shared API takes a plain string key; useAppearance ignores one outside the fixed fields.
  const appearanceApi = useMemo<AppearanceApi>(() => ({
    preferences: appearance.preferences, status: appearance.status,
    setPreference: (key: string, value: string) => appearance.setPreference(key as AppearanceKey, value),
    error: appearance.error, retry: appearance.retry, motion: appearance.motion,
  }), [appearance.preferences, appearance.setPreference, appearance.status, appearance.error, appearance.retry, appearance.motion]);
  const setLook = useCallback((value: string) => appearance.setPreference('look', value), [appearance.setPreference]);
  const setScheme = useCallback((value: string) => appearance.setPreference('scheme', value), [appearance.setPreference]);
  const setDensity = useCallback((value: string) => appearance.setPreference('density', value), [appearance.setPreference]);
  const setScanline = useCallback((value: string) => appearance.setPreference('scanline', value), [appearance.setPreference]);
  const setDotgrid = useCallback((value: string) => appearance.setPreference('dotgrid', value), [appearance.setPreference]);
  const setFont = useCallback((value: string) => appearance.setPreference('font', value), [appearance.setPreference]);
  const setMotion = useCallback((value: string) => appearance.setPreference('motion', value), [appearance.setPreference]);
  const setAccent = useCallback((value: string) => appearance.setPreference('accent', value), [appearance.setPreference]);
  // H221 — the language is an appearance preference (cached + synced like the others); the
  // masthead's EN | RO radio group and the sheet's Language rows both set it by code.
  const lang = appearance.preferences.lang;
  const setLang = useCallback((value: string) => appearance.setPreference('lang', value), [appearance.setPreference]);
  // DEMO mode (opt-in, watermarked): OFF by default → the HUD shows ONLY real
  // backend data + honest empty states; ON → fills the seeded demo corpus.
  const [demo, setDemo] = useDemoMode();
  // Voice preferences (persisted): mode = hands-free | ptt; tts = server | browser | off;
  // lang = auto | ro | en; barge = off | on (experimental talk-over interrupt)
  const [voiceCfg, setVoiceCfg] = useState(() => { const d = { mode: 'hands-free', tts: 'server', lang: 'auto', barge: 'off' }; try { return { ...d, ...JSON.parse(localStorage.getItem('hud.voice') || '{}') }; } catch { return d; } });
  const setVoice = (patch) => setVoiceCfg((c) => ({ ...c, ...patch }));

  // The document is titled in the owner's language (nav/routes pageTitle).
  const { route, notice, dismissNotice } = useHudRoute(floating, lang);
  // PHASE_B_PLAN.md §4.4: the route notice names the page the router fell back to when it raised
  // the notice, recorded here as the notice appears (never the page on screen later); once the
  // owner moves on to another page the notice is no longer news and is withdrawn.
  const [routeNoticeAt, setRouteNoticeAt] = useState<{ path: string; page: RoutePage } | null>(null);
  if (notice && !routeNoticeAt) setRouteNoticeAt({ path: route.path, page: pageForRoute(route) });
  if (!notice && routeNoticeAt) setRouteNoticeAt(null);
  useEffect(() => {
    if (notice && routeNoticeAt && route.path !== routeNoticeAt.path) dismissNotice();
    // useHudRoute hands a new dismissNotice on every render; the route and the notice decide
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notice, routeNoticeAt, route.path]);
  const setMode = useCallback((next: string) => navigateHud('/v2/' + next), []);
  useEffect(() => { const handoff = () => setMode('chat'); window.addEventListener('nerva-desktop-handoff', handoff); return () => window.removeEventListener('nerva-desktop-handoff', handoff); }, []);
  const [agents, setAgents] = useState<any[]>(demo ? V2.AGENTS : []);
  // Whether a poll of the hub has completed since the page loaded (or left the demo sample): its
  // agents, from the hub's roster or not, are then in `agents`. A selected agent that still cannot be
  // confirmed after one is held for want of the roster (recipientHold), not "being checked" for ever.
  const [rosterPolled, setRosterPolled] = useState(false);
  const initialRecipient = useRef(savedRecipient());
  const [activeId, setActiveId] = useState(initialRecipient.current ? '' : 'jarvis');
  const [recipientReady, setRecipientReady] = useState(!initialRecipient.current);
  const recipientGeneration = useRef(0);
  const recipientSelected = useRef(!!initialRecipient.current);
  const recipientPrincipalAtChoice = useRef(recipientPrincipal());
  const [messages, setMessages] = useState<any[]>(demo ? V2.SEED_MESSAGES : []);
  const [currentOutcome, setCurrentOutcome] = useState<TurnOutcome | null>(null);
  const sessionId = useRef<string | null>(savedChatSession());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() => sessionId.current);
  const sessionGeneration = useRef(0);
  const selectedSessionId = useCallback(() => sessionId.current, []);
  const sessionActivityGeneration = useCallback(() =>
    `${sessionGeneration.current}:${turnEpoch.current}:${nextTextTurn.current}:${latestTextTurn.current}`, []);
  // Why App last dropped the recipient (home/talk/types.ts RecipientRefusal). It is state, not a
  // ref: a refusal must redraw at once even when the recipient was already empty and not ready (a
  // saved choice refused while it was being checked), or the composer keeps saying
  // "Checking the selected agent…" until something else redraws.
  const [recipientRefusal, setRecipientRefusal] = useState<RecipientRefusal | null>(null);
  // The last display name the hub's roster gave each agent (only rows it served: a demo or seed name
  // is not the hub's), so an agent that leaves the roster is still named as the owner knew it. Noted
  // as a poll is committed (below), so a choice made in that same frame already carries the name.
  const knownNames = useRef(new Map<string, string>());
  useEffect(() => { noteRosterNames(knownNames.current, agents); }, [agents]);
  const rememberRecipient = useCallback((id: string) => {
    const generation = ++recipientGeneration.current;
    // the owner's own choice settles a saved one still being checked: a later check (the next
    // roster poll) must neither restore over it nor refuse it
    initialRecipient.current = null;
    recipientSelected.current = id !== 'jarvis';
    recipientPrincipalAtChoice.current = recipientPrincipal();
    setActiveId(id); setRecipientReady(true); setRecipientRefusal(null);
    try { sessionStorage.removeItem(CHAT_RECIPIENT_KEY); } catch { /* storage unavailable */ }
    if (demo || id === 'jarvis') return;
    const name = knownNames.current.get(id);
    const saved = (credential: string) => JSON.stringify({ agent: id, ...(name ? { name } : {}), session: sessionId.current, credential });
    try { sessionStorage.setItem(CHAT_RECIPIENT_KEY, saved('')); } catch { /* storage unavailable */ }
    void recipientCredential().then(credential => {
      if (generation === recipientGeneration.current) {
        try { sessionStorage.setItem(CHAT_RECIPIENT_KEY, saved(credential)); } catch { /* storage unavailable */ }
      }
    }).catch(() => {});
  }, [demo]);
  // Drops the recipient, saying why. Nothing is sent until the owner chooses again: the message never
  // goes to a substitute (the composer's To reads "Choose an agent" and its line gives the reason).
  const clearRecipient = useCallback((refusal: RecipientRefusal) => {
    ++recipientGeneration.current;
    initialRecipient.current = null;
    recipientSelected.current = false;
    try { sessionStorage.removeItem(CHAT_RECIPIENT_KEY); } catch { /* storage unavailable */ }
    setActiveId(''); setRecipientReady(false); setRecipientRefusal(refusal);
  }, []);
  const selectSession = useCallback((id: string, turns?: any[]) => {
    // Convert a supplied snapshot before touching the selected id or its storage.
    // A malformed server response must not leave a half-applied recovery.
    const mappedTurns = turns ? visibleTurns(turns) : undefined;
    sessionGeneration.current++;
    sessionRecovery.current?.allowExplicitSelection(id);
    if (id !== sessionId.current || turns) setCurrentOutcome(null);
    if (recipientSelected.current && id !== sessionId.current && (sessionId.current || turns)) {
      clearRecipient({ reason: 'conversation' });
    } else if (!sessionId.current) {
      const saved = savedRecipient();
      if (saved?.session === null) {
        try { sessionStorage.setItem(CHAT_RECIPIENT_KEY, JSON.stringify({ ...saved, session: id })); } catch { /* storage unavailable */ }
      }
    }
    sessionId.current = id;
    setActiveSessionId(id);
    try { sessionStorage.setItem(CHAT_SESSION_KEY, id); } catch { /* storage unavailable */ }
    if (mappedTurns) setMessages(mappedTurns);
  }, [clearRecipient]);
  useEffect(() => {
    const saved = initialRecipient.current;
    if (!saved || demo || !agents.some(agent => agent.rosterSource === 'api')) return;
    const generation = recipientGeneration.current;
    void recipientCredential().then(credential => {
      if (generation !== recipientGeneration.current || !initialRecipient.current) return;
      initialRecipient.current = null;
      // A saved choice is used only by the sign-in that made it, in its conversation, while the
      // roster still offers the agent; otherwise it is refused, and the refusal says which rule held.
      if (!saved.credential) clearRecipient({ reason: 'unverified' });
      else if (saved.credential !== credential) clearRecipient({ reason: 'signin' });
      else if (saved.session !== sessionId.current && saved.session !== null) clearRecipient({ reason: 'conversation' });
      else if (!selectableChatAgents(agents, false).some(agent => agent.id === saved.agent)) {
        clearRecipient({ reason: 'unavailable', agent: saved.agent, name: knownNames.current.get(saved.agent) ?? saved.name });
      }
      else {
        recipientSelected.current = true;
        recipientPrincipalAtChoice.current = recipientPrincipal();
        setActiveId(saved.agent); setRecipientReady(true); setRecipientRefusal(null);
      }
    }).catch(() => {
      // No digest here (crypto.subtle needs a secure origin): the saved choice can never be checked,
      // so it is refused now rather than left at "Checking…" — unless the owner chose meanwhile.
      if (generation !== recipientGeneration.current || !initialRecipient.current) return;
      clearRecipient({ reason: 'unverified' });
    });
  }, [agents, demo, clearRecipient]);
  useEffect(() => {
    let credential = recipientPrincipal();
    let discoveringOwner = isNetworkedOrigin() && !getToken() && !ownerSession();
    const check = () => {
      const next = recipientPrincipal();
      if (next === credential) return;
      credential = next;
      if (discoveringOwner && ownerSession() && !getToken()) {
        discoveringOwner = false;
        if (recipientSelected.current && !initialRecipient.current) recipientPrincipalAtChoice.current = next;
        return;
      }
      if (initialRecipient.current) return; // first owner-session discovery is checked by restoration
      clearRecipient({ reason: 'signin' });
    };
    const off = onOwnerSession(check);
    window.addEventListener('storage', check);
    window.addEventListener('focus', check);
    return () => { off(); window.removeEventListener('storage', check); window.removeEventListener('focus', check); };
  }, [clearRecipient]);
  useEffect(() => {
    if (demo || initialRecipient.current || activeId === 'jarvis' || !activeId ||
      !agents.some(agent => agent.rosterSource === 'api') ||
      selectableChatAgents(agents, false).some(agent => agent.id === activeId)) return;
    clearRecipient({ reason: 'unavailable', agent: activeId, name: knownNames.current.get(activeId) });
  }, [activeId, agents, demo, clearRecipient]);
  const sessionRecovery = useRef<SessionRecovery | null>(null);
  if (!sessionRecovery.current) {
    sessionRecovery.current = new SessionRecovery(
      () => apiGet('/memory', { admin: true }),
      (snapshot) => selectSession(snapshot.session, snapshot.turns),
    );
  }
  useEffect(() => {
    const selected = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (typeof detail?.sessionId === 'string' && Array.isArray(detail.turns)) {
        setCurrentOutcome(null);
        if (turnBusy.current || textTurns.current.size) {
          abortRef.current?.abort(); abortRef.current = null;
          turnEpoch.current++; turnBusy.current = false;
          for(const turn of textTurns.current.values()){turn.controller.abort();turn.settle('');}
          setThinking(null);
        }
        selectSession(detail.sessionId, detail.turns);
      }
    };
    window.addEventListener('nerva:session-selected', selected);
    return () => window.removeEventListener('nerva:session-selected', selected);
  }, [selectSession]);
  const [thinking, setThinking] = useState(null);
  useDesktopConversation(setMessages, !!thinking, demo, selectedSessionId,
    sessionRecovery.current, sessionActivityGeneration);
  useQuickEntryFocus();
  useDesktopDecisionNotifications(!floating && !demo);
  const inspectBlend = useRef<((file: File) => boolean) | null>(null);
  const [projectForChat, setProjectForChat] = useState<WorkshopRef | null>(null);
  useLayoutEffect(() => setProjectForChat(null), [activeId, activeSessionId]);
  const [boardResultForChat, setBoardResultForChat] = useState<BoardResultRef | null>(null);
  useLayoutEffect(() => setBoardResultForChat(null), [activeId, activeSessionId, demo]);
  useLayoutEffect(() => { if (route.mode !== 'chat') setBoardResultForChat(null); }, [route.mode]);
  const discussBoardResult = (ref: BoardResultRef) => {
    setBoardResultForChat(ref);
    setMode('chat');
  };
  // bumped after every successful explicit save so Memory › Saved replies refetches
  const [artifactsRefresh, setArtifactsRefresh] = useState(0);
  const bumpArtifacts = useCallback(() => setArtifactsRefresh((n) => n + 1), []);
  // mic/voice state is owned by the useVoice loop (defined below), not a bare flag
  // `palette` opens the search and command sheet (nav/CommandSheet), which can open filtered to
  // panels (the backtick, the contents column's "Find a panel…").
  const [palette, setPalette] = useState(false);
  const [sheetFilter, setSheetFilter] = useState<'panels' | null>(null);
  const [cinema, setCinema] = useState(false);
  const [provModal, setProvModal] = useState(null);
  const [dossier, setDossier] = useState(null);
  // Owner B0 finding: onboarding must find the user, not vice-versa. On boot
  // (never in demo mode, never after a dismiss) ask the command center whether
  // the install is usable; if not, land on it. An API error never blocks the HUD.
  const [firstRun, setFirstRun] = useState(false);
  useEffect(() => {
    if (demo) return;
    try { if (localStorage.getItem(FIRST_RUN_DISMISS_KEY) === '1') return; } catch { /* ignore */ }
    apiGet('/api/onboarding/command-center')
      .then((cc: any) => { if (shouldShowFirstRun(cc)) setFirstRun(true); })
      .catch(() => {});
  }, [demo]);
  // What Cinema's briefing wall reads (the read-only decision cards of api/loaders decisionCard()).
  const [decisions, setDecisions] = useState(() => demo ? V2.DECISIONS.map((d, i) => ({ ...d, _id: 'd' + i })) : []);
  // P1 live-data state — empty by default (honest); demo pre-seeds, backend overwrites. Cinema and
  // the pet companion read these; the frame and the pages read the hub snapshot below.
  const [tasks, setTasks] = useState([]); // the autonomy queue (/tasks)
  const [calendar, setCalendar] = useState(demo ? V2.CALENDAR : []);
  const [heartbeat, setHeartbeat] = useState(demo ? V2.HEARTBEAT : []);
  const [serverUp, setServerUp] = useState(false);
  const [safeMode, setSafeMode] = useState(SAFE_MODE_OFF);
  const power = usePower(demo);   // H182: battery, resume, keep-awake
  const [pressure, dismissPressure] = usePressure(demo);   // H161: memory/disk running out
  const [firstRunDismissed, setFirstRunDismissed] = useState(() => {
    try { return localStorage.getItem('hud.seen') === '1'; } catch { return false; }
  });
  const [llm, setLlm] = useState({ state: 'unknown', model: null, residents: [] });
  const [trust, setTrust] = useState({ mic: 'on', strict_local: false });
  const [sources, setSources] = useState({ tasks: false, trust: false });
  const [locality, setLocality] = useState(null); // {local_pct} from real runs, or null
  // The hub as one snapshot (frame/types.ts), committed beside the setters above.
  const [hub, setHub] = useState<HubSnapshot>(() => initialHubSnapshot(demo));
  // H202: a roster change (create, rename, retire, restore) refreshes the live data now,
  // not at the next 30 s poll.
  const refreshNow = useRef<() => void>(() => {});

  // PHASE_B_PLAN.md §2.3, §10.6: App keeps a minute clock and Cinema keeps the 1-second one
  // (SecondsCinema), so the frame and the pages are not re-rendered every second. The pages read
  // it as a Date that changes once a minute, on the minute.
  const clock = useMinuteClock();
  const clockMinute = Math.floor(clock.getTime() / 60_000);
  const minuteClock = useMemo(() => new Date(clockMinute * 60_000), [clockMinute]);
  const t = V2.I18N[lang];
  // %-local is honest, in priority order: a real measured split from /api/analytics/
  // locality (the brand metric, from run-history routes) → strict-local proof (100%)
  // → demo sample → unknown (hidden, never faked).
  // …and WHERE it came from, so the wall can label it truthfully: a strict-local 100% is a
  // correct inference from governance, not a measurement, and must not display as one.
  const { pct: localPct, source: localPctSource } = localityFigure({ locality, trust, demo });
  const liveModes = useLiveModes(); // P4: stream live data into the capability modes; reports which keys are live
  // H22 — first-party page-view beacon. Fires once on load (privacy-first, no
  // cookies/PII; see analytics.ts), then once per HUD view change.
  // URL routing reports the actual mode or selected console page. initAnalytics()
  // is idempotent and already fired the initial view, so the per-mode effect skips
  // its first run to avoid a duplicate on mount.
  useEffect(() => { initAnalytics(); }, []);
  const _firstView = useRef(true);
  useEffect(() => {
    if (_firstView.current) { _firstView.current = false; return; }
    trackPageview(route.path);
  }, [route.path]);
  // `hud.lang` stays written for the v1 shell (agents/web/static/i18n.js reads it); the document
  // carries lang/dir so assistive tech and :lang() styling follow the HUD's language.
  // Not while the first hydration is pending: a stale default must not clobber a legacy choice
  // (appearance.ts journals that choice, so `lang` already holds it, but the write can wait).
  useEffect(() => {
    const entry = V2.LANGUAGES.find(l => l.code === lang);
    document.documentElement.lang = lang;
    document.documentElement.dir = entry?.dir || 'ltr';
    if (appearance.status === 'loading') return;
    try { localStorage.setItem('hud.lang', lang); } catch { /* ignore */ }
  }, [lang, appearance.status]);
  // v1 ↔ v2 coherence: the v1 shell's setLocale() (agents/web/static/i18n.js) writes hud.lang and
  // fires `jarvis:locale_changed`; the same write reaches other tabs as a `storage` event.
  useEffect(() => {
    const adopt = (code: unknown) => {
      if (typeof code === 'string' && code !== lang && V2.LANGUAGES.some(l => l.code === code)) setLang(code);
    };
    const onLocale = (e: Event) => adopt((e as CustomEvent).detail);
    const onStorage = (e: StorageEvent) => { if (e.key === 'hud.lang') adopt(e.newValue); };
    window.addEventListener('jarvis:locale_changed', onLocale);
    window.addEventListener('storage', onStorage);
    return () => { window.removeEventListener('jarvis:locale_changed', onLocale); window.removeEventListener('storage', onStorage); };
  }, [lang, setLang]);
  useEffect(() => { try { localStorage.setItem('hud.voice', JSON.stringify(voiceCfg)); } catch { /* ignore */ } }, [voiceCfg]);
  // Re-seed (or clear) the demo-only cockpit corpus when DEMO toggles at runtime.
  // Demo ON also restores the pristine ADMIN/OBSERVE fiction — the live cycles in
  // useLiveModes strip and refill those corpora in place, and demo must keep its
  // labelled complete picture even while the poller runs.
  useEffect(() => {
    setDecisions(demo ? V2.DECISIONS.map((d, i) => ({ ...d, _id: 'd' + i })) : []);
    setMessages(demo ? V2.SEED_MESSAGES : []);
    if (demo) restoreDemoCorpora();
  }, [demo]);

  // Rehydrate the visible transcript from server-persisted memory on load, so a
  // page refresh no longer drops the conversation (2026-07-24 QA finding). The
  // turns already persist server-side (ConversationMemory → disk); the HUD just
  // never re-fetched them. `GET /memory` returns the current session's last turns.
  // Runs once; never clobbers a conversation the user started before it resolved.
  const _rehydrated = useRef(false);
  useEffect(() => {
    if (demo || _rehydrated.current) return;
    _rehydrated.current = true;
    let active = true;
    const savedId = savedChatSession();
    const expectedSessionGeneration = sessionGeneration.current;
    const expectedTurnEpoch = turnEpoch.current;
    const expectedNextTextTurn = nextTextTurn.current;
    const expectedLatestTextTurn = latestTextTurn.current;
    const isCurrent = () => active && sessionGeneration.current === expectedSessionGeneration &&
      sessionId.current === savedId && turnEpoch.current === expectedTurnEpoch &&
      nextTextTurn.current === expectedNextTextTurn &&
      latestTextTurn.current === expectedLatestTextTurn &&
      !turnBusy.current && textTurns.current.size === 0;
    const history = savedId
      ? apiPost('/sessions/resume', { session_id: savedId }, { admin: true }).catch(async (error) => {
          const healed = await sessionRecovery.current?.recover(savedId, error, isCurrent);
          if (healed) return null;  // the shared recovery committed the current session + transcript
          throw error;              // transient, protected or stale: preserve selection and messages
        })
      : apiGet('/memory', { admin: true });
    history
      .then((r: any) => {
        if (!r || !isCurrent()) return;
        if (typeof r?.session === 'string') selectSession(r.session);
        const turns = (r && r.turns) || [];
        if (!turns.length) return;
        const mapped = visibleTurns(turns);
        setMessages((cur) => (cur.length ? cur : mapped));
      })
      .catch(() => {});
    return () => { active = false; _rehydrated.current = false; };
  }, [demo, selectSession]);

  // hotkeys (H209): every shortcut is an action in shortcuts.ts, rebindable from the
  // Keyboard Shortcuts panel (mod+/); nothing here spells a key.
  const [shortcutOverrides, changeShortcuts] = useShortcutOverrides();
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  useEffect(() => {
    const list = shortcutBindings(shortcutOverrides);
    function onKey(e) {
      if (floating || shortcutsOpen) return;   // the panel owns the keyboard while it is open
      const action = matchAction(e, list, 'global');
      if (!action) return;
      // A field owns its keys: only the sheet and the panel answer there, on a chord held
      // with Ctrl/⌘ or Alt, so no letter typed into it (a password included) is eaten.
      // A <select> types to jump to an option (the composer's To), and an editable region takes
      // letters: both own their keys as a field does.
      const tag = (e.target && e.target.tagName ? e.target.tagName : '').toLowerCase();
      const field = tag === 'input' || tag === 'textarea' || tag === 'select' || !!(e.target && e.target.isContentEditable);
      if (field && !firesInInputs(action)) return;
      if (action.id === 'session.palette') { e.preventDefault(); setSheetFilter(null); setPalette((p) => !p); return; }
      // Not over Cinema, which paints above the panel: it would open unseen.
      if (action.id === 'session.shortcuts' && !cinema) { e.preventDefault(); setPalette(false); setShortcutsOpen(true); return; }
      if (cinema) return;   // Cinema owns the keyboard (Esc exits it)
      // The chat transcript is in the tab order (its `role="log"` region), so it is a place a
      // keyboard user reads FROM. Without this, typing a digit while reading jumps to another
      // page and drops focus to <body>; `a` goes to Glance. Same reasoning as the input/textarea
      // bail: a surface you are reading or typing into owns its keys.
      if (e.target && e.target.closest && e.target.closest('[role="log"]')) return;
      if (action.id === 'composer.focus') {
        const box = document.querySelector('[data-composer]') as HTMLInputElement | null;
        if (box) { e.preventDefault(); box.focus(); }
        return;
      }
      e.preventDefault();   // a rebound chord (Ctrl+J, Ctrl+D) runs the HUD action, not the browser's too
      if (action.id.startsWith('mode.')) setMode(action.id.slice(5));
      // Glance is a route, the backtick opens the sheet on panels.
      else if (action.id === 'view.ambient') navigateHud('/v2/glance');
      else if (action.id === 'view.cinema') setCinema(true);   // HUD-v3 cinema mode (full-bleed mesh)
      else if (action.id === 'view.console') { setSheetFilter('panels'); setPalette((p) => !p); }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [cinema, shortcutOverrides, shortcutsOpen]);

  // The conversation's turns. (PHASE_B_PLAN.md §2.4 retired the cockpit's cognition trace, its
  // post-turn snapshot read and its live scoring subscription: they drew routing the chat stream
  // does not report, honesty defects D11 and D15. The working reply shows only what the stream
  // says; the Observe › Cognition panel keeps its own reads.)
  const timers = useRef([]);
  const turnBusy=useRef(false), turnEpoch=useRef(0);
  const abortRef = useRef<AbortController|null>(null); // vision turn
  const textTurns=useRef(new Map<number,{controller:AbortController;settle:(text:string)=>void}>());
  // A state copy of the in-flight turns (textTurns is a ref), so the pages re-render; the agent
  // asked and the time are kept from the moment the reply bubble is reserved.
  const [inflight, setInflight] = useState<readonly { turnId: number; agent: string; askedAt: number }[]>([]);
  const nextTextTurn=useRef(0), latestTextTurn=useRef(0);
  const lastTypedSubmit=useRef({text:'',at:0});
  const questionTurn=useRef<number|null>(null);
  const [question,setQuestion]=useState<Question|null>(null);
  const answerQuestion=useCallback(async(answer:QuestionAnswer)=>{
    if(!question)throw new Error('Question unavailable');
    const id=question.id, owner=questionTurn.current;
    const signal=owner===null?undefined:textTurns.current.get(owner)?.controller.signal;
    if(!signal || signal.aborted)throw new Error('Question unavailable');
    const response=await apiFetchOnce(`/chat/pending/${id}/answer`,{method:'POST',body:answer,signal});
    if(!response.ok)throw new Error('Answer rejected');
    const result=await response.json();
    if(result?.ok!==true || result.status!=='resolved')throw new Error('Answer not acknowledged');
    if(questionTurn.current===owner)setQuestion(current=>current?.id===id?null:current);
  },[question]);

  // DEMO only: when the chat stream fails in the demo sample, a staged reply from the agent the
  // owner wrote to, so the conversation still demos. It invents no routing and no stages: the
  // waiting line names the agent that was asked, as a live turn's does.
  const runMock = useCallback((agent: string) => {
    timers.current.forEach(clearTimeout); timers.current = [];
    setThinking({ label: t.think, route: [agent.toUpperCase()] });
    timers.current.push(setTimeout(() => {
      setThinking(null);
      setMessages((m) => [...m, { role: 'agent', who: agent, role_label: '', ts: fmtTimeShort(new Date()), text: demoReplyFor(agent) }]);
    }, 1200));
  }, [t]);

  // P2 — real streaming turn: POST /chat/stream token-by-token. Resolves with the FINAL reply
  // text so the voice loop can speak it. On /chat/stream failure: honest system notice (or, in
  // the demo sample only, the staged demo reply).
  // H5.16: runTurn is defined before useVoice (which takes runTurn as onTurn), so
  // the token->TTS forward goes through a ref, assigned right after the hook runs.
  const voiceRef = useRef(null);
  const runTurn = useCallback((text:string, source:'typed'|'voice'='typed', excerpts?:ChatAttachment[], directReply=false, history?:HistorySend, onAdmitted?: () => void,
    board?: BoardSend & { onFinished: (ok: boolean) => void }) => new Promise<string>((resolve) => {
    if (recipientSelected.current && recipientPrincipalAtChoice.current !== recipientPrincipal()) { clearRecipient({ reason: 'signin' }); resolve(''); return; }
    if (!demo && (!recipientReady || (activeId !== 'jarvis' && !selectableChatAgents(agents, false).some(agent => agent.id === activeId)))) { resolve(''); return; }
    if (turnBusy.current || (source==='voice' && (thinking || textTurns.current.size>0)) || (thinking && textTurns.current.size===0)) { resolve(''); return; }
    // The turn is sent, typed or hands-free voice: it ends the line about a dropped change of
    // recipient (switchDropped, below). A turn refused above sends nothing and ends nothing.
    setSwitchDropped(null);
    const id=++nextTextTurn.current, epoch=turnEpoch.current;
    latestTextTurn.current=id;
    setCurrentOutcome(null);
    timers.current.forEach(clearTimeout); timers.current = [];
    const ctl = new AbortController();
    let streamed='', closed=false, referenceReported=false, admitted=false, boardReported=false, boardAccepted=false;
    const reportReference = (ok: boolean) => { if (history && !referenceReported) { referenceReported=true; history.onResult(ok); } };
    const reportBoard = (ok: boolean) => { if (board && !boardReported) { boardReported=true; board.onFinished(ok); } };
    const settle=(reply:string)=>{
      if(closed)return;
      closed=true;
      if (board && !boardAccepted) setMessages(messages => messages.filter(message => message._turnId !== id && message._boardTurnId !== id));
      reportBoard(false);
      if (onAdmitted && !admitted) setMessages(messages => messages.filter(message => message._draftTurnId !== id && message._turnId !== id));
      textTurns.current.delete(id);
      setInflight(list => list.filter(turn => turn.turnId !== id));
      if(questionTurn.current===id){questionTurn.current=null;setQuestion(null);}
      if(textTurns.current.size===0 && !turnBusy.current)setThinking(null);
      resolve(reply);
    };
    textTurns.current.set(id,{controller:ctl,settle});
    // Reserve the reply bubble now: a queued request may emit start after a newer one.
    // Phase B stamps (home/talk/types.ts ReplyStamps, epoch ms): _askedAt here, _startedAt on the
    // first `start` frame, _firstTokenAt on the first `token` frame.
    const askedAt = Date.now();
    setInflight(list => [...list, { turnId: id, agent: activeId, askedAt }]);
    setMessages((m) => [...m,
      { role: 'user', text, ts: fmtTimeShort(new Date()), ...(onAdmitted ? { _draftTurnId: id } : {}), ...(board ? { _boardTurnId: id } : {}), ...(history ? { _historyTurnId: id, attachmentNames: [historySourceLabel({ ...history.reference, role: history.role })].filter(Boolean) } : excerpts?.length ? { attachmentNames: excerpts.map(item => item.name) } : {}) },
      { role: 'agent', who: activeId, role_label: '', ts: fmtTimeShort(new Date()), text: '', _turnId:id, _askedAt:askedAt },
    ]);
    setThinking({ label: t.think + ' · routing', route: null });
    const updateBubble=(change:(message:any)=>any)=>setMessages((messages)=>messages.map(message=>message._turnId===id?change(message):message));
    postStream('/chat/stream', { message: text, agent: activeId, tool_events: true,
      ...(source==='typed' && directReply && !text.trim().startsWith('/') ? { reasoning: 'none' } : {}),
      ...(excerpts?.length ? { attachments: excerpts } : {}),
      ...(onAdmitted && excerpts?.length ? { require_full_attachments: true } : {}),
      ...(board ? { board_references: board.boardReferences, ...(board.allowBoardCloud ? { allow_board_cloud: true } : {}) } : {}),
      ...(history ? { history_reference: history.reference } : {}),
      ...(sessionId.current ? { session_id: sessionId.current } : {}) }, (evt) => {
      if(closed||epoch!==turnEpoch.current||ctl.signal.aborted)return;
      if (onAdmitted && !admitted && ['start','token','end'].includes(evt.type)) {
        admitted = true;
        onAdmitted();
      }
      if (evt.type === 'start') {
        if(id===latestTextTurn.current)setThinking({ label: t.think, route: [String(evt.agent || activeId).toUpperCase()] });
        const startedAt=Date.now();
        updateBubble(message=>({...message,who:evt.agent||activeId,_startedAt:message._startedAt??startedAt}));
      } else if (evt.type === 'clarify') {
        const prompt=pendingQuestion(evt);
        if(prompt){questionTurn.current=id;setQuestion(prompt);}
      } else if (evt.type === 'token') {
        streamed += evt.text || '';
        // H5.16: forward the delta to the voice loop's streaming-speak session so
        // sentence #1 is synthesized while the model is still writing sentence #2.
        // No-op unless a voice turn opened a session (typed turns stay silent).
        try { if(source==='voice')voiceRef.current?.pushSpeakDelta(evt.text || ''); } catch { /* never break the stream over TTS */ }
        const tokenAt=Date.now();
        updateBubble(message=>({...message,text:streamed,_firstTokenAt:message._firstTokenAt??tokenAt}));
      } else if (evt.type === 'tool') {
        // H137 — one card per tool call, updated in place (no arguments or results ride here).
        updateBubble(message=>({...message,tools:mergeToolEvent(message.tools,evt.event)}));
      } else if (evt.type === 'outcome_progress') {
        if (id === latestTextTurn.current) setCurrentOutcome(turnOutcome(evt.outcome));
      } else if (evt.type === 'end') {
        if (board) {
          const recorded = boardSources(evt.board_sources);
          const used = Array.isArray(evt.board_sources) && recorded.length === board.boardReferences.length &&
            recorded.every((item, index) => item.board === board.boardReferences[index].board &&
              item.task_id === board.boardReferences[index].task_id && item.source === board.boardReferences[index].source &&
              item.sha256 === board.boardReferences[index].sha256);
          if (!used) {
            setMessages(messages => [...messages.filter(message => message._turnId !== id && message._boardTurnId !== id),
              { role: 'agent', who: 'system', text: lang === 'ro' ? '⚠ Sursa din tablou nu a fost folosită. Pasajele rămân pregătite.' : '⚠ The board source was not used. Your reviewed passages remain staged.', ts: fmtTimeShort(new Date()) }]);
            reportBoard(false); settle(''); return;
          }
          setMessages(messages => messages.map(message => message._boardTurnId === id ? { ...message, boardSources: recorded } : message));
          boardAccepted = true;
          reportBoard(true);
        }
        const referenceUsed = evt.history_source_used === true && typeof evt.session_id === 'string';
        reportReference(referenceUsed);
        if (history && !referenceUsed) {
          setMessages(messages => [...messages.filter(message => message._turnId !== id && message._historyTurnId !== id), { role: 'agent', who: 'system',
            role_label: '', ts: fmtTimeShort(new Date()), text: lang === 'ro'
              ? '⚠ Sursa conversației nu a putut fi folosită. Ciorna și pasajul sunt păstrate; revizuiește sursa înainte de o nouă trimitere.'
              : '⚠ The chat source could not be used. Your draft and passage are preserved; review the source before sending again.' }]);
          settle(''); return;
        }
        const finalText = typeof evt.text === 'string' ? evt.text : streamed;
        const activity = text.trim().startsWith('/') || evt.agent === 'system' ? null : toolActivity(evt.outcome?.tools);
        const calls = modelCalls(evt.model_calls);
        const receipt = calls.length ? { prov: { models: calls } } : {};
        const changed = typeof evt.session_id === 'string' && evt.session_id !== sessionId.current;
        if (typeof evt.session_id === 'string') selectSession(evt.session_id);
        if(id===latestTextTurn.current) setCurrentOutcome(changed && ['/new', '/reset', '/undo'].includes(text.trim())
          ? null : turnOutcome(evt.outcome));
        if (changed && ['/new', '/reset', '/undo'].includes(text.trim())) {
          if (text.trim() === '/undo') {
            const commandEpoch = turnEpoch.current;
            apiPost('/sessions/resume', { session_id: evt.session_id }, { admin: true })
              .then((r: any) => {
                if (sessionId.current === evt.session_id && turnEpoch.current === commandEpoch && Array.isArray(r?.turns)) {
                  selectSession(evt.session_id, r.turns);
                }
              })
              .catch(() => {});
          }
          setMessages([{ role: 'agent', who: evt.agent || activeId, role_label: '', ts: fmtTimeShort(new Date()), text: finalText, _complete: true,
            toolActivity: activity, ...receipt }]);
        } else {
          updateBubble(message=>({...message,text:finalText,who:evt.agent||activeId,approvals:approvalIds(evt.pending_approvals),
            toolActivity:activity,_complete:true,...receipt}));
        }
        // H674: what the owner should know beside the reply (e.g. the summary was deferred).
        const notes = noticeMessages(evt, fmtTimeShort(new Date()));
        if (notes.length) setMessages((m) => [...m, ...notes]);
        settle(finalText);
      }
    }, { signal: ctl.signal, admin: !!history || !!board }).then(() => {
      // EOF without an end frame must still release the composer and voice promise.
      reportReference(false);
      settle(streamed);
    }).catch((err) => {
      reportReference(false);
      if(closed||epoch!==turnEpoch.current){settle(streamed);return;}
      if(!closed && epoch===turnEpoch.current && id===latestTextTurn.current)setCurrentOutcome(null);
      if (history && err?.name !== 'AbortError') {
        setMessages(messages => [...messages.filter(message => message._turnId !== id && message._historyTurnId !== id), { role: 'agent', who: 'system',
          role_label: '', ts: fmtTimeShort(new Date()), text: lang === 'ro'
            ? '⚠ Sursa conversației a fost refuzată sau s-a schimbat. Ciorna și pasajul sunt păstrate; revizuiește din nou.'
            : '⚠ The chat source was refused or changed. Your draft and passage are preserved; review it again.' }]);
        settle(''); return;
      }
      // A user Stop (AbortError) is a clean outcome, not a failure: the partial
      // text already streamed into the bubble stays, no error notice — and the
      // server's disconnect path guarantees no partial is persisted to memory.
      if (err && err.name === 'AbortError') { settle(streamed); return; }
      if (onAdmitted && err?.status === 413 && err?.body?.detail === 'attachment_limit') {
        setMessages(m => [...m, { role: 'agent', who: 'system', role_label: '', ts: fmtTimeShort(new Date()),
          text: lang === 'ro' ? 'Pasajele depășesc limita pentru atașamente. Scurtează selecția sau elimină o referință @file și retrimite.'
            : 'The passages exceed the attachment limit. Shorten a selection or remove an @file reference and send again.' }]);
        settle(''); return;
      }
      if (err?.body?.detail === 'chat_agent_unavailable') {
        setMessages((m) => [...m, { role: 'agent', who: 'system', role_label: '', ts: fmtTimeShort(new Date()),
          text: lang === 'ro'
            ? '⚠ Agentul selectat nu mai este disponibil. Reîmprospătează pagina, alege un agent activ și trimite din nou.'
            : '⚠ The selected agent is no longer available. Refresh the page, choose an enabled agent, and send again.' }]);
        settle('');return;
      }
      // HONESTY: never fabricate a reply. The staged mock is for DEMO only; otherwise
      // surface the real failure (e.g. no model loaded / backend offline).
      if (demo && textTurns.current.size===1) {
        settle('');setMessages(messages=>messages.filter(message=>message._turnId!==id));runMock(activeId);return;
      }
      // In the owner's language, and naming controls the Ledger frame has (the classic ◐ DEMO badge is gone)
      setMessages((m) => [...m, { role: 'agent', who: 'system', role_label: '', ts: fmtTimeShort(new Date()), text: lang === 'ro'
        ? '⚠ Niciun răspuns — backendul de model nu poate fi accesat sau niciun model nu este încărcat. Încarcă un model (Setări › Configurarea modelului) sau, pentru a previzualiza interfața, activează exemplul demo din căutare (Ctrl K).'
        : '⚠ No reply — the model backend is unreachable or no model is loaded. Load a model (Settings › Model setup), or turn the demo sample on from search (Ctrl K) to preview the interface.' }]);
      settle('');
    });
  }).finally(() => { if (!demo) notifyDesktopConversation(); }), [t, activeId, agents, recipientReady, runMock, demo, thinking, selectSession, lang, clearRecipient]);

  const runVision=useCallback(async(text:string,draft:VisionDraft)=>{
    if(turnBusy.current||thinking||textTurns.current.size>0)return;
    turnBusy.current=true;
    setSwitchDropped(null);   // a sent turn ends the line about a dropped change of recipient (runTurn)
    setCurrentOutcome(null);
    const epoch=++turnEpoch.current,controller=new AbortController();abortRef.current=controller;
    setMessages(messages=>[...messages,{role:'user',text,imageNames:[...draft.names],ts:fmtTimeShort(new Date())}]);
    setThinking({label:'Vision analysis',route:null});
    try {
      const answer=await describeImages(text,draft,controller.signal);
      if(epoch!==turnEpoch.current||controller.signal.aborted)return;
      setMessages(messages=>[...messages,{role:'vision',...answer,ts:fmtTimeShort(new Date())}]);
    } catch(error){
      if(epoch!==turnEpoch.current||controller.signal.aborted)return;
      setMessages(messages=>[...messages,{role:'agent',who:'system',text:`Vision analysis failed: ${(error as Error).message}`,ts:fmtTimeShort(new Date())}]);
    } finally {
      if(epoch===turnEpoch.current){turnBusy.current=false;abortRef.current=null;setThinking(null);}
    }
  },[thinking]);
  const stopTurn=useCallback(()=>{
    questionTurn.current=null;setQuestion(null);
    turnEpoch.current++;
    for(const turn of textTurns.current.values()){turn.controller.abort();turn.settle('');}
    abortRef.current?.abort();abortRef.current=null;turnBusy.current=false;
    setCurrentOutcome(null);
    timers.current.forEach(clearTimeout);timers.current=[];setThinking(null);
  },[]);
  // Whom the owner may choose: the hub's roster offers them (selectableChatAgents); without that
  // roster, Jarvis alone — App's own default, which needs none (runTurn and submit take it so). The
  // To reads the same rule (home/talk/RecipientPicker.tsx recipientChoosable) to hold its switch.
  const canChooseRecipient = useCallback((id: string) => recipientChoosable(id, agents, demo), [agents, demo]);
  // The recipient changes; the Dossier does not open (opening an agent never changes who the owner
  // writes to, PHASE_B_PLAN.md §3.2). It stops a reply being written, so while one is in flight it is
  // called only once the owner has answered the To's question (RecipientPicker); "Write to <Agent>"
  // from the sheet or the Dossier calls it at once only when no reply is being written (writeTo).
  const selectChatAgent=useCallback((id:string)=>{
    if(!canChooseRecipient(id)) return;
    if(id!==activeId)stopTurn();
    rememberRecipient(id);
  },[activeId,canChooseRecipient,stopTurn,rememberRecipient]);
  // A change of recipient the owner asked for while a reply was being written, waiting for the
  // answer in the composer's To (home/talk/types.ts RecipientSwitch; PHASE_B_PLAN.md §12 item 11).
  // App keeps it, so the question outlives the composer: leaving Home and coming back shows it
  // again. Nothing switches by itself. It belongs to the recipient it would replace, to the side of
  // the demo boundary it was asked on, and to an agent a roster the hub served still offers: when
  // any of those moves it is dropped, in the same frame (liveSwitch) and then from the state. A poll
  // the hub did not serve (GET /api/agents failed once; the loader's /status rows are not the
  // roster) drops nothing, as it drops no recipient (the effect that refuses one waits for a served
  // roster): the question stays until the owner answers it, Send stays held, and the To holds only
  // its switch, saying why, until a served roster offers the agent (switchStanding 'held').
  const [recipientSwitch, setRecipientSwitch] = useState<RecipientSwitch | null>(null);
  const switchStands = !!recipientSwitch && recipientSwitch.from === activeId && recipientSwitch.demo === demo
    && recipientSwitch.id !== activeId;
  const liveSwitch = switchStands && switchStanding(recipientSwitch!.id, agents, demo) !== 'gone' ? recipientSwitch : null;
  // A question dropped because a roster the hub served no longer offers the agent asked for is not
  // dropped in silence: the composer says so on one line (recipientSwitchDropped) until the next turn
  // sent, typed or hands-free voice (runTurn and runVision end it once they send; a turn they refuse
  // ends nothing), a change of recipient (`from`), the demo boundary, or the owner's Dismiss. Send is
  // free meanwhile. A voice turn goes to the recipient kept, as ever (PHASE_B_PLAN.md §12 item 12).
  const [switchDropped, setSwitchDropped] = useState<RecipientSwitchDropped | null>(null);
  const switchGone = switchStands && !liveSwitch;
  useLayoutEffect(() => {
    if (!recipientSwitch || liveSwitch) return;
    if (switchGone) {
      const name = knownNames.current.get(recipientSwitch.id) ?? recipientSwitch.name;
      setSwitchDropped({ id: recipientSwitch.id, ...(name ? { name } : {}), from: recipientSwitch.from, demo: recipientSwitch.demo });
    }
    setRecipientSwitch(null);
  }, [recipientSwitch, liveSwitch, switchGone]);
  const liveDropped = switchDropped && switchDropped.from === activeId && switchDropped.demo === demo ? switchDropped : null;
  useLayoutEffect(() => { if (switchDropped && !liveDropped) setSwitchDropped(null); }, [switchDropped, liveDropped]);
  const askRecipientSwitch = useCallback((id: string | null) => {
    // the last name the hub's roster gave the agent goes with the question, so it names the agent as
    // the owner knew it if the roster is then not served
    const name = id === null ? undefined : knownNames.current.get(id);
    setRecipientSwitch(id === null ? null : { id, from: activeId, demo, at: Date.now(), ...(name ? { name } : {}) });
  }, [activeId, demo]);
  const submit=useCallback((text:string,vision?:VisionDraft,excerpts?:ChatAttachment[],directReply=false,options?:HistorySend | { awaitAdmission: true } | BoardSend)=>{
    const history = options && 'reference' in options ? options : undefined;
    if (recipientSelected.current && recipientPrincipalAtChoice.current !== recipientPrincipal()) { clearRecipient({ reason: 'signin' }); return false; }
    if (!demo && (!recipientReady || (activeId !== 'jarvis' && !selectableChatAgents(agents, false).some(agent => agent.id === activeId)))) return false;
    if(turnBusy.current || (vision && (thinking||textTurns.current.size>0)) || (thinking && textTurns.current.size===0))return false;
    if(!demo&&vision?.review_token && (vision.session_id!==sessionId.current || vision.agent!==activeId))return false;
    // runVision and runTurn end the line about a dropped change of recipient once they send
    if(vision)void runVision(text,vision);
    else {
      const now=Date.now();
      if(lastTypedSubmit.current.text===text && now-lastTypedSubmit.current.at<500)return false;
      lastTypedSubmit.current={text,at:now};
      if (options && 'boardReferences' in options) return new Promise<boolean>(resolve => {
        const finish = (ok: boolean) => {
          if (!ok && lastTypedSubmit.current.at === now && lastTypedSubmit.current.text === text) lastTypedSubmit.current = {text:'',at:0};
          resolve(ok);
        };
        void runTurn(text, 'typed', undefined, directReply, undefined, undefined,
          { ...options, onFinished: finish }).catch(() => finish(false));
      });
      if (options && 'awaitAdmission' in options && excerpts?.length) return new Promise<boolean>(resolve => {
        let admitted = false;
        const finish = () => {
          if (!admitted && lastTypedSubmit.current.at === now && lastTypedSubmit.current.text === text) lastTypedSubmit.current = {text:'',at:0};
          resolve(admitted);
        };
        void runTurn(text, 'typed', excerpts, directReply, history, () => { admitted = true; resolve(true); }).then(finish, finish);
      });
      void runTurn(text, 'typed', excerpts, directReply, history);
    }
    return true;
  },[runTurn,runVision,thinking,activeId,agents,demo,recipientReady,clearRecipient]);
  // Hands-free voice loop: mic → local Whisper → runTurn → speak the reply, repeat.
  const voice = useVoice({ lang: voiceCfg.lang === 'auto' ? lang : voiceCfg.lang, mode: voiceCfg.mode, ttsSource: voiceCfg.tts, micMuted: trust.mic === 'off', barge: voiceCfg.barge === 'on', onTurn: (text:string)=>runTurn(text,'voice') });
  useListeningIndicator(demo, voice.active);   // H222: the tray says when Nerva is listening
  voiceRef.current = voice;

  // Leaving DEMO is a provenance boundary, not just a URL toggle. Clear every
  // demo-owned surface in the same event before the banner disappears; the
  // next live refresh may then publish only a current evidence snapshot.
  const clearDemoDerivedState = useCallback(() => {
    setQuestion(null);
    timers.current.forEach(clearTimeout);
    timers.current = [];
    for(const turn of textTurns.current.values()){turn.controller.abort();turn.settle('');}
    questionTurn.current=null;
    abortRef.current?.abort();
    abortRef.current = null;
    turnEpoch.current++;turnBusy.current=false;
    setCurrentOutcome(null);
    setAgents([]);
    setRosterPolled(false);
    setActiveId('jarvis');
    setRecipientReady(true);
    setRecipientRefusal(null);
    setRecipientSwitch(null);
    setSwitchDropped(null);
    recipientSelected.current = false;
    setMessages([]);
    setThinking(null);
    setProvModal(null);
    setDossier(null);
    setDecisions([]);
    setTasks([]);
    setCalendar([]);
    setHeartbeat([]);
    setServerUp(false);
    setLlm({ state: 'unknown', model: null, residents: [] });
    setTrust({ mic: 'on', strict_local: false });
    setSources({ tasks: false, trust: false });
    setLocality(null);
    // The hub snapshot the frame and the pages read is demo-owned too (it holds the demo loader's
    // corpus), so it goes back to Checking… in the same event, not an effect later.
    setHub(initialHubSnapshot(false));
  }, []);
  // Popstate can also take the HUD out of DEMO. A layout effect closes that
  // path before paint; the explicit Exit control clears in its event handler.
  const previousDemo = useRef(demo);
  useLayoutEffect(() => {
    if (previousDemo.current && !demo) clearDemoDerivedState();
    else if (!previousDemo.current && demo) {
      stopTurn(); ++recipientGeneration.current;
      try { sessionStorage.removeItem(CHAT_RECIPIENT_KEY); } catch { /* storage unavailable */ }
      initialRecipient.current = null;
      recipientSelected.current = false;
      setRecipientRefusal(null);
      setRecipientSwitch(null);
      setSwitchDropped(null);
    }
    previousDemo.current = demo;
  }, [clearDemoDerivedState, demo, stopTurn]);
  const exitDemo = useCallback(() => {
    clearDemoDerivedState();
    setDemo(false);
  }, [clearDemoDerivedState, setDemo]);

  useEffect(() => () => {timers.current.forEach(clearTimeout);turnEpoch.current++;for(const turn of textTurns.current.values()){turn.controller.abort();turn.settle('');}abortRef.current?.abort();turnBusy.current=false;}, []);

  // Re-seed the hub snapshot when demo toggles (Checking…, or the demo sample), before the loader
  // below commits the new cycle.
  useEffect(() => { setHub(initialHubSnapshot(demo)); }, [demo]);

  // P1 — load live data and poll every 30s. A generation guard prevents a
  // slower, older poll from replacing a newer evidence snapshot.
  useEffect(() => {
    let active = true;
    let lifecycle = 0;
    const makeRunner = () => createLatestRefreshRunner({
      loadData: () => {
        const id = lifecycle;
        return loadJarvisData(demo, () => active && id === lifecycle);
      },
      loadLocality: demo ? undefined : () => apiGet<any>('/api/analytics/locality'),
      commitData: (d) => {
        noteRosterNames(knownNames.current, d.agents);
        setAgents(d.agents); setRosterPolled(true);
        setTasks(Array.isArray(d.tasks) ? d.tasks : []); setCalendar(d.calendar);
        setHeartbeat(d.heartbeat);
        setServerUp(!!d.serverUp); setSafeMode(d.safeMode || SAFE_MODE_OFF); setLlm(d.llm || { state: 'unknown', model: null, residents: [] });
        setSources(d.sources || { tasks: false, trust: false });
        /* Live approvals REPLACE the list only when the feed actually answered.
           `/autonomy/approvals` is admin-guarded, so on the common token-configured
           install it refuses — and an unconditional set would then wipe the demo cards
           and render an empty queue as "queue clear ✓", an all-clear derived from a 401.
           The conditional is the fail-closed half of the same rule the loader applies:
           absence of evidence never becomes evidence of absence. */
        if (d.sources && d.sources.decisions === true) {
          setDecisions((d.decisions || []).map((it, i) => ({ ...it, _id: 'live' + (it.id != null ? it.id : i) })));
        }
        if (d.trust) setTrust(d.trust);
        setHub((prev) => hubSnapshotFrom(d as HubLoaderData, prev));
      },
      commitLocality: (nextLocality) => {
        setLocality(nextLocality);
        setHub((prev) => hubWithLocality(prev, nextLocality));
      },
    });
    let runner = makeRunner();
    const stop = () => { active = false; lifecycle++; runner.stop(); };
    const invalidate = () => { lifecycle++; runner.stop(); runner = makeRunner(); };
    const resume = (event: PageTransitionEvent) => {
      if (event.persisted && !active) {
        active = true;
        lifecycle++;
        runner = makeRunner();
        void runner.refresh();
      }
    };
    window.addEventListener('beforeunload', invalidate);
    window.addEventListener('pagehide', stop);
    window.addEventListener('pageshow', resume);
    void runner.refresh();
    refreshNow.current = () => { void runner.refresh(); };
    const iv = setInterval(() => { void runner.refresh(); }, 30000);
    return () => {
      refreshNow.current = () => {};
      stop();
      window.removeEventListener('beforeunload', invalidate);
      window.removeEventListener('pagehide', stop);
      window.removeEventListener('pageshow', resume);
      clearInterval(iv);
    };
  }, [demo]);

  const rootAttrs = {
    className: 'hud-root',
    'data-look': look, 'data-scheme': scheme, 'data-accent': accent, 'data-density': density,
    'data-font': appearance.preferences.font, 'data-motion': motion, 'data-scanline': scanline, 'data-dotgrid': dotgrid,
  };

  // Theme contract §8: while Personalisation is open, its own status line (localised, with its own
  // retry) is the one live region that announces an appearance sync failure; the shell keeps quiet.
  const personalisationOpen = route.mode === 'console' && route.panel === 'appearance';
  const appearanceNotice = appearance.error && !personalisationOpen && <div role="status" style={{fontSize:'var(--n-fs-meta)', color:'var(--amber)', padding:'4px 8px'}}>
    {appearance.error} <button className="tool-btn" onClick={appearance.retry}>Retry sync</button>
  </div>;
  const questionPanel=question && <PendingQuestion key={question.id} question={question} onAnswer={answerQuestion} lang={lang}/>;

  const petAgentState: AgentPetState = safeMode.enabled
    ? 'failing'
    : thinking
      ? (String(thinking.label || '').toLowerCase().includes('tool') ? 'tool' : 'thinking')
      : tasks.some((tk: any) => tk?.status === 'running')
        ? 'tool'
        : currentOutcome
          ? 'finishing'
          : 'idle';
  const petStandalone = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('pet_overlay') === '1';
  const principalChanged = recipientSelected.current && recipientPrincipalAtChoice.current !== recipientPrincipal();
  // 'checking' only while there is a selected agent to check: a saved choice being verified, or the
  // one chosen while the hub does not serve the roster that could confirm it. With no agent
  // selected (one was dropped), it is 'choose' whatever the roster: "Checking the selected agent…"
  // would name an agent there is not.
  const recipientStatus = demo || (recipientReady && !principalChanged &&
    (activeId === 'jarvis' || selectableChatAgents(agents, false).some(agent => agent.id === activeId)))
    ? 'ready' : (initialRecipient.current || (activeId && !principalChanged && !agents.some(agent => agent.rosterSource === 'api')))
      ? 'checking' : 'choose';
  // Why there is no recipient to send to, from the first frame it is so: a recipient App still holds
  // is refused before the effect that drops it has run (a changed sign-in, an agent the roster no
  // longer offers); one already dropped carries the reason clearRecipient recorded.
  const recipientNotice: RecipientRefusal | null = recipientStatus !== 'choose' ? null
    : principalChanged ? { reason: 'signin' }
      : activeId && activeId !== 'jarvis' ? { reason: 'unavailable', agent: activeId, name: knownNames.current.get(activeId) }
        : recipientRefusal;
  // A selected agent still not confirmed once a poll has completed without the hub serving the
  // roster (a saved choice, or one chosen before the roster stopped being served): "checking" is no
  // longer what is true. The choice is kept, and confirmed when a served roster offers the agent (the
  // effects above); meanwhile nothing is sent to it, the composer says why, and the To offers Jarvis,
  // which needs no roster. Nothing switches by itself.
  const heldAgent = initialRecipient.current ? initialRecipient.current.agent : activeId;
  const recipientHold: RecipientHold | null = recipientStatus === 'checking' && !demo && rosterPolled && !rosterServed(agents) && heldAgent
    ? (() => {
      const name = knownNames.current.get(heldAgent) ?? initialRecipient.current?.name;
      return { agent: heldAgent, ...(name ? { name } : {}) };
    })() : null;
  const canContinueHistory = () => !turnBusy.current && textTurns.current.size === 0;

  // ---- What the pages read ----------------------------------------------------------------------
  // This tab's in-flight turns with their reply stamps (home/talk/types.ts): the working reply and
  // the running foot read them. A stopped turn leaves the list; its bubble keeps its stamps.
  const turns = useMemo<TabTurn[]>(() => inflight.map((turn) => {
    const bubble: any = messages.find((m: any) => m && m._turnId === turn.turnId);
    const stamp = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
    return { turnId: turn.turnId, agent: turn.agent, askedAt: stamp(bubble?._askedAt) ?? turn.askedAt,
      startedAt: stamp(bubble?._startedAt), firstTokenAt: stamp(bubble?._firstTokenAt) };
  }), [inflight, messages]);
  const openFind = useCallback((filter?: 'panels') => { setSheetFilter(filter ?? null); setPalette(true); }, []);
  const openGlance = useCallback(() => navigateHud('/v2/glance'), []);
  const frameLang: Lang = langOf(lang);

  if (petStandalone) return (
    <AppearanceProvider value={appearanceApi}>
      <div {...rootAttrs} style={{ padding: 12, minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <PetCompanionOverlay enabled={!demo} agentState={petAgentState} standalone />
      </div>
    </AppearanceProvider>
  );

  // What App owns for the conversation, handed to the pages as `talk` (home/talk/types.ts).
  const talkInput = (): TalkInput => ({
    messages, thinking, onStop: stopTurn, onProv: setProvModal, onArtifactSaved: demo ? undefined : bumpArtifacts,
    exportAllowed: !demo, messageActionsAllowed: !demo, messageScope: `${activeId}:${activeSessionId || ''}`, lang, t,
    onSubmit: submit, mic: voice.active, setMic: voice.toggle, voice, cfg: voiceCfg, onCfg: setVoice, micMuted: trust.mic === 'off',
    motion, demo, agent: activeId, agents, recipientStatus, sessionId: activeSessionId || '', selectedTurn: !demo,
    outcome: currentOutcome, power, projectForChat, onProjectReviewed: () => setProjectForChat(null),
    boardResultForChat, onBoardResultReviewed: () => setBoardResultForChat(null), inspectBlend,
    turnActive: !!thinking, canContinue: canContinueHistory, onSelectAgent: selectChatAgent,
    recipientSwitch: liveSwitch, onRecipientSwitch: askRecipientSwitch, recipientRefusal: recipientNotice,
    recipientHold, recipientSwitchDropped: liveDropped, onRecipientSwitchDropped: () => setSwitchDropped(null),
  });

  // The floating desktop window: the conversation page's floating variant.
  if (floating) return <AppearanceProvider value={appearanceApi}><RouteBoundary routeKey={`floating:${demo}`}>
    <div {...rootAttrs} className="hud-root desktop-floating" data-frame-root="ledger">
      {questionPanel}
      <ChatPage variant="floating" talk={talkInput()} turns={turns} hub={hub} lang={frameLang} demo={demo} navigate={navigateHud}
        awaitingAnswer={!!question}
        notices={<>{appearanceNotice}<Notices lang={frameLang} hub={hub} page={pageForRoute(route)} demo={demo} onExitDemo={exitDemo} /></>} />
      {provModal && <ProvModal prov={provModal} onClose={() => setProvModal(null)} />}
    </div></RouteBoundary></AppearanceProvider>;

  // Every other page (PHASE_B_PLAN.md §2.1): the Frame, or Glance full screen; over both, the
  // search and command sheet (Ctrl K, the backtick, the masthead's Find).
  const page = pageForRoute(route);
  const firstRunNotice: FirstRunNotice = {
    dismissed: firstRunDismissed,
    onDismiss: () => { setFirstRunDismissed(true); try { localStorage.setItem('hud.seen', '1'); } catch { /* ignore */ } },
    onDemo: () => setDemo(true),
  };
  const modeBody = (id: string) => ledgerModeBody(id, t, {
    demo, lang, frameLang, agents, localPct, artifactsRefresh,
    onOpenAgent: (agentId: string) => setDossier(agentId),
    onChanged: () => refreshNow.current(),
    onDiscussResult: demo ? undefined : discussBoardResult,
    // Saved replies goes to the conversation itself once the project is staged.
    onDiscussProject: (project: WorkshopRef) => setProjectForChat(project),
    // No composer is mounted beside Saved replies, so this is false and the panel says why.
    onInspectBlend: (file: File) => !!inspectBlend.current?.(file),
  });
  // "Write to <Agent>" (the sheet, the Dossier): the recipient changes, never the Dossier; then the
  // composer takes the focus. A page without a composer goes to Home first. As a pick in the
  // composer's To is: at once when no reply is being written (there is nothing to stop); while one
  // is, which a change of recipient would stop, it becomes the To's question (recipientSwitch) and
  // nothing changes until the owner answers. Writing to the recipient already chosen answers an open
  // question "stay".
  const writeTo = (id: string) => {
    if (!canWriteTo(id)) return;
    if (thinking && id !== activeId) askRecipientSwitch(id);
    else {
      setRecipientSwitch(null);
      if (id !== activeId) selectChatAgent(id);
    }
    if (!document.querySelector('[data-composer]')) navigateHud(HOME_PATH);
    window.setTimeout(() => { (document.querySelector('[data-composer]') as HTMLElement | null)?.focus(); }, 0);
  };
  // Whether App takes this agent as the recipient (selectChatAgent's own rule, as the sheet asks it).
  const canWriteTo = (id: string) => demo || selectableChatAgents(agents, false).some((agent) => agent.id === id);
  // What the sheet may do beyond navigating: open a surface, re-read, or toggle the demo
  // sample. Nothing here decides, signs, stops or changes a mode (nav/commands.ts).
  const sheetActions: SheetActions = {
    onGlance: openGlance,
    onCinema: () => setCinema(true),
    onShortcuts: () => setShortcutsOpen(true),
    onVerifyRecord: () => { if (!demo) void refreshPolled(AUDIT_VERIFY_PATH); },
    onRefresh: () => { refreshNow.current(); if (!demo) void refreshPolled(DOCKET_FEED_PATH, { admin: true }); },
    demo,
    setDemo: (on: boolean) => { if (on) setDemo(true); else exitDemo(); },
    onPersonalisation: () => navigateHud(PERSONALISATION_PATH),
  };
  return (
    <AppearanceProvider value={appearanceApi}>
    <div {...rootAttrs} data-frame-root="ledger">
      {questionPanel}
      <div className="tex-layer tex-glow"></div>
      <div className="tex-layer tex-dotgrid"></div>
      <div className="tex-layer tex-scan"></div>
      <div className="tex-scanbar"></div>
      {page.kind === 'glance' ? (
        <RouteBoundary routeKey={`${route.path}:${demo}`}>
          <Glance hub={hub} lang={frameLang} demo={demo} clock={minuteClock} turns={turns} onExit={closeHudOverlay} navigate={navigateHud} />
        </RouteBoundary>
      ) : (
        <Frame route={route} page={page} hub={hub} adminSettled={liveModes.adminSettled} lang={frameLang} setLang={setLang} scheme={scheme} schemePreference={schemePreference}
          setScheme={setScheme} theme={themeById(look)} navigation={FRAME_NAVIGATION} onFind={openFind} onGlance={openGlance}
          demo={demo} onExitDemo={exitDemo} turns={turns} shortcutOverrides={shortcutOverrides} voiceStatus={voice.status}
          power={power} pressure={pressure} onDismissPressure={dismissPressure} routeNotice={notice}
          routeNoticePage={routeNoticeAt?.page ?? null} onDismissRouteNotice={dismissNotice}
          appearanceNotice={appearanceNotice} firstRun={firstRunNotice}>
          <LedgerPage route={route} page={page} lang={frameLang} demo={demo} hub={hub} clock={minuteClock} talk={talkInput()}
            turns={turns} question={question} live={liveModes.live} onDemo={() => setDemo(true)} onFind={openFind} modeBody={modeBody} />
        </Frame>
      )}
      {provModal && <ProvModal prov={provModal} onClose={() => setProvModal(null)} />}
      {dossier && <RouteBoundary overlay><Dossier id={dossier} onClose={() => setDossier(null)} onOpen={setDossier} agents={agents}
        onChanged={() => refreshNow.current()} onWriteTo={canWriteTo(dossier) ? writeTo : undefined} lang={lang} /></RouteBoundary>}
      {firstRun && <RouteBoundary overlay><FirstRunGate onClose={() => setFirstRun(false)} /></RouteBoundary>}
      <PointerOverlay enabled={!demo} />
      <PetCompanionOverlay enabled={!demo} agentState={petAgentState} />
      <CommandSheet open={palette} filter={sheetFilter} onClose={() => setPalette(false)} lang={frameLang} navigate={navigateHud}
        agents={agents} onOpenAgent={(id) => setDossier(id)} onWriteTo={writeTo} actions={sheetActions}
        ui={{ font: appearance.preferences.font, setFont, look, setLook, scheme: schemePreference, setScheme, density, setDensity, motion: appearance.preferences.motion, setMotion, scanline, setScanline, dotgrid, setDotgrid }}
        accent={accent} setAccent={setAccent} setLang={setLang} shortcutOverrides={shortcutOverrides} />
      {shortcutsOpen && <ShortcutsPanel overrides={shortcutOverrides} onChange={changeShortcuts} onClose={() => setShortcutsOpen(false)} />}
      {cinema && <CinemaWithClock agents={agents} tasks={tasks} llm={llm} trust={trust} sources={sources} demo={demo} localPct={localPct} voice={voice} decisions={decisions} calendar={calendar} heartbeat={heartbeat} serverUp={serverUp} motion={motion} localPctSource={localPctSource} shortcutOverrides={shortcutOverrides} onExit={() => setCinema(false)} t={t} />}
    </div>
    </AppearanceProvider>
  );
}

/** The demo sample's staged replies (runMock), by the agent the owner wrote to. */
function demoReplyFor(agent: string): string {
  const map: Record<string, string> = {
    pepper: 'Pepper has it — your calendar is reconciled and the **14:00 Raiffeisen review** is protected with prep at 13:15.',
    stark: 'Stark pulled the numbers — **Digitaholic MRR is +6.2% WoW**; I flagged the missing churn-cohort slide for the review.',
    vision: "Vision is on it — indexing sources now; I'll have a cited brief in your queue within the hour.",
    veronica: 'Veronica drafted it — held for your review since Ultron flagged a **client name** as sensitive.',
    gecko: "Gecko's watching the markets — EUR/RON steady at 4.97; idle cash is **€4.2k over buffer**, sweep available.",
    hercules: "Hercules logged it — your sleep was 7h12m; tonight's plan is a light mobility session.",
    frigga: 'Frigga keeps that local — noted privately, nothing left the device.',
    friday: 'Friday compiled your brief — **6 items ranked**, weather clear, good day to cycle in.',
    jerome: 'Jerome cued the soundtrack — focus playlist matched to your morning.',
    jarvis: "Understood. I'll handle that directly and keep everything on-device.",
  };
  return map[agent] || map.jarvis;
}

function ProvModal({ prov, onClose }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => previous?.focus();
  }, []);
  return (
    <div className="pal-scrim" onClick={onClose} onKeyDown={(event) => { if (event.key === 'Escape') onClose(); }} style={{ alignItems: 'center', paddingTop: 0 }}>
      <div className="pal" role="dialog" aria-modal="true" aria-labelledby="model-calls-title" onClick={(e) => e.stopPropagation()} style={{ width: 'min(440px,92vw)' }}>
        <div className="pal-input" style={{ borderBottom: '1px solid var(--panel-line)' }}><span className="pc"><Icon d={ICONS.shield} size={16} /></span><span id="model-calls-title" style={{ fontSize: 'var(--n-fs-ui)', letterSpacing: '.04em' }}>MODELS CALLED</span><button ref={closeRef} type="button" className="tool-btn" onClick={onClose} aria-label="Close model call details" style={{marginLeft:'auto'}}>×</button></div>
        <div style={{ padding: 18 }}>
          <p style={{margin:'0 0 12px',color:'var(--ink-2)',fontSize:'var(--n-fs-label)'}}>Measured provider and model for this reply. Physical execution location was not reported.</p>
          <ul style={{margin:0,paddingLeft:20,overflowWrap:'anywhere'}}>{prov.models.map(({provider,model}) => <li key={provider+'\0'+model}><b>{provider}</b> / {model}</li>)}</ul>
        </div>
      </div>
    </div>
  );
}

// Which V2 keys must carry REAL backend data for a capability mode to be "live": ModePage draws a
// mode only when one of them is live, or in demo, and the area-page empty state otherwise.
export const MODE_LIVE_KEYS = {
  trust: ['AUDIT_CHAIN', 'PAYMENTS'], memory: ['MEMORY_STATS'], autonomy: ['AUTONOMY'],
  observe: ['OBSERVE'], interop: ['INTEROP'], admin: ['ADMIN'],
  ...PREVIEW_MODE_LIVE_KEYS,
};

/* ---- The Ledger frame's pages --------------------------------------------------------------- */

/** App's clock (PHASE_B_PLAN.md §2.3): a Date that changes once a minute, on the minute. What
 *  shows seconds keeps a clock of its own (Cinema below, the working reply). */
function useMinuteClock(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const untilNextMinute = () => 60_000 - (Date.now() % 60_000);
    const tick = () => { setNow(new Date()); timer = setTimeout(tick, untilNextMinute()); };
    timer = setTimeout(tick, untilNextMinute());
    return () => { if (timer !== null) clearTimeout(timer); };
  }, []);
  return now;
}

/** Cinema with the 1-second clock it shows: only Cinema re-renders each second, not the frame and
 *  the conversation around it. */
function CinemaWithClock(props: Record<string, unknown>) {
  const clock = useClock();
  return <CinemaMesh {...props} clock={clock} />;
}

type LedgerModeContext = {
  demo: boolean; lang: string; frameLang: Lang; agents: any[]; localPct: number | null; artifactsRefresh: number;
  onOpenAgent: (id: string) => void; onChanged: () => void;
  onDiscussResult?: (ref: BoardResultRef) => void; onDiscussProject: (project: WorkshopRef) => void;
  onInspectBlend: (file: File) => boolean;
};

/* A mode's body inside its ModePage. ModePage decides whether a mode with live sources is drawn
   (the area-page empty state otherwise), so nothing here is gated. Work, Timeline and Trust are
   LedgerPage's (they read the hub, the clock and this tab's turns). */
function ledgerModeBody(mode: string, t: any, ctx: LedgerModeContext): React.ReactNode {
  switch (mode) {
    case 'projects': return <ProjectsMode t={t} demo={ctx.demo} lang={ctx.frameLang} onDiscussResult={ctx.onDiscussResult as any} />;
    case 'jobs': return <JobsWorkspace />;
    // The roster opens the Dossier without changing who the owner writes to (§3.2).
    case 'agents': return <AgentsMode agents={ctx.agents} onOpen={ctx.onOpenAgent} t={t} onChanged={ctx.onChanged} />;
    // Saved replies: the Artifacts panel as a page; "Discuss in chat" stages the project and goes Home.
    case 'artifacts': return <ArtifactsPage lang={ctx.frameLang} demo={ctx.demo} refreshKey={ctx.artifactsRefresh}
      onInspectBlend={ctx.onInspectBlend} onDiscussProject={ctx.onDiscussProject} />;
    case 'memory': return <MemoryMode t={t} demo={ctx.demo} />;
    // demo (§1.4) disables its mode control; lang words its looser-mode confirmation as the running head does
    case 'autonomy': return <AutonomyMode t={t} demo={ctx.demo} lang={ctx.frameLang} />;
    case 'build': return <BuildMode t={t} />;
    case 'observe': return <ObserveMode t={t} />;
    case 'interop': return <InteropMode t={t} />;
    case 'comms': return <CommsMode t={t} />;
    case 'admin': return <AdminMode t={t} />;
    case 'finance': return <FinanceMode t={t} />;
    case 'health': return <HealthMode t={t} />;
    case 'knowledge': return <KnowledgeMode t={t} />;
    case 'family': return <FamilyMode t={t} />;
    default: return <SlotNote lang={ctx.frameLang} />;
  }
}

interface LedgerPageProps {
  route: HudRoute;
  page: RoutePage;
  lang: Lang;
  demo: boolean;
  hub: HubSnapshot;
  clock: Date;
  talk: TalkInput;
  turns: readonly TabTurn[];
  /** App's open mid-turn question (the Work overview's "Needs you", the working reply's wait). */
  question: Question | null;
  live: Readonly<Record<string, boolean>>;
  onDemo: () => void;
  onFind: (filter?: 'panels') => void;
  modeBody: (mode: string) => React.ReactNode;
}

/* The Ledger frame's own pages: every section carries its own source label and its own refused,
   unknown and empty states, so the page is drawn whatever the V2 live keys say (no empty-state
   gate: Trust's MODE_LIVE_KEYS would hide its honest per-section states behind one). */
const OWN_PAGES: ReadonlySet<string> = new Set(['work', 'timeline', 'trust', 'artifacts']);

/* The page body inside the Frame (PHASE_B_PLAN.md §2.1): pageForRoute decides. Its own component,
   so the attention readings are asked only where a page body is drawn (not in Glance or the
   floating window). */
function LedgerPage({ route, page, lang, demo, hub, clock, talk, turns, question, live, onDemo, onFind, modeBody }: LedgerPageProps) {
  const attention = useFrameAttention({ demo, hub });
  // a page's links (its contents column, All pages, its own) leave the Decisions card and the hash
  // of the page being left behind, as their hrefs do (hud-routing.ts navigatePage)
  const common = { page, lang, attention, navigate: navigatePage, onFind };
  const awaitingAnswer = !!question;
  if (page.kind === 'home') {
    return <Home hub={hub} clock={clock} lang={lang} demo={demo} navigate={navigatePage} talk={talk} turns={turns} awaitingAnswer={awaitingAnswer} />;
  }
  if (page.kind === 'chat') return <ChatPage variant="chat" {...common} talk={talk} turns={turns} hub={hub} demo={demo} awaitingAnswer={awaitingAnswer} />;
  if (page.kind === 'allPages') return <AreaPage {...common}><AllPages lang={lang} navigate={navigatePage} attention={attention} /></AreaPage>;
  if (page.kind === 'panel' && route.panel) return <PanelPage panelId={route.panel} {...common} />;
  const mode = (page.entry.ref.kind === 'mode' ? page.entry.ref.id : 'cockpit') as HudMode;
  const body = mode === 'work' ? <WorkOverview hub={hub} lang={lang} demo={demo} navigate={navigatePage} turns={turns} question={question} />
    : mode === 'timeline' ? <Timeline hub={hub} lang={lang} demo={demo} clock={clock} navigate={navigatePage} turns={turns} />
      : mode === 'trust' ? <TrustOverview hub={hub} lang={lang} demo={demo} navigate={navigatePage} />
        : modeBody(mode);
  return (
    <ModePage mode={mode} {...common} demo={demo} live={live} onDemo={onDemo} hubState={hubReading(hub).state}
      liveKeys={OWN_PAGES.has(mode) ? null : MODE_LIVE_KEYS[mode] ?? null}>
      {body}
    </ModePage>
  );
}

export default App;
