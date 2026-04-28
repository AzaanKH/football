"""
Efficiency Metrics Feature Module

Computes efficiency metrics from season-to-date statistics.
Metrics include yards per attempt, catch rate, touchdown rates, etc.
"""

from typing import Dict, Optional
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class EfficiencyMetrics:
    """Compute efficiency features from historical stats."""

    def __init__(self, cursor):
        """
        Initialize with database cursor.

        Args:
            cursor: Database cursor for executing queries
        """
        self.cursor = cursor

    def compute(self, player_id: str, season: int, week: int) -> Dict[str, Optional[Decimal]]:
        """
        Compute efficiency metrics for a player at a specific week.

        Uses season-to-date data (weeks prior to current week).

        Args:
            player_id: The player's unique ID
            season: The season year
            week: The week to compute features for

        Returns:
            Dictionary with 7 efficiency features
        """
        features = {
            'yards_per_carry': None,
            'yards_per_target': None,
            'yards_per_reception': None,
            'td_per_touch': None,
            'catch_rate': None,
            'yards_per_pass_attempt': None,
            'td_per_pass_attempt': None,
        }

        # Get season-to-date totals, falling back to recent prior-season data
        totals = self._get_season_totals(player_id, season, week)

        if not totals:
            return features

        # Rushing efficiency
        if totals['rushing_attempts'] and totals['rushing_attempts'] > 0:
            features['yards_per_carry'] = Decimal(str(round(
                totals['rushing_yards'] / totals['rushing_attempts'], 2
            )))

        # Receiving efficiency
        if totals['targets'] and totals['targets'] > 0:
            features['yards_per_target'] = Decimal(str(round(
                totals['receiving_yards'] / totals['targets'], 2
            )))
            features['catch_rate'] = Decimal(str(round(
                totals['receptions'] / totals['targets'], 4
            )))

        if totals['receptions'] and totals['receptions'] > 0:
            features['yards_per_reception'] = Decimal(str(round(
                totals['receiving_yards'] / totals['receptions'], 2
            )))

        # TD efficiency (per touch)
        total_touches = (totals['rushing_attempts'] or 0) + (totals['receptions'] or 0)
        total_tds = (totals['rushing_tds'] or 0) + (totals['receiving_tds'] or 0)
        if total_touches > 0:
            features['td_per_touch'] = Decimal(str(round(
                total_tds / total_touches, 4
            )))

        # Passing efficiency
        if totals['passing_attempts'] and totals['passing_attempts'] > 0:
            features['yards_per_pass_attempt'] = Decimal(str(round(
                totals['passing_yards'] / totals['passing_attempts'], 2
            )))
            features['td_per_pass_attempt'] = Decimal(str(round(
                totals['passing_tds'] / totals['passing_attempts'], 4
            )))

        return features

    def _get_season_totals(self, player_id: str, season: int, week: int) -> Optional[Dict]:
        """
        Get season-to-date totals for a player prior to the given week.

        Args:
            player_id: Player's unique ID
            season: Current season
            week: Current week (will sum stats before this week)

        Returns:
            Dictionary with summed totals or None if no data
        """
        query = """
            SELECT
                COALESCE(SUM(passing_attempts), 0) as passing_attempts,
                COALESCE(SUM(passing_yards), 0) as passing_yards,
                COALESCE(SUM(passing_tds), 0) as passing_tds,
                COALESCE(SUM(rushing_attempts), 0) as rushing_attempts,
                COALESCE(SUM(rushing_yards), 0) as rushing_yards,
                COALESCE(SUM(rushing_tds), 0) as rushing_tds,
                COALESCE(SUM(targets), 0) as targets,
                COALESCE(SUM(receptions), 0) as receptions,
                COALESCE(SUM(receiving_yards), 0) as receiving_yards,
                COALESCE(SUM(receiving_tds), 0) as receiving_tds,
                COUNT(*) as games_played
            FROM player_weekly_stats
            WHERE player_id = %s
              AND season = %s
              AND week < %s
        """
        self.cursor.execute(query, (player_id, season, week))
        row = self.cursor.fetchone()

        if row and row[10] > 0:  # games_played is last column
            columns = [
                'passing_attempts', 'passing_yards', 'passing_tds',
                'rushing_attempts', 'rushing_yards', 'rushing_tds',
                'targets', 'receptions', 'receiving_yards', 'receiving_tds',
                'games_played'
            ]
            return dict(zip(columns, row))

        history_query = """
            SELECT
                COALESCE(SUM(passing_attempts), 0) as passing_attempts,
                COALESCE(SUM(passing_yards), 0) as passing_yards,
                COALESCE(SUM(passing_tds), 0) as passing_tds,
                COALESCE(SUM(rushing_attempts), 0) as rushing_attempts,
                COALESCE(SUM(rushing_yards), 0) as rushing_yards,
                COALESCE(SUM(rushing_tds), 0) as rushing_tds,
                COALESCE(SUM(targets), 0) as targets,
                COALESCE(SUM(receptions), 0) as receptions,
                COALESCE(SUM(receiving_yards), 0) as receiving_yards,
                COALESCE(SUM(receiving_tds), 0) as receiving_tds,
                COUNT(*) as games_played
            FROM (
                SELECT *
                FROM player_weekly_stats
                WHERE player_id = %s
                  AND ((season = %s AND week < %s) OR season < %s)
                ORDER BY season DESC, week DESC
                LIMIT 10
            ) recent_games
        """
        self.cursor.execute(history_query, (player_id, season, week, season))
        row = self.cursor.fetchone()
        if not row or row[10] == 0:
            return None

        columns = [
            'passing_attempts', 'passing_yards', 'passing_tds',
            'rushing_attempts', 'rushing_yards', 'rushing_tds',
            'targets', 'receptions', 'receiving_yards', 'receiving_tds',
            'games_played'
        ]
        return dict(zip(columns, row))

    def compute_batch(self, player_ids: list, season: int, week: int) -> Dict[str, Dict]:
        """
        Compute efficiency metrics for multiple players.

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
                logger.warning(f"Error computing efficiency for {player_id}: {e}")
                results[player_id] = {k: None for k in [
                    'yards_per_carry', 'yards_per_target', 'yards_per_reception',
                    'td_per_touch', 'catch_rate', 'yards_per_pass_attempt', 'td_per_pass_attempt'
                ]}
        return results
