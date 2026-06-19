export function FreshnessBadge({ stale, cachedAt }: { stale?: boolean; cachedAt?: string }) {
  return (
    <span className="rounded-full border border-neutral-700 px-2 py-0.5 text-[11px] text-neutral-400">
      {stale ? 'stale' : 'fresh'}{cachedAt ? ` · ${new Date(cachedAt).toLocaleTimeString()}` : ''}
    </span>
  );
}
