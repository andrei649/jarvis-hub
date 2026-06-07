import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { normalizeBaseUrl } from '../api/client';
import { DEFAULT_CONFIG, loadConfig, saveConfig, type ServerConfig } from '../storage/settings';

type ServerContextValue = {
  config: ServerConfig;
  /** True once the persisted config has been read from storage. */
  ready: boolean;
  /** True when a non-empty base URL is configured. */
  configured: boolean;
  updateConfig: (next: ServerConfig) => Promise<void>;
};

const ServerContext = createContext<ServerContextValue | null>(null);

export function ServerProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfig] = useState<ServerConfig>(DEFAULT_CONFIG);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    loadConfig().then((c) => {
      if (active) {
        setConfig(c);
        setReady(true);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const updateConfig = useCallback(async (next: ServerConfig) => {
    const normalized: ServerConfig = {
      baseUrl: normalizeBaseUrl(next.baseUrl),
      token: next.token.trim(),
    };
    setConfig(normalized);
    await saveConfig(normalized);
  }, []);

  const value = useMemo<ServerContextValue>(
    () => ({ config, ready, configured: !!config.baseUrl, updateConfig }),
    [config, ready, updateConfig],
  );

  return <ServerContext.Provider value={value}>{children}</ServerContext.Provider>;
}

export function useServer(): ServerContextValue {
  const ctx = useContext(ServerContext);
  if (!ctx) throw new Error('useServer must be used within a ServerProvider');
  return ctx;
}
