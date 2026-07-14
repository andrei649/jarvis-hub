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

// No vite/client types wired in this project, so read the build-time env via a cast.
const SIGNAL_LAYER_URL =
  (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_SIGNAL_LAYER_URL
  || 'http://localhost:8787';

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

const signalLayerHealth = () => {
  if (typeof fetch !== 'function') return Promise.resolve(null);
  return fetch(`${SIGNAL_LAYER_URL}/healthz`, { cache: 'no-store' })
    .then(r => r.ok ? r.json() : null)
    .catch(() => null);
};

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
      // their proof before any request from this cycle can complete.
      set('ADMIN', { ...V2.ADMIN, models: [] });
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

      // OBSERVE — compose from several Jarvis endpoints plus Signal Layer health.
      // Signal Layer is enough to make Observe useful for the Sunday replay path.
      await Promise.all([
        apiGet('/bench/stats').catch(() => null),
        apiGet('/api/quality').catch(() => null),
        apiGet('/api/resilience').catch(() => null),
        apiGet('/api/arena/leaderboard').catch(() => null),
        apiGet('/api/traces?limit=8').catch(() => null),
        signalLayerHealth(),
      ]).then(([bench, quality, resil, arena, traces, signalLayer]: any[]) => {
        const O = { ...V2.OBSERVE };
        if (bench) O.bench = { p50: bench.latency?.p50 ?? bench.p50 ?? O.bench.p50, p95: bench.latency?.p95 ?? bench.p95 ?? O.bench.p95, p99: bench.latency?.p99 ?? bench.p99 ?? O.bench.p99 };
        if (quality) O.quality = { success_rate: quality.success_rate ?? quality.rolling_avg ?? O.quality.success_rate, interactions: quality.interactions ?? quality.count ?? O.quality.interactions, escalations: quality.escalations ?? O.quality.escalations };
        if (resil) O.resilience = { uptime: resil.uptime ?? O.resilience.uptime, ssrf_blocked: resil.ssrf_blocked ?? O.resilience.ssrf_blocked, errors_24h: resil.errors_24h ?? O.resilience.errors_24h, redactions: resil.redactions ?? O.resilience.redactions };
        const al = arr(arena, 'leaderboard');
        if (al && al.length) O.arena = al.map((a: any) => ({ model: a.model || a.id, wins: a.wins ?? a.elo ?? 0, latency: a.latency || '', cost: a.cost || '', pick: !!a.pick }));
        const tl = arr(traces, 'traces');
        if (tl && tl.length) O.traces = tl.slice(0, 6).map((tr: any) => ({ id: tr.id || tr.trace_id, query: tr.query || tr.intent || '', agents: tr.agents || [], total: tr.total || tr.latency_ms || 0, status: tr.status || 'ok', stages: tr.stages || [] }));
        set('OBSERVE', O);
        if (bench || quality || resil || (al && al.length) || (tl && tl.length) || signalLayer?.ok) mark('OBSERVE');
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
        if (pluginList.length) { set('ADMIN', { ...V2.ADMIN, plugins: pluginList.map((x: any) => ({ id: x.id || x.name, name: x.name || x.id, scope: (x.allowed_domains && x.allowed_domains[0]) || x.scope || x.network_access || '', net: String(x.network_access || x.net || '').toLowerCase(), on: x.enabled !== false })) }); mark('ADMIN'); }
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
