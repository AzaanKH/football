import { buildRequest, isStale, requestKey } from './predictionState';

const A = { player_id: 'a', name: 'Player A' };
const B = { player_id: 'b', name: 'Player B' };

test('buildRequest ignores empty slots and duplicate players', () => {
  expect(buildRequest({ season: 2025, week: 7, position: 'rb', players: [A, null, A, B] }))
    .toEqual({ season: 2025, week: 7, position: 'rb', playerIds: ['a', 'b'] });
});

test('requestKey ignores player order', () => {
  const ab = buildRequest({ season: 2025, week: 7, position: 'rb', players: [A, B] });
  const ba = buildRequest({ season: 2025, week: 7, position: 'rb', players: [B, A] });
  expect(requestKey(ab)).toBe(requestKey(ba));
});

test('a result is stale once week, season, position or players change', () => {
  const request = buildRequest({ season: 2025, week: 7, position: 'rb', players: [A] });
  const result = { request };

  expect(isStale(result, request)).toBe(false);
  expect(isStale(result, { ...request, week: 8 })).toBe(true);
  expect(isStale(result, { ...request, season: 2024 })).toBe(true);
  expect(isStale(result, { ...request, position: 'wr' })).toBe(true);
  expect(isStale(result, { ...request, playerIds: ['a', 'b'] })).toBe(true);
  expect(isStale(null, request)).toBe(false);
});
