import React, { useState, useEffect, useMemo, useRef } from 'react';
import './index.css';

// shadcn components
import { Button } from './components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './components/ui/select';
import { PlayerCombobox } from './components/ui/player-combobox';
import { Badge } from './components/ui/badge';
import { Tabs, TabsList, TabsTrigger } from './components/ui/tabs';
import { Skeleton } from './components/ui/skeleton';
import { Progress } from './components/ui/progress';
import { Separator } from './components/ui/separator';

import {
  errorMessage,
  getModelStatus,
  getSeasons,
  getWeeks,
  isCancel,
  predictWeek,
} from './lib/api';
import { buildRequest, isStale, requestKey } from './lib/predictionState';

// Icons
const FootballIcon = () => (
  <svg className="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <ellipse cx="12" cy="12" rx="9" ry="5" transform="rotate(45 12 12)" />
    <path d="M12 2v20M2 12h20" transform="rotate(45 12 12)" />
  </svg>
);

const UserIcon = () => (
  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
);

const TrophyIcon = () => (
  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
    <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
    <path d="M4 22h16" />
    <path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" />
    <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" />
    <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
  </svg>
);

const PlusIcon = () => (
  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 5v14M5 12h14" />
  </svg>
);

const TrashIcon = () => (
  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
  </svg>
);

const SparklesIcon = () => (
  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 3l1.912 5.813a2 2 0 001.275 1.275L21 12l-5.813 1.912a2 2 0 00-1.275 1.275L12 21l-1.912-5.813a2 2 0 00-1.275-1.275L3 12l5.813-1.912a2 2 0 001.275-1.275L12 3z" />
  </svg>
);

const ChartIcon = () => (
  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M3 3v18h18" />
    <path d="M18 17V9M13 17V5M8 17v-3" />
  </svg>
);

const CalendarIcon = () => (
  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
    <line x1="16" y1="2" x2="16" y2="6" />
    <line x1="8" y1="2" x2="8" y2="6" />
    <line x1="3" y1="10" x2="21" y2="10" />
  </svg>
);

const TrendUpIcon = () => (
  <svg className="w-4 h-4 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
    <polyline points="17 6 23 6 23 12" />
  </svg>
);

const TrendDownIcon = () => (
  <svg className="w-4 h-4 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="23 18 13.5 8.5 8.5 13.5 1 6" />
    <polyline points="17 18 23 18 23 12" />
  </svg>
);

const positionInfo = {
  qb: { label: 'Quarterback', color: 'bg-red-500', emoji: '🏈' },
  rb: { label: 'Running Back', color: 'bg-blue-500', emoji: '🏃' },
  wr: { label: 'Wide Receiver', color: 'bg-green-500', emoji: '🎯' },
};


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
  // A result remembers the request that produced it: {request, predictions, unavailable}
  const [result, setResult] = useState(null);
  const [isLoadingPredictions, setIsLoadingPredictions] = useState(false);
  const [error, setError] = useState(null);
  const [setupError, setSetupError] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const inFlight = useRef(null); // {controller, key} of the pending prediction request

  // Check system status and load seasons on mount; the default season comes from the data
  useEffect(() => {
    getModelStatus()
      .then(setSystemStatus)
      .catch((err) => console.error('Error checking status:', err));

    getSeasons()
      .then((data) => {
        setSeasons(data.seasons);
        setSeason(data.default);
      })
      .catch(() => setSetupError('Could not reach the backend. Make sure it is running.'));
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
        setSetupError(weeks.length ? null : `No prediction data for the ${season} season yet.`);
      })
      .catch((err) => {
        if (!isCancel(err)) setSetupError('Failed to load weeks for this season.');
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
      setError('Please select at least one player.');
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
        })),
        // Players the backend couldn't predict, each with a human-readable reason
        unavailable: data.unavailable || [],
      });
    } catch (err) {
      if (isCancel(err)) return;
      console.error('Error fetching predictions:', err);
      setError(errorMessage(err, 'Failed to get predictions.'));
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
  const maxPoints = predictions.length
    ? Math.max(...predictions.map((p) => p.predictedPoints)) * 1.1
    : 30;
  const selectedCount = currentRequest.playerIds.length;
  const selectedIds = players.filter(Boolean).map((p) => p.player_id);
  const ready = season != null && week != null;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-primary/20 rounded-lg text-primary animate-float">
                <FootballIcon />
              </div>
              <div>
                <h1 className="text-xl font-bold text-white">Fantasy Football Predictor</h1>
                <p className="text-sm text-slate-400">
                  {ready ? `${season} · Week ${week} Predictions` : 'Loading...'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {systemStatus?.weekly_predictor_available ? (
                <Badge variant="outline" className="text-primary border-primary">
                  <SparklesIcon />
                  <span className="ml-1">Model Ready</span>
                </Badge>
              ) : (
                <Badge variant="outline" className="text-yellow-500 border-yellow-500">
                  Model Unavailable
                </Badge>
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        {setupError && (
          <div role="alert" className="mb-6 p-3 rounded-lg bg-destructive/20 border border-destructive/50 text-destructive text-sm">
            {setupError}
          </div>
        )}

        {/* Season / Week Selection */}
        <Card className="mb-6 bg-slate-800/50 border-slate-700 backdrop-blur-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-white flex items-center gap-2">
              <CalendarIcon />
              Prediction Week
            </CardTitle>
            <CardDescription className="text-slate-400">
              Select the NFL week you want predictions for
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center gap-4">
              <Select
                value={week != null ? week.toString() : undefined}
                onValueChange={(v) => setWeek(parseInt(v, 10))}
                disabled={!availableWeeks.length}
              >
                <SelectTrigger aria-label="Week" className="w-48 bg-slate-700/50 border-slate-600 text-white">
                  <SelectValue placeholder="Select week" />
                </SelectTrigger>
                <SelectContent className="bg-slate-800 border-slate-700">
                  {availableWeeks.map((w) => (
                    <SelectItem
                      key={w.week}
                      value={w.week.toString()}
                      className="text-white hover:bg-slate-700"
                    >
                      Week {w.week} {w.players > 0 ? `(${w.players} players)` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={season != null ? season.toString() : undefined}
                onValueChange={(v) => setSeason(parseInt(v, 10))}
                disabled={!seasons.length}
              >
                <SelectTrigger aria-label="Season" className="w-36 bg-slate-700/50 border-slate-600 text-white">
                  <SelectValue placeholder="Season" />
                </SelectTrigger>
                <SelectContent className="bg-slate-800 border-slate-700">
                  {seasons.map((s) => (
                    <SelectItem key={s} value={s.toString()} className="text-white hover:bg-slate-700">
                      Season {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Position Selection */}
        <Card className="mb-6 bg-slate-800/50 border-slate-700 backdrop-blur-sm">
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2">
              <UserIcon />
              Select Position
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs value={position} onValueChange={handlePositionChange} className="w-full">
              <TabsList className="grid w-full grid-cols-3 bg-slate-700/50">
                {Object.entries(positionInfo).map(([key, info]) => (
                  <TabsTrigger
                    key={key}
                    value={key}
                    className="data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
                  >
                    <span className="mr-2">{info.emoji}</span>
                    {info.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </CardContent>
        </Card>

        <div className="grid lg:grid-cols-2 gap-6">
          {/* Player Selection */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm">
            <CardHeader>
              <CardTitle className="text-white flex items-center gap-2">
                <ChartIcon />
                Player Selection
                <Badge className="ml-auto" variant="secondary">
                  {selectedCount} selected
                </Badge>
              </CardTitle>
              <CardDescription className="text-slate-400">
                {ready ? `Compare players for your Week ${week} lineup` : 'Loading weeks...'}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {error && (
                <div role="alert" className="p-3 rounded-lg bg-destructive/20 border border-destructive/50 text-destructive text-sm animate-bounce-in">
                  {error}
                </div>
              )}

              {slots.map((slot, index) => (
                <div
                  key={slot.key}
                  className="flex gap-2 items-center animate-slide-up"
                  style={{ animationDelay: `${index * 50}ms` }}
                >
                  <div className="flex-1">
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
                    variant="destructive"
                    size="icon"
                    onClick={() => removePlayer(slot.key)}
                    className="shrink-0"
                    aria-label={slot.player ? `Remove ${slot.player.name}` : 'Remove player slot'}
                  >
                    <TrashIcon />
                  </Button>
                </div>
              ))}

              <Button
                onClick={addPlayer}
                variant="outline"
                className="w-full border-dashed border-slate-600 text-slate-300 hover:bg-slate-700 hover:text-white"
              >
                <PlusIcon />
                <span className="ml-2">Add Player</span>
              </Button>

              <Separator className="bg-slate-700" />

              <Button
                onClick={getPredictions}
                className="w-full bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-6"
                disabled={!ready || isLoadingPredictions || selectedCount === 0}
              >
                {isLoadingPredictions ? (
                  <div className="flex items-center gap-2">
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Analyzing Week {week}...
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <SparklesIcon />
                    Predict Week {week ?? ''}
                  </div>
                )}
              </Button>
            </CardContent>
          </Card>

          {/* Predictions Results: labeled with the request that produced them */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm">
            <CardHeader>
              <CardTitle className="text-white flex items-center gap-2">
                <TrophyIcon />
                {result ? `Week ${resultWeek} Predictions` : 'Predictions'}
              </CardTitle>
              <CardDescription className="text-slate-400">
                {result
                  ? `${result.request.season} season · PPR scoring`
                  : 'Projected fantasy points for upcoming game'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {stale && !isLoadingPredictions && (
                <div
                  role="status"
                  className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-md border border-yellow-500/50 bg-yellow-500/10 px-3 py-2 text-sm text-yellow-200"
                >
                  <span>These results are for your previous selection (Week {resultWeek}).</span>
                  {ready && selectedCount > 0 && (
                    <Button size="sm" variant="outline" onClick={getPredictions}>
                      Update for Week {week}
                    </Button>
                  )}
                </div>
              )}

              {isLoadingPredictions ? (
                <div className="space-y-4">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="space-y-2">
                      <Skeleton className="h-4 w-3/4 bg-slate-700" />
                      <Skeleton className="h-8 w-full bg-slate-700" />
                    </div>
                  ))}
                </div>
              ) : result ? (
                <div className={`space-y-4 ${stale ? 'opacity-60' : ''}`}>
                  {predictions.map((player, index) => (
                    <div
                      key={player.playerId}
                      className="animate-bounce-in"
                      style={{ animationDelay: `${index * 100}ms` }}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-3">
                          <div
                            className={`w-8 h-8 rounded-full flex items-center justify-center text-white font-bold text-sm ${
                              index === 0
                                ? 'bg-yellow-500 animate-glow'
                                : index === 1
                                ? 'bg-slate-400'
                                : index === 2
                                ? 'bg-amber-700'
                                : 'bg-slate-600'
                            }`}
                          >
                            {index + 1}
                          </div>
                          <div>
                            <span className="text-white font-medium">{player.playerName}</span>
                            {player.features?.trend === 'improving' && (
                              <span className="ml-2" title="Trending up"><TrendUpIcon /></span>
                            )}
                            {player.features?.trend === 'declining' && (
                              <span className="ml-2" title="Trending down"><TrendDownIcon /></span>
                            )}
                          </div>
                        </div>
                        <Badge
                          className={`${
                            index === 0
                              ? 'bg-yellow-500/20 text-yellow-500 border-yellow-500/50'
                              : 'bg-primary/20 text-primary border-primary/50'
                          }`}
                          variant="outline"
                        >
                          {player.predictedPoints.toFixed(1)} pts
                        </Badge>
                      </div>

                      <Progress
                        value={player.predictedPoints}
                        max={maxPoints}
                        className={`h-2 ${index === 0 ? 'bg-yellow-500/20' : 'bg-slate-700'}`}
                      />

                      <div className="flex items-center justify-between mt-1">
                        <p className="text-xs text-slate-500">
                          Range: {player.confidenceLow.toFixed(1)} - {player.confidenceHigh.toFixed(1)} pts
                        </p>
                        {player.features?.avg_3_games != null && (
                          <p className="text-xs text-slate-500">
                            3-game avg: {Number(player.features.avg_3_games).toFixed(1)}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}

                  {unavailable.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                        No prediction
                      </p>
                      {unavailable.map((player) => (
                        <div
                          key={player.player_id}
                          className="flex items-start justify-between gap-3 rounded-md border border-slate-700 px-3 py-2"
                        >
                          <span className="text-slate-300">{player.player_name || player.player_id}</span>
                          <span className="text-right text-xs text-slate-500">{player.message}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {predictions.length > 0 && (
                    <>
                      <Separator className="bg-slate-700 my-4" />
                      <p className="text-center text-sm text-slate-400">
                        <span className="text-primary font-semibold">{predictions[0].playerName}</span>
                        {' '}is projected to score the most in Week {resultWeek}!
                      </p>
                    </>
                  )}
                </div>
              ) : (
                <div className="text-center py-12">
                  <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-slate-700/50 flex items-center justify-center text-slate-500">
                    <ChartIcon />
                  </div>
                  <p className="text-slate-400">No predictions yet</p>
                  <p className="text-sm text-slate-500 mt-1">
                    Select players and click "Predict Week {week ?? ''}" to see results
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Footer Info */}
        <Card className="mt-6 bg-slate-800/50 border-slate-700 backdrop-blur-sm">
          <CardContent className="py-4">
            <div className="flex flex-wrap items-center justify-center gap-4 text-sm text-slate-400">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                <span>Weekly Predictor</span>
              </div>
              <Separator orientation="vertical" className="h-4 bg-slate-700" />
              <div className="flex items-center gap-2">
                <span>Reliability + Matchup Features</span>
              </div>
              <Separator orientation="vertical" className="h-4 bg-slate-700" />
              <div className="flex items-center gap-2">
                <span>Rolling Averages + Matchups</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  );
};

export default App;
