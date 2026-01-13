import React, { useState, useEffect } from 'react';
import axios from 'axios';
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

const API_BASE = 'http://localhost:5001';

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

const App = () => {
  const [position, setPosition] = useState('rb');
  const [players, setPlayers] = useState([]);
  const [selectedPlayerIds, setSelectedPlayerIds] = useState([]);
  const [predictions, setPredictions] = useState([]);
  const [week, setWeek] = useState(15);
  const [season] = useState(2025);
  const [availableWeeks, setAvailableWeeks] = useState([]);
  const [isLoadingPlayers, setIsLoadingPlayers] = useState(false);
  const [isLoadingPredictions, setIsLoadingPredictions] = useState(false);
  const [error, setError] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [useLegacy, setUseLegacy] = useState(false);

  // Check system status on mount
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const response = await axios.get(`${API_BASE}/model_status`);
        setSystemStatus(response.data);

        // If weekly predictor not available, fall back to legacy
        if (!response.data.weekly_predictor_available) {
          setUseLegacy(true);
        }
      } catch (error) {
        console.error('Error checking status:', error);
        setUseLegacy(true);
      }
    };
    checkStatus();
  }, []);

  // Fetch available weeks
  useEffect(() => {
    const fetchWeeks = async () => {
      try {
        const response = await axios.get(`${API_BASE}/available_weeks?season=${season}`);
        setAvailableWeeks(response.data.weeks || []);
        if (response.data.weeks?.length > 0) {
          setWeek(response.data.weeks[response.data.weeks.length - 1].week);
        }
      } catch (error) {
        console.error('Error fetching weeks:', error);
        // Generate default weeks if API fails
        setAvailableWeeks(Array.from({ length: 17 }, (_, i) => ({ week: i + 1, players: 0 })));
      }
    };
    fetchWeeks();
  }, [season]);

  // Fetch players when position changes
  useEffect(() => {
    const fetchPlayers = async () => {
      setIsLoadingPlayers(true);
      setError(null);
      try {
        // Try new PostgreSQL endpoint first
        let response;
        try {
          response = await axios.get(`${API_BASE}/players?position=${position}&limit=200`);
          setPlayers(response.data.map(p => ({
            player_id: p.player_id,
            PlayerName: p.full_name,
            team: p.team
          })));
        } catch {
          // Fall back to legacy SQLite endpoint
          response = await axios.get(`${API_BASE}/get_players/${position}`);
          setPlayers(response.data);
        }
      } catch (error) {
        console.error('Error fetching players:', error);
        setError('Failed to load players. Make sure the backend is running.');
      } finally {
        setIsLoadingPlayers(false);
      }
    };
    fetchPlayers();
  }, [position]);

  const handlePositionChange = (value) => {
    setPosition(value);
    setSelectedPlayerIds([]);
    setPredictions([]);
  };

  const handlePlayerChange = (index, playerId) => {
    const updated = [...selectedPlayerIds];
    updated[index] = playerId;
    setSelectedPlayerIds(updated);
  };

  const addPlayer = () => {
    setSelectedPlayerIds([...selectedPlayerIds, '']);
  };

  const removePlayer = (index) => {
    setSelectedPlayerIds(selectedPlayerIds.filter((_, i) => i !== index));
  };

  const getPredictions = async () => {
    const validIds = selectedPlayerIds.filter(id => id);
    if (validIds.length === 0) {
      setError('Please select at least one player.');
      return;
    }

    setIsLoadingPredictions(true);
    setError(null);

    try {
      let response;

      if (!useLegacy && systemStatus?.weekly_predictor_available) {
        // Use new weekly prediction endpoint
        response = await axios.post(`${API_BASE}/predict_week`, {
          position,
          player_ids: validIds,
          week,
          season
        });

        setPredictions(response.data.predictions.map(p => ({
          PlayerName: p.player_name,
          PredictedPoints: p.predicted_points,
          ConfidenceLow: p.confidence_low,
          ConfidenceHigh: p.confidence_high,
          features: p.features
        })));
      } else {
        // Fall back to legacy endpoint
        const selectedPlayers = validIds.map(id => {
          const player = players.find(p => p.player_id === id || p.PlayerName === id);
          return player || { PlayerName: id };
        });

        response = await axios.post(`${API_BASE}/predict`, {
          position,
          players: selectedPlayers,
          use_ensemble: false
        });

        setPredictions(response.data);
      }
    } catch (error) {
      console.error('Error fetching predictions:', error);
      setError(error.response?.data?.error || 'Failed to get predictions.');
    } finally {
      setIsLoadingPredictions(false);
    }
  };

  const getMaxPoints = () => {
    if (predictions.length === 0) return 30;
    return Math.max(...predictions.map(p => p.PredictedPoints)) * 1.1;
  };

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
                  {useLegacy ? 'Legacy Mode' : `Week ${week} Predictions`}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {systemStatus?.weekly_predictor_available ? (
                <Badge variant="outline" className="text-primary border-primary">
                  <SparklesIcon />
                  <span className="ml-1">Phase 4 Active</span>
                </Badge>
              ) : (
                <Badge variant="outline" className="text-yellow-500 border-yellow-500">
                  Legacy Mode
                </Badge>
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        {/* Week Selection (only for new system) */}
        {!useLegacy && (
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
              <div className="flex items-center gap-4">
                <Select value={week.toString()} onValueChange={(v) => setWeek(parseInt(v))}>
                  <SelectTrigger className="w-48 bg-slate-700/50 border-slate-600 text-white">
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
                <span className="text-slate-400">Season {season}</span>
              </div>
            </CardContent>
          </Card>
        )}

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
                  {selectedPlayerIds.filter(id => id).length} selected
                </Badge>
              </CardTitle>
              <CardDescription className="text-slate-400">
                Compare players for your Week {week} lineup
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {error && (
                <div className="p-3 rounded-lg bg-destructive/20 border border-destructive/50 text-destructive text-sm animate-bounce-in">
                  {error}
                </div>
              )}

              {isLoadingPlayers ? (
                <div className="space-y-3">
                  {[1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-12 w-full bg-slate-700" />
                  ))}
                </div>
              ) : (
                <>
                  {selectedPlayerIds.map((playerId, index) => (
                    <div
                      key={index}
                      className="flex gap-2 items-center animate-slide-up"
                      style={{ animationDelay: `${index * 50}ms` }}
                    >
                      <div className="flex-1">
                        <PlayerCombobox
                          players={players}
                          value={playerId}
                          onValueChange={(value) => handlePlayerChange(index, value)}
                          placeholder="Search for a player..."
                        />
                      </div>
                      <Button
                        variant="destructive"
                        size="icon"
                        onClick={() => removePlayer(index)}
                        className="shrink-0"
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
                    disabled={isLoadingPredictions || selectedPlayerIds.filter(id => id).length === 0}
                  >
                    {isLoadingPredictions ? (
                      <div className="flex items-center gap-2">
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Analyzing Week {week}...
                      </div>
                    ) : (
                      <div className="flex items-center gap-2">
                        <SparklesIcon />
                        Predict Week {week}
                      </div>
                    )}
                  </Button>
                </>
              )}
            </CardContent>
          </Card>

          {/* Predictions Results */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm">
            <CardHeader>
              <CardTitle className="text-white flex items-center gap-2">
                <TrophyIcon />
                Week {week} Predictions
              </CardTitle>
              <CardDescription className="text-slate-400">
                Projected fantasy points for upcoming game
              </CardDescription>
            </CardHeader>
            <CardContent>
              {isLoadingPredictions ? (
                <div className="space-y-4">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="space-y-2">
                      <Skeleton className="h-4 w-3/4 bg-slate-700" />
                      <Skeleton className="h-8 w-full bg-slate-700" />
                    </div>
                  ))}
                </div>
              ) : predictions.length > 0 ? (
                <div className="space-y-4">
                  {predictions.map((player, index) => (
                    <div
                      key={index}
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
                            <span className="text-white font-medium">{player.PlayerName}</span>
                            {player.features?.trend && (
                              <span className="ml-2">
                                {player.features.trend === 'improving' ? <TrendUpIcon /> : <TrendDownIcon />}
                              </span>
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
                          {player.PredictedPoints.toFixed(1)} pts
                        </Badge>
                      </div>

                      <Progress
                        value={player.PredictedPoints}
                        max={getMaxPoints()}
                        className={`h-2 ${index === 0 ? 'bg-yellow-500/20' : 'bg-slate-700'}`}
                      />

                      {/* Confidence interval */}
                      {player.ConfidenceLow !== undefined && player.ConfidenceHigh !== undefined && (
                        <div className="flex items-center justify-between mt-1">
                          <p className="text-xs text-slate-500">
                            Range: {player.ConfidenceLow.toFixed(1)} - {player.ConfidenceHigh.toFixed(1)} pts
                          </p>
                          {player.features?.avg_3_games != null && !isNaN(Number(player.features.avg_3_games)) && (
                            <p className="text-xs text-slate-500">
                              3-game avg: {Number(player.features.avg_3_games).toFixed(1)}
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  ))}

                  <Separator className="bg-slate-700 my-4" />

                  <div className="text-center">
                    <p className="text-sm text-slate-400">
                      {predictions.length > 0 && (
                        <>
                          <span className="text-primary font-semibold">{predictions[0].PlayerName}</span>
                          {' '}is projected to score the most in Week {week}!
                        </>
                      )}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="text-center py-12">
                  <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-slate-700/50 flex items-center justify-center text-slate-500">
                    <ChartIcon />
                  </div>
                  <p className="text-slate-400">No predictions yet</p>
                  <p className="text-sm text-slate-500 mt-1">
                    Select players and click "Predict Week {week}" to see results
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
                <span>{useLegacy ? 'Legacy XGBoost' : 'Phase 4 Weekly Predictor'}</span>
              </div>
              <Separator orientation="vertical" className="h-4 bg-slate-700" />
              <div className="flex items-center gap-2">
                <span>{useLegacy ? '14 Features' : '22 Predictive Features'}</span>
              </div>
              <Separator orientation="vertical" className="h-4 bg-slate-700" />
              <div className="flex items-center gap-2">
                <span>{useLegacy ? 'Same-Game Data' : 'Rolling Averages + Matchups'}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  );
};

export default App;
