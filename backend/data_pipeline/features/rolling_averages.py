"""
Rolling Averages Feature Module

Computes rolling averages for key statistics over different windows (3, 5, 10 games).
Uses only data from previous weeks to avoid data leakage.
"""

from typing import Dict, List, Optional
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class RollingAverages:
    """Compute rolling average features from historical stats."""

    def __init__(self, cursor):
        """
        Initialize with database cursor.

        Args:
            cursor: Database cursor for executing queries
        """
        self.cursor = cursor

    def compute(self, player_id: str, season: int, week: int) -> Dict[str, Optional[Decimal]]:
        """
        Compute rolling averages for a player at a specific week.

        Uses only data from previous weeks (no data leakage).
        For week 5, uses weeks 1-4. For week 1, returns None for all features.

        Args:
            player_id: The player's unique ID
            season: The season year
            week: The week to compute features for

        Returns:
            Dictionary with 9 rolling average features
        """
        features = {
            'fantasy_pts_avg_3': None,
            'fantasy_pts_avg_5': None,
            'fantasy_pts_avg_10': None,
            'rushing_yds_avg_3': None,
            'receiving_yds_avg_3': None,
            'passing_yds_avg_3': None,
            'targets_avg_3': None,
            'touches_avg_3': None,
            'receptions_avg_3': None,
            'games_played_prior': 0,
            'current_season_games_played': 0,
            'has_prev_season_data': False,
            'has_full_window_3': False,
            'has_full_window_5': False,
            'has_full_window_10': False,
            'fantasy_pts_baseline': None,
        }

        # Get historical stats for this player (prior weeks only)
        stats = self._get_prior_stats(player_id, season, week)

        if not stats:
            return features

        # Compute rolling averages
        current_season_games = sum(1 for s in stats if s.get('season') == season)
        previous_season_games = len(stats) - current_season_games
        features['games_played_prior'] = len(stats)
        features['current_season_games_played'] = current_season_games
        features['has_prev_season_data'] = previous_season_games > 0
        features['has_full_window_3'] = len(stats) >= 3
        features['has_full_window_5'] = len(stats) >= 5
        features['has_full_window_10'] = len(stats) >= 10

        features['fantasy_pts_avg_3'] = self._rolling_avg(stats, 'fantasy_points_ppr', 3)
        features['fantasy_pts_avg_5'] = self._rolling_avg(stats, 'fantasy_points_ppr', 5)
        features['fantasy_pts_avg_10'] = self._rolling_avg(stats, 'fantasy_points_ppr', 10)
        features['rushing_yds_avg_3'] = self._rolling_avg(stats, 'rushing_yards', 3)
        features['receiving_yds_avg_3'] = self._rolling_avg(stats, 'receiving_yards', 3)
        features['passing_yds_avg_3'] = self._rolling_avg(stats, 'passing_yards', 3)
        features['targets_avg_3'] = self._rolling_avg(stats, 'targets', 3)
        features['receptions_avg_3'] = self._rolling_avg(stats, 'receptions', 3)
        features['fantasy_pts_baseline'] = self._blended_baseline(stats, season)

        # Touches = rushing_attempts + receptions
        if stats:
            touches = []
            for s in stats[-3:]:
                touch = (s.get('rushing_attempts') or 0) + (s.get('receptions') or 0)
                touches.append(touch)
            features['touches_avg_3'] = Decimal(str(round(sum(touches) / len(touches), 2)))

        return features

    def _get_prior_stats(self, player_id: str, season: int, week: int) -> List[Dict]:
        """
        Get all stats for a player prior to the given week.

        Includes current season prior weeks and previous season for cross-season averages.

        Args:
            player_id: Player's unique ID
            season: Current season
            week: Current week (will get stats before this week)

        Returns:
            List of stat dictionaries ordered by season, week
        """
        query = """
            SELECT
                season, week, fantasy_points_ppr,
                passing_yards, rushing_yards, receiving_yards,
                rushing_attempts, targets, receptions,
                passing_tds, rushing_tds, receiving_tds
            FROM player_weekly_stats
            WHERE player_id = %s
              AND ((season = %s AND week < %s) OR (season < %s))
            ORDER BY season DESC, week DESC
            LIMIT 10
        """
        self.cursor.execute(query, (player_id, season, week, season))
        rows = self.cursor.fetchall()

        # Convert to list of dicts and reverse to chronological order
        columns = [
            'season', 'week', 'fantasy_points_ppr',
            'passing_yards', 'rushing_yards', 'receiving_yards',
            'rushing_attempts', 'targets', 'receptions',
            'passing_tds', 'rushing_tds', 'receiving_tds'
        ]
        stats = [dict(zip(columns, row)) for row in rows]
        return list(reversed(stats))

    def _rolling_avg(self, stats: List[Dict], field: str, window: int) -> Optional[Decimal]:
        """
        Compute rolling average for a field over given window.

        Args:
            stats: List of stat dictionaries (chronological order)
            field: The field name to average
            window: Number of games to include

        Returns:
            Decimal average or None if insufficient data
        """
        if len(stats) < window:
            # Use available data if we have at least 1 game
            if len(stats) >= 1:
                values = [s.get(field) or 0 for s in stats]
                return Decimal(str(round(sum(values) / len(values), 2)))
            return None

        # Use last N games
        recent = stats[-window:]
        values = [s.get(field) or 0 for s in recent]
        return Decimal(str(round(sum(values) / len(values), 2)))

    def _blended_baseline(self, stats: List[Dict], season: int, prior_weight: int = 3) -> Optional[Decimal]:
        """
        Blend current-season form with prior-season history for early-season stability.

        The current season contributes its available games. Prior seasons act as a
        shrinkage prior so week 1-3 predictions do not collapse toward zero.
        """
        current_values = [
            float(s.get('fantasy_points_ppr') or 0)
            for s in stats
            if s.get('season') == season
        ]
        prior_values = [
            float(s.get('fantasy_points_ppr') or 0)
            for s in stats
            if s.get('season') != season
        ]

        if current_values and prior_values:
            current_avg = sum(current_values) / len(current_values)
            prior_avg = sum(prior_values[-5:]) / len(prior_values[-5:])
            blended = ((len(current_values) * current_avg) + (prior_weight * prior_avg)) / (
                len(current_values) + prior_weight
            )
            return Decimal(str(round(blended, 2)))

        if current_values:
            return Decimal(str(round(sum(current_values) / len(current_values), 2)))

        if prior_values:
            return Decimal(str(round(sum(prior_values[-5:]) / len(prior_values[-5:]), 2)))

        return None

    def compute_batch(self, player_ids: List[str], season: int, week: int) -> Dict[str, Dict]:
        """
        Compute rolling averages for multiple players efficiently.

        Args:
            player_ids: List of player IDs
            season: Season year
            week: Week number

        Returns:
            Dictionary mapping player_id to feature dictionary
        """
        results = {}
        for player_id in player_ids:
            try:
                results[player_id] = self.compute(player_id, season, week)
            except Exception as e:
                logger.warning(f"Error computing rolling averages for {player_id}: {e}")
                results[player_id] = {k: None for k in [
                    'fantasy_pts_avg_3', 'fantasy_pts_avg_5', 'fantasy_pts_avg_10',
                    'rushing_yds_avg_3', 'receiving_yds_avg_3', 'passing_yds_avg_3',
                    'targets_avg_3', 'touches_avg_3', 'receptions_avg_3',
                    'games_played_prior', 'current_season_games_played', 'has_prev_season_data',
                    'has_full_window_3', 'has_full_window_5', 'has_full_window_10',
                    'fantasy_pts_baseline'
                ]}
        return results
