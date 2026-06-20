export function WatchlistPanel({ items }: { items: any[] }) {
  return (
    <aside className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-4">
      <h2 className="text-xl font-medium">Watchlist</h2>
      <p className="mt-1 text-sm text-neutral-400">Used by the relevance engine.</p>
      <div className="mt-4 flex flex-col gap-2">
        {items.map(item => (
          <div key={item.id} className="rounded-xl border border-neutral-800 bg-neutral-950 p-3">
            <div className="text-sm font-medium text-neutral-100">{item.label}</div>
            <div className="mt-1 text-xs uppercase tracking-wide text-neutral-500">{item.type} · {item.priority}</div>
          </div>
        ))}
      </div>
    </aside>
  );
}
