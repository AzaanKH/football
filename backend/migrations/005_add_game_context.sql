-- Migration: per-game context on weekly stats, and snap-share features
--
-- Sleeper's per-game stats (api.sleeper.com) report the team a player was on,
-- the opponent, the game date and offensive snaps. Storing them per game lets
-- features use the opponent actually faced (correct for traded players), real
-- days of rest, snap share, and opponent points allowed by position.

ALTER TABLE player_weekly_stats
    ADD COLUMN IF NOT EXISTS team VARCHAR(5),
    ADD COLUMN IF NOT EXISTS opponent VARCHAR(5),
    ADD COLUMN IF NOT EXISTS game_date DATE,
    ADD COLUMN IF NOT EXISTS off_snaps INTEGER,
    ADD COLUMN IF NOT EXISTS team_off_snaps INTEGER;

-- Opponent-defense aggregation groups played games by opponent and week
CREATE INDEX IF NOT EXISTS idx_stats_opponent_week
    ON player_weekly_stats(opponent, season, week)
    WHERE played;

ALTER TABLE player_features
    ADD COLUMN IF NOT EXISTS snap_share_avg_3 DECIMAL(10,4);
