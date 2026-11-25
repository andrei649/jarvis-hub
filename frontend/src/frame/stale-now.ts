/* A clock for the hub snapshot's staleness (frame/types.ts hubReading): read again on every new
   snapshot, and once more at the moment a live snapshot turns stale, because a stalled loader
   commits nothing and so would never re-render the frame by itself. */
import { useEffect, useMemo, useState } from 'react';
import { staleAfter, type HubSnapshot } from '../signals/types';

export function useStaleNow(hub: HubSnapshot): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (hub.state !== 'live' || hub.lastGoodAt === null) return undefined;
    const wait = hub.lastGoodAt + staleAfter(hub.intervalMs) - Date.now() + 1;
    if (wait <= 0) return undefined;
    const timer = setTimeout(() => setTick((n) => n + 1), wait);
    return () => clearTimeout(timer);
  }, [hub]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => Date.now(), [hub, tick]);
}
