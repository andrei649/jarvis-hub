import { stableId } from '../util/id.mjs';

export function normalizeWorldMonitorToolResult(toolName, result) {
  const payload = unwrapMcpPayload(result);
  const records = asArray(payload?.items || payload?.events || payload?.data || payload?.results || payload)
    .filter(isRecordLike);
  const evidence = [];
  const signals = [];

  for (const record of records) {
    const ev = evidenceFromRecord(toolName, record);
    evidence.push(ev);
    signals.push(signalFromRecord(toolName, record, ev.id));
  }

  return { signals, evidence };
}

// Guard against fabricating a phantom signal from an empty/unstructured payload:
// when records fall back to the payload object itself, keep it only if it carries
// at least one field a real record would have.
function isRecordLike(record) {
  if (!record || typeof record !== 'object' || Array.isArray(record)) return false;
  const fields = ['title', 'headline', 'name', 'summary', 'description', 'body', 'text',
    'url', 'link', 'symbol', 'airport', 'country', 'countryCode', 'country_code', 'type', 'severity'];
  return fields.some(f => record[f] != null && record[f] !== '');
}

export function normalizeWorldMonitorBrief(result) {
  const payload = unwrapMcpPayload(result) || {};
  const now = new Date().toISOString();
  const sources = asArray(payload.sources).map(source => ({
    id: stableId(['source', source?.url || source?.name || JSON.stringify(source)]),
    provider: 'worldmonitor',
    sourceName: source?.name || source?.title || 'WorldMonitor source',
    sourceFamily: source?.sourceFamily || source?.family || 'unknown',
    url: source?.url,
    publishedAt: source?.publishedAt || source?.published_at,
    fetchedAt: source?.fetchedAt || now,
    cachedAt: source?.cachedAt || payload.cached_at,
    stale: Boolean(source?.stale || payload.stale),
    reliability: source?.reliability || 'unknown',
    raw: source
  }));

  return {
    id: stableId(['world-brief', payload.generatedAt || payload.generated_at || now, payload.summary || payload.text || '']),
    type: 'brief',
    scope: 'world',
    title: payload.title || 'Global Intelligence Brief',
    executiveSummary: payload.executiveSummary || payload.summary || payload.text || 'WorldMonitor returned a brief, but no summary field was recognized.',
    generatedAt: payload.generatedAt || payload.generated_at || now,
    globalStatus: payload.globalStatus || payload.status || 'unknown',
    topSignals: asArray(payload.topRisks || payload.risks || payload.topSignals).slice(0, 8),
    recommendations: asArray(payload.recommendations),
    evidenceIds: sources.map(source => source.id),
    sources,
    freshness: { stale: Boolean(payload.stale), cachedAt: payload.cachedAt || payload.cached_at, checkedAt: now },
    provider: 'worldmonitor',
    raw: payload
  };
}

export function normalizeWorldMonitorCountryAssessment({ iso2, payloads, errors = [] }) {
  const now = new Date().toISOString();
  const merged = Object.assign({}, ...payloads.map(unwrapMcpPayload).filter(Boolean));
  const score = Number(merged.score ?? merged.risk_score ?? merged.riskScore ?? 35);
  const evidence = asArray(merged.sources).map(source => ({
    id: stableId(['country-source', iso2, source?.url || source?.name || JSON.stringify(source)]),
    provider: 'worldmonitor',
    sourceName: source?.name || source?.title || 'WorldMonitor country source',
    sourceFamily: source?.sourceFamily || source?.family || 'unknown',
    url: source?.url,
    publishedAt: source?.publishedAt || source?.published_at,
    fetchedAt: source?.fetchedAt || now,
    cachedAt: source?.cachedAt || merged.cached_at || merged.cachedAt,
    stale: Boolean(source?.stale || merged.stale),
    reliability: source?.reliability || 'unknown',
    raw: source
  }));

  return {
    id: stableId(['country-assessment', iso2, score, merged.cached_at || now]),
    subject: { type: 'country', id: iso2, label: merged.countryName || merged.country || iso2 },
    risk: { score, level: levelFromScore(score), components: merged.components || merged.drivers || {} },
    claim: merged.summary || merged.brief || `${iso2} currently has ${levelFromScore(score)} assessed risk.`,
    confidence: confidenceFromPayload(merged),
    drivers: asArray(merged.drivers || merged.riskDrivers || merged.topDrivers),
    recommendations: asArray(merged.recommendations || merged.actions),
    evidenceIds: evidence.map(item => item.id),
    evidence,
    freshness: { stale: Boolean(merged.stale), cachedAt: merged.cachedAt || merged.cached_at, checkedAt: now },
    provider: 'worldmonitor',
    errors,
    raw: payloads
  };
}

function signalFromRecord(toolName, record, evidenceId) {
  const now = new Date().toISOString();
  const title = record?.title || record?.headline || record?.name || titleFromTool(toolName);
  const summary = record?.summary || record?.description || record?.body || record?.text || title;
  const type = record?.type || typeFromTool(toolName);
  const stale = Boolean(record?.stale);
  return {
    id: stableId(['signal', toolName, title, record?.publishedAt || record?.date || JSON.stringify(record).slice(0, 200)]),
    domain: 'world',
    type,
    title,
    summary: String(summary).slice(0, 1500),
    entities: entitiesFromRecord(record),
    evidenceIds: [evidenceId],
    severity: severityFromRecord(record),
    confidence: confidenceFromPayload(record),
    claimStatus: toolName.includes('news') || toolName.includes('conflict') ? 'raw_osint_lead' : 'confirmed',
    status: 'new',
    observedAt: record?.observedAt || record?.observed_at || record?.publishedAt || now,
    publishedAt: record?.publishedAt || record?.published_at || record?.date,
    fetchedAt: record?.fetchedAt || record?.fetched_at || now,
    cachedAt: record?.cachedAt || record?.cached_at,
    stale,
    provider: 'worldmonitor',
    relevance: { score: 0, reasons: [], matchedTargets: [] },
    raw: record
  };
}

function evidenceFromRecord(toolName, record) {
  return {
    id: stableId(['evidence', toolName, record?.url || record?.source || JSON.stringify(record).slice(0, 200)]),
    provider: 'worldmonitor',
    sourceName: record?.source || record?.sourceName || toolName,
    sourceFamily: sourceFamilyFromTool(toolName),
    url: record?.url || record?.link,
    observedAt: record?.observedAt || record?.observed_at,
    publishedAt: record?.publishedAt || record?.published_at || record?.date,
    fetchedAt: record?.fetchedAt || record?.fetched_at || new Date().toISOString(),
    cachedAt: record?.cachedAt || record?.cached_at,
    stale: Boolean(record?.stale),
    reliability: toolName.includes('conflict') || toolName.includes('news') ? 'unknown' : 'medium',
    raw: record
  };
}

function unwrapMcpPayload(result) {
  if (Array.isArray(result?.content)) {
    const text = result.content.find(item => item.type === 'text')?.text;
    if (text) { try { return JSON.parse(text); } catch { return { text }; } }
  }
  return result;
}

function asArray(value) { return value ? (Array.isArray(value) ? value : [value]) : []; }
function typeFromTool(toolName) {
  if (toolName.includes('conflict')) return 'conflict';
  if (toolName.includes('aviation')) return 'aviation';
  if (toolName.includes('market')) return 'market';
  if (toolName.includes('cyber')) return 'cyber';
  if (toolName.includes('natural')) return 'natural_disaster';
  return 'geopolitical_news';
}
function titleFromTool(toolName) { return `${typeFromTool(toolName).replaceAll('_', ' ')} signal`; }
function sourceFamilyFromTool(toolName) {
  if (toolName.includes('aviation')) return 'aviation';
  if (toolName.includes('market')) return 'market';
  if (toolName.includes('cyber')) return 'cyber';
  if (toolName.includes('natural')) return 'weather';
  if (toolName.includes('conflict')) return 'osint';
  return 'rss';
}
function severityFromRecord(record) {
  const raw = String(record?.severity || record?.level || '').toLowerCase();
  if (['critical', 'high', 'elevated', 'normal', 'low'].includes(raw)) return raw;
  const score = Number(record?.score ?? record?.risk_score ?? record?.riskScore ?? NaN);
  if (Number.isFinite(score)) return score >= 85 ? 'critical' : score >= 70 ? 'high' : score >= 50 ? 'elevated' : score >= 25 ? 'normal' : 'low';
  return 'normal';
}
function confidenceFromPayload(record) { return record?.stale ? 'low' : (record?.confidence || 'medium'); }
function levelFromScore(score) { return score >= 85 ? 'critical' : score >= 70 ? 'high' : score >= 50 ? 'elevated' : score >= 25 ? 'moderate' : 'low'; }
function entitiesFromRecord(record) {
  const out = [];
  const country = (record?.countryCode || record?.country_code || record?.iso2 || '').toString().toUpperCase().slice(0, 2);
  if (country) out.push({ type: 'country', id: country, label: country });
  if (record?.airport) out.push({ type: 'airport', id: String(record.airport).toUpperCase(), label: String(record.airport).toUpperCase() });
  if (record?.symbol) out.push({ type: 'market', id: String(record.symbol).toUpperCase(), label: String(record.symbol).toUpperCase() });
  return out;
}
