// Local exports and hosted builds share one snapshot format. Node's built-ins
// are enough; the hosting provider doesn't need Python, a model, or a database.
import { mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gzipSync, gunzipSync } from 'node:zlib';

const frontend = fileURLToPath(new URL('../', import.meta.url));
const defaultDataDir = join(frontend, 'public', 'data');
const defaultSnapshot = resolve(frontend, '../../backend/snapshots/predictions.json.gz');
const maxSnapshotBytes = 128 * 1024 * 1024;
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

function requireValid(condition, message) {
  if (!condition) throw new Error(`Invalid prediction data: ${message}`);
}

function parseJson(text, path) {
  requireValid(typeof text === 'string', `${path} must contain JSON text`);
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`Invalid prediction data: ${path} is not valid JSON`);
  }
}

// Construct paths only from validated manifest values, never from an archive's
// filenames. Every manifest entry must be present before we replace local data.
export function expectedFiles(index) {
  requireValid(object(index) && index.version === 1, 'unsupported index version');
  requireValid(index.scoring === 'ppr', 'unsupported scoring');
  requireValid(Number.isFinite(Date.parse(index.exported_at)), 'missing export timestamp');
  requireValid(Array.isArray(index.positions) && index.positions.length > 0 &&
    index.positions.every((position) => ['qb', 'rb', 'wr'].includes(position)) &&
    new Set(index.positions).size === index.positions.length, 'invalid positions');
  requireValid(Array.isArray(index.seasons) && index.seasons.length > 0, 'no exported seasons');
  const seasons = new Set();
  const paths = ['index.json'];
  for (const season of index.seasons) {
    requireValid(object(season) && Number.isInteger(season.season) && season.season >= 2000 &&
      !seasons.has(season.season), 'invalid or duplicate season');
    seasons.add(season.season);
    requireValid(Array.isArray(season.weeks) && season.weeks.length > 0, 'no exported weeks');
    const weeks = new Set();
    for (const week of season.weeks) {
      requireValid(object(week) && Number.isInteger(week.week) && week.week >= 1 && week.week <= 18 &&
        !weeks.has(week.week), 'invalid or duplicate week');
      weeks.add(week.week);
      for (const position of index.positions) {
        paths.push(`${season.season}/week-${String(week.week).padStart(2, '0')}/${position}.json`);
      }
    }
  }
  requireValid(seasons.has(index.default_season), 'default season was not exported');
  return paths;
}

export function validateFiles(files) {
  requireValid(object(files), 'missing files');
  const index = parseJson(files['index.json'], 'index.json');
  const paths = expectedFiles(index);
  requireValid(Object.keys(files).length === paths.length &&
    Object.keys(files).every((path) => paths.includes(path)), 'unexpected or missing files');
  for (const path of paths.slice(1)) {
    const file = parseJson(files[path], path);
    const [season, week, position] = path.match(/^(\d+)\/week-(\d+)\/(\w+)\.json$/).slice(1);
    requireValid(object(file) && file.version === 1 && file.season === Number(season) &&
      file.week === Number(week) && file.position === position && file.scoring === index.scoring,
    `${path} does not match its manifest entry`);
    requireValid(Array.isArray(file.players) && Array.isArray(file.predictions) &&
      Array.isArray(file.unavailable), `${path} is missing player results`);
    const results = new Set();
    for (const result of [...file.predictions, ...file.unavailable]) {
      requireValid(object(result) && typeof result.player_id === 'string' &&
        result.player_id.length > 0 && !results.has(result.player_id), `${path} has invalid player results`);
      results.add(result.player_id);
    }
    for (const prediction of file.predictions) {
      requireValid([prediction.predicted_points, prediction.confidence_low, prediction.confidence_high]
        .every(Number.isFinite), `${path} has invalid prediction points`);
    }
    requireValid(file.players.every((player) => object(player) &&
      typeof player.name === 'string' && results.has(player.player_id)), `${path} has players without results`);
  }
  return index;
}

export async function readExport(dataDir = defaultDataDir) {
  const files = {};
  try {
    files['index.json'] = await readFile(join(dataDir, 'index.json'), 'utf8');
    const paths = expectedFiles(parseJson(files['index.json'], 'index.json'));
    for (const path of paths.slice(1)) files[path] = await readFile(join(dataDir, path), 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') {
      throw new Error('Missing prediction export. Export locally, or set PREDICTIONS_SNAPSHOT_URL to a published snapshot.');
    }
    throw error;
  }
  validateFiles(files);
  return files;
}

export async function packSnapshot(dataDir = defaultDataDir, snapshotPath = defaultSnapshot) {
  const files = await readExport(dataDir);
  const bundle = Buffer.from(JSON.stringify({ version: 1, files }));
  requireValid(bundle.length <= maxSnapshotBytes, 'snapshot exceeds the 128 MiB unpacked limit');
  const compressed = gzipSync(bundle);
  await mkdir(dirname(snapshotPath), { recursive: true });
  const staging = await mkdtemp(join(dirname(snapshotPath), '.snapshot-'));
  try {
    await writeFile(join(staging, 'snapshot.gz'), compressed);
    await rename(join(staging, 'snapshot.gz'), snapshotPath);
  } finally {
    await rm(staging, { recursive: true, force: true });
  }
  return { index: parseJson(files['index.json'], 'index.json'), files: Object.keys(files).length,
    bytes: compressed.length, snapshotPath };
}

export function unpackSnapshot(bytes) {
  requireValid(bytes.length <= maxSnapshotBytes, 'download exceeds the 128 MiB limit');
  let bundle;
  try {
    bundle = JSON.parse(gunzipSync(bytes, { maxOutputLength: maxSnapshotBytes }).toString('utf8'));
  } catch {
    throw new Error('Invalid prediction snapshot: expected a gzip JSON bundle (version 1).');
  }
  requireValid(object(bundle) && bundle.version === 1, 'unsupported snapshot version');
  validateFiles(bundle.files);
  return bundle.files;
}

async function replaceExport(files, dataDir) {
  const parent = dirname(dataDir);
  await mkdir(parent, { recursive: true });
  // Both temporary paths are created inside the export's parent. Cleanup only
  // touches those exact directories, and preserves the prior export on failure.
  const staging = await mkdtemp(join(parent, '.prediction-data-'));
  let movedOld = false;
  let installed = false;
  try {
    const next = join(staging, 'next');
    await mkdir(next);
    for (const [path, content] of Object.entries(files)) {
      await mkdir(dirname(join(next, path)), { recursive: true });
      await writeFile(join(next, path), content);
    }
    try {
      await rename(dataDir, join(staging, 'previous'));
      movedOld = true;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    try {
      await rename(next, dataDir);
      installed = true;
    } catch (error) {
      if (movedOld) {
        await rename(join(staging, 'previous'), dataDir);
        movedOld = false;
      }
      throw error;
    }
  } finally {
    // If rollback also failed, keep 'previous' available for recovery.
    if (!movedOld || installed) await rm(staging, { recursive: true, force: true });
  }
}

async function downloadSnapshot(url) {
  // A release asset can briefly be unavailable while a local publish replaces
  // it. Retry downloads, but never silently deploy cached data after a failure.
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(45_000) });
      if (!response.ok) throw new Error(`Snapshot download failed (HTTP ${response.status}).`);
      if (Number(response.headers.get('content-length')) > maxSnapshotBytes) {
        throw new Error('Prediction snapshot download is too large.');
      }
      const chunks = [];
      let size = 0;
      for await (const chunk of response.body) {
        size += chunk.length;
        if (size > maxSnapshotBytes) throw new Error('Prediction snapshot download is too large.');
        chunks.push(chunk);
      }
      return Buffer.concat(chunks);
    } catch (error) {
      if (attempt === 2) throw error;
      await new Promise((resolve) => setTimeout(resolve, 1_000));
    }
  }
}

export async function prepareData({ dataDir = defaultDataDir,
  url = process.env.PREDICTIONS_SNAPSHOT_URL, local = false } = {}) {
  let files;
  if (url && !local) {
    files = unpackSnapshot(await downloadSnapshot(url));
    await replaceExport(files, dataDir);
  } else {
    files = await readExport(dataDir);
  }
  return { index: parseJson(files['index.json'], 'index.json'), files: Object.keys(files).length };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const command = process.argv[2];
    let result;
    if (command === 'pack') result = await packSnapshot();
    else if (command === 'prepare') result = await prepareData({ local: process.argv.includes('--local') });
    else throw new Error('Usage: node scripts/prediction-data.mjs pack | prepare [--local]');
    console.log(`Predictions: ${result.files} files, exported ${result.index.exported_at}.`);
    if (result.snapshotPath) console.log(`Snapshot: ${result.snapshotPath} (${result.bytes} bytes).`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
