import { McpClient } from './mcpClient.mjs';
import { normalizeWorldMonitorToolResult, normalizeWorldMonitorCountryAssessment, normalizeWorldMonitorBrief } from '../normalizers/worldMonitor.mjs';

export class WorldMonitorProvider {
  constructor({ baseUrl, mcpUrl, timeoutMs = 8000 }) {
    this.id = 'worldmonitor';
    this.name = 'WorldMonitor Live Provider';
    this.mode = 'live';
    this.baseUrl = baseUrl;
    this.mcp = new McpClient({ mcpUrl, timeoutMs });
    this.timeoutMs = timeoutMs;
  }

  async health() {
    const started = Date.now();
    try {
      const health = await this.#getJson('/api/health');
      return {
        provider: this.id,
        mode: this.mode,
        status: health?.status || 'ok',
        fresh: health?.fresh ?? undefined,
        stale: health?.stale ?? undefined,
        checkedAt: new Date().toISOString(),
        latencyMs: Date.now() - started,
        raw: health
      };
    } catch (error) {
      return {
        provider: this.id,
        mode: this.mode,
        status: 'degraded',
        checkedAt: new Date().toISOString(),
        latencyMs: Date.now() - started,
        error: {
          code: error.code || 'provider_health_failed',
          message: error.message
        }
      };
    }
  }

  async fetchSignals(input = {}) {
    const calls = [
      ['get_conflict_events', { limit: 30, country: input.country }],
      ['get_aviation_status', { limit: 30, country: input.country }],
      ['get_market_data', { limit: 30 }],
      ['get_cyber_threats', { limit: 30, country: input.country }],
      ['get_natural_disasters', { limit: 30, country: input.country }],
      ['get_news_intelligence', { limit: 30, country: input.country }]
    ];

    const settled = await Promise.allSettled(
      calls.map(([name, args]) => this.mcp.callTool(name, removeUndefined(args)).then(result => ({ name, result })))
    );

    const normalized = [];
    const evidence = [];
    const errors = [];

    for (const item of settled) {
      if (item.status === 'fulfilled') {
        const out = normalizeWorldMonitorToolResult(item.value.name, item.value.result);
        normalized.push(...out.signals);
        evidence.push(...out.evidence);
      } else {
        errors.push({ code: item.reason?.code || 'tool_failed', message: item.reason?.message || 'Tool failed' });
      }
    }

    let signals = normalized;
    if (input.type) signals = signals.filter(signal => signal.type === input.type);
    if (input.minSeverity) signals = signals.filter(signal => severityRank(signal.severity) >= severityRank(input.minSeverity));
    if (input.limit) signals = signals.slice(0, input.limit);

    return {
      provider: this.id,
      mode: this.mode,
      signals,
      evidence,
      freshness: {
        checkedAt: new Date().toISOString(),
        stale: signals.some(signal => signal.stale),
        degraded: errors.length > 0,
        errors
      }
    };
  }

  async fetchBrief(input = {}) {
    try {
      const result = await this.mcp.callTool('get_world_brief', { scope: input.scope || 'world' });
      return {
        provider: this.id,
        mode: this.mode,
        brief: normalizeWorldMonitorBrief(result)
      };
    } catch (error) {
      return {
        provider: this.id,
        mode: this.mode,
        brief: null,
        error: {
          code: error.code || 'brief_failed',
          message: error.message
        }
      };
    }
  }

  async fetchEntityAssessment(input) {
    if (input.type !== 'country') {
      return { provider: this.id, mode: this.mode, assessment: null };
    }

    const iso2 = String(input.id || '').toUpperCase();
    const calls = await Promise.allSettled([
      this.mcp.readResource(`worldmonitor://countries/${iso2}/risk`),
      this.mcp.callTool('get_country_brief', { country: iso2 })
    ]);

    const payloads = calls.filter(c => c.status === 'fulfilled').map(c => c.value);
    const errors = calls.filter(c => c.status === 'rejected').map(c => ({ code: c.reason?.code, message: c.reason?.message }));

    if (!payloads.length) {
      return {
        provider: this.id,
        mode: this.mode,
        assessment: null,
        error: errors[0] || { code: 'country_assessment_failed', message: 'No country assessment payloads returned' }
      };
    }

    return {
      provider: this.id,
      mode: this.mode,
      assessment: normalizeWorldMonitorCountryAssessment({ iso2, payloads, errors })
    };
  }

  async #getJson(path) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(`${this.baseUrl}${path}`, { signal: controller.signal });
      const text = await response.text();
      let json = {};
      try { json = text ? JSON.parse(text) : {}; } catch {}
      if (!response.ok) {
        const error = new Error(`WorldMonitor HTTP ${response.status}`);
        error.code = 'worldmonitor_http_error';
        error.status = response.status;
        error.body = json;
        throw error;
      }
      return json;
    } finally {
      clearTimeout(timer);
    }
  }
}

function removeUndefined(input) {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}

function severityRank(value) {
  return ({ low: 0, normal: 1, elevated: 2, high: 3, critical: 4 })[value] ?? 0;
}
