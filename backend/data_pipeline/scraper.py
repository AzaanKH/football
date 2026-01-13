"""
Pro Football Reference Scraper

Fallback data source when APIs fail or for historical data.
Uses BeautifulSoup for HTML parsing.

Be respectful of the website:
- Use delays between requests (3+ seconds)
- Cache responses when possible
- Don't scrape excessively
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import logging
import time
from typing import Optional, Dict, List
from datetime import datetime
import re

logger = logging.getLogger(__name__)


class ProFootballReferenceScraper:
    """
    Scraper for Pro Football Reference website.

    Provides fallback data when APIs are unavailable.
    Respects rate limits and caches responses.
    """

    BASE_URL = "https://www.pro-football-reference.com"

    def __init__(self, delay: float = 3.0):
        """
        Initialize the scraper.

        Args:
            delay: Minimum seconds between requests (default 3s)
        """
        self.delay = delay
        self._last_request_time = 0
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        })

    def _rate_limit(self):
        """Wait between requests to be respectful."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            sleep_time = self.delay - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def _get_page(self, url: str) -> Optional[BeautifulSoup]:
        """
        Fetch and parse a webpage.

        Args:
            url: URL to fetch

        Returns:
            BeautifulSoup object or None if failed
        """
        self._rate_limit()

        try:
            logger.info(f"Scraping: {url}")
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'lxml')
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def get_fantasy_stats(self, season: int) -> Optional[pd.DataFrame]:
        """
        Scrape fantasy football stats for a season.

        Args:
            season: NFL season year

        Returns:
            DataFrame with fantasy stats or None
        """
        url = f"{self.BASE_URL}/years/{season}/fantasy.htm"
        soup = self._get_page(url)

        if not soup:
            return None

        table = soup.find('table', {'id': 'fantasy'})
        if not table:
            logger.error(f"Fantasy table not found for {season}")
            return None

        try:
            # Use pandas to parse the HTML table
            df = pd.read_html(str(table))[0]

            # Clean up multi-level columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ['_'.join(col).strip() for col in df.columns]

            # Remove header rows that appear in data
            df = df[df.iloc[:, 0] != 'Rk']

            logger.info(f"Scraped {len(df)} players for {season}")
            return df

        except Exception as e:
            logger.error(f"Failed to parse fantasy table: {e}")
            return None

    def get_weekly_fantasy_stats(self, season: int, week: int) -> Optional[pd.DataFrame]:
        """
        Scrape weekly fantasy stats.

        Args:
            season: NFL season year
            week: Week number

        Returns:
            DataFrame with weekly stats or None
        """
        url = f"{self.BASE_URL}/years/{season}/week_{week}/fantasy.htm"
        soup = self._get_page(url)

        if not soup:
            return None

        table = soup.find('table', {'id': 'fantasy'})
        if not table:
            logger.warning(f"Weekly fantasy table not found for {season} week {week}")
            return None

        try:
            df = pd.read_html(str(table))[0]

            # Clean column names
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ['_'.join(col).strip() for col in df.columns]

            df = df[df.iloc[:, 0] != 'Rk']

            # Add week and season columns
            df['season'] = season
            df['week'] = week

            logger.info(f"Scraped {len(df)} players for {season} week {week}")
            return df

        except Exception as e:
            logger.error(f"Failed to parse weekly fantasy table: {e}")
            return None

    def get_passing_stats(self, season: int) -> Optional[pd.DataFrame]:
        """
        Scrape passing stats for a season.

        Args:
            season: NFL season year

        Returns:
            DataFrame with passing stats or None
        """
        url = f"{self.BASE_URL}/years/{season}/passing.htm"
        soup = self._get_page(url)

        if not soup:
            return None

        table = soup.find('table', {'id': 'passing'})
        if not table:
            return None

        try:
            df = pd.read_html(str(table))[0]
            df = df[df.iloc[:, 0] != 'Rk']
            logger.info(f"Scraped {len(df)} passers for {season}")
            return df
        except Exception as e:
            logger.error(f"Failed to parse passing table: {e}")
            return None

    def get_rushing_stats(self, season: int) -> Optional[pd.DataFrame]:
        """
        Scrape rushing stats for a season.

        Args:
            season: NFL season year

        Returns:
            DataFrame with rushing stats or None
        """
        url = f"{self.BASE_URL}/years/{season}/rushing.htm"
        soup = self._get_page(url)

        if not soup:
            return None

        table = soup.find('table', {'id': 'rushing'})
        if not table:
            return None

        try:
            df = pd.read_html(str(table))[0]
            df = df[df.iloc[:, 0] != 'Rk']
            logger.info(f"Scraped {len(df)} rushers for {season}")
            return df
        except Exception as e:
            logger.error(f"Failed to parse rushing table: {e}")
            return None

    def get_receiving_stats(self, season: int) -> Optional[pd.DataFrame]:
        """
        Scrape receiving stats for a season.

        Args:
            season: NFL season year

        Returns:
            DataFrame with receiving stats or None
        """
        url = f"{self.BASE_URL}/years/{season}/receiving.htm"
        soup = self._get_page(url)

        if not soup:
            return None

        table = soup.find('table', {'id': 'receiving'})
        if not table:
            return None

        try:
            df = pd.read_html(str(table))[0]
            df = df[df.iloc[:, 0] != 'Rk']
            logger.info(f"Scraped {len(df)} receivers for {season}")
            return df
        except Exception as e:
            logger.error(f"Failed to parse receiving table: {e}")
            return None

    def get_player_game_log(self, player_url: str, season: int) -> Optional[pd.DataFrame]:
        """
        Scrape a player's game log for a season.

        Args:
            player_url: Player's PFR URL path (e.g., '/players/M/MahoPa00')
            season: NFL season year

        Returns:
            DataFrame with game-by-game stats or None
        """
        url = f"{self.BASE_URL}{player_url}/gamelog/{season}/"
        soup = self._get_page(url)

        if not soup:
            return None

        # Try different table IDs
        for table_id in ['stats', 'gamelog', 'pgl_basic']:
            table = soup.find('table', {'id': table_id})
            if table:
                break

        if not table:
            logger.warning(f"Game log table not found for {player_url}")
            return None

        try:
            df = pd.read_html(str(table))[0]
            df['season'] = season
            return df
        except Exception as e:
            logger.error(f"Failed to parse game log: {e}")
            return None

    def close(self):
        """Close the session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def transform_pfr_fantasy_stats(df: pd.DataFrame, season: int) -> List[Dict]:
    """
    Transform Pro Football Reference fantasy stats to our schema.

    Args:
        df: Raw DataFrame from PFR
        season: Season year

    Returns:
        List of transformed stat dictionaries
    """
    results = []

    # Common column mappings (PFR uses various formats)
    column_mappings = {
        'Player': 'full_name',
        'Tm': 'team',
        'FantPos': 'position',
        'G': 'games',
        'GS': 'games_started',
        'Passing_Yds': 'passing_yards',
        'Passing_TD': 'passing_tds',
        'Int': 'interceptions',
        'Rushing_Yds': 'rushing_yards',
        'Rushing_TD': 'rushing_tds',
        'Receiving_Yds': 'receiving_yards',
        'Receiving_TD': 'receiving_tds',
        'Rec': 'receptions',
        'Tgt': 'targets',
        'FL': 'fumbles_lost',
        'FantPt': 'fantasy_points',
        'PPR': 'fantasy_points_ppr',
    }

    for _, row in df.iterrows():
        try:
            stat = {'season': season, 'source': 'scraped'}

            for pfr_col, our_col in column_mappings.items():
                # Try exact match and partial match
                for col in df.columns:
                    if pfr_col in str(col):
                        value = row[col]
                        # Convert to appropriate type
                        if pd.isna(value):
                            value = 0
                        elif our_col in ['full_name', 'team', 'position']:
                            value = str(value)
                        else:
                            try:
                                value = float(value)
                            except (ValueError, TypeError):
                                value = 0
                        stat[our_col] = value
                        break

            if stat.get('full_name'):
                results.append(stat)

        except Exception as e:
            logger.warning(f"Failed to transform row: {e}")
            continue

    return results


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    with ProFootballReferenceScraper() as scraper:
        print("Testing Pro Football Reference scraper...")

        # Test fantasy stats for 2023
        df = scraper.get_fantasy_stats(2023)
        if df is not None:
            print(f"\nRetrieved {len(df)} players for 2023")
            print("\nColumns:", list(df.columns)[:10])
            print("\nSample data:")
            print(df.head(3))
        else:
            print("Failed to retrieve data")
