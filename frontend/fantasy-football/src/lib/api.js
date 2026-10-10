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
 * Which NFL week is current right now, from the export.
 *
 * The week current at export time stays current until its `expires_at`
 * (its last game finished). After that the export has rolled over: the
 * current week is the first one in the exported calendar that hasn't
 * finished (the backend's data_pipeline/season.py rule), or null once the
 * regular season is over. Exports without an expiry (older files, or
 * outside the regular season) keep the exported week.
 */
export function weekStatus(index, now = Date.now()) {
  const exported = index.current_week ?? null;
  const expiresAt = exported?.expires_at ? Date.parse(exported.expires_at) : NaN;
  if (!exported || Number.isNaN(expiresAt) || now < expiresAt) {
    return { currentWeek: exported, exportedWeek: exported, rolledOver: false };
  }
  const calendar = index.calendar?.season === exported.season ? index.calendar.weeks : [];
  const next = calendar.find((w) => now < Date.parse(w.finished_at));
  return {
    currentWeek: next ? { season: exported.season, week: next.week, season_type: 'regular' } : null,
    exportedWeek: exported,
    rolledOver: true,
  };
}

const isSaved = (index, week) => Boolean(week) && index.seasons.some(
  (s) => s.season === week.season && s.weeks.some((w) => w.week === week.week)
);

/**
 * Seasons with saved predictions, newest first, the default to show, when
 * the export was made, and where the NFL calendar is now.
 */
export async function getSeasons() {
  const index = await getIndex();
  const { currentWeek, exportedWeek, rolledOver } = weekStatus(index);
  return {
    seasons: index.seasons.map((s) => s.season),
    default: index.default_season,
    currentWeek,
    currentWeekSaved: isSaved(index, currentWeek),
    // The week current at export time, and whether it has finished since
    exportedWeek,
    weekRolledOver: rolledOver,
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
  const [file, index] = await Promise.all([
    getWeekFile({ season, week, position }, signal),
    withSignal(getIndex(), signal),
  ]);
  const { currentWeek, rolledOver } = weekStatus(index);
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
    current_week: currentWeek,
    // Injury statuses were captured at export time: current only until that week ends
    injury_status_current: !rolledOver,
  };
}
