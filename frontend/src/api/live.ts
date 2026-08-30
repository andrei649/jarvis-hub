/* HUD v2 · P4 live data for the capability modes. The ported modes read V2.<KEY>
   directly; rather than rewrite each, we fetch the real endpoints (shapes verified
   against the v1 HUD), assign onto the shared V2 object, and bump a version to
   re-render. Every fetch is independent and only overwrites V2 on success. The
   local-model inventory is stricter: every poll clears prior rows until that
   cycle supplies a valid array, so demo seed or stale residency cannot look live.

   CDX-9: off @ts-nocheck (completes the api/ layer). The `: any` at each fetch is the
   real ingestion boundary — heterogeneous backend shapes are normalized here before
   landing on V2; tightening those into per-endpoint response types is a follow-up that
   wants V2 (data.ts) typed first. */
import { useState, useEffect } from 'react';
import { apiGet } from './client';
import type { LocalModelRow } from './types';
import { V2 } from '../data';

const arr = (x: any, ...keys: string[]) => {
  if (Array.isArray(x)) return x;
  for (const k of keys) if (x && Array.isArray(x[k])) return x[k];
  return null;
};

export const PREVIEW_MODE_LIVE_KEYS = {
  build: ['BUILD'],
  comms: ['COMMS'],
  finance: ['FINANCE'],
  health: ['HEALTH'],
  knowledge: ['KNOWLEDGE'],
  family: ['FAMILY'],
};

const firstArr = (x: any, ...keys: string[]) => arr(x, ...keys) || [];
const text = (x: any, fallback = '') => String(x ?? fallback);

export function localModelStatus(model: Pick<LocalModelRow, 'resident' | 'available'>): string {
  if (model.resident === true) return 'loaded';
  if (model.resident == null) return 'residency unknown';
  if (model.available === true) return 'ready';
  if (model.available == null) return 'availability unknown';
  return 'unavailable';
}

export function mapLocalModelsForAdmin(models: LocalModelRow[]): any[] {
  return models.map((model) => ({
    id: model.id,
    name: model.name || model.id,
    type: 'local',
    backend: model.provider,
    provider: model.provider,
    ctx: model.ctx || '—',
    status: localModelStatus(model),
    use: model.configured ? 'configured' : '',
    available: model.available,
    configured: model.configured,
    resident: model.resident,
    controls: model.controls,
  }));
}

export function pluginIsConfigured(plugin: any): boolean {
  return !!plugin && plugin.enabled !== false && (plugin.configured === true || plugin.available === true);
}

export function balancePayloadIsLive(payload: any): boolean {
  if (!payload || payload.mock === true) return false;
  return Object.entries(payload).some(([key, value]) => key !== 'mock' && Array.isArray(value) && value.length > 0);
}

function pluginById(plugins: any[] | null | undefined, id: string) {
  return (plugins || []).find((p) => (p && (p.id === id || p.name === id)));
}

function pluginReady(plugins: any[] | null | undefined, id: string): boolean {
  return pluginIsConfigured(pluginById(plugins, id));
}

function workflowToCanvas(workflow: any) {
  const steps = firstArr(workflow, 'steps').slice(0, 8);
  if (!steps.length) {
    return {
      ...V2.BUILD.workflow,
      name: text(workflow?.name, workflow?.id || 'Workflow'),
      status: 'live',
      nodes: [],
      edges: [],
    };
  }
  const nodes = steps.map((step: any, i: number) => ({
    id: text(step.id, `step-${i + 1}`),
    label: text(step.id || step.agent_id || `step ${i + 1}`).slice(0, 18),
    kind: step.kind || 'agent',
    x: 70 + (i % 4) * 190,
    y: 40 + Math.floor(i / 4) * 82,
  }));
  const nodeIds = new Set(nodes.map((n: any) => n.id));
  let edges = steps.flatMap((step: any) => firstArr(step, 'depends_on')
    .filter((dep: any) => nodeIds.has(text(dep)) && nodeIds.has(text(step.id)))
    .map((dep: any) => [text(dep), text(step.id)]));
  if (!edges.length && nodes.length > 1) {
    edges = nodes.slice(1).map((n: any, i: number) => [nodes[i].id, n.id]);
  }
  return {
    ...V2.BUILD.workflow,
    name: text(workflow?.name, workflow?.id || 'Workflow'),
    status: 'live',
    nodes,
    edges,
  };
}

/** Build the OBSERVE view from the live payloads, never borrowing the demo seed.
 *
 * Exported so its behaviour is tested directly — a test that re-implements this
 * would pass while the shipped path regressed.
 *
 * Every field used to end in `?? seed.<field>`, and the seed is a complete,
 * plausible picture: 91% success, 847 interactions, 99.97% uptime, 0 errors. So a
 * field the backend did not supply rendered as a convincing fabricated number,
 * under a green LIVE badge — `mark('OBSERVE')` fires when ANY of the six fetches
 * returns something truthy.
 *
 * Two of them supplied nothing at all. `/api/quality` returns `{stats, alert}`, so
 * `quality.success_rate` was always undefined; `/api/resilience` returns
 * `{metrics, circuit_breakers}` and has never emitted uptime / ssrf_blocked /
 * errors_24h / redactions. Both objects are truthy, so the panel was marked live
 * over 100% seed data.
 *
 * Un-hydrated fields are null now, and the panels render null as "\u2014".
 */
export function hydrateObserve(bench: any, quality: any, resil: any, seed: any) {
  const O: any = { ...seed };
  // No `if (payload)` guard on any of the three blocks: a failed fetch arrives
  // here as null (`.catch(() => null)`), and skipping the block would leave that
  // panel at whatever the seed carried while a sibling endpoint that DID answer
  // stamps the LIVE badge. A null payload nulls its own block instead.
  O.bench = {
    p50: bench?.latency?.p50 ?? bench?.p50 ?? null,
    p95: bench?.latency?.p95 ?? bench?.p95 ?? null,
    p99: bench?.latency?.p99 ?? bench?.p99 ?? null,
  };
  // The real nesting. `avg_score` is the rolling quality average and `n` the
  // sample count; escalations are not tracked by this endpoint at all.
  const qs = quality?.stats ?? quality;
  O.quality = {
    success_rate: qs?.avg_score ?? qs?.success_rate ?? qs?.rolling_avg ?? null,
    interactions: qs?.n ?? qs?.interactions ?? qs?.count ?? null,
    escalations: qs?.escalations ?? null,
  };
  // Derive what the payload really carries: per-agent success/failure counts
  // under `metrics`. Uptime and redactions are not emitted by any endpoint, so
  // they stay null rather than borrowing the seed's 99.97%.
  const m = resil?.metrics && typeof resil.metrics === 'object' ? Object.values(resil.metrics) as any[] : [];
  const failures = m.reduce((n: number, st: any) => n + (Number(st?.failure) || 0), 0);
  O.resilience = {
    uptime: resil?.uptime ?? null,
    ssrf_blocked: resil?.ssrf_blocked ?? null,
    errors_24h: resil?.errors_24h ?? (m.length ? failures : null),
    redactions: resil?.redactions ?? null,
  };
  return O;
}

/* Secret-name heuristic — mirrors `_SECRET_HINTS` in agents/core/routers/admin.py
 * (key/token/secret/password/passwd/pass/client_id). /api/admin/env returns the
 * whole environment with secrets already masked server-side by mask_secret()
 * (agents/core/web_helpers.py:79); filtering by NAME keeps PATH out of a panel
 * titled "API KEYS & SECRETS" and keeps never-configured seed keys out too.
 * We only know a key is SET — never claim validity or rotation age. */
const SECRET_NAME_HINTS = ['key', 'token', 'secret', 'password', 'passwd', 'pass', 'client_id'];

export function hydrateAdminKeys(env: any) {
  if (!env || typeof env !== 'object' || Array.isArray(env)) return [];
  return Object.entries(env)
    .filter(([name]) => SECRET_NAME_HINTS.some((h) => name.toLowerCase().includes(h)))
    .slice(0, 8)
    .map(([name, value]) => ({ name, masked: text(value as any, ''), status: 'set', rotated: '' }));
}

/* /api/admin/agents/stats → OBSERVE's "LATENCY BY AGENT" meters. latency_ms
 * becomes seconds at one decimal; agents without a measured latency are dropped,
 * not invented — the seed's seven per-agent latencies had no source at all. */
export function hydrateByAgent(stats: any) {
  if (!stats || typeof stats !== 'object' || Array.isArray(stats)) return [];
  const out: any[] = [];
  for (const [id, s] of Object.entries(stats)) {
    const ms = s && typeof s === 'object' ? Number((s as any).latency_ms) : NaN;
    if (Number.isFinite(ms) && ms > 0) out.push({ id, v: Math.round(ms / 100) / 10 });
  }
  return out;
}

/* Start-of-cycle corpora: the demo fiction is stripped before any request of the
 * cycle can complete (same rule as ADMIN models), so nothing renders unless THIS
 * cycle's backend actually said it. Demo mode re-imports these seeds fresh. */
export function honestAdminSeed() {
  return { ...V2.ADMIN, models: [], plugins: [], keys: [], backups: [], channels: [], system: null };
}
export function honestObserveSeed() {
  // /bench/stats 503s without an orchestrator while /api/quality still answers
  // 200, so the panel is badged live: the scalars must start null too, or the
  // seed's 4.2s p50 renders as fact. Objects stay — ObserveMode reads the fields.
  return {
    ...V2.OBSERVE,
    by_agent: [], arena: [], traces: [],
    quality: { success_rate: null, interactions: null, escalations: null },
    bench: { p50: null, p95: null, p99: null },
    resilience: { uptime: null, ssrf_blocked: null, errors_24h: null, redactions: null },
  };
}

/* The OBSERVE live badge means "Jarvis observability data arrived this cycle".
 * Signal Layer health says nothing about whether /api/quality or /api/traces
 * ever answered, so it must not stamp the badge over a still-seeded panel. */
export function observeEvidence(bench: any, quality: any, resil: any, arenaRows: any, traceRows: any) {
  return !!(
    bench || quality || resil ||
    (Array.isArray(arenaRows) && arenaRows.length > 0) ||
    (Array.isArray(traceRows) && traceRows.length > 0)
  );
}

function marketplaceSkills(raw: any[]) {
  return raw.slice(0, 8).map((skill: any) => ({
    name: text(skill.name || skill.id, 'Skill'),
    author: text(skill.author || skill.agent || 'jarvis').toLowerCase(),
    desc: text(skill.description || skill.review_status || skill.version || 'Marketplace skill'),
    installed: skill.installed === true || skill.enabled === true,
    runs: Number(skill.runs || 0),
  }));
}

function formatCommsTs(value: any): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return new Date(value * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return text(value, 'live');
}

function roomsToComms(rooms: any[], channels: any[] = [], inboxThreads: any[] = []) {
  const liveInbox = inboxThreads.slice(0, 12).map((thread: any, i: number) => {
    const channel = text(thread.channel, 'telegram').toLowerCase();
    return {
      id: text(thread.thread_id || thread.id, `inbox-${i}`),
      thread_id: text(thread.thread_id || thread.id, `inbox-${i}`),
      channel,
      from: text(thread.from || thread.sender, channel),
      agent: text(thread.agent, 'veronica'),
      subj: text(thread.subj, `${channel} thread`),
      preview: text(thread.preview, 'Live channel message'),
      ts: formatCommsTs(thread.ts),
      unread: thread.unread !== false,
      dir: 'in',
      local: true,
      replyable: ['telegram', 'web'].includes(channel),
    };
  });
  const roomThreads = rooms.slice(0, 12).map((room: any, i: number) => ({
    id: text(room.id, `room-${i}`),
    channel: 'room',
    from: text(room.name, 'Room'),
    agent: text(room.default_agent, 'jarvis'),
    subj: text(room.name, 'Room'),
    preview: text(room.description, 'Live multi-agent room'),
    ts: room.created_at ? new Date(room.created_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'live',
    unread: false,
    dir: 'in',
    local: true,
  }));
  const threads = [...liveInbox, ...roomThreads].slice(0, 12);
  const channelRows = channels
    .filter((channel: any) => ['discord', 'slack'].includes(text(channel?.id).toLowerCase()))
    .map((channel: any) => {
      const id = text(channel.id).toLowerCase();
      return { id, label: id === 'discord' ? 'Discord' : 'Slack', count: 0 };
    });
  const inboxRows = Array.from(new Set(liveInbox.map((thread: any) => thread.channel))).map((id: any) => ({
    id,
    label: id === 'web' ? 'Web' : id.charAt(0).toUpperCase() + id.slice(1),
    count: liveInbox.filter((thread: any) => thread.channel === id).length,
  }));
  return {
    ...V2.COMMS,
    threads,
    channels: [...inboxRows, { id: 'room', label: 'Rooms', count: roomThreads.length }, ...channelRows],
  };
}

function watchesToFinance(watches: any[]) {
  return {
    ...V2.FINANCE,
    net_worth: '—',
    mom: 'owner data',
    accounts: [],
    budgets: [],
    watches: watches.slice(0, 8).map((w: any) => ({
      pair: text(w.symbol || w.pair, 'watch'),
      val: '—',
      band: [w.low, w.high].filter((v) => v !== null && v !== undefined && v !== '').join('–') || text(w.note, 'saved'),
      state: 'ok',
    })),
    pending: [],
  };
}

function paymentsToFinancePending(payments: any[]) {
  return payments.slice(0, 8).map((p: any) => ({
    who: text(p.mandate_id || p.payee || p.agent || 'payment'),
    desc: text(p.memo || p.desc || p.description || 'Payment request'),
    amt: `${text(p.currency || '')}${p.amount != null ? p.amount : ''}`,
    state: text(p.state || p.status || 'pending'),
  }));
}

function kgToKnowledge(entities: any[]) {
  return {
    ...V2.KNOWLEDGE,
    queue: [],
    saved: entities.slice(0, 8).map((e: any) => ({
      title: text(e.name || e.id || e.label, 'Entity'),
      src: text(e.type || e.entity_type || 'knowledge graph'),
      tag: text(e.source || 'KG'),
      cites: Number(e.citations || e.edges || 0),
    })),
    digest: [],
  };
}


export interface LiveModes { ver: number; live: Record<string, boolean>; }

/* Returns `live`: which V2 keys received REAL, non-empty backend data this session.
   modeComponent() uses it to decide whether a capability mode shows real content or
   an honest "not connected" state — so seed is never passed off as live. */
export function useLiveModes(): LiveModes {
  const [ver, setVer] = useState(0);
  const [live, setLive] = useState<Record<string, boolean>>({});
  useEffect(() => {
    let alive = true;
    let changed = false;
    let loadGeneration = 0;
    let pluginList: any[] = [];
    const mark = (key: string) => { if (alive) setLive((p) => (p[key] ? p : { ...p, [key]: true })); };
    const clearMark = (key: string) => { if (alive) setLive((p) => (p[key] ? { ...p, [key]: false } : p)); };
    const set = (key: string, val: any) => { if (val !== undefined && val !== null) { (V2 as any)[key] = val; changed = true; } };

    async function load() {
      const loadId = ++loadGeneration;
      changed = false;
      // Model residency is current-cycle evidence. Clear seed/stale rows and
      // their proof before any request from this cycle can complete. Same rule
      // for the rest of the ADMIN corpus: plugins/keys/backups/channels/system
      // have no other honest source, so they start empty and stay empty unless
      // this cycle's backend supplies them.
      set('ADMIN', honestAdminSeed());
      clearMark('ADMIN_MODELS');
      if (alive) setVer((v) => v + 1);

      // MEMORY — flatten /memory/stats {sessions:{total}, vectors:{stored}, knowledge_graph:{entities,relations}}
      await apiGet('/memory/stats').then((s: any) => {
        if (!s) return;
        set('MEMORY_STATS', {
          sessions: s?.sessions?.total ?? s?.sessions ?? V2.MEMORY_STATS.sessions,
          vectors: s?.vectors?.stored ?? s?.vectors ?? V2.MEMORY_STATS.vectors,
          entities: s?.knowledge_graph?.entities ?? V2.MEMORY_STATS.entities,
          relations: s?.knowledge_graph?.relations ?? V2.MEMORY_STATS.relations,
        });
        mark('MEMORY_STATS');
      }).catch(() => {});

      // OBSERVE — compose from several Jarvis endpoints. Seed traces/arena/
      // by_agent are stripped first: an empty leaderboard or a silent
      // /api/traces must read as "no data", not as the demo corpus. The live
      // badge needs Jarvis evidence (observeEvidence), not neighbour health —
      // the World Intelligence panel talks to Signal Layer on its own.
      set('OBSERVE', honestObserveSeed());
      await Promise.all([
        apiGet('/bench/stats').catch(() => null),
        apiGet('/api/quality').catch(() => null),
        apiGet('/api/resilience').catch(() => null),
        apiGet('/api/arena/leaderboard').catch(() => null),
        apiGet('/api/traces?limit=8').catch(() => null),
        apiGet('/api/admin/agents/stats', { admin: true }).catch(() => null),
      ]).then(([bench, quality, resil, arena, traces, agentStats]: any[]) => {
        const O = hydrateObserve(bench, quality, resil, V2.OBSERVE);
        const al = arr(arena, 'leaderboard');
        O.arena = al ? al.map((a: any) => ({ model: a.model || a.id, wins: a.wins ?? a.elo ?? 0, latency: a.latency || '', cost: a.cost || '', pick: !!a.pick })) : [];
        const tl = arr(traces, 'traces');
        O.traces = tl ? tl.slice(0, 6).map((tr: any) => ({ id: tr.id || tr.trace_id, query: tr.query || tr.intent || '', agents: tr.agents || [], total: tr.total || tr.latency_ms || 0, status: tr.status || 'ok', stages: tr.stages || [] })) : [];
        O.by_agent = hydrateByAgent(agentStats);
        set('OBSERVE', O);
        if (observeEvidence(bench, quality, resil, al, tl)) mark('OBSERVE');
      }).catch(() => {});

      // INTEROP — a2a peers / mcp servers / widgets / webhooks
      await Promise.all([
        apiGet('/api/a2a/peers').catch(() => null),
        apiGet('/api/admin/mcp').catch(() => null),
        apiGet('/api/admin/widgets').catch(() => null),
        apiGet('/api/webhooks').catch(() => null),
      ]).then(([a2a, mcp, widgets, webhooks]: any[]) => {
        const I = { ...V2.INTEROP };
        const ap = arr(a2a, 'peers'); if (ap) I.a2a = ap.map((p: any) => ({ peer: p.peer || p.name || p.id, protocol: p.protocol || 'A2A', status: p.status || (p.connected ? 'connected' : 'idle'), agents: p.agents || [] }));
        const ms = arr(mcp, 'servers'); if (ms) I.mcp = ms.map((s: any) => ({ server: s.name || s.server, tools: (s.tools && s.tools.length) || s.tool_count || 0, status: s.status || (s.connected ? 'up' : 'down'), scope: s.scope || '' }));
        const wd = arr(widgets, 'widgets'); if (wd) I.widgets = wd.map((w: any) => ({ name: w.title || w.name || 'widget', surface: w.surface || w.token || '', enabled: w.enabled !== false }));
        const wh = arr(webhooks, 'webhooks'); if (wh) I.webhooks = wh.map((w: any) => ({ event: w.event || w.id, dir: w.dir || 'in', url: w.url || w.target || '', status: w.status || 'active' }));
        set('INTEROP', I);
        if (ap || ms || wd || wh) mark('INTEROP');
      }).catch(() => {});

      // AUTONOMY — morning brief + observer log
      await Promise.all([
        apiGet('/autonomy/brief').catch(() => null),
        apiGet('/autonomy/observer').catch(() => null),
      ]).then(([brief, obs]: any[]) => {
        const A = { ...V2.AUTONOMY };
        const bi = arr(brief, 'items', 'brief'); if (bi) A.brief = bi.map((b: any, i: number) => ({ rank: b.rank || i + 1, agent: String(b.agent || '').toUpperCase(), title: b.title || b.text || '', detail: b.detail || '' }));
        const oe = arr(obs, 'events', 'log', 'recent'); if (oe) A.observer = oe.map((e: any) => ({ ts: e.ts || e.time || '', agent: String(e.agent || '').toUpperCase(), action: e.action || e.text || '', result: e.result || e.status || '' }));
        set('AUTONOMY', A);
        if (bi || oe) mark('AUTONOMY');
      }).catch(() => {});

      // TRUST — audit chain + payments ledger
      await apiGet('/api/security/audit/intent').then((a: any) => {
        const acts = arr(a, 'actions', 'records', 'entries');
        if (acts && acts.length) { set('AUDIT_CHAIN', acts.slice(0, 6).map((r: any, i: number) => ({ verb: String(r.action || r.verb || 'ACTION').toUpperCase().slice(0, 6), x: r.why || r.detail || r.action || '', hash: String(r.hash || '').slice(0, 4) || String(i), prev: String(r.prev || '').slice(0, 4) || '0000', t: r.t || r.ts || '' }))); mark('AUDIT_CHAIN'); }
      }).catch(() => {});
      await apiGet('/api/payments').then((p: any) => {
        const list = arr(p, 'payments');
        // Keep the broker `id` so TrustMode can POST /api/payments/{id}/approve|reject|settle.
        if (list && list.length) { set('PAYMENTS', list.map((x: any) => ({ id: x.id || x.payment_id || '', pcap: x.mandate_id || x.payee || '', desc: x.memo || x.desc || '', amt: String(x.currency || '') + (x.amount != null ? x.amount : ''), state: x.state || x.status || 'pending' }))); mark('PAYMENTS'); }
      }).catch(() => {});

      // ADMIN — local models + plugin registry
      await apiGet('/plugins').then((p: any) => {
        pluginList = firstArr(p, 'plugins');
        // Preserve the backend plugin `id` so AdminMode can PUT /plugins/{id}/toggle.
        // `honesty` (tranche 3b) is the per-plugin live-vs-needs_config verdict the
        // registry badges render; absent on seeded demo rows so those stay unbadged.
        if (pluginList.length) { set('ADMIN', { ...V2.ADMIN, plugins: pluginList.map((x: any) => ({
          id: x.id || x.name,
          name: x.name || x.id,
          scope: (x.allowed_domains && x.allowed_domains[0]) || x.scope || x.network_access || '',
          net: String(x.network_access || x.net || '').toLowerCase(),
          on: x.enabled !== false,
          honesty: x.honesty || null,
          degraded: x.degraded === true,
          degradedReason: x.degraded_reason || '',
          degradedNeeds: Array.isArray(x.degraded_needs) ? x.degraded_needs : [],
        })) }); mark('ADMIN'); }
      }).catch(() => { pluginList = []; });
      await apiGet('/api/models/local').then((m: any) => {
        if (!alive || loadId !== loadGeneration) return;
        const models = arr(m, 'models');
        if (models) {
          set('ADMIN', { ...V2.ADMIN, models: mapLocalModelsForAdmin(models) });
          mark('ADMIN_MODELS');
          mark('ADMIN');
        }
      }).catch(() => {
        if (!alive || loadId !== loadGeneration) return;
        set('ADMIN', { ...V2.ADMIN, models: [] });
        clearMark('ADMIN_MODELS');
      });

      // API KEYS & SECRETS — what the server actually has in its environment,
      // already masked server-side. Absent or empty → the panel stays "not
      // connected" rather than showing keys that were never configured.
      await apiGet('/api/admin/env', { admin: true }).then((env: any) => {
        if (!alive || loadId !== loadGeneration) return;
        const keys = hydrateAdminKeys(env);
        set('ADMIN', { ...V2.ADMIN, keys });
        if (keys.length) mark('ADMIN');
      }).catch(() => {});

      // P3.1 PREVIEW MODES — real endpoints or honest plugin-gated empty states.
      await Promise.all([
        apiGet('/api/workflows').catch(() => null),
        apiGet('/api/skills/marketplace', { admin: true }).catch(() => null),
        apiGet('/sandbox/status').catch(() => null),
      ]).then(([workflows, marketplace, sandbox]: any[]) => {
        const wf = firstArr(workflows, 'workflows');
        const ms = firstArr(marketplace, 'skills');
        if (!wf.length && !ms.length && !sandbox) return;
        set('BUILD', {
          ...V2.BUILD,
          workflow: wf.length ? workflowToCanvas(wf[0]) : V2.BUILD.workflow,
          skills: ms.length ? marketplaceSkills(ms) : V2.BUILD.skills,
          sandbox: sandbox ? [{ in: 'sandbox.status()', out: sandbox.available ? `Docker · ${sandbox.docker_image || 'ready'}` : 'sandbox unavailable' }] : V2.BUILD.sandbox,
        });
        mark('BUILD');
      }).catch(() => {});

      await Promise.all([
        apiGet('/api/rooms').catch(() => null),
        apiGet('/status').catch(() => null),
        apiGet('/api/channels/inbox').catch(() => null),
      ]).then(([rooms, status, inbox]: any[]) => {
        const list = firstArr(rooms, 'rooms');
        const channels = firstArr(status, 'channels')
          .filter((channel: any) => ['discord', 'slack'].includes(text(channel?.id).toLowerCase()));
        const inboxThreads = firstArr(inbox, 'threads');
        if (list.length || channels.length || inboxThreads.length) {
          set('COMMS', roomsToComms(list, channels, inboxThreads));
          mark('COMMS');
        }
      }).catch(() => {});

      await Promise.all([
        apiGet('/api/market/watchlist/saved').catch(() => null),
        apiGet('/api/payments').catch(() => null),
      ]).then(([saved, payments]: any[]) => {
        const watches = firstArr(saved, 'watches');
        const pay = firstArr(payments, 'payments');
        if (!watches.length && !pay.length && !pluginReady(pluginList, 'balance')) return;
        set('FINANCE', {
          ...(watches.length ? watchesToFinance(watches) : { ...V2.FINANCE, accounts: [], budgets: [], watches: [] }),
          pending: paymentsToFinancePending(pay),
        });
        if (watches.length || pay.length) mark('FINANCE');
      }).catch(() => {});

      await apiGet('/api/kg/entities?limit=8').then((kg: any) => {
        const entities = firstArr(kg, 'entities');
        if (entities.length && pluginReady(pluginList, 'websearch')) { set('KNOWLEDGE', kgToKnowledge(entities)); mark('KNOWLEDGE'); }
      }).catch(() => {});

      if (pluginReady(pluginList, 'apple-health')) {
        set('HEALTH', { ...V2.HEALTH, rings: [], metrics: [], week: [], plan: [], sync: 'Apple Health · configured LAN bridge' });
        mark('HEALTH');
      }
      if (pluginReady(pluginList, 'whatsapp-bridge')) {
        set('FAMILY', { ...V2.FAMILY, members: [], events: [], reminders: [] });
        mark('FAMILY');
      }

      if (alive && changed) setVer((v) => v + 1);
    }

    load();
    const iv = setInterval(load, 30000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return { ver, live };
}
