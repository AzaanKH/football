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
        cursor.fetchall.return_value = [(pid,) for pid in sample_weekly_stats]

        result = mocks['orchestrator'].sync_weekly_stats(2024, 10)

        assert result['processed'] == 2
        mocks['sleeper'].get_weekly_stats.assert_called_once_with(2024, 10)

    @pytest.mark.unit
    def test_sync_weekly_stats_skips_untracked_players(self, mock_orchestrator, sample_weekly_stats):
        """Sleeper returns team defenses and IDP rows; only tracked players are stored."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_stats.return_value = {
            **sample_weekly_stats,
            'KC': {'pts_ppr': 9.0},
            '99999': {'pts_ppr': 1.0},
        }
        cursor = mocks['db']['cursor']
        cursor.fetchall.return_value = [(pid,) for pid in sample_weekly_stats]

        result = mocks['orchestrator'].sync_weekly_stats(2024, 10)

        stored_ids = {row['player_id'] for row in self._stat_inserts(cursor)}
        assert stored_ids == set(sample_weekly_stats)
        assert result['skipped_unknown'] == 2
        assert result['processed'] == len(sample_weekly_stats)

    @pytest.mark.unit
    def test_sync_weekly_stats_merges_game_context(self, mock_orchestrator, sample_weekly_stats):
        """Opponent, date and snaps come from the per-game feed; missing context stays NULL."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_stats.return_value = sample_weekly_stats
        with_context, without = list(sample_weekly_stats)
        mocks['sleeper'].get_weekly_game_context.return_value = {
            with_context: {'team': 'SF', 'opponent': 'TB', 'game_date': '2024-11-10',
                           'off_snaps': 56, 'team_off_snaps': 70},
        }
        cursor = mocks['db']['cursor']
        cursor.fetchall.return_value = [(pid,) for pid in sample_weekly_stats]

        result = mocks['orchestrator'].sync_weekly_stats(2024, 10)

        rows = {row['player_id']: row for row in self._stat_inserts(cursor)}
        assert rows[with_context]['opponent'] == 'TB' and rows[with_context]['off_snaps'] == 56
        assert rows[without]['opponent'] is None and rows[without]['team_off_snaps'] is None
        assert result['with_context'] == 1

    @staticmethod
    def _stat_inserts(cursor):
        """Row dicts passed to player_weekly_stats INSERTs."""
        return [
            c.args[1] for c in cursor.execute.call_args_list
            if len(c.args) > 1 and 'INSERT INTO player_weekly_stats' in c.args[0]
        ]

    @pytest.mark.unit
    def test_sync_weekly_stats_fallback_off_by_default(self, mock_orchestrator):
        """PFR blocks automated requests, so scraping must be opt-in."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_stats.return_value = {}

        with pytest.raises(Exception, match="No stats data available"):
            mocks['orchestrator'].sync_weekly_stats(2024, 10)

        mocks['scraper'].get_weekly_fantasy_stats.assert_not_called()

    @pytest.mark.unit
    def test_sync_weekly_stats_fallback_to_scraper(self, mock_orchestrator):
        """Scraped stats keep their values, are labeled 'scraped', and use Sleeper IDs."""
        import pandas as pd
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_stats.return_value = {}
        mocks['scraper'].get_weekly_fantasy_stats.return_value = pd.DataFrame({
            'Unnamed: 1_level_0_Player': ['Saquon Barkley', 'Unknown Rookie'],
            'Unnamed: 2_level_0_Tm': ['PHI', 'NYJ'],
            'Unnamed: 3_level_0_FantPos': ['RB', 'WR'],
            'Rushing_Att': [26, 0],
            'Rushing_Yds': [159, 0],
            'Rushing_TD': [2, 0],
            'Receiving_Rec': [3, 4],
            'Receiving_Yds': [24, 51],
            'Fantasy_PPR': [33.3, 9.1],
        })
        cursor = mocks['db']['cursor']
        cursor.fetchall.return_value = [('4866', 'Saquon Barkley', 'RB', 'PHI')]
        cursor.fetchone.return_value = (True,)

        result = mocks['orchestrator'].sync_weekly_stats(2024, 10, use_fallback=True)

        rows = self._stat_inserts(cursor)
        assert len(rows) == 1
        row = rows[0]
        assert row['player_id'] == '4866'
        assert row['source'] == 'scraped'
        assert row['week'] == 10
        assert row['rushing_yards'] == 159
        assert row['rushing_attempts'] == 26
        assert row['receptions'] == 3
        assert row['fantasy_points_ppr'] == 33.3
        assert result['unmatched'] == 1
        assert result['processed'] == 1

    @pytest.mark.unit
    def test_sync_weekly_stats_scraper_format_change_fails_loudly(self, mock_orchestrator):
        """A scraped table without PPR points must fail, not store zeros."""
        import pandas as pd
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_stats.return_value = {}
        mocks['scraper'].get_weekly_fantasy_stats.return_value = pd.DataFrame({
            'Player': ['Test Player'], 'Tm': ['TST'], 'FantPt': [100.0]
        })

        with pytest.raises(ValueError, match='fantasy_points_ppr'):
            mocks['orchestrator'].sync_weekly_stats(2024, 10, use_fallback=True)

        assert self._stat_inserts(mocks['db']['cursor']) == []

    @pytest.mark.unit
    def test_sync_weekly_stats_upsert_refreshes_every_column(self, mock_orchestrator,
                                                             sample_weekly_stats):
        """Re-syncing must update all stat columns and the source label."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_stats.return_value = sample_weekly_stats
        cursor = mocks['db']['cursor']
        cursor.fetchall.return_value = [(pid,) for pid in sample_weekly_stats]
        cursor.fetchone.return_value = (False,)

        result = mocks['orchestrator'].sync_weekly_stats(2024, 10)

        sql = next(
            c.args[0] for c in cursor.execute.call_args_list
            if 'INSERT INTO player_weekly_stats' in c.args[0]
        )
        for column in ('rushing_attempts', 'interceptions', 'fumbles_lost', 'source'):
            assert f'{column} = EXCLUDED.{column}' in sql
        assert result['updated'] == result['processed']
        assert result['inserted'] == 0

    @pytest.mark.unit
    def test_sync_weekly_stats_keeps_context_when_enrichment_fails(self, mock_orchestrator,
                                                                   sample_weekly_stats):
        """A failed game-context request sends NULLs; the upsert must not store them over context."""
        mocks = mock_orchestrator
        mocks['sleeper'].get_weekly_stats.return_value = sample_weekly_stats
        mocks['sleeper'].get_weekly_game_context.return_value = {}
        cursor = mocks['db']['cursor']
        cursor.fetchall.return_value = [(pid,) for pid in sample_weekly_stats]
        cursor.fetchone.return_value = (False,)

        mocks['orchestrator'].sync_weekly_stats(2024, 10)

        sql = next(
            c.args[0] for c in cursor.execute.call_args_list
            if 'INSERT INTO player_weekly_stats' in c.args[0]
        )
        for column in ('team', 'opponent', 'game_date', 'off_snaps', 'team_off_snaps'):
            assert f'{column} = COALESCE(EXCLUDED.{column}, player_weekly_stats.{column})' in sql
        assert all(row['team'] is None for row in self._stat_inserts(cursor))

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
        mocks['sleeper'].get_weekly_projections.return_value = {
            **sample_projections, 'KC': {'pts_ppr': 8.0},  # team defense: untracked
        }
        cursor = mocks['db']['cursor']
        cursor.fetchall.return_value = [(pid,) for pid in sample_projections]
        cursor.fetchone.return_value = (True,)

        result = mocks['orchestrator'].sync_projections(2024, 10)

        assert result['processed'] == 2
        assert result['inserted'] == 2
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
        cursor.fetchall.return_value = [(pid,) for pid in sample_weekly_stats]

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
        cursor.fetchall.return_value = [(pid,) for pid in sample_weekly_stats]

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
