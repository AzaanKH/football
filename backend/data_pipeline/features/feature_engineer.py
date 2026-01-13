"""
Feature Engineer Orchestrator

Main entry point for computing all features. Coordinates all feature modules
and handles batch processing and database operations.
"""

import logging
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
import time

from .rolling_averages import RollingAverages
from .efficiency import EfficiencyMetrics
from .consistency import ConsistencyMetrics
from .trends import TrendFeatures
from .matchups import MatchupFeatures

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """
    Orchestrates feature computation across all modules.

    Usage:
        with FeatureEngineer(db_connection) as engineer:
            engineer.compute_all_features(season=2024, week=10)
    """

    def __init__(self, connection):
        """
        Initialize with database connection.

        Args:
            connection: psycopg2 database connection
        """
        self.connection = connection
        self.cursor = connection.cursor()

        # Initialize feature modules
        self.rolling_avg = RollingAverages(self.cursor)
        self.efficiency = EfficiencyMetrics(self.cursor)
        self.consistency = ConsistencyMetrics(self.cursor)
        self.trends = TrendFeatures(self.cursor)
        self.matchups = MatchupFeatures(self.cursor)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close cursor."""
        if self.cursor:
            self.cursor.close()

    def compute_player_features(
        self,
        player_id: str,
        season: int,
        week: int,
        matchup_info: Optional[Dict] = None
    ) -> Dict:
        """
        Compute all features for a single player.

        Args:
            player_id: Player's unique ID
            season: Season year
            week: Week to compute features for
            matchup_info: Optional dict with 'opponent' and 'is_home'

        Returns:
            Dictionary containing all 28 features
        """
        features = {
            'player_id': player_id,
            'season': season,
            'week': week,
        }

        # Rolling averages (9 features)
        features.update(self.rolling_avg.compute(player_id, season, week))

        # Efficiency metrics (7 features)
        features.update(self.efficiency.compute(player_id, season, week))

        # Consistency metrics (4 features)
        features.update(self.consistency.compute(player_id, season, week))

        # Trend features (4 features)
        features.update(self.trends.compute(player_id, season, week))

        # Matchup features (4 features)
        matchup_info = matchup_info or {}
        features.update(self.matchups.compute(
            player_id, season, week,
            opponent=matchup_info.get('opponent'),
            is_home=matchup_info.get('is_home')
        ))

        return features

    def compute_all_features(
        self,
        season: int,
        week: int,
        positions: Optional[List[str]] = None
    ) -> Dict[str, int]:
        """
        Compute features for all players with stats in the specified week.

        Args:
            season: Season year
            week: Week to compute features for
            positions: Optional list of positions to filter (e.g., ['QB', 'RB', 'WR'])

        Returns:
            Dictionary with processing stats (total, inserted, updated, errors)
        """
        start_time = time.time()
        stats = {'total': 0, 'inserted': 0, 'updated': 0, 'errors': 0}

        # Get players who have stats prior to this week
        player_ids = self._get_players_with_prior_stats(season, week, positions)
        stats['total'] = len(player_ids)

        logger.info(f"Computing features for {len(player_ids)} players ({season} W{week})")

        for i, player_id in enumerate(player_ids):
            try:
                features = self.compute_player_features(player_id, season, week)
                result = self._save_features(features)
                if result == 'inserted':
                    stats['inserted'] += 1
                elif result == 'updated':
                    stats['updated'] += 1

                # Progress logging every 100 players
                if (i + 1) % 100 == 0:
                    elapsed = time.time() - start_time
                    logger.info(f"  Progress: {i + 1}/{len(player_ids)} ({elapsed:.1f}s)")

            except Exception as e:
                logger.error(f"Error computing features for {player_id}: {e}")
                stats['errors'] += 1

        self.connection.commit()

        elapsed = time.time() - start_time
        logger.info(
            f"Feature computation complete: {stats['inserted']} inserted, "
            f"{stats['updated']} updated, {stats['errors']} errors ({elapsed:.1f}s)"
        )

        return stats

    def compute_historical_features(
        self,
        seasons: List[int],
        positions: Optional[List[str]] = None
    ) -> Dict[str, int]:
        """
        Compute features for all historical weeks.

        Args:
            seasons: List of seasons to process
            positions: Optional list of positions to filter

        Returns:
            Aggregated processing stats
        """
        total_stats = {'total': 0, 'inserted': 0, 'updated': 0, 'errors': 0}

        for season in seasons:
            logger.info(f"Processing season {season}...")

            # Get weeks with data for this season
            weeks = self._get_weeks_with_data(season)

            for week in weeks:
                # Skip week 1 (no prior data)
                if week == 1:
                    continue

                stats = self.compute_all_features(season, week, positions)
                for key in total_stats:
                    total_stats[key] += stats[key]

        return total_stats

    def _get_players_with_prior_stats(
        self,
        season: int,
        week: int,
        positions: Optional[List[str]] = None
    ) -> List[str]:
        """
        Get player IDs who have stats in prior weeks of the season.

        Args:
            season: Season year
            week: Current week
            positions: Optional position filter

        Returns:
            List of player IDs
        """
        query = """
            SELECT DISTINCT pws.player_id
            FROM player_weekly_stats pws
            JOIN players p ON pws.player_id = p.player_id
            WHERE pws.season = %s AND pws.week < %s
        """
        params = [season, week]

        if positions:
            placeholders = ','.join(['%s'] * len(positions))
            query += f" AND p.position IN ({placeholders})"
            params.extend(positions)

        self.cursor.execute(query, params)
        return [row[0] for row in self.cursor.fetchall()]

    def _get_weeks_with_data(self, season: int) -> List[int]:
        """Get weeks that have data for a season."""
        query = """
            SELECT DISTINCT week
            FROM player_weekly_stats
            WHERE season = %s
            ORDER BY week
        """
        self.cursor.execute(query, (season,))
        return [row[0] for row in self.cursor.fetchall()]

    def _save_features(self, features: Dict) -> str:
        """
        Save features to database using upsert.

        Args:
            features: Dictionary of features to save

        Returns:
            'inserted' or 'updated'
        """
        # Define column order (must match table schema)
        columns = [
            'player_id', 'season', 'week',
            # Rolling averages
            'fantasy_pts_avg_3', 'fantasy_pts_avg_5', 'fantasy_pts_avg_10',
            'rushing_yds_avg_3', 'receiving_yds_avg_3', 'passing_yds_avg_3',
            'targets_avg_3', 'touches_avg_3', 'receptions_avg_3',
            # Efficiency
            'yards_per_carry', 'yards_per_target', 'yards_per_reception',
            'td_per_touch', 'catch_rate', 'yards_per_pass_attempt', 'td_per_pass_attempt',
            # Consistency
            'fantasy_pts_std_5', 'boom_rate_5', 'bust_rate_5', 'floor_score',
            # Trends
            'fantasy_pts_trend_3', 'usage_trend_3', 'snap_share_trend_3', 'target_share_trend_3',
            # Matchups
            'opp_position_rank', 'opp_fantasy_pts_allowed', 'is_home', 'days_rest',
        ]

        values = [features.get(col) for col in columns]

        # Build upsert query
        placeholders = ','.join(['%s'] * len(columns))
        update_cols = [f"{col} = EXCLUDED.{col}" for col in columns if col not in ['player_id', 'season', 'week']]
        update_clause = ','.join(update_cols)

        query = f"""
            INSERT INTO player_features ({','.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (player_id, season, week)
            DO UPDATE SET {update_clause}, computed_at = CURRENT_TIMESTAMP
            RETURNING (xmax = 0) as inserted
        """

        self.cursor.execute(query, values)
        result = self.cursor.fetchone()

        return 'inserted' if result[0] else 'updated'

    def get_features_for_prediction(
        self,
        player_ids: List[str],
        season: int,
        week: int
    ) -> List[Dict]:
        """
        Get computed features for use in ML prediction.

        Args:
            player_ids: List of player IDs
            season: Season year
            week: Week number

        Returns:
            List of feature dictionaries
        """
        if not player_ids:
            return []

        placeholders = ','.join(['%s'] * len(player_ids))
        query = f"""
            SELECT *
            FROM player_features
            WHERE player_id IN ({placeholders})
              AND season = %s
              AND week = %s
        """

        self.cursor.execute(query, (*player_ids, season, week))
        columns = [desc[0] for desc in self.cursor.description]
        rows = self.cursor.fetchall()

        return [dict(zip(columns, row)) for row in rows]

    def get_feature_summary(self) -> Dict:
        """
        Get summary statistics about computed features.

        Returns:
            Dictionary with feature computation statistics
        """
        query = """
            SELECT
                COUNT(*) as total_records,
                COUNT(DISTINCT player_id) as unique_players,
                MIN(season) as min_season,
                MAX(season) as max_season,
                MIN(computed_at) as oldest_computation,
                MAX(computed_at) as newest_computation
            FROM player_features
        """
        self.cursor.execute(query)
        row = self.cursor.fetchone()
        columns = ['total_records', 'unique_players', 'min_season', 'max_season',
                   'oldest_computation', 'newest_computation']
        return dict(zip(columns, row))
