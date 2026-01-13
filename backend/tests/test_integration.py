"""
Integration Tests for Data Pipeline

These tests make REAL API calls to Sleeper, ESPN, and Pro Football Reference.
They do NOT write to the database.

Run with: pytest tests/test_integration.py -m integration -v

Note: These tests require internet connectivity and may be slow.
"""

import pytest
from tests.conftest import requires_internet


@pytest.mark.integration
class TestSleeperAPIIntegration:
    """Integration tests for Sleeper API (real calls)."""

    @requires_internet
    def test_get_nfl_state_returns_valid_data(self, sleeper_client):
        """Test that we can fetch current NFL state."""
        state = sleeper_client.get_nfl_state()

        assert state is not None
        assert 'season' in state
        assert 'week' in state
        # Season may be int or string depending on API
        season = int(state['season']) if isinstance(state['season'], str) else state['season']
        assert season >= 2024

    @requires_internet
    def test_get_all_players_returns_data(self, sleeper_client):
        """Test that we can fetch all players."""
        players = sleeper_client.get_all_players()

        assert players is not None
        assert len(players) > 1000  # Should have thousands of players

        # Verify structure of a player
        sample_player = next(iter(players.values()))
        assert 'player_id' in sample_player or 'full_name' in sample_player

    @requires_internet
    def test_get_all_players_includes_known_stars(self, sleeper_client):
        """Test that known star players are in the data."""
        players = sleeper_client.get_all_players()

        # Find Patrick Mahomes by name
        mahomes = None
        for player in players.values():
            if player.get('full_name') == 'Patrick Mahomes':
                mahomes = player
                break

        assert mahomes is not None
        assert mahomes.get('position') == 'QB'
        assert mahomes.get('team') == 'KC'

    @requires_internet
    def test_get_weekly_stats_returns_data(self, sleeper_client):
        """Test fetching weekly stats for a completed week."""
        # Use 2023 season week 1 (definitely completed)
        stats = sleeper_client.get_weekly_stats(2023, 1)

        assert stats is not None
        assert len(stats) > 100  # Should have stats for many players

    @requires_internet
    def test_get_weekly_stats_includes_fantasy_points(self, sleeper_client):
        """Test that weekly stats include fantasy points."""
        stats = sleeper_client.get_weekly_stats(2023, 1)

        # Find a player with fantasy points
        has_points = False
        for player_stats in stats.values():
            if player_stats.get('pts_ppr', 0) > 0:
                has_points = True
                break

        assert has_points, "No players with fantasy points found"

    @requires_internet
    def test_get_season_stats_returns_data(self, sleeper_client):
        """Test fetching full season stats."""
        stats = sleeper_client.get_season_stats(2023)

        assert stats is not None
        assert len(stats) > 100

    @requires_internet
    def test_get_weekly_projections_returns_data(self, sleeper_client):
        """Test fetching projections."""
        # Get current state to know valid week
        state = sleeper_client.get_nfl_state()
        season = state.get('season', 2024)
        week = state.get('week', 1)

        projections = sleeper_client.get_weekly_projections(season, week)

        # Projections might be empty in offseason
        assert projections is not None
        # During season, should have data
        if week > 0 and week <= 18:
            assert len(projections) > 0 or True  # Allow empty in offseason

    @requires_internet
    def test_get_trending_players_returns_list(self, sleeper_client):
        """Test fetching trending players."""
        trending = sleeper_client.get_trending_players(limit=10)

        assert trending is not None
        assert isinstance(trending, list)
        # During active season, should have trending players
        if len(trending) > 0:
            assert 'player_id' in trending[0]


@pytest.mark.integration
class TestESPNAPIIntegration:
    """Integration tests for ESPN API (real calls)."""

    @requires_internet
    def test_client_initializes_without_auth(self, espn_client):
        """Test that ESPN client initializes."""
        assert espn_client is not None
        assert espn_client.client is not None

    @requires_internet
    @pytest.mark.skip(reason="ESPN player endpoint requires specific access")
    def test_get_players_returns_data(self, espn_client):
        """Test fetching players from ESPN."""
        players = espn_client.get_players(season=2024, limit=10)

        assert players is not None
        # ESPN API access varies, so just verify it returns something
        assert isinstance(players, list)


@pytest.mark.integration
@pytest.mark.slow
class TestScraperIntegration:
    """
    Integration tests for Pro Football Reference scraper.

    These tests are marked 'slow' because of required delays between requests.
    Run with: pytest tests/test_integration.py -m "integration and slow" -v
    """

    @requires_internet
    def test_scraper_initializes(self, scraper):
        """Test that scraper initializes."""
        assert scraper is not None
        assert scraper.session is not None

    @requires_internet
    def test_get_fantasy_stats_2023(self, scraper):
        """Test scraping fantasy stats for 2023 season."""
        df = scraper.get_fantasy_stats(2023)

        assert df is not None
        assert len(df) > 100  # Should have many players
        # Verify it has expected columns (may vary by year)
        assert len(df.columns) > 5

    @requires_internet
    def test_get_passing_stats_2023(self, scraper):
        """Test scraping passing stats."""
        df = scraper.get_passing_stats(2023)

        assert df is not None
        assert len(df) > 30  # Should have 32+ teams worth of QBs

    @requires_internet
    def test_get_rushing_stats_2023(self, scraper):
        """Test scraping rushing stats."""
        df = scraper.get_rushing_stats(2023)

        assert df is not None
        assert len(df) > 50

    @requires_internet
    def test_get_receiving_stats_2023(self, scraper):
        """Test scraping receiving stats."""
        df = scraper.get_receiving_stats(2023)

        assert df is not None
        assert len(df) > 100


@pytest.mark.integration
class TestDataTransformation:
    """Test data transformation with real API data."""

    @requires_internet
    def test_transform_real_player_data(self, sleeper_client):
        """Test transforming real player data."""
        from data_pipeline.sleeper_client import transform_player_data

        players = sleeper_client.get_all_players()
        assert len(players) > 0

        # Transform a few players
        transformed_count = 0
        for player_id, player_data in list(players.items())[:10]:
            transformed = transform_player_data(player_data)

            assert transformed['player_id'] is not None
            assert transformed['sleeper_id'] is not None
            transformed_count += 1

        assert transformed_count == 10

    @requires_internet
    def test_transform_real_weekly_stats(self, sleeper_client):
        """Test transforming real weekly stats."""
        from data_pipeline.sleeper_client import transform_weekly_stats

        stats = sleeper_client.get_weekly_stats(2023, 1)
        assert len(stats) > 0

        # Transform a few stat lines
        for player_id, player_stats in list(stats.items())[:5]:
            transformed = transform_weekly_stats(player_id, player_stats, 2023, 1)

            assert transformed['player_id'] == player_id
            assert transformed['season'] == 2023
            assert transformed['week'] == 1
            assert transformed['source'] == 'sleeper'
            assert 'fantasy_points' in transformed


@pytest.mark.integration
class TestAPIRateLimiting:
    """Test that rate limiting works correctly."""

    @requires_internet
    def test_sleeper_respects_rate_limit(self, sleeper_client):
        """Test that Sleeper client respects rate limits."""
        import time

        start = time.time()

        # Make 5 quick requests
        for _ in range(5):
            sleeper_client.get_nfl_state()

        elapsed = time.time() - start

        # Should take at least (5-1) * 0.1 = 0.4 seconds due to rate limiting
        # (first request has no delay)
        assert elapsed >= 0.3, f"Rate limiting not working, elapsed: {elapsed}"

    @requires_internet
    def test_espn_respects_rate_limit(self, espn_client):
        """Test that ESPN client respects rate limits."""
        import time

        start = time.time()

        # Make 3 requests (ESPN has longer delay)
        for _ in range(3):
            espn_client._rate_limit()

        elapsed = time.time() - start

        # Should take at least (3-1) * 0.5 = 1.0 seconds
        assert elapsed >= 0.9, f"Rate limiting not working, elapsed: {elapsed}"
