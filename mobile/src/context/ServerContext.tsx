import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { normalizeBaseUrl } from '../api/client';
import { DEFAULT_CONFIG, loadServerRecord, newChatScope, reconfigureServer, saveServerRecord, type ServerConfig, type ServerRecord } from '../storage/settings';
import { normalizeAppearance, type Appearance } from '../appearance';

type ServerContextValue = {
  config: ServerConfig; ready: boolean; configured: boolean; appearance: Appearance | null; connectionEpoch: number; chatScope: string;
  updateConfig: (next: ServerConfig) => Promise<void>;
  cacheAppearance: (epoch: number, next: Appearance | null) => Promise<boolean>;
};
const ServerContext = createContext<ServerContextValue | null>(null);
export function ServerProvider({ children }: { children: React.ReactNode }) {
  const owner = useRef<{ record: ServerRecord; epoch: number }>({ record: { version: 2, config: DEFAULT_CONFIG, appearance: null, chatScope: newChatScope() }, epoch: 0 });
  const [state, setState] = useState({ ...owner.current, ready: false });
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    const epoch = owner.current.epoch;
    let cancelled = false;
    void loadServerRecord().then(record => {
      if (!cancelled && owner.current.epoch === epoch) {
        owner.current = { record, epoch: epoch + 1 };
        setState({ ...owner.current, ready: true });
        // Persist the migrated scope; read the latest owner at write time if settings race hydration.
        void saveServerRecord(() => owner.current.record).catch(() => {});
      }
    });
    return () => { cancelled = true; active.current = false; };
  }, []);
  const updateConfig = useCallback(async (next: ServerConfig) => {
    const config = { baseUrl: normalizeBaseUrl(next.baseUrl), token: next.token.trim(), adminToken: next.adminToken.trim() };
    // Every explicit save supersedes hydration, even a clear equal to initial defaults.
    owner.current = { record: reconfigureServer(owner.current.record, config), epoch: owner.current.epoch + 1 };
    // One state update defaults appearance on the first render of a new identity.
    setState({ ...owner.current, ready: true });
    await saveServerRecord(() => owner.current.record);
  }, []);
  const cacheAppearance = useCallback(async (epoch: number, next: Appearance | null) => {
    if (!active.current || owner.current.epoch !== epoch) return false;
    owner.current = { ...owner.current, record: { ...owner.current.record, appearance: next ? normalizeAppearance(next) : null } };
    setState({ ...owner.current, ready: true });
    await saveServerRecord(() => owner.current.record);
    return active.current && owner.current.epoch === epoch;
  }, []);
  const value = useMemo<ServerContextValue>(() => ({ config: state.record.config, ready: state.ready,
    configured: !!state.record.config.baseUrl, appearance: state.record.appearance, connectionEpoch: state.epoch, chatScope: state.record.chatScope,
    updateConfig, cacheAppearance }), [state, updateConfig, cacheAppearance]);
  return <ServerContext.Provider value={value}>{children}</ServerContext.Provider>;
}
export function useServer(): ServerContextValue {
  const context = useContext(ServerContext);
  if (!context) throw new Error('useServer must be used within a ServerProvider');
  return context;
}
