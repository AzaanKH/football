"""
Unit Tests for Sleeper API Client

These tests use mocked HTTP responses to test the SleeperClient
without making actual API calls.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import httpx

from data_pipeline.sleeper_client import (
    SleeperClient,
    transform_player_data,
    transform_weekly_stats
)


class TestSleeperClientUnit:
    """Unit tests for SleeperClient with mocked HTTP."""

    @pytest.fixture
    def mock_client(self):
        """Create a SleeperClient with mocked httpx.Client."""
        with patch('data_pipeline.sleeper_client.httpx.Client') as mock:
            client_instance = MagicMock()
            mock.return_value = client_instance
            sleeper = SleeperClient(timeout=10.0)
            sleeper.client = client_instance
            yield sleeper, client_instance
            sleeper.close()

    @pytest.mark.unit
    def test_init_creates_client_with_correct_headers(self):
        """Test that client is initialized with correct headers."""
        with patch('data_pipeline.sleeper_client.httpx.Client') as mock:
            SleeperClient(timeout=15.0)

            mock.assert_called_once()
            call_kwargs = mock.call_args[1]
            assert call_kwargs['timeout'] == 15.0
            assert 'User-Agent' in call_kwargs['headers']
            assert 'Accept' in call_kwargs['headers']

    @pytest.mark.unit
    def test_get_all_players_success(self, mock_client, sample_sleeper_players):
        """Test successful player fetch."""
        client, http_mock = mock_client

        # Setup mock response
        response_mock = MagicMock()
        response_mock.json.return_value = sample_sleeper_players
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_all_players()

        assert result == sample_sleeper_players
        http_mock.get.assert_called_once()
        assert '/players/nfl' in http_mock.get.call_args[0][0]

    @pytest.mark.unit
    def test_get_all_players_http_error(self, mock_client):
        """Test handling of HTTP errors."""
        client, http_mock = mock_client

        http_mock.get.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500)
        )

        result = client.get_all_players()

        assert result == {}

    @pytest.mark.unit
    def test_get_all_players_request_error(self, mock_client):
        """Test handling of network errors."""
        client, http_mock = mock_client

        http_mock.get.side_effect = httpx.RequestError("Connection failed")

        result = client.get_all_players()

        assert result == {}

    @pytest.mark.unit
    def test_get_weekly_stats_success(self, mock_client, sample_weekly_stats):
        """Test fetching weekly stats."""
        client, http_mock = mock_client

        response_mock = MagicMock()
        response_mock.json.return_value = sample_weekly_stats
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_weekly_stats(2024, 10)

        assert result == sample_weekly_stats
        assert '/stats/nfl/regular/2024/10' in http_mock.get.call_args[0][0]

    @pytest.mark.unit
    def test_get_weekly_stats_empty(self, mock_client):
        """Test handling of empty stats response."""
        client, http_mock = mock_client

        response_mock = MagicMock()
        response_mock.json.return_value = None
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_weekly_stats(2024, 10)

        assert result == {}

    @pytest.mark.unit
    def test_get_weekly_projections_success(self, mock_client, sample_projections):
        """Test fetching weekly projections."""
        client, http_mock = mock_client

        response_mock = MagicMock()
        response_mock.json.return_value = sample_projections
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_weekly_projections(2024, 10)

        assert result == sample_projections
        assert '/projections/nfl/regular/2024/10' in http_mock.get.call_args[0][0]

    @pytest.mark.unit
    def test_get_nfl_state_success(self, mock_client, sample_nfl_state):
        """Test fetching NFL state."""
        client, http_mock = mock_client

        response_mock = MagicMock()
        response_mock.json.return_value = sample_nfl_state
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_nfl_state()

        assert result == sample_nfl_state
        assert result['season'] == 2024
        assert result['week'] == 10

    @pytest.mark.unit
    def test_get_trending_players_success(self, mock_client):
        """Test fetching trending players."""
        client, http_mock = mock_client

        trending_data = [
            {"player_id": "4046", "count": 1500},
            {"player_id": "5850", "count": 1200}
        ]

        response_mock = MagicMock()
        response_mock.json.return_value = trending_data
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_trending_players(limit=5)

        assert len(result) == 2
        assert result[0]['player_id'] == '4046'

    @pytest.mark.unit
    def test_rate_limiting(self, mock_client):
        """Test that rate limiting delays requests."""
        client, http_mock = mock_client

        response_mock = MagicMock()
        response_mock.json.return_value = {}
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        import time
        start = time.time()

        # Make two quick requests
        client._rate_limit()
        client._rate_limit()

        elapsed = time.time() - start
        # Should have waited at least min_request_interval (0.1s)
        assert elapsed >= client._min_request_interval * 0.9  # 10% tolerance

    @pytest.mark.unit
    def test_context_manager(self):
        """Test that context manager properly closes client."""
        with patch('data_pipeline.sleeper_client.httpx.Client') as mock:
            client_instance = MagicMock()
            mock.return_value = client_instance

            with SleeperClient() as client:
                pass

            client_instance.close.assert_called_once()


class TestTransformPlayerData:
    """Tests for player data transformation."""

    @pytest.mark.unit
    def test_transform_complete_player(self, sample_sleeper_player):
        """Test transforming a complete player record."""
        result = transform_player_data(sample_sleeper_player)

        assert result['player_id'] == '4046'
        assert result['sleeper_id'] == '4046'
        assert result['full_name'] == 'Patrick Mahomes'
        assert result['position'] == 'QB'
        assert result['team'] == 'KC'
        assert result['age'] == 28
        assert result['college'] == 'Texas Tech'

    @pytest.mark.unit
    def test_transform_player_with_missing_fields(self):
        """Test transforming player with missing optional fields."""
        partial_player = {
            'player_id': '123',
            'full_name': 'Test Player',
            'position': 'WR'
        }

        result = transform_player_data(partial_player)

        assert result['player_id'] == '123'
        assert result['full_name'] == 'Test Player'
        assert result['position'] == 'WR'
        assert result['team'] is None
        assert result['injury_status'] is None
        assert result['fantasy_positions'] == []

    @pytest.mark.unit
    def test_transform_player_empty_input(self):
        """Test transforming empty player data."""
        result = transform_player_data({})

        assert result['player_id'] is None
        assert result['full_name'] == ''
        assert result['fantasy_positions'] == []


class TestTransformWeeklyStats:
    """Tests for weekly stats transformation."""

    @pytest.mark.unit
    def test_transform_qb_stats(self):
        """Test transforming QB weekly stats."""
        stats = {
            'pts_std': 25.5,
            'pts_ppr': 25.5,
            'pass_att': 35,
            'pass_cmp': 28,
            'pass_yd': 312,
            'pass_td': 3,
            'pass_int': 1,
            'rush_att': 4,
            'rush_yd': 28
        }

        result = transform_weekly_stats('4046', stats, 2024, 10)

        assert result['player_id'] == '4046'
        assert result['season'] == 2024
        assert result['week'] == 10
        assert result['fantasy_points'] == 25.5
        assert result['passing_yards'] == 312
        assert result['passing_tds'] == 3
        assert result['interceptions'] == 1
        assert result['rushing_yards'] == 28
        assert result['source'] == 'sleeper'

    @pytest.mark.unit
    def test_transform_rb_stats(self):
        """Test transforming RB weekly stats."""
        stats = {
            'pts_std': 18.2,
            'pts_ppr': 22.2,
            'rush_att': 22,
            'rush_yd': 112,
            'rush_td': 1,
            'rec_tgt': 6,
            'rec': 4,
            'rec_yd': 30
        }

        result = transform_weekly_stats('5850', stats, 2024, 10)

        assert result['fantasy_points'] == 18.2
        assert result['fantasy_points_ppr'] == 22.2
        assert result['rushing_yards'] == 112
        assert result['rushing_tds'] == 1
        assert result['receptions'] == 4
        assert result['targets'] == 6
        assert result['receiving_yards'] == 30

    @pytest.mark.unit
    def test_transform_stats_with_missing_fields(self):
        """Test that missing stats default to 0."""
        stats = {'pts_std': 5.0}

        result = transform_weekly_stats('123', stats, 2024, 1)

        assert result['fantasy_points'] == 5.0
        assert result['passing_yards'] == 0
        assert result['rushing_yards'] == 0
        assert result['receptions'] == 0
        assert result['fumbles'] == 0

    @pytest.mark.unit
    def test_transform_empty_stats(self):
        """Test transforming empty stats."""
        result = transform_weekly_stats('123', {}, 2024, 1)

        assert result['player_id'] == '123'
        assert result['season'] == 2024
        assert result['week'] == 1
        assert result['fantasy_points'] == 0
        assert result['source'] == 'sleeper'
