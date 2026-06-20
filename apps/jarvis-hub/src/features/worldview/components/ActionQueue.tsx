export function ActionQueue({ recommendations }: { recommendations: any[] }) {
  return (
    <section className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-4">
      <h2 className="text-xl font-medium">Action queue</h2>
      <p className="mt-1 text-sm text-neutral-400">Jarvis recommends. Approval is required before external or high-impact action.</p>
      <div className="mt-4 flex flex-col gap-2">
        {recommendations.length ? recommendations.map((rec, index) => (
          <div key={`${rec.label}-${index}`} className="rounded-xl border border-neutral-800 bg-neutral-950 p-3">
            <div className="text-sm text-neutral-100">{rec.label}</div>
            <div className="mt-1 text-xs uppercase tracking-wide text-neutral-500">
              {rec.type} · {rec.requiresApproval ? 'approval required' : 'no approval required'}
            </div>
          </div>
        )) : <div className="text-sm text-neutral-400">No recommendations loaded.</div>}
      </div>
    </section>
  );
}
