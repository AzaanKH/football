"""
Sleeper API Client

Primary data source for NFL player data and statistics.
Documentation: https://docs.sleeper.com/

Rate Limit: 1000 calls/minute (be respectful)
Authentication: None required
"""

import httpx
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class SleeperClient:
    """
    Client for the Sleeper Fantasy Football API.

    Endpoints used:
    - GET /v1/players/nfl - All NFL players (~5MB, cache daily)
    - GET /v1/stats/nfl/{season}/{week} - Weekly stats
    - GET /v1/projections/nfl/{season}/{week} - Projections
    - GET /v1/players/nfl/trending/add - Trending players (most added)
    """

    BASE_URL = "https://api.sleeper.app/v1"

    def __init__(self, timeout: float = 30.0):
        """
        Initialize the Sleeper client.

        Args:
            timeout: Request timeout in seconds
        """
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                'User-Agent': 'FantasyFootballPredictor/1.0',
                'Accept': 'application/json'
            }
        )
        self._last_request_time = 0
        self._min_request_interval = 0.1  # 100ms between requests (conservative)

    def _rate_limit(self):
        """Ensure we don't exceed rate limits."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _get(self, endpoint: str) -> Optional[Any]:
        """
        Make a GET request to the Sleeper API.

        Args:
            endpoint: API endpoint (without base URL)

        Returns:
            JSON response or None if request failed
        """
        self._rate_limit()
        url = f"{self.BASE_URL}{endpoint}"

        try:
            logger.debug(f"Requesting: {url}")
            response = self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for {url}: {e}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error for {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error for {url}: {e}")
            return None

    def get_all_players(self) -> Dict[str, Dict]:
        """
        Fetch all NFL players from Sleeper.

        This is a large response (~5MB). Cache locally and refresh daily.

        Returns:
            Dictionary mapping player_id to player data
        """
        logger.info("Fetching all NFL players from Sleeper...")
        data = self._get("/players/nfl")

        if data:
            logger.info(f"Retrieved {len(data)} players")
            return data

        logger.error("Failed to fetch players")
        return {}

    def get_player(self, player_id: str) -> Optional[Dict]:
        """
        Fetch a single player by ID.

        Args:
            player_id: Sleeper player ID

        Returns:
            Player data or None
        """
        data = self._get(f"/players/nfl/{player_id}")
        return data

    def get_weekly_stats(self, season: int, week: int) -> Dict[str, Dict]:
        """
        Fetch player stats for a specific week.

        Args:
            season: NFL season year (e.g., 2024)
            week: Week number (1-18 for regular season)

        Returns:
            Dictionary mapping player_id to their stats for that week
        """
        logger.info(f"Fetching stats for {season} week {week}...")
        data = self._get(f"/stats/nfl/regular/{season}/{week}")

        if data:
            logger.info(f"Retrieved stats for {len(data)} players")
            return data

        logger.warning(f"No stats found for {season} week {week}")
        return {}

    def get_season_stats(self, season: int) -> Dict[str, Dict]:
        """
        Fetch cumulative season stats for all players.

        Args:
            season: NFL season year

        Returns:
            Dictionary mapping player_id to their season totals
        """
        logger.info(f"Fetching season stats for {season}...")
        data = self._get(f"/stats/nfl/regular/{season}")

        if data:
            logger.info(f"Retrieved season stats for {len(data)} players")
            return data

        return {}

    def get_weekly_projections(self, season: int, week: int) -> Dict[str, Dict]:
        """
        Fetch player projections for a specific week.

        Args:
            season: NFL season year
            week: Week number

        Returns:
            Dictionary mapping player_id to their projections
        """
        logger.info(f"Fetching projections for {season} week {week}...")
        data = self._get(f"/projections/nfl/regular/{season}/{week}")

        if data:
            logger.info(f"Retrieved projections for {len(data)} players")
            return data

        return {}

    def get_trending_players(self, sport: str = "nfl", type: str = "add",
                            lookback_hours: int = 24, limit: int = 25) -> List[Dict]:
        """
        Fetch trending players (most added/dropped).

        Args:
            sport: Sport type (nfl)
            type: 'add' or 'drop'
            lookback_hours: Hours to look back (24 or 48)
            limit: Number of players to return

        Returns:
            List of trending player data
        """
        logger.info(f"Fetching trending {type} players...")
        data = self._get(f"/players/{sport}/trending/{type}?lookback_hours={lookback_hours}&limit={limit}")

        if data:
            logger.info(f"Retrieved {len(data)} trending players")
            return data

        return []

    def get_nfl_state(self) -> Optional[Dict]:
        """
        Get current NFL state (season, week, etc).

        Returns:
            Dictionary with season info or None
        """
        return self._get("/state/nfl")

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Utility functions for transforming Sleeper data

def _safe_int(value) -> Optional[int]:
    """Safely convert a value to int, returning None for invalid values."""
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_str(value) -> Optional[str]:
    """Safely convert a value to string, returning None for empty values."""
    if value is None or value == '':
        return None
    return str(value)


def transform_player_data(sleeper_player: Dict) -> Dict:
    """
    Transform Sleeper player data to our database schema.

    Args:
        sleeper_player: Raw player data from Sleeper API

    Returns:
        Transformed player data matching our schema
    """
    return {
        'player_id': sleeper_player.get('player_id'),
        'sleeper_id': sleeper_player.get('player_id'),
        'full_name': sleeper_player.get('full_name') or '',
        'first_name': sleeper_player.get('first_name') or '',
        'last_name': sleeper_player.get('last_name') or '',
        'position': _safe_str(sleeper_player.get('position')),
        'team': _safe_str(sleeper_player.get('team')),
        'status': _safe_str(sleeper_player.get('status')),
        'injury_status': _safe_str(sleeper_player.get('injury_status')),
        'injury_body_part': _safe_str(sleeper_player.get('injury_body_part')),
        'years_exp': _safe_int(sleeper_player.get('years_exp')),
        'age': _safe_int(sleeper_player.get('age')),
        'height': _safe_str(sleeper_player.get('height')),
        'weight': _safe_int(sleeper_player.get('weight')),
        'college': _safe_str(sleeper_player.get('college')),
        'fantasy_positions': sleeper_player.get('fantasy_positions') or []
    }


def transform_weekly_stats(player_id: str, stats: Dict, season: int, week: int) -> Dict:
    """
    Transform Sleeper weekly stats to our database schema.

    Args:
        player_id: Player ID
        stats: Raw stats from Sleeper API
        season: Season year
        week: Week number

    Returns:
        Transformed stats matching our schema
    """
    # Sleeper uses specific stat keys - map them to our schema
    return {
        'player_id': player_id,
        'season': season,
        'week': week,
        'fantasy_points': stats.get('pts_std', 0),
        'fantasy_points_ppr': stats.get('pts_ppr', 0),
        'passing_attempts': stats.get('pass_att', 0),
        'passing_completions': stats.get('pass_cmp', 0),
        'passing_yards': stats.get('pass_yd', 0),
        'passing_tds': stats.get('pass_td', 0),
        'interceptions': stats.get('pass_int', 0),
        'passing_2pt': stats.get('pass_2pt', 0),
        'rushing_attempts': stats.get('rush_att', 0),
        'rushing_yards': stats.get('rush_yd', 0),
        'rushing_tds': stats.get('rush_td', 0),
        'rushing_2pt': stats.get('rush_2pt', 0),
        'targets': stats.get('rec_tgt', 0),
        'receptions': stats.get('rec', 0),
        'receiving_yards': stats.get('rec_yd', 0),
        'receiving_tds': stats.get('rec_td', 0),
        'receiving_2pt': stats.get('rec_2pt', 0),
        'fumbles': stats.get('fum', 0),
        'fumbles_lost': stats.get('fum_lost', 0),
        'source': 'sleeper'
    }


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    with SleeperClient() as client:
        # Get current NFL state
        state = client.get_nfl_state()
        if state:
            print(f"Current season: {state.get('season')}, week: {state.get('week')}")

        # Get trending players
        trending = client.get_trending_players(limit=5)
        print(f"\nTop 5 trending adds:")
        for player in trending:
            print(f"  - {player.get('player_id')}: {player.get('count')} adds")
