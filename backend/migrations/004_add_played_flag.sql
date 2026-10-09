-- Migration: flag weekly stat rows where the player actually had a fantasy opportunity
--
-- Sleeper returns a stats row for every rostered player each week, including
-- weeks they were inactive, injured, or never touched the ball. Those rows have
-- 0 points AND 0 opportunities; treating them as games drags rolling averages
-- toward zero and teaches the model to predict "did the player play?" instead of
-- "how many points will they score?".
--
-- played = at least one pass attempt, rush attempt, target, or reception,
-- or any fantasy points (kickers, return/fumble-recovery TDs, 2-pt plays).
-- Generated, so every writer and reader shares one definition.

ALTER TABLE player_weekly_stats
    ADD COLUMN IF NOT EXISTS played BOOLEAN GENERATED ALWAYS AS (
        COALESCE(passing_attempts, 0) + COALESCE(rushing_attempts, 0)
        + COALESCE(targets, 0) + COALESCE(receptions, 0) > 0
        OR COALESCE(fantasy_points_ppr, 0) <> 0
    ) STORED;

-- Feature queries read a player's recent played games, newest first
CREATE INDEX IF NOT EXISTS idx_stats_player_played
    ON player_weekly_stats(player_id, season DESC, week DESC)
    WHERE played;
