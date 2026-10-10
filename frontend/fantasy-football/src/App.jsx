import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Plus, X } from 'lucide-react';
import './index.css';

import { Button } from './components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './components/ui/select';
import { PlayerCombobox } from './components/ui/player-combobox';
import { Tabs, TabsList, TabsTrigger } from './components/ui/tabs';
import { RangeField } from './components/range-field';
import { PlayerCutout, PlayerPhoto } from './components/player-photo';

import {
  errorMessage,
  getSeasons,
  getWeeks,
  isCancel,
  predictWeek,
} from './lib/api';
import { buildRequest, isStale, requestKey } from './lib/predictionState';
import { cn } from './lib/utils';

const POSITIONS = [
  { value: 'qb', short: 'QB', label: 'Quarterbacks' },
  { value: 'rb', short: 'RB', label: 'Running backs' },
  { value: 'wr', short: 'WR', label: 'Wide receivers' },
];

// Points between the top two projections below which the call is too close to rank
const CLOSE_CALL_POINTS = 1.5;

const timeFormat = new Intl.DateTimeFormat(undefined, {
  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
});
const dateFormat = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

const formatTime = (iso) => (iso ? timeFormat.format(new Date(iso)) : null);
const formatDate = (iso) => (iso ? dateFormat.format(new Date(iso)) : null);

// Saved predictions older than this get a "may be out of date" note
const STALE_EXPORT_DAYS = 7;
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * What the saved data covers and how fresh it is, for the intro screen.
 * `now` is injectable for tests.
 */
export function dataSummary(data, now = Date.now()) {
  if (!data?.seasons.length) return null;
  const first = data.seasons[data.seasons.length - 1];
  const last = data.seasons[0];
  const lines = [
    `Saved predictions for the ${first === last ? first : `${first}-${last}`} `
      + `season${first === last ? '' : 's'}, exported ${formatTime(data.exportedAt)}.`,
  ];
  if (data.statsThrough) {
    lines.push(`Stats through ${data.statsThrough.season} week ${data.statsThrough.week}.`);
  }
  const current = data.currentWeek;
  if (current && !data.currentWeekSaved) {
    lines.push(`Week ${current.week} of ${current.season} hasn't been exported yet.`);
  }
  const ageDays = Math.floor((now - new Date(data.exportedAt).getTime()) / DAY_MS);
  let warning = null;
  if (data.weekRolledOver && data.exportedWeek) {
    // The NFL week moved on since the export: projections and injuries predate it
    warning = `These predictions were saved during week ${data.exportedWeek.week}, which has finished, `
      + 'so projections and injury news may be out of date.';
  } else if (ageDays >= STALE_EXPORT_DAYS) {
    warning = `These predictions were saved ${ageDays} days ago and may be out of date.`;
  }
  return { text: lines.join(' '), warning };
}

/**
 * The decision the comparison supports, in one line, and the players it
 * names (pictured above the headline).
 */
function verdict(predictions) {
  const [first, second] = predictions;
  if (!first) return null;
  if (!second) {
    return {
      title: `${first.playerName} projects ${first.predictedPoints.toFixed(1)} points`,
      detail: 'Add another player to compare.',
      featured: [first],
    };
  }
  const gap = first.predictedPoints - second.predictedPoints;
  if (gap < CLOSE_CALL_POINTS) {
    return {
      title: `Close call: ${first.playerName} or ${second.playerName}`,
      detail: `Only ${gap.toFixed(1)} points apart, and their ranges overlap.`,
      featured: [first, second],
    };
  }
  return {
    title: `Start ${first.playerName}`,
    detail: `Projects ${gap.toFixed(1)} more points than ${second.playerName}.`,
    featured: [first],
  };
}

function Freshness({ result }) {
  const { freshness, request, currentWeek } = result;
  if (!freshness) return null;
  const lines = [];
  const projections = formatTime(freshness.projections_synced_at);
  lines.push(projections
    ? `Projections for week ${request.week} updated ${projections}.`
    : `No Sleeper projections synced for week ${request.week}; these use the model estimate.`);
  if (freshness.stats_through) {
    lines.push(`Stats through ${freshness.stats_through.season} week ${freshness.stats_through.week}.`);
  }
  const saved = formatTime(result.exportedAt);
  if (saved) lines.push(`Predictions saved ${saved}.`);
  const players = formatDate(freshness.players_synced_at);
  if (players) lines.push(`Player and injury info from ${players}.`);
  const isCurrent = currentWeek
    && currentWeek.season === request.season && currentWeek.week === request.week;
  if (currentWeek && !isCurrent) {
    lines.push(`Injury status is shown only for the current week (${currentWeek.season} week ${currentWeek.week}).`);
  }
  return (
    <p className="mt-8 max-w-prose text-pretty text-sm leading-relaxed text-chalk-muted">
      {lines.join(' ')} All points are PPR.
    </p>
  );
}

let nextSlotKey = 0;
const newSlot = () => ({ key: nextSlotKey++, player: null });

const App = () => {
  const [position, setPosition] = useState('rb');
  // Each slot holds a full player object so its label never depends on search results
  const [slots, setSlots] = useState(() => [newSlot()]);
  const [seasons, setSeasons] = useState([]);
  const [season, setSeason] = useState(null);
  const [availableWeeks, setAvailableWeeks] = useState([]);
  const [week, setWeek] = useState(null);
  // A result remembers the request that produced it: {request, predictions, unavailable, ...}
  const [result, setResult] = useState(null);
  const [isLoadingPredictions, setIsLoadingPredictions] = useState(false);
  const [error, setError] = useState(null);
  const [setupError, setSetupError] = useState(null);
  // What the saved predictions cover and when they were exported
  const [dataInfo, setDataInfo] = useState(null);
  const inFlight = useRef(null); // {controller, key} of the pending prediction request

  // Load the saved seasons on mount; the default season comes from the data
  useEffect(() => {
    getSeasons()
      .then((data) => {
        setDataInfo(data);
        setSeasons(data.seasons);
        setSeason(data.default);
        if (!data.seasons.length) setSetupError('No predictions have been saved yet.');
      })
      .catch((err) => setSetupError(errorMessage(err, "Couldn't load the saved predictions. Try reloading.")));
  }, []);

  // Load weeks for the season; default to the latest week with data
  useEffect(() => {
    if (season == null) return undefined;
    const controller = new AbortController();

    getWeeks(season, controller.signal)
      .then((weeks) => {
        setAvailableWeeks(weeks);
        setWeek((current) =>
          weeks.some((w) => w.week === current) ? current : weeks[weeks.length - 1]?.week ?? null
        );
        setSetupError(weeks.length ? null : `No saved predictions for the ${season} season.`);
      })
      .catch((err) => {
        if (!isCancel(err)) setSetupError(errorMessage(err, `Couldn't load the saved weeks for ${season}. Try reloading.`));
      });

    return () => controller.abort();
  }, [season]);

  const players = slots.map((slot) => slot.player);
  const currentRequest = useMemo(
    () => buildRequest({ season, week, position, players }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [season, week, position, slots]
  );
  const currentKey = requestKey(currentRequest);
  const stale = isStale(result, currentRequest);

  // Inputs changed while a prediction was pending: its answer would be for old inputs
  useEffect(() => {
    if (inFlight.current && inFlight.current.key !== currentKey) {
      inFlight.current.controller.abort();
      inFlight.current = null;
      setIsLoadingPredictions(false);
    }
  }, [currentKey]);

  const handlePositionChange = (value) => {
    setPosition(value);
    setSlots([newSlot()]);
    setResult(null);
    setError(null);
  };

  const handlePlayerChange = (key, player) => {
    setSlots((current) => current.map((slot) => (slot.key === key ? { ...slot, player } : slot)));
  };

  const addPlayer = () => setSlots((current) => [...current, newSlot()]);

  const removePlayer = (key) => setSlots((current) => current.filter((slot) => slot.key !== key));

  const getPredictions = async () => {
    const request = currentRequest;
    if (request.playerIds.length === 0) {
      setError('Pick at least one player to compare.');
      return;
    }

    inFlight.current?.controller.abort();
    const controller = new AbortController();
    inFlight.current = { controller, key: requestKey(request) };
    setIsLoadingPredictions(true);
    setError(null);

    try {
      const data = await predictWeek(request, controller.signal);
      setResult({
        request,
        predictions: data.predictions.map((p) => ({
          playerId: p.player_id,
          playerName: p.player_name,
          predictedPoints: p.predicted_points,
          confidenceLow: p.confidence_low,
          confidenceHigh: p.confidence_high,
          features: p.features,
          context: p.context,
        })),
        // Players the backend couldn't predict, each with a human-readable reason
        unavailable: data.unavailable || [],
        freshness: data.freshness,
        currentWeek: data.current_week,
        injuryStatusCurrent: data.injury_status_current,
        exportedAt: dataInfo?.exportedAt,
      });
    } catch (err) {
      if (isCancel(err)) return;
      console.error('Error loading predictions:', err);
      setError(errorMessage(err, `Couldn't load the saved predictions for week ${request.week}. Try again.`));
    } finally {
      if (inFlight.current?.controller === controller) {
        inFlight.current = null;
        setIsLoadingPredictions(false);
      }
    }
  };

  const predictions = result?.predictions ?? [];
  const unavailable = result?.unavailable ?? [];
  const resultWeek = result?.request.week;
  const selectedCount = currentRequest.playerIds.length;
  const selectedIds = players.filter(Boolean).map((p) => p.player_id);
  const ready = season != null && week != null;
  const call = verdict(predictions);
  // Statuses are from the export: shown only for the current week, while it still is
  const showInjuries = Boolean(
    result?.injuryStatusCurrent
    && result.currentWeek
    && result.currentWeek.season === result.request.season
    && result.currentWeek.week === result.request.week
  );
  const summary = dataSummary(dataInfo);

  return (
    <div className="min-h-screen bg-turf text-chalk">
      {/* One control bar: everything that scopes the comparison */}
      <header className="border-b border-yardline">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-3 px-4 py-4">
          <h1 className="font-condensed text-3xl font-bold leading-none tracking-tight">Start/Sit</h1>

          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={season != null ? season.toString() : undefined}
              onValueChange={(v) => setSeason(parseInt(v, 10))}
              disabled={!seasons.length}
            >
              <SelectTrigger aria-label="Season" className="h-9 w-34 border-yardline bg-sideline text-chalk">
                <SelectValue placeholder="Season" />
              </SelectTrigger>
              <SelectContent>
                {seasons.map((s) => (
                  <SelectItem key={s} value={s.toString()}>{s} season</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={week != null ? week.toString() : undefined}
              onValueChange={(v) => setWeek(parseInt(v, 10))}
              disabled={!availableWeeks.length}
            >
              <SelectTrigger aria-label="Week" className="h-9 w-28 border-yardline bg-sideline text-chalk">
                <SelectValue placeholder="Week" />
              </SelectTrigger>
              <SelectContent>
                {availableWeeks.map((w) => (
                  <SelectItem key={w.week} value={w.week.toString()}>Week {w.week}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Tabs value={position} onValueChange={handlePositionChange}>
              <TabsList aria-label="Position" className="h-9 border border-yardline bg-sideline p-0.5">
                {POSITIONS.map((p) => (
                  <TabsTrigger
                    key={p.value}
                    value={p.value}
                    aria-label={p.label}
                    title={p.label}
                    className="h-full rounded-sm px-3 font-condensed text-base font-semibold text-chalk-secondary data-[state=active]:bg-chalk data-[state=active]:text-turf"
                  >
                    {p.short}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-10 px-4 py-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
        {/* Players: first on mobile, right-hand column on desktop */}
        <aside aria-labelledby="players-title" className="lg:col-start-2 lg:row-start-1">
          <div className="rounded-lg bg-sideline p-4">
            <h2 id="players-title" className="mb-3 font-condensed text-xl font-semibold">Your players</h2>

            <div className="space-y-2">
              {slots.map((slot) => (
                <div key={slot.key} className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <PlayerCombobox
                      position={position}
                      season={season}
                      week={week}
                      value={slot.player}
                      excludeIds={selectedIds}
                      onValueChange={(player) => handlePlayerChange(slot.key, player)}
                      placeholder="Search for a player..."
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => removePlayer(slot.key)}
                    className="shrink-0 text-chalk-secondary hover:bg-turf hover:text-chalk"
                    aria-label={slot.player ? `Remove ${slot.player.name}` : 'Remove player slot'}
                  >
                    <X className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
              ))}
            </div>

            <Button
              onClick={addPlayer}
              variant="ghost"
              className="mt-2 w-full justify-start gap-2 text-chalk hover:bg-turf hover:text-chalk"
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add player
            </Button>

            <Button
              onClick={getPredictions}
              className="mt-4 h-11 w-full bg-pylon font-condensed text-lg font-semibold text-pylon-ink hover:bg-pylon/90"
              disabled={!ready || isLoadingPredictions || selectedCount === 0}
            >
              {isLoadingPredictions ? `Comparing week ${week}...` : `Compare week ${week ?? ''}`}
            </Button>

            {error && (
              <p role="alert" className="mt-3 text-sm text-chalk">
                <span className="mr-1 inline-block h-2 w-2 rounded-full bg-out" aria-hidden="true" />
                {error}
              </p>
            )}
          </div>
        </aside>

        {/* Results: the main focus */}
        <section aria-labelledby="results-title" className="min-w-0 lg:col-start-1 lg:row-start-1">
          {setupError && (
            <p role="alert" className="mb-6 rounded-md border border-out/60 px-4 py-3 text-sm text-chalk">
              {setupError}
            </p>
          )}
          {summary?.warning && (
            <p role="status" className="mb-6 rounded-md border border-flag/60 px-4 py-3 text-sm text-chalk">
              {summary.warning}
            </p>
          )}

          {stale && !isLoadingPredictions && (
            <div
              role="status"
              className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-md border border-flag/70 px-4 py-3 text-sm text-chalk"
            >
              <span>These results are for your previous selection (Week {resultWeek}).</span>
              {ready && selectedCount > 0 && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={getPredictions}
                  className="border-chalk/40 bg-transparent text-chalk hover:bg-sideline hover:text-chalk"
                >
                  Update for Week {week}
                </Button>
              )}
            </div>
          )}

          {result ? (
            <div aria-busy={isLoadingPredictions} className={isLoadingPredictions || stale ? 'opacity-60' : undefined}>
              <p className="font-condensed text-lg text-chalk-secondary">
                Week {resultWeek}, {result.request.season}
              </p>
              {/* The named players stand on a yard line; a close call shows both, same size */}
              {call && (
                <div className="mt-1 flex w-fit items-end border-b border-yardline">
                  {call.featured.map((p, i) => (
                    <PlayerCutout
                      key={p.playerId}
                      playerId={p.playerId}
                      className={cn('h-24 sm:h-32', i > 0 && '-ml-6 sm:-ml-8')}
                    />
                  ))}
                </div>
              )}
              <h2 id="results-title" className="mb-1 mt-3 font-condensed text-verdict font-bold leading-tight text-balance">
                {call ? call.title : 'No players could be projected'}
              </h2>
              {call && <p className="mb-8 text-pretty text-chalk-secondary">{call.detail}</p>}

              {predictions.length > 0 && (
                <RangeField
                  predictions={predictions}
                  showInjuries={showInjuries}
                  animationKey={requestKey(result.request)}
                />
              )}

              {unavailable.length > 0 && (
                <div className="mt-8">
                  <h3 className="mb-2 font-condensed text-xl font-semibold">Not projected</h3>
                  <ul className="divide-y divide-yardline border-y border-yardline">
                    {unavailable.map((player) => (
                      <li key={player.player_id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
                        <span className="flex items-center gap-2 text-chalk">
                          <PlayerPhoto playerId={player.player_id} name={player.player_name} size="sm" muted />
                          {player.player_name || player.player_id}
                        </span>
                        <span className="text-sm text-chalk-secondary">
                          {player.reason === 'bye' ? 'Bye week' : player.message}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <Freshness result={result} />
            </div>
          ) : (
            <div className="max-w-md">
              <h2 id="results-title" className="mb-2 font-condensed text-4xl font-bold leading-tight text-balance">
                {isLoadingPredictions ? `Comparing week ${week}...` : 'Who should you start?'}
              </h2>
              <p className="text-pretty text-chalk-secondary">
                Pick the players you're deciding between, then compare them. You'll see each
                one's projected PPR points and the range they usually land in.
              </p>
              {summary && (
                <p className="mt-4 text-pretty text-sm text-chalk-muted">{summary.text}</p>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

export default App;
