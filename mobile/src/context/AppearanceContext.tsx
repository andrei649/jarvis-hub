import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import { DEFAULT_APPEARANCE, type Appearance } from '../appearance';
import { fetchAppearance } from '../api/appearance';
import { ApiError } from '../api/client';
import { useServer } from './ServerContext';

type Status = 'loading' | 'synced' | 'offline' | 'unauthorized' | 'uncached' | 'unconfigured';
type Value = { preferences: Appearance; status: Status };
const Context = createContext<Value>({ preferences: DEFAULT_APPEARANCE, status: 'unconfigured' });
export function AppearanceProvider({ children }: { children: React.ReactNode }) {
  const { config, ready, configured, connectionEpoch, appearance, cacheAppearance } = useServer();
  const [state, setState] = useState<{ epoch: number; status: Status }>({ epoch: -1, status: 'loading' });
  const requestEpoch = useRef(0);
  useEffect(() => {
    if (!ready || !configured) return;
    let active = true;
    let abort: AbortController | undefined;
    const refresh = async () => {
      const request = ++requestEpoch.current;
      abort?.abort();
      const controller = new AbortController(); abort = controller;
      const current = () => active && request === requestEpoch.current && !controller.signal.aborted;
      setState({ epoch: connectionEpoch, status: 'loading' });
      let fetched = false;
      try {
        const preferences = await fetchAppearance(config, controller.signal);
        if (!current()) return;
        fetched = true;
        const saved = await cacheAppearance(connectionEpoch, preferences);
        if (saved && current()) setState({ epoch: connectionEpoch, status: 'synced' });
      } catch (error) {
        if (!current()) return;
        const unauthorized = error instanceof ApiError && (error.status === 401 || error.status === 403);
        if (unauthorized) {
          try { await cacheAppearance(connectionEpoch, null); } catch { /* Memory still clears even when storage is unavailable. */ }
        }
        if (current()) setState({ epoch: connectionEpoch, status: unauthorized ? 'unauthorized' : fetched ? 'uncached' : 'offline' });
      }
    };
    void refresh();
    let last = AppState.currentState;
    const listener = AppState.addEventListener('change', next => {
      if (next === 'active' && last !== 'active') void refresh();
      last = next;
    });
    return () => { active = false; ++requestEpoch.current; abort?.abort(); listener.remove(); };
  }, [ready, configured, config, connectionEpoch, cacheAppearance]);
  const status = !ready ? 'loading' : !configured ? 'unconfigured' : state.epoch === connectionEpoch ? state.status : 'loading';
  return <Context.Provider value={{ preferences: appearance ?? DEFAULT_APPEARANCE, status }}>{children}</Context.Provider>;
}
export const useAppearance = () => useContext(Context);
