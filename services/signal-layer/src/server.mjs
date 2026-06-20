import http from 'node:http';
import { URL } from 'node:url';
import { createWorldAnalyst } from './agent/worldAnalyst.mjs';
import { createEvidenceLedger } from './core/evidenceLedger.mjs';
import { scoreSignalsForWatchlist } from './core/relevance.mjs';
import { buildCountryAssessment, buildWorldBriefFromSignals } from './core/assessment.mjs';
import { defaultWatchlist } from './core/watchlist.mjs';

export function createServer({ config, provider }) {
  const state = {
    watchlist: [...defaultWatchlist]
  };
  const analyst = createWorldAnalyst({ provider, getWatchlist: () => state.watchlist });

  return http.createServer(async (req, res) => {
    const started = Date.now();
    try {
      const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
      const method = req.method || 'GET';

      applyCors(req, res, config);

      if (method === 'OPTIONS') return send(res, 204, null);

      // Bearer-token gate, only when a token is configured. /healthz stays open
      // as a liveness/fallback probe (it exposes only ok/mode, no data).
      if (config.authToken && !(method === 'GET' && url.pathname === '/healthz')) {
        if (!isAuthorized(req, config.authToken)) {
          return send(res, 401, { error: { code: 'unauthorized', message: 'Missing or invalid bearer token' } });
        }
      }

      if (method === 'GET' && url.pathname === '/healthz') {
        const providerHealth = await provider.health();
        return send(res, 200, {
          service: 'jarvis-signal-layer',
          ok: true,
          mode: config.mode,
          uptimeSeconds: Math.round(process.uptime()),
          provider: providerHealth,
          latencyMs: Date.now() - started
        });
      }

      if (method === 'GET' && url.pathname === '/provider-health/worldmonitor') {
        return send(res, 200, await provider.health());
      }

      if (method === 'GET' && url.pathname === '/watchlist') {
        return send(res, 200, { watchlist: state.watchlist });
      }

      if (method === 'POST' && url.pathname === '/watchlist') {
        const body = await readJson(req);
        const target = validateWatchTarget(body);
        state.watchlist.push(target);
        return send(res, 201, { watchlist: state.watchlist, added: target });
      }

      if (method === 'GET' && url.pathname === '/signals') {
        const limit = parsePositiveInt(url.searchParams.get('limit'), 50);
        const relevantOnly = url.searchParams.get('relevantOnly') === 'true';
        const type = url.searchParams.get('type') || undefined;
        const country = url.searchParams.get('country') || undefined;
        const minSeverity = url.searchParams.get('minSeverity') || undefined;
        const raw = await provider.fetchSignals({ type, country, minSeverity, limit: Math.max(limit, 100) });
        const scored = scoreSignalsForWatchlist(raw.signals, state.watchlist);
        const signals = (relevantOnly ? scored.filter(s => s.relevance.score > 0) : scored).slice(0, limit);
        const ledger = createEvidenceLedger(raw.evidence);
        return send(res, 200, {
          mode: config.mode,
          provider: raw.provider,
          generatedAt: new Date().toISOString(),
          count: signals.length,
          signals,
          evidence: ledger.toPublicEvidence(signals.flatMap(s => s.evidenceIds)),
          freshness: raw.freshness
        });
      }

      if (method === 'GET' && url.pathname === '/briefs/world') {
        const raw = await provider.fetchBrief({ scope: 'world' });
        if (raw.brief) return send(res, 200, raw.brief);

        const signalPayload = await provider.fetchSignals({ limit: 100 });
        const scored = scoreSignalsForWatchlist(signalPayload.signals, state.watchlist);
        return send(res, 200, buildWorldBriefFromSignals({
          signals: scored,
          evidence: signalPayload.evidence,
          provider: signalPayload.provider,
          freshness: signalPayload.freshness
        }));
      }

      const countryMatch = url.pathname.match(/^\/assessments\/country\/([A-Za-z]{2})$/);
      if (method === 'GET' && countryMatch) {
        const iso2 = countryMatch[1].toUpperCase();
        const assessment = await provider.fetchEntityAssessment({ type: 'country', id: iso2 });
        if (assessment.assessment) return send(res, 200, assessment.assessment);

        const signalPayload = await provider.fetchSignals({ country: iso2, limit: 100 });
        const scored = scoreSignalsForWatchlist(signalPayload.signals, state.watchlist);
        return send(res, 200, buildCountryAssessment({
          iso2,
          signals: scored,
          evidence: signalPayload.evidence,
          provider: signalPayload.provider,
          freshness: signalPayload.freshness
        }));
      }

      if (method === 'POST' && url.pathname === '/ask/world') {
        const body = await readJson(req);
        const answer = await analyst.answer({
          question: String(body.question || ''),
          mode: body.mode || 'general',
          country: body.country,
          limit: parsePositiveInt(body.limit, 12)
        });
        return send(res, 200, answer);
      }

      return send(res, 404, {
        error: {
          code: 'not_found',
          message: `No route for ${method} ${url.pathname}`
        }
      });
    } catch (error) {
      return send(res, error.statusCode || 500, {
        error: {
          code: error.code || 'internal_error',
          message: error.message || 'Unexpected error',
          retryable: Boolean(error.retryable)
        }
      });
    }
  });
}

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(value || '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function send(res, status, payload) {
  // CORS headers are set per-request via applyCors(); writeHead merges them in.
  const headers = { 'cache-control': 'no-store' };

  if (payload === null) {
    res.writeHead(status, headers);
    return res.end();
  }

  const body = JSON.stringify(payload, null, 2);
  res.writeHead(status, { ...headers, 'content-type': 'application/json; charset=utf-8' });
  res.end(body);
}

// CORS: reflect the request Origin only for local pages (localhost / 127.0.0.1 /
// ::1, any port) plus any explicitly allowed origins — never a blanket `*`, which
// would let any website read this service from a user's browser.
function applyCors(req, res, config) {
  res.setHeader('access-control-allow-methods', 'GET,POST,OPTIONS');
  res.setHeader('access-control-allow-headers', 'content-type, authorization');
  const origin = req.headers.origin;
  if (origin && isAllowedOrigin(origin, config)) {
    res.setHeader('access-control-allow-origin', origin);
    res.setHeader('vary', 'Origin');
    if (config.authToken) res.setHeader('access-control-allow-credentials', 'true');
  }
}

function isAllowedOrigin(origin, config) {
  let host;
  try { host = new URL(origin).hostname; } catch { return false; }
  if (host === 'localhost' || host === '127.0.0.1' || host === '::1') return true;
  return (config.allowedOrigins || []).includes(origin);
}

function isAuthorized(req, token) {
  const header = req.headers['authorization'] || '';
  return header === `Bearer ${token}`;
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString('utf8');
  if (!raw.trim()) return {};
  try {
    return JSON.parse(raw);
  } catch {
    const error = new Error('Request body must be valid JSON');
    error.statusCode = 400;
    error.code = 'invalid_json';
    throw error;
  }
}

function validateWatchTarget(value) {
  const allowed = new Set(['country', 'city', 'airport', 'route', 'market', 'topic', 'company']);
  if (!value || !allowed.has(value.type) || !value.value) {
    const error = new Error('Watch target must include type and value');
    error.statusCode = 400;
    error.code = 'invalid_watch_target';
    throw error;
  }
  return {
    id: value.id || `${value.type}:${String(value.value).toUpperCase()}`,
    type: value.type,
    value: String(value.value),
    label: value.label || String(value.value),
    priority: value.priority || 'normal'
  };
}
