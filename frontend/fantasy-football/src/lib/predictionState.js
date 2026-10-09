/**
 * Prediction request identity.
 *
 * Results are stored together with the request that produced them, so the UI
 * always labels them with *their* season/week/players, and can tell when the
 * current inputs no longer match (stale results).
 */

/** Normalized request for the current inputs; players is a list of slots. */
export function buildRequest({ season, week, position, players }) {
  const playerIds = [...new Set(players.filter(Boolean).map((p) => p.player_id))];
  return { season, week, position, playerIds };
}

/** Order-insensitive identity: reordering the same players isn't a new request. */
export function requestKey(request) {
  if (!request) return '';
  const { season, week, position, playerIds } = request;
  return JSON.stringify([season, week, position, [...playerIds].sort()]);
}

/** Whether a stored result no longer matches the current inputs. */
export function isStale(result, currentRequest) {
  return Boolean(result) && requestKey(result.request) !== requestKey(currentRequest);
}
