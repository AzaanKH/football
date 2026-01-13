"""
Trend Features Module

Computes trend features using linear regression to identify
whether a player's performance is improving or declining.
"""

from typing import Dict, List, Optional
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class TrendFeatures:
    """Compute trend features from historical stats."""

    def __init__(self, cursor):
        """
        Initialize with database cursor.

        Args:
            cursor: Database cursor for executing queries
        """
        self.cursor = cursor

    def compute(self, player_id: str, season: int, week: int) -> Dict[str, Optional[Decimal]]:
        """
        Compute trend features for a player at a specific week.

        Uses linear regression slope over last 3 games to determine trend.
        Positive slope = improving, negative slope = declining.

        Args:
            player_id: The player's unique ID
            season: The season year
            week: The week to compute features for

        Returns:
            Dictionary with 4 trend features
        """
        features = {
            'fantasy_pts_trend_3': None,
            'usage_trend_3': None,
            'snap_share_trend_3': None,
            'target_share_trend_3': None,
        }

        # Get recent stats
        stats = self._get_recent_stats(player_id, season, week)

        if not stats or len(stats) < 2:
            return features

        # Use last 3 games for trends
        recent = stats[-3:] if len(stats) >= 3 else stats

        # Fantasy points trend
        fantasy_pts = [s.get('fantasy_points_ppr') or 0 for s in recent]
        features['fantasy_pts_trend_3'] = self._compute_slope(fantasy_pts)

        # Usage trend (touches = rushing_attempts + receptions)
        usage = [
            (s.get('rushing_attempts') or 0) + (s.get('receptions') or 0)
            for s in recent
        ]
        features['usage_trend_3'] = self._compute_slope(usage)

        # Note: snap_share and target_share require team-level data
        # which we don't currently have. Set to None for now.
        # These could be added later when we have team snap counts
        features['snap_share_trend_3'] = None
        features['target_share_trend_3'] = None

        return features

    def _get_recent_stats(self, player_id: str, season: int, week: int) -> List[Dict]:
        """
        Get recent stats for trend analysis.

        Args:
            player_id: Player's unique ID
            season: Current season
            week: Current week

        Returns:
            List of stat dictionaries (chronological order)
        """
        query = """
            SELECT
                season, week, fantasy_points_ppr,
                rushing_attempts, targets, receptions
            FROM player_weekly_stats
            WHERE player_id = %s
              AND ((season = %s AND week < %s) OR (season < %s))
            ORDER BY season DESC, week DESC
            LIMIT 5
        """
        self.cursor.execute(query, (player_id, season, week, season))
        rows = self.cursor.fetchall()

        columns = ['season', 'week', 'fantasy_points_ppr', 'rushing_attempts', 'targets', 'receptions']
        stats = [dict(zip(columns, row)) for row in rows]
        return list(reversed(stats))  # Chronological order

    def _compute_slope(self, values: List[float]) -> Optional[Decimal]:
        """
        Compute linear regression slope for a series of values.

        Uses simple linear regression: slope = sum((x-x_mean)(y-y_mean)) / sum((x-x_mean)^2)

        Args:
            values: List of numeric values in chronological order

        Returns:
            Slope as Decimal (positive = improving, negative = declining)
        """
        if len(values) < 2:
            return None

        n = len(values)
        x = list(range(n))  # [0, 1, 2, ...]

        x_mean = sum(x) / n
        y_mean = sum(values) / n

        numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return Decimal('0')

        slope = numerator / denominator
        return Decimal(str(round(slope, 4)))

    def compute_batch(self, player_ids: list, season: int, week: int) -> Dict[str, Dict]:
        """
        Compute trend features for multiple players.

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
                logger.warning(f"Error computing trends for {player_id}: {e}")
                results[player_id] = {k: None for k in [
                    'fantasy_pts_trend_3', 'usage_trend_3',
                    'snap_share_trend_3', 'target_share_trend_3'
                ]}
        return results
