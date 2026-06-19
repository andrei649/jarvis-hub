import { loadConfig } from './config.mjs';
import { createProvider } from './providers/index.mjs';
import { createServer } from './server.mjs';

const config = loadConfig();
const provider = createProvider(config);
const server = createServer({ config, provider });

server.listen(config.port, config.host, () => {
  console.log(JSON.stringify({
    service: 'jarvis-signal-layer',
    mode: config.mode,
    host: config.host,
    port: config.port
  }));
});

process.on('SIGTERM', () => server.close(() => process.exit(0)));
process.on('SIGINT', () => server.close(() => process.exit(0)));
