"""
ESPN Fantasy API Client

Secondary data source for NFL player data and cross-validation.
Note: This API is unofficial and undocumented. Endpoints may change.

Authentication:
- Public leagues: No auth required
- Private leagues: Requires espn_s2 and SWID cookies
"""

import httpx
import logging
from typing import Dict, List, Optional, Any
import time

logger = logging.getLogger(__name__)


class ESPNClient:
    """
    Client for the ESPN Fantasy Football API.

    This is an unofficial API reverse-engineered from ESPN's web app.
    Use as secondary/validation source, not primary.

    Base URLs:
    - Fantasy API: https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl
    - Sports Core: https://sports.core.api.espn.com/v2/sports/football/leagues/nfl
    """

    FANTASY_BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
    SPORTS_CORE_URL = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
    SITE_API_URL = "https://site.api.espn.com/apis"

    def __init__(self, espn_s2: Optional[str] = None, swid: Optional[str] = None,
                 timeout: float = 30.0):
        """
        Initialize the ESPN client.

        Args:
            espn_s2: ESPN S2 cookie for private leagues
            swid: SWID cookie for private leagues
            timeout: Request timeout in seconds
        """
        cookies = {}
        if espn_s2 and swid:
            cookies = {'espn_s2': espn_s2, 'SWID': swid}

        self.client = httpx.Client(
            timeout=timeout,
            cookies=cookies,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'X-Fantasy-Source': 'kona',
                'X-Fantasy-Platform': 'kona-PROD-1dc40132dc2070ef47881dc95b633e62cebc9e9e'
            }
        )
        self._last_request_time = 0
        self._min_request_interval = 0.5  # 500ms between requests (be conservative)

    def _rate_limit(self):
        """Ensure we don't hit rate limits."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str, params: Optional[Dict] = None) -> Optional[Any]:
        """
        Make a GET request.

        Args:
            url: Full URL to request
            params: Query parameters

        Returns:
            JSON response or None if request failed
        """
        self._rate_limit()

        try:
            logger.debug(f"Requesting: {url}")
            response = self.client.get(url, params=params)
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

    def get_players(self, season: int, scoring_period: int = 0,
                   limit: int = 1000) -> List[Dict]:
        """
        Fetch player data from ESPN.

        Args:
            season: NFL season year
            scoring_period: Week number (0 for full season)
            limit: Maximum players to return

        Returns:
            List of player data
        """
        url = f"{self.FANTASY_BASE_URL}/seasons/{season}/players"

        # ESPN requires a special filter header for large requests
        headers = {
            'X-Fantasy-Filter': f'{{"players":{{"limit":{limit},"filterActive":{{"value":true}}}}}}'
        }

        self._rate_limit()

        try:
            response = self.client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            players = data.get('players', [])
            logger.info(f"Retrieved {len(players)} players from ESPN")
            return players
        except Exception as e:
            logger.error(f"Failed to fetch ESPN players: {e}")
            return []

    def get_player_news(self, player_id: int, limit: int = 10) -> List[Dict]:
        """
        Fetch recent news for a player.

        Args:
            player_id: ESPN player ID (not Sleeper ID)
            limit: Maximum news items

        Returns:
            List of news items
        """
        url = f"{self.SITE_API_URL}/fantasy/v2/games/ffl/news/players"
        params = {'playerId': player_id, 'limit': limit}

        data = self._get(url, params=params)
        if data:
            return data.get('feed', [])
        return []

    def get_team_injuries(self, team_id: int) -> List[Dict]:
        """
        Fetch injuries for a specific team.

        Args:
            team_id: ESPN team ID (1-32)

        Returns:
            List of injury reports
        """
        url = f"{self.SPORTS_CORE_URL}/teams/{team_id}/injuries"

        data = self._get(url)
        if data:
            return data.get('items', [])
        return []

    def get_all_injuries(self) -> Dict[str, List[Dict]]:
        """
        Fetch injuries for all teams.

        Returns:
            Dictionary mapping team abbreviation to injury list
        """
        # ESPN team IDs mapping (approximate)
        team_ids = {
            'ARI': 22, 'ATL': 1, 'BAL': 33, 'BUF': 2, 'CAR': 29, 'CHI': 3,
            'CIN': 4, 'CLE': 5, 'DAL': 6, 'DEN': 7, 'DET': 8, 'GB': 9,
            'HOU': 34, 'IND': 11, 'JAX': 30, 'KC': 12, 'LAC': 24, 'LAR': 14,
            'LV': 13, 'MIA': 15, 'MIN': 16, 'NE': 17, 'NO': 18, 'NYG': 19,
            'NYJ': 20, 'PHI': 21, 'PIT': 23, 'SEA': 26, 'SF': 25, 'TB': 27,
            'TEN': 10, 'WAS': 28
        }

        injuries = {}
        for team_abbr, team_id in team_ids.items():
            team_injuries = self.get_team_injuries(team_id)
            if team_injuries:
                injuries[team_abbr] = team_injuries
            time.sleep(0.3)  # Extra rate limiting for bulk requests

        return injuries

    def get_scoreboard(self, season: int, week: int) -> Optional[Dict]:
        """
        Fetch scoreboard data for a week.

        Args:
            season: NFL season year
            week: Week number

        Returns:
            Scoreboard data or None
        """
        url = f"{self.SITE_API_URL}/fantasy/v2/games/ffl/games"
        params = {
            'dates': f'{season}',
            'seasontype': 2,
            'week': week
        }

        return self._get(url, params=params)

    def get_league_data(self, league_id: int, season: int,
                       views: List[str] = None) -> Optional[Dict]:
        """
        Fetch data for a specific league.

        Args:
            league_id: ESPN league ID
            season: NFL season year
            views: List of views to include (mTeam, mRoster, mMatchup, etc.)

        Returns:
            League data or None
        """
        if views is None:
            views = ['mTeam', 'mRoster', 'mMatchup', 'mSettings']

        url = f"{self.FANTASY_BASE_URL}/seasons/{season}/segments/0/leagues/{league_id}"
        params = {'view': views}

        return self._get(url, params=params)

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def transform_espn_player(espn_player: Dict) -> Dict:
    """
    Transform ESPN player data to match our schema.

    Args:
        espn_player: Raw player data from ESPN

    Returns:
        Transformed player data
    """
    player_info = espn_player.get('player', {})

    # ESPN position mapping
    position_map = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'DST'}

    return {
        'espn_id': str(player_info.get('id', '')),
        'full_name': player_info.get('fullName', ''),
        'first_name': player_info.get('firstName', ''),
        'last_name': player_info.get('lastName', ''),
        'position': position_map.get(player_info.get('defaultPositionId'), ''),
        'team': player_info.get('proTeamId'),  # Need to map team ID to abbr
        'injury_status': player_info.get('injuryStatus', ''),
        'source': 'espn'
    }


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    with ESPNClient() as client:
        # Test getting players (limited)
        print("Testing ESPN API...")

        # This might not work without proper setup
        # players = client.get_players(season=2024, limit=10)
        # print(f"Retrieved {len(players)} players")

        print("ESPN client initialized successfully")
        print("Note: Many ESPN endpoints require league access or may be restricted")
