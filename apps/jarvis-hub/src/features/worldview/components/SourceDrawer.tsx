export function SourceDrawer({ signal, evidence }: { signal: any; evidence: any[] }) {
  if (!signal) return null;
  const ids = new Set(signal.evidenceIds || []);
  const matching = evidence.filter(item => ids.has(item.id));

  return (
    <section className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-medium">Evidence drawer</h2>
          <p className="mt-1 text-sm text-neutral-400">{signal.title}</p>
        </div>
        <div className="rounded-full border border-neutral-700 px-3 py-1 text-xs uppercase text-neutral-400">
          {signal.claimStatus}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        {matching.map(item => (
          <article key={item.id} className="rounded-xl border border-neutral-800 bg-neutral-950 p-3">
            <div className="text-sm font-medium text-neutral-100">{item.sourceName || item.sourceFamily}</div>
            <div className="mt-1 text-xs uppercase tracking-wide text-neutral-500">{item.sourceFamily} · {item.reliability || 'unknown'} reliability</div>
            <dl className="mt-3 space-y-1 text-sm text-neutral-400">
              <Row label="Published" value={item.publishedAt} />
              <Row label="Fetched" value={item.fetchedAt} />
              <Row label="Cached" value={item.cachedAt} />
              <Row label="Stale" value={String(Boolean(item.stale))} />
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

function Row({ label, value }: { label: string; value?: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt>{label}</dt>
      <dd className="text-right text-neutral-300">{value || 'unknown'}</dd>
    </div>
  );
}
