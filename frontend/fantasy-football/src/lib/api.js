/**
 * Data access: saved predictions exported as static JSON
 * (backend/export_static.py -> public/data/), so no server is needed.
 *
 *   data/index.json                          seasons, weeks, export freshness
 *   data/<season>/week-<NN>/<position>.json  search list + every player's result
 */

// Relative to the app's base path, so the build works from any subfolder
const DATA_BASE = `${import.meta.env.BASE_URL}data/`;
const SEARCH_LIMIT = 50;

/** A load failed in a way the user should be told about (message is user-facing). */
export class DataError extends Error {
  constructor(message) {
    super(message);
    this.name = 'DataError';
  }
}

/** True when a request was cancelled via its AbortSignal (not a real failure). */
export const isCancel = (error) => error?.name === 'AbortError';

/** Human-readable message for a failed load. */
export const errorMessage = (error, fallback) =>
  error instanceof DataError ? error.message : fallback;

// One download per file for the session: search and compare share it
const cache = new Map();

function loadJson(path, missingMessage) {
  if (!cache.has(path)) {
    const promise = fetch(DATA_BASE + path)
      .then(async (response) => {
        // A static host may answer a missing file with index.html, so check the type too
        const type = response.headers.get('content-type') || '';
        if (!response.ok || !type.includes('json')) throw new DataError(missingMessage);
        return response.json();
      })
      .catch((error) => {
        cache.delete(path); // retry on the next call
        throw error instanceof DataError ? error : new DataError(missingMessage);
      });
    cache.set(path, promise);
  }
  return cache.get(path);
}

/** The shared download, abandoned (not cancelled: others may share it) on abort. */
function withSignal(promise, signal) {
  if (!signal) return promise;
  const aborted = () => new DOMException('Aborted', 'AbortError');
  if (signal.aborted) return Promise.reject(aborted());
  return new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(aborted()), { once: true });
    promise.then(resolve, reject);
  });
}

const getIndex = () =>
  loadJson('index.json', "Couldn't load the saved predictions. Try reloading.");

const weekFilePath = (season, week, position) =>
  `${season}/week-${String(week).padStart(2, '0')}/${position}.json`;

function getWeekFile({ season, week, position }, signal) {
  const path = weekFilePath(season, week, position);
  return withSignal(
    loadJson(path, `No saved predictions for week ${week} of ${season}.`),
    signal
  );
}

/**
 * Seasons with saved predictions, newest first, the default to show, and
 * when the export was made.
 */
export async function getSeasons() {
  const index = await getIndex();
  const current = index.current_week;
  return {
    seasons: index.seasons.map((s) => s.season),
    default: index.default_season,
    currentWeek: current,
    // Whether the NFL week that was current at export time was saved
    currentWeekSaved: Boolean(current) && index.seasons.some(
      (s) => s.season === current.season && s.weeks.some((w) => w.week === current.week)
    ),
    exportedAt: index.exported_at,
    statsThrough: index.stats_through,
  };
}

export async function getWeeks(season, signal) {
  const index = await withSignal(getIndex(), signal);
  return index.seasons.find((s) => s.season === season)?.weeks ?? [];
}

/**
 * Search the week's predictable players, most productive first: by name, or
 * by exact team abbreviation (as the server did).
 */
export async function searchPlayers({ position, season, week, search, limit = SEARCH_LIMIT }, signal) {
  const file = await getWeekFile({ season, week, position }, signal);
  const query = (search || '').trim().toLowerCase();
  const matches = query
    ? file.players.filter(
        (p) => p.name?.toLowerCase().includes(query) || p.team?.toLowerCase() === query
      )
    : file.players;
  return matches.slice(0, limit).map((p) => ({ player_id: p.player_id, name: p.name, team: p.team }));
}

/**
 * Saved results for the requested players, in the /predict_week shape:
 * predictions highest first, then unavailable players in request order.
 */
export async function predictWeek({ position, playerIds, week, season }, signal) {
  const file = await getWeekFile({ season, week, position }, signal);
  const predictions = new Map(file.predictions.map((p) => [p.player_id, p]));
  const unavailable = new Map(file.unavailable.map((p) => [p.player_id, p]));

  const ids = [...new Set(playerIds)];
  return {
    week,
    season,
    position,
    scoring: file.scoring,
    predictions: ids
      .filter((id) => predictions.has(id))
      .map((id) => predictions.get(id))
      .sort((a, b) => b.predicted_points - a.predicted_points),
    unavailable: ids
      .filter((id) => !predictions.has(id))
      .map((id) => unavailable.get(id) ?? {
        player_id: id,
        player_name: null,
        reason: 'not_exported',
        message: 'No saved prediction for this player this week.',
      }),
    freshness: file.freshness,
    current_week: file.current_week,
  };
}
