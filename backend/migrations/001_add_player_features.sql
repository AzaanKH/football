-- Migration: Add player_features table
-- Run this on existing databases to add Phase 2 feature engineering support

-- Player computed features table
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

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_player_features_lookup ON player_features(player_id, season, week);
CREATE INDEX IF NOT EXISTS idx_player_features_season ON player_features(season, week);

-- Grant permissions
GRANT ALL PRIVILEGES ON player_features TO postgres;
