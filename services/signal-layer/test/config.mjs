import assert from 'node:assert/strict';
import { loadConfig } from '../src/config.mjs';

assert.equal(loadConfig({ JARVIS_WORLDVIEW_MODE: 'live' }).mode, 'replay',
  'retired WorldView settings must not enable live Signal Layer behavior');
assert.equal(loadConfig({ JARVIS_SIGNAL_LAYER_MODE: 'live' }).mode, 'live');
assert.equal(loadConfig({ JARVIS_SIGNAL_LAYER_MODE: 'replay', JARVIS_WORLDVIEW_MODE: 'live' }).mode, 'replay');
assert.equal(loadConfig({}).host, '127.0.0.1');
console.log('Signal Layer configuration: retired settings ignored, opt-in and local bind preserved');
