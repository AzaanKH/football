"""
Consistency Metrics Feature Module

Computes consistency/volatility metrics including standard deviation,
boom/bust rates, and floor scores.
"""

from typing import Dict, List, Optional
from decimal import Decimal
import math
import logging

logger = logging.getLogger(__name__)


class ConsistencyMetrics:
    """Compute consistency features from historical stats."""

    # Thresholds for boom/bust classification (PPR scoring)
    BOOM_THRESHOLD = 20.0  # Points above this = boom game
    BUST_THRESHOLD = 5.0   # Points below this = bust game

    def __init__(self, cursor):
        """
        Initialize with database cursor.

        Args:
            cursor: Database cursor for executing queries
        """
        self.cursor = cursor

    def compute(self, player_id: str, season: int, week: int) -> Dict[str, Optional[Decimal]]:
        """
        Compute consistency metrics for a player at a specific week.

        Uses data from previous weeks only to avoid data leakage.

        Args:
            player_id: The player's unique ID
            season: The season year
            week: The week to compute features for

        Returns:
            Dictionary with 4 consistency features
        """
        features = {
            'fantasy_pts_std_5': None,
            'boom_rate_5': None,
            'bust_rate_5': None,
            'floor_score': None,
        }

        # Get recent fantasy point scores
        scores = self._get_recent_scores(player_id, season, week)

        if not scores or len(scores) < 2:
            return features

        # Use last 5 games (or whatever is available)
        recent_scores = scores[-5:] if len(scores) >= 5 else scores

        # Standard deviation
        features['fantasy_pts_std_5'] = self._compute_std(recent_scores)

        # Boom rate (% of games > 20 pts)
        boom_games = sum(1 for s in recent_scores if s > self.BOOM_THRESHOLD)
        features['boom_rate_5'] = Decimal(str(round(boom_games / len(recent_scores), 4)))

        # Bust rate (% of games < 5 pts)
        bust_games = sum(1 for s in recent_scores if s < self.BUST_THRESHOLD)
        features['bust_rate_5'] = Decimal(str(round(bust_games / len(recent_scores), 4)))

        # Floor score (10th percentile approximation)
        # For small samples, use minimum score
        sorted_scores = sorted(recent_scores)
        if len(sorted_scores) >= 10:
            floor_idx = max(0, int(len(sorted_scores) * 0.1))
            features['floor_score'] = Decimal(str(round(sorted_scores[floor_idx], 2)))
        else:
            # Use minimum as floor for small samples
            features['floor_score'] = Decimal(str(round(sorted_scores[0], 2)))

        return features

    def _get_recent_scores(self, player_id: str, season: int, week: int) -> List[float]:
        """
        Get recent fantasy point scores for a player.

        Args:
            player_id: Player's unique ID
            season: Current season
            week: Current week (will get scores before this week)

        Returns:
            List of fantasy point scores (chronological order)
        """
        query = """
            SELECT fantasy_points_ppr
            FROM player_weekly_stats
            WHERE player_id = %s
              AND ((season = %s AND week < %s) OR (season < %s))
            ORDER BY season DESC, week DESC
            LIMIT 10
        """
        self.cursor.execute(query, (player_id, season, week, season))
        rows = self.cursor.fetchall()

        # Reverse to chronological order and return scores
        scores = [float(row[0] or 0) for row in reversed(rows)]
        return scores

    def _compute_std(self, scores: List[float]) -> Optional[Decimal]:
        """
        Compute standard deviation of scores.

        Args:
            scores: List of fantasy point scores

        Returns:
            Standard deviation as Decimal or None if insufficient data
        """
        if len(scores) < 2:
            return None

        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        std = math.sqrt(variance)
        return Decimal(str(round(std, 2)))

    def compute_batch(self, player_ids: list, season: int, week: int) -> Dict[str, Dict]:
        """
        Compute consistency metrics for multiple players.

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
                logger.warning(f"Error computing consistency for {player_id}: {e}")
                results[player_id] = {k: None for k in [
                    'fantasy_pts_std_5', 'boom_rate_5', 'bust_rate_5', 'floor_score'
                ]}
        return results
