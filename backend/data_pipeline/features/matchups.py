"""
Matchup Features Module

Computes matchup-based features including opponent strength,
home/away indicator, and days rest.
"""

from typing import Dict, Optional
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class MatchupFeatures:
    """Compute matchup features based on opponent and game context."""

    def __init__(self, cursor):
        """
        Initialize with database cursor.

        Args:
            cursor: Database cursor for executing queries
        """
        self.cursor = cursor

    def compute(
        self,
        player_id: str,
        season: int,
        week: int,
        opponent: Optional[str] = None,
        is_home: Optional[bool] = None
    ) -> Dict[str, Optional[any]]:
        """
        Compute matchup features for a player's upcoming game.

        Args:
            player_id: The player's unique ID
            season: The season year
            week: The week to compute features for
            opponent: Opponent team abbreviation (e.g., 'KC', 'BUF')
            is_home: Whether the player is playing at home

        Returns:
            Dictionary with 4 matchup features
        """
        features = {
            'opp_position_rank': None,
            'opp_fantasy_pts_allowed': None,
            'is_home': is_home,
            'days_rest': None,
        }

        # Get player's position
        position = self._get_player_position(player_id)

        if opponent and position:
            # Get opponent's defense ranking vs this position
            opp_stats = self._get_opponent_defense(opponent, position, season, week)
            if opp_stats:
                features['opp_position_rank'] = opp_stats.get('rank')
                features['opp_fantasy_pts_allowed'] = opp_stats.get('pts_allowed')

        # Calculate days rest since last game
        features['days_rest'] = self._get_days_rest(player_id, season, week)

        return features

    def _get_player_position(self, player_id: str) -> Optional[str]:
        """
        Get player's position.

        Args:
            player_id: Player's unique ID

        Returns:
            Position string (QB, RB, WR, TE) or None
        """
        query = "SELECT position FROM players WHERE player_id = %s"
        self.cursor.execute(query, (player_id,))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def _get_opponent_defense(
        self,
        team: str,
        position: str,
        season: int,
        week: int
    ) -> Optional[Dict]:
        """
        Get opponent's defense stats against a position.

        Uses team_defense_stats table if available, otherwise computes from historical data.

        Args:
            team: Team abbreviation
            position: Position to check (QB, RB, WR, TE)
            season: Season year
            week: Week number

        Returns:
            Dictionary with rank and pts_allowed or None
        """
        # Try to get from team_defense_stats table
        rank_column = f"rank_vs_{position.lower()}"
        pts_column = f"fantasy_points_allowed_{position.lower()}"

        # Get most recent defense stats before this week
        query = f"""
            SELECT {rank_column}, {pts_column}
            FROM team_defense_stats
            WHERE team = %s AND season = %s AND week < %s
            ORDER BY week DESC
            LIMIT 1
        """
        try:
            self.cursor.execute(query, (team, season, week))
            row = self.cursor.fetchone()
            if row:
                return {'rank': row[0], 'pts_allowed': Decimal(str(row[1])) if row[1] else None}
        except Exception as e:
            logger.debug(f"Could not get defense stats from table: {e}")

        # Fallback: Calculate from historical data
        return self._calculate_defense_stats(team, position, season, week)

    def _calculate_defense_stats(
        self,
        team: str,
        position: str,
        season: int,
        week: int
    ) -> Optional[Dict]:
        """
        Calculate opponent defense stats from historical player performance.

        Computes average fantasy points allowed to a position by looking at
        all games where players of that position played against this team.

        Args:
            team: Team abbreviation
            position: Position to check
            season: Season year
            week: Week number

        Returns:
            Dictionary with estimated pts_allowed or None
        """
        # This query requires knowing which team each player faced each week
        # For now, return None as we don't have schedule data
        # This could be enhanced later with schedule/matchup data
        return None

    def _get_days_rest(self, player_id: str, season: int, week: int) -> Optional[int]:
        """
        Calculate days since player's last game.

        Standard NFL schedule: 7 days between games, unless bye week.

        Args:
            player_id: Player's unique ID
            season: Current season
            week: Current week

        Returns:
            Days since last game, typically 7 for normal weeks
        """
        # Check if player played the previous week
        query = """
            SELECT week
            FROM player_weekly_stats
            WHERE player_id = %s
              AND season = %s
              AND week < %s
            ORDER BY week DESC
            LIMIT 1
        """
        self.cursor.execute(query, (player_id, season, week))
        row = self.cursor.fetchone()

        if not row:
            # No previous game this season - could be first game or injury
            return None

        last_week = row[0]
        weeks_since = week - last_week

        # Standard NFL rest is 7 days per week
        # Bye weeks or missed games result in more rest
        return weeks_since * 7

    def compute_batch(
        self,
        player_ids: list,
        season: int,
        week: int,
        matchup_data: Optional[Dict] = None
    ) -> Dict[str, Dict]:
        """
        Compute matchup features for multiple players.

        Args:
            player_ids: List of player IDs
            season: Season year
            week: Week number
            matchup_data: Optional dict mapping player_id to {opponent, is_home}

        Returns:
            Dictionary mapping player_id to feature dictionary
        """
        matchup_data = matchup_data or {}
        results = {}

        for player_id in player_ids:
            try:
                player_matchup = matchup_data.get(player_id, {})
                results[player_id] = self.compute(
                    player_id,
                    season,
                    week,
                    opponent=player_matchup.get('opponent'),
                    is_home=player_matchup.get('is_home')
                )
            except Exception as e:
                logger.warning(f"Error computing matchups for {player_id}: {e}")
                results[player_id] = {k: None for k in [
                    'opp_position_rank', 'opp_fantasy_pts_allowed', 'is_home', 'days_rest'
                ]}

        return results
