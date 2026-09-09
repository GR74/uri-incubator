/* Local preview: node build/serve.js. Only serves application assets. */
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const assets = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/index.html', ['index.html', 'text/html; charset=utf-8']],
  ['/src/uri.html', ['src/uri.html', 'text/html; charset=utf-8']],
  ['/src/workspace.jsx', ['src/workspace.jsx', 'text/javascript; charset=utf-8']],
  ['/src/workspace-research-domain.jsx', ['src/workspace-research-domain.jsx', 'text/javascript; charset=utf-8']],
  ['/src/workspace-research.jsx', ['src/workspace-research.jsx', 'text/javascript; charset=utf-8']],
  ['/src/workspace-evidence.jsx', ['src/workspace-evidence.jsx', 'text/javascript; charset=utf-8']],
  ['/src/workspace.css', ['src/workspace.css', 'text/css; charset=utf-8']],
]);

http.createServer((req, res) => {
  if (!['GET', 'HEAD'].includes(req.method)) {
    res.writeHead(405, { Allow: 'GET, HEAD' });
    return res.end();
  }
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname === '/favicon.ico') { res.writeHead(204); return res.end(); }
  const asset = assets.get(pathname);
  if (!asset) { res.writeHead(404); return res.end('Not found'); }
  fs.readFile(path.join(root, asset[0]), (error, data) => {
    if (error) { res.writeHead(404); return res.end('Not found'); }
    res.writeHead(200, { 'Content-Type': asset[1], 'Cache-Control': 'no-store' });
    res.end(req.method === 'HEAD' ? undefined : data);
  });
}).listen(4173, '127.0.0.1', () => console.log('URI preview: http://127.0.0.1:4173'));
