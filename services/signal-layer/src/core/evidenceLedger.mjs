export function createEvidenceLedger(evidence = []) {
  const byId = new Map();
  for (const item of evidence) {
    if (item?.id) byId.set(item.id, item);
  }
  return {
    get(id) {
      return byId.get(id);
    },
    list() {
      return [...byId.values()];
    },
    toPublicEvidence(ids = []) {
      const unique = [...new Set(ids)].filter(Boolean);
      return unique.map(id => byId.get(id)).filter(Boolean).map(toPublicEvidenceItem);
    }
  };
}

function toPublicEvidenceItem(item) {
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
