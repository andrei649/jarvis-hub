import { useCallback, useEffect, useState } from 'react';

export function readDemoMode(search: string): boolean {
  return new URLSearchParams(search).getAll('demo').includes('1');
}

export function replaceDemoMode(enabled: boolean, href = window.location.href): string {
  const url = new URL(href, window.location.origin);
  url.searchParams.delete('demo');
  if (enabled) url.searchParams.append('demo', '1');
  return `${url.pathname}${url.search}${url.hash}`;
}

export function useDemoMode(): [boolean, (enabled: boolean) => void] {
  const [demo, setDemoState] = useState(() => readDemoMode(window.location.search));

  useEffect(() => {
    const sync = () => setDemoState(readDemoMode(window.location.search));
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, []);

  const setDemo = useCallback((enabled: boolean) => {
    window.history.replaceState(window.history.state, '', replaceDemoMode(enabled));
    setDemoState(enabled);
  }, []);

  return [demo, setDemo];
}
