import { spawn } from 'node:child_process';
import { createServer, preview } from 'vite';
import { fileURLToPath } from 'node:url';

const cwd = fileURLToPath(new URL('.', import.meta.url));
const api = spawn(process.env.PYTHON || 'python', ['-u', '-m', 'difficulty.server'], { cwd, stdio: ['ignore', 'pipe', 'inherit'] });
let web;
let started = false;
function close() { api.kill(); web?.httpServer?.close(); web?.close?.(); }
api.on('error', error => { console.error('Python 3.11+ 실행이 필요합니다:', error.message); process.exitCode = 1; });
api.on('exit', code => { web?.httpServer?.close(); web?.close?.(); process.exitCode = code || 0; });
api.stdout.on('data', async data => {
  process.stdout.write(data);
  if (!started && data.toString().includes('DIFFICULTY_API_READY')) {
    started = true;
    try {
      web = process.argv.includes('--preview') ? await preview() : await createServer();
      if (web.listen) await web.listen();
      console.log('  ➜  Local: http://localhost:' + (process.argv.includes('--preview') ? '4173' : '5173') + '/');
    } catch (error) { console.error(error.message); close(); process.exitCode = 1; }
  }
});
process.on('SIGINT', close);
process.on('SIGTERM', close);
