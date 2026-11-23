// Local production preview. Deployment uses nginx; no API proxy or backend import.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
const root = resolve('dist');
const types = { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript',
  '.css': 'text/css', '.json': 'application/json', '.png': 'image/png',
  '.ttf': 'font/ttf', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.ico': 'image/x-icon' };
createServer(async (req, res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    let file = resolve(root, `.${pathname}`);
    if (file !== root && !file.startsWith(root + sep)) { res.writeHead(403).end(); return; }
    try { if (!(await stat(file)).isFile()) file = resolve(root, 'index.html'); }
    catch { if (extname(file)) { res.writeHead(404).end(); return; } file = resolve(root, 'index.html'); }
    const data = await readFile(file);
    res.writeHead(200, { 'Content-Type': types[extname(file)] ?? 'application/octet-stream', 'Cache-Control': 'no-cache' });
    res.end(data);
  } catch { res.writeHead(500).end('Build the frontend with npm run build first.'); }
}).listen(Number(process.env.PORT ?? 8081), '127.0.0.1', () => console.log('Frontend preview ready'));
