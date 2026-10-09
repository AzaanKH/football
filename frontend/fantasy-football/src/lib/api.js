import axios from 'axios';

// Override with REACT_APP_API_BASE (e.g. in .env.local) when the API isn't local
const http = axios.create({
  baseURL: process.env.REACT_APP_API_BASE || 'http://localhost:5001',
});

/** True when a request was cancelled via its AbortSignal (not a real failure). */
export const isCancel = (error) => axios.isCancel(error);

/** Human-readable message from an API error response. */
export const errorMessage = (error, fallback) =>
  error?.response?.data?.error || fallback;

export async function getModelStatus() {
  const { data } = await http.get('/model_status');
  return data;
}

/** Seasons with data, newest first, plus the default to show. */
export async function getSeasons() {
  const { data } = await http.get('/seasons');
  return data;
}

export async function getWeeks(season, signal) {
  const { data } = await http.get('/available_weeks', { params: { season }, signal });
  return data.weeks || [];
}

/**
 * Server-side player search. With season+week, returns only players that can
 * be predicted that week, most productive first.
 */
export async function searchPlayers({ position, season, week, search, limit = 50 }, signal) {
  const { data } = await http.get('/players', {
    params: { position, season, week, search: search || undefined, limit },
    signal,
  });
  return data.map((p) => ({ player_id: p.player_id, name: p.full_name, team: p.team }));
}

export async function predictWeek({ position, playerIds, week, season }, signal) {
  const { data } = await http.post(
    '/predict_week',
    { position, player_ids: playerIds, week, season },
    { signal }
  );
  return data;
}
