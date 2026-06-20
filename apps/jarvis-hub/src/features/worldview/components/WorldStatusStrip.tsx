export function WorldStatusStrip({ health, brief, signalCount }: { health: any; brief: any; signalCount: number }) {
  const status = brief?.globalStatus || health?.status || 'unknown';
  const stale = brief?.freshness?.stale || health?.stale > 0;

  return (
    <section className="grid grid-cols-1 gap-3 rounded-2xl border border-neutral-800 bg-neutral-900/80 p-4 md:grid-cols-4">
      <Metric label="Global status" value={String(status).toUpperCase()} />
      <Metric label="Provider" value={health?.provider || 'worldmonitor'} />
      <Metric label="Mode" value={health?.mode || 'replay'} />
      <Metric label="Freshness" value={stale ? 'STALE PRESENT' : 'GOOD'} />
      <div className="md:col-span-4 text-sm text-neutral-400">
        Signals analyzed: {signalCount}. Last checked: {health?.checkedAt || brief?.generatedAt || 'not loaded'}.
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-950 p-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="mt-1 text-lg font-medium text-neutral-100">{value}</div>
    </div>
  );
}
