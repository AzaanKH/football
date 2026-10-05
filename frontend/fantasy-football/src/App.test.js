import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import * as api from './lib/api';

jest.mock('./lib/api', () => ({
  getModelStatus: jest.fn(),
  getSeasons: jest.fn(),
  getWeeks: jest.fn(),
  searchPlayers: jest.fn(),
  predictWeek: jest.fn(),
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
  features: { avg_3_games: points, trend: 'improving' },
});

beforeEach(() => {
  jest.clearAllMocks();
  api.getModelStatus.mockResolvedValue({ weekly_predictor_available: true });
  api.getSeasons.mockResolvedValue({ seasons: [2025, 2024], default: 2025 });
  api.getWeeks.mockResolvedValue([{ week: 6, players: 500 }, { week: 7, players: 510 }]);
  api.searchPlayers.mockImplementation(async ({ search }) =>
    PLAYERS.filter((p) => !search || p.name.toLowerCase().includes(search.toLowerCase()))
  );
});

async function renderReady() {
  render(<App />);
  await screen.findByText('2025 · Week 7 Predictions');
}

async function selectPlayer(name) {
  // Pick into the first empty slot, like a user would
  const [emptySlot] = await screen.findAllByRole('combobox', { name: /search for a player/i });
  userEvent.click(emptySlot);
  userEvent.click(await screen.findByRole('option', { name: new RegExp(name, 'i') }));
  await waitFor(() => expect(screen.queryByRole('option')).not.toBeInTheDocument());
  // Radix returns focus to the trigger on close; in jsdom that lands a tick later,
  // and opening another popover before it does would immediately dismiss it.
  const trigger = await screen.findByRole('combobox', { name: new RegExp(`player: ${name}`, 'i') });
  await waitFor(() => expect(trigger).toHaveFocus());
}

const predictButton = () => screen.getByRole('button', { name: /predict week/i });

test('uses the season and latest week from the backend', async () => {
  await renderReady();

  expect(api.getWeeks).toHaveBeenCalledWith(2025, expect.anything());
});

test('player search runs on the server for the selected week', async () => {
  await renderReady();

  userEvent.click(screen.getByRole('combobox', { name: /search for a player/i }));
  userEvent.type(await screen.findByPlaceholderText(/search by name or team/i), 'bij');

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
  api.predictWeek.mockResolvedValue({ predictions: [prediction(PLAYERS[0], 19.6)], unavailable: [] });
  await renderReady();

  await selectPlayer('Derrick Henry');
  userEvent.click(predictButton());

  expect(await screen.findByText('Week 7 Predictions')).toBeInTheDocument();
  expect(api.predictWeek).toHaveBeenCalledWith(
    { season: 2025, week: 7, position: 'rb', playerIds: ['3198'] },
    expect.anything()
  );
  expect(screen.queryByText(/previous selection/i)).not.toBeInTheDocument();

  userEvent.click(screen.getByRole('button', { name: /add player/i }));
  await selectPlayer('Bijan Robinson');

  const banner = await screen.findByRole('status');
  expect(banner).toHaveTextContent('These results are for your previous selection (Week 7).');
  expect(screen.getByText('19.6 pts')).toBeInTheDocument(); // old result still visible, clearly labeled
});

test('changing inputs cancels a pending prediction and ignores its answer', async () => {
  let pendingSignal;
  api.predictWeek.mockImplementation((request, signal) => {
    pendingSignal = signal;
    return new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject({ name: 'CanceledError' }));
    });
  });
  await renderReady();

  await selectPlayer('Derrick Henry');
  userEvent.click(predictButton());
  await screen.findByText(/analyzing week 7/i);

  userEvent.click(screen.getByRole('button', { name: /add player/i }));
  await selectPlayer('Bijan Robinson');

  await waitFor(() => expect(pendingSignal.aborted).toBe(true));
  expect(screen.queryByText(/analyzing week/i)).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument(); // a cancel is not an error
  expect(screen.getByText('No predictions yet')).toBeInTheDocument();
});

test('shows unavailable players with their reason', async () => {
  api.predictWeek.mockResolvedValue({
    predictions: [prediction(PLAYERS[0], 19.6)],
    unavailable: [{ player_id: '9509', player_name: 'Bijan Robinson', reason: 'no_history',
                    message: 'No games played before this week.' }],
  });
  await renderReady();

  await selectPlayer('Derrick Henry');
  userEvent.click(predictButton());

  const noPrediction = (await screen.findByText('No prediction')).closest('div');
  expect(within(noPrediction).getByText('Bijan Robinson')).toBeInTheDocument();
  expect(within(noPrediction).getByText('No games played before this week.')).toBeInTheDocument();
});

test('shows the API error message when prediction fails', async () => {
  api.predictWeek.mockRejectedValue({ response: { data: { error: 'Weekly predictor not available' } } });
  await renderReady();

  await selectPlayer('Derrick Henry');
  userEvent.click(predictButton());

  expect(await screen.findByRole('alert')).toHaveTextContent('Weekly predictor not available');
});

test('shows a setup error when the backend is unreachable', async () => {
  api.getSeasons.mockRejectedValue(new Error('Network Error'));
  render(<App />);

  expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach the backend/i);
});
