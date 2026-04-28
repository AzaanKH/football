"""
Unit Tests for Data Pipeline Orchestrator

These tests use mocked API clients and database connections to test
the orchestrator logic without external dependencies.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from contextlib import contextmanager

from data_pipeline.orchestrator import DataOrchestrator


class TestDataOrchestratorUnit:
    """Unit tests for DataOrchestrator with mocked dependencies."""

    @pytest.fixture
    def mock_orchestrator(self, mock_db_connection):
        """Create orchestrator with mocked clients and DB."""
        with patch('data_pipeline.orchestrator.SleeperClient') as sleeper_mock, \
             patch('data_pipeline.orchestrator.ESPNClient') as espn_mock, \
             patch('data_pipeline.orchestrator.ProFootballReferenceScraper') as scraper_mock:

            # Setup mock clients
            sleeper_instance = MagicMock()
            espn_instance = MagicMock()
            scraper_instance = MagicMock()

            sleeper_mock.return_value = sleeper_instance
            espn_mock.return_value = espn_instance
            scraper_mock.return_value = scraper_instance

            orchestrator = DataOrchestrator(
                database_url='postgresql://test:test@localhost:5432/test'
            )

            # Replace the lazy-loaded clients
            orchestrator._sleeper_client = sleeper_instance
            orchestrator._espn_client = espn_instance
            orchestrator._scraper = scraper_instance

            yield {
                'orchestrator': orchestrator,
                'sleeper': sleeper_instance,
                'espn': espn_instance,
                'scraper': scraper_instance,
                'db': mock_db_connection
            }

            orchestrator.close()

    @pytest.mark.unit
    def test_init_with_default_database_url(self):
        """Test initialization with default database URL."""
        with patch.dict('os.environ', {}, clear=True):
            orchestrator = DataOrchestrator()
            assert 'localhost:5432' in orchestrator.database_url
            orchestrator.close()

    @pytest.mark.unit
    def test_init_with_custom_database_url(self):
        """Test initialization with custom database URL."""
        custom_url = 'postgresql://user:pass@myhost:5433/mydb'
        orchestrator = DataOrchestrator(database_url=custom_url)
        assert orchestrator.database_url == custom_url
        orchestrator.close()

    @pytest.mark.unit
    def test_init_from_env_variable(self):
        """Test initialization from DATABASE_URL environment variable."""
        env_url = 'postgresql://env:pass@envhost:5432/envdb'
        with patch.dict('os.environ', {'DATABASE_URL': env_url}):
            orchestrator = DataOrchestrator()
            assert orchestrator.database_url == env_url
            orchestrator.close()

    @pytest.mark.unit
    def test_lazy_loading_sleeper_client(self, mock_db_connection):
        """Test that Sleeper client is lazily loaded."""
        with patch('data_pipeline.orchestrator.SleeperClient') as mock:
            orchestrator = DataOrchestrator()

            # Client not created yet
            mock.assert_not_called()

            # Access the property
            _ = orchestrator.sleeper

            # Now it's created
            mock.assert_called_once()
            orchestrator.close()

    @pytest.mark.unit
    def test_sync_players_success(self, mock_orchestrator, sample_sleeper_players):
        """Test successful player sync."""
        mocks = mock_orchestrator
        orch = mocks['orchestrator']
        mocks['sleeper'].get_all_players.return_value = sample_sleeper_players

        # Mock DB cursor to track operations
        cursor = mocks['db']['cursor']
        cursor.rowcount = 1  # Simulate insert

        result = orch.sync_players()

        assert result['processed'] == 3  # Only fantasy-relevant positions
        mocks['sleeper'].get_all_players.assert_called_once()

    @pytest.mark.unit
    def test_sync_players_filters_non_fantasy_positions(self, mock_orchestrator):
        """Test that non-fantasy positions are filtered."""
        mocks = mock_orchestrator
        players = {
            '1': {'player_id': '1', 'position': 'QB', 'full_name': 'Test QB'},
            '2': {'player_id': '2', 'position': 'OL', 'full_name': 'Test OL'},  # Filtered
            '3': {'player_id': '3', 'position': 'LB', 'full_name': 'Test LB'},  # Filtered
            '4': {'player_id': '4', 'position': 'RB', 'full_name': 'Test RB'},
        }
        mocks['sleeper'].get_all_players.return_value = players
        cursor = mocks['db']['cursor']
        cursor.rowcount = 1

        result = mocks['orchestrator'].sync_players()

        # Only QB and RB should be processed
        assert result['processed'] == 2

    @pytest.mark.unit
    def test_sync_players_api_failure(self, mock_orchestrator):
        """Test handling of API failure during player sync."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_all_players.return_value = {}  # Empty = failure

        with pytest.raises(Exception, match="Failed to fetch players"):
            mocks['orchestrator'].sync_players()

    @pytest.mark.unit
    def test_sync_weekly_stats_success(self, mock_orchestrator, sample_weekly_stats):
        """Test successful weekly stats sync."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_stats.return_value = sample_weekly_stats
        cursor = mocks['db']['cursor']
        cursor.rowcount = 1

        result = mocks['orchestrator'].sync_weekly_stats(2024, 10)

        assert result['processed'] == 2
        mocks['sleeper'].get_weekly_stats.assert_called_once_with(2024, 10)

    @pytest.mark.unit
    def test_sync_weekly_stats_fallback_to_scraper(self, mock_orchestrator):
        """Test fallback to scraper when API fails."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_stats.return_value = {}  # API fails

        # Mock scraper response
        import pandas as pd
        scraper_df = pd.DataFrame({
            'Player': ['Test Player'],
            'Tm': ['TST'],
            'FantPt': [100.0]
        })
        mocks['scraper'].get_weekly_fantasy_stats.return_value = scraper_df
        cursor = mocks['db']['cursor']
        cursor.rowcount = 1

        result = mocks['orchestrator'].sync_weekly_stats(2024, 10, use_fallback=True)

        mocks['scraper'].get_weekly_fantasy_stats.assert_called_once_with(2024, 10)

    @pytest.mark.unit
    def test_sync_weekly_stats_no_fallback(self, mock_orchestrator):
        """Test that fallback is not used when disabled."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_stats.return_value = {}  # API fails

        with pytest.raises(Exception, match="No stats data available"):
            mocks['orchestrator'].sync_weekly_stats(2024, 10, use_fallback=False)

        mocks['scraper'].get_weekly_fantasy_stats.assert_not_called()

    @pytest.mark.unit
    def test_sync_projections_success(self, mock_orchestrator, sample_projections):
        """Test successful projections sync."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_projections.return_value = sample_projections
        cursor = mocks['db']['cursor']
        cursor.rowcount = 1

        result = mocks['orchestrator'].sync_projections(2024, 10)

        assert result['processed'] == 2
        mocks['sleeper'].get_weekly_projections.assert_called_once_with(2024, 10)

    @pytest.mark.unit
    def test_sync_projections_failure(self, mock_orchestrator):
        """Test handling of projections API failure."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_projections.return_value = {}

        with pytest.raises(Exception, match="No projections data available"):
            mocks['orchestrator'].sync_projections(2024, 10)

    @pytest.mark.unit
    def test_sync_matchups_success(self, mock_orchestrator):
        """Test successful matchup sync."""
        mocks = mock_orchestrator
        mocks['espn'].get_week_matchups.return_value = [
            {'team': 'KC', 'opponent': 'BUF', 'is_home': True, 'game_date': None, 'source': 'espn'},
            {'team': 'BUF', 'opponent': 'KC', 'is_home': False, 'game_date': None, 'source': 'espn'},
        ]
        cursor = mocks['db']['cursor']
        cursor.rowcount = 1

        result = mocks['orchestrator'].sync_matchups(2024, 10)

        assert result['processed'] == 2
        mocks['espn'].get_week_matchups.assert_called_once_with(2024, 10)

    @pytest.mark.unit
    def test_get_current_season_info_success(self, mock_orchestrator, sample_nfl_state):
        """Test getting current season info."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_nfl_state.return_value = sample_nfl_state

        result = mocks['orchestrator'].get_current_season_info()

        assert result['season'] == 2024
        assert result['week'] == 10

    @pytest.mark.unit
    def test_get_current_season_info_api_failure(self, mock_orchestrator):
        """Test fallback when NFL state API fails."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_nfl_state.return_value = None

        result = mocks['orchestrator'].get_current_season_info()

        # Should fall back to current year and week 1
        from datetime import datetime
        assert result['season'] == datetime.now().year
        assert result['week'] == 1

    @pytest.mark.unit
    def test_full_sync_success(self, mock_orchestrator, sample_sleeper_players,
                               sample_weekly_stats, sample_projections, sample_nfl_state):
        """Test full sync runs all components."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_all_players.return_value = sample_sleeper_players
        mocks['sleeper'].get_weekly_stats.return_value = sample_weekly_stats
        mocks['sleeper'].get_weekly_projections.return_value = sample_projections
        mocks['espn'].get_week_matchups.return_value = [
            {'team': 'KC', 'opponent': 'BUF', 'is_home': True, 'game_date': None, 'source': 'espn'},
            {'team': 'BUF', 'opponent': 'KC', 'is_home': False, 'game_date': None, 'source': 'espn'},
        ]
        mocks['sleeper'].get_nfl_state.return_value = sample_nfl_state
        cursor = mocks['db']['cursor']
        cursor.rowcount = 1

        result = mocks['orchestrator'].full_sync(season=2024, current_week=10)

        assert result['players'] is not None
        assert result['matchups'] is not None
        assert result['projections'] is not None
        assert len(result['errors']) == 0

    @pytest.mark.unit
    def test_full_sync_with_historical(self, mock_orchestrator, sample_sleeper_players,
                                       sample_weekly_stats, sample_projections):
        """Test full sync with historical data."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_all_players.return_value = sample_sleeper_players
        mocks['sleeper'].get_weekly_stats.return_value = sample_weekly_stats
        mocks['sleeper'].get_weekly_projections.return_value = sample_projections
        mocks['espn'].get_week_matchups.return_value = [
            {'team': 'KC', 'opponent': 'BUF', 'is_home': True, 'game_date': None, 'source': 'espn'},
            {'team': 'BUF', 'opponent': 'KC', 'is_home': False, 'game_date': None, 'source': 'espn'},
        ]
        cursor = mocks['db']['cursor']
        cursor.rowcount = 1

        result = mocks['orchestrator'].full_sync(
            season=2024, current_week=5, sync_historical=True
        )

        # Should sync finalized weeks 1-4 and prep week 5 context
        assert len(result['stats']) == 4
        assert result['matchups'] is not None

    @pytest.mark.unit
    def test_full_sync_partial_failure(self, mock_orchestrator, sample_sleeper_players):
        """Test full sync handles partial failures gracefully."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_all_players.return_value = sample_sleeper_players
        mocks['sleeper'].get_weekly_stats.side_effect = Exception("Stats API down")
        mocks['sleeper'].get_weekly_projections.return_value = {}
        mocks['espn'].get_week_matchups.return_value = []
        cursor = mocks['db']['cursor']
        cursor.rowcount = 1

        result = mocks['orchestrator'].full_sync(season=2024, current_week=2)

        # Players should succeed, stats and projections should fail
        assert result['players'] is not None
        assert len(result['errors']) > 0

    @pytest.mark.unit
    def test_close_closes_all_clients(self, mock_orchestrator):
        """Test that close() closes all client connections."""
        mocks = mock_orchestrator

        mocks['orchestrator'].close()

        mocks['sleeper'].close.assert_called_once()
        mocks['espn'].close.assert_called_once()
        mocks['scraper'].close.assert_called_once()

    @pytest.mark.unit
    def test_context_manager(self, mock_db_connection):
        """Test context manager properly closes orchestrator."""
        with patch('data_pipeline.orchestrator.SleeperClient') as sleeper_mock, \
             patch('data_pipeline.orchestrator.ESPNClient'), \
             patch('data_pipeline.orchestrator.ProFootballReferenceScraper'):

            sleeper_instance = MagicMock()
            sleeper_mock.return_value = sleeper_instance

            with DataOrchestrator() as orch:
                # Access to create client
                _ = orch.sleeper

            sleeper_instance.close.assert_called_once()


class TestIngestionLogging:
    """Tests for ingestion logging functionality."""

    @pytest.fixture
    def mock_orchestrator_with_logging(self, mock_db_connection):
        """Create orchestrator for testing logging."""
        with patch('data_pipeline.orchestrator.SleeperClient') as sleeper_mock:
            sleeper_instance = MagicMock()
            sleeper_mock.return_value = sleeper_instance

            orchestrator = DataOrchestrator()
            orchestrator._sleeper_client = sleeper_instance

            # Setup cursor to return log IDs
            mock_db_connection['cursor'].fetchone.return_value = (1,)

            yield {
                'orchestrator': orchestrator,
                'sleeper': sleeper_instance,
                'db': mock_db_connection
            }

            orchestrator.close()

    @pytest.mark.unit
    def test_log_ingestion_creates_entry(self, mock_orchestrator_with_logging):
        """Test that ingestion logging creates database entry."""
        mocks = mock_orchestrator_with_logging
        cursor = mocks['db']['cursor']

        # Make a sync call that triggers logging
        mocks['sleeper'].get_all_players.return_value = {}

        try:
            mocks['orchestrator'].sync_players()
        except Exception:
            pass

        # Verify INSERT was called for ingestion_log
        insert_calls = [
            call for call in cursor.execute.call_args_list
            if 'ingestion_log' in str(call)
        ]
        assert len(insert_calls) > 0
