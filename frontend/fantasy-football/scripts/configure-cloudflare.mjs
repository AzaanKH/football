// Pass JSON directly as an argv value: Windows PowerShell's native argument
// quoting otherwise splits the Pages build command and strips JSON quotes.
import { readFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const [operation, ...options] = process.argv.slice(2);
if (!['create', 'edit'].includes(operation) || options.some((option) => option !== '--dry-run')) {
  console.error('Usage: node scripts/configure-cloudflare.mjs create | edit [--dry-run]');
  process.exit(1);
}

const config = JSON.parse(await readFile(new URL('../../../cloudflare/pages.json', import.meta.url), 'utf8'));
const cli = fileURLToPath(new URL('../node_modules/cf/bin/cf', import.meta.url));
const args = [cli, 'pages', operation];
if (operation === 'edit') args.push(config.name);
args.push('--body', JSON.stringify(config), ...options);
const child = spawn(process.execPath, args, { stdio: 'inherit' });
child.on('error', (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
child.on('exit', (code) => { process.exitCode = code ?? 1; });
