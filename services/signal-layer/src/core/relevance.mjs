const severityBoost = {
  low: 0,
  normal: 5,
  elevated: 12,
  high: 20,
  critical: 30
};

export function scoreSignalsForWatchlist(signals, watchlist = []) {
  return signals.map(signal => ({
    ...signal,
    relevance: scoreSignal(signal, watchlist)
  })).sort((a, b) => {
    if (b.relevance.score !== a.relevance.score) return b.relevance.score - a.relevance.score;
    return severityRank(b.severity) - severityRank(a.severity);
  });
}

export function scoreSignal(signal, watchlist = []) {
  let score = severityBoost[signal.severity] || 0;
  const reasons = [];
  const matchedTargets = [];

  for (const target of watchlist) {
    const match = matchTarget(signal, target);
    if (match) {
      const boost = boostForTarget(target);
      score += boost;
      reasons.push(match.reason);
      matchedTargets.push(target);
    }
  }

  if (signal.stale) {
    score -= 12;
    reasons.push('Lower priority because the provider marked this signal as stale.');
  }
  if (signal.confidence === 'low') {
    score -= 15;
    reasons.push('Lower confidence because evidence is weak, stale, or uncorroborated.');
  }
  if (signal.confidence === 'high') {
    score += 8;
    reasons.push('Higher confidence because the signal has stronger evidence.');
  }

  score = Math.max(0, Math.min(100, score));
  if (!reasons.length && score > 0) reasons.push(`Raised by severity: ${signal.severity}.`);

  return { score, reasons: [...new Set(reasons)], matchedTargets };
}

function matchTarget(signal, target) {
  const value = String(target.value).toLowerCase();
  const title = String(signal.title || '').toLowerCase();
  const summary = String(signal.summary || '').toLowerCase();
  const text = `${title} ${summary}`;
  const entity = signal.entities?.find(item => {
    const id = String(item.id || '').toLowerCase();
    const label = String(item.label || '').toLowerCase();
    return item.type === target.type && (id === value || label === value || label.includes(value));
  });

  if (entity) {
    return { reason: `Matches watched ${target.type}: ${target.label || target.value}.` };
  }

  if (target.type === 'topic' && (signal.type === value || text.includes(value))) {
    return { reason: `Matches watched topic: ${target.label || target.value}.` };
  }

  if (target.type === 'route' && text.includes(value)) {
    return { reason: `Mentions watched route: ${target.label || target.value}.` };
  }

  if (target.type === 'market' && text.includes(value)) {
    return { reason: `Mentions watched market: ${target.label || target.value}.` };
  }

  return null;
}

function boostForTarget(target) {
  const base = {
    country: 35,
    city: 40,
    airport: 45,
    route: 35,
    market: 35,
    topic: 25,
    company: 30
  }[target.type] || 20;
  const priority = target.priority === 'high' ? 10 : target.priority === 'low' ? -5 : 0;
  return base + priority;
}

function severityRank(value) {
  return ({ low: 0, normal: 1, elevated: 2, high: 3, critical: 4 })[value] ?? 0;
}
