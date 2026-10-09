import { vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import * as api from './lib/api';

vi.mock('./lib/api', () => ({
  getModelStatus: vi.fn(),
  getSeasons: vi.fn(),
  getWeeks: vi.fn(),
  searchPlayers: vi.fn(),
  predictWeek: vi.fn(),
  isCancel: (error) => error?.name === 'CanceledError',
  errorMessage: (error, fallback) => error?.response?.data?.error || fallback,
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

beforeEach(() => {
  api.getModelStatus.mockResolvedValue({ weekly_predictor_available: true });
  api.getSeasons.mockResolvedValue({ seasons: [2025, 2024], default: 2025 });
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

test('player search runs on the server for the selected week', async () => {
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
      signal.addEventListener('abort', () => reject({ name: 'CanceledError' }));
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

test('shows the API error message when prediction fails', async () => {
  const user = userEvent.setup();
  api.predictWeek.mockRejectedValue({ response: { data: { error: 'Weekly predictor not available' } } });
  await renderReady();

  await selectPlayer(user, 'Derrick Henry');
  await user.click(predictButton());

  expect(await screen.findByRole('alert')).toHaveTextContent('Weekly predictor not available');
});

test('shows a setup error when the backend is unreachable', async () => {
  const user = userEvent.setup();
  api.getSeasons.mockRejectedValue(new Error('Network Error'));
  render(<App />);

  expect(await screen.findByRole('alert')).toHaveTextContent(/can't reach the prediction server/i);
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

  api.predictWeek.mockResolvedValueOnce(response([prediction(PLAYERS[1], 17.0), prediction(PLAYERS[0], 16.8)]));
  await user.click(predictButton());
  expect(await screen.findByRole('heading', { name: 'Close call: Bijan Robinson or Derrick Henry' }))
    .toBeInTheDocument();
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
