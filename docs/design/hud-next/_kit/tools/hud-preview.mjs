// hud-preview.mjs — serve a built HUD bundle from a worktree, with live data read from the running
// hub, and nothing ever written to it.
//
//   node hud-preview.mjs <worktree-root> [--port 4180] [--hub http://127.0.0.1:8080]
//
// - /v2 and /v2/<route>     -> <worktree>/agents/web/v2/index.html, rewritten the way the hub's
//                              render_ui_html() does (asset paths, base-path bootstrap)
// - /v2/assets/*            -> files from <worktree>/agents/web/v2/assets
// - /manifest.webmanifest   -> the bundle's manifest
// - /sw-v2.js               -> 404 (no service worker, so nothing is cached between builds)
// - anything else, GET/HEAD -> proxied to the hub (live data; SSE streams are piped)
// - anything else, other    -> 405 {"error":"read-only preview"} (no chat turns, no analytics
//                              beacons, no appearance writes, no decisions ever reach the hub)
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const root = path.resolve(args[0] || '.');
const opt = (n, d) => { const i = args.indexOf(`--${n}`); return i > -1 ? args[i + 1] : d; };
const port = Number(opt('port', 4180));
const hub = new URL(opt('hub', 'http://127.0.0.1:8080'));
const bundle = path.join(root, 'agents', 'web', 'v2');

const TYPES = { '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.txt': 'text/plain', '.map': 'application/json' };

function shell() {
  let html = fs.readFileSync(path.join(bundle, 'index.html'), 'utf8');
  html = html.replace(/(src|href)=(["'])([^"']*)\2/g, (m, attr, q, p) => {
    if (p.startsWith('./assets/')) p = '/v2/' + p.slice(2);
    else if (p === './manifest.webmanifest') p = '/manifest.webmanifest';
    return `${attr}=${q}${p}${q}`;
  });
  const boot = '<script>window.__NERVA_BASE_PATH__="";window.nervaAppUrl=function(p){return window.__NERVA_BASE_PATH__+p;};</script>';
  return html.replace('<head>', '<head>\n' + boot);
}

function sendFile(res, file) {
  if (!file.startsWith(bundle) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end('not found'); return; }
  res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
  fs.createReadStream(file).pipe(res);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${port}`);
  const p = decodeURIComponent(url.pathname);
  if (p === '/sw-v2.js' || p === '/v2/sw-v2.js') { res.writeHead(404); res.end(); return; }
  if (p === '/manifest.webmanifest' || p === '/v2/manifest.webmanifest') return sendFile(res, path.join(bundle, 'manifest.webmanifest'));
  if (p.startsWith('/v2/assets/')) return sendFile(res, path.join(bundle, p.slice('/v2/'.length)));
  if (p === '/' || p === '/v2' || p.startsWith('/v2/')) {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
    res.end(shell());
    return;
  }
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: 'read-only preview' }));
    return;
  }
  const headers = { accept: req.headers.accept || '*/*' };
  const up = http.request({ hostname: hub.hostname, port: hub.port, path: url.pathname + url.search, method: req.method, headers }, (r) => {
    const out = { ...r.headers };
    delete out['content-security-policy'];
    res.writeHead(r.statusCode || 502, out);
    r.pipe(res);
  });
  up.on('error', (e) => { if (!res.headersSent) res.writeHead(502, { 'content-type': 'application/json' }); res.end(JSON.stringify({ error: String(e) })); });
  req.on('close', () => up.destroy());
  up.end();
});

server.listen(port, '127.0.0.1', () => console.log(`hud-preview: http://127.0.0.1:${port}/v2/ (bundle ${bundle}; GET proxied to ${hub.origin}; writes refused)`));
