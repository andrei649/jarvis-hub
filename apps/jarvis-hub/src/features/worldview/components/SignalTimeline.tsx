import { FreshnessBadge } from './FreshnessBadge';

export function SignalTimeline({ signals, selectedId, onSelect }: { signals: any[]; selectedId?: string; onSelect: (signal: any) => void }) {
  if (!signals.length) {
    return <div className="rounded-xl border border-neutral-800 bg-neutral-950 p-4 text-neutral-400">No relevant signals loaded.</div>;
  }

  return (
    <div className="flex flex-col gap-3">
      {signals.map(signal => (
        <button
          key={signal.id}
          onClick={() => onSelect(signal)}
          className={`rounded-xl border p-4 text-left transition ${selectedId === signal.id ? 'border-neutral-300 bg-neutral-800' : 'border-neutral-800 bg-neutral-950 hover:border-neutral-600'}`}
        >
          <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-wide text-neutral-500">
            <span>{signal.type}</span>
            <span>•</span>
            <span>{signal.severity}</span>
            <span>•</span>
            <span>{signal.confidence} confidence</span>
            <FreshnessBadge stale={signal.stale} cachedAt={signal.cachedAt} />
          </div>
          <h3 className="mt-2 text-base font-medium text-neutral-100">{signal.title}</h3>
          <p className="mt-2 line-clamp-3 text-sm text-neutral-400">{signal.summary}</p>
          {signal.relevance?.reasons?.length ? (
            <p className="mt-3 text-sm text-neutral-300">Why it matters: {signal.relevance.reasons[0]}</p>
          ) : null}
        </button>
      ))}
    </div>
  );
}
