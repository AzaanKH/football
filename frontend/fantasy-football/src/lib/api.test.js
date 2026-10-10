import { vi } from 'vitest';

const INDEX = {
  exported_at: '2026-10-09T22:38:22Z',
  default_season: 2026,
  current_week: { season: 2026, week: 5, season_type: 'regular' },
  stats_through: { season: 2026, week: 4 },
  seasons: [
    { season: 2026, weeks: [{ week: 4, players: 300 }, { week: 5, players: 310 }] },
    { season: 2025, weeks: [{ week: 18, players: 320 }] },
  ],
};

const prediction = (id, name, points) => ({
  player_id: id, player_name: name, predicted_points: points,
  confidence_low: points - 8, confidence_high: points + 8, features: {}, context: {},
});

const WEEK = {
  scoring: 'ppr',
  players: [
    { player_id: '9221', name: 'Jahmyr Gibbs', team: 'DET' },
    { player_id: '4866', name: 'Saquon Barkley', team: 'PHI' },
    { player_id: '1', name: 'Bye Back', team: 'DEN' },
  ],
  predictions: [prediction('9221', 'Jahmyr Gibbs', 25.7), prediction('4866', 'Saquon Barkley', 18.2)],
  unavailable: [{ player_id: '1', player_name: 'Bye Back', reason: 'bye', message: 'On bye.' }],
  freshness: { projections_synced_at: '2026-10-09T04:25:13Z' },
  current_week: INDEX.current_week,
};

const FILES = { 'index.json': INDEX, '2026/week-05/rb.json': WEEK };

let api;
let fetchMock;

beforeEach(async () => {
  fetchMock = vi.fn(async (url) => {
    const file = FILES[url.replace(/^\/data\//, '')];
    // Like `vite preview`: an unknown path gets the HTML page, not a 404
    return file
      ? new Response(JSON.stringify(file), { headers: { 'content-type': 'application/json' } })
      : new Response('<!doctype html>', { headers: { 'content-type': 'text/html' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  vi.resetModules(); // fresh file cache per test
  api = await import('./api');
});

afterEach(() => vi.unstubAllGlobals());

const RB_WEEK_5 = { position: 'rb', season: 2026, week: 5 };

test('seasons and weeks come from the index, which is fetched once', async () => {
  const data = await api.getSeasons();
  expect(data).toMatchObject({
    seasons: [2026, 2025], default: 2026, exportedAt: INDEX.exported_at, currentWeekSaved: true,
  });
  expect(await api.getWeeks(2025)).toEqual([{ week: 18, players: 320 }]);
  expect(await api.getWeeks(2019)).toEqual([]);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test('search filters the week file by name or exact team, keeping its ranking', async () => {
  expect((await api.searchPlayers({ ...RB_WEEK_5, search: '' })).map((p) => p.name))
    .toEqual(['Jahmyr Gibbs', 'Saquon Barkley', 'Bye Back']);
  expect(await api.searchPlayers({ ...RB_WEEK_5, search: ' saq ' }))
    .toEqual([{ player_id: '4866', name: 'Saquon Barkley', team: 'PHI' }]);
  expect((await api.searchPlayers({ ...RB_WEEK_5, search: 'det' })).map((p) => p.name)).toEqual(['Jahmyr Gibbs']);
  expect(await api.searchPlayers({ ...RB_WEEK_5, search: 'de' })).toEqual([]); // team must match exactly
  expect(await api.searchPlayers({ ...RB_WEEK_5, limit: 1 })).toHaveLength(1);
  expect(fetchMock).toHaveBeenCalledWith('/data/2026/week-05/rb.json');
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test('predictWeek returns the requested players, ranked, with unavailable ones explained', async () => {
  const data = await api.predictWeek({ ...RB_WEEK_5, playerIds: ['1', '4866', '9221', 'nobody'] });

  expect(data.predictions.map((p) => p.player_id)).toEqual(['9221', '4866']);
  expect(data.unavailable.map((p) => [p.player_id, p.reason])).toEqual([
    ['1', 'bye'], ['nobody', 'not_exported'],
  ]);
  expect(data).toMatchObject({ season: 2026, week: 5, freshness: WEEK.freshness, current_week: INDEX.current_week });
});

test('a week that was not exported is a user-facing error, retried next time', async () => {
  const request = { position: 'rb', season: 2026, week: 6, playerIds: ['9221'] };
  const error = await api.predictWeek(request).catch((e) => e);

  expect(error).toBeInstanceOf(api.DataError);
  expect(api.errorMessage(error, 'fallback')).toBe('No saved predictions for week 6 of 2026.');
  await api.predictWeek(request).catch(() => {});
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test('aborting one caller cancels its wait, not the shared download', async () => {
  const controller = new AbortController();
  const aborted = api.searchPlayers(RB_WEEK_5, controller.signal);
  controller.abort();

  const error = await aborted.catch((e) => e);
  expect(api.isCancel(error)).toBe(true);
  expect(api.errorMessage(new Error('boom'), 'fallback')).toBe('fallback');
  expect(await api.searchPlayers(RB_WEEK_5)).toHaveLength(3);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
