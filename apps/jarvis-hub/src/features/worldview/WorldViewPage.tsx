'use client';

import { useEffect, useState } from 'react';
import { fetchProviderHealth, fetchSignals, fetchWatchlist, fetchWorldBrief, askWorld } from './api/worldviewClient';
import { WorldStatusStrip } from './components/WorldStatusStrip';
import { SignalTimeline } from './components/SignalTimeline';
import { SourceDrawer } from './components/SourceDrawer';
import { WatchlistPanel } from './components/WatchlistPanel';
import { ActionQueue } from './components/ActionQueue';

export function WorldViewPage() {
  const [health, setHealth] = useState<any>(null);
  const [brief, setBrief] = useState<any>(null);
  const [signalsPayload, setSignalsPayload] = useState<any>(null);
  const [watchlist, setWatchlist] = useState<any[]>([]);
  const [selectedSignal, setSelectedSignal] = useState<any>(null);
  const [answer, setAnswer] = useState<string>('');
  const [question, setQuestion] = useState('What changed overnight that matters to me?');

  useEffect(() => {
    Promise.all([
      fetchProviderHealth(),
      fetchWorldBrief(),
      fetchSignals({ limit: 20, relevantOnly: true }),
      fetchWatchlist()
    ]).then(([healthResult, briefResult, signalsResult, watchlistResult]) => {
      setHealth(healthResult);
      setBrief(briefResult);
      setSignalsPayload(signalsResult);
      setWatchlist(watchlistResult.watchlist || []);
      setSelectedSignal(signalsResult.signals?.[0] || null);
    }).catch(error => {
      setAnswer(`WorldView failed to load: ${error.message}`);
    });
  }, []);

  async function submitQuestion() {
    const result = await askWorld(question);
    setAnswer(result.answer);
  }

  const signals = signalsPayload?.signals || [];
  const evidence = signalsPayload?.evidence || brief?.sources || [];

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="mx-auto flex max-w-7xl flex-col gap-4 p-6">
        <header className="flex flex-col gap-2">
          <p className="text-sm uppercase tracking-[0.35em] text-neutral-500">Jarvis Hub</p>
          <h1 className="text-3xl font-semibold">WorldView</h1>
          <p className="max-w-3xl text-neutral-400">
            External-world signals, evidence, relevance, assessments, and approval-gated recommendations.
          </p>
        </header>

        <WorldStatusStrip health={health} brief={brief} signalCount={signals.length} />

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr_360px]">
          <WatchlistPanel items={watchlist} />

          <div className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-medium">What changed</h2>
                <p className="text-sm text-neutral-400">Signals ranked by personal relevance and severity.</p>
              </div>
            </div>
            <SignalTimeline signals={signals} selectedId={selectedSignal?.id} onSelect={setSelectedSignal} />
          </div>

          <div className="flex flex-col gap-4">
            <section className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-4">
              <h2 className="text-xl font-medium">World Analyst</h2>
              <p className="mt-1 text-sm text-neutral-400">Ask for a brief grounded in the current signal payload.</p>
              <textarea
                className="mt-4 min-h-24 w-full rounded-xl border border-neutral-700 bg-neutral-950 p-3 text-sm outline-none focus:border-neutral-500"
                value={question}
                onChange={event => setQuestion(event.target.value)}
              />
              <button
                className="mt-3 rounded-xl bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-950"
                onClick={submitQuestion}
              >
                Ask Jarvis
              </button>
              {answer ? <pre className="mt-4 whitespace-pre-wrap rounded-xl bg-neutral-950 p-3 text-sm text-neutral-300">{answer}</pre> : null}
            </section>

            <ActionQueue recommendations={brief?.recommendations || []} />
          </div>
        </section>

        <SourceDrawer signal={selectedSignal} evidence={evidence} />
      </div>
    </main>
  );
}
