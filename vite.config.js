import { defineConfig } from 'vite';
import { setDefaultResultOrder } from 'node:dns';

setDefaultResultOrder('ipv4first');

const api = { '/api': { target: 'http://127.0.0.1:' + (process.env.DIFFICULTY_PORT || '8787') } };
function canonicalHost(req, res, next) {
  const port = req.headers.host === '127.0.0.1:5173' ? 5173 : req.headers.host === '127.0.0.1:4173' ? 4173 : null;
  if (port && req.headers.accept?.includes('text/html')) {
    res.writeHead(302, { Location: 'http://localhost:' + port + req.url });
    res.end();
  } else next();
}
export default defineConfig({
  plugins: [{ name: 'local-map-domain', configureServer(server) { server.middlewares.use(canonicalHost); }, configurePreviewServer(server) { server.middlewares.use(canonicalHost); } }],
  server: { host: 'localhost', port: 5173, strictPort: true, proxy: api, fs: { deny: ['.env', '.env.*', '**/*.sqlite', '**/integrated_roads/**', '**/difficulty_data/**'] } },
  preview: { host: 'localhost', port: 4173, strictPort: true, proxy: api }
});
