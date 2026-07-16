#!/usr/bin/env node
/**
 * JSON bridge for zjk1984/findskills — stdout only JSON (stderr for logs).
 * Usage: FINDSKILLS_ROOT=/path/to/findskills node scripts/findskills_json.mjs search "A股复盘" --limit 3
 */
import { pathToFileURL } from 'node:url';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const opts = { command: 'search', query: '', limit: 10, source: null };
  let i = 0;
  while (i < argv.length) {
    const arg = argv[i];
    if (arg === 'search' || arg === 'recommend' || arg === 'popular') {
      opts.command = arg;
    } else if (arg === '--limit' || arg === '-l') {
      opts.limit = parseInt(argv[++i], 10) || 10;
    } else if (arg === '--source' || arg === '-s') {
      opts.source = argv[++i];
    } else if (!arg.startsWith('-')) {
      opts.query = opts.query ? `${opts.query} ${arg}` : arg;
    }
    i += 1;
  }
  return opts;
}

async function loadSearchEngine() {
  const root =
    process.env.FINDSKILLS_ROOT ||
    resolve(process.env.HOME || '', '.agent-reach', 'findskills');
  const enginePath = resolve(root, 'src', 'search-engine.js');
  const mod = await import(pathToFileURL(enginePath).href);
  return { SearchEngine: mod.default, root };
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const { SearchEngine } = await loadSearchEngine();
  const engine = new SearchEngine();

  let wrapped;
  if (opts.command === 'recommend') {
    const interests = opts.query.split(',').map((s) => s.trim()).filter(Boolean);
    wrapped = await engine.recommendForUser(interests, { limit: opts.limit });
  } else if (opts.command === 'popular') {
    wrapped = await engine.getPopularSkills({ limit: opts.limit });
  } else if (opts.source) {
    wrapped = await engine.searchFrom(opts.source, opts.query, {
      limit: opts.limit,
    });
  } else {
    wrapped = await engine.search(opts.query, { limit: opts.limit });
  }

  if (wrapped?.success === false) {
    process.stdout.write(JSON.stringify({ success: false, error: wrapped.error }));
    process.exit(1);
  }

  const data = wrapped?.data ?? wrapped;
  process.stdout.write(JSON.stringify({ success: true, data }));
}

main().catch((err) => {
  process.stdout.write(
    JSON.stringify({ success: false, error: { message: String(err.message || err) } })
  );
  process.exit(1);
});
