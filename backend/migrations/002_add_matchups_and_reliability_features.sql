-- Migration: Add matchup context and early-season reliability features

ALTER TABLE player_features
    ADD COLUMN IF NOT EXISTS games_played_prior INTEGER,
    ADD COLUMN IF NOT EXISTS current_season_games_played INTEGER,
    ADD COLUMN IF NOT EXISTS has_prev_season_data BOOLEAN,
    ADD COLUMN IF NOT EXISTS has_full_window_3 BOOLEAN,
    ADD COLUMN IF NOT EXISTS has_full_window_5 BOOLEAN,
    ADD COLUMN IF NOT EXISTS has_full_window_10 BOOLEAN,
    ADD COLUMN IF NOT EXISTS fantasy_pts_baseline DECIMAL(10,2);

CREATE TABLE IF NOT EXISTS team_weekly_matchups (
    id SERIAL PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    team VARCHAR(5) NOT NULL,
    opponent VARCHAR(5),
    is_home BOOLEAN,
    game_date TIMESTAMPTZ,
    source VARCHAR(20) DEFAULT 'espn',
    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_team_matchup UNIQUE (season, week, team)
);

CREATE INDEX IF NOT EXISTS idx_team_weekly_matchups_lookup
    ON team_weekly_matchups(season, week, team);

GRANT ALL PRIVILEGES ON team_weekly_matchups TO postgres;
