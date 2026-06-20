import { stableId } from '../util/id.mjs';

export function buildWorldBriefFromSignals({ signals, evidence, provider, freshness }) {
  const top = [...signals].sort((a, b) => b.relevance.score - a.relevance.score).slice(0, 6);
  const highestSeverity = top.reduce((max, signal) => severityRank(signal.severity) > severityRank(max) ? signal.severity : max, 'low');
  const evidenceIds = [...new Set(top.flatMap(signal => signal.evidenceIds || []))];

  return {
    id: stableId(['brief', 'world', new Date().toISOString().slice(0, 13), top.map(signal => signal.id).join('|')]),
    type: 'brief',
    scope: 'world',
    title: 'Global Intelligence Brief',
    executiveSummary: summarizeTopSignals(top),
    generatedAt: new Date().toISOString(),
    globalStatus: highestSeverity,
    topSignals: top.map(toBriefSignal),
    recommendations: recommendFromSignals(top),
    evidenceIds,
    sources: evidence.filter(item => evidenceIds.includes(item.id)).map(publicEvidence),
    freshness: freshness || { checkedAt: new Date().toISOString(), stale: false },
    provider,
    raw: null
  };
}

export function buildCountryAssessment({ iso2, signals, evidence, provider, freshness }) {
  const top = signals.slice(0, 6);
  const score = Math.min(100, Math.max(10, top.reduce((sum, signal) => sum + severityScore(signal.severity), 0) + Math.min(25, top.length * 4)));
  const evidenceIds = [...new Set(top.flatMap(signal => signal.evidenceIds || []))];
  return {
    id: stableId(['assessment', 'country', iso2, new Date().toISOString().slice(0, 13), top.map(signal => signal.id).join('|')]),
    subject: { type: 'country', id: iso2, label: iso2 },
    risk: {
      score,
      level: riskLevel(score),
      components: componentScores(top)
    },
    claim: top.length
      ? `${iso2} has ${riskLevel(score)} assessed risk based on ${top.length} current signals.`
      : `${iso2} has no current high-relevance signals in the provider payload.`,
    confidence: top.some(signal => signal.confidence === 'low') ? 'medium' : 'medium',
    drivers: top.map(signal => ({ title: signal.title, severity: signal.severity, type: signal.type })),
    recommendations: recommendFromSignals(top),
    evidenceIds,
    evidence: evidence.filter(item => evidenceIds.includes(item.id)).map(publicEvidence),
    freshness: freshness || { checkedAt: new Date().toISOString(), stale: false },
    provider,
    raw: null
  };
}

function summarizeTopSignals(top) {
  if (!top.length) return 'No current signals were available from the configured provider.';
  const relevant = top.filter(signal => signal.relevance.score > 0).length;
  const high = top.filter(signal => ['high', 'critical'].includes(signal.severity)).length;
  return `Jarvis analyzed current world signals and found ${relevant} personally relevant item${relevant === 1 ? '' : 's'} among the top signals. ${high} high-severity item${high === 1 ? '' : 's'} should be monitored. Confidence and freshness are shown per signal.`;
}

function toBriefSignal(signal) {
  return {
    id: signal.id,
    title: signal.title,
    type: signal.type,
    severity: signal.severity,
    confidence: signal.confidence,
    relevance: signal.relevance,
    whyItMatters: signal.relevance?.reasons?.[0] || `Severity is ${signal.severity}.`,
    evidenceIds: signal.evidenceIds
  };
}

function recommendFromSignals(signals) {
  const recs = [];
  if (signals.some(signal => signal.type === 'aviation')) recs.push({ type: 'monitor', label: 'Monitor watched airports and airspace again within 24 hours.', requiresApproval: true });
  if (signals.some(signal => signal.type === 'market')) recs.push({ type: 'brief', label: 'Generate a market pulse before making finance decisions.', requiresApproval: true });
  if (signals.some(signal => signal.type === 'cyber')) recs.push({ type: 'review', label: 'Review cyber exposure before taking action.', requiresApproval: true });
  if (signals.some(signal => ['conflict', 'geopolitical_news'].includes(signal.type))) recs.push({ type: 'monitor', label: 'Keep affected countries/routes on elevated watch.', requiresApproval: true });
  if (!recs.length) recs.push({ type: 'monitor', label: 'Continue monitoring. No immediate action recommended.', requiresApproval: false });
  return dedupeByLabel(recs).slice(0, 5);
}

function publicEvidence(item) {
  return {
    id: item.id,
    provider: item.provider,
    sourceName: item.sourceName,
    sourceFamily: item.sourceFamily,
    url: item.url,
    observedAt: item.observedAt,
    publishedAt: item.publishedAt,
    fetchedAt: item.fetchedAt,
    cachedAt: item.cachedAt,
    stale: Boolean(item.stale),
    reliability: item.reliability || 'unknown'
  };
}

function componentScores(signals) {
  const out = {};
  for (const signal of signals) {
    out[signal.type] = Math.max(out[signal.type] || 0, severityScore(signal.severity));
  }
  return out;
}

function severityScore(value) {
  return ({ low: 5, normal: 12, elevated: 25, high: 40, critical: 60 })[value] ?? 10;
}

function severityRank(value) {
  return ({ low: 0, normal: 1, elevated: 2, high: 3, critical: 4 })[value] ?? 0;
}

function riskLevel(score) {
  if (score >= 85) return 'critical';
  if (score >= 70) return 'high';
  if (score >= 50) return 'elevated';
  if (score >= 25) return 'moderate';
  return 'low';
}

function dedupeByLabel(items) {
  const seen = new Set();
  return items.filter(item => {
    if (seen.has(item.label)) return false;
    seen.add(item.label);
    return true;
  });
}
