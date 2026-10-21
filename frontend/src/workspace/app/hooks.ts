/* Data hooks shared by every screen.

   useAsync loads once per dependency change and ignores answers that arrive after a newer
   request or after unmount (no stale overwrite, no state update on an unmounted page).
   usePolling refreshes on an interval only while the tab is visible, and immediately when the
   tab comes back, so a background tab does not keep the server busy. */
import { useCallback, useEffect, useRef, useState } from 'react';

export interface AsyncState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (update: T | null | ((prev: T | null) => T | null)) => void;
}

export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const value = await loadRef.current();
      if (mine === seq.current) setData(value);
    } catch (err) {
      if (mine === seq.current) setError(err);
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    return () => { seq.current += 1; };
    // The caller lists what `load` closes over; `reload` itself is stable.
  }, deps);

  return { data, error, loading, reload, setData };
}

export function usePolling(tick: () => void | Promise<void>, intervalMs: number, enabled = true): void {
  const tickRef = useRef(tick);
  tickRef.current = tick;
  useEffect(() => {
    if (!enabled) return undefined;
    const run = () => { if (document.visibilityState !== 'hidden') void tickRef.current(); };
    run();
    const timer = window.setInterval(run, intervalMs);
    const onVisible = () => { if (document.visibilityState === 'visible') run(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [intervalMs, enabled]);
}

/** Copies text to the clipboard; false when the browser refuses (the caller then shows the text selected). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Permission denied or insecure context: fall through to the selection fallback.
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}
