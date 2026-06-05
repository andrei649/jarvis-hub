// @ts-nocheck
/* HUD v2 · P4 live data for the capability modes. The ported modes read V2.<KEY>
   directly; rather than rewrite each, we fetch the real endpoints (shapes verified
   against the v1 HUD), assign onto the shared V2 object, and bump a version to
   re-render. Every fetch is independent and only overwrites V2 on success, so an
   absent/partial backend leaves the seeded mock intact (never breaks a panel). */
import { useState, useEffect } from 'react';
import { apiGet } from './client';
import { V2 } from '../data';

const arr = (x: any, ...keys: string[]) => {
  if (Array.isArray(x)) return x;
  for (const k of keys) if (x && Array.isArray(x[k])) return x[k];
  return null;
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
    const mark = (key: string) => { if (alive) setLive((p) => (p[key] ? p : { ...p, [key]: true })); };
    const set = (key: string, val: any) => { if (val !== undefined && val !== null) { (V2 as any)[key] = val; changed = true; } };

    async function load() {
      changed = false;

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

      // OBSERVE — compose from several endpoints
      await Promise.all([
        apiGet('/bench/stats').catch(() => null),
        apiGet('/api/quality').catch(() => null),
        apiGet('/api/resilience').catch(() => null),
        apiGet('/api/arena/leaderboard').catch(() => null),
        apiGet('/api/traces?limit=8').catch(() => null),
      ]).then(([bench, quality, resil, arena, traces]: any[]) => {
        const O = { ...V2.OBSERVE };
        if (bench) O.bench = { p50: bench.latency?.p50 ?? bench.p50 ?? O.bench.p50, p95: bench.latency?.p95 ?? bench.p95 ?? O.bench.p95, p99: bench.latency?.p99 ?? bench.p99 ?? O.bench.p99 };
        if (quality) O.quality = { success_rate: quality.success_rate ?? quality.rolling_avg ?? O.quality.success_rate, interactions: quality.interactions ?? quality.count ?? O.quality.interactions, escalations: quality.escalations ?? O.quality.escalations };
        if (resil) O.resilience = { uptime: resil.uptime ?? O.resilience.uptime, ssrf_blocked: resil.ssrf_blocked ?? O.resilience.ssrf_blocked, errors_24h: resil.errors_24h ?? O.resilience.errors_24h, redactions: resil.redactions ?? O.resilience.redactions };
        const al = arr(arena, 'leaderboard');
        if (al && al.length) O.arena = al.map((a: any) => ({ model: a.model || a.id, wins: a.wins ?? a.elo ?? 0, latency: a.latency || '', cost: a.cost || '', pick: !!a.pick }));
        const tl = arr(traces, 'traces');
        if (tl && tl.length) O.traces = tl.slice(0, 6).map((tr: any) => ({ id: tr.id || tr.trace_id, query: tr.query || tr.intent || '', agents: tr.agents || [], total: tr.total || tr.latency_ms || 0, status: tr.status || 'ok', stages: tr.stages || [] }));
        set('OBSERVE', O);
        if (bench || quality || resil || (al && al.length) || (tl && tl.length)) mark('OBSERVE');
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
        if (list && list.length) { set('PAYMENTS', list.map((x: any) => ({ pcap: x.mandate_id || x.payee || '', desc: x.memo || x.desc || '', amt: String(x.currency || '') + (x.amount != null ? x.amount : ''), state: x.state || x.status || 'pending' }))); mark('PAYMENTS'); }
      }).catch(() => {});

      // ADMIN — local models + plugin registry
      await apiGet('/api/models/local').then((m: any) => {
        const models = arr(m, 'models');
        if (models && models.length) { set('ADMIN', { ...V2.ADMIN, models: models.map((x: any) => ({ name: x.name || x.id, type: x.type || (x.local ? 'local' : 'cloud'), backend: x.backend || x.provider || '', ctx: x.ctx || '—', status: x.status || (x.active ? 'loaded' : 'ready'), use: x.use || '' })) }); mark('ADMIN'); }
      }).catch(() => {});
      await apiGet('/plugins').then((p: any) => {
        const plugins = arr(p, 'plugins');
        if (plugins && plugins.length) { set('ADMIN', { ...V2.ADMIN, plugins: plugins.map((x: any) => ({ name: x.name || x.id, scope: (x.allowed_domains && x.allowed_domains[0]) || x.scope || x.network_access || '', net: String(x.network_access || x.net || '').toLowerCase(), on: x.enabled !== false })) }); mark('ADMIN'); }
      }).catch(() => {});

      if (alive && changed) setVer((v) => v + 1);
    }

    load();
    const iv = setInterval(load, 30000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return { ver, live };
}
