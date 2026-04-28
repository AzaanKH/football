-- Fantasy Football Database Schema
-- This script runs automatically when the Docker container starts

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Players table (from Sleeper API)
CREATE TABLE IF NOT EXISTS players (
    player_id VARCHAR(50) PRIMARY KEY,
    sleeper_id VARCHAR(50),
    espn_id VARCHAR(50),
    full_name VARCHAR(100) NOT NULL,
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    position VARCHAR(10),
    team VARCHAR(5),
    status VARCHAR(100),
    injury_status VARCHAR(100),
    injury_body_part VARCHAR(100),
    years_exp INTEGER,
    age INTEGER,
    height VARCHAR(10),
    weight INTEGER,
    college VARCHAR(100),
    fantasy_positions TEXT[],
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create index on common lookups
CREATE INDEX IF NOT EXISTS idx_players_position ON players(position);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team);
CREATE INDEX IF NOT EXISTS idx_players_name ON players(full_name);

-- Weekly stats table (time-series data)
CREATE TABLE IF NOT EXISTS player_weekly_stats (
    id SERIAL,
    time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    player_id VARCHAR(50) NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,

    -- Fantasy points
    fantasy_points REAL DEFAULT 0,
    fantasy_points_ppr REAL DEFAULT 0,

    -- Passing stats
    passing_attempts INTEGER DEFAULT 0,
    passing_completions INTEGER DEFAULT 0,
    passing_yards REAL DEFAULT 0,
    passing_tds INTEGER DEFAULT 0,
    interceptions INTEGER DEFAULT 0,
    passing_2pt INTEGER DEFAULT 0,

    -- Rushing stats
    rushing_attempts INTEGER DEFAULT 0,
    rushing_yards REAL DEFAULT 0,
    rushing_tds INTEGER DEFAULT 0,
    rushing_2pt INTEGER DEFAULT 0,

    -- Receiving stats
    targets INTEGER DEFAULT 0,
    receptions INTEGER DEFAULT 0,
    receiving_yards REAL DEFAULT 0,
    receiving_tds INTEGER DEFAULT 0,
    receiving_2pt INTEGER DEFAULT 0,

    -- Misc stats
    fumbles INTEGER DEFAULT 0,
    fumbles_lost INTEGER DEFAULT 0,

    -- Metadata
    source VARCHAR(20) DEFAULT 'sleeper',  -- 'sleeper', 'espn', 'scraped', 'manual'
    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_player_week UNIQUE (player_id, season, week)
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('player_weekly_stats', 'time', if_not_exists => TRUE);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_stats_player ON player_weekly_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_stats_season_week ON player_weekly_stats(season, week);
CREATE INDEX IF NOT EXISTS idx_stats_player_season ON player_weekly_stats(player_id, season);

-- Team defense stats table
CREATE TABLE IF NOT EXISTS team_defense_stats (
    id SERIAL PRIMARY KEY,
    team VARCHAR(5) NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,

    -- Points allowed
    points_allowed REAL DEFAULT 0,

    -- Fantasy points allowed by position
    fantasy_points_allowed_qb REAL DEFAULT 0,
    fantasy_points_allowed_rb REAL DEFAULT 0,
    fantasy_points_allowed_wr REAL DEFAULT 0,
    fantasy_points_allowed_te REAL DEFAULT 0,

    -- Yards allowed
    passing_yards_allowed REAL DEFAULT 0,
    rushing_yards_allowed REAL DEFAULT 0,

    -- Rankings (1 = best defense against position, 32 = worst)
    rank_vs_qb INTEGER,
    rank_vs_rb INTEGER,
    rank_vs_wr INTEGER,
    rank_vs_te INTEGER,

    source VARCHAR(20) DEFAULT 'calculated',
    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_team_week UNIQUE (team, season, week)
);

-- Team matchup context for weekly feature generation
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

-- Projections table (for storing external projections)
CREATE TABLE IF NOT EXISTS player_projections (
    id SERIAL PRIMARY KEY,
    player_id VARCHAR(50) NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,

    projected_points REAL,
    projected_points_ppr REAL,

    -- Projected stats
    proj_passing_yards REAL,
    proj_passing_tds REAL,
    proj_rushing_yards REAL,
    proj_rushing_tds REAL,
    proj_receiving_yards REAL,
    proj_receiving_tds REAL,
    proj_receptions REAL,

    source VARCHAR(20) DEFAULT 'sleeper',
    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_projection UNIQUE (player_id, season, week, source)
);

-- Data ingestion log (for tracking pipeline runs)
CREATE TABLE IF NOT EXISTS ingestion_log (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    data_type VARCHAR(50) NOT NULL,  -- 'players', 'stats', 'projections'
    season INTEGER,
    week INTEGER,
    records_processed INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'started',  -- 'started', 'completed', 'failed'
    error_message TEXT,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Helper function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Add trigger to players table
DROP TRIGGER IF EXISTS update_players_updated_at ON players;
CREATE TRIGGER update_players_updated_at
    BEFORE UPDATE ON players
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Player computed features table (Phase 2: Feature Engineering)
CREATE TABLE IF NOT EXISTS player_features (
    id SERIAL PRIMARY KEY,
    player_id VARCHAR(50) NOT NULL REFERENCES players(player_id),
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,

    -- Rolling Averages (9 features)
    fantasy_pts_avg_3 DECIMAL(10,2),
    fantasy_pts_avg_5 DECIMAL(10,2),
    fantasy_pts_avg_10 DECIMAL(10,2),
    rushing_yds_avg_3 DECIMAL(10,2),
    receiving_yds_avg_3 DECIMAL(10,2),
    passing_yds_avg_3 DECIMAL(10,2),
    targets_avg_3 DECIMAL(10,2),
    touches_avg_3 DECIMAL(10,2),
    receptions_avg_3 DECIMAL(10,2),
    games_played_prior INTEGER,
    current_season_games_played INTEGER,
    has_prev_season_data BOOLEAN,
    has_full_window_3 BOOLEAN,
    has_full_window_5 BOOLEAN,
    has_full_window_10 BOOLEAN,
    fantasy_pts_baseline DECIMAL(10,2),

    -- Efficiency Metrics (7 features)
    yards_per_carry DECIMAL(10,2),
    yards_per_target DECIMAL(10,2),
    yards_per_reception DECIMAL(10,2),
    td_per_touch DECIMAL(10,4),
    catch_rate DECIMAL(10,4),
    yards_per_pass_attempt DECIMAL(10,2),
    td_per_pass_attempt DECIMAL(10,4),

    -- Consistency Metrics (4 features)
    fantasy_pts_std_5 DECIMAL(10,2),
    boom_rate_5 DECIMAL(10,4),      -- % games > 20 pts PPR
    bust_rate_5 DECIMAL(10,4),      -- % games < 5 pts PPR
    floor_score DECIMAL(10,2),      -- 10th percentile of recent scores

    -- Trend Features (4 features)
    fantasy_pts_trend_3 DECIMAL(10,4),  -- linear regression slope
    usage_trend_3 DECIMAL(10,4),
    snap_share_trend_3 DECIMAL(10,4),
    target_share_trend_3 DECIMAL(10,4),

    -- Matchup Features (4 features)
    opp_position_rank INTEGER,
    opp_fantasy_pts_allowed DECIMAL(10,2),
    is_home BOOLEAN,
    days_rest INTEGER,

    -- Metadata
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_player_feature UNIQUE (player_id, season, week)
);

-- Create indexes for player_features
CREATE INDEX IF NOT EXISTS idx_player_features_lookup ON player_features(player_id, season, week);
CREATE INDEX IF NOT EXISTS idx_player_features_season ON player_features(season, week);

-- Grant permissions (for development)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;
