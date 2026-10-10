import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile, mkdir } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { gzipSync } from 'node:zlib';
import { packSnapshot, prepareData, readExport, unpackSnapshot, validateFiles } from '../prediction-data.mjs';

function fixture(exportedAt = '2026-10-09T22:38:22Z') {
  return {
    'index.json': JSON.stringify({ version: 1, exported_at: exportedAt, scoring: 'ppr',
      positions: ['rb'], seasons: [{ season: 2026, weeks: [{ week: 5, players: 1 }] }],
      default_season: 2026 }),
    '2026/week-05/rb.json': JSON.stringify({ version: 1, season: 2026, week: 5,
      position: 'rb', scoring: 'ppr', players: [{ player_id: '1', name: 'Test Player', team: 'DET' }],
      predictions: [{ player_id: '1', predicted_points: 20, confidence_low: 12, confidence_high: 28 }],
      unavailable: [] }),
  };
}

const snapshot = (files) => gzipSync(JSON.stringify({ version: 1, files }));

async function workspace(t) {
  const root = await mkdtemp(join(tmpdir(), 'football-snapshot-test-'));
  // Cleanup only this exact temporary directory, returned by mkdtemp.
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

async function writeExport(dataDir, files) {
  for (const [path, content] of Object.entries(files)) {
    const file = join(dataDir, path);
    await mkdir(join(file, '..'), { recursive: true });
    await writeFile(file, content);
  }
}

async function serve(t, handler) {
  const server = createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve())));
  return `http://127.0.0.1:${server.address().port}/predictions.json.gz`;
}

test('pack/unpack preserves the complete export and can replace an existing snapshot', async (t) => {
  const root = await workspace(t);
  const dataDir = join(root, 'data');
  const snapshotPath = join(root, 'snapshots', 'predictions.json.gz');
  await writeExport(dataDir, fixture());
  const result = await packSnapshot(dataDir, snapshotPath);
  assert.equal(result.files, 2);
  assert.deepEqual(unpackSnapshot(await readFile(snapshotPath)), fixture());
  const updated = fixture('2026-10-10T12:00:00Z');
  await writeExport(dataDir, updated);
  await packSnapshot(dataDir, snapshotPath);
  assert.deepEqual(unpackSnapshot(await readFile(snapshotPath)), updated);
});

test('a missing week refuses packaging and preserves the previous snapshot', async (t) => {
  const root = await workspace(t);
  const dataDir = join(root, 'data');
  const snapshotPath = join(root, 'predictions.json.gz');
  await writeExport(dataDir, fixture());
  await packSnapshot(dataDir, snapshotPath);
  const previous = await readFile(snapshotPath);
  await rm(join(dataDir, '2026/week-05/rb.json'));
  await assert.rejects(packSnapshot(dataDir, snapshotPath), /Missing prediction export/);
  assert.deepEqual(await readFile(snapshotPath), previous);
});

test('missing local data stops a deployment build with setup instructions', async (t) => {
  const root = await workspace(t);
  await assert.rejects(prepareData({ dataDir: join(root, 'data'), url: '' }), /PREDICTIONS_SNAPSHOT_URL/);
});

test('snapshot validation rejects unsafe paths, missing files, and incompatible payloads', () => {
  assert.throws(() => unpackSnapshot(Buffer.from('<html>not a snapshot</html>')), /gzip JSON/);
  assert.throws(() => unpackSnapshot(gzipSync(JSON.stringify({ version: 2, files: fixture() }))), /version/);
  assert.throws(() => unpackSnapshot(snapshot({ ...fixture(), '../outside.json': '{}' })), /unexpected/);
  const missing = fixture();
  delete missing['2026/week-05/rb.json'];
  assert.throws(() => validateFiles(missing), /missing files/);
  const mismatch = fixture();
  const week = JSON.parse(mismatch['2026/week-05/rb.json']);
  mismatch['2026/week-05/rb.json'] = JSON.stringify({ ...week, week: 6 });
  assert.throws(() => validateFiles(mismatch), /manifest entry/);
  week.predictions[0].predicted_points = null;
  mismatch['2026/week-05/rb.json'] = JSON.stringify(week);
  assert.throws(() => validateFiles(mismatch), /prediction points/);
});

test('a hosted build downloads all files into a fresh checkout without a backend', async (t) => {
  const root = await workspace(t);
  const files = fixture();
  const url = await serve(t, (_request, response) => response.end(snapshot(files)));
  const dataDir = join(root, 'public/data');
  const result = await prepareData({ dataDir, url });
  assert.equal(result.files, 2);
  assert.deepEqual(await readExport(dataDir), files);
});

test('a hosted build replaces cached data, while explicit local builds use the local export', async (t) => {
  const root = await workspace(t);
  const dataDir = join(root, 'data');
  const latest = fixture('2026-10-10T12:00:00Z');
  const url = await serve(t, (_request, response) => response.end(snapshot(latest)));
  await writeExport(dataDir, fixture());
  assert.equal((await prepareData({ dataDir, url, local: true })).index.exported_at, '2026-10-09T22:38:22Z');
  await prepareData({ dataDir, url });
  assert.deepEqual(await readExport(dataDir), latest);
});

test('invalid downloaded data preserves the previous export and fails the build', async (t) => {
  const root = await workspace(t);
  const dataDir = join(root, 'data');
  await writeExport(dataDir, fixture());
  const url = await serve(t, (_request, response) => response.end(snapshot({ ...fixture(), '/bad.json': '{}' })));
  await assert.rejects(prepareData({ dataDir, url }), /unexpected/);
  assert.deepEqual(await readExport(dataDir), fixture());
});

test('temporary missing release assets are retried; persistent failures never use cached data', async (t) => {
  const root = await workspace(t);
  const dataDir = join(root, 'data');
  await writeExport(dataDir, fixture());
  let requests = 0;
  const url = await serve(t, (_request, response) => {
    requests++;
    if (requests === 1) response.writeHead(404).end();
    else response.end(snapshot(fixture('2026-10-10T12:00:00Z')));
  });
  await prepareData({ dataDir, url });
  assert.equal(requests, 2);
  const failedUrl = await serve(t, (_request, response) => response.writeHead(503).end());
  await assert.rejects(prepareData({ dataDir, url: failedUrl }), /HTTP 503/);
  assert.deepEqual(await readExport(dataDir), fixture('2026-10-10T12:00:00Z'));
});
