"""
Matchup Features Module

Computes matchup-based features including opponent strength,
home/away indicator, and days rest.
"""

from datetime import date
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
        self._defense_cache: Dict = {}

    def compute(
        self,
        player_id: str,
        season: int,
        week: int,
        opponent: Optional[str] = None,
        is_home: Optional[bool] = None,
        game_date: Optional[date] = None,
    ) -> Dict[str, Optional[any]]:
        """
        Compute matchup features for a player's upcoming game.

        Args:
            player_id: The player's unique ID
            season: The season year
            week: The week to compute features for
            opponent: Opponent team abbreviation (e.g., 'KC', 'BUF')
            is_home: Whether the player is playing at home
            game_date: Date of this week's game, for real days of rest

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
        features['days_rest'] = self._get_days_rest(player_id, season, week, game_date)

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

    # Defense form: average over the defense's most recent games (across seasons)
    DEFENSE_WINDOW_GAMES = 8
    # Fewer games than this and the average is too noisy to use
    DEFENSE_MIN_GAMES = 3

    def _get_opponent_defense(
        self,
        team: str,
        position: str,
        season: int,
        week: int
    ) -> Optional[Dict]:
        """
        Opponent's recent fantasy points allowed to a position, and its rank.

        Args:
            team: Opponent team abbreviation
            position: Position to check (QB, RB, WR, TE)
            season: Season year
            week: Week being predicted (only earlier games are used)

        Returns:
            {'rank': 1 = fewest points allowed (toughest) .. 32,
             'pts_allowed': average PPR allowed per game} or None
        """
        return self._defense_table(season, week).get((team, position.upper()))

    def _defense_table(self, season: int, week: int) -> Dict:
        """
        (defense, position) -> {rank, pts_allowed} using games before the week.

        Built once per (season, week) from per-game opponents in
        player_weekly_stats and cached; every player that week shares it.
        """
        key = (season, week)
        if key in self._defense_cache:
            return self._defense_cache[key]

        self.cursor.execute("""
            WITH games AS (
                SELECT s.season, s.week, s.opponent AS defense, p.position,
                       SUM(s.fantasy_points_ppr) AS pts
                FROM player_weekly_stats s
                JOIN players p ON p.player_id = s.player_id
                WHERE s.played
                  AND s.opponent IS NOT NULL
                  AND p.position IN ('QB', 'RB', 'WR', 'TE')
                  AND (s.season < %s OR (s.season = %s AND s.week < %s))
                GROUP BY s.season, s.week, s.opponent, p.position
            ),
            recent AS (
                SELECT defense, position, pts,
                       ROW_NUMBER() OVER (
                           PARTITION BY defense, position ORDER BY season DESC, week DESC
                       ) AS game_rank
                FROM games
            )
            SELECT defense, position, AVG(pts), COUNT(*)
            FROM recent
            WHERE game_rank <= %s
            GROUP BY defense, position
            HAVING COUNT(*) >= %s
        """, (season, season, week, self.DEFENSE_WINDOW_GAMES, self.DEFENSE_MIN_GAMES))

        by_position: Dict[str, list] = {}
        for defense, position, pts, _games in self.cursor.fetchall():
            by_position.setdefault(position, []).append((float(pts), defense))

        table = {}
        for position, entries in by_position.items():
            for rank, (pts, defense) in enumerate(sorted(entries), start=1):
                table[(defense, position)] = {
                    'rank': rank,
                    'pts_allowed': Decimal(str(round(pts, 2))),
                }

        self._defense_cache[key] = table
        return table

    def _get_days_rest(self, player_id: str, season: int, week: int,
                       game_date: Optional[date] = None) -> Optional[int]:
        """
        Days since the player's previous game this season.

        Uses real game dates when both are known (Thursday/Monday games,
        byes); otherwise approximates 7 days per week.

        Args:
            player_id: Player's unique ID
            season: Current season
            week: Current week
            game_date: Date of this week's game, if known

        Returns:
            Days of rest, or None before the player's first game of the season
        """
        query = """
            SELECT week, game_date
            FROM player_weekly_stats
            WHERE player_id = %s
              AND played
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

        last_week, last_date = row
        if game_date and last_date:
            return (game_date - last_date).days
        return (week - last_week) * 7

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
