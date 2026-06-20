import { ReplayProvider } from './replayProvider.mjs';
import { WorldMonitorProvider } from './worldMonitorProvider.mjs';

export function createProvider(config) {
  if (config.mode === 'live') {
    return new WorldMonitorProvider(config.worldMonitor);
  }
  return new ReplayProvider();
}
