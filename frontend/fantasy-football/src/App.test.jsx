import { vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import * as api from './lib/api';

vi.mock('./lib/api', () => ({
  getSeasons: vi.fn(),
  getWeeks: vi.fn(),
  searchPlayers: vi.fn(),
  predictWeek: vi.fn(),
  isCancel: (error) => error?.name === 'AbortError',
  errorMessage: (error, fallback) => (error?.name === 'DataError' ? error.message : fallback),
}));

const PLAYERS = [
  { player_id: '3198', name: 'Derrick Henry', team: 'BAL' },
  { player_id: '9509', name: 'Bijan Robinson', team: 'ATL' },
];

const prediction = (player, points) => ({
  player_id: player.player_id,
  player_name: player.name,
  predicted_points: points,
  confidence_low: points - 8,
  confidence_high: points + 8,
  features: { avg_3_games: points, trend: 'improving', projection_source: 'sleeper' },
  context: { team: player.team, opponent: 'CIN', is_home: false, kickoff: null, injury_status: 'Questionable' },
});

const FRESHNESS = {
  projections_synced_at: '2026-10-05T08:30:00Z',
  stats_synced_at: '2026-01-13T03:56:00Z',
  players_synced_at: '2026-04-28T04:34:00Z',
  stats_through: { season: 2025, week: 18 },
  model_trained_at: '2026-10-05T09:00:00Z',
};

const response = (predictions, extra = {}) => ({
  predictions, unavailable: [], freshness: FRESHNESS,
  current_week: { season: 2026, week: 5 }, ...extra,
});

const DAY_MS = 24 * 60 * 60 * 1000;

const savedData = (extra = {}) => ({
  seasons: [2025, 2024],
  default: 2025,
  currentWeek: { season: 2025, week: 7 },
  currentWeekSaved: true,
  exportedAt: new Date(Date.now() - DAY_MS).toISOString(),
  statsThrough: { season: 2025, week: 6 },
  ...extra,
});

beforeEach(() => {
  api.getSeasons.mockResolvedValue(savedData());
  api.getWeeks.mockResolvedValue([{ week: 6, players: 500 }, { week: 7, players: 510 }]);
  api.searchPlayers.mockImplementation(async ({ search }) =>
    PLAYERS.filter((p) => !search || p.name.toLowerCase().includes(search.toLowerCase()))
  );
});

async function renderReady() {
  render(<App />);
  await screen.findByRole('button', { name: 'Compare week 7' });
}

async function selectPlayer(user, name) {
  // Pick into the first empty slot, like a user would
  const [emptySlot] = await screen.findAllByRole('combobox', { name: /search for a player/i });
  await user.click(emptySlot);
  await user.click(await screen.findByRole('option', { name: new RegExp(name, 'i') }));
  await waitFor(() => expect(screen.queryByRole('option')).not.toBeInTheDocument());
  // Radix returns focus to the trigger on close; in jsdom that lands a tick later,
  // and opening another popover before it does would immediately dismiss it.
  const trigger = await screen.findByRole('combobox', { name: new RegExp(`player: ${name}`, 'i') });
  await waitFor(() => expect(trigger).toHaveFocus());
}

const predictButton = () => screen.getByRole('button', { name: /^compare week/i });

test('uses the season and latest week from the backend', async () => {
  const user = userEvent.setup();
  await renderReady();

  expect(api.getWeeks).toHaveBeenCalledWith(2025, expect.anything());
});

test('player search uses the selected season, week and position', async () => {
  const user = userEvent.setup();
  await renderReady();

  await user.click(screen.getByRole('combobox', { name: /search for a player/i }));
  await user.type(await screen.findByPlaceholderText(/search by name or team/i), 'bij');

  await screen.findByRole('option', { name: /bijan robinson/i });
  await waitFor(() =>
    expect(api.searchPlayers).toHaveBeenLastCalledWith(
      { position: 'rb', season: 2025, week: 7, search: 'bij' },
      expect.anything()
    )
  );
  expect(screen.queryByRole('option', { name: /derrick henry/i })).not.toBeInTheDocument();
});

test('results keep their own labels and are flagged stale when inputs change', async () => {
  const user = userEvent.setup();
  api.predictWeek.mockResolvedValue(response([prediction(PLAYERS[0], 19.6)]));
  await renderReady();

  await selectPlayer(user, 'Derrick Henry');
  await user.click(predictButton());

  expect(await screen.findByRole('heading', { name: 'Derrick Henry projects 19.6 points' })).toBeInTheDocument();
  expect(screen.getByText('Week 7, 2025')).toBeInTheDocument();
  expect(api.predictWeek).toHaveBeenCalledWith(
    { season: 2025, week: 7, position: 'rb', playerIds: ['3198'] },
    expect.anything()
  );
  expect(screen.queryByText(/previous selection/i)).not.toBeInTheDocument();
  expect(screen.getByRole('listitem', {
    name: 'Derrick Henry: 19.6 projected PPR points, 80% range 11.6 to 27.6, at CIN, Sleeper projection',
  })).toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: /add player/i }));
  await selectPlayer(user, 'Bijan Robinson');

  const banner = await screen.findByRole('status');
  expect(banner).toHaveTextContent('These results are for your previous selection (Week 7).');
  // old result still visible, labeled with its own week
  expect(screen.getByRole('heading', { name: 'Derrick Henry projects 19.6 points' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Update for Week 7' })).toBeInTheDocument();
});

test('changing inputs cancels a pending prediction and ignores its answer', async () => {
  const user = userEvent.setup();
  let pendingSignal;
  api.predictWeek.mockImplementation((request, signal) => {
    pendingSignal = signal;
    return new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject({ name: 'AbortError' }));
    });
  });
  await renderReady();

  await selectPlayer(user, 'Derrick Henry');
  await user.click(predictButton());
  await screen.findByRole('heading', { name: 'Comparing week 7...' });

  await user.click(screen.getByRole('button', { name: /add player/i }));
  await selectPlayer(user, 'Bijan Robinson');

  await waitFor(() => expect(pendingSignal.aborted).toBe(true));
  expect(screen.queryByText(/comparing week/i)).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument(); // a cancel is not an error
  expect(screen.getByRole('heading', { name: 'Who should you start?' })).toBeInTheDocument();
});

test('shows unavailable players with their reason', async () => {
  const user = userEvent.setup();
  api.predictWeek.mockResolvedValue(response([prediction(PLAYERS[0], 19.6)], {
    unavailable: [
      { player_id: '9509', player_name: 'Bijan Robinson', reason: 'no_history',
        message: 'No games played before this week.' },
      { player_id: '1', player_name: 'Bye Back', reason: 'bye', message: 'On bye this week.' },
    ],
  }));
  await renderReady();

  await selectPlayer(user, 'Derrick Henry');
  await user.click(predictButton());

  const notProjected = (await screen.findByRole('heading', { name: 'Not projected' })).closest('div');
  expect(within(notProjected).getByText('Bijan Robinson')).toBeInTheDocument();
  expect(within(notProjected).getByText('No games played before this week.')).toBeInTheDocument();
  expect(within(notProjected).getByText('Bye week')).toBeInTheDocument();
});

test('says which week has no saved predictions when loading fails', async () => {
  const user = userEvent.setup();
  api.predictWeek.mockRejectedValue({ name: 'DataError', message: 'No saved predictions for week 7 of 2025.' });
  await renderReady();

  await selectPlayer(user, 'Derrick Henry');
  await user.click(predictButton());

  expect(await screen.findByRole('alert')).toHaveTextContent('No saved predictions for week 7 of 2025.');
});

test('shows a setup error when the saved predictions cannot be loaded', async () => {
  api.getSeasons.mockRejectedValue(new TypeError('Failed to fetch'));
  render(<App />);

  expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load the saved predictions. Try reloading.");
});

test('describes the saved data and its freshness before comparing', async () => {
  await renderReady();

  const summary = screen.getByText(/saved predictions for the 2024-2025 seasons, exported/i);
  expect(summary).toHaveTextContent('Stats through 2025 week 6.');
  expect(summary).not.toHaveTextContent(/hasn't been exported/);
  expect(screen.queryByText(/may be out of date/i)).not.toBeInTheDocument();
});

test('flags an old export and a current week that was not saved', async () => {
  api.getSeasons.mockResolvedValue(savedData({
    exportedAt: new Date(Date.now() - 10 * DAY_MS).toISOString(),
    currentWeek: { season: 2025, week: 8 },
    currentWeekSaved: false,
  }));
  await renderReady();

  expect(screen.getByRole('status')).toHaveTextContent('These predictions were saved 10 days ago and may be out of date.');
  expect(screen.getByText(/week 8 of 2025 hasn't been exported yet/i)).toBeInTheDocument();
});

test('names the decision: start the clear leader, or flag a close call', async () => {
  const user = userEvent.setup();
  api.predictWeek.mockResolvedValueOnce(response([prediction(PLAYERS[1], 21.2), prediction(PLAYERS[0], 16.8)]));
  await renderReady();
  await selectPlayer(user, 'Derrick Henry');
  await user.click(screen.getByRole('button', { name: /add player/i }));
  await selectPlayer(user, 'Bijan Robinson');
  await user.click(predictButton());

  expect(await screen.findByRole('heading', { name: 'Start Bijan Robinson' })).toBeInTheDocument();
  expect(screen.getByText('Projects 4.4 more points than Derrick Henry.')).toBeInTheDocument();
  // The recommended player is pictured; the other isn't
  expect(screen.getAllByTestId('player-cutout').map((img) => img.getAttribute('src'))).toEqual([
    'https://sleepercdn.com/content/nfl/players/thumb/9509.jpg',
  ]);

  api.predictWeek.mockResolvedValueOnce(response([prediction(PLAYERS[1], 17.0), prediction(PLAYERS[0], 16.8)]));
  await user.click(predictButton());
  expect(await screen.findByRole('heading', { name: 'Close call: Bijan Robinson or Derrick Henry' }))
    .toBeInTheDocument();
  expect(screen.getAllByTestId('player-cutout')).toHaveLength(2); // both, same size
});

test('shows injury status only when the result is for the current week, and says why', async () => {
  const user = userEvent.setup();
  api.predictWeek.mockResolvedValue(response([prediction(PLAYERS[0], 19.6)]));
  await renderReady();
  await selectPlayer(user, 'Derrick Henry');
  await user.click(predictButton());

  await screen.findByRole('heading', { name: 'Derrick Henry projects 19.6 points' });
  expect(screen.queryByText('Questionable')).not.toBeInTheDocument();
  expect(screen.getByText(/injury status is shown only for the current week \(2026 week 5\)/i)).toBeInTheDocument();
  expect(screen.getByText(/stats through 2025 week 18/i)).toBeInTheDocument();
  expect(screen.getByText(/predictions saved/i)).toBeInTheDocument();
  expect(screen.getByText(/all points are ppr/i)).toBeInTheDocument();
});

test('shows the injury chip for the current week', async () => {
  const user = userEvent.setup();
  api.predictWeek.mockResolvedValue(response([prediction(PLAYERS[0], 19.6)], {
    current_week: { season: 2025, week: 7 },
  }));
  await renderReady();
  await selectPlayer(user, 'Derrick Henry');
  await user.click(predictButton());

  expect(await screen.findByText('Questionable')).toBeInTheDocument();
});

test('the chart has a table view with the same values', async () => {
  const user = userEvent.setup();
  api.predictWeek.mockResolvedValue(response([prediction(PLAYERS[0], 19.6)]));
  await renderReady();
  await selectPlayer(user, 'Derrick Henry');
  await user.click(predictButton());

  await user.click(await screen.findByRole('button', { name: 'Show as table' }));

  const row = await screen.findByRole('row', { name: /derrick henry/i });
  expect(within(row).getByText('19.6')).toBeInTheDocument();
  expect(within(row).getByText('11.6 to 27.6')).toBeInTheDocument();
  expect(within(row).getByText('Sleeper projection')).toBeInTheDocument();
  expect(within(row).getByText('BAL @ CIN')).toBeInTheDocument();
});
